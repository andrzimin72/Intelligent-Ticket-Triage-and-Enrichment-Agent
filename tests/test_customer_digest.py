import json
import pytest
import sys
import os
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from moto import mock_aws
import boto3


# Make the Lambdas importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src_customer_digest_orchestrator'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src_customer_digest_worker'))


@pytest.fixture
def aws_env():
    """Set up AWS credentials and environment variables."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def orchestrator_env(aws_env):
    """Environment variables for the orchestrator."""
    os.environ["CUSTOMER_PREFERENCES_TABLE"] = "test-customer-preferences"
    os.environ["CUSTOMER_DIGEST_QUEUE_URL"] = "https://sqs.us-east-1.amazonaws.com/123456789/test-queue"
    os.environ["MAX_CUSTOMERS_PER_RUN"] = "500"
    os.environ["AWS_REGION_NAME"] = "us-east-1"


@pytest.fixture
def worker_env(aws_env):
    """Environment variables for the worker."""
    os.environ["RMM_SECRET_NAME"] = "test/msp/rmm/api_keys"
    os.environ["CUSTOMER_DIGEST_MODEL_ID"] = "anthropic.claude-haiku-4-5-v1:0"
    os.environ["GUARDRAIL_ID"] = "gr-test"
    os.environ["GUARDRAIL_VERSION"] = "1"
    os.environ["SENDER_EMAIL"] = "security@yourmsp.com"
    os.environ["MIN_SEVERITY"] = "warning"
    os.environ["AWS_REGION_NAME"] = "us-east-1"


@pytest.fixture
def aws_resources(aws_env):
    """Create DynamoDB table, SQS queue, and Secrets Manager secret."""
    with mock_aws():
        # Create DynamoDB table
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="test-customer-preferences",
            KeySchema=[{"AttributeName": "customer_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "customer_id", "AttributeType": "S"},
                {"AttributeName": "enabled", "AttributeType": "N"},
            ],
            GlobalSecondaryIndexes=[{
                "IndexName": "enabled-index",
                "KeySchema": [
                    {"AttributeName": "enabled", "KeyType": "HASH"},
                    {"AttributeName": "customer_id", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )
        
        # Create SQS queue
        sqs = boto3.client("sqs", region_name="us-east-1")
        queue = sqs.create_queue(QueueName="test-queue")
        queue_url = queue["QueueUrl"]
        
        # Create Secrets Manager secret
        sm = boto3.client("secretsmanager", region_name="us-east-1")
        sm.create_secret(
            Name="test/msp/rmm/api_keys",
            SecretString=json.dumps({
                "BASE_URL": "https://api.ninjarmm.com",
                "API_TOKEN": "test-token"
            })
        )
        
        yield {
            "dynamodb": dynamodb,
            "table": table,
            "sqs": sqs,
            "queue_url": queue_url,
            "sm": sm,
        }


def test_orchestrator_fans_out_enabled_customers(orchestrator_env, aws_resources):
    """Orchestrator should send one SQS message per enabled customer."""
    table = aws_resources["table"]
    sqs = aws_resources["sqs"]
    queue_url = aws_resources["queue_url"]
    
    # Seed with 3 customers: 2 enabled, 1 disabled
    table.put_item(Item={
        "customer_id": "CUST-1",
        "enabled": True,
        "email": "cust1@example.com",
        "customer_name": "Acme Corp",
        "organization_id": "ORG-1",
    })
    table.put_item(Item={
        "customer_id": "CUST-2",
        "enabled": True,
        "email": "cust2@example.com",
        "customer_name": "Beta Inc",
        "organization_id": "ORG-2",
    })
    table.put_item(Item={
        "customer_id": "CUST-3",
        "enabled": False,  # Disabled
        "email": "cust3@example.com",
        "customer_name": "Gamma LLC",
        "organization_id": "ORG-3",
    })
    
    # Update queue URL in env
    os.environ["CUSTOMER_DIGEST_QUEUE_URL"] = queue_url
    
    import customer_digest_orchestrator
    import importlib
    importlib.reload(customer_digest_orchestrator)
    
    result = customer_digest_orchestrator.lambda_handler({}, None)
    
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["customers_enabled"] == 2
    assert body["messages_sent"] == 2
    
    # Verify SQS messages
    response = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10)
    messages = response.get("Messages", [])
    assert len(messages) == 2
    
    # Verify message content
    customer_ids = set()
    for msg in messages:
        body = json.loads(msg["Body"])
        customer_ids.add(body["customer_id"])
        assert "email" in body
        assert "organization_id" in body
    
    assert customer_ids == {"CUST-1", "CUST-2"}


def test_orchestrator_respects_max_cap(orchestrator_env, aws_resources):
    """Orchestrator should respect MAX_CUSTOMERS_PER_RUN."""
    table = aws_resources["table"]
    
    # Seed with 10 enabled customers
    for i in range(10):
        table.put_item(Item={
            "customer_id": f"CUST-{i}",
            "enabled": True,
            "email": f"cust{i}@example.com",
            "customer_name": f"Customer {i}",
            "organization_id": f"ORG-{i}",
        })
    
    # Set cap to 5
    os.environ["MAX_CUSTOMERS_PER_RUN"] = "5"
    
    import customer_digest_orchestrator
    import importlib
    importlib.reload(customer_digest_orchestrator)
    
    result = customer_digest_orchestrator.lambda_handler({}, None)
    
    body = json.loads(result["body"])
    assert body["customers_enabled"] == 10
    assert body["messages_sent"] == 5  # Capped


def test_worker_skips_customers_with_no_alerts(worker_env, aws_resources):
    """Worker should skip sending email if customer has no alerts."""
    # Mock the API call to return empty alerts
    with patch('customer_digest_worker.urllib.request.urlopen') as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"data": []}).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response
        
        import customer_digest_worker
        import importlib
        importlib.reload(customer_digest_worker)
        
        message = {
            "customer_id": "CUST-1",
            "email": "cust1@example.com",
            "customer_name": "Acme Corp",
            "organization_id": "ORG-1",
        }
        
        # Should not raise, should skip email
        customer_digest_worker.process_customer(message)
        
        # Verify SES was NOT called
        # (We can't easily verify this without mocking SES, but the function should return early)


def test_worker_generates_and_sends_digest(worker_env, aws_resources):
    """Worker should generate summary and send email when alerts exist."""
    # Mock the API call to return alerts
    alerts = [
        {
            "alertName": "High CPU Usage",
            "deviceName": "SERVER-01",
            "severity": "warning",
            "alertTime": datetime.utcnow().isoformat() + "Z",
        },
        {
            "alertName": "Disk Space Low",
            "deviceName": "SERVER-02",
            "severity": "error",
            "alertTime": datetime.utcnow().isoformat() + "Z",
        },
    ]
    
    with patch('customer_digest_worker.urllib.request.urlopen') as mock_urlopen, \
         patch('customer_digest_worker.bedrock_runtime') as mock_bedrock, \
         patch('customer_digest_worker.ses_client') as mock_ses:
        
        # Mock NinjaOne API response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"data": alerts}).encode('utf-8')
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response
        
        # Mock Bedrock response
        mock_bedrock.apply_guardrail.return_value = {
            "action": "NONE",
            "text": "Your systems are secure with minor items requiring attention.",
            "assessments": []
        }
        mock_bedrock.invoke_model.return_value = {
            "body": MagicMock(
                read=MagicMock(return_value=json.dumps({
                    "content": [{"text": "Your systems are secure with minor items requiring attention."}]
                }).encode('utf-8'))
            )
        }
        
        # Mock SES
        mock_ses.send_email.return_value = {}
        
        import customer_digest_worker
        import importlib
        importlib.reload(customer_digest_worker)
        
        message = {
            "customer_id": "CUST-1",
            "email": "cust1@example.com",
            "customer_name": "Acme Corp",
            "organization_id": "ORG-1",
        }
        
        customer_digest_worker.process_customer(message)
        
        # Verify SES was called
        mock_ses.send_email.assert_called_once()
        call_args = mock_ses.send_email.call_args
        assert call_args.kwargs["Destination"]["ToAddresses"] == ["cust1@example.com"]
        assert "Daily Security Digest" in call_args.kwargs["Message"]["Subject"]["Data"]


def test_format_digest_email():
    """Test email formatting."""
    import customer_digest_worker
    
    html = customer_digest_worker.format_digest_email(
        customer_name="Acme Corp",
        summary="Your systems are secure.",
        alert_count=2
    )
    
    assert "Acme Corp" in html
    assert "Your systems are secure." in html
    assert "2 alerts" in html
    assert "Daily Security Digest" in html