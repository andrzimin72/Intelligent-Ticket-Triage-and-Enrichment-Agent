"""
Test package initialization for MSP Triage Infrastructure.

This package contains all test modules for the platform.
Tests are organized by component/service.

Test Structure:
    tests/
    ├── conftest.py              # Shared pytest fixtures
    ├── test_tenant_resolver.py  # Tenant resolution tests
    ├── test_agent_security.py   # Security primitives tests
    ├── test_tenant_onboarding.py # Onboarding API tests
    └── ...

Usage:
    # Run all tests
    pytest tests/
    
    # Run with coverage
    pytest tests/ --cov=src_* --cov-report=html
    
    # Run specific test file
    pytest tests/test_tenant_resolver.py -v
"""

# Test configuration constants
TEST_ENVIRONMENT = "test"
TEST_AWS_REGION = "us-east-1"
TEST_DEFAULT_TENANT_ID = "test-tenant"

# Common test data
MOCK_ENTRA_TENANT_ID = "12345678-1234-1234-1234-123456789012"
MOCK_ADMIN_GROUP_ID = "87654321-4321-4321-4321-210987654321"
MOCK_USER_AAD_ID = "user-aad-12345"

# AWS service mocks configuration
MOCK_DYNAMODB_TABLES = [
    "test-tenant-registry",
    "test-agent-feedback",
    "test-status-cache",
]

__all__ = [
    "TEST_ENVIRONMENT",
    "TEST_AWS_REGION",
    "TEST_DEFAULT_TENANT_ID",
    "MOCK_ENTRA_TENANT_ID",
    "MOCK_ADMIN_GROUP_ID",
    "MOCK_USER_AAD_ID",
    "MOCK_DYNAMODB_TABLES",
]