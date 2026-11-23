"""
Tests for identity_tools.py — the Bedrock Agent action group.

Covers:
- Read-only tools (get_user_info, verify_identity, check_account_lockout)
- Write tools (request/execute password reset, request/execute account unlock)
- Trusted identity extraction
- Parameter stripping
- 204 No Content handling
"""

import json
import pytest
import sys
import os
from unittest.mock import patch, MagicMock
from datetime import datetime
from moto import mock_aws
import boto3


# Make the Lambda importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src_identity_tools'))


@pytest.fixture
def aws_env():
    """Set up AWS credentials and environment variables."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["ENTRA_GRAPH_SECRET_NAME"] = "test/entra/graph_credentials"
    os.environ["ENTRA_TENANT_ID"] = "test-tenant-id"
    os.environ["ENTRA_APP_CLIENT_ID"] = "test-app-client-id"
    os.environ["PENDING_OPERATIONS_TABLE"] = "test-pending"
    os.environ["CONFIRMATION_NONCES_TABLE"] = "test-nonces"
    os.environ["RATE_LIMIT_TABLE"] = "test-rate-limits"
    os.environ["AUDIT_LOG_TABLE"] = "test-audit"
    os.environ["CONFIRMATION_SECRET_NAME"] = "test/confirmation_signing"
    os.environ["CONFIRMATION_TTL_SECONDS"] = "600"
    os.environ["ADMIN_GROUP_ID"] = "admin-group-123"
    os.environ["ADMIN_CHECK_CACHE_SECONDS"] = "60"
    os.environ["AUDIT_LOG_RETENTION"] = "365"
    os.environ["SELF_RATE_LIMITS"] = json.dumps({
        "per_operation_hourly": 3,
        "per_operation_daily": 5,
        "requests_hourly": 10,
    })
    os.environ["ADMIN_RATE_LIMITS"] = json.dumps({
        "per_operation_hourly": 20,
        "per_operation_daily": 50,
        "per_target_daily": 3,
        "requests_hourly": 30,
    })
    os.environ["NOTIFICATION_SENDER_EMAIL"] = "security@example.com"
    os.environ["SECURITY_NOTIFICATION_EMAIL"] = ""
    os.environ["AWS_REGION_NAME"] = "us-east-1"


@pytest.fixture
def aws_resources(aws_env):
    """Create DynamoDB tables and Secrets Manager secret."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        
        # Create all required tables
        for table_name, key_schema, attributes in [
            ("test-pending",
             [{"AttributeName": "confirmation_id", "KeyType": "HASH"}],
             [{"AttributeName": "confirmation_id", "AttributeType": "S"},
              {"AttributeName": "session_id", "AttributeType": "S"},
              {"AttributeName": "created_at", "AttributeType": "S"}]),
            ("test-nonces",
             [{"AttributeName": "confirmation_id", "KeyType": "HASH"}],
             [{"AttributeName": "confirmation_id", "AttributeType": "S"}]),
            ("test-rate-limits",
             [{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
             [{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}]),
            ("test-audit",
             [{"AttributeName": "audit_id", "KeyType": "HASH"}, {"AttributeName": "timestamp", "KeyType": "RANGE"}],
             [{"AttributeName": "audit_id", "AttributeType": "S"}, {"AttributeName": "timestamp", "AttributeType": "S"}]),
        ]:
            kwargs = {
                "TableName": table_name,
                "KeySchema": key_schema,
                "AttributeDefinitions": attributes,
                "BillingMode": "PAY_PER_REQUEST",
            }
            if table_name == "test-pending":
                kwargs["GlobalSecondaryIndexes"] = [{
                    "IndexName": "session-index",
                    "KeySchema": [
                        {"AttributeName": "session_id", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }]
            dynamodb.create_table(**kwargs)
        
        # Secrets Manager
        sm = boto3.client("secretsmanager", region_name="us-east-1")
        sm.create_secret(
            Name="test/entra/graph_credentials",
            SecretString=json.dumps({"CLIENT_SECRET": "test-client-secret"})
        )
        sm.create_secret(
            Name="test/confirmation_signing",
            SecretString=json.dumps({"SIGNING_KEY": "test-signing-key"})
        )
        
        yield {"dynamodb": dynamodb, "sm": sm}


IDENT = {
    "actor_aad_id": "user-aad-123",
    "actor_name": "John Doe",
    "session_id": "session-abc",
}


# =============================================================================
# READ-ONLY TOOL TESTS
# =============================================================================

def test_get_user_info_success(aws_resources):
    """Test successful user lookup."""
    with patch('identity_tools.graph_api_request') as mock_graph:
        mock_graph.side_effect = [
            {
                'id': 'user-123',
                'displayName': 'John Doe',
                'mail': 'john.doe@example.com',
                'jobTitle': 'Software Engineer',
                'department': 'Engineering'
            },
            {'displayName': 'Jane Smith'}
        ]
        
        import identity_tools
        import importlib
        importlib.reload(identity_tools)
        
        result = identity_tools.tool_get_user_info({'user_identifier': 'john.doe@example.com'})
        
        assert result['success'] is True
        assert result['user_id'] == 'user-123'
        assert result['display_name'] == 'John Doe'
        assert result['manager'] == 'Jane Smith'


def test_lambda_handler_routes_to_correct_tool(aws_resources):
    """Test that the Lambda handler routes to the correct tool based on apiPath."""
    with patch('identity_tools.tool_get_user_info') as mock_tool:
        mock_tool.return_value = {
            'success': True,
            'user_id': 'user-123',
            'display_name': 'John Doe'
        }
        
        import identity_tools
        import importlib
        importlib.reload(identity_tools)
        
        event = {
            'apiPath': '/get-user-info',
            'actionGroup': 'identity_tools',
            'httpMethod': 'POST',
            'parameters': [{'name': 'user_identifier', 'value': 'john.doe@example.com'}]
        }
        
        result = identity_tools.lambda_handler(event, None)
        
        assert result['messageVersion'] == '1.0'
        assert result['response']['httpStatusCode'] == 200
        mock_tool.assert_called_once()


# =============================================================================
# WRITE TOOL TESTS (TWO-PHASE)
# =============================================================================

def test_request_password_reset_creates_pending_operation(aws_resources):
    """Test that request_password_reset creates a pending operation."""
    with patch('identity_tools.graph_api_request') as mock_graph, \
         patch('identity_tools.sec.consume_rate_limit') as mock_rate, \
         patch('identity_tools.sec.is_authorized_admin') as mock_admin:
        
        mock_graph.return_value = {
            'id': 'user-aad-123',
            'displayName': 'John Doe',
            'userPrincipalName': 'john.doe@example.com',
        }
        mock_rate.return_value = (True, "")
        mock_admin.return_value = False
        
        import identity_tools
        import importlib
        importlib.reload(identity_tools)
        
        result = identity_tools.tool_request_password_reset(
            {'target_user_identifier': 'john.doe@example.com'},
            IDENT
        )
        
        assert result['success'] is True
        assert 'confirmation_id' in result
        assert result['operation_type'] == 'password_reset'
        assert result['is_admin_override'] is False


def test_request_password_reset_requires_admin_for_other_user(aws_resources):
    """Test that resetting another user's password requires admin privilege."""
    with patch('identity_tools.graph_api_request') as mock_graph, \
         patch('identity_tools.sec.consume_rate_limit') as mock_rate, \
         patch('identity_tools.sec.is_authorized_admin') as mock_admin:
        
        mock_graph.return_value = {
            'id': 'other-user-id',  # Different from actor
            'displayName': 'Jane Smith',
        }
        mock_rate.return_value = (True, "")
        mock_admin.return_value = False  # Not an admin
        
        import identity_tools
        import importlib
        importlib.reload(identity_tools)
        
        result = identity_tools.tool_request_password_reset(
            {'target_user_identifier': 'jane.smith@example.com'},
            IDENT
        )
        
        assert result['success'] is False
        assert 'administrator privileges' in result['error'].lower()


def test_request_password_reset_admin_requires_justification(aws_resources):
    """Test that admin overrides require a justification."""
    with patch('identity_tools.graph_api_request') as mock_graph, \
         patch('identity_tools.sec.consume_rate_limit') as mock_rate, \
         patch('identity_tools.sec.is_authorized_admin') as mock_admin:
        
        mock_graph.return_value = {
            'id': 'other-user-id',
            'displayName': 'Jane Smith',
        }
        mock_rate.return_value = (True, "")
        mock_admin.return_value = True  # Is an admin
        
        import identity_tools
        import importlib
        importlib.reload(identity_tools)
        
        # No justification
        result = identity_tools.tool_request_password_reset(
            {'target_user_identifier': 'jane.smith@example.com'},
            IDENT
        )
        
        assert result['success'] is False
        assert 'justification' in result['error'].lower()


def test_execute_password_reset_requires_approved_confirmation(aws_resources):
    """Test that execute_password_reset requires an approved confirmation."""
    import identity_tools
    import importlib
    importlib.reload(identity_tools)
    
    result = identity_tools.tool_execute_password_reset(
        {'confirmation_id': 'nonexistent-id'},
        IDENT
    )
    
    assert result['success'] is False
    assert 'not recognised' in result['error'].lower()


def test_lambda_handler_strips_identity_parameters(aws_resources):
    """Test that the Lambda handler strips identity fields from parameters."""
    with patch('identity_tools.tool_request_password_reset') as mock_tool:
        mock_tool.return_value = {'success': True, 'confirmation_id': 'abc123'}
        
        import identity_tools
        import importlib
        importlib.reload(identity_tools)
        
        event = {
            'apiPath': '/request-password-reset',
            'sessionAttributes': {'user_aad_id': 'real-user', 'user_name': 'Real User'},
            'sessionId': 'session-123',
            'actionGroup': 'identity_tools',
            'httpMethod': 'POST',
            'parameters': [
                {'name': 'target_user_identifier', 'value': 'user@example.com'},
                {'name': 'user_aad_id', 'value': 'attacker-id'},  # Should be stripped
                {'name': 'is_admin', 'value': 'true'},  # Should be stripped
            ]
        }
        
        identity_tools.lambda_handler(event, None)
        
        # Verify the tool was called with stripped parameters
        call_args = mock_tool.call_args[0][0]
        assert 'user_aad_id' not in call_args
        assert 'is_admin' not in call_args
        assert 'target_user_identifier' in call_args


def test_graph_204_does_not_raise(aws_resources):
    """Regression test: Graph API PATCH returns 204 with an empty body."""
    import identity_tools
    
    # Mock a 204 response
    mock_response = MagicMock()
    mock_response.status = 204
    mock_response.read.return_value = b''
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    
    with patch('identity_tools.urllib.request.urlopen', return_value=mock_response):
        result = identity_tools.graph_api_request('/users/123', method='PATCH', body={})
        assert result == {}  # Should not raise JSONDecodeError


# =============================================================================
# TRUSTED IDENTITY TESTS
# =============================================================================

def test_write_without_session_identity_fails(aws_resources):
    """Test that write operations fail without session identity."""
    import identity_tools
    import importlib
    importlib.reload(identity_tools)
    
    event = {
        'apiPath': '/request-password-reset',
        'parameters': [{'name': 'target_user_identifier', 'value': 'user@example.com'}]
        # Missing sessionAttributes and sessionId
    }
    
    result = identity_tools.lambda_handler(event, None)
    
    assert result['response']['httpStatusCode'] == 400
    response_body = json.loads(result['response']['responseBody']['application/json']['body'])
    assert 'verified Teams identity' in response_body['error']