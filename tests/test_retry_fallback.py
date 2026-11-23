import json
import pytest
from unittest.mock import patch, MagicMock
from botocore.exceptions import ClientError


def test_retry_on_throttling_error(lambda_module, mock_http, mock_bedrock):
    """Verify that throttling errors trigger retries."""
    # First two calls fail with throttling, third succeeds
    throttling_error = ClientError(
        {'Error': {'Code': 'ThrottlingException', 'Message': 'Rate exceeded'}},
        'InvokeModel'
    )
    
    mock_bedrock.invoke_model.side_effect = [
        throttling_error,
        throttling_error,
        {
            "body": _make_bedrock_body({
                "summary": "ok", "category": "Software", "priority": "High",
                "extracted_entities": {}, "draft_internal_notes": "ok", "confidence_score": 0.9
            })
        }
    ]
    
    event = {"body": json.dumps({"ticket_id": "12345"})}
    result = lambda_module.lambda_handler(event, None)
    
    assert result["statusCode"] == 200
    # Should have been called 3 times (2 retries + 1 success)
    assert mock_bedrock.invoke_model.call_count == 3


def test_no_retry_on_validation_error(lambda_module, mock_http, mock_bedrock):
    """Verify that validation errors fail immediately without retry."""
    validation_error = ClientError(
        {'Error': {'Code': 'ValidationException', 'Message': 'Invalid input'}},
        'InvokeModel'
    )
    
    mock_bedrock.invoke_model.side_effect = validation_error
    
    event = {"Records": [{"body": json.dumps({"ticket_id": "12345"}), "messageId": "msg-1"}]}
    result = lambda_module.lambda_handler(event, None)
    
    # Should fail immediately
    assert len(result["batchItemFailures"]) == 1
    # Should have been called only once (no retries)
    assert mock_bedrock.invoke_model.call_count == 1


def test_fallback_triggered_when_primary_fails(lambda_module, mock_http, mock_bedrock):
    """Verify that fallback model is used when primary model fails."""
    # Primary model fails with service unavailable
    service_error = ClientError(
        {'Error': {'Code': 'ServiceUnavailable', 'Message': 'Service unavailable'}},
        'InvokeModel'
    )
    
    # Make primary model always fail
    def side_effect(*args, **kwargs):
        model_id = kwargs.get('modelId')
        if model_id == lambda_module.MODEL_ID:
            raise service_error
        else:
            # Fallback model succeeds
            return {
                "body": _make_bedrock_body({
                    "summary": "ok", "category": "Software", "priority": "High",
                    "extracted_entities": {}, "draft_internal_notes": "ok", "confidence_score": 0.9
                })
            }
    
    mock_bedrock.invoke_model.side_effect = side_effect
    
    event = {"body": json.dumps({"ticket_id": "12345"})}
    result = lambda_module.lambda_handler(event, None)
    
    assert result["statusCode"] == 200
    # Should have tried primary (3 times) then fallback (1 time)
    assert mock_bedrock.invoke_model.call_count == 4


def test_metrics_record_fallback_usage(lambda_module, mock_http, mock_bedrock, mock_aws_services):
    """Verify that metrics correctly record fallback usage."""
    # Create metrics table
    dynamodb = mock_aws_services["dynamodb"]
    dynamodb.create_table(
        TableName="test-metrics",
        KeySchema=[{"AttributeName": "ticket_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "ticket_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST"
    )
    
    with patch.dict('os.environ', {'METRICS_TABLE': 'test-metrics'}):
        import importlib
        importlib.reload(lambda_module)
    
    # Make primary fail, fallback succeed
    service_error = ClientError(
        {'Error': {'Code': 'ServiceUnavailable', 'Message': 'Service unavailable'}},
        'InvokeModel'
    )
    
    def side_effect(*args, **kwargs):
        model_id = kwargs.get('modelId')
        if model_id == lambda_module.MODEL_ID:
            raise service_error
        else:
            return {
                "body": _make_bedrock_body({
                    "summary": "ok", "category": "Software", "priority": "High",
                    "extracted_entities": {}, "draft_internal_notes": "ok", "confidence_score": 0.9
                })
            }
    
    mock_bedrock.invoke_model.side_effect = side_effect
    
    event = {"body": json.dumps({"ticket_id": "12345"})}
    lambda_module.lambda_handler(event, None)
    
    # Verify metrics record
    table = dynamodb.Table("test-metrics")
    item = table.get_item(Key={"ticket_id": "12345"})["Item"]
    
    assert item["fallback_triggered"] is True
    assert item["model_id_used"] == lambda_module.FALLBACK_MODEL_ID
    assert item["retry_count"] >= 3  # At least 3 retries on primary


def _make_bedrock_body(data):
    """Helper to build a Bedrock-shaped response body."""
    import io
    return io.BytesIO(json.dumps({
        "content": [{"text": json.dumps(data)}]
    }).encode("utf-8"))