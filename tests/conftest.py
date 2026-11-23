import json
import os
import sys
import pytest
import boto3
from moto import mock_aws
from unittest.mock import patch, MagicMock

# Make the Lambda code importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# --- Constants for test data ---
TEST_TICKET_ID = "12345"
TEST_CUSTOMER_ID = "CUST-99"
TEST_REGION = "us-east-1"
TEST_MODEL_ID = "anthropic.claude-sonnet-5-5-v1:0"
TEST_GUARDRAIL_ID = "gr-test123"
TEST_GUARDRAIL_VERSION = "1"
TEST_IDEMPOTENCY_TABLE = "test-idempotency"

TEST_PSA_SECRET = {
    "BASE_URL": "https://api-na.myconnectwise.net",
    "COMPANY_ID": "TestCo",
    "PUBLIC_KEY": "pubkey",
    "PRIVATE_KEY": "privkey",
    "CLIENT_ID": "TestAgent"
}

TEST_RMM_SECRET = {
    "BASE_URL": "https://api.ninjarmm.com",
    "API_TOKEN": "test-bearer-token"
}

# Predictable LLM response for happy path
HAPPY_PATH_LLM_RESPONSE = {
    "summary": "Exchange server EXCH-SVR-01 is offline due to high CPU usage. Mail flow is impacted.",
    "category": "Software",
    "priority": "High",
    "extracted_entities": {"hostname": "EXCH-SVR-01", "error_code": "550 5.7.1"},
    "draft_internal_notes": "Server EXCH-SVR-01 showing high CPU. RMM alert confirms issue started at 08:00 UTC.",
    "confidence_score": 0.92
}


@pytest.fixture
def aws_credentials():
    """Mock AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = TEST_REGION


@pytest.fixture
def lambda_env_vars(aws_credentials):
    """Set all environment variables the Lambda expects."""
    env_vars = {
        "AWS_REGION": TEST_REGION,
        "MODEL_ID": TEST_MODEL_ID,
        "PSA_SECRET_NAME": "test/msp/psa/api_keys",
        "RMM_SECRET_NAME": "test/msp/rmm/api_keys",
        "GUARDRAIL_ID": TEST_GUARDRAIL_ID,
        "GUARDRAIL_VERSION": TEST_GUARDRAIL_VERSION,
        "IDEMPOTENCY_TABLE": TEST_IDEMPOTENCY_TABLE,
        "IDEMPOTENCY_TTL_DAYS": "30",
        "LOG_LEVEL": "DEBUG",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        yield env_vars


@pytest.fixture
def mock_aws_services(aws_credentials):
    """Spin up moto mocks for DynamoDB and Secrets Manager."""
    with mock_aws():
        # --- Secrets Manager ---
        sm = boto3.client("secretsmanager", region_name=TEST_REGION)
        sm.create_secret(
            Name="test/msp/psa/api_keys",
            SecretString=json.dumps(TEST_PSA_SECRET)
        )
        sm.create_secret(
            Name="test/msp/rmm/api_keys",
            SecretString=json.dumps(TEST_RMM_SECRET)
        )
        sm.create_secret(
            Name="test/msp/webhook/token",
            SecretString=json.dumps({"TOKEN": "valid-webhook-token"})
        )

        # --- DynamoDB idempotency table ---
        dynamodb = boto3.resource("dynamodb", region_name=TEST_REGION)
        dynamodb.create_table(
            TableName=TEST_IDEMPOTENCY_TABLE,
            KeySchema=[{"AttributeName": "ticket_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "ticket_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
            TTL={"AttributeName": "ttl", "Enabled": True}
        )

        yield {
            "secretsmanager": sm,
            "dynamodb": dynamodb,
        }


@pytest.fixture
def mock_bedrock():
    """Mock the Bedrock runtime client. Returns predictable LLM output."""
    with patch("boto3.client") as mock_client_factory:
        mock_bedrock_client = MagicMock()

        # Default: return happy-path LLM response
        mock_bedrock_client.invoke_model.return_value = {
            "body": MagicMock(
                read=MagicMock(return_value=json.dumps({
                    "content": [{"text": json.dumps(HAPPY_PATH_LLM_RESPONSE)}]
                }).encode("utf-8"))
            )
        }

        # Default: guardrail passes (no intervention)
        mock_bedrock_client.apply_guardrail.return_value = {
            "action": "NONE",
            "outputs": [],
            "assessments": []
        }

        # Route boto3.client calls: bedrock-runtime -> mock, others -> real
        def client_side_effect(service, **kwargs):
            if service == "bedrock-runtime":
                return mock_bedrock_client
            # For secretsmanager/dynamodb, fall through to real (moto) client
            return boto3.client.__wrapped__(service, **kwargs) if hasattr(boto3.client, "__wrapped__") else boto3._get_default_session().create_client(service, **kwargs)

        # Simpler approach: patch the module-level clients after import
        import lambda_function
        original_bedrock = lambda_function.bedrock_runtime
        lambda_function.bedrock_runtime = mock_bedrock_client

        yield mock_bedrock_client

        # Restore
        lambda_function.bedrock_runtime = original_bedrock


@pytest.fixture
def mock_http():
    """Mock all outbound HTTP calls (ConnectWise, NinjaOne)."""
    with patch("lambda_function.make_api_request") as mock_req:
        def side_effect(url, headers, method="GET", data=None):
            # --- ConnectWise ticket query ---
            if "/service/tickets?" in url and "conditions=id=" in url:
                return [{
                    "id": int(TEST_TICKET_ID),
                    "summary": "Exchange Server Offline",
                    "description": "User reports they can't send emails.",
                    "company": {"id": int(TEST_CUSTOMER_ID)},
                    "board": {"name": "Service"},
                    "priority": {"name": "Medium"},
                    "customFields": []
                }]

            # --- ConnectWise activities ---
            if f"/service/tickets/{TEST_TICKET_ID}/activities" in url and method == "GET":
                return [{
                    "dateEntered": "2026-11-14T08:00:00Z",
                    "contactName": "John Doe",
                    "notes": "Yes, it says '550 5.7.1 Unable to relay'."
                }]

            # --- ConnectWise ticket update (PATCH) ---
            if f"/service/tickets/{TEST_TICKET_ID}" in url and method == "PATCH":
                return {"id": int(TEST_TICKET_ID)}

            # --- ConnectWise activity creation (POST) ---
            if f"/service/tickets/{TEST_TICKET_ID}/activities" in url and method == "POST":
                return {"id": 999}

            # --- NinjaOne alerts ---
            if "/v2/alerts" in url:
                return {
                    "data": [{
                        "deviceName": "EXCH-SVR-01",
                        "alertName": "High CPU",
                        "severity": "CRITICAL",
                        "alertTime": "2026-11-14T08:00:00Z"
                    }]
                }

            raise ValueError(f"Unmocked HTTP call: {method} {url}")

        mock_req.side_effect = side_effect
        yield mock_req


@pytest.fixture
def lambda_module(lambda_env_vars, mock_aws_services, mock_bedrock):
    """
    Import (or reload) the Lambda module with all mocks in place.
    Reloading ensures environment variables are re-read.
    """
    import importlib
    import lambda_function
    importlib.reload(lambda_function)
    return lambda_function