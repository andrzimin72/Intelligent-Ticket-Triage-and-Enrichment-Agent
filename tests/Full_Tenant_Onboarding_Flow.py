"""Integration test: Full tenant onboarding flow."""
import pytest
import boto3
import time
import json
import requests


@pytest.fixture(scope='module')
def api_client():
    """Set up API client for integration tests."""
    api_url = os.environ.get('API_URL', 'http://localhost:4566/restapis/dev/_user_request_')
    api_key = os.environ.get('API_KEY', 'test-api-key')
    return {
        'url': api_url,
        'headers': {
            'x-api-key': api_key,
            'Content-Type': 'application/json'
        }
    }


def test_tenant_onboarding_full_flow(api_client):
    """Test complete tenant onboarding from creation to active status."""
    tenant_data = {
        'tenant_id': 'integration-test-tenant',
        'display_name': 'Integration Test Corp',
        'entra_tenant_id': '33333333-3333-3333-3333-333333333333',
        'admin_group_id': 'cccccccc-cccc-cccc-cccc-cccccccccccc',
        'contact_email': 'admin@integration-test.com',
        'branding': {'company_name': 'Integration Test Corp'},
        'timezone': 'America/New_York'
    }
    
    # Step 1: Create tenant
    response = requests.post(
        f"{api_client['url']}/tenants",
        headers=api_client['headers'],
        json=tenant_data
    )
    
    assert response.status_code == 202
    data = response.json()
    assert data['tenant_id'] == 'integration-test-tenant'
    assert data['status'] == 'provisioning'
    assert data['management_mode'] == 'api'
    
    # Step 2: Verify tenant record created in DynamoDB
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('dev-msp-triage-tenant-registry')
    item = table.get_item(Key={'tenant_id': 'integration-test-tenant'})
    assert 'Item' in item
    assert item['Item']['status'] == 'provisioning'
    
    # Step 3: Verify secrets created
    secrets_client = boto3.client('secretsmanager')
    for secret_type in ['psa', 'rmm', 'graph']:
        secret_name = f"dev/tenants/integration-test-tenant/{secret_type}"
        response = secrets_client.describe_secret(SecretId=secret_name)
        assert response['Name'] == secret_name
    
    # Step 4: Verify S3 folders created
    s3_client = boto3.client('s3')
    
    # Check agent schemas
    response = s3_client.list_objects_v2(
        Bucket='dev-msp-triage-agent-schemas',
        Prefix='tenants/integration-test-tenant/'
    )
    assert response['KeyCount'] >= 1
    
    # Step 5: Verify SQS message queued
    sqs_client = boto3.client('sqs')
    queue_url = sqs_client.get_queue_url(
        QueueName='dev-msp-triage-tenant-provisioning'
    )['QueueUrl']
    
    response = sqs_client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=5
    )
    
    assert 'Messages' in response
    message = json.loads(response['Messages'][0]['Body'])
    assert message['tenant_id'] == 'integration-test-tenant'
    assert message['action'] == 'provision'
    
    # Step 6: Poll until tenant becomes active (timeout after 20 minutes)
    max_wait = 1200  # 20 minutes
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        response = requests.get(
            f"{api_client['url']}/tenants/integration-test-tenant",
            headers=api_client['headers']
        )
        data = response.json()
        
        if data.get('status') == 'active':
            break
        
        time.sleep(30)
    
    assert data['status'] == 'active'
    assert 'agent_id' in data
    assert 'agent_alias_id' in data
    
    # Step 7: Cleanup
    response = requests.delete(
        f"{api_client['url']}/tenants/integration-test-tenant?confirm=true&preserve_data=false",
        headers=api_client['headers']
    )
    assert response.status_code == 202