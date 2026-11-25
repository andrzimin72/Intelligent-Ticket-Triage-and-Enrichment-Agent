"""Integration test: Complete password reset flow."""
import pytest
import boto3
import time
import json
import requests
from unittest.mock import patch


def test_password_reset_complete_flow():
    """Test complete password reset from request to completion."""
    
    # Step 1: Generate reset token
    token = password_reset_shared.generate_reset_token(
        user_aad_id='test-user-aad-123',
        tenant_id='test-tenant-alpha'
    )
    
    assert ':' in token
    assert len(token.split(':')[0]) >= 32
    
    # Step 2: Verify token stored in DynamoDB
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('dev-msp-triage-password-reset-tokens')
    item = table.get_item(Key={'token': token.split(':')[0]})
    
    assert 'Item' in item
    assert item['Item']['user_aad_id'] == 'test-user-aad-123'
    assert item['Item']['tenant_id'] == 'test-tenant-alpha'
    assert 'expires_at' in item['Item']
    
    # Step 3: Validate token
    result = password_reset_shared.validate_reset_token(
        token=token,
        user_aad_id='test-user-aad-123',
        tenant_id='test-tenant-alpha'
    )
    
    assert result['valid'] is True
    
    # Step 4: Attempt to use token (mock Graph API)
    with patch('password_reset_shared.call_graph_api') as mock_graph:
        mock_graph.return_value = {'success': True}
        
        result = password_reset_shared.execute_password_reset(
            token=token,
            new_password='NewSecurePassword123!'
        )
        
        assert result['success'] is True
        mock_graph.assert_called_once()
    
    # Step 5: Verify token invalidated after use
    result = password_reset_shared.validate_reset_token(
        token=token,
        user_aad_id='test-user-aad-123',
        tenant_id='test-tenant-alpha'
    )
    
    assert result['valid'] is False
    assert result['reason'] == 'token_already_used'
    
    # Step 6: Verify audit log entry created
    table = dynamodb.Table('dev-msp-triage-agent-audit-log')
    # Query for recent audit entries
    # (Implementation depends on audit log schema)