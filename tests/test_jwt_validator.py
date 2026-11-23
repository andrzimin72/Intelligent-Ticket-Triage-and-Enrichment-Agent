"""
Tests for Bot Framework JWT validation.
"""

import pytest
import sys
import os
import time
import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src_teams_bot'))


class TestJWTValidator:
    """Tests for JWT validation logic."""
    
    def test_extract_token_from_valid_header(self):
        """Should extract token from valid Bearer header."""
        import jwt_validator
        
        token = jwt_validator.extract_token_from_header("Bearer abc123.xyz.789")
        assert token == "abc123.xyz.789"
    
    def test_extract_token_from_lowercase_bearer(self):
        """Should handle lowercase 'bearer'."""
        import jwt_validator
        
        token = jwt_validator.extract_token_from_header("bearer abc123.xyz.789")
        assert token == "abc123.xyz.789"
    
    def test_extract_token_from_missing_header(self):
        """Should return None for missing header."""
        import jwt_validator
        
        token = jwt_validator.extract_token_from_header("")
        assert token is None
    
    def test_extract_token_from_malformed_header(self):
        """Should return None for malformed header."""
        import jwt_validator
        
        token = jwt_validator.extract_token_from_header("Basic abc123")
        assert token is None
    
    @patch('jwt_validator.requests.get')
    def test_fetch_jwks_caches_result(self, mock_get):
        """Should cache JWKS and not re-fetch within TTL."""
        import jwt_validator
        
        # Mock the metadata and JWKS responses
        mock_metadata = MagicMock()
        mock_metadata.json.return_value = {'jwks_uri': 'https://example.com/jwks'}
        mock_metadata.raise_for_status = MagicMock()
        
        mock_jwks = MagicMock()
        mock_jwks.json.return_value = {'keys': [{'kid': 'test-key', 'kty': 'RSA'}]}
        mock_jwks.raise_for_status = MagicMock()
        
        mock_get.side_effect = [mock_metadata, mock_jwks]
        
        # Clear cache
        jwt_validator._jwks_cache = {'keys': None, 'fetched_at': 0}
        
        # First call should fetch
        jwks1 = jwt_validator._fetch_jwks()
        assert mock_get.call_count == 2
        
        # Second call should use cache
        jwks2 = jwt_validator._fetch_jwks()
        assert mock_get.call_count == 2  # No additional calls
        assert jwks1 == jwks2
    
    @patch('jwt_validator.requests.get')
    def test_fetch_jwks_refreshes_after_ttl(self, mock_get):
        """Should refresh JWKS after TTL expires."""
        import jwt_validator
        
        mock_metadata = MagicMock()
        mock_metadata.json.return_value = {'jwks_uri': 'https://example.com/jwks'}
        mock_metadata.raise_for_status = MagicMock()
        
        mock_jwks = MagicMock()
        mock_jwks.json.return_value = {'keys': []}
        mock_jwks.raise_for_status = MagicMock()
        
        mock_get.side_effect = [mock_metadata, mock_jwks, mock_metadata, mock_jwks]
        
        # Clear cache
        jwt_validator._jwks_cache = {'keys': None, 'fetched_at': 0}
        
        # First fetch
        jwt_validator._fetch_jwks()
        assert mock_get.call_count == 2
        
        # Simulate cache expiration
        jwt_validator._jwks_cache['fetched_at'] = time.time() - jwt_validator.JWKS_CACHE_TTL - 1
        
        # Second fetch should refresh
        jwt_validator._fetch_jwks()
        assert mock_get.call_count == 4
    
    def test_validate_bot_framework_jwt_with_invalid_token(self):
        """Should raise JWTValidationError for invalid token."""
        import jwt_validator
        
        with pytest.raises(jwt_validator.JWTValidationError):
            jwt_validator.validate_bot_framework_jwt("invalid.token.here", "bot-app-id")
    
    @patch('jwt_validator._get_signing_key')
    @patch('jwt_validator.jwt.decode')
    def test_validate_bot_framework_jwt_with_valid_token(self, mock_decode, mock_get_key):
        """Should validate a properly signed token."""
        import jwt_validator
        
        mock_get_key.return_value = MagicMock()
        mock_decode.return_value = {
            'iss': 'https://api.botframework.com',
            'aud': 'bot-app-id-123',
            'exp': int(time.time()) + 3600,
        }
        
        payload = jwt_validator.validate_bot_framework_jwt("valid.token.here", "bot-app-id-123")
        
        assert payload['aud'] == 'bot-app-id-123'
        mock_decode.assert_called_once()
    
    @patch('jwt_validator._get_signing_key')
    @patch('jwt_validator.jwt.decode')
    def test_validate_bot_framework_jwt_with_wrong_audience(self, mock_decode, mock_get_key):
        """Should reject token with wrong audience."""
        import jwt_validator
        from jwt import InvalidAudienceError
        
        mock_get_key.return_value = MagicMock()
        mock_decode.side_effect = InvalidAudienceError("Invalid audience")
        
        with pytest.raises(jwt_validator.JWTValidationError):
            jwt_validator.validate_bot_framework_jwt("token.here", "wrong-bot-id")
    
    @patch('jwt_validator._get_signing_key')
    @patch('jwt_validator.jwt.decode')
    def test_validate_bot_framework_jwt_with_expired_token(self, mock_decode, mock_get_key):
        """Should reject expired token."""
        import jwt_validator
        from jwt import ExpiredSignatureError
        
        mock_get_key.return_value = MagicMock()
        mock_decode.side_effect = ExpiredSignatureError("Signature has expired")
        
        with pytest.raises(jwt_validator.JWTValidationError):
            jwt_validator.validate_bot_framework_jwt("expired.token.here", "bot-app-id")
    
    def test_validate_teams_request_with_jwt_missing_auth_header(self):
        """Should reject request without Authorization header."""
        import jwt_validator
        
        event = {'headers': {}}
        result = jwt_validator.validate_teams_request_with_jwt(event, "bot-app-id")
        assert result is False
    
    def test_validate_teams_request_with_jwt_malformed_auth_header(self):
        """Should reject request with malformed Authorization header."""
        import jwt_validator
        
        event = {'headers': {'authorization': 'Basic abc123'}}
        result = jwt_validator.validate_teams_request_with_jwt(event, "bot-app-id")
        assert result is False
    
    @patch('jwt_validator.validate_bot_framework_jwt')
    def test_validate_teams_request_with_jwt_valid_token(self, mock_validate):
        """Should accept request with valid JWT."""
        import jwt_validator
        
        mock_validate.return_value = {
            'iss': 'https://api.botframework.com',
            'aud': 'bot-app-id',
            'serviceurl': 'https://smba.trafficmanager.net/teams/',
        }
        
        event = {
            'headers': {'authorization': 'Bearer valid.token.here'},
            'body': json.dumps({
                'serviceUrl': 'https://smba.trafficmanager.net/teams/'
            })
        }
        
        result = jwt_validator.validate_teams_request_with_jwt(event, "bot-app-id")
        assert result is True
    
    @patch('jwt_validator.validate_bot_framework_jwt')
    def test_validate_teams_request_with_jwt_service_url_mismatch(self, mock_validate):
        """Should reject request with mismatched service URL."""
        import jwt_validator
        
        mock_validate.return_value = {
            'iss': 'https://api.botframework.com',
            'aud': 'bot-app-id',
            'serviceurl': 'https://smba.trafficmanager.net/teams/',
        }
        
        event = {
            'headers': {'authorization': 'Bearer valid.token.here'},
            'body': json.dumps({
                'serviceUrl': 'https://different.url.com/'
            })
        }
        
        result = jwt_validator.validate_teams_request_with_jwt(event, "bot-app-id")
        assert result is False