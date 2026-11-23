import json
import time
from datetime import datetime, timedelta


def test_duplicate_ticket_is_skipped(lambda_module, mock_http):
    """Second invocation of the same ticket_id should be a no-op."""
    event = {"Records": [{"body": json.dumps({"ticket_id": "12345"}), "messageId": "msg-1"}]}

    # First call: processes normally
    result1 = lambda_module.lambda_handler(event, None)
    assert result1 == {"batchItemFailures": []}
    first_call_count = mock_http.call_count

    # Second call: should skip processing entirely
    result2 = lambda_module.lambda_handler(event, None)
    assert result2 == {"batchItemFailures": []}

    # HTTP call count should NOT have increased (no PSA/RMM/Bedrock calls)
    assert mock_http.call_count == first_call_count


def test_failed_ticket_can_be_retried(lambda_module, mock_http, mock_bedrock):
    """If processing fails, the idempotency record is deleted so retry works."""
    # Make the LLM fail on first call
    mock_bedrock.invoke_model.side_effect = Exception("Bedrock timeout")

    event = {"Records": [{"body": json.dumps({"ticket_id": "12345"}), "messageId": "msg-1"}]}

    # First call: fails
    result1 = lambda_module.lambda_handler(event, None)
    assert len(result1["batchItemFailures"]) == 1

    # Verify DynamoDB record was deleted (allows retry)
    table = lambda_module.dynamodb.Table(lambda_module.IDEMPOTENCY_TABLE)
    response = table.get_item(Key={"ticket_id": "12345"})
    assert "Item" not in response

    # Reset mock for successful retry
    mock_bedrock.invoke_model.side_effect = None
    mock_bedrock.invoke_model.return_value = {
        "body": _make_bedrock_body(lambda_module.HAPPY_PATH_LLM_RESPONSE if hasattr(lambda_module, "HAPPY_PATH_LLM_RESPONSE") else {
            "summary": "ok", "category": "Software", "priority": "High",
            "extracted_entities": {}, "draft_internal_notes": "ok", "confidence_score": 0.9
        })
    }

    # Second call: should succeed now
    result2 = lambda_module.lambda_handler(event, None)
    assert result2 == {"batchItemFailures": []}


def test_force_reprocess_clears_record(lambda_module, mock_http):
    """Direct invocation with force_reprocess=true should bypass idempotency."""
    # First, process normally
    event1 = {"body": json.dumps({"ticket_id": "12345"})}
    lambda_module.lambda_handler(event1, None)
    first_call_count = mock_http.call_count

    # Now force reprocess
    event2 = {"body": json.dumps({"ticket_id": "12345", "force_reprocess": True})}
    lambda_module.lambda_handler(event2, None)

    # HTTP calls should have been made again
    assert mock_http.call_count > first_call_count


def _make_bedrock_body(data):
    """Helper to build a Bedrock-shaped response body."""
    import io
    return io.BytesIO(json.dumps({
        "content": [{"text": json.dumps(data)}]
    }).encode("utf-8"))