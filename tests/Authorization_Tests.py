"""Security tests: Authorization."""
import pytest
import requests


class TestAuthorization:
    """Test authorization mechanisms."""
    
    def test_tenant_scoped_access(self):
        """Test tenant-scoped data access."""
        # Tenant A's JWT
        tenant_a_token = generate_tenant_jwt('tenant-a')
        
        # Tenant A can access their own data
        response = requests.get(
            f'{PORTAL_API_URL}/me',
            headers={'Authorization': f'Bearer {tenant_a_token}'}
        )
        assert response.status_code == 200
        assert response.json()['tenant_id'] == 'tenant-a'
        
        # Tenant A cannot access Tenant B's data
        response = requests.get(
            f'{PORTAL_API_URL}/tenants/tenant-b/status',
            headers={'Authorization': f'Bearer {tenant_a_token}'}
        )
        assert response.status_code == 403
    
    def test_admin_only_endpoints(self):
        """Test admin-only endpoint access."""
        # Regular user JWT
        user_token = generate_user_jwt('regular-user', is_admin=False)
        
        response = requests.post(
            f'{API_URL}/tenants',
            headers={'Authorization': f'Bearer {user_token}'},
            json={'tenant_id': 'new-tenant'}
        )
        assert response.status_code == 403
        
        # Admin user JWT
        admin_token = generate_user_jwt('admin-user', is_admin=True)
        
        response = requests.post(
            f'{API_URL}/tenants',
            headers={'Authorization': f'Bearer {admin_token}'},
            json={'tenant_id': 'new-tenant'}
        )
        assert response.status_code == 202