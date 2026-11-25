"""Unit tests for tenant resolution logic."""
import pytest
import json
from unittest.mock import MagicMock, patch
from moto import mock_dynamodb
import boto3

# Import module under test
import sys
sys.path.insert(0, 'src_shared')
import tenant_resolver


@pytest.fixture
def mock_dynamodb_table():
    """Set up mock DynamoDB table."""
    with mock_dynamodb():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        table = dynamodb.create_table(
            TableName='test-tenant-registry',
            KeySchema=[{'AttributeName': 'tenant_id', 'KeyType': 'HASH'}],
            AttributeDefinitions=[
                {'AttributeName': 'tenant_id', 'AttributeType': 'S'},
                {'AttributeName': 'entra_tenant_id', 'AttributeType': 'S'},
            ],
            GlobalSecondaryIndexes=[{
                'IndexName': 'entra-tenant-index',
                'KeySchema': [{'AttributeName': 'entra_tenant_id', 'KeyType': 'HASH'}],
                'Projection': {'ProjectionType': 'ALL'}
            }],
            BillingMode='PAY_PER_REQUEST'
        )
        
        # Insert test data
        table.put_item(Item={
            'tenant_id': 'test-tenant-alpha',
            'entra_tenant_id': '11111111-1111-1111-1111-111111111111',
            'status': 'active',
            'enabled': 1
        })
        
        yield table


def test_resolve_tenant_from_teams_activity_success(mock_dynamodb_table):
    """Test successful tenant resolution from Teams activity."""
    activity = {
        'channelData': {
            'tenant': {
                'id': '11111111-1111-1111-1111-111111111111'
            }
        }
    }
    
    with patch.object(tenant_resolver, 'TABLE_NAME', 'test-tenant-registry'):
        result = tenant_resolver.resolve_tenant_from_teams_activity(activity)
    
    assert result == 'test-tenant-alpha'


def test_resolve_tenant_from_teams_activity_missing_channel_data():
    """Test tenant resolution with missing channelData."""
    activity = {}
    result = tenant_resolver.resolve_tenant_from_teams_activity(activity)
    assert result is None


def test_resolve_tenant_from_teams_activity_unknown_tenant(mock_dynamodb_table):
    """Test tenant resolution with unknown Entra tenant ID."""
    activity = {
        'channelData': {
            'tenant': {
                'id': '99999999-9999-9999-9999-999999999999'
            }
        }
    }
    
    with patch.object(tenant_resolver, 'TABLE_NAME', 'test-tenant-registry'):
        result = tenant_resolver.resolve_tenant_from_teams_activity(activity)
    
    assert result is None


def test_resolve_tenant_from_teams_activity_disabled_tenant(mock_dynamodb_table):
    """Test tenant resolution with disabled tenant."""
    # Update tenant to disabled
    mock_dynamodb_table.update_item(
        Key={'tenant_id': 'test-tenant-alpha'},
        UpdateExpression='SET enabled = :e',
        ExpressionAttributeValues={':e': 0}
    )
    
    activity = {
        'channelData': {
            'tenant': {
                'id': '11111111-1111-1111-1111-111111111111'
            }
        }
    }
    
    with patch.object(tenant_resolver, 'TABLE_NAME', 'test-tenant-registry'):
        result = tenant_resolver.resolve_tenant_from_teams_activity(activity)
    
    assert result is None