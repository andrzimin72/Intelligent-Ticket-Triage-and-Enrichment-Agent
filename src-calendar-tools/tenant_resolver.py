"""
Tenant Resolver - Multi-Tenant Resolution and Isolation Module

This module provides the core tenant resolution logic for the MSP AI Platform.
It is shared across all Lambda functions and copied into each function's
deployment package at build time.

PRIMARY RESPONSIBILITIES:
    1. Resolve tenant context from various sources:
       - Microsoft Teams activity (Entra tenant ID from channelData)
       - API Gateway requests (JWT claims, headers)
       - Direct tenant_id lookup
    
    2. Verify tenant state:
       - Tenant exists in registry
       - Tenant is enabled
       - Tenant is in active state
       - Agent is healthy (optional)
    
    3. Provide tenant-scoped resource names:
       - Secret names (PSA, RMM, Graph)
       - S3 paths (examples, KB docs, branding)
       - DynamoDB keys
    
    4. Cache tenant lookups for performance:
       - In-memory cache with TTL
       - Thread-safe for Lambda container reuse
       - Graceful degradation on cache failures

SECURITY MODEL:
    - Tenant context MUST come from trusted sources (Teams activity, JWT)
    - Tenant context MUST NEVER come from LLM parameters or user input
    - All tenant-scoped operations must verify tenant state first
    - Failed lookups must not leak information about tenant existence

USAGE:
    import tenant_resolver
    
    # From Teams activity
    tenant_id = tenant_resolver.resolve_tenant_from_teams_activity(activity)
    tenant = tenant_resolver.get_tenant(tenant_id)
    
    # From API request (JWT)
    tenant_id = tenant_resolver.resolve_tenant_from_jwt(event)
    tenant = tenant_resolver.get_tenant(tenant_id)
    
    # Get tenant-scoped resources
    secret_name = tenant_resolver.get_secret_name(tenant_id, 'graph')
    s3_path = tenant_resolver.get_s3_path(tenant_id, 'examples')

VERSION: 2.0.0
AUTHOR: Platform Engineering Team
"""

import os
import time
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from aws_xray_sdk.core import xray_recorder

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION (Environment Variables)
# =============================================================================

# Required environment variables
TENANT_REGISTRY_TABLE = os.environ.get('TENANT_REGISTRY_TABLE')
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

# Optional environment variables
ENABLE_KB = os.environ.get('ENABLE_KB', 'false').lower() == 'true'
AGENT_SCHEMAS_BUCKET = os.environ.get('AGENT_SCHEMAS_BUCKET', '')
KB_DOCUMENTS_BUCKET = os.environ.get('KB_DOCUMENTS_BUCKET', '')
CUSTOMER_BRANDING_BUCKET = os.environ.get('CUSTOMER_BRANDING_BUCKET', '')
FEW_SHOT_EXAMPLES_BUCKET = os.environ.get('FEW_SHOT_EXAMPLES_BUCKET', '')

# Cache configuration
CACHE_ENABLED = os.environ.get('TENANT_CACHE_ENABLED', 'true').lower() == 'true'
CACHE_TTL_SECONDS = int(os.environ.get('TENANT_CACHE_TTL_SECONDS', '300'))  # 5 minutes
CACHE_MAX_SIZE = int(os.environ.get('TENANT_CACHE_MAX_SIZE', '1000'))

# =============================================================================
# CONSTANTS
# =============================================================================

# Tenant statuses
class TenantStatus:
    """Enumeration of tenant lifecycle states."""
    PROVISIONING = 'provisioning'
    ACTIVE = 'active'
    DISABLED = 'disabled'
    DEPROVISIONING = 'deprovisioning'
    DELETED = 'deleted'
    DELETE_FAILED = 'delete_failed'
    
    # States where tenant can process requests
    OPERATIONAL_STATES = {ACTIVE}
    
    # States where tenant exists but cannot process requests
    NON_OPERATIONAL_STATES = {
        PROVISIONING, DISABLED, DEPROVISIONING, DELETED, DELETE_FAILED
    }


# Management modes
class ManagementMode:
    """Enumeration of tenant management modes (Phase D)."""
    TERRAFORM = 'terraform'      # Legacy Terraform-managed
    HYBRID = 'hybrid'            # Adopted from Terraform
    API = 'api'                  # Fully API-managed


# Secret types
class SecretType:
    """Enumeration of tenant secret types."""
    PSA = 'psa'
    RMM = 'rmm'
    GRAPH = 'graph'
    
    ALL_TYPES = {PSA, RMM, GRAPH}


