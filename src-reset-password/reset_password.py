"""
Secure Password Reset — One-Time Link Flow (Phase 3: Tenant-Scoped)

Serves a self-service password reset form and processes submissions.
The form is accessed via a signed, single-use, time-limited token.

Security properties:
- Tokens are 256-bit random, unguessable
- Tokens are single-use (atomic conditional update)
- Tokens expire after TTL (default 15 minutes)
- Tokens are bound to a specific user AND tenant (NEW)
- Rate limit: max N attempts per token before invalidation
- Password validated against Entra ID policy server-side
- Full audit trail (without logging the password itself)
- Uses tenant-scoped Graph credentials (NEW)
- Uses tenant-scoped rate limits (NEW)
"""

import json
import os
import logging
import secrets
import string
import urllib.parse
import urllib.request
import urllib.error
import html
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
import boto3
from botocore.exceptions import ClientError

from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

import password_reset_shared as prs
import tenant_resolver  # NEW: tenant-aware

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# =============================================================================
# CONFIGURATION
# =============================================================================

RESET_TOKENS_TABLE = os.environ.get('RESET_TOKENS_TABLE')
AUDIT_LOG_TABLE = os.environ.get('AUDIT_LOG_TABLE')
TENANT_REGISTRY_TABLE = os.environ.get('TENANT_REGISTRY_TABLE')  # NEW
TOKEN_TTL_SECONDS = int(os.environ.get('TOKEN_TTL_SECONDS', '900'))
MAX_ATTEMPTS_PER_TOKEN = int(os.environ.get('MAX_ATTEMPTS_PER_TOKEN', '5'))
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
SUPPORT_EMAIL = os.environ.get('SUPPORT_EMAIL', 'support@yourmsp.com')
MSP_COMPANY_NAME = os.environ.get('MSP_COMPANY_NAME', 'Your MSP')
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)


# =============================================================================
# REQUEST HANDLERS (Phase 3: tenant-aware)
# =============================================================================

def handle_get(event: Dict[str, Any]) -> Dict[str, Any]:
    """Handles GET /set-password?token=... — shows the form or error page."""
    query_params = event.get('queryStringParameters') or {}
    token = query_params.get('token', '')
    
    is_valid, token_record, error_message = prs.validate_token(token)
    
    if not is_valid:
        return {
            'statusCode': 400,
            'headers': {
                'Content-Type': 'text/html; charset=utf-8',
                'Cache-Control': 'no-store',
            },
            'body': prs.build_error_page_html(error_message, SUPPORT_EMAIL),
        }
    
    # Extract tenant_id from token record (NEW)
    tenant_id = token_record.get('tenant_id', 'default')
    user_aad_id = token_record['user_aad_id']
    
    logger.info(f"Password reset form accessed for user {user_aad_id} in tenant {tenant_id}")
    
    # Fetch user info using tenant-scoped Graph credentials (NEW)
    user_info = prs.get_user_info(user_aad_id, tenant_id=tenant_id)
    if not user_info:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'},
            'body': prs.build_error_page_html("Unable to load your account information. Please contact IT support.", SUPPORT_EMAIL),
        }
    
    attempts_remaining = MAX_ATTEMPTS_PER_TOKEN - token_record.get('attempts', 0)
    
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'text/html; charset=utf-8',
            'Cache-Control': 'no-store, no-cache, must-revalidate, private',
            'Pragma': 'no-cache',
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'Referrer-Policy': 'no-referrer',
        },
        'body': prs.build_form_html(token, user_info, attempts_remaining=attempts_remaining),
    }


