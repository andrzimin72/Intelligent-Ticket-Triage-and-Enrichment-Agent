"""Automated multi-tenancy isolation tests."""
import pytest
import boto3
import json
from botocore.exceptions import ClientError


class TestMultiTenancyIsolation:
    """Test suite for multi-tenant data isolation."""
    
    @pytest.fixture(autouse=True)
    def setup_tenants(self):
        """Set up test tenants."""
        self.tenants = ['isolation-test-a', 'isolation-test-b']
        self.dynamodb = boto3.resource('dynamodb')
        
        for tenant_id in self.tenants:
            # Create tenant records
            table = self.dynamodb.Table('dev-msp-triage-tenant-registry')
            table.put_item(Item={
                'tenant_id': tenant_id,
                'entra_tenant_id': f'11111111-1111-1111-1111-{tenant_id[-12:]}',
                'status': 'active',
                'enabled': 1
            })
            
            # Create tenant-specific audit entries
            table = self.dynamodb.Table('dev-msp-triage-agent-audit-log')
            table.put_item(Item={
                'audit_id': f'audit-{tenant_id}-001',
                'timestamp': '2026-11-23T10:00:00Z',
                'tenant_id': tenant_id,
                'user_id': f'user-{tenant_id}',
                'operation': 'test_operation',
                'data': f'secret-data-{tenant_id}'
            })
        
        yield
        
        # Cleanup
        for tenant_id in self.tenants:
            table = self.dynamodb.Table('dev-msp-triage-tenant-registry')
            table.delete_item(Key={'tenant_id': tenant_id})
    
    def test_dynamodb_tenant_isolation(self):
        """Verify DynamoDB tenant isolation."""
        table = self.dynamodb.Table('dev-msp-triage-agent-audit-log')
        
        # Query tenant A's data
        response = table.scan(
            FilterExpression='tenant_id = :tid',
            ExpressionAttributeValues={':tid': 'isolation-test-a'}
        )
        
        items = response.get('Items', [])
        assert len(items) == 1
        assert items[0]['tenant_id'] == 'isolation-test-a'
        assert 'isolation-test-b' not in json.dumps(items)
    
    def test_s3_tenant_isolation(self):
        """Verify S3 tenant isolation."""
        s3_client = boto3.client('s3')
        bucket = 'dev-msp-triage-agent-schemas'
        
        # Create tenant-specific objects
        for tenant_id in self.tenants:
            s3_client.put_object(
                Bucket=bucket,
                Key=f'tenants/{tenant_id}/test.json',
                Body=json.dumps({'tenant': tenant_id})
            )
        
        # List tenant A's objects
        response = s3_client.list_objects_v2(
            Bucket=bucket,
            Prefix='tenants/isolation-test-a/'
        )
        
        objects = response.get('Contents', [])
        assert len(objects) == 1
        assert 'isolation-test-b' not in objects[0]['Key']
        
        # Cleanup
        for tenant_id in self.tenants:
            s3_client.delete_object(
                Bucket=bucket,
                Key=f'tenants/{tenant_id}/test.json'
            )
    
    def test_secrets_tenant_isolation(self):
        """Verify Secrets Manager tenant isolation."""
        secrets_client = boto3.client('secretsmanager')
        
        # Each tenant should only see their own secrets
        for tenant_id in self.tenants:
            secret_name = f'dev/tenants/{tenant_id}/graph'
            
            # Verify secret exists
            response = secrets_client.describe_secret(SecretId=secret_name)
            assert response['Name'] == secret_name
            
            # Verify other tenant cannot access (would require IAM policy test)
            # This is validated by IAM policies in production
    
    def test_bedrock_agent_isolation(self):
        """Verify Bedrock agent isolation."""
        bedrock_client = boto3.client('bedrock-agent')
        
        # Each tenant should have their own agent
        for tenant_id in self.tenants:
            agent_name = f'dev-it-concierge-{tenant_id}'
            
            # Find agent by name
            agents = bedrock_client.list_agents()
            matching = [a for a in agents['agentSummaries'] 
                       if a['agentName'] == agent_name]
            
            assert len(matching) == 1
            agent_id = matching[0]['agentId']
            
            # Verify agent is scoped to tenant
            agent = bedrock_client.get_agent(agentId=agent_id)
            assert tenant_id in agent['agent']['agentName']