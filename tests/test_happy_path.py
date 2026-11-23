import json


def test_full_happy_path(lambda_module, mock_http, mock_aws_services):
    """End-to-end: ticket arrives, gets enriched, PSA is updated."""
    event = {"Records": [{"body": json.dumps({"ticket_id": "12345"}), "messageId": "msg-1"}]}

    result = lambda_module.lambda_handler(event, None)

    # Should succeed with no batch failures
    assert result == {"batchItemFailures": []}

    # Verify HTTP calls were made in the right order
    calls = mock_http.call_args_list
    assert len(calls) == 4  # CW ticket, CW activities, Ninja alerts, CW PATCH, CW POST
    # Actually 5 calls: CW ticket, CW activities, Ninja alerts, CW PATCH (custom fields), CW POST (activity)
    assert len(calls) == 5

    # Verify the PATCH payload contained our AI enrichment
    patch_call = [c for c in calls if c.kwargs.get("method") == "PATCH" or (len(c.args) > 2 and c.args[2] == "PATCH")][0]
    patch_payload = patch_call.kwargs.get("data") or patch_call[1].get("data")
    assert patch_payload["customFields"][0]["value"] == "Software"
    assert patch_payload["customFields"][1]["value"] == "High"

    # Verify DynamoDB record was created with COMPLETED status
    table = mock_aws_services["dynamodb"].Table(lambda_module.IDEMPOTENCY_TABLE)
    item = table.get_item(Key={"ticket_id": "12345"})["Item"]
    assert item["processing_status"] == "COMPLETED"
    assert "Software" in item["enrichment_data"]


def test_direct_invocation_path(lambda_module, mock_http):
    """Direct Lambda invocation (e.g., from CLI) also works."""
    event = {"body": json.dumps({"ticket_id": "12345"})}

    result = lambda_module.lambda_handler(event, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["data"]["category"] == "Software"
    assert body["data"]["confidence_score"] == 0.92