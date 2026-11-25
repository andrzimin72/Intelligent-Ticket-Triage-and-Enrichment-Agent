"""API tests: Comprehensive API testing."""
import pytest
import requests


class TestOnboardingAPI:
    """Test tenant onboarding API."""
    
    def test_create_tenant_success(self):
        """Test successful tenant creation."""
        response = requests.post(
            f'{API_URL}/tenants',
            headers={'x-api-key': API_KEY, 'Content-Type': 'application/json'},
            json={
                'tenant_id': 'api-test-tenant',
                'display_name': 'API Test Tenant',
                'entra_tenant_id': '66666666-6666-6666-6666-666666666666',
                'admin_group_id': 'ffffffff-ffff-ffff-ffff-ffffffffffff',
                'contact_email': 'admin@api-test.com'
            }
        )
        
        assert response.status_code == 202
        data = response.json()
        assert data['tenant_id'] == 'api-test-tenant'
        assert data['status'] == 'provisioning'
    
    def test_create_tenant_missing_fields(self):
        """Test tenant creation with missing required fields."""
        response = requests.post(
            f'{API_URL}/tenants',
            headers={'x-api-key': API_KEY, 'Content-Type': 'application/json'},
            json={
                'tenant_id': 'api-test-tenant'
                # Missing other required fields
            }
        )
        
        assert response.status_code == 400
        assert 'Missing required fields' in response.json()['error']
    
    def test_create_tenant_duplicate(self):
        """Test creating duplicate tenant."""
        # Create tenant
        requests.post(
            f'{API_URL}/tenants',
            headers={'x-api-key': API_KEY, 'Content-Type': 'application/json'},
            json={
                'tenant_id': 'duplicate-test',
                'display_name': 'Duplicate Test',
                'entra_tenant_id': '77777777-7777-7777-7777-777777777777',
                'admin_group_id': '11111111-1111-1111-1111-111111111111',
                'contact_email': 'admin@duplicate.com'
            }
        )
        
        # Attempt to create duplicate
        response = requests.post(
            f'{API_URL}/tenants',
            headers={'x-api-key': API_KEY, 'Content-Type': 'application/json'},
            json={
                'tenant_id': 'duplicate-test',
                'display_name': 'Duplicate Test',
                'entra_tenant_id': '77777777-7777-7777-7777-777777777777',
                'admin_group_id': '11111111-1111-1111-1111-111111111111',
                'contact_email': 'admin@duplicate.com'
            }
        )
        
        assert response.status_code == 409
    
    def test_get_tenant_status(self):
        """Test getting tenant status."""
        response = requests.get(
            f'{API_URL}/tenants/api-test-tenant',
            headers={'x-api-key': API_KEY}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data['tenant_id'] == 'api-test-tenant'
    
    def test_list_tenants(self):
        """Test listing all tenants."""
        response = requests.get(
            f'{API_URL}/tenants',
            headers={'x-api-key': API_KEY}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert 'tenants' in data
        assert 'count' in data


class TestStatusAPI:
    """Test status API."""
    
    def test_get_system_status(self):
        """Test getting system-wide status."""
        response = requests.get(
            f'{API_URL}/status',
            headers={'x-api-key': API_KEY}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert 'system_health' in data
        assert 'tenants' in data
    
    def test_get_tenant_health(self):
        """Test getting tenant health."""
        response = requests.get(
            f'{API_URL}/status/tenants/api-test-tenant/health',
            headers={'x-api-key': API_KEY}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert 'health_score' in data
        assert 'overall_health' in data
    
    def test_get_aggregated_metrics(self):
        """Test getting aggregated metrics."""
        response = requests.get(
            f'{API_URL}/status/metrics',
            headers={'x-api-key': API_KEY}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert 'totals' in data


class TestAnalyticsAPI:
    """Test analytics API."""
    
    def test_get_health_trends(self):
        """Test getting health trends."""
        response = requests.get(
            f'{API_URL}/analytics/health-trends?days=30',
            headers={'x-api-key': API_KEY}
        )
        
        # May return 404 if no data yet
        assert response.status_code in [200, 404]
    
    def test_get_executive_summary(self):
        """Test getting executive summary."""
        response = requests.get(
            f'{API_URL}/analytics/executive-summary',
            headers={'x-api-key': API_KEY}
        )
        
        assert response.status_code in [200, 404]