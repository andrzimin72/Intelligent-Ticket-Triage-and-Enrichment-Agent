import json
import pytest
from unittest.mock import patch


def test_simple_ticket_routes_to_haiku(lambda_module, mock_http, mock_bedrock):
    """Tickets matching simple patterns should use Haiku."""
    # Mock a simple ticket
    def side_effect(url, headers, method="GET", data=None):
        if "/service/tickets?" in url:
            return [{
                "id": 12345,
                "summary": "Password reset request",
                "description": "User forgot their password",
                "company": {"id": 99},
                "customFields": []
            }]
        if "/activities" in url and method == "GET":
            return []
        return {}
    
    mock_http.side_effect = side_effect
    
    # Haiku succeeds
    mock_bedrock.invoke_model.return_value = {
        "body": _make_bedrock_body({
            "summary": "User needs password reset",
            "category": "User Request",
            "priority": "Low",
            "extracted_entities": {},
            "draft_internal_notes": "Reset password per SOP",
            "confidence_score": 0.95
        })
    }
    
    event = {"body": json.dumps({"ticket_id": "12345"})}
    result = lambda_module.lambda_handler(event, None)
    
    assert result["statusCode"] == 200
    
    # Verify Haiku was called (not Sonnet)
    call_args = mock_bedrock.invoke_model.call_args
    assert lambda_module.HAIKU_MODEL_ID in call_args.kwargs.get('modelId', '')


def test_complex_ticket_routes_to_sonnet(lambda_module, mock_http, mock_bedrock):
    """Tickets with error codes/hostnames should use Sonnet."""
    def side_effect(url, headers, method="GET", data=None):
        if "/service/tickets?" in url:
            return [{
                "id": 12345,
                "summary": "Exchange Server Offline",
                "description": "EXCH-SVR-01 showing error 550 5.7.1",
                "company": {"id": 99},
                "customFields": []
            }]
        if "/activities" in url and method == "GET":
            return []
        return {}
    
    mock_http.side_effect = side_effect
    
    mock_bedrock.invoke_model.return_value = {
        "body": _make_bedrock_body({
            "summary": "Exchange server offline",
            "category": "Software",
            "priority": "High",
            "extracted_entities": {"hostname": "EXCH-SVR-01", "error_code": "550 5.7.1"},
            "draft_internal_notes": "Investigate Exchange",
            "confidence_score": 0.9
        })
    }
    
    event = {"body": json.dumps({"ticket_id": "12345"})}
    result = lambda_module.lambda_handler(event, None)
    
    assert result["statusCode"] == 200
    
    # Verify Sonnet was called (not Haiku)
    call_args = mock_bedrock.invoke_model.call_args
    assert lambda_module.MODEL_ID in call_args.kwargs.get('modelId', '')


def test_haiku_low_confidence_triggers_sonnet_rerun(lambda_module, mock_http, mock_bedrock):
    """If Haiku returns low confidence, ticket should be re-run with Sonnet."""
    def side_effect(url, headers, method="GET", data=None):
        if "/service/tickets?" in url:
            return [{
                "id": 12345,
                "summary": "Password reset",
                "description": "Simple request",
                "company": {"id": 99},
                "customFields": []
            }]
        if "/activities" in url and method == "GET":
            return []
        return {}
    
    mock_http.side_effect = side_effect
    
    # First call (Haiku): low confidence
    # Second call (Sonnet): high confidence
    mock_bedrock.invoke_model.side_effect = [
        {
            "body": _make_bedrock_body({
                "summary": "unclear",
                "category": "User Request",
                "priority": "Medium",
                "extracted_entities": {},
                "draft_internal_notes": "Needs review",
                "confidence_score": 0.4  # Below threshold
            })
        },
        {
            "body": _make_bedrock_body({
                "summary": "Password reset for user",
                "category": "User Request",
                "priority": "Low",
                "extracted_entities": {},
                "draft_internal_notes": "Reset per SOP",
                "confidence_score": 0.92
            })
        }
    ]
    
    event = {"body": json.dumps({"ticket_id": "12345"})}
    result = lambda_module.lambda_handler(event, None)
    
    assert result["statusCode"] == 200
    # Should have been called twice (Haiku then Sonnet)
    assert mock_bedrock.invoke_model.call_count == 2


def test_cost_optimization_can_be_disabled(lambda_module, mock_http, mock_bedrock):
    """When ENABLE_COST_OPTIMIZATION is false, all tickets use Sonnet."""
    with patch.dict('os.environ', {'ENABLE_COST_OPTIMIZATION': 'false'}):
        import importlib
        importlib.reload(lambda_module)
    
    def side_effect(url, headers, method="GET", data=None):
        if "/service/tickets?" in url:
            return [{
                "id": 12345,
                "summary": "Password reset",
                "description": "Simple",
                "company": {"id": 99},
                "customFields": []
            }]
        if "/activities" in url and method == "GET":
            return []
        return {}
    
    mock_http.side_effect = side_effect
    
    mock_bedrock.invoke_model.return_value = {
        "body": _make_bedrock_body({
            "summary": "ok", "category": "User Request", "priority": "Low",
            "extracted_entities": {}, "draft_internal_notes": "ok", "confidence_score": 0.9
        })
    }
    
    event = {"body": json.dumps({"ticket_id": "12345"})}
    lambda_module.lambda_handler(event, None)
    
    # Should have used Sonnet even for simple ticket
    call_args = mock_bedrock.invoke_model.call_args
    assert lambda_module.MODEL_ID in call_args.kwargs.get('modelId', '')


def test_complexity_classifier():
    """Unit tests for the complexity classifier."""
    import sys
    sys.path.insert(0, 'src')
    import lambda_function
    
    # Simple ticket
    assert lambda_function.classify_ticket_complexity({
        "subject": "Password reset",
        "description": "User forgot password",
        "email_thread": ""
    }) == 'simple'
    
    # Complex ticket (hostname)
    assert lambda_function.classify_ticket_complexity({
        "subject": "Server down",
        "description": "EXCH-SVR-01 is offline",
        "email_thread": ""
    }) == 'complex'
    
    # Complex ticket (error code)
    assert lambda_function.classify_ticket_complexity({
        "subject": "Error",
        "description": "Getting error 550 5.7.1",
        "email_thread": ""
    }) == 'complex'
    
    # Complex ticket (security)
    assert lambda_function.classify_ticket_complexity({
        "subject": "Malware detected",
        "description": "Antivirus found ransomware",
        "email_thread": ""
    }) == 'complex'
    
    # Unknown (short, no indicators)
    assert lambda_function.classify_ticket_complexity({
        "subject": "Help",
        "description": "Need assistance",
        "email_thread": ""
    }) == 'unknown'


def _make_bedrock_body(data):
    import io
    return io.BytesIO(json.dumps({
        "content": [{"text": json.dumps(data)}]
    }).encode("utf-8"))