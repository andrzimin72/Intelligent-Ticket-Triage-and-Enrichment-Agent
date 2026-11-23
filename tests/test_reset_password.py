"""
Tests for the secure password reset flow.
"""

import pytest
import sys
import os
import time
import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from moto import mock_aws
import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src_reset_password'))


@pytest.fixture
def aws_env():
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["ENTRA_GRAPH_SECRET_NAME"] = "test/entra/graph_credentials"
    os.environ["ENTRA_TENANT_ID"] = "test-tenant"
    os.environ["ENTRA_APP_CLIENT_ID"] = "test-client"
    os.environ["RESET_TOKENS_TABLE"] = "test-reset-tokens"
    os.environ["AUDIT_LOG_TABLE"] = "test-audit"
    os.environ["TOKEN_TTL_SECONDS"] = "900"
    os.environ["MAX_ATTEMPTS_PER_TOKEN"] = "5"
    os.environ["SENDER_EMAIL"] = "reset@example.com"
    os.environ["SUPPORT_EMAIL"] = "support@example.com"
    os.environ["MSP_COMPANY_NAME"] = "Test MSP"
    os.environ["AWS_REGION_NAME"] = "us-east-1"


@pytest.fixture
def aws_resources(aws_env):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        
        dynamodb.create_table(
            TableName="test-reset-tokens",
            KeySchema=[{"AttributeName": "token", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "token", "AttributeType": "S"},
                {"AttributeName": "user_aad_id", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[{
                "IndexName": "user-index",
                "KeySchema": [{"AttributeName": "user_aad_id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )
        
        dynamodb.create_table(
            TableName="test-audit",
            KeySchema=[
                {"AttributeName": "audit_id", "KeyType": "HASH"},
                {"AttributeName": "timestamp", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "audit_id", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        
        sm = boto3.client("secretsmanager", region_name="us-east-1")
        sm.create_secret(
            Name="test/entra/graph_credentials",
            SecretString=json.dumps({"CLIENT_SECRET": "test-secret"})
        )
        
        yield {"dynamodb": dynamodb, "sm": sm}


class TestTokenGeneration:
    def test_token_is_url_safe_and_256_bits(self, aws_resources):
        import reset_password
        token = reset_password.generate_reset_token(
            user_aad_id="user-123", initiator_aad_id="init-456",
            initiator_name="Admin", is_admin_override=False
        )
        assert len(token) > 32  # URL-safe base64 of 32 bytes
        # Should only contain URL-safe characters
        import string
        allowed = string.ascii_letters + string.digits + '-_'
        assert all(c in allowed for c in token)
    
    def test_token_is_stored_in_dynamodb(self, aws_resources):
        import reset_password
        token = reset_password.generate_reset_token(
            user_aad_id="user-123", initiator_aad_id="init-456",
            initiator_name="Admin", is_admin_override=False
        )
        
        table = aws_resources["dynamodb"].Table("test-reset-tokens")
        item = table.get_item(Key={"token": token})["Item"]
        
        assert item["user_aad_id"] == "user-123"
        assert item["initiator_aad_id"] == "init-456"
        assert item["status"] == "pending"
        assert item["attempts"] == 0


class TestTokenValidation:
    def test_valid_token(self, aws_resources):
        import reset_password
        token = reset_password.generate_reset_token(
            user_aad_id="user-123", initiator_aad_id="init-456",
            initiator_name="Admin", is_admin_override=False
        )
        
        is_valid, record, error = reset_password.validate_token(token)
        assert is_valid is True
        assert record["user_aad_id"] == "user-123"
    
    def test_invalid_token(self, aws_resources):
        import reset_password
        is_valid, record, error = reset_password.validate_token("nonexistent-token")
        assert is_valid is False
        assert "invalid" in error.lower()
    
    def test_expired_token(self, aws_resources):
        import reset_password
        token = reset_password.generate_reset_token(
            user_aad_id="user-123", initiator_aad_id="init-456",
            initiator_name="Admin", is_admin_override=False
        )
        
        # Manually expire the token
        table = aws_resources["dynamodb"].Table("test-reset-tokens")
        table.update_item(
            Key={"token": token},
            UpdateExpression="SET expires_at = :exp",
            ExpressionAttributeValues={":exp": int(time.time()) - 1},
        )
        
        is_valid, record, error = reset_password.validate_token(token)
        assert is_valid is False
        assert "expired" in error.lower()
    
    def test_consumed_token_rejected(self, aws_resources):
        import reset_password
        token = reset_password.generate_reset_token(
            user_aad_id="user-123", initiator_aad_id="init-456",
            initiator_name="Admin", is_admin_override=False
        )
        
        assert reset_password.mark_token_consumed(token) is True
        is_valid, record, error = reset_password.validate_token(token)
        assert is_valid is False
        assert "already been used" in error.lower()


class TestSingleUseEnforcement:
    def test_token_can_only_be_consumed_once(self, aws_resources):
        import reset_password
        token = reset_password.generate_reset_token(
            user_aad_id="user-123", initiator_aad_id="init-456",
            initiator_name="Admin", is_admin_override=False
        )
        
        assert reset_password.mark_token_consumed(token) is True
        # Second attempt fails
        assert reset_password.mark_token_consumed(token) is False


class TestRateLimiting:
    def test_attempts_increment(self, aws_resources):
        import reset_password
        token = reset_password.generate_reset_token(
            user_aad_id="user-123", initiator_aad_id="init-456",
            initiator_name="Admin", is_admin_override=False
        )
        
        count = reset_password.increment_token_attempts(token)
        assert count == 1
        
        count = reset_password.increment_token_attempts(token)
        assert count == 2
    
    def test_token_invalidated_after_max_attempts(self, aws_resources):
        import reset_password
        token = reset_password.generate_reset_token(
            user_aad_id="user-123", initiator_aad_id="init-456",
            initiator_name="Admin", is_admin_override=False
        )
        
        # Exhaust attempts
        for _ in range(5):
            reset_password.increment_token_attempts(token)
        
        # Next attempt should invalidate
        count = reset_password.increment_token_attempts(token)
        assert count > 5
        
        # Token should now be invalidated
        is_valid, record, error = reset_password.validate_token(token)
        assert is_valid is False
        assert "invalidated" in error.lower()


class TestPasswordValidation:
    def test_valid_password(self, aws_resources):
        import reset_password
        user_info = {"displayName": "John Doe", "userPrincipalName": "john@example.com"}
        
        is_valid, error = reset_password.validate_password("Str0ng!Pass#2026", user_info)
        assert is_valid is True
    
    def test_too_short(self, aws_resources):
        import reset_password
        user_info = {"displayName": "John Doe"}
        
        is_valid, error = reset_password.validate_password("Short1!", user_info)
        assert is_valid is False
        assert "at least" in error.lower()
    
    def test_missing_character_classes(self, aws_resources):
        import reset_password
        user_info = {"displayName": "John Doe"}
        
        # Only lowercase + digits (2 classes, need 3)
        is_valid, error = reset_password.validate_password("onlylowercase123", user_info)
        assert is_valid is False
        assert "3 of" in error
    
    def test_contains_username(self, aws_resources):
        import reset_password
        user_info = {"displayName": "John Doe", "userPrincipalName": "johndoe@example.com"}
        
        is_valid, error = reset_password.validate_password("MyJohnDoePass123!", user_info)
        assert is_valid is False
        assert "name" in error.lower() or "email" in error.lower()


class TestHTTPEndpoints:
    def test_get_with_valid_token_returns_form(self, aws_resources):
        import reset_password
        token = reset_password.generate_reset_token(
            user_aad_id="user-123", initiator_aad_id="init-456",
            initiator_name="Admin", is_admin_override=False
        )
        
        with patch('reset_password.get_user_info') as mock_user:
            mock_user.return_value = {
                "displayName": "John Doe",
                "mail": "john@example.com",
            }
            
            event = {
                "requestContext": {"http": {"method": "GET"}},
                "queryStringParameters": {"token": token},
            }
            
            result = reset_password.lambda_handler(event, None)
            assert result["statusCode"] == 200
            assert "Set Your New Password" in result["body"]
            assert "John Doe" in result["body"]
    
    def test_get_with_invalid_token_returns_error(self, aws_resources):
        import reset_password
        
        event = {
            "requestContext": {"http": {"method": "GET"}},
            "queryStringParameters": {"token": "invalid-token"},
        }
        
        result = reset_password.lambda_handler(event, None)
        assert result["statusCode"] == 400
        assert "invalid" in result["body"].lower() or "expired" in result["body"].lower()
    
    def test_post_with_valid_password_sets_password(self, aws_resources):
        import reset_password
        import urllib.parse
        
        token = reset_password.generate_reset_token(
            user_aad_id="user-123", initiator_aad_id="init-456",
            initiator_name="Admin", is_admin_override=False
        )
        
        with patch('reset_password.get_user_info') as mock_user, \
             patch('reset_password.graph_request') as mock_graph, \
             patch('reset_password.send_confirmation_email') as mock_email:
            
            mock_user.return_value = {
                "displayName": "John Doe",
                "mail": "john@example.com",
                "userPrincipalName": "john@example.com",
            }
            mock_graph.return_value = {}
            mock_email.return_value = True
            
            form_data = urllib.parse.urlencode({
                "token": token,
                "newPassword": "Str0ng!Pass#2026",
                "confirmPassword": "Str0ng!Pass#2026",
            })
            
            event = {
                "requestContext": {"http": {"method": "POST", "sourceIp": "1.2.3.4"}},
                "headers": {"user-agent": "Test/1.0"},
                "body": form_data,
                "isBase64Encoded": False,
            }
            
            result = reset_password.lambda_handler(event, None)
            assert result["statusCode"] == 200
            assert "successfully" in result["body"].lower()
            
            # Verify Graph API was called
            mock_graph.assert_called_once()
            call_args = mock_graph.call_args
            assert "user-123" in call_args[0][0]
            assert call_args[1]["method"] == "PATCH"
            
            # Verify token is now consumed
            is_valid, _, _ = reset_password.validate_token(token)
            assert is_valid is False
    
    def test_post_with_mismatched_passwords_shows_error(self, aws_resources):
        import reset_password
        import urllib.parse
        
        token = reset_password.generate_reset_token(
            user_aad_id="user-123", initiator_aad_id="init-456",
            initiator_name="Admin", is_admin_override=False
        )
        
        with patch('reset_password.get_user_info') as mock_user:
            mock_user.return_value = {
                "displayName": "John Doe",
                "mail": "john@example.com",
            }
            
            form_data = urllib.parse.urlencode({
                "token": token,
                "newPassword": "Str0ng!Pass#2026",
                "confirmPassword": "Different!Pass#2026",
            })
            
            event = {
                "requestContext": {"http": {"method": "POST"}},
                "headers": {},
                "body": form_data,
                "isBase64Encoded": False,
            }
            
            result = reset_password.lambda_handler(event, None)
            assert result["statusCode"] == 200
            assert "do not match" in result["body"].lower()
    
    def test_post_with_weak_password_shows_error(self, aws_resources):
        import reset_password
        import urllib.parse
        
        token = reset_password.generate_reset_token(
            user_aad_id="user-123", initiator_aad_id="init-456",
            initiator_name="Admin", is_admin_override=False
        )
        
        with patch('reset_password.get_user_info') as mock_user:
            mock_user.return_value = {
                "displayName": "John Doe",
                "mail": "john@example.com",
            }
            
            form_data = urllib.parse.urlencode({
                "token": token,
                "newPassword": "weak",
                "confirmPassword": "weak",
            })
            
            event = {
                "requestContext": {"http": {"method": "POST"}},
                "headers": {},
                "body": form_data,
                "isBase64Encoded": False,
            }
            
            result = reset_password.lambda_handler(event, None)
            assert result["statusCode"] == 200
            assert "at least" in result["body"].lower()
    
    def test_audit_log_does_not_contain_password(self, aws_resources):
        import reset_password
        import urllib.parse
        
        token = reset_password.generate_reset_token(
            user_aad_id="user-123", initiator_aad_id="init-456",
            initiator_name="Admin", is_admin_override=False
        )
        
        with patch('reset_password.get_user_info') as mock_user, \
             patch('reset_password.graph_request') as mock_graph, \
             patch('reset_password.send_confirmation_email'):
            
            mock_user.return_value = {
                "displayName": "John Doe",
                "mail": "john@example.com",
                "userPrincipalName": "john@example.com",
            }
            mock_graph.return_value = {}
            
            secret_password = "MySuperSecretPassword123!"
            form_data = urllib.parse.urlencode({
                "token": token,
                "newPassword": secret_password,
                "confirmPassword": secret_password,
            })
            
            event = {
                "requestContext": {"http": {"method": "POST", "sourceIp": "1.2.3.4"}},
                "headers": {},
                "body": form_data,
                "isBase64Encoded": False,
            }
            
            reset_password.lambda_handler(event, None)
            
            # Check audit log doesn't contain the password
            table = aws_resources["dynamodb"].Table("test-audit")
            response = table.scan()
            for item in response.get("Items", []):
                params_str = item.get("parameters", "")
                assert secret_password not in params_str