# S3 path types
class S3PathType:
    """Enumeration of tenant-scoped S3 path types."""
    AGENT_EXAMPLES = 'agent_examples'
    KB_DOCUMENTS = 'kb_documents'
    CUSTOMER_BRANDING = 'customer_branding'
    FEW_SHOT_EXAMPLES = 'few_shot_examples'


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class TenantResolverError(Exception):
    """Base exception for tenant resolver errors."""
    pass


class TenantNotFoundError(TenantResolverError):
    """Raised when a tenant cannot be found in the registry."""
    pass


class TenantDisabledError(TenantResolverError):
    """Raised when a tenant is disabled."""
    pass


class TenantNotActiveError(TenantResolverError):
    """Raised when a tenant is not in an operational state."""
    def __init__(self, tenant_id: str, status: str, message: Optional[str] = None):
        self.tenant_id = tenant_id
        self.status = status
        super().__init__(
            message or f"Tenant {tenant_id} is not active (status: {status})"
        )


class InvalidTenantContextError(TenantResolverError):
    """Raised when tenant context cannot be resolved from input."""
    pass


class TenantRegistryError(TenantResolverError):
    """Raised when there's an error accessing the tenant registry."""
    pass


# =============================================================================
# TENANT DATA CLASS
# =============================================================================

