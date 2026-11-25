"""Test data management utilities."""
import boto3
import json
import pytest


@pytest.fixture(scope='session')
def test_data_manager():
    """Manage test data lifecycle."""
    manager = TestDataManager()
    yield manager
    manager.cleanup()


class TestDataManager:
    """Manage test data creation and cleanup."""
    
    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb')
        self.s3_client = boto3.client('s3')
        self.created_resources = []
    
    def create_test_tenant(self, tenant_id):
        """Create a test tenant."""
        table = self.dynamodb.Table('dev-msp-triage-tenant-registry')
        table.put_item(Item={
            'tenant_id': tenant_id,
            'status': 'active',
            'entra_tenant_id': f'11111111-1111-1111-1111-{tenant_id[-12:]}',
        })
        self.created_resources.append(('tenant', tenant_id))
    
    def create_test_data(self, tenant_id, data_type, data):
        """Create test data for a tenant."""
        if data_type == 'audit_log':
            table = self.dynamodb.Table('dev-msp-triage-agent-audit-log')
            table.put_item(Item=data)
        elif data_type == 's3_object':
            self.s3_client.put_object(
                Bucket='dev-msp-triage-agent-schemas',
                Key=f'tenants/{tenant_id}/{data["key"]}',
                Body=data['body']
            )
        
        self.created_resources.append((data_type, tenant_id, data))
    
    def cleanup(self):
        """Clean up all created test data."""
        for resource in reversed(self.created_resources):
            try:
                if resource[0] == 'tenant':
                    table = self.dynamodb.Table('dev-msp-triage-tenant-registry')
                    table.delete_item(Key={'tenant_id': resource[1]})
                elif resource[0] == 'audit_log':
                    table = self.dynamodb.Table('dev-msp-triage-agent-audit-log')
                    table.delete_item(Key={
                        'audit_id': resource[2]['audit_id'],
                        'timestamp': resource[2]['timestamp']
                    })
                elif resource[0] == 's3_object':
                    self.s3_client.delete_object(
                        Bucket='dev-msp-triage-agent-schemas',
                        Key=f'tenants/{resource[1]}/{resource[2]["key"]}'
                    )
            except Exception as e:
                print(f"Cleanup error: {e}")