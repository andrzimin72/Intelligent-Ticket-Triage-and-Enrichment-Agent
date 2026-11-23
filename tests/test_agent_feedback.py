"""
Tests for agent feedback loop.
"""

import json
import pytest
import sys
import os
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from moto import mock_aws
import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src_agent_feedback'))


@pytest.fixture
def aws_env():
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["FEEDBACK_TABLE"] = "test-agent-feedback"
    os.environ["FEEDBACK_RETENTION"] = "365"
    os.environ["AWS_REGION_NAME"] = "us-east-1"


@pytest.fixture
def aws_resources(aws_env):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        
        dynamodb.create_table(
            TableName="test-agent-feedback",
            KeySchema=[{"AttributeName": "feedback_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "feedback_id", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[{
                "IndexName": "status-index",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )
        
        yield {"dynamodb": dynamodb}


def test_store_thumbs_up_feedback(aws_resources):
    """Test storing positive feedback."""
    import agent_feedback
    
    feedback_data = {
        'feedback_type': 'thumbs_up',
        'user_aad_id': 'user-123',
        'user_name': 'John Doe',
        'session_id': 'session-abc',
        'agent_response': 'Your calendar is clear tomorrow at 2pm.',
        'user_message': 'When am I free tomorrow?',
        'tools_called': [{'tool': '/list-my-calendar', 'parameters': {}}],
    }
    
    result = agent_feedback.lambda_handler({
        'body': json.dumps({'feedback_data': feedback_data})
    }, None)
    
    assert result['statusCode'] == 200
    body = json.loads(result['body'])
    assert 'feedback_id' in body
    
    # Verify stored in DynamoDB
    table = aws_resources["dynamodb"].Table("test-agent-feedback")
    item = table.get_item(Key={'feedback_id': body['feedback_id']})['Item']
    assert item['feedback_type'] == 'thumbs_up'
    assert item['status'] == 'pending_review'


def test_store_detailed_feedback(aws_resources):
    """Test storing detailed correction feedback."""
    import agent_feedback
    
    feedback_data = {
        'feedback_type': 'thumbs_down',
        'user_aad_id': 'user-123',
        'session_id': 'session-abc',
        'agent_response': 'I booked Conference Room A for you.',
        'user_message': 'Find me a 30-minute slot tomorrow',
        'tools_called': [{'tool': '/request-room-booking', 'parameters': {}}],
        'error_category': 'wrong_tool',
        'correction_text': 'Should have called find_free_time, not booked a room',
        'expected_tool': '/find-free-time',
        'expected_parameters': '{"duration_minutes": 30}',
    }
    
    result = agent_feedback.lambda_handler({
        'body': json.dumps({'feedback_data': feedback_data})
    }, None)
    
    assert result['statusCode'] == 200
    body = json.loads(result['body'])
    
    # Verify stored with all details
    table = aws_resources["dynamodb"].Table("test-agent-feedback")
    item = table.get_item(Key={'feedback_id': body['feedback_id']})['Item']
    assert item['error_category'] == 'wrong_tool'
    assert 'find_free_time' in item['correction_text']
    assert item['expected_tool'] == '/find-free-time'


def test_invalid_error_category_rejected(aws_resources):
    """Test that invalid error categories are rejected."""
    import agent_feedback
    
    feedback_data = {
        'feedback_type': 'thumbs_down',
        'user_aad_id': 'user-123',
        'session_id': 'session-abc',
        'agent_response': 'test',
        'error_category': 'invalid_category',
    }
    
    result = agent_feedback.lambda_handler({
        'body': json.dumps({'feedback_data': feedback_data})
    }, None)
    
    assert result['statusCode'] == 400
    body = json.loads(result['body'])
    assert 'Invalid error_category' in body['error']


def test_missing_required_fields_rejected(aws_resources):
    """Test that missing required fields are rejected."""
    import agent_feedback
    
    feedback_data = {
        'feedback_type': 'thumbs_up',
        # Missing user_aad_id, session_id, agent_response
    }
    
    result = agent_feedback.lambda_handler({
        'body': json.dumps({'feedback_data': feedback_data})
    }, None)
    
    assert result['statusCode'] == 400
    body = json.loads(result['body'])
    assert 'Missing required fields' in body['error']