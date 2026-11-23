import json
import pytest
from unittest.mock import patch, MagicMock


def test_feedback_collector_finds_incorrect_tickets(lambda_module, mock_aws_services):
    """Verify the collector identifies Incorrect tickets from ConnectWise."""
    # Setup: Create a metrics record for a ticket
    metrics_table = mock_aws_services["dynamodb"].Table("test-metrics")
    metrics_table.put_item(Item={
        "ticket_id": "12345",
        "timestamp": "2026-11-14T10:00:00Z",
        "ai_category": "Security",
        "ai_priority": "High",
        "ai_confidence_score": 0.92,
        "model_id_used": "claude-sonnet-5-5-v1:0",
        "complexity": "complex"
    })
    
    # Mock ConnectWise to return "Incorrect" for this ticket
    with patch('feedback_collector.make_api_request') as mock_req:
        def side_effect(url, headers, method="GET"):
            if "/service/tickets/12345" in url:
                return {
                    "id": 12345,
                    "summary": "Test ticket",
                    "description": "Test",
                    "company": {"id": 99},
                    "priority": {"name": "Low"},
                    "customFields": [
                        {"id": 999, "value": "Incorrect"},  # AI Accuracy
                        {"id": 998, "value": "This was a routine lockout, not a breach"}  # Correction Notes
                    ]
                }
            return {}
        
        mock_req.side_effect = side_effect
        
        # Run the collector
        result = feedback_collector.lambda_handler({}, None)
        
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["incorrect_collected"] == 1
        
        # Verify feedback record was stored
        feedback_table = mock_aws_services["dynamodb"].Table("test-feedback")
        item = feedback_table.get_item(Key={"ticket_id": "12345"})["Item"]
        assert item["status"] == "pending_review"
        assert "routine lockout" in item["correction_notes"]


def test_few_shot_examples_loaded_from_s3(lambda_module, mock_aws_services):
    """Verify few-shot examples are loaded from S3 and cached."""
    # Setup: Create S3 bucket with examples
    s3 = mock_aws_services["s3"]
    s3.create_bucket(Bucket="test-few-shot")
    s3.put_object(
        Bucket="test-few-shot",
        Key="examples.json",
        Body=json.dumps([{
            "id": "12345",
            "input_summary": "Password reset for locked account",
            "output": {"category": "User Request", "priority": "Low"},
            "rationale": "Routine lockout, not security"
        }])
    )
    
    with patch.dict('os.environ', {
        'FEW_SHOT_EXAMPLES_BUCKET': 'test-few-shot',
        'FEW_SHOT_EXAMPLES_KEY': 'examples.json',
        'MAX_FEW_SHOT_EXAMPLES': '5'
    }):
        import importlib
        importlib.reload(lambda_module)
        
        examples = lambda_module.load_few_shot_examples()
        
        assert len(examples) == 1
        assert examples[0]["rationale"] == "Routine lockout, not security"


def test_few_shot_examples_cached(lambda_module, mock_aws_services):
    """Verify few-shot examples are cached and not re-read from S3 on every call."""
    s3 = mock_aws_services["s3"]
    s3.create_bucket(Bucket="test-few-shot")
    s3.put_object(
        Bucket="test-few-shot",
        Key="examples.json",
        Body=json.dumps([])
    )
    
    with patch.dict('os.environ', {
        'FEW_SHOT_EXAMPLES_BUCKET': 'test-few-shot',
        'FEW_SHOT_CACHE_TTL': '300'
    }):
        import importlib
        importlib.reload(lambda_module)
        
        # First call: loads from S3
        lambda_module.load_few_shot_examples()
        first_load_time = lambda_module._few_shot_cache['last_loaded']
        
        # Second call: should use cache (no S3 read)
        with patch.object(lambda_module.s3_client, 'get_object') as mock_s3:
            lambda_module.load_few_shot_examples()
            mock_s3.assert_not_called()  # S3 not called again
        
        # Cache timestamp should not have changed
        assert lambda_module._few_shot_cache['last_loaded'] == first_load_time