@dataclass
class Tenant:
    """
    Represents a tenant in the MSP AI Platform.
    
    Attributes:
        tenant_id: Unique tenant identifier (partition key)
        display_name: Human-readable tenant name
        entra_tenant_id: Microsoft Entra ID tenant GUID
        admin_group_id: Entra ID group for admin operations
        contact_email: Primary contact email
        status: Current lifecycle status
        enabled: Whether tenant is enabled (1) or disabled (0)
        management_mode: How tenant is managed (terraform/hybrid/api)
        agent_id: Bedrock agent ID (if provisioned)
        agent_alias_id: Bedrock agent alias ID (if provisioned)
        branding: JSON string of branding configuration
        timezone: Tenant's timezone (e.g., 'America/New_York')
        created_at: ISO timestamp of creation
        updated_at: ISO timestamp of last update
        raw: Original DynamoDB item (for access to additional fields)
    """
    tenant_id: str
    display_name: str = ''
    entra_tenant_id: str = ''
    admin_group_id: str = ''
    contact_email: str = ''
    status: str = TenantStatus.PROVISIONING
    enabled: int = 1
    management_mode: str = ManagementMode.API
    agent_id: Optional[str] = None
    agent_alias_id: Optional[str] = None
    branding: str = '{}'
    timezone: str = 'UTC'
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_dynamodb_item(cls, item: Dict[str, Any]) -> 'Tenant':
        """
        Create a Tenant instance from a DynamoDB item.
        
        Args:
            item: DynamoDB item dictionary
            
        Returns:
            Tenant instance
        """
        return cls(
            tenant_id=item.get('tenant_id', ''),
            display_name=item.get('display_name', ''),
            entra_tenant_id=item.get('entra_tenant_id', ''),
            admin_group_id=item.get('admin_group_id', ''),
            contact_email=item.get('contact_email', ''),
            status=item.get('status', TenantStatus.PROVISIONING),
            enabled=int(item.get('enabled', 1)),
            management_mode=item.get('management_mode', ManagementMode.API),
            agent_id=item.get('agent_id'),
            agent_alias_id=item.get('agent_alias_id'),
            branding=item.get('branding', '{}'),
            timezone=item.get('timezone', 'UTC'),
            created_at=item.get('created_at'),
            updated_at=item.get('updated_at'),
            raw=item,
        )
    
    def is_operational(self) -> bool:
        """Check if tenant is in an operational state."""
        return (
            self.enabled == 1 and
            self.status in TenantStatus.OPERATIONAL_STATES
        )
    
    def is_active(self) -> bool:
        """Check if tenant status is 'active'."""
        return self.status == TenantStatus.ACTIVE
    
    def is_enabled(self) -> bool:
        """Check if tenant is enabled."""
        return self.enabled == 1
    
    def has_agent(self) -> bool:
        """Check if tenant has a provisioned Bedrock agent."""
        return bool(self.agent_id and self.agent_alias_id)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert tenant to dictionary (excluding raw data)."""
        return {
            'tenant_id': self.tenant_id,
            'display_name': self.display_name,
            'entra_tenant_id': self.entra_tenant_id,
            'admin_group_id': self.admin_group_id,
            'contact_email': self.contact_email,
            'status': self.status,
            'enabled': self.enabled,
            'management_mode': self.management_mode,
            'agent_id': self.agent_id,
            'agent_alias_id': self.agent_alias_id,
            'branding': self.branding,
            'timezone': self.timezone,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }


# =============================================================================
# THREAD-SAFE CACHE
# =============================================================================

class TenantCache:
    """
    Thread-safe in-memory cache for tenant lookups.
    
    Designed for Lambda container reuse where the same container
    may handle multiple invocations. Uses a lock to ensure
    thread safety during cache updates.
    """
    
    def __init__(self, ttl_seconds: int = 300, max_size: int = 1000):
        """
        Initialize the cache.
        
        Args:
            ttl_seconds: Time-to-live for cache entries in seconds
            max_size: Maximum number of entries to cache
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[Tenant]:
        """
        Get a tenant from the cache.
        
        Args:
            key: Cache key (tenant_id or entra_tenant_id)
            
        Returns:
            Tenant if found and not expired, None otherwise
        """
        if not CACHE_ENABLED:
            return None
        
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            
            # Check expiration
            if time.time() - entry['timestamp'] > self._ttl_seconds:
                del self._cache[key]
                self._misses += 1
                return None
            
            self._hits += 1
            return entry['tenant']
    
    def set(self, key: str, tenant: Tenant) -> None:
        """
        Set a tenant in the cache.
        
        Args:
            key: Cache key (tenant_id or entra_tenant_id)
            tenant: Tenant instance to cache
        """
        if not CACHE_ENABLED:
            return
        
        with self._lock:
            # Evict oldest entries if cache is full
            if len(self._cache) >= self._max_size:
                self._evict_oldest()
            
            self._cache[key] = {
                'tenant': tenant,
                'timestamp': time.time(),
            }
    
    def invalidate(self, key: str) -> None:
        """
        Remove a specific entry from the cache.
        
        Args:
            key: Cache key to invalidate
        """
        with self._lock:
            self._cache.pop(key, None)
    
    def invalidate_tenant(self, tenant_id: str) -> None:
        """
        Invalidate all cache entries for a specific tenant.
        
        Args:
            tenant_id: Tenant ID to invalidate
        """
        with self._lock:
            keys_to_remove = [
                k for k, v in self._cache.items()
                if v['tenant'].tenant_id == tenant_id
            ]
            for key in keys_to_remove:
                del self._cache[key]
    
    def clear(self) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
    
    def _evict_oldest(self) -> None:
        """Evict the oldest 10% of cache entries (must hold lock)."""
        if not self._cache:
            return
        
        # Sort by timestamp and remove oldest 10%
        sorted_entries = sorted(
            self._cache.items(),
            key=lambda x: x[1]['timestamp']
        )
        num_to_evict = max(1, len(sorted_entries) // 10)
        
        for key, _ in sorted_entries[:num_to_evict]:
            del self._cache[key]
    
    def stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache stats
        """
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0.0
            
            return {
                'size': len(self._cache),
                'max_size': self._max_size,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate_percent': round(hit_rate, 2),
                'ttl_seconds': self._ttl_seconds,
            }


# Global cache instance (shared across Lambda invocations in same container)
_tenant_cache = TenantCache(
    ttl_seconds=CACHE_TTL_SECONDS,
    max_size=CACHE_MAX_SIZE
)


# =============================================================================
# AWS CLIENT INITIALIZATION
# =============================================================================

# Initialize DynamoDB resource (reused across invocations)
_dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)

# Get table reference (lazy initialization)
_tenant_registry_table = None


def _get_tenant_registry_table():
    """Get the tenant registry table reference (lazy initialization)."""
    global _tenant_registry_table
    if _tenant_registry_table is None:
        if not TENANT_REGISTRY_TABLE:
            raise TenantRegistryError(
                "TENANT_REGISTRY_TABLE environment variable not set"
            )
        _tenant_registry_table = _dynamodb.Table(TENANT_REGISTRY_TABLE)
    return _tenant_registry_table


# =============================================================================
# CORE RESOLUTION FUNCTIONS
# =============================================================================

@xray_recorder.capture('resolve_tenant_from_teams_activity')
def resolve_tenant_from_teams_activity(activity: Dict[str, Any]) -> Optional[str]:
    """
    Resolve tenant_id from Microsoft Teams activity.
    
    The Teams activity contains the Entra tenant ID in channelData,
    which is a trusted source (signed by Microsoft). This function
    looks up the tenant in the registry using the Entra tenant ID GSI.
    
    SECURITY NOTE:
        This is the PREFERRED method for tenant resolution in bot contexts.
        The Entra tenant ID comes from Microsoft's signed activity payload,
        NOT from user input or LLM parameters.
    
    Args:
        activity: Microsoft Teams activity payload
        
    Returns:
        tenant_id if found and operational, None otherwise
        
    Raises:
        InvalidTenantContextError: If activity structure is invalid
    """
    if not activity:
        logger.warning("Empty activity provided to resolve_tenant_from_teams_activity")
        return None
    
    # Extract Entra tenant ID from activity
    try:
        channel_data = activity.get('channelData', {}) or {}
        tenant_info = channel_data.get('tenant', {}) or {}
        entra_tenant_id = tenant_info.get('id')
    except (AttributeError, TypeError) as e:
        logger.error(f"Failed to parse Teams activity structure: {e}")
        raise InvalidTenantContextError(f"Invalid activity structure: {e}")
    
    if not entra_tenant_id:
        logger.warning("No Entra tenant ID found in Teams activity")
        return None
    
    # Validate Entra tenant ID format (GUID)
    if not _is_valid_guid(entra_tenant_id):
        logger.warning(f"Invalid Entra tenant ID format: {entra_tenant_id}")
        return None
    
    # Look up tenant by Entra tenant ID
    tenant = lookup_tenant_by_entra_id(entra_tenant_id)
    
    if tenant is None:
        logger.info(f"No tenant found for Entra tenant ID: {entra_tenant_id}")
        return None
    
    # Verify tenant is operational
    if not tenant.is_operational():
        logger.warning(
            f"Tenant {tenant.tenant_id} is not operational "
            f"(status={tenant.status}, enabled={tenant.enabled})"
        )
        return None
    
    logger.debug(f"Resolved tenant {tenant.tenant_id} from Teams activity")
    return tenant.tenant_id


@xray_recorder.capture('resolve_tenant_from_jwt')
def resolve_tenant_from_jwt(event: Dict[str, Any]) -> Optional[str]:
    """
    Resolve tenant_id from API Gateway JWT claims (Cognito).
    
    The tenant_id is stored as a custom attribute in the Cognito user pool,
    which is populated during user provisioning based on Entra ID group
    membership.
    
    SECURITY NOTE:
        JWT claims are trusted because they're signed by Cognito.
        The tenant_id in the claim was set during user provisioning,
        not by the user themselves.
    
    Args:
        event: API Gateway event with authorizer context
        
    Returns:
        tenant_id if found and operational, None otherwise
    """
    if not event:
        logger.warning("Empty event provided to resolve_tenant_from_jwt")
        return None
    
    # Extract JWT claims from authorizer context
    try:
        claims = (
            event.get('requestContext', {})
            .get('authorizer', {})
            .get('jwt', {})
            .get('claims', {})
        )
    except (AttributeError, TypeError) as e:
        logger.error(f"Failed to parse JWT claims: {e}")
        return None
    
    if not claims:
        logger.warning("No JWT claims found in event")
        return None
    
    # Get tenant_id from custom claim
    # Cognito custom attributes are prefixed with "custom:"
    tenant_id = claims.get('custom:tenant_id')
    
    if not tenant_id:
        logger.warning(
            f"No tenant_id in JWT claims for user: {claims.get('email', 'unknown')}"
        )
        return None
    
    # Verify tenant is operational
    tenant = get_tenant(tenant_id)
    if tenant is None or not tenant.is_operational():
        logger.warning(f"Tenant {tenant_id} from JWT is not operational")
        return None
    
    logger.debug(f"Resolved tenant {tenant_id} from JWT")
    return tenant_id


@xray_recorder.capture('resolve_tenant_from_api_key')
def resolve_tenant_from_api_key(event: Dict[str, Any]) -> Optional[str]:
    """
    Resolve tenant_id from API key context (for admin APIs).
    
    API key-authenticated endpoints (like the onboarding API) may include
    a tenant_id in the request path or body. This function extracts it
    and verifies the tenant exists.
    
    SECURITY NOTE:
        This is less secure than JWT-based resolution because the tenant_id
        comes from the request itself. Use only for admin operations where
        the API key provides the trust boundary.
    
    Args:
        event: API Gateway event
        
    Returns:
        tenant_id if found, None otherwise
    """
    if not event:
        return None
    
    # Try to extract from path parameters
    path_params = event.get('pathParameters', {}) or {}
    tenant_id = path_params.get('tenant_id') or path_params.get('id')
    
    # Try to extract from path
    if not tenant_id:
        path = event.get('rawPath', '') or event.get('path', '')
        path_parts = [p for p in path.strip('/').split('/') if p]
        if 'tenants' in path_parts:
            idx = path_parts.index('tenants')
            if idx + 1 < len(path_parts):
                tenant_id = path_parts[idx + 1]
    
    if not tenant_id:
        return None
    
    # Verify tenant exists (don't require operational state for admin APIs)
    tenant = get_tenant(tenant_id)
    if tenant is None:
        logger.warning(f"Tenant {tenant_id} from API key context not found")
        return None
    
    return tenant_id


# =============================================================================
# LOOKUP FUNCTIONS
# =============================================================================

@xray_recorder.capture('lookup_tenant_by_entra_id')
def lookup_tenant_by_entra_id(entra_tenant_id: str) -> Optional[Tenant]:
    """
    Look up a tenant by their Entra tenant ID using the GSI.
    
    Args:
        entra_tenant_id: Microsoft Entra ID tenant GUID
        
    Returns:
        Tenant instance if found, None otherwise
        
    Raises:
        TenantRegistryError: If DynamoDB query fails
    """
    if not entra_tenant_id:
        return None
    
    # Check cache first (keyed by entra_tenant_id)
    cache_key = f"entra:{entra_tenant_id}"
    cached = _tenant_cache.get(cache_key)
    if cached is not None:
        logger.debug(f"Cache hit for entra_tenant_id: {entra_tenant_id}")
        return cached
    
    # Query DynamoDB GSI
    try:
        table = _get_tenant_registry_table()
        response = table.query(
            IndexName='entra-tenant-index',
            KeyConditionExpression='entra_tenant_id = :etid',
            ExpressionAttributeValues={':etid': entra_tenant_id},
            Limit=1
        )
        
        items = response.get('Items', [])
        if not items:
            logger.debug(f"No tenant found for entra_tenant_id: {entra_tenant_id}")
            return None
        
        tenant = Tenant.from_dynamodb_item(items[0])
        
        # Cache the result
        _tenant_cache.set(cache_key, tenant)
        _tenant_cache.set(f"tenant:{tenant.tenant_id}", tenant)
        
        return tenant
    
    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.error(f"DynamoDB query failed for entra_tenant_id lookup: {error_code}")
        raise TenantRegistryError(f"Failed to lookup tenant by Entra ID: {error_code}")
    except Exception as e:
        logger.exception(f"Unexpected error in lookup_tenant_by_entra_id: {e}")
        raise TenantRegistryError(f"Unexpected error: {e}")


@xray_recorder.capture('get_tenant')
def get_tenant(tenant_id: str, force_refresh: bool = False) -> Optional[Tenant]:
    """
    Get a tenant by tenant_id.
    
    Args:
        tenant_id: Unique tenant identifier
        force_refresh: If True, bypass cache and fetch from DynamoDB
        
    Returns:
        Tenant instance if found, None otherwise
        
    Raises:
        TenantRegistryError: If DynamoDB operation fails
    """
    if not tenant_id:
        return None
    
    # Check cache first (unless force_refresh)
    cache_key = f"tenant:{tenant_id}"
    if not force_refresh:
        cached = _tenant_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit for tenant_id: {tenant_id}")
            return cached
    
    # Fetch from DynamoDB
    try:
        table = _get_tenant_registry_table()
        response = table.get_item(Key={'tenant_id': tenant_id})
        
        item = response.get('Item')
        if not item:
            logger.debug(f"Tenant not found: {tenant_id}")
            return None
        
        tenant = Tenant.from_dynamodb_item(item)
        
        # Cache the result
        _tenant_cache.set(cache_key, tenant)
        if tenant.entra_tenant_id:
            _tenant_cache.set(f"entra:{tenant.entra_tenant_id}", tenant)
        
        return tenant
    
    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.error(f"DynamoDB get_item failed for tenant {tenant_id}: {error_code}")
        raise TenantRegistryError(f"Failed to get tenant: {error_code}")
    except Exception as e:
        logger.exception(f"Unexpected error in get_tenant: {e}")
        raise TenantRegistryError(f"Unexpected error: {e}")


@xray_recorder.capture('get_tenant_or_raise')
def get_tenant_or_raise(
    tenant_id: str,
    require_operational: bool = True,
    require_agent: bool = False
) -> Tenant:
    """
    Get a tenant by tenant_id, raising exceptions on failure.
    
    This is the strict version of get_tenant() that raises specific
    exceptions instead of returning None. Use this when you need to
    provide detailed error messages to callers.
    
    Args:
        tenant_id: Unique tenant identifier
        require_operational: If True, raise if tenant is not operational
        require_agent: If True, raise if tenant has no agent
        
    Returns:
        Tenant instance
        
    Raises:
        TenantNotFoundError: If tenant doesn't exist
        TenantDisabledError: If tenant is disabled
        TenantNotActiveError: If tenant is not in operational state
        TenantResolverError: If tenant has no agent but one is required
    """
    tenant = get_tenant(tenant_id)
    
    if tenant is None:
        raise TenantNotFoundError(f"Tenant not found: {tenant_id}")
    
    if not tenant.is_enabled():
        raise TenantDisabledError(f"Tenant is disabled: {tenant_id}")
    
    if require_operational and not tenant.is_operational():
        raise TenantNotActiveError(tenant_id, tenant.status)
    
    if require_agent and not tenant.has_agent():
        raise TenantResolverError(
            f"Tenant {tenant_id} has no provisioned agent"
        )
    
    return tenant


# =============================================================================
# VERIFICATION FUNCTIONS
# =============================================================================

def verify_tenant_operational(tenant_id: str) -> bool:
    """
    Verify that a tenant exists and is operational.
    
    Args:
        tenant_id: Unique tenant identifier
        
    Returns:
        True if tenant is operational, False otherwise
    """
    try:
        tenant = get_tenant(tenant_id)
        return tenant is not None and tenant.is_operational()
    except Exception as e:
        logger.error(f"Error verifying tenant {tenant_id}: {e}")
        return False


def verify_tenant_access(
    requesting_tenant_id: str,
    target_tenant_id: str
) -> bool:
    """
    Verify that a requesting tenant can access a target tenant's resources.
    
    In the current architecture, tenants are fully isolated, so a tenant
    can only access its own resources. This function enforces that.
    
    Args:
        requesting_tenant_id: Tenant making the request
        target_tenant_id: Tenant whose resources are being accessed
        
    Returns:
        True if access is allowed, False otherwise
    """
    if requesting_tenant_id != target_tenant_id:
        logger.warning(
            f"Cross-tenant access attempt: {requesting_tenant_id} -> {target_tenant_id}"
        )
        return False
    
    return verify_tenant_operational(requesting_tenant_id)


def verify_agent_ready(tenant_id: str) -> bool:
    """
    Verify that a tenant has a ready Bedrock agent.
    
    Args:
        tenant_id: Unique tenant identifier
        
    Returns:
        True if tenant has agent_id and agent_alias_id, False otherwise
    """
    try:
        tenant = get_tenant(tenant_id)
        return tenant is not None and tenant.has_agent()
    except Exception as e:
        logger.error(f"Error verifying agent for tenant {tenant_id}: {e}")
        return False


# =============================================================================
# RESOURCE NAME HELPERS
# =============================================================================

def get_secret_name(tenant_id: str, secret_type: str) -> str:
    """
    Get the Secrets Manager secret name for a tenant.
    
    Args:
        tenant_id: Unique tenant identifier
        secret_type: Type of secret ('psa', 'rmm', or 'graph')
        
    Returns:
        Full secret name (e.g., 'dev/tenants/msp-acme/graph')
        
    Raises:
        ValueError: If secret_type is invalid
    """
    if secret_type not in SecretType.ALL_TYPES:
        raise ValueError(
            f"Invalid secret type: {secret_type}. "
            f"Must be one of: {', '.join(SecretType.ALL_TYPES)}"
        )
    
    return f"{ENVIRONMENT}/tenants/{tenant_id}/{secret_type}"


def get_s3_path(
    tenant_id: str,
    path_type: str,
    filename: Optional[str] = None
) -> str:
    """
    Get the S3 path for a tenant-scoped resource.
    
    Args:
        tenant_id: Unique tenant identifier
        path_type: Type of path ('agent_examples', 'kb_documents', etc.)
        filename: Optional filename to append
        
    Returns:
        S3 key path (e.g., 'tenants/msp-acme/agent-examples.json')
        
    Raises:
        ValueError: If path_type is invalid
    """
    if path_type == S3PathType.AGENT_EXAMPLES:
        base_path = f"tenants/{tenant_id}"
        if filename:
            return f"{base_path}/{filename}"
        return f"{base_path}/agent-examples.json"
    
    elif path_type == S3PathType.KB_DOCUMENTS:
        base_path = f"tenants/{tenant_id}"
        if filename:
            return f"{base_path}/{filename}"
        return base_path
    
    elif path_type == S3PathType.CUSTOMER_BRANDING:
        base_path = tenant_id  # Note: no 'tenants/' prefix for branding
        if filename:
            return f"{base_path}/{filename}"
        return base_path
    
    elif path_type == S3PathType.FEW_SHOT_EXAMPLES:
        base_path = f"tenants/{tenant_id}"
        if filename:
            return f"{base_path}/{filename}"
        return f"{base_path}/agent-examples.json"
    
    else:
        raise ValueError(f"Invalid path type: {path_type}")


def get_s3_bucket(path_type: str) -> str:
    """
    Get the S3 bucket name for a tenant-scoped resource type.
    
    Args:
        path_type: Type of path ('agent_examples', 'kb_documents', etc.)
        
    Returns:
        S3 bucket name
        
    Raises:
        ValueError: If path_type is invalid or bucket not configured
    """
    bucket_map = {
        S3PathType.AGENT_EXAMPLES: AGENT_SCHEMAS_BUCKET,
        S3PathType.KB_DOCUMENTS: KB_DOCUMENTS_BUCKET,
        S3PathType.CUSTOMER_BRANDING: CUSTOMER_BRANDING_BUCKET,
        S3PathType.FEW_SHOT_EXAMPLES: FEW_SHOT_EXAMPLES_BUCKET or AGENT_SCHEMAS_BUCKET,
    }
    
    bucket = bucket_map.get(path_type)
    if not bucket:
        raise ValueError(
            f"S3 bucket not configured for path type: {path_type}"
        )
    
    return bucket


# =============================================================================
# BATCH OPERATIONS
# =============================================================================

@xray_recorder.capture('list_all_tenants')
def list_all_tenants(
    status_filter: Optional[str] = None,
    enabled_only: bool = False
) -> List[Tenant]:
    """
    List all tenants from the registry.
    
    WARNING: This performs a full table scan. Use sparingly.
    
    Args:
        status_filter: Optional status to filter by
        enabled_only: If True, only return enabled tenants
        
    Returns:
        List of Tenant instances
    """
    try:
        table = _get_tenant_registry_table()
        
        # Build scan parameters
        scan_params = {}
        
        if status_filter and enabled_only:
            scan_params['FilterExpression'] = (
                '#s = :status AND enabled = :enabled'
            )
            scan_params['ExpressionAttributeNames'] = {'#s': 'status'}
            scan_params['ExpressionAttributeValues'] = {
                ':status': status_filter,
                ':enabled': 1
            }
        elif status_filter:
            scan_params['FilterExpression'] = '#s = :status'
            scan_params['ExpressionAttributeNames'] = {'#s': 'status'}
            scan_params['ExpressionAttributeValues'] = {':status': status_filter}
        elif enabled_only:
            scan_params['FilterExpression'] = 'enabled = :enabled'
            scan_params['ExpressionAttributeValues'] = {':enabled': 1}
        
        # Paginate through results
        tenants = []
        response = table.scan(**scan_params)
        
        while True:
            for item in response.get('Items', []):
                tenants.append(Tenant.from_dynamodb_item(item))
            
            if 'LastEvaluatedKey' not in response:
                break
            
            response = table.scan(
                ExclusiveStartKey=response['LastEvaluatedKey'],
                **scan_params
            )
        
        logger.info(f"Listed {len(tenants)} tenants")
        return tenants
    
    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.error(f"DynamoDB scan failed in list_all_tenants: {error_code}")
        raise TenantRegistryError(f"Failed to list tenants: {error_code}")
    except Exception as e:
        logger.exception(f"Unexpected error in list_all_tenants: {e}")
        raise TenantRegistryError(f"Unexpected error: {e}")


@xray_recorder.capture('count_tenants_by_status')
def count_tenants_by_status() -> Dict[str, int]:
    """
    Count tenants grouped by status.
    
    Returns:
        Dictionary mapping status to count
    """
    tenants = list_all_tenants()
    
    counts = {}
    for tenant in tenants:
        status = tenant.status
        counts[status] = counts.get(status, 0) + 1
    
    return counts


# =============================================================================
# CACHE MANAGEMENT
# =============================================================================

def invalidate_tenant_cache(tenant_id: str) -> None:
    """
    Invalidate all cache entries for a specific tenant.
    
    Call this after updating a tenant's record to ensure subsequent
    reads get fresh data.
    
    Args:
        tenant_id: Tenant ID to invalidate
    """
    _tenant_cache.invalidate_tenant(tenant_id)
    logger.debug(f"Invalidated cache for tenant: {tenant_id}")


def clear_tenant_cache() -> None:
    """Clear the entire tenant cache."""
    _tenant_cache.clear()
    logger.info("Cleared tenant cache")


def get_cache_stats() -> Dict[str, Any]:
    """
    Get cache statistics for monitoring.
    
    Returns:
        Dictionary with cache stats
    """
    return _tenant_cache.stats()


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def _is_valid_guid(value: str) -> bool:
    """
    Validate that a string is a valid GUID format.
    
    Args:
        value: String to validate
        
    Returns:
        True if valid GUID format, False otherwise
    """
    import re
    guid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        re.IGNORECASE
    )
    return bool(guid_pattern.match(value))


def _is_valid_tenant_id(value: str) -> bool:
    """
    Validate that a string is a valid tenant_id format.
    
    Tenant IDs must be:
    - 3-32 characters
    - Lowercase alphanumeric or hyphens
    - Cannot start or end with hyphen
    
    Args:
        value: String to validate
        
    Returns:
        True if valid tenant_id format, False otherwise
    """
    import re
    tenant_id_pattern = re.compile(r'^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$')
    return bool(tenant_id_pattern.match(value))


def normalize_tenant_id(tenant_id: str) -> str:
    """
    Normalize a tenant_id to lowercase and strip whitespace.
    
    Args:
        tenant_id: Tenant ID to normalize
        
    Returns:
        Normalized tenant ID
    """
    return tenant_id.strip().lower()


def get_tenant_context_summary(tenant_id: str) -> Dict[str, Any]:
    """
    Get a summary of tenant context for logging/debugging.
    
    Args:
        tenant_id: Tenant ID
        
    Returns:
        Dictionary with tenant summary (safe to log)
    """
    try:
        tenant = get_tenant(tenant_id)
        if tenant is None:
            return {'tenant_id': tenant_id, 'found': False}
        
        return {
            'tenant_id': tenant.tenant_id,
            'display_name': tenant.display_name,
            'status': tenant.status,
            'enabled': tenant.enabled,
            'management_mode': tenant.management_mode,
            'has_agent': tenant.has_agent(),
            'found': True,
        }
    except Exception as e:
        return {
            'tenant_id': tenant_id,
            'found': False,
            'error': str(e),
        }


# =============================================================================
# MODULE INITIALIZATION
# =============================================================================

def _validate_configuration() -> None:
    """
    Validate module configuration at import time.
    
    Logs warnings for missing optional configuration but doesn't fail.
    """
    if not TENANT_REGISTRY_TABLE:
        logger.warning(
            "TENANT_REGISTRY_TABLE not set. "
            "Tenant resolution will fail until this is configured."
        )
    
    if not ENVIRONMENT:
        logger.warning("ENVIRONMENT not set, defaulting to 'dev'")
    
    if not CACHE_ENABLED:
        logger.info("Tenant cache is disabled")
    else:
        logger.info(
            f"Tenant cache enabled: TTL={CACHE_TTL_SECONDS}s, "
            f"max_size={CACHE_MAX_SIZE}"
        )


# Run validation on import
_validate_configuration()


# =============================================================================
# PUBLIC API SUMMARY
# =============================================================================

"""
PUBLIC API:

Resolution Functions:
    resolve_tenant_from_teams_activity(activity) -> Optional[str]
    resolve_tenant_from_jwt(event) -> Optional[str]
    resolve_tenant_from_api_key(event) -> Optional[str]

Lookup Functions:
    lookup_tenant_by_entra_id(entra_tenant_id) -> Optional[Tenant]
    get_tenant(tenant_id, force_refresh=False) -> Optional[Tenant]
    get_tenant_or_raise(tenant_id, require_operational=True, require_agent=False) -> Tenant

Verification Functions:
    verify_tenant_operational(tenant_id) -> bool
    verify_tenant_access(requesting_tenant_id, target_tenant_id) -> bool
    verify_agent_ready(tenant_id) -> bool

Resource Helpers:
    get_secret_name(tenant_id, secret_type) -> str
    get_s3_path(tenant_id, path_type, filename=None) -> str
    get_s3_bucket(path_type) -> str

Batch Operations:
    list_all_tenants(status_filter=None, enabled_only=False) -> List[Tenant]
    count_tenants_by_status() -> Dict[str, int]

Cache Management:
    invalidate_tenant_cache(tenant_id) -> None
    clear_tenant_cache() -> None
    get_cache_stats() -> Dict[str, Any]

Utilities:
    normalize_tenant_id(tenant_id) -> str
    get_tenant_context_summary(tenant_id) -> Dict[str, Any]

Data Classes:
    Tenant (dataclass)
    TenantStatus (constants)
    ManagementMode (constants)
    SecretType (constants)
    S3PathType (constants)

Exceptions:
    TenantResolverError (base)
    TenantNotFoundError
    TenantDisabledError
    TenantNotActiveError
    InvalidTenantContextError
    TenantRegistryError
"""
