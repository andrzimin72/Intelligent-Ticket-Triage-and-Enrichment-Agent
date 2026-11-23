import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock


def test_write_metrics_record(lambda_module, mock_aws_services):
    """Verify metrics record is written to DynamoDB after enrichment."""
    # Create metrics table
    dynamodb = mock_aws_services["dynamodb"]
    dynamodb.create_table(
        TableName="test-metrics",
        KeySchema=[{"AttributeName": "ticket_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "ticket_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST"
    )
    
    # Set environment variable
    with patch.dict('os.environ', {'METRICS_TABLE': 'test-metrics'}):
        import importlib
        importlib.reload(lambda_module)
    
    # Simulate enrichment
    enrichment_data = {
        "category": "Software",
        "priority": "High",
        "confidence_score": 0.92
    }
    
    lambda_module.write_metrics_record(
        ticket_id="12345",
        customer_id="CUST-99",
        enrichment_data=enrichment_data,
        model_id="claude-sonnet-5-5-v1:0",
        processing_duration_ms=1500,
        guardrail_interventions=1
    )
    
    # Verify record was written
    table = dynamodb.Table("test-metrics")
    item = table.get_item(Key={"ticket_id": "12345"})["Item"]
    
    assert item["ai_category"] == "Software"
    assert item["ai_priority"] == "High"
    assert item["ai_confidence_score"] == 0.92
    assert item["processing_duration_ms"] == 1500
    assert item["guardrail_interventions"] == 1


def test_calculate_metrics():
    """Verify metrics calculation logic."""
    import sys
    sys.path.insert(0, 'src_metrics_reporter')
    import metrics_reporter
    
    records = [
        {"ticket_id": "1", "ai_category": "Software", "ai_confidence_score": 0.9, "processing_duration_ms": 1000, "guardrail_interventions": 0},
        {"ticket_id": "2", "ai_category": "Network", "ai_confidence_score": 0.8, "processing_duration_ms": 1500, "guardrail_interventions": 1},
        {"ticket_id": "3", "ai_category": "Software", "ai_confidence_score": 0.95, "processing_duration_ms": 1200, "guardrail_interventions": 0},
    ]
    
    feedback_map = {
        "1": "Correct",
        "2": "Incorrect",
        "3": "Correct"
    }
    
    metrics = metrics_reporter.calculate_metrics(records, feedback_map)
    
    assert metrics["total_tickets"] == 3
    assert metrics["accuracy_rate"] == 66.67  # 2 correct out of 3 feedback
    assert metrics["avg_confidence"] == 0.883  # (0.9 + 0.8 + 0.95) / 3
    assert metrics["avg_processing_time_ms"] == 1233  # (1000 + 1500 + 1200) / 3
    assert metrics["guardrail_interventions"] == 1
    assert metrics["top_categories"][0][0] == "Software"  # Most common
    assert metrics["tickets_with_feedback"] == 3


def test_format_email_report():
    """Verify HTML report formatting."""
    import sys
    sys.path.insert(0, 'src_metrics_reporter')
    import metrics_reporter
    
    metrics = {
        "total_tickets": 100,
        "accuracy_rate": 85.5,
        "avg_confidence": 0.88,
        "avg_processing_time_ms": 1500,
        "guardrail_interventions": 15,
        "top_categories": [("Software", 40), ("Network", 30), ("Hardware", 20)],
        "feedback_breakdown": {"Correct": 85, "Incorrect": 15},
        "tickets_with_feedback": 100,
        "tickets_without_feedback": 0
    }
    
    start_date = datetime(2026, 11, 7)
    end_date = datetime(2026, 11, 14)
    
    html = metrics_reporter.format_email_report(metrics, start_date, end_date)
    
    assert "100" in html  # Total tickets
    assert "85.5%" in html  # Accuracy rate
    assert "Software" in html  # Top category
    assert "Correct" in html  # Feedback breakdown