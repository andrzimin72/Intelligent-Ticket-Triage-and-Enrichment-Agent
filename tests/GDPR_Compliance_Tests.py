"""Compliance tests: GDPR compliance."""
import pytest


class TestGDPRCompliance:
    """Test GDPR compliance requirements."""
    
    def test_data_deletion_on_request(self):
        """Test complete data deletion on tenant deprovisioning."""
        # Create tenant with data
        tenant_id = 'gdpr-test-tenant'
        
        # Create tenant
        requests.post(
            f'{API_URL}/tenants',
            headers={'x-api-key': API_KEY},
            json={
                'tenant_id': tenant_id,
                'display_name': 'GDPR Test',
                'entra_tenant_id': '88888888-8888-8888-8888-888888888888',
                'admin_group_id': '22222222-2222-2222-2222-222222222222',
                'contact_email': 'admin@gdpr-test.com'
            }
        )
        
        # Wait for active
        wait_for_tenant_active(tenant_id)
        
        # Add some data
        add_test_data(tenant_id)
        
        # Delete tenant with hard delete
        requests.delete(
            f'{API_URL}/tenants/{tenant_id}?confirm=true&preserve_data=false',
            headers={'x-api-key': API_KEY}
        )
        
        # Wait for deprovisioning
        wait_for_tenant_deleted(tenant_id)
        
        # Verify all data is deleted
        dynamodb = boto3.resource('dynamodb')
        
        # Check tenant registry
        table = dynamodb.Table('dev-msp-triage-tenant-registry')
        response = table.get_item(Key={'tenant_id': tenant_id})
        assert 'Item' not in response or response['Item']['status'] == 'deleted'
        
        # Check audit logs
        table = dynamodb.Table('dev-msp-triage-agent-audit-log')
        response = table.scan(
            FilterExpression='tenant_id = :tid',
            ExpressionAttributeValues={':tid': tenant_id}
        )
        assert len(response.get('Items', [])) == 0
        
        # Check S3
        s3_client = boto3.client('s3')
        response = s3_client.list_objects_v2(
            Bucket='dev-msp-triage-agent-schemas',
            Prefix=f'tenants/{tenant_id}/'
        )
        assert response['KeyCount'] == 0
    
    def test_data_portability(self):
        """Test data portability (GDPR Article 20)."""
        # Export tenant data
        tenant_id = 'portability-test-tenant'
        
        export = export_tenant_data(tenant_id)
        
        # Verify export format
        assert 'tenant_metadata' in export
        assert 'audit_logs' in export
        assert 'feedback_records' in export
        
        # Verify export is in machine-readable format
        assert isinstance(export, dict)
        
        # Verify export can be imported
        # (Implementation depends on import functionality)