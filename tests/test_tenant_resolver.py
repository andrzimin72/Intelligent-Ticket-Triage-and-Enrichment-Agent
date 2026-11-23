"""
Tests for tenant resolution and isolation.
"""

import pytest
import sys
import os
from unittest.mock import patch, MagicMock
from moto import mock_aws
import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src_shared'))


@pytest.fixture
def aws_env():
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["TENANT_REGISTRY_TABLE"] = "test-tenant-registry"
    os.environ["DEFAULT_TENANT_ID"] = "default"
    os.environ["ENVIRONMENT"] = "dev"


@pytest.fixture
def aws_resources(aws_env):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName="test-tenant-registry",
            KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "tenant_id", "AttributeType": "S"},
                {"AttributeName": "entra_tenant_id", "AttributeType": "S"},
                {"AttributeName": "enabled", "AttributeType": "N"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "entra-tenant-index",
                    "KeySchema": [{"AttributeName": "entra_tenant_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "enabled-index",
                    "KeySchema": [{"AttributeName": "enabled", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield {"dynamodb": dynamodb}


def test_resolve_tenant_from_teams_activity():
    """Tenant ID should come from Teams channelData."""
    import tenant_resolver
    
    activity = {
        "channelData": {
            "tenant": {"id": "entra-tenant-abc"}
        }
    }
    
    result = tenant_resolver.resolve_tenant_from_teams_activity(activity)
    assert result == "entra-tenant-abc"


def test_resolve_tenant_missing_channel_data():
    """Should return None if no tenant info in activity."""
    import tenant_resolver
    
    activity = {"type": "message", "text": "hello"}
    result = tenant_resolver.resolve_tenant_from_teams_activity(activity)
    assert result is None


def test_lookup_tenant_by_entra_id(aws_resources):
    """Should find tenant by Entra tenant ID."""
    import tenant_resolver
    
    table = aws_resources["dynamodb"].Table("test-tenant-registry")
    table.put_item(Item={
        "tenant_id": "msp-acme",
        "entra_tenant_id": "entra-tenant-abc",
        "enabled": 1,
        "display_name": "Acme MSP",
    })
    
    tenant = tenant_resolver.lookup_tenant_by_entra_id("entra-tenant-abc")
    assert tenant is not None
    assert tenant["tenant_id"] == "msp-acme"


def test_lookup_disabled_tenant_returns_none(aws_resources):
    """Disabled tenants should not be resolved."""
    import tenant_resolver
    
    table = aws_resources["dynamodb"].Table("test-tenant-registry")
    table.put_item(Item={
        "tenant_id": "msp-disabled",
        "entra_tenant_id": "entra-disabled",
        "enabled": 0,
    })
    
    tenant = tenant_resolver.lookup_tenant_by_entra_id("entra-disabled")
    assert tenant is None


def test_get_tenant_secret_name_default_tenant():
    """Default tenant should use legacy secret paths for backward compatibility."""
    import tenant_resolver
    
    os.environ["ENVIRONMENT"] = "dev"
    name = tenant_resolver.get_tenant_secret_name("default", "psa")
    assert name == "dev/msp/psa/api_keys"


def test_get_tenant_secret_name_custom_tenant():
    """Custom tenants should use tenant-scoped paths."""
    import tenant_resolver
    
    os.environ["ENVIRONMENT"] = "dev"
    name = tenant_resolver.get_tenant_secret_name("msp-acme", "psa")
    assert name == "dev/tenants/msp-acme/psa"


def test_get_tenant_s3_prefix():
    """S3 prefix should be tenant-scoped."""
    import tenant_resolver
    
    prefix = tenant_resolver.get_tenant_s3_prefix("msp-acme")
    assert prefix == "tenants/msp-acme/"


def test_extract_trusted_tenant_id_missing():
    """Should raise if tenant_id missing from session attributes."""
    import tenant_resolver
    
    event = {"sessionAttributes": {"user_aad_id": "user-123"}}
    
    with pytest.raises(tenant_resolver.TenantResolutionError):
        tenant_resolver.extract_trusted_tenant_id(event)


def test_extract_trusted_tenant_id_present():
    """Should return tenant_id from session attributes."""
    import tenant_resolver
    
    event = {
        "sessionAttributes": {
            "tenant_id": "msp-acme",
            "user_aad_id": "user-123",
        }
    }
    
    result = tenant_resolver.extract_trusted_tenant_id(event)
    assert result == "msp-acme"


def test_tenant_cache_isolation(aws_resources):
    """Cache keys should include tenant_id to prevent cross-tenant leakage."""
    import tenant_resolver
    
    table = aws_resources["dynamodb"].Table("test-tenant-registry")
    table.put_item(Item={
        "tenant_id": "msp-acme",
        "entra_tenant_id": "entra-acme",
        "enabled": 1,
        "display_name": "Acme",
    })
    table.put_item(Item={
        "tenant_id": "msp-beta",
        "entra_tenant_id": "entra-beta",
        "enabled": 1,
        "display_name": "Beta",
    })
    
    tenant_resolver.clear_tenant_cache()
    
    acme = tenant_resolver.lookup_tenant_by_entra_id("entra-acme")
    beta = tenant_resolver.lookup_tenant_by_entra_id("entra-beta")
    
    assert acme["tenant_id"] == "msp-acme"
    assert beta["tenant_id"] == "msp-beta"
    assert acme != beta


def test_cross_tenant_secret_isolation():
    """Secret names for different tenants must be different."""
    import tenant_resolver
    
    os.environ["ENVIRONMENT"] = "dev"
    
    acme_secret = tenant_resolver.get_tenant_secret_name("msp-acme", "psa")
    beta_secret = tenant_resolver.get_tenant_secret_name("msp-beta", "psa")
    
    assert acme_secret != beta_secret
    assert "msp-acme" in acme_secret
    assert "msp-beta" in beta_secret