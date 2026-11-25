"""API contract tests: Verify API contracts."""
import pytest
import jsonschema


# Define API response schemas
TENANT_SCHEMA = {
    'type': 'object',
    'required': ['tenant_id', 'status'],
    'properties': {
        'tenant_id': {'type': 'string'},
        'status': {'type': 'string', 'enum': ['provisioning', 'active', 'deprovisioning', 'deleted']},
        'display_name': {'type': 'string'},
        'management_mode': {'type': 'string'},
    }
}

STATUS_SCHEMA = {
    'type': 'object',
    'required': ['system_health', 'tenants'],
    'properties': {
        'system_health': {'type': 'string'},
        'tenants': {
            'type': 'object',
            'required': ['total', 'by_status'],
        }
    }
}


class TestAPIContracts:
    """Test API response contracts."""
    
    def test_tenant_response_contract(self):
        """Test tenant API response matches contract."""
        response = requests.get(
            f'{API_URL}/tenants/api-test-tenant',
            headers={'x-api-key': API_KEY}
        )
        
        assert response.status_code == 200
        
        # Validate against schema
        jsonschema.validate(instance=response.json(), schema=TENANT_SCHEMA)
    
    def test_status_response_contract(self):
        """Test status API response matches contract."""
        response = requests.get(
            f'{API_URL}/status',
            headers={'x-api-key': API_KEY}
        )
        
        assert response.status_code == 200
        jsonschema.validate(instance=response.json(), schema=STATUS_SCHEMA)