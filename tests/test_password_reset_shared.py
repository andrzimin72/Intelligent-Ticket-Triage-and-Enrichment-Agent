"""Unit tests for password reset token generation and validation."""
import pytest
import time
import hmac
import hashlib
from unittest.mock import patch, MagicMock
from moto import mock_dynamodb
import boto3

import sys
sys.path.insert(0, 'src_identity_tools')
import password_reset_shared


@pytest.fixture
def mock_token_table():
    """Set up mock DynamoDB table for tokens."""
    with mock_dynamodb():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        table = dynamodb.create_table(
            TableName='test-password-reset-tokens',
            KeySchema=[{'AttributeName': 'token', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'token', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST'
        )
        yield table


def test_generate_reset_token_format(mock_token_table):
    """Test that generated tokens have correct format."""
    with patch.object(password_reset_shared, 'TABLE_NAME', 'test-password-reset-tokens'), \
         patch.object(password_reset_shared, 'SIGNING_KEY', 'test-key'):
        
        token = password_reset_shared.generate_reset_token(
            user_aad_id='user-123',
            tenant_id='test-tenant'
        )
    
    # Token should be in format: token:signature
    assert ':' in token
    parts = token.split(':')
    assert len(parts) == 2
    assert len(parts[0]) >= 32  # 256-bit token
    assert len(parts[1]) == 64  # SHA-256 hex signature


def test_validate_reset_token_success(mock_token_table):
    """Test successful token validation."""
    with patch.object(password_reset_shared, 'TABLE_NAME', 'test-password-reset-tokens'), \
         patch.object(password_reset_shared, 'SIGNING_KEY', 'test-key'):
        
        # Generate token
        token = password_reset_shared.generate_reset_token(
            user_aad_id='user-123',
            tenant_id='test-tenant'
        )
        
        # Validate token
        result = password_reset_shared.validate_reset_token(
            token=token,
            user_aad_id='user-123',
            tenant_id='test-tenant'
        )
    
    assert result['valid'] is True


def test_validate_reset_token_wrong_user(mock_token_table):
    """Test token validation with wrong user ID."""
    with patch.object(password_reset_shared, 'TABLE_NAME', 'test-password-reset-tokens'), \
         patch.object(password_reset_shared, 'SIGNING_KEY', 'test-key'):
        
        token = password_reset_shared.generate_reset_token(
            user_aad_id='user-123',
            tenant_id='test-tenant'
        )
        
        result = password_reset_shared.validate_reset_token(
            token=token,
            user_aad_id='user-456',  # Wrong user
            tenant_id='test-tenant'
        )
    
    assert result['valid'] is False
    assert result['reason'] == 'invalid_signature'


def test_validate_reset_token_expired(mock_token_table):
    """Test token validation with expired token."""
    with patch.object(password_reset_shared, 'TABLE_NAME', 'test-password-reset-tokens'), \
         patch.object(password_reset_shared, 'SIGNING_KEY', 'test-key'), \
         patch.object(password_reset_shared, 'TOKEN_TTL_SECONDS', 1):
        
        token = password_reset_shared.generate_reset_token(
            user_aad_id='user-123',
            tenant_id='test-tenant'
        )
        
        # Wait for token to expire
        time.sleep(2)
        
        result = password_reset_shared.validate_reset_token(
            token=token,
            user_aad_id='user-123',
            tenant_id='test-tenant'
        )
    
    assert result['valid'] is False
    assert result['reason'] == 'token_expired'


def test_validate_reset_token_max_attempts_exceeded(mock_token_table):
    """Test token validation after max attempts exceeded."""
    with patch.object(password_reset_shared, 'TABLE_NAME', 'test-password-reset-tokens'), \
         patch.object(password_reset_shared, 'SIGNING_KEY', 'test-key'), \
         patch.object(password_reset_shared, 'MAX_ATTEMPTS', 3):
        
        token = password_reset_shared.generate_reset_token(
            user_aad_id='user-123',
            tenant_id='test-tenant'
        )
        
        # Make 3 failed attempts
        for _ in range(3):
            password_reset_shared.validate_reset_token(
                token=token,
                user_aad_id='wrong-user',
                tenant_id='test-tenant'
            )
        
        # 4th attempt should fail even with correct user
        result = password_reset_shared.validate_reset_token(
            token=token,
            user_aad_id='user-123',
            tenant_id='test-tenant'
        )
    
    assert result['valid'] is False
    assert result['reason'] == 'max_attempts_exceeded'