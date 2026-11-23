"""
Comprehensive tests for the Bedrock Guardrail integration.

These tests specifically verify the fix for the silent-failure bug where
the BLOCK case (guardrail rejects content entirely) was being misclassified
as NONE, causing PII to flow through to the LLM.

The Bedrock Guardrail API has two intervention modes:
  - BLOCK: action='GUARDRAIL_INTERVENED', outputs=[] (content rejected)
  - ANONYMIZE: action='GUARDRAIL_INTERVENED', outputs=[{'text': '...'}] (content sanitized)

Both must be handled correctly.
"""

import json
import pytest
import sys
import os
from unittest.mock import patch, MagicMock
from moto import mock_aws
import boto3


# Make the Lambda code importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


@pytest.fixture
def aws_credentials():
    """Mock AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def lambda_env_vars(aws_credentials):
    """Set all environment variables the Lambda expects."""
    env_vars = {
        "AWS_REGION": "us-east-1",
        "MODEL_ID": "anthropic.claude-sonnet-5-5-v1:0",
        "FALLBACK_MODEL_ID": "anthropic.claude-sonnet-5-v1:0",
        "HAIKU_MODEL_ID": "anthropic.claude-haiku-4-5-v1:0",
        "PSA_SECRET_NAME": "test/msp/psa/api_keys",
        "RMM_SECRET_NAME": "test/msp/rmm/api_keys",
        "GUARDRAIL_ID": "gr-test123",
        "GUARDRAIL_VERSION": "1",
        "IDEMPOTENCY_TABLE": "test-idempotency",
        "IDEMPOTENCY_TTL_DAYS": "30",
        "METRICS_TABLE": "test-metrics",
        "METRICS_TTL_DAYS": "90",
        "LOG_LEVEL": "DEBUG",
    }
    with patch.dict(os.environ, env_vars, clear=False):
        yield env_vars


@pytest.fixture
def mock_aws_services(aws_credentials):
    """Spin up moto mocks for DynamoDB and Secrets Manager."""
    with mock_aws():
        sm = boto3.client("secretsmanager", region_name="us-east-1")
        sm.create_secret(
            Name="test/msp/psa/api_keys",
            SecretString=json.dumps({
                "BASE_URL": "https://api-na.myconnectwise.net",
                "COMPANY_ID": "TestCo",
                "PUBLIC_KEY": "pubkey",
                "PRIVATE_KEY": "privkey",
                "CLIENT_ID": "TestAgent"
            })
        )
        sm.create_secret(
            Name="test/msp/rmm/api_keys",
            SecretString=json.dumps({
                "BASE_URL": "https://api.ninjarmm.com",
                "API_TOKEN": "test-bearer-token"
            })
        )
        
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName="test-idempotency",
            KeySchema=[{"AttributeName": "ticket_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "ticket_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        dynamodb.create_table(
            TableName="test-metrics",
            KeySchema=[{"AttributeName": "ticket_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "ticket_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        
        yield {
            "secretsmanager": sm,
            "dynamodb": dynamodb,
        }


@pytest.fixture
def mock_bedrock():
    """Mock the Bedrock runtime client."""
    with patch("boto3.client") as mock_client_factory:
        mock_bedrock_client = MagicMock()
        
        # Default: guardrail passes (no intervention)
        mock_bedrock_client.apply_guardrail.return_value = {
            "action": "NONE",
            "outputs": [],
            "assessments": []
        }
        
        # Default: LLM returns happy-path response
        mock_bedrock_client.invoke_model.return_value = {
            "body": _make_bedrock_body({
                "summary": "ok",
                "category": "Software",
                "priority": "High",
                "extracted_entities": {},
                "draft_internal_notes": "ok",
                "confidence_score": 0.9
            })
        }
        
        import lambda_function
        original_bedrock = lambda_function.bedrock_runtime
        lambda_function.bedrock_runtime = mock_bedrock_client
        
        yield mock_bedrock_client
        
        lambda_function.bedrock_runtime = original_bedrock


@pytest.fixture
def mock_http():
    """Mock all outbound HTTP calls (ConnectWise, NinjaOne)."""
    with patch("lambda_function.make_api_request") as mock_req:
        def side_effect(url, headers, method="GET", data=None):
            if "/service/tickets?" in url and "conditions=id=" in url:
                return [{
                    "id": 12345,
                    "summary": "Exchange Server Offline",
                    "description": "User reports they can't send emails.",
                    "company": {"id": 99},
                    "board": {"name": "Service"},
                    "priority": {"name": "Medium"},
                    "customFields": []
                }]
            if "/service/tickets/12345/activities" in url and method == "GET":
                return [{
                    "dateEntered": "2026-11-14T08:00:00Z",
                    "contactName": "John Doe",
                    "notes": "Yes, it says '550 5.7.1 Unable to relay'."
                }]
            if "/service/tickets/12345" in url and method == "PATCH":
                return {"id": 12345}
            if "/service/tickets/12345/activities" in url and method == "POST":
                return {"id": 999}
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
    """Import (or reload) the Lambda module with all mocks in place."""
    import importlib
    import lambda_function
    importlib.reload(lambda_function)
    return lambda_function


def _make_bedrock_body(data):
    """Helper to build a Bedrock-shaped response body."""
    import io
    return io.BytesIO(json.dumps({
        "content": [{"text": json.dumps(data)}]
    }).encode("utf-8"))


# ==============================================================================
# UNIT TESTS: apply_guardrail function
# ==============================================================================

class TestApplyGuardrail:
    """Unit tests for the apply_guardrail function."""
    
    def test_block_case_returns_empty_text(self, lambda_module, mock_bedrock):
        """
        CRITICAL TEST: When guardrail BLOCKS content (no sanitized output),
        apply_guardrail must return empty text so the caller correctly raises ValueError.
        
        This test catches the silent-failure bug where BLOCK was being
        misclassified as NONE, causing PII to flow through to the LLM.
        """
        # Simulate Bedrock BLOCK response: action=GUARDRAIL_INTERVENED, outputs=[]
        mock_bedrock.apply_guardrail.return_value = {
            'action': 'GUARDRAIL_INTERVENED',
            'outputs': [],  # ← empty = BLOCK, not ANONYMIZE
            'assessments': [{'piiEntitiesFilter': {'matchedEntities': [{'type': 'SSN'}]}}]
        }
        
        result = lambda_module.apply_guardrail("My SSN is 123-45-6789", source='INPUT')
        
        # Must report intervention (not NONE)
        assert result['action'] == lambda_module.GUARDRAIL_ACTION_BLOCK
        # Must return empty text (caller's `if not text:` check depends on this)
        assert result['text'] == ''
        # Must include assessments for audit trail
        assert len(result['assessments']) == 1
    
    def test_anonymize_case_returns_sanitized_text(self, lambda_module, mock_bedrock):
        """When guardrail ANONYMIZES content, apply_guardrail must return the sanitized text."""
        mock_bedrock.apply_guardrail.return_value = {
            'action': 'GUARDRAIL_INTERVENED',
            'outputs': [{'text': 'My name is [NAME]'}],  # ← sanitized output
            'assessments': [{'piiEntitiesFilter': {'matchedEntities': [{'type': 'NAME'}]}}]
        }
        
        result = lambda_module.apply_guardrail("My name is John Smith", source='INPUT')
        
        assert result['action'] == lambda_module.GUARDRAIL_ACTION_ANONYMIZE
        assert result['text'] == 'My name is [NAME]'
        assert len(result['assessments']) == 1
    
    def test_pass_case_returns_original_text(self, lambda_module, mock_bedrock):
        """When guardrail passes content, apply_guardrail must return the original text unchanged."""
        mock_bedrock.apply_guardrail.return_value = {
            'action': 'NONE',
            'outputs': [],
            'assessments': []
        }
        
        original = "Server EXCH-SVR-01 is offline"
        result = lambda_module.apply_guardrail(original, source='INPUT')
        
        assert result['action'] == lambda_module.GUARDRAIL_ACTION_NONE
        assert result['text'] == original
        assert result['assessments'] == []
    
    def test_guardrail_not_configured_returns_none(self, lambda_module):
        """When guardrail is not configured, apply_guardrail must return NONE with original text."""
        # Clear guardrail config
        lambda_module.GUARDRAIL_ID = None
        lambda_module.GUARDRAIL_VERSION = None
        
        original = "Some text"
        result = lambda_module.apply_guardrail(original, source='INPUT')
        
        assert result['action'] == lambda_module.GUARDRAIL_ACTION_NONE
        assert result['text'] == original
    
    def test_block_on_output_returns_empty_text(self, lambda_module, mock_bedrock):
        """BLOCK on OUTPUT must also return empty text."""
        mock_bedrock.apply_guardrail.return_value = {
            'action': 'GUARDRAIL_INTERVENED',
            'outputs': [],
            'assessments': [{'topicPolicy': {'blockedTopics': [{'topicName': 'Alarming-Content'}]}}]
        }
        
        result = lambda_module.apply_guardrail(
            "Catastrophic failure imminent!",
            source='OUTPUT'
        )
        
        assert result['action'] == lambda_module.GUARDRAIL_ACTION_BLOCK
        assert result['text'] == ''


# ==============================================================================
# END-TO-END TESTS: Full pipeline behavior
# ==============================================================================

class TestEndToEndGuardrailBehavior:
    """End-to-end tests verifying the full pipeline handles each guardrail state correctly."""
    
    def test_block_on_input_causes_ticket_failure(self, lambda_module, mock_http, mock_bedrock):
        """
        CRITICAL TEST: When input guardrail BLOCKS, the ticket must fail and go to DLQ.
        
        This verifies the fix: previously, BLOCK was misclassified as NONE,
        causing the ticket to process "successfully" with PII flowing to the LLM.
        """
        # Input guardrail BLOCKS (no sanitized output)
        mock_bedrock.apply_guardrail.return_value = {
            'action': 'GUARDRAIL_INTERVENED',
            'outputs': [],
            'assessments': [{'sensitiveInformationPolicy': {'matchedEntities': [{'type': 'SSN'}]}}]
        }
        
        event = {"Records": [{"body": json.dumps({"ticket_id": "12345"}), "messageId": "msg-1"}]}
        result = lambda_module.lambda_handler(event, None)
        
        # Must be reported as batch failure → goes to DLQ
        assert len(result["batchItemFailures"]) == 1
        # LLM must NOT have been called
        mock_bedrock.invoke_model.assert_not_called()
    
    def test_anonymize_on_input_proceeds_with_sanitized_text(self, lambda_module, mock_http, mock_bedrock):
        """When input guardrail ANONYMIZES, the ticket must proceed with sanitized text."""
        # Input guardrail ANONYMIZES
        mock_bedrock.apply_guardrail.side_effect = [
            # INPUT: anonymize
            {
                'action': 'GUARDRAIL_INTERVENED',
                'outputs': [{'text': 'Analyze ticket with [NAME] and [EMAIL]'}],
                'assessments': [{'piiEntitiesFilter': {'matchedEntities': [{'type': 'NAME'}, {'type': 'EMAIL'}]}}]
            },
            # OUTPUT: pass
            {'action': 'NONE', 'outputs': [], 'assessments': []}
        ]
        
        event = {"body": json.dumps({"ticket_id": "12345"})}
        result = lambda_module.lambda_handler(event, None)
        
        assert result["statusCode"] == 200
        
        # Verify invoke_model was called with the SANITIZED prompt
        invoke_call = mock_bedrock.invoke_model.call_args
        body = json.loads(invoke_call.kwargs["body"])
        user_content = body["messages"][0]["content"]
        assert "[NAME]" in user_content or "[EMAIL]" in user_content
    
    def test_block_on_output_causes_ticket_failure(self, lambda_module, mock_http, mock_bedrock):
        """When output guardrail BLOCKS, the ticket must fail."""
        mock_bedrock.apply_guardrail.side_effect = [
            # INPUT: pass
            {'action': 'NONE', 'outputs': [], 'assessments': []},
            # OUTPUT: block
            {
                'action': 'GUARDRAIL_INTERVENED',
                'outputs': [],
                'assessments': [{'topicPolicy': {'blockedTopics': [{'topicName': 'Alarming-Content'}]}}]
            }
        ]
        
        event = {"Records": [{"body": json.dumps({"ticket_id": "12345"}), "messageId": "msg-1"}]}
        result = lambda_module.lambda_handler(event, None)
        
        # Must fail
        assert len(result["batchItemFailures"]) == 1
    
    def test_anonymize_on_output_proceeds_with_sanitized_text(self, lambda_module, mock_http, mock_bedrock):
        """When output guardrail ANONYMIZES, the ticket must proceed with sanitized text."""
        mock_bedrock.apply_guardrail.side_effect = [
            # INPUT: pass
            {'action': 'NONE', 'outputs': [], 'assessments': []},
            # OUTPUT: anonymize
            {
                'action': 'GUARDRAIL_INTERVENED',
                'outputs': [{'text': json.dumps({
                    "summary": "Issue for [NAME]",
                    "category": "Software",
                    "priority": "High",
                    "extracted_entities": {},
                    "draft_internal_notes": "ok",
                    "confidence_score": 0.9
                })}],
                'assessments': []
            }
        ]
        
        event = {"body": json.dumps({"ticket_id": "12345"})}
        result = lambda_module.lambda_handler(event, None)
        
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "[NAME]" in body["data"]["summary"]
    
    def test_pass_through_processes_normally(self, lambda_module, mock_http, mock_bedrock):
        """When guardrail passes, the ticket must process normally."""
        # Both input and output pass
        mock_bedrock.apply_guardrail.return_value = {
            'action': 'NONE',
            'outputs': [],
            'assessments': []
        }
        
        event = {"body": json.dumps({"ticket_id": "12345"})}
        result = lambda_module.lambda_handler(event, None)
        
        assert result["statusCode"] == 200
        # LLM should have been called once
        assert mock_bedrock.invoke_model.call_count == 1


# ==============================================================================
# METRICS TESTS: Verify correct counting of interventions vs blocks
# ==============================================================================

class TestMetricsCounting:
    """Tests verifying that guardrail interventions and blocks are counted correctly."""
    
    def test_anonymize_increments_interventions_counter(self, lambda_module, mock_http, mock_bedrock, mock_aws_services):
        """ANONYMIZE events should increment the guardrail_interventions counter."""
        # Both input and output anonymize
        mock_bedrock.apply_guardrail.side_effect = [
            {
                'action': 'GUARDRAIL_INTERVENED',
                'outputs': [{'text': 'Sanitized input'}],
                'assessments': []
            },
            {
                'action': 'GUARDRAIL_INTERVENED',
                'outputs': [{'text': json.dumps({
                    "summary": "ok", "category": "Software", "priority": "High",
                    "extracted_entities": {}, "draft_internal_notes": "ok", "confidence_score": 0.9
                })}],
                'assessments': []
            }
        ]
        
        event = {"body": json.dumps({"ticket_id": "12345"})}
        lambda_module.lambda_handler(event, None)
        
        # Verify metrics record has interventions = 2 (one input, one output)
        table = mock_aws_services["dynamodb"].Table("test-metrics")
        item = table.get_item(Key={"ticket_id": "12345"})["Item"]
        assert item["guardrail_interventions"] == 2
        assert item["guardrail_blocks"] == 0
    
    def test_block_does_not_increment_interventions_counter(self, lambda_module, mock_http, mock_bedrock, mock_aws_services):
        """
        BLOCK events should NOT increment the guardrail_interventions counter.
        
        This is important: BLOCKs represent failures, not sanitizations.
        They should be tracked separately.
        """
        # Input guardrail BLOCKS
        mock_bedrock.apply_guardrail.return_value = {
            'action': 'GUARDRAIL_INTERVENED',
            'outputs': [],
            'assessments': []
        }
        
        event = {"Records": [{"body": json.dumps({"ticket_id": "12345"}), "messageId": "msg-1"}]}
        lambda_module.lambda_handler(event, None)
        
        # Ticket should have failed, so no metrics record should be written
        table = mock_aws_services["dynamodb"].Table("test-metrics")
        response = table.get_item(Key={"ticket_id": "12345"})
        assert "Item" not in response  # No metrics record for failed tickets


# ==============================================================================
# REGRESSION TESTS: Ensure the bug doesn't come back
# ==============================================================================

class TestRegressionPrevention:
    """Tests specifically designed to prevent the original bug from recurring."""
    
    def test_empty_outputs_means_block_not_pass(self, lambda_module, mock_bedrock):
        """
        Regression test: empty outputs with GUARDRAIL_INTERVENED action must be BLOCK,
        not pass-through. This was the original bug.
        """
        mock_bedrock.apply_guardrail.return_value = {
            'action': 'GUARDRAIL_INTERVENED',
            'outputs': [],  # Empty outputs
            'assessments': [{'piiEntitiesFilter': {'matchedEntities': [{'type': 'SSN'}]}}]
        }
        
        result = lambda_module.apply_guardrail("SSN: 123-45-6789", source='INPUT')
        
        # Must NOT be NONE (the bug)
        assert result['action'] != lambda_module.GUARDRAIL_ACTION_NONE
        # Must be BLOCK
        assert result['action'] == lambda_module.GUARDRAIL_ACTION_BLOCK
        # Must have empty text
        assert result['text'] == ''
    
    def test_non_empty_outputs_means_anonymize(self, lambda_module, mock_bedrock):
        """Regression test: non-empty outputs with GUARDRAIL_INTERVENED must be ANONYMIZE."""
        mock_bedrock.apply_guardrail.return_value = {
            'action': 'GUARDRAIL_INTERVENED',
            'outputs': [{'text': 'Sanitized: [NAME]'}],
            'assessments': []
        }
        
        result = lambda_module.apply_guardrail("Name: John", source='INPUT')
        
        assert result['action'] == lambda_module.GUARDRAIL_ACTION_ANONYMIZE
        assert result['text'] == 'Sanitized: [NAME]'
    
    def test_action_none_means_pass_through(self, lambda_module, mock_bedrock):
        """Regression test: action=NONE must mean pass-through, regardless of outputs."""
        mock_bedrock.apply_guardrail.return_value = {
            'action': 'NONE',
            'outputs': [],
            'assessments': []
        }
        
        original = "Normal ticket content"
        result = lambda_module.apply_guardrail(original, source='INPUT')
        
        assert result['action'] == lambda_module.GUARDRAIL_ACTION_NONE
        assert result['text'] == original