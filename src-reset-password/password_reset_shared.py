"""
Password Reset Shared Module (Phase 3: Tenant-Scoped)

Common logic for the secure password reset flow:
- Token generation and validation (now tenant-scoped)
- Email sending (reset link + confirmation)
- Password validation against Entra ID policy
- Graph API helpers (tenant-aware)
- Audit logging (tenant-scoped)

Security properties:
- Tokens are 256-bit random, unguessable
- Tokens are single-use (atomic conditional update)
- Tokens expire after TTL (default 15 minutes)
- Tokens are bound to a specific user AND tenant (NEW)
- Rate limit: max N attempts per token before invalidation
- Password validated against Entra ID policy server-side
- Full audit trail (without logging the password itself)
"""

import json
import os
import logging
import secrets
import string
import urllib.parse
import urllib.request
import urllib.error
import re
import time
import uuid
import html
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION (read from environment variables)
# =============================================================================

ENTRA_GRAPH_SECRET_NAME = os.environ.get('ENTRA_GRAPH_SECRET_NAME')
ENTRA_TENANT_ID = os.environ.get('ENTRA_TENANT_ID')
ENTRA_APP_CLIENT_ID = os.environ.get('ENTRA_APP_CLIENT_ID')
RESET_TOKENS_TABLE = os.environ.get('RESET_TOKENS_TABLE')
AUDIT_LOG_TABLE = os.environ.get('AUDIT_LOG_TABLE')
TENANT_REGISTRY_TABLE = os.environ.get('TENANT_REGISTRY_TABLE')  # NEW
TOKEN_TTL_SECONDS = int(os.environ.get('TOKEN_TTL_SECONDS', '900'))  # 15 minutes
MAX_ATTEMPTS_PER_TOKEN = int(os.environ.get('MAX_ATTEMPTS_PER_TOKEN', '5'))
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
SUPPORT_EMAIL = os.environ.get('SUPPORT_EMAIL', 'support@yourmsp.com')
MSP_COMPANY_NAME = os.environ.get('MSP_COMPANY_NAME', 'Your MSP')
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

# Entra ID default password policy
MIN_PASSWORD_LENGTH = 8
RECOMMENDED_PASSWORD_LENGTH = 12

# =============================================================================
# AWS CLIENTS
# =============================================================================

secrets_client = boto3.client('secretsmanager', region_name=AWS_REGION)
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
ses_client = boto3.client('ses', region_name=AWS_REGION)
cloudwatch = boto3.client('cloudwatch', region_name=AWS_REGION)

_secret_cache: Dict[str, Dict[str, str]] = {}
_graph_token_cache: Dict[str, Dict[str, Any]] = {}  # Now keyed by tenant_id


# =============================================================================
# TENANT-AWARE SECRETS & GRAPH API
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
        # Construct tenant-scoped secret name
        environment = os.environ.get('ENVIRONMENT', 'dev')
        if tenant_id == 'default':
            # Backward compatibility: default tenant uses legacy paths
            legacy_names = {
                'graph': f"{environment}/msp/entra/graph_credentials",
            }
            actual_secret_name = legacy_names.get(secret_type, f"{environment}/tenants/{tenant_id}/{secret_type}")
        else:
            actual_secret_name = f"{environment}/tenants/{tenant_id}/{secret_type}"
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


