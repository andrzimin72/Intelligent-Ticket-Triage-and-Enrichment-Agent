"""
Shared modules for MSP Triage Infrastructure Lambda functions.

This package contains reusable modules that are copied into multiple
Lambda function deployment packages. These modules provide common
functionality across different services.

Modules:
    tenant_resolver: Multi-tenant resolution and isolation logic
        - Resolves tenant from Teams activity (Entra tenant ID)
        - Provides tenant-scoped secret names
        - Validates tenant context

Usage in Lambda functions:
    # Copy this module into your Lambda source directory
    cp src_shared/tenant_resolver.py src_your_lambda/
    
    # Import in your Lambda code
    import tenant_resolver
    
    # Resolve tenant from Teams activity
    entra_tenant_id = tenant_resolver.resolve_tenant_from_teams_activity(activity)
    tenant = tenant_resolver.lookup_tenant_by_entra_id(entra_tenant_id)
    
    # Get tenant-scoped secret name
    secret_name = tenant_resolver.get_tenant_secret_name(tenant_id, "graph")

Security Model:
    - Tenant ID is extracted from trusted sources (Teams activity)
    - Never from LLM parameters or user input
    - All operations are scoped by tenant_id
    - Cross-tenant access is prevented by design

Version: 1.0.0
"""

__version__ = "1.0.0"
__author__ = "MSP Triage Platform Team"

# Expose main modules for convenient importing
from . import tenant_resolver

__all__ = [
    "tenant_resolver",
    "__version__",
]