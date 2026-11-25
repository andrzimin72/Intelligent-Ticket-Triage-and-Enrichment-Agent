"""Integration test: Verify tenant data isolation."""
import pytest
import boto3
import json


def test_tenant_data_isolation():
    """Verify that tenant A cannot access tenant B's data."""
    
    # Setup: Create two test tenants
    tenants = ['test-tenant-alpha', 'test-tenant-beta']
    
    for tenant_id in tenants:
        # Create tenant record
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('dev-msp-triage-tenant-registry')
        table.put_item(Item={
            'tenant_id': tenant_id,
            'entra_tenant_id': f'11111111-1111-1111-1111-{tenant_id[-12:]}',
            'status': 'active',
            'enabled': 1
        })
        
        # Create tenant-specific data
        table = dynamodb.Table('dev-msp-triage-agent-audit-log')
        table.put_item(Item={
            'audit_id': f'audit-{tenant_id}-001',
            'timestamp': '2026-11-23T10:00:00Z',
            'tenant_id': tenant_id,
            'user_id': f'user-{tenant_id}',
            'operation': 'test_operation'
        })
    
    # Test: Query tenant A's data
    table = dynamodb.Table('dev-msp-triage-agent-audit-log')
    response = table.scan(
        FilterExpression='tenant_id = :tid',
        ExpressionAttributeValues={':tid': 'test-tenant-alpha'}
    )
    
    items = response.get('Items', [])
    assert len(items) == 1
    assert items[0]['tenant_id'] == 'test-tenant-alpha'
    
    # Verify tenant B's data is not included
    for item in items:
        assert item['tenant_id'] != 'test-tenant-beta'
    
    # Test: Attempt cross-tenant access (should fail)
    # Simulate tenant A trying to access tenant B's audit log
    with pytest.raises(Exception) as exc_info:
        tenant_resolver.verify_tenant_access(
            requesting_tenant='test-tenant-alpha',
            target_tenant='test-tenant-beta'
        )
    
    assert 'access_denied' in str(exc_info.value)
    
    # Cleanup
    for tenant_id in tenants:
        table = dynamodb.Table('dev-msp-triage-tenant-registry')
        table.delete_item(Key={'tenant_id': tenant_id})