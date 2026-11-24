"""
Tenant Resolver Module

Resolves the current tenant from trusted context (Teams activity / Entra tenant ID).
Provides tenant-scoped secret names and configuration.

Security properties:
- Tenant ID comes ONLY from trusted sources (Teams activity, session attributes)
- Never from model parameters or user input
- Fails closed if tenant cannot be resolved
- Caches tenant records briefly to reduce DynamoDB reads
- Cache keys include tenant_id to prevent cross-tenant leakage
"""

import json
import os
import logging
import time
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

TENANT_REGISTRY_TABLE = os.environ.get('TENANT_REGISTRY_TABLE')
DEFAULT_TENANT_ID = os.environ.get('DEFAULT_TENANT_ID', 'default')
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)

# Cache tenant records for 5 minutes to reduce DynamoDB reads
_tenant_cache: Dict[str, Dict[str, Any]] = {}
_tenant_cache_time: Dict[str, float] = {}
CACHE_TTL_SECONDS = 300


class TenantResolutionError(Exception):
    """Raised when tenant cannot be resolved from trusted context."""


# =============================================================================
# TENANT RESOLUTION FROM TEAMS ACTIVITY
# =============================================================================

def resolve_tenant_from_teams_activity(activity: Dict[str, Any]) -> Optional[str]:
    """
    Extracts the Entra tenant ID from a Teams activity.
    
    Returns the Entra tenant ID string, or None if not present.
    This is the TRUSTED source — Microsoft cryptographically signs the activity.
    """
    channel_data = activity.get('channelData') or {}
    tenant = channel_data.get('tenant') or {}
    entra_tenant_id = tenant.get('id')
    
    if entra_tenant_id:
        logger.info(f"Resolved Entra tenant ID from Teams activity: {entra_tenant_id}")
        return entra_tenant_id
    
    logger.warning("No tenant ID found in Teams activity")
    return None


# =============================================================================
# TENANT LOOKUP
# =============================================================================

def lookup_tenant_by_entra_id(entra_tenant_id: str) -> Optional[Dict[str, Any]]:
    """
    Looks up the internal tenant record by Entra tenant ID.
    
    Returns the tenant record dict, or None if not found.
    Uses a short-lived cache to reduce DynamoDB reads.
    """
    cache_key = f"entra:{entra_tenant_id}"
    current_time = time.time()
    
    if cache_key in _tenant_cache:
        if current_time - _tenant_cache_time[cache_key] < CACHE_TTL_SECONDS:
            return _tenant_cache[cache_key]
    
    if not TENANT_REGISTRY_TABLE:
        logger.warning("TENANT_REGISTRY_TABLE not configured")
        return None
    
    try:
        table = dynamodb.Table(TENANT_REGISTRY_TABLE)
        response = table.query(
            IndexName='entra-tenant-index',
            KeyConditionExpression='entra_tenant_id = :etid',
            ExpressionAttributeValues={':etid': entra_tenant_id}
        )
        
        items = response.get('Items', [])
        if not items:
            logger.warning(f"No tenant found for Entra tenant ID: {entra_tenant_id}")
            return None
        
        tenant = items[0]
        
        if tenant.get('enabled', 0) != 1:
            logger.warning(f"Tenant {tenant.get('tenant_id')} is disabled")
            return None
        
        _tenant_cache[cache_key] = tenant
        _tenant_cache_time[cache_key] = current_time
        
        return tenant
    
    except ClientError as e:
        logger.error(f"Failed to lookup tenant by Entra ID: {e}")
        return None


def lookup_tenant_by_id(tenant_id: str) -> Optional[Dict[str, Any]]:
    """
    Looks up the internal tenant record by tenant_id directly.
    
    Use this when tenant_id is already known (e.g., from session attributes).
    """
    cache_key = f"id:{tenant_id}"
    current_time = time.time()
    
    if cache_key in _tenant_cache:
        if current_time - _tenant_cache_time[cache_key] < CACHE_TTL_SECONDS:
            return _tenant_cache[cache_key]
    
    if not TENANT_REGISTRY_TABLE:
        return None
    
    try:
        table = dynamodb.Table(TENANT_REGISTRY_TABLE)
        response = table.get_item(Key={'tenant_id': tenant_id})
        tenant = response.get('Item')
        
        if not tenant:
            return None
        
        if tenant.get('enabled', 0) != 1:
            return None
        
        _tenant_cache[cache_key] = tenant
        _tenant_cache_time[cache_key] = current_time
        
        return tenant
    
    except ClientError as e:
        logger.error(f"Failed to lookup tenant by ID: {e}")
        return None


# =============================================================================
# TENANT-SCOPED NAMES
# =============================================================================

def get_tenant_secret_name(tenant_id: str, secret_type: str) -> str:
    """
    Constructs a tenant-scoped secret name.
    
    Examples:
    - get_tenant_secret_name("default", "psa") → "dev/msp/psa/api_keys" (legacy)
    - get_tenant_secret_name("msp-acme", "psa") → "dev/tenants/msp-acme/psa"
    
    The default tenant uses legacy secret paths for backward compatibility.
    """
    environment = os.environ.get('ENVIRONMENT', 'dev')
    
    if tenant_id == DEFAULT_TENANT_ID:
        legacy_names = {
            'psa': f"{environment}/msp/psa/api_keys",
            'rmm': f"{environment}/msp/rmm/api_keys",
            'graph': f"{environment}/msp/entra/graph_credentials",
            'webhook': f"{environment}/msp/webhook/token",
            'unsubscribe': f"{environment}/msp/unsubscribe/signing_key",
            'teams_bot': f"{environment}/msp/teams/bot_secret",
            'confirmation': f"{environment}/msp/agent/confirmation_signing_key",
        }
        return legacy_names.get(secret_type, f"{environment}/tenants/{tenant_id}/{secret_type}")
    
    return f"{environment}/tenants/{tenant_id}/{secret_type}"


def get_tenant_s3_prefix(tenant_id: str) -> str:
    """Returns the S3 key prefix for tenant-scoped objects."""
    return f"tenants/{tenant_id}/"


# =============================================================================
# TRUSTED TENANT EXTRACTION
# =============================================================================

def extract_trusted_tenant_id(event: Dict[str, Any]) -> str:
    """
    Extracts the tenant_id from trusted session attributes.
    
    This MUST be set by the Teams bot from the Teams activity — never from
    model parameters or user input.
    
    Raises TenantResolutionError if tenant_id is missing.
    """
    attrs = event.get('sessionAttributes') or {}
    tenant_id = attrs.get('tenant_id')
    
    if not tenant_id:
        raise TenantResolutionError(
            "Tenant context missing. This operation requires a verified tenant identity."
        )
    
    return tenant_id


def clear_tenant_cache():
    """Clears the tenant cache. Useful for testing or after tenant updates."""
    global _tenant_cache, _tenant_cache_time
    _tenant_cache = {}
    _tenant_cache_time = {}
    logger.info("Tenant cache cleared")