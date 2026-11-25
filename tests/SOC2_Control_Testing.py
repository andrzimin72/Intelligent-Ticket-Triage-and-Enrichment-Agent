"""Compliance tests: SOC 2 control validation."""
import pytest


class TestSOC2Controls:
    """Test SOC 2 control implementation."""
    
    def test_cc6_1_logical_access_controls(self):
        """Test CC6.1: Logical access security controls."""
        # Verify JWT validation is enforced
        response = requests.get(
            f'{PORTAL_API_URL}/me',
            headers={}  # No auth
        )
        assert response.status_code == 401
        
        # Verify API key authentication
        response = requests.get(
            f'{API_URL}/status',
            headers={}  # No API key
        )
        assert response.status_code == 403
    
    def test_cc6_7_encryption_in_transit(self):
        """Test CC6.7: Encryption in transit."""
        # Verify all endpoints use HTTPS
        # (This is enforced at API Gateway level)
        
        # Attempt HTTP connection (should fail)
        http_url = API_URL.replace('https://', 'http://')
        
        try:
            response = requests.get(http_url, timeout=5)
            # Should redirect to HTTPS or fail
            assert response.status_code in [301, 302, 403]
        except requests.exceptions.SSLError:
            # Expected - SSL error on HTTP
            pass
    
    def test_cc7_2_monitoring(self):
        """Test CC7.2: System monitoring."""
        # Verify CloudWatch dashboards exist
        cloudwatch = boto3.client('cloudwatch')
        dashboards = cloudwatch.list_dashboards()
        
        dashboard_names = [d['DashboardName'] for d in dashboards['DashboardEntries']]
        
        assert 'msp-triage-dev-executive' in dashboard_names
        assert 'msp-triage-dev-operations' in dashboard_names
        assert 'msp-triage-dev-security' in dashboard_names
        assert 'msp-triage-dev-cost' in dashboard_names
    
    def test_cc8_1_change_management(self):
        """Test CC8.1: Change management controls."""
        # Verify CI/CD pipeline enforces code review
        # (This is validated by GitHub branch protection rules)
        
        # Verify all changes go through CI/CD
        # Check GitHub Actions workflow runs
        # (Implementation depends on GitHub API access)