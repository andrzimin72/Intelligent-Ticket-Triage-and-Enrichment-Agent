"""Security tests: Authentication."""
import pytest
import jwt
import time
import requests


class TestAuthentication:
    """Test authentication mechanisms."""
    
    def test_jwt_validation_valid_token(self):
        """Test valid JWT token is accepted."""
        # Generate valid JWT
        payload = {
            'sub': 'test-user',
            'iat': int(time.time()),
            'exp': int(time.time()) + 3600,
            'aud': 'test-bot-app-id'
        }
        
        token = jwt.encode(payload, 'test-secret', algorithm='HS256')
        
        # Validate token
        result = jwt_validator.validate_jwt(token)
        assert result['valid'] is True
    
    def test_jwt_validation_expired_token(self):
        """Test expired JWT token is rejected."""
        payload = {
            'sub': 'test-user',
            'iat': int(time.time()) - 7200,
            'exp': int(time.time()) - 3600,  # Expired 1 hour ago
            'aud': 'test-bot-app-id'
        }
        
        token = jwt.encode(payload, 'test-secret', algorithm='HS256')
        
        result = jwt_validator.validate_jwt(token)
        assert result['valid'] is False
        assert result['reason'] == 'token_expired'
    
    def test_jwt_validation_invalid_signature(self):
        """Test JWT with invalid signature is rejected."""
        payload = {
            'sub': 'test-user',
            'iat': int(time.time()),
            'exp': int(time.time()) + 3600
        }
        
        token = jwt.encode(payload, 'wrong-secret', algorithm='HS256')
        
        result = jwt_validator.validate_jwt(token)
        assert result['valid'] is False
        assert result['reason'] == 'invalid_signature'
    
    def test_api_key_authentication(self):
        """Test API key authentication."""
        # Valid API key
        response = requests.get(
            f'{API_URL}/status',
            headers={'x-api-key': VALID_API_KEY}
        )
        assert response.status_code == 200
        
        # Invalid API key
        response = requests.get(
            f'{API_URL}/status',
            headers={'x-api-key': 'invalid-key'}
        )
        assert response.status_code == 403
        
        # Missing API key
        response = requests.get(f'{API_URL}/status')
        assert response.status_code == 403