def handle_post(event: Dict[str, Any]) -> Dict[str, Any]:
    """Handles POST /set-password — processes the password submission."""
    # Parse form data (application/x-www-form-urlencoded)
    body = event.get('body', '')
    if event.get('isBase64Encoded'):
        import base64
        body = base64.b64decode(body).decode('utf-8')
    
    form_data = urllib.parse.parse_qs(body)
    token = (form_data.get('token') or [''])[0]
    new_password = (form_data.get('newPassword') or [''])[0]
    confirm_password = (form_data.get('confirmPassword') or [''])[0]
    
    source_ip = (event.get('requestContext', {})
                 .get('http', {})
                 .get('sourceIp', ''))
    user_agent = (event.get('headers') or {}).get('user-agent', '')[:200]
    
    # Validate token
    is_valid, token_record, error_message = prs.validate_token(token)
    
    if not is_valid:
        # Extract tenant_id if available for audit (NEW)
        tenant_id = token_record.get('tenant_id', 'unknown') if token_record else 'unknown'
        prs.write_audit(
            tenant_id=tenant_id,
            event_type='token_invalid_attempt',
            token=token, user_aad_id='unknown', initiator_aad_id='unknown',
            success=False, details={'reason': error_message},
            source_ip=source_ip, user_agent=user_agent,
        )
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'},
            'body': prs.build_error_page_html(error_message, SUPPORT_EMAIL),
        }
    
    # Extract tenant context (NEW)
    tenant_id = token_record.get('tenant_id', 'default')
    user_aad_id = token_record['user_aad_id']
    initiator_aad_id = token_record.get('initiator_aad_id', 'unknown')
    
    # Increment attempt counter (rate limiting)
    attempts = prs.increment_token_attempts(token)
    if attempts > MAX_ATTEMPTS_PER_TOKEN:
        prs.write_audit(
            tenant_id=tenant_id,
            event_type='token_abuse',
            token=token, user_aad_id=user_aad_id, initiator_aad_id=initiator_aad_id,
            success=False, details={'reason': 'max_attempts_exceeded'},
            source_ip=source_ip, user_agent=user_agent,
        )
        return {
            'statusCode': 429,
            'headers': {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'},
            'body': prs.build_error_page_html(
                "This reset link has been invalidated due to too many failed attempts. Please request a new password reset.",
                SUPPORT_EMAIL,
            ),
        }
    
    # Client-side validation check
    if new_password != confirm_password:
        user_info = prs.get_user_info(user_aad_id, tenant_id=tenant_id) or {}
        attempts_remaining = MAX_ATTEMPTS_PER_TOKEN - attempts
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'text/html; charset=utf-8',
                'Cache-Control': 'no-store, no-cache, must-revalidate, private',
            },
            'body': prs.build_form_html(
                token, user_info,
                error_message="Passwords do not match. Please try again.",
                attempts_remaining=attempts_remaining,
            ),
        }
    
    # Fetch user info for password validation (using tenant-scoped Graph credentials)
    user_info = prs.get_user_info(user_aad_id, tenant_id=tenant_id)
    if not user_info:
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'},
            'body': prs.build_error_page_html("Unable to load your account. Please contact IT support.", SUPPORT_EMAIL),
        }
    
    # Server-side password validation
    is_valid_pwd, pwd_error = prs.validate_password(new_password, user_info)
    if not is_valid_pwd:
        attempts_remaining = MAX_ATTEMPTS_PER_TOKEN - attempts
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'text/html; charset=utf-8',
                'Cache-Control': 'no-store, no-cache, must-revalidate, private',
            },
            'body': prs.build_form_html(
                token, user_info,
                error_message=pwd_error,
                attempts_remaining=attempts_remaining,
            ),
        }
    
    # Atomically mark token as consumed (prevents double-use)
    if not prs.mark_token_consumed(token):
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'},
            'body': prs.build_error_page_html("This reset link has already been used.", SUPPORT_EMAIL),
        }
    
    # Set the password via Graph API (using tenant-scoped credentials)
    try:
        prs.graph_request(
            f"/users/{user_aad_id}",
            method='PATCH',
            body={
                'passwordProfile': {
                    'password': new_password,
                    'forceChangePasswordNextSignIn': False,  # User just set it themselves
                },
            },
            tenant_id=tenant_id,  # NEW: use tenant-scoped Graph token
        )
    except Exception as e:
        logger.error(f"Failed to set password for {user_aad_id} in tenant {tenant_id}: {e}")
        # Token is already consumed — user needs a new reset
        prs.write_audit(
            tenant_id=tenant_id,
            event_type='password_set_failed',
            token=token, user_aad_id=user_aad_id, initiator_aad_id=initiator_aad_id,
            success=False, details={'error': str(e)[:200]},
            source_ip=source_ip, user_agent=user_agent,
        )
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'},
            'body': prs.build_error_page_html(
                "We were unable to set your password. The reset link has been consumed for security. Please request a new password reset.",
                SUPPORT_EMAIL,
            ),
        }
    
    # Success! Send confirmation email
    user_email = user_info.get('mail') or user_info.get('userPrincipalName')
    if user_email:
        prs.send_confirmation_email(user_email, user_info)
    
    # Audit log (never log the password)
    prs.write_audit(
        tenant_id=tenant_id,
        event_type='password_set_success',
        token=token, user_aad_id=user_aad_id, initiator_aad_id=initiator_aad_id,
        success=True, details={'password_length': len(new_password)},
        source_ip=source_ip, user_agent=user_agent,
    )
    
    logger.info(f"Password set successfully for user {user_aad_id} in tenant {tenant_id}")
    
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'text/html; charset=utf-8',
            'Cache-Control': 'no-store, no-cache, must-revalidate, private',
        },
        'body': prs.build_success_page_html(user_info.get('displayName', 'User')),
    }


# =============================================================================
# LAMBDA HANDLER
# =============================================================================

@xray_recorder.capture('reset_password_handler')
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main entry point — routes GET and POST requests."""
    try:
        method = event.get('requestContext', {}).get('http', {}).get('method', 'GET')
        
        if method == 'GET':
            return handle_get(event)
        elif method == 'POST':
            return handle_post(event)
        else:
            return {
                'statusCode': 405,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Method not allowed'}),
            }
    
    except Exception as e:
        logger.exception(f"Unhandled error in reset_password: {e}")
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'},
            'body': prs.build_error_page_html(
                "An unexpected error occurred. Please contact IT support.",
                SUPPORT_EMAIL,
            ),
        }
