import json
import urllib.error


def test_psa_api_failure_fails_gracefully(lambda_module, mock_http, mock_bedrock):
    """If ConnectWise API returns 500, Lambda should report batch failure."""
    def failing_side_effect(url, headers, method="GET", data=None):
        if "/service/tickets?" in url:
            raise urllib.error.HTTPError(url, 500, "Internal Server Error", {}, None)
        return {}

    mock_http.side_effect = failing_side_effect

    event = {"Records": [{"body": json.dumps({"ticket_id": "12345"}), "messageId": "msg-1"}]}
    result = lambda_module.lambda_handler(event, None)

    assert len(result["batchItemFailures"]) == 1
    # LLM should NOT have been called
    mock_bedrock.invoke_model.assert_not_called()


def test_rmm_failure_degrades_gracefully(lambda_module, mock_http, mock_bedrock):
    """If NinjaOne API fails, Lambda should still process the ticket (without RMM context)."""
    def partial_failure(url, headers, method="GET", data=None):
        if "/v2/alerts" in url:
            raise Exception("NinjaOne timeout")
        if "/service/tickets?" in url:
            return [{"id": 12345, "summary": "Test", "description": "Test", "company": {"id": 99}}]
        if "/activities" in url and method == "GET":
            return []
        if method == "PATCH":
            return {}
        if method == "POST":
            return {}
        return {}

    mock_http.side_effect = partial_failure

    event = {"body": json.dumps({"ticket_id": "12345"})}
    result = lambda_module.lambda_handler(event, None)

    # Should still succeed
    assert result["statusCode"] == 200
    # LLM should have been called (with empty RMM alerts)
    mock_bedrock.invoke_model.assert_called_once()


def test_llm_returns_invalid_json(lambda_module, mock_http, mock_bedrock):
    """If LLM returns malformed JSON, Lambda should fail gracefully."""
    mock_bedrock.invoke_model.return_value = {
        "body": _make_bytes_io({"content": [{"text": "not valid json at all"}]})
    }

    event = {"Records": [{"body": json.dumps({"ticket_id": "12345"}), "messageId": "msg-1"}]}
    result = lambda_module.lambda_handler(event, None)

    assert len(result["batchItemFailures"]) == 1


def test_llm_returns_markdown_wrapped_json(lambda_module, mock_http, mock_bedrock):
    """LLM sometimes wraps JSON in ```json ... ``` — parser should handle it."""
    wrapped_json = f"```json\n{json.dumps({
        'summary': 'ok', 'category': 'Software', 'priority': 'High',
        'extracted_entities': {}, 'draft_internal_notes': 'ok', 'confidence_score': 0.9
    })}\n```"
    mock_bedrock.invoke_model.return_value = {
        "body": _make_bytes_io({"content": [{"text": wrapped_json}]})
    }

    event = {"body": json.dumps({"ticket_id": "12345"})}
    result = lambda_module.lambda_handler(event, None)

    assert result["statusCode"] == 200


def test_low_confidence_adds_flag(lambda_module, mock_http, mock_bedrock):
    """Confidence < 0.7 should append a human-review flag to internal notes."""
    low_conf = {
        "summary": "unclear", "category": "User Request", "priority": "Medium",
        "extracted_entities": {}, "draft_internal_notes": "Needs review",
        "confidence_score": 0.4
    }
    mock_bedrock.invoke_model.return_value = {
        "body": _make_bytes_io({"content": [{"text": json.dumps(low_conf)}]})
    }

    event = {"body": json.dumps({"ticket_id": "12345"})}
    result = lambda_module.lambda_handler(event, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert "FLAG: Low confidence" in body["data"]["draft_internal_notes"]


def _make_bytes_io(data):
    import io
    return io.BytesIO(json.dumps(data).encode("utf-8"))