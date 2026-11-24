"""
Identity Tools for Bedrock Agent (Multi-Tenant, Phase 1)

Provides identity operations via Microsoft Graph API:
- Read-only: get_user_info, verify_identity, check_account_lockout, get_operation_status
- Write phase 1: request_password_reset, request_account_unlock
- Write phase 2: execute_password_reset (SECURE: generates one-time link)
- Write phase 2: execute_account_unlock

Multi-tenant additions (Phase 1):
- Tenant ID extracted from trusted session attributes (never from parameters)
- Secrets resolved per-tenant (tenant-scoped secret names)
- Graph API tokens cached per-tenant (different Entra tenants)
- Admin authorization uses tenant-specific admin group
- Audit logs include tenant_id
- Rate limits are tenant-scoped
"""

import json
import os
import logging
import secrets
import string
import urllib.parse
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
import boto3
from botocore.exceptions import ClientError

from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

import agent_security as sec
import password_reset_shared as prs
import tenant_resolver  # NEW: multi-tenant support

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# =============================================================================
# CONFIGURATION
# =============================================================================

ENTRA_GRAPH_SECRET_NAME = os.environ.get('ENTRA_GRAPH_SECRET_NAME')
ENTRA_TENANT_ID = os.environ.get('ENTRA_TENANT_ID')
ENTRA_APP_CLIENT_ID = os.environ.get('ENTRA_APP_CLIENT_ID')
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

# Multi-tenant configuration (NEW)
TENANT_REGISTRY_TABLE = os.environ.get('TENANT_REGISTRY_TABLE')
DEFAULT_TENANT_ID = os.environ.get('DEFAULT_TENANT_ID', 'default')
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')

# Password reset configuration
PASSWORD_RESET_URL = os.environ.get('PASSWORD_RESET_URL', '')

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
MIN_JUSTIFICATION_LENGTH = 20

secrets_client = boto3.client('secretsmanager', region_name=AWS_REGION)

_secret_cache: Dict[str, Dict[str, str]] = {}
_token_cache: Dict[str, Dict[str, Any]] = {}  # Now keyed by tenant_id


# =============================================================================
# SECRETS & GRAPH API (now tenant-aware)
# =============================================================================

def _infer_secret_type(secret_name: str) -> str:
    """Infers the secret type from its name for tenant-scoped lookup."""
    name_lower = secret_name.lower()
    if 'psa' in name_lower:
        return 'psa'
    if 'rmm' in name_lower:
        return 'rmm'
    if 'entra' in name_lower or 'graph' in name_lower:
        return 'graph'
    if 'webhook' in name_lower:
        return 'webhook'
    if 'unsubscribe' in name_lower:
        return 'unsubscribe'
    if 'teams' in name_lower or 'bot' in name_lower:
        return 'teams_bot'
    if 'confirmation' in name_lower:
        return 'confirmation'
    return 'unknown'


def get_secret(secret_name: str, tenant_id: Optional[str] = None) -> Dict[str, str]:
    """
    Fetches and caches secrets from AWS Secrets Manager.
    
    If tenant_id is provided, constructs a tenant-scoped secret name.
    Otherwise uses the literal secret_name (legacy behavior).
    
    Cache key includes tenant_id to prevent cross-tenant leakage.
    """
    if tenant_id:
        secret_type = _infer_secret_type(secret_name)
        actual_secret_name = tenant_resolver.get_tenant_secret_name(tenant_id, secret_type)
    else:
        actual_secret_name = secret_name
    
    cache_key = f"{tenant_id or 'none'}:{actual_secret_name}"
    
    if cache_key in _secret_cache:
        return _secret_cache[cache_key]
    
    try:
        response = secrets_client.get_secret_value(SecretId=actual_secret_name)
        secret = json.loads(response['SecretString'])
        _secret_cache[cache_key] = secret
        return secret
    except ClientError as e:
        logger.error(f"Failed to retrieve secret {actual_secret_name}: {e}")
        raise


