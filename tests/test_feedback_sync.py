import json
import pytest
import sys
import os
from unittest.mock import patch, MagicMock
from datetime import datetime
from moto import mock_aws
import boto3


# Make the sync Lambda importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src_feedback_sync'))


@pytest.fixture
def aws_env():
    """Set up AWS credentials and environment variables."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["FEEDBACK_TABLE"] = "test-feedback"
    os.environ["FEW_SHOT_EXAMPLES_BUCKET"] = "test-few-shot"
    os.environ["FEW_SHOT_EXAMPLES_KEY"] = "examples.json"
    os.environ["MAX_FEW_SHOT_EXAMPLES"] = "5"
    os.environ["AWS_REGION_NAME"] = "us-east-1"


@pytest.fixture
def aws_resources(aws_env):
    """Create DynamoDB table and S3 bucket."""
    with mock_aws():
        # Create DynamoDB table
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName="test-feedback",
            KeySchema=[{"AttributeName": "ticket_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "ticket_id", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[{
                "IndexName": "status-index",
                "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )
        
        # Create S3 bucket
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-few-shot")
        
        yield {"dynamodb": dynamodb, "s3": s3, "table": table}


def _make_feedback_record(ticket_id, status="approved"):
    """Helper to create a feedback record."""
    return {
        "ticket_id": ticket_id,
        "status": status,
        "customer_id": "CUST-99",
        "timestamp": datetime.utcnow().isoformat(),
        "ai_output": json.dumps({
            "category": "Security",
            "priority": "High",
            "summary": "AI thought this was a breach",
            "draft_internal_notes": "Escalate to security team",
            "confidence_score": 0.95
        }),
        "human_correction": json.dumps({
            "current_priority": "Low",
            "correction_notes": "This was a routine account lockout, not a breach"
        }),
        "original_ticket_context": json.dumps({
            "subject": "Account locked",
            "description": "User says their account is locked"
        }),
        "correction_notes": "This was a routine account lockout, not a breach",
        "ai_model_used": "claude-sonnet-5-5-v1:0",
        "ai_confidence_score": 0.95,
        "complexity": "complex",
        "reviewed_by": "sara@yourmsp.com",
        "reviewed_at": datetime.utcnow().isoformat(),
    }


def test_sync_with_no_approved_records(aws_resources):
    """Sync should be a no-op when there are no approved records."""
    import feedback_sync
    import importlib
    importlib.reload(feedback_sync)
    
    result = feedback_sync.lambda_handler({}, None)
    
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["records_processed"] == 0
    assert body["examples_added"] == 0


def test_sync_converts_and_writes_examples(aws_resources):
    """Sync should convert approved records and write to S3."""
    table = aws_resources["table"]
    s3 = aws_resources["s3"]
    
    # Seed with an approved record
    table.put_item(Item=_make_feedback_record("12345", status="approved"))
    
    # Initialize existing examples.json
    s3.put_object(
        Bucket="test-few-shot",
        Key="examples.json",
        Body=b"[]"
    )
    
    import feedback_sync
    import importlib
    importlib.reload(feedback_sync)
    
    result = feedback_sync.lambda_handler({}, None)
    
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["records_approved"] == 1
    assert body["examples_converted"] == 1
    assert body["examples_injected"] == 1
    assert body["total_examples_in_s3"] == 1
    
    # Verify S3 was updated
    response = s3.get_object(Bucket="test-few-shot", Key="examples.json")
    examples = json.loads(response["Body"].read().decode("utf-8"))
    assert len(examples) == 1
    assert examples[0]["id"] == "12345"
    assert "routine account lockout" in examples[0]["rationale"]
    
    # Verify DynamoDB status was updated
    item = table.get_item(Key={"ticket_id": "12345"})["Item"]
    assert item["status"] == "injected"


def test_sync_deduplicates_by_ticket_id(aws_resources):
    """Sync should not add duplicate examples for the same ticket."""
    table = aws_resources["table"]
    s3 = aws_resources["s3"]
    
    # Seed S3 with an existing example for ticket 12345
    s3.put_object(
        Bucket="test-few-shot",
        Key="examples.json",
        Body=json.dumps([{
            "id": "12345",
            "input_summary": "Existing example",
            "output": {},
            "rationale": "Existing rationale",
            "added_at": "2026-01-01T00:00:00Z"
        }])
    )
    
    # Seed DynamoDB with the same ticket approved again
    table.put_item(Item=_make_feedback_record("12345", status="approved"))
    
    import feedback_sync
    import importlib
    importlib.reload(feedback_sync)
    
    result = feedback_sync.lambda_handler({}, None)
    
    body = json.loads(result["body"])
    assert body["examples_converted"] == 1
    # The existing example should be preserved, not duplicated
    assert body["total_examples_in_s3"] == 1
    
    # Verify S3 still has only one example
    response = s3.get_object(Bucket="test-few-shot", Key="examples.json")
    examples = json.loads(response["Body"].read().decode("utf-8"))
    assert len(examples) == 1
    # The existing one should win (preserves order)
    assert examples[0]["input_summary"] == "Existing example"


def test_sync_respects_max_limit(aws_resources):
    """Sync should trim examples to MAX_FEW_SHOT_EXAMPLES."""
    table = aws_resources["table"]
    s3 = aws_resources["s3"]
    
    # Seed S3 with 4 existing examples
    existing = [
        {
            "id": f"existing-{i}",
            "input_summary": f"Existing {i}",
            "output": {},
            "rationale": f"Rationale {i}",
            "added_at": f"2026-01-0{i}T00:00:00Z"
        }
        for i in range(1, 5)
    ]
    s3.put_object(
        Bucket="test-few-shot",
        Key="examples.json",
        Body=json.dumps(existing)
    )
    
    # Seed DynamoDB with 3 new approved records
    for i in range(1, 4):
        table.put_item(Item=_make_feedback_record(f"new-{i}", status="approved"))
    
    import feedback_sync
    import importlib
    importlib.reload(feedback_sync)
    
    result = feedback_sync.lambda_handler({}, None)
    
    body = json.loads(result["body"])
    # Total would be 4 + 3 = 7, but MAX is 5
    assert body["total_examples_in_s3"] == 5
    
    # Verify S3 has exactly 5 examples
    response = s3.get_object(Bucket="test-few-shot", Key="examples.json")
    examples = json.loads(response["Body"].read().decode("utf-8"))
    assert len(examples) == 5
    
    # Verify most recent examples are kept (new ones should be first)
    assert examples[0]["id"].startswith("new-")


def test_sync_skips_non_approved_records(aws_resources):
    """Sync should only process 'approved' records, not 'pending_review' or 'rejected'."""
    table = aws_resources["table"]
    s3 = aws_resources["s3"]
    
    s3.put_object(Bucket="test-few-shot", Key="examples.json", Body=b"[]")
    
    # Seed with mixed statuses
    table.put_item(Item=_make_feedback_record("approved-1", status="approved"))
    table.put_item(Item=_make_feedback_record("pending-1", status="pending_review"))
    table.put_item(Item=_make_feedback_record("rejected-1", status="rejected"))
    table.put_item(Item=_make_feedback_record("injected-1", status="injected"))
    
    import feedback_sync
    import importlib
    importlib.reload(feedback_sync)
    
    result = feedback_sync.lambda_handler({}, None)
    
    body = json.loads(result["body"])
    assert body["records_approved"] == 1
    assert body["examples_injected"] == 1
    
    # Verify only the approved one was updated
    approved_item = table.get_item(Key={"ticket_id": "approved-1"})["Item"]
    assert approved_item["status"] == "injected"
    
    pending_item = table.get_item(Key={"ticket_id": "pending-1"})["Item"]
    assert pending_item["status"] == "pending_review"  # Unchanged


def test_convert_to_few_shot_example():
    """Unit test for the conversion logic."""
    import feedback_sync
    
    record = _make_feedback_record("12345")
    example = feedback_sync.convert_to_few_shot_example(record)
    
    assert example["id"] == "12345"
    assert "Account locked" in example["input_summary"]
    assert example["output"]["priority"] == "Low"  # Human's priority
    assert example["output"]["category"] == "Security"  # AI's category (we don't have human's)
    assert "routine account lockout" in example["rationale"]
    assert "added_at" in example