def get_graph_token(tenant_id: str = 'default') -> str:
    """
    Gets a Microsoft Graph access token, tenant-aware.
    
    Different tenants may have different Entra tenants and credentials.
    Token cache is keyed by tenant_id.
    """
    current_time = time.time()
    cache_key = f"graph_token:{tenant_id}"
    
    if cache_key in _graph_token_cache and _graph_token_cache[cache_key]['expires_at'] > current_time + 300:
        return _graph_token_cache[cache_key]['token']
    
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
        'grant_type': 'client_credentials',
    }).encode()
    
    req = urllib.request.Request(
        token_url,
        data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            payload = json.loads(r.read())
        
        _graph_token_cache[cache_key] = {
            'token': payload['access_token'],
            'expires_at': current_time + payload.get('expires_in', 3600),
        }
        
        logger.info(f"Obtained Graph token for tenant {tenant_id}")
        return payload['access_token']
    
    except Exception as e:
        logger.error(f"Failed to obtain Graph token for tenant {tenant_id}: {e}")
        raise


def graph_request(endpoint: str, method: str = 'GET', body: Dict = None,
                  tenant_id: str = 'default') -> Dict[str, Any]:
    """Makes a request to the Microsoft Graph API, tenant-aware."""
    token = get_graph_token(tenant_id=tenant_id)
    url = f"{GRAPH_API_BASE}{endpoint}"
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    
    req = urllib.request.Request(url, headers=headers, method=method)
    if body:
        req.data = json.dumps(body).encode('utf-8')
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
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


def get_user_info(user_aad_id: str, tenant_id: str = 'default') -> Optional[Dict[str, Any]]:
    """Gets user info from Graph for display on the form, tenant-aware."""
    try:
        return graph_request(f"/users/{user_aad_id}?$select=displayName,mail,userPrincipalName",
                            tenant_id=tenant_id)
    except Exception as e:
        logger.error(f"Failed to get user info for {user_aad_id} in tenant {tenant_id}: {e}")
        return None


# =============================================================================
# TOKEN MANAGEMENT (Phase 3: tenant-scoped)
# =============================================================================

def generate_reset_token(user_aad_id: str, initiator_aad_id: str,
                         initiator_name: str, is_admin_override: bool,
                         tenant_id: str = 'default') -> str:
    """
    Generates a single-use, time-limited password reset token.
    
    Phase 3: Now includes tenant_id for cross-tenant isolation.
    
    Returns the token string (URL-safe, 256 bits of entropy).
    """
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = int(now.timestamp()) + TOKEN_TTL_SECONDS
    
    dynamodb.Table(RESET_TOKENS_TABLE).put_item(
        Item={
            'token': token,
            'tenant_id': tenant_id,              # NEW: tenant binding
            'user_aad_id': user_aad_id,
            'initiator_aad_id': initiator_aad_id,
            'initiator_name': initiator_name,
            'is_admin_override': is_admin_override,
            'status': 'pending',
            'attempts': 0,
            'created_at': now.isoformat(),
            'expires_at': expires_at,
            'ttl': expires_at + 3600,  # Keep in DB for 1 hour after expiry for audit
        },
        ConditionExpression='attribute_not_exists(token)',
    )
    
    logger.info(f"Generated reset token for user {user_aad_id} in tenant {tenant_id} (initiator: {initiator_aad_id})")
    return token


def validate_token(token: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Validates a reset token.
    
    Phase 3: Returns tenant_id from the token record for downstream use.
    
    Returns: (is_valid, token_record, error_message)
    """
    if not token:
        return False, None, "Missing token."
    
    try:
        table = dynamodb.Table(RESET_TOKENS_TABLE)
        response = table.get_item(Key={'token': token})
        item = response.get('Item')
        
        if not item:
            return False, None, "This reset link is invalid or has already been used."
        
        # Check expiration
        if int(item.get('expires_at', 0)) < int(time.time()):
            return False, item, "This reset link has expired. Please request a new one."
        
        # Check status
        if item.get('status') == 'consumed':
            return False, item, "This reset link has already been used."
        
        if item.get('status') == 'invalidated':
            return False, item, "This reset link has been invalidated due to too many failed attempts."
        
        # Phase 3: Verify tenant_id exists (backward compatibility for old tokens)
        if not item.get('tenant_id'):
            logger.warning(f"Token {token[:8]}... missing tenant_id — treating as 'default'")
            item['tenant_id'] = 'default'
        
        return True, item, ""
    
    except ClientError as e:
        logger.error(f"Failed to validate token: {e}")
        return False, None, "Unable to validate this reset link. Please try again."


def mark_token_consumed(token: str) -> bool:
    """Atomically marks a token as consumed (single-use enforcement)."""
    try:
        dynamodb.Table(RESET_TOKENS_TABLE).update_item(
            Key={'token': token},
            UpdateExpression='SET #s = :consumed, consumed_at = :ts',
            ConditionExpression='#s = :pending',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':consumed': 'consumed',
                ':pending': 'pending',
                ':ts': datetime.now(timezone.utc).isoformat(),
            },
        )
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            return False
        logger.error(f"Failed to mark token consumed: {e}")
        return False


def increment_token_attempts(token: str) -> int:
    """
    Increments the attempt counter for a token.
    If the counter exceeds MAX_ATTEMPTS_PER_TOKEN, invalidates the token.
    
    Returns the new attempt count.
    """
    try:
        table = dynamodb.Table(RESET_TOKENS_TABLE)
        response = table.update_item(
            Key={'token': token},
            UpdateExpression='ADD attempts :one SET last_attempt_at = :ts',
            ConditionExpression='attempts < :max',
            ExpressionAttributeValues={
                ':one': 1,
                ':max': MAX_ATTEMPTS_PER_TOKEN,
                ':ts': datetime.now(timezone.utc).isoformat(),
            },
            ReturnValues='ALL_NEW',
        )
        return response['Attributes'].get('attempts', 1)
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            # Max attempts exceeded — invalidate the token
            try:
                table.update_item(
                    Key={'token': token},
                    UpdateExpression='SET #s = :invalidated',
                    ExpressionAttributeNames={'#s': 'status'},
                    ExpressionAttributeValues={':invalidated': 'invalidated'},
                )
                logger.warning(f"Token {token[:8]}... invalidated after {MAX_ATTEMPTS_PER_TOKEN} failed attempts")
                _emit_abuse_metric()
            except ClientError as inner_e:
                logger.error(f"Failed to invalidate token: {inner_e}")
            return MAX_ATTEMPTS_PER_TOKEN + 1
        logger.error(f"Failed to increment attempts: {e}")
        return 0


def _emit_abuse_metric():
    """Emits a CloudWatch metric for token abuse attempts."""
    try:
        cloudwatch.put_metric_data(
            Namespace='Custom/MSP-Agent',
            MetricData=[{
                'MetricName': 'ResetTokenAbuseAttempts',
                'Value': 1,
                'Unit': 'Count',
            }],
        )
    except Exception as e:
        logger.warning(f"Failed to emit abuse metric: {e}")


# =============================================================================
# PASSWORD VALIDATION
# =============================================================================

def validate_password(password: str, user_info: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validates a password against Entra ID policy.
    
    Entra default policy:
    - Min 8 characters
    - Must contain 3 of: uppercase, lowercase, digits, special chars
    - Cannot contain the user's account name (parts of display name / UPN)
    - Max 256 characters
    
    Returns: (is_valid, error_message)
    """
    if not password:
        return False, "Password is required."
    
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    
    if len(password) > 256:
        return False, "Password must be 256 characters or fewer."
    
    # Count character class presence
    has_upper = bool(re.search(r'[A-Z]', password))
    has_lower = bool(re.search(r'[a-z]', password))
    has_digit = bool(re.search(r'\d', password))
    has_special = bool(re.search(r'[^A-Za-z0-9]', password))
    
    classes_present = sum([has_upper, has_lower, has_digit, has_special])
    if classes_present < 3:
        return False, "Password must contain at least 3 of: uppercase letters, lowercase letters, digits, special characters."
    
    # Check password doesn't contain user identifiers
    display_name = (user_info.get('displayName') or '').lower()
    upn = (user_info.get('userPrincipalName') or '').lower()
    mail = (user_info.get('mail') or '').lower()
    
    # Extract name parts (first/last name)
    name_parts = []
    if display_name:
        name_parts.extend(display_name.split())
    if upn and '@' in upn:
        name_parts.append(upn.split('@')[0])
    if mail and '@' in mail:
        name_parts.append(mail.split('@')[0])
    
    password_lower = password.lower()
    for part in name_parts:
        if len(part) >= 3 and part in password_lower:
            return False, "Password cannot contain parts of your name or email address."
    
    # Recommend (but don't require) stronger passwords
    if len(password) < RECOMMENDED_PASSWORD_LENGTH:
        logger.info(f"Password meets minimum requirements but is under {RECOMMENDED_PASSWORD_LENGTH} chars")
    
    return True, ""


# =============================================================================
# EMAIL TEMPLATES
# =============================================================================

def build_reset_email_html(token: str, reset_url: str, user_info: Dict[str, Any],
                           initiator_name: str, is_admin_override: bool) -> str:
    """Builds the HTML email containing the reset link."""
    user_name = html.escape(user_info.get('displayName', 'there'))
    initiator = html.escape(initiator_name)
    company = html.escape(MSP_COMPANY_NAME)
    support = html.escape(SUPPORT_EMAIL)
    
    # Build the full URL with token
    full_url = f"{reset_url}?token={token}"
    
    who_initiated = "you" if not is_admin_override else f"an administrator ({initiator})"
    ttl_minutes = TOKEN_TTL_SECONDS // 60
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; background-color: #f5f5f5;">
    <div style="background-color: #2c3e50; color: white; padding: 20px; text-align: center;">
        <h1 style="margin: 0; font-size: 22px;">Password Reset Request</h1>
    </div>
    
    <div style="padding: 20px; background-color: white;">
        <p>Hello {user_name},</p>
        
        <p>A password reset was requested for your account by <strong>{who_initiated}</strong>.</p>
        
        <p>Click the button below to set your new password. This link is valid for <strong>{ttl_minutes} minutes</strong> and can only be used once.</p>
        
        <p style="text-align: center; margin: 30px 0;">
            <a href="{full_url}" 
               style="background-color: #3498db; color: white; padding: 12px 30px; 
                      text-decoration: none; border-radius: 5px; font-weight: bold;
                      display: inline-block;">
                Set New Password
            </a>
        </p>
        
        <p style="font-size: 13px; color: #7f8c8d;">
            If the button doesn't work, copy and paste this link into your browser:<br>
            <a href="{full_url}" style="color: #3498db; word-break: break-all;">{full_url}</a>
        </p>
        
        <div style="background-color: #fdecea; border-left: 4px solid #e74c3c; padding: 12px; margin: 20px 0;">
            <strong>Did not request this?</strong><br>
            If you did not request a password reset, your account may be compromised. 
            Please contact IT support immediately at <a href="mailto:{support}">{support}</a>.
        </div>
        
        <p style="font-size: 12px; color: #7f8c8d; margin-top: 20px;">
            For security, this email does not contain your password. You will set your new password 
            through the secure link above.
        </p>
    </div>
    
    <div style="background-color: #ecf0f1; padding: 15px; text-align: center; font-size: 12px; color: #7f8c8d;">
        <p style="margin: 0;">&copy; {datetime.now(timezone.utc).year} {company}. All rights reserved.</p>
    </div>
</body>
</html>"""


def build_confirmation_email_html(user_info: Dict[str, Any]) -> str:
    """Builds the 'password changed successfully' confirmation email."""
    user_name = html.escape(user_info.get('displayName', 'there'))
    company = html.escape(MSP_COMPANY_NAME)
    support = html.escape(SUPPORT_EMAIL)
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; background-color: #f5f5f5;">
    <div style="background-color: #27ae60; color: white; padding: 20px; text-align: center;">
        <h1 style="margin: 0; font-size: 22px;">✓ Password Changed Successfully</h1>
    </div>
    
    <div style="padding: 20px; background-color: white;">
        <p>Hello {user_name},</p>
        
        <p>Your password has been changed successfully. You can now sign in to your account with your new password.</p>
        
        <div style="background-color: #e8f5e9; border-left: 4px solid #27ae60; padding: 12px; margin: 20px 0;">
            <strong>If you did not make this change</strong>, please contact IT support immediately at 
            <a href="mailto:{support}">{support}</a>. Your account may be compromised.
        </div>
        
        <p style="font-size: 13px; color: #7f8c8d;">
            For your security, we never store or transmit your password.
        </p>
    </div>
    
    <div style="background-color: #ecf0f1; padding: 15px; text-align: center; font-size: 12px; color: #7f8c8d;">
        <p style="margin: 0;">&copy; {datetime.now(timezone.utc).year} {company}. All rights reserved.</p>
    </div>
</body>
</html>"""


def send_reset_email(user_email: str, user_info: Dict[str, Any], token: str,
                     reset_url: str, initiator_name: str, is_admin_override: bool) -> bool:
    """Sends the password reset email with the secure link."""
    try:
        ses_client.send_email(
            Source=SENDER_EMAIL,
            Destination={'ToAddresses': [user_email]},
            Message={
                'Subject': {'Data': 'Action Required: Set Your New Password', 'Charset': 'UTF-8'},
                'Body': {
                    'Html': {
                        'Data': build_reset_email_html(token, reset_url, user_info, initiator_name, is_admin_override),
                        'Charset': 'UTF-8',
                    },
                },
            },
            Tags=[{'Name': 'email_type', 'Value': 'password_reset_link'}],
        )
        logger.info(f"Reset email sent to {user_email}")
        return True
    except ClientError as e:
        logger.error(f"Failed to send reset email to {user_email}: {e}")
        return False


def send_confirmation_email(user_email: str, user_info: Dict[str, Any]) -> bool:
    """Sends the 'password changed' confirmation email."""
    try:
        ses_client.send_email(
            Source=SENDER_EMAIL,
            Destination={'ToAddresses': [user_email]},
            Message={
                'Subject': {'Data': 'Your Password Has Been Changed', 'Charset': 'UTF-8'},
                'Body': {
                    'Html': {
                        'Data': build_confirmation_email_html(user_info),
                        'Charset': 'UTF-8',
                    },
                },
            },
            Tags=[{'Name': 'email_type', 'Value': 'password_changed'}],
        )
        logger.info(f"Confirmation email sent to {user_email}")
        return True
    except ClientError as e:
        logger.error(f"Failed to send confirmation email to {user_email}: {e}")
        return False


# =============================================================================
# AUDIT LOGGING (Phase 3: tenant-scoped)
# =============================================================================

def write_audit(*, tenant_id: str,   # NEW
                event_type: str, token: str, user_aad_id: str,
                initiator_aad_id: str, success: bool, details: Dict[str, Any],
                source_ip: Optional[str] = None, user_agent: Optional[str] = None) -> None:
    """Writes an audit log entry. Never logs the password itself."""
    if not AUDIT_LOG_TABLE:
        return
    
    try:
        # Redact sensitive fields
        safe_details = {k: v for k, v in details.items() 
                       if k not in ('password', 'newPassword', 'confirmPassword')}
        
        dynamodb.Table(AUDIT_LOG_TABLE).put_item(Item={
            'audit_id': str(uuid.uuid4()),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'tenant_id': tenant_id,              # NEW
            'user_id': user_aad_id,
            'tool_name': 'reset_password',
            'operation_type': event_type,  # 'token_created', 'token_consumed', 'token_failed', 'token_abuse'
            'parameters': json.dumps({
                'token_prefix': token[:8] + '...' if token else 'none',  # Only log prefix, not full token
                'initiator_aad_id': initiator_aad_id,
                'source_ip': source_ip or '',
                'user_agent': (user_agent or '')[:200],
                **safe_details,
            }),
            'result_summary': json.dumps({'success': success}),
            'ttl': int(time.time()) + 365 * 86400,
        })
    except ClientError as e:
        logger.error(f"Failed to write audit log: {e}")