@xray_recorder.capture('get_graph_access_token')
def get_graph_access_token(tenant_id: str = 'default') -> str:
    """
    Gets an OAuth2 access token for Microsoft Graph API.
    
    Now tenant-aware: different tenants may have different Entra tenants.
    Token cache is keyed by tenant_id.
    """
    current_time = datetime.utcnow().timestamp()
    cache_key = f"graph_token:{tenant_id}"
    
    if cache_key in _token_cache and _token_cache[cache_key]['expires_at'] > current_time + 300:
        return _token_cache[cache_key]['token']
    
    graph_secret = get_secret(ENTRA_GRAPH_SECRET_NAME, tenant_id=tenant_id)
    client_secret = graph_secret.get('CLIENT_SECRET')
    client_id = graph_secret.get('CLIENT_ID', ENTRA_APP_CLIENT_ID)
    tenant_id_for_auth = graph_secret.get('TENANT_ID', ENTRA_TENANT_ID)
    
    if not client_secret:
        raise ValueError("CLIENT_SECRET not found in Entra Graph credentials")
    
    token_url = f"https://login.microsoftonline.com/{tenant_id_for_auth}/oauth2/v2.0/token"
    
    body = urllib.parse.urlencode({
        'client_id': client_id,
        'client_secret': client_secret,
        'scope': 'https://graph.microsoft.com/.default',
        'grant_type': 'client_credentials'
    }).encode('utf-8')
    
    req = urllib.request.Request(
        token_url,
        data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST'
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            token_response = json.loads(response.read().decode('utf-8'))
        
        access_token = token_response['access_token']
        expires_in = token_response.get('expires_in', 3600)
        
        _token_cache[cache_key] = {
            'token': access_token,
            'expires_at': current_time + expires_in
        }
        
        logger.info(f"Successfully obtained Graph API access token for tenant {tenant_id}")
        return access_token
    
    except Exception as e:
        logger.error(f"Failed to obtain Graph API access token for tenant {tenant_id}: {e}")
        raise


def graph_api_request(endpoint: str, method: str = 'GET', body: Dict = None,
                      tenant_id: str = 'default') -> Dict[str, Any]:
    """Makes a request to the Microsoft Graph API, tenant-aware."""
    access_token = get_graph_access_token(tenant_id=tenant_id)
    url = f"{GRAPH_API_BASE}{endpoint}"
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    req = urllib.request.Request(url, headers=headers, method=method)
    if body:
        req.data = json.dumps(body).encode('utf-8')
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read()
            if response.status == 204 or not raw:
                return {}
            return json.loads(raw.decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        logger.error(f"Graph API error {e.code}: {error_body}")
        raise
    except Exception as e:
        logger.error(f"Graph API request failed: {e}")
        raise


def find_user_by_identifier(user_identifier: str, tenant_id: str = 'default') -> Optional[Dict[str, Any]]:
    """Finds a user by email address or display name, tenant-aware."""
    if '@' in user_identifier:
        try:
            return graph_api_request(f"/users/{user_identifier}", tenant_id=tenant_id)
        except Exception as e:
            logger.warning(f"User not found by email {user_identifier}: {e}")
            return None
    
    try:
        result = graph_api_request(
            f"/users?$filter=startsWith(displayName,'{user_identifier}')&$top=1",
            tenant_id=tenant_id
        )
        users = result.get('value', [])
        return users[0] if users else None
    except Exception as e:
        logger.warning(f"User search failed for {user_identifier}: {e}")
        return None


def get_user_manager(user_id: str, tenant_id: str = 'default') -> Optional[str]:
    """Gets the user's manager display name, tenant-aware."""
    try:
        result = graph_api_request(f"/users/{user_id}/manager", tenant_id=tenant_id)
        return result.get('displayName')
    except Exception as e:
        logger.warning(f"Failed to get manager for user {user_id}: {e}")
        return None


# =============================================================================
# READ-ONLY TOOLS
# =============================================================================

@xray_recorder.capture('tool_get_user_info')
def tool_get_user_info(params: Dict[str, Any], identity: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user_identifier = params.get('user_identifier')
    tenant_id = (identity or {}).get('tenant_id', 'default')
    
    if not user_identifier:
        return {'success': False, 'error': 'user_identifier is required'}
    
    logger.info(f"Looking up user: {user_identifier} (tenant: {tenant_id})")
    user = find_user_by_identifier(user_identifier, tenant_id=tenant_id)
    
    if not user:
        result = {'success': False, 'error': f'User not found: {user_identifier}'}
        sec.write_audit(tenant_id=tenant_id, actor_aad_id='unknown', tool_name='get_user_info',
                       operation_type='read', parameters=params, result=result, success=False)
        return result
    
    manager_name = get_user_manager(user['id'], tenant_id=tenant_id)
    
    result = {
        'success': True,
        'user_id': user['id'],
        'display_name': user.get('displayName'),
        'email': user.get('mail') or user.get('userPrincipalName'),
        'job_title': user.get('jobTitle'),
        'department': user.get('department'),
        'manager': manager_name,
    }
    
    sec.write_audit(tenant_id=tenant_id, actor_aad_id='unknown', tool_name='get_user_info',
                   operation_type='read', parameters=params, result=result, success=True,
                   target_user_id=user['id'])
    return result


@xray_recorder.capture('tool_verify_identity')
def tool_verify_identity(params: Dict[str, Any], identity: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user_id = params.get('user_id')
    tenant_id = (identity or {}).get('tenant_id', 'default')
    
    if not user_id:
        return {'success': False, 'error': 'user_id is required'}
    
    logger.info(f"Verifying identity for user: {user_id} (tenant: {tenant_id})")
    
    try:
        auth_methods = graph_api_request(f"/users/{user_id}/authentication/methods", tenant_id=tenant_id)
        mfa_enabled = len(auth_methods.get('value', [])) > 1
        
        user_details = graph_api_request(f"/users/{user_id}?$select=signInActivity,accountEnabled", tenant_id=tenant_id)
        
        last_sign_in = None
        sign_in_activity = user_details.get('signInActivity', {})
        if sign_in_activity:
            last_sign_in = sign_in_activity.get('lastSignInDateTime')
        
        account_enabled = user_details.get('accountEnabled', False)
        
        result = {
            'success': True,
            'is_verified': True,
            'mfa_enabled': mfa_enabled,
            'last_sign_in': last_sign_in,
            'account_enabled': account_enabled,
        }
        
        sec.write_audit(tenant_id=tenant_id, actor_aad_id='unknown', tool_name='verify_identity',
                       operation_type='read', parameters=params, result=result, success=True,
                       target_user_id=user_id)
        return result
    
    except Exception as e:
        logger.error(f"Failed to verify identity for user {user_id}: {e}")
        result = {'success': False, 'error': f'Failed to verify identity: {str(e)}'}
        sec.write_audit(tenant_id=tenant_id, actor_aad_id='unknown', tool_name='verify_identity',
                       operation_type='read', parameters=params, result=result, success=False)
        return result


@xray_recorder.capture('tool_check_account_lockout')
def tool_check_account_lockout(params: Dict[str, Any], identity: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user_identifier = params.get('user_identifier')
    tenant_id = (identity or {}).get('tenant_id', 'default')
    
    if not user_identifier:
        return {'success': False, 'error': 'user_identifier is required'}
    
    logger.info(f"Checking account lockout for: {user_identifier} (tenant: {tenant_id})")
    user = find_user_by_identifier(user_identifier, tenant_id=tenant_id)
    
    if not user:
        result = {'success': False, 'error': f'User not found: {user_identifier}'}
        sec.write_audit(tenant_id=tenant_id, actor_aad_id='unknown', tool_name='check_account_lockout',
                       operation_type='read', parameters=params, result=result, success=False)
        return result
    
    try:
        user_details = graph_api_request(
            f"/users/{user['id']}?$select=accountEnabled,signInActivity",
            tenant_id=tenant_id
        )
        
        account_enabled = user_details.get('accountEnabled', False)
        sign_in_activity = user_details.get('signInActivity', {})
        
        is_locked_out = not account_enabled
        failed_sign_in_count = 0
        lockout_timestamp = None
        
        if is_locked_out:
            lockout_timestamp = sign_in_activity.get('lastNonInteractiveSignInDateTime')
        
        result = {
            'success': True,
            'user_id': user['id'],
            'display_name': user.get('displayName'),
            'is_locked_out': is_locked_out,
            'failed_sign_in_count': failed_sign_in_count,
            'lockout_timestamp': lockout_timestamp,
        }
        
        sec.write_audit(tenant_id=tenant_id, actor_aad_id='unknown', tool_name='check_account_lockout',
                       operation_type='read', parameters=params, result=result, success=True,
                       target_user_id=user['id'])
        return result
    
    except Exception as e:
        logger.error(f"Failed to check lockout for user {user_identifier}: {e}")
        result = {'success': False, 'error': f'Failed to check lockout status: {str(e)}'}
        sec.write_audit(tenant_id=tenant_id, actor_aad_id='unknown', tool_name='check_account_lockout',
                       operation_type='read', parameters=params, result=result, success=False)
        return result


@xray_recorder.capture('tool_get_operation_status')
def tool_get_operation_status(params: Dict[str, Any], identity: Dict[str, str]) -> Dict[str, Any]:
    confirmation_id = params.get('confirmation_id')
    
    if not confirmation_id:
        return {'success': False, 'error': 'confirmation_id is required'}
    
    return sec.get_operation_status(confirmation_id=confirmation_id, identity=identity)


# =============================================================================
# WRITE TOOLS — PHASE 1 (REQUEST)
# =============================================================================

def _resolve_target_and_authorize(params, identity):
    """Shared authorization for both request tools. Tenant-aware."""
    tenant_id = identity.get('tenant_id', 'default')
    target_identifier = params.get("target_user_identifier")
    
    if not target_identifier:
        raise ValueError("target_user_identifier is required.")

    target = find_user_by_identifier(target_identifier, tenant_id=tenant_id)
    if not target:
        raise ValueError(f"User not found: {target_identifier}")

    is_self = (target.get("id") == identity["actor_aad_id"])
    if is_self:
        return target, False, None

    # Look up tenant record to get admin group ID
    tenant_record = tenant_resolver.lookup_tenant_by_id(tenant_id)
    if not tenant_record:
        raise ValueError(f"Tenant {tenant_id} not found")
    
    tenant_admin_group_id = tenant_record.get('admin_group_id', '')
    
    # Not self -> requires server-verified admin privilege
    if not sec.is_authorized_admin(tenant_id, identity["actor_aad_id"],
                                    lambda *args, **kwargs: graph_api_request(*args, tenant_id=tenant_id, **kwargs),
                                    tenant_admin_group_id):
        raise ValueError(
            "You can only manage your own account. Resetting another user's account "
            "requires IT administrator privileges. I can raise a ticket for you instead."
        )

    justification = (params.get("justification") or "").strip()
    if len(justification) < MIN_JUSTIFICATION_LENGTH:
        raise ValueError(
            f"Administrator actions require a justification of at least "
            f"{MIN_JUSTIFICATION_LENGTH} characters explaining the business reason."
        )

    return target, True, justification


@xray_recorder.capture('tool_request_password_reset')
def tool_request_password_reset(params, identity):
    tenant_id = identity.get('tenant_id', 'default')
    
    try:
        target, is_admin, justification = _resolve_target_and_authorize(params, identity)
    except ValueError as exc:
        sec.write_audit(tenant_id=tenant_id, actor_aad_id=identity["actor_aad_id"],
                        tool_name="request_password_reset", operation_type="write",
                        parameters=params, result={"error": str(exc)}, success=False)
        return {"success": False, "error": str(exc)}

    allowed, message = sec.consume_rate_limit(
        tenant_id=tenant_id,
        actor=identity["actor_aad_id"], operation="password_reset_request",
        is_admin=is_admin,
    )
    if not allowed:
        return {"success": False, "error": message}

    pending = sec.create_pending_operation(
        identity=identity, operation_type="password_reset", target=target,
        is_admin_override=is_admin, justification=justification,
    )
    sec.write_audit(tenant_id=tenant_id, actor_aad_id=identity["actor_aad_id"],
                    tool_name="request_password_reset", operation_type="write",
                    parameters=params, result=pending, success=True,
                    target_user_id=target["id"], is_admin_override=is_admin,
                    confirmation_id=pending["confirmation_id"],
                    justification=justification)
    return {"success": True, **pending}


@xray_recorder.capture('tool_request_account_unlock')
def tool_request_account_unlock(params, identity):
    tenant_id = identity.get('tenant_id', 'default')
    
    try:
        target, is_admin, justification = _resolve_target_and_authorize(params, identity)
    except ValueError as exc:
        sec.write_audit(tenant_id=tenant_id, actor_aad_id=identity["actor_aad_id"],
                        tool_name="request_account_unlock", operation_type="write",
                        parameters=params, result={"error": str(exc)}, success=False)
        return {"success": False, "error": str(exc)}

    allowed, message = sec.consume_rate_limit(
        tenant_id=tenant_id,
        actor=identity["actor_aad_id"], operation="account_unlock_request",
        is_admin=is_admin,
    )
    if not allowed:
        return {"success": False, "error": message}

    pending = sec.create_pending_operation(
        identity=identity, operation_type="account_unlock", target=target,
        is_admin_override=is_admin, justification=justification,
    )
    sec.write_audit(tenant_id=tenant_id, actor_aad_id=identity["actor_aad_id"],
                    tool_name="request_account_unlock", operation_type="write",
                    parameters=params, result=pending, success=True,
                    target_user_id=target["id"], is_admin_override=is_admin,
                    confirmation_id=pending["confirmation_id"],
                    justification=justification)
    return {"success": True, **pending}


# =============================================================================
# WRITE TOOLS — PHASE 2 (EXECUTE)
# =============================================================================

@xray_recorder.capture('tool_execute_password_reset')
def tool_execute_password_reset(params: Dict[str, Any], identity: Dict[str, Any]) -> Dict[str, Any]:
    """Phase 2: Execute a password reset by generating a secure one-time reset link."""
    tenant_id = identity.get('tenant_id', 'default')
    confirmation_id = params.get('confirmation_id')
    
    if not confirmation_id:
        return {'success': False, 'error': 'confirmation_id is required.', 'retryable': False}
    
    try:
        pending = sec.claim_approved_operation(
            confirmation_id=confirmation_id, identity=identity,
            expected_operation='password_reset',
        )
    except ValueError as exc:
        return {'success': False, 'error': str(exc), 'retryable': False}
    
    is_admin = bool(pending.get('is_admin_override'))
    target_user_id = pending['target_user_id']
    target_display_name = pending.get('target_display_name', '')
    
    allowed, message = sec.consume_rate_limit(
        tenant_id=tenant_id,
        actor=identity['actor_aad_id'], operation='password_reset',
        is_admin=is_admin, target_id=target_user_id,
    )
    if not allowed:
        sec.mark_operation_failed(confirmation_id, 'rate_limit')
        return {'success': False, 'error': message}
    
    # Get target user's email for the reset link
    target_email = pending.get('target_upn', '')
    if not target_email:
        try:
            user_info = graph_api_request(f"/users/{target_user_id}?$select=mail,userPrincipalName", tenant_id=tenant_id)
            target_email = user_info.get('mail') or user_info.get('userPrincipalName', '')
        except Exception as e:
            logger.warning(f"Failed to fetch target email: {e}")
    
        # Generate the reset token (using shared module, now tenant-scoped)
    try:
        token = prs.generate_reset_token(
            user_aad_id=target_user_id,
            initiator_aad_id=identity['actor_aad_id'],
            initiator_name=identity['actor_name'],
            is_admin_override=is_admin,
            tenant_id=tenant_id,  # NEW: pass tenant context
        )
    except Exception as e:
        logger.error(f"Failed to generate reset token: {e}")
        sec.refund_rate_limit(tenant_id=tenant_id, actor=identity['actor_aad_id'],
                              operation='password_reset', is_admin=is_admin, target_id=target_user_id)
        sec.mark_operation_failed(confirmation_id, str(e))
        return {'success': False, 'error': 'Failed to generate reset link. Please contact IT support.'}
    
    if not PASSWORD_RESET_URL:
        logger.error("PASSWORD_RESET_URL not configured")
        sec.mark_operation_failed(confirmation_id, 'missing_config')
        return {'success': False, 'error': 'Password reset service is not configured. Please contact IT.'}
    
    # Send the reset email to the target user
    email_sent = False
    if target_email:
        try:
            # Fetch user info for the email template (using tenant-scoped Graph credentials)
            user_info = graph_api_request(
                f"/users/{target_user_id}?$select=displayName,mail,userPrincipalName",
                tenant_id=tenant_id  # NEW
            )
            email_sent = prs.send_reset_email(
                user_email=target_email,
                user_info=user_info,
                token=token,
                reset_url=PASSWORD_RESET_URL,
                initiator_name=identity['actor_name'],
                is_admin_override=is_admin,
            )
        except Exception as e:
            logger.error(f"Failed to send reset email: {e}")
    
    occurred_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    result = {
        'success': True,
        'email_sent': email_sent,
        'target_email': target_email,
        'token_prefix': token[:8] + '...',
        'message': (
            f"A secure password reset link has been sent to {target_display_name}'s registered email. "
            f"The link is valid for {prs.TOKEN_TTL_SECONDS // 60} minutes and can only be used once. "
            f"The user will set their own password through a secure form — you will not see or transmit the password."
        ),
    }
    
    if not email_sent:
        # Security: do NOT return the reset link to the agent
        sec.mark_operation_failed(confirmation_id, "email_delivery_failed")
        logger.error(f"Failed to send reset email to {target_email} for user {target_user_id}")
        return {
            'success': False,
            'error': (
                "The secure password reset email could not be delivered. "
                "Please contact IT support or try again later."
            ),
        }
    
    sec.write_audit(
        tenant_id=tenant_id,
        actor_aad_id=identity['actor_aad_id'],
        tool_name='execute_password_reset',
        operation_type='write',
        parameters=params,
        result=result,
        success=True,
        target_user_id=target_user_id,
        is_admin_override=is_admin,
        confirmation_id=confirmation_id,
        justification=pending.get('justification'),
    )
    
    sec.notify_security_event(
        event_type='password_reset',
        target_email=target_email,
        target_display_name=target_display_name,
        actor_display_name=identity['actor_name'],
        is_admin_override=is_admin,
        occurred_at=occurred_at,
        extra_guidance=(
            "A secure link has been sent to your registered email address. "
            "Click the link to set your new password. The link expires in "
            f"{prs.TOKEN_TTL_SECONDS // 60} minutes."
        ),
    )
    
    logger.info(f"Password reset link generated for user {target_user_id} in tenant {tenant_id} (token: {token[:8]}...)")
    return result


@xray_recorder.capture('tool_execute_account_unlock')
def tool_execute_account_unlock(params: Dict[str, Any], identity: Dict[str, Any]) -> Dict[str, Any]:
    """Phase 2: Execute an account unlock for a previously approved operation."""
    tenant_id = identity.get('tenant_id', 'default')
    confirmation_id = params.get('confirmation_id')
    
    if not confirmation_id:
        return {'success': False, 'error': 'confirmation_id is required.', 'retryable': False}
    
    try:
        pending = sec.claim_approved_operation(
            confirmation_id=confirmation_id, identity=identity,
            expected_operation='account_unlock',
        )
    except ValueError as exc:
        return {'success': False, 'error': str(exc), 'retryable': False}
    
    is_admin = bool(pending.get('is_admin_override'))
    target_id = pending['target_user_id']
    
    allowed, message = sec.consume_rate_limit(
        tenant_id=tenant_id,
        actor=identity['actor_aad_id'], operation='account_unlock',
        is_admin=is_admin, target_id=target_id,
    )
    if not allowed:
        sec.mark_operation_failed(confirmation_id, 'rate_limit')
        return {'success': False, 'error': message}
    
    occurred_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    
    try:
        user_details = graph_api_request(f"/users/{target_id}?$select=accountEnabled", tenant_id=tenant_id)
        was_disabled = not user_details.get('accountEnabled', True)
        
        if not was_disabled:
            result = {
                'success': True,
                'was_disabled': False,
                'message': f"Account for {pending.get('target_display_name')} is already enabled. "
                           f"If you're having trouble signing in, the issue may be a temporary lockout "
                           f"from failed attempts. Try resetting your password instead."
            }
            sec.write_audit(tenant_id=tenant_id, actor_aad_id=identity['actor_aad_id'],
                           tool_name='execute_account_unlock', operation_type='write',
                           parameters=params, result=result, success=True,
                           target_user_id=target_id, is_admin_override=is_admin,
                           confirmation_id=confirmation_id,
                           justification=pending.get('justification'))
            return result
        
        graph_api_request(
            f"/users/{target_id}", method='PATCH',
            body={'accountEnabled': True},
            tenant_id=tenant_id
        )
    except Exception as exc:
        sec.refund_rate_limit(tenant_id=tenant_id, actor=identity['actor_aad_id'],
                              operation='account_unlock', is_admin=is_admin, target_id=target_id)
        sec.mark_operation_failed(confirmation_id, str(exc))
        logger.error(f"Account unlock failed for {target_id}: {exc}")
        sec.write_audit(tenant_id=tenant_id, actor_aad_id=identity['actor_aad_id'],
                        tool_name='execute_account_unlock', operation_type='write',
                        parameters=params, result={'error': str(exc)}, success=False,
                        target_user_id=target_id, is_admin_override=is_admin,
                        confirmation_id=confirmation_id)
        return {'success': False,
                'error': 'The directory rejected the account unlock. Please contact IT support.'}
    
    sec.notify_security_event(
        event_type='account_unlock',
        target_email=pending.get('target_upn', ''),
        target_display_name=pending.get('target_display_name', ''),
        actor_display_name=identity['actor_name'],
        is_admin_override=is_admin, occurred_at=occurred_at,
    )
    
    result = {
        'success': True,
        'was_disabled': True,
        'message': f"Account for {pending.get('target_display_name')} has been re-enabled. "
                   f"You should now be able to sign in. A security notification email has been sent.",
    }
    sec.write_audit(tenant_id=tenant_id, actor_aad_id=identity['actor_aad_id'],
                    tool_name='execute_account_unlock', operation_type='write',
                    parameters=params, result=result, success=True,
                    target_user_id=target_id, is_admin_override=is_admin,
                    confirmation_id=confirmation_id,
                    justification=pending.get('justification'))
    return result


# =============================================================================
# LAMBDA HANDLER (tenant-aware)
# =============================================================================

_WRITE_TOOLS = {
    '/request-password-reset':  tool_request_password_reset,
    '/execute-password-reset':  tool_execute_password_reset,
    '/request-account-unlock':  tool_request_account_unlock,
    '/execute-account-unlock':  tool_execute_account_unlock,
    '/get-operation-status':    tool_get_operation_status,
}

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main entry point for the Bedrock Agent action group."""
    logger.info(f"Agent action group invoked: {json.dumps(event, default=str)}")
    
    api_path = event.get('apiPath')
    parameters = event.get('parameters', [])
    params = {p['name']: p['value'] for p in parameters}
    
    # Strip any identity/privilege fields the model may try to inject
    for forbidden in ('user_aad_id', 'is_admin', 'is_admin_override', 'actor_aad_id', 'tenant_id'):
        params.pop(forbidden, None)
    
    try:
        # Extract trusted identity AND tenant (NEW)
        identity = sec.extract_trusted_identity(event)
        tenant_id = tenant_resolver.extract_trusted_tenant_id(event)  # NEW
        
        # Add user email and tenant context from session attributes
        attrs = event.get('sessionAttributes') or {}
        identity['user_email'] = attrs.get('user_email')
        identity['tenant_id'] = tenant_id  # NEW
        
        if api_path in _WRITE_TOOLS:
            result = _WRITE_TOOLS[api_path](params, identity)
        elif api_path == '/get-user-info':
            result = tool_get_user_info(params, identity)
        elif api_path == '/verify-identity':
            result = tool_verify_identity(params, identity)
        elif api_path == '/check-account-lockout':
            result = tool_check_account_lockout(params, identity)
        else:
            result = {
                'success': False,
                'error': f'Unknown API path: {api_path}'
            }
    except sec.IdentityError as exc:
        result = {'success': False, 'error': str(exc)}
    except tenant_resolver.TenantResolutionError as exc:
        result = {'success': False, 'error': str(exc)}
    except Exception as exc:
        logger.exception(f"Error in agent action group: {e}")
        result = {'success': False, 'error': 'An internal error occurred. Please contact IT support.'}
    
    response_body = {
        'application/json': {
            'body': json.dumps(result)
        }
    }
    
    action_response = {
        'messageVersion': '1.0',
        'response': {
            'actionGroup': event.get('actionGroup'),
            'apiPath': api_path,
            'httpMethod': event.get('httpMethod'),
            'httpStatusCode': 200 if result.get('success', False) else 400,
            'responseBody': response_body
        }
    }
    
    logger.info(f"Tool response: {json.dumps(result, default=str)}")
    return action_response
