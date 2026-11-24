"""
Tenant Portal API Backend

Provides tenant-scoped endpoints for the self-service portal.
All requests are authenticated via Cognito JWT and tenant-isolated
using the tenant_id claim from the token.

Endpoints:
- GET    /me              — Get current tenant metadata
- PUT    /me              — Update tenant metadata
- GET    /me/status       — Get current tenant status
- GET    /me/history      — Get status history (last 30 days)
- GET    /me/rules        — List custom health rules
- POST   /me/rules        — Create a custom health rule
- DELETE /me/rules/{id}   — Delete a custom health rule
- GET    /me/webhooks     — List webhook configurations
- POST   /me/webhooks     — Create a webhook configuration
- DELETE /me/webhooks/{id} — Delete a webhook configuration
- GET    /me/audit        — Get audit log (last 100 entries)
"""

import json
import os
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import boto3
from botocore.exceptions import ClientError
from decimal import Decimal

from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configuration
TENANT_REGISTRY_TABLE = os.environ.get('TENANT_REGISTRY_TABLE')
CUSTOM_RULES_TABLE = os.environ.get('CUSTOM_RULES_TABLE', '')
WEBHOOK_CONFIGS_TABLE = os.environ.get('WEBHOOK_CONFIGS_TABLE', '')
STATUS_HISTORY_TABLE = os.environ.get('STATUS_HISTORY_TABLE', '')
AUDIT_LOG_TABLE = os.environ.get('AUDIT_LOG_TABLE')
COGNITO_USER_POOL_ID = os.environ.get('COGNITO_USER_POOL_ID')
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)

# Validation patterns
TENANT_ID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$')
EMAIL_PATTERN = re.compile(r'^[^@]+@[^@]+\.[^@]+$')


# =============================================================================
# AUTHENTICATION HELPERS
# =============================================================================

def extract_tenant_from_event(event: Dict[str, Any]) -> Optional[str]:
    """
    Extracts the tenant_id from the Cognito JWT claims.
    
    The tenant_id is stored as a custom attribute in Cognito,
    mapped from the user's Entra ID group membership or
    manually assigned during user provisioning.
    """
    claims = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
    
    # Custom attribute in Cognito is prefixed with "custom:"
    tenant_id = claims.get('custom:tenant_id')
    
    if not tenant_id:
        logger.warning(f"No tenant_id in JWT claims for user {claims.get('email', 'unknown')}")
        return None
    
    return tenant_id


def extract_user_email(event: Dict[str, Any]) -> Optional[str]:
    """Extracts the user's email from JWT claims."""
    claims = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
    return claims.get('email')


def verify_tenant_access(tenant_id: str, user_email: str) -> bool:
    """
    Verifies that the user has access to the specified tenant.
    
    For V1, we use a simple model: the user's email must be in the
    tenant's allowed_users list, OR the user is the tenant's contact_email.
    
    In V2, this would check Entra ID group membership.
    """
    try:
        table = dynamodb.Table(TENANT_REGISTRY_TABLE)
        response = table.get_item(Key={'tenant_id': tenant_id})
        tenant = response.get('Item')
        
        if not tenant:
            return False
        
        # Check if user is the tenant's contact
        if tenant.get('contact_email') == user_email:
            return True
        
        # Check allowed_users list
        allowed_users = tenant.get('allowed_users', [])
        if isinstance(allowed_users, str):
            allowed_users = json.loads(allowed_users)
        
        return user_email in allowed_users
    
    except Exception as e:
        logger.error(f"Failed to verify tenant access: {e}")
        return False


def convert_decimals(obj: Any) -> Any:
    """Converts DynamoDB Decimal types to int/float for JSON serialization."""
    if isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals(v) for v in obj]
    elif isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    return obj


# =============================================================================
# ROUTE HANDLERS
# =============================================================================

def handle_get_me(tenant_id: str) -> Dict[str, Any]:
    """GET /me — Get current tenant metadata."""
    try:
        table = dynamodb.Table(TENANT_REGISTRY_TABLE)
        response = table.get_item(Key={'tenant_id': tenant_id})
        tenant = response.get('Item')
        
        if not tenant:
            return {'statusCode': 404, 'body': json.dumps({'error': 'Tenant not found'})}
        
        # Remove sensitive fields
        safe_fields = {
            'tenant_id': tenant.get('tenant_id'),
            'display_name': tenant.get('display_name'),
            'contact_email': tenant.get('contact_email'),
            'status': tenant.get('status'),
            'management_mode': tenant.get('management_mode'),
            'branding': tenant.get('branding'),
            'timezone': tenant.get('timezone'),
            'created_at': tenant.get('created_at'),
            'allowed_users': tenant.get('allowed_users', []),
        }
        
        # Parse branding if it's a string
        if isinstance(safe_fields['branding'], str):
            try:
                safe_fields['branding'] = json.loads(safe_fields['branding'])
            except json.JSONDecodeError:
                safe_fields['branding'] = {}
        
        # Parse allowed_users if it's a string
        if isinstance(safe_fields['allowed_users'], str):
            try:
                safe_fields['allowed_users'] = json.loads(safe_fields['allowed_users'])
            except json.JSONDecodeError:
                safe_fields['allowed_users'] = []
        
        return {'statusCode': 200, 'body': json.dumps(convert_decimals(safe_fields))}
    
    except Exception as e:
        logger.exception(f"Failed to get tenant {tenant_id}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


def handle_put_me(tenant_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """PUT /me — Update tenant metadata."""
    try:
        body = json.loads(event.get('body', '{}') or '{}')
        
        # Only allow specific fields to be updated
        allowed_updates = ['display_name', 'contact_email', 'branding', 'timezone', 'allowed_users']
        update_parts = []
        expr_values = {}
        expr_names = {}
        
        for field in allowed_updates:
            if field in body:
                value = body[field]
                
                # Validate email
                if field == 'contact_email' and not EMAIL_PATTERN.match(value):
                    return {'statusCode': 400, 'body': json.dumps({'error': 'Invalid email format'})}
                
                # Convert complex types to JSON strings for DynamoDB
                if field in ('branding', 'allowed_users'):
                    value = json.dumps(value)
                
                update_parts.append(f"#{field} = :{field}")
                expr_names[f"#{field}"] = field
                expr_values[f":{field}"] = value
        
        if not update_parts:
            return {'statusCode': 400, 'body': json.dumps({'error': 'No valid fields to update'})}
        
        update_parts.append("updated_at = :ts")
        expr_values[':ts'] = datetime.now(timezone.utc).isoformat()
        
        table = dynamodb.Table(TENANT_REGISTRY_TABLE)
        table.update_item(
            Key={'tenant_id': tenant_id},
            UpdateExpression='SET ' + ', '.join(update_parts),
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )
        
        return {'statusCode': 200, 'body': json.dumps({'message': 'Tenant updated successfully'})}
    
    except Exception as e:
        logger.exception(f"Failed to update tenant {tenant_id}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


def handle_get_status(tenant_id: str) -> Dict[str, Any]:
    """GET /me/status — Get current tenant status."""
    try:
        # Get the most recent status snapshot
        history_table = dynamodb.Table(STATUS_HISTORY_TABLE)
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        
        response = history_table.query(
            KeyConditionExpression='tenant_id = :tid AND snapshot_date <= :date',
            ExpressionAttributeValues={
                ':tid': tenant_id,
                ':date': today,
            },
            ScanIndexForward=False,
            Limit=1
        )
        
        items = response.get('Items', [])
        if not items:
            return {'statusCode': 404, 'body': json.dumps({'error': 'No status data available'})}
        
        return {'statusCode': 200, 'body': json.dumps(convert_decimals(items[0]))}
    
    except Exception as e:
        logger.exception(f"Failed to get status for {tenant_id}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


def handle_get_history(tenant_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /me/history — Get status history (last 30 days)."""
    try:
        query_params = event.get('queryStringParameters') or {}
        days = int(query_params.get('days', '30'))
        days = min(max(days, 1), 90)  # Clamp between 1 and 90
        
        history_table = dynamodb.Table(STATUS_HISTORY_TABLE)
        start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
        
        response = history_table.query(
            KeyConditionExpression='tenant_id = :tid AND snapshot_date >= :start',
            ExpressionAttributeValues={
                ':tid': tenant_id,
                ':start': start_date,
            },
            ScanIndexForward=True
        )
        
        items = response.get('Items', [])
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'history': convert_decimals(items),
                'count': len(items),
                'days': days,
            })
        }
    
    except Exception as e:
        logger.exception(f"Failed to get history for {tenant_id}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


def handle_get_rules(tenant_id: str) -> Dict[str, Any]:
    """GET /me/rules — List custom health rules."""
    if not CUSTOM_RULES_TABLE:
        return {'statusCode': 200, 'body': json.dumps({'rules': [], 'count': 0})}
    
    try:
        table = dynamodb.Table(CUSTOM_RULES_TABLE)
        response = table.query(
            KeyConditionExpression='tenant_id = :tid',
            ExpressionAttributeValues={':tid': tenant_id}
        )
        rules = response.get('Items', [])
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'rules': convert_decimals(rules),
                'count': len(rules),
            })
        }
    
    except Exception as e:
        logger.exception(f"Failed to list rules for {tenant_id}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


def handle_post_rules(tenant_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /me/rules — Create a custom health rule."""
    if not CUSTOM_RULES_TABLE:
        return {'statusCode': 400, 'body': json.dumps({'error': 'Custom health rules not enabled'})}
    
    try:
        body = json.loads(event.get('body', '{}') or '{}')
        
        # Validate rule
        rule_type = body.get('type')
        if rule_type not in ('threshold', 'presence', 'trend'):
            return {'statusCode': 400, 'body': json.dumps({'error': 'Invalid rule type'})}
        
        # Check rule limit
        table = dynamodb.Table(CUSTOM_RULES_TABLE)
        response = table.query(
            KeyConditionExpression='tenant_id = :tid',
            ExpressionAttributeValues={':tid': tenant_id},
            Select='COUNT'
        )
        current_count = response.get('Count', 0)
        
        if current_count >= 10:
            return {'statusCode': 409, 'body': json.dumps({'error': 'Maximum 10 rules per tenant'})}
        
        rule_id = str(uuid.uuid4())[:8]
        item = {
            'tenant_id': tenant_id,
            'rule_id': rule_id,
            'type': rule_type,
            'metric': body.get('metric'),
            'impact': body.get('impact', 0),
            'description': body.get('description', ''),
            'enabled': body.get('enabled', True),
            'created_at': datetime.now(timezone.utc).isoformat(),
            'created_by': body.get('created_by', 'portal_user'),
        }
        
        # Add type-specific fields
        if rule_type == 'threshold':
            item['operator'] = body.get('operator')
            item['value'] = body.get('value')
        elif rule_type == 'presence':
            item['expected_value'] = body.get('expected_value')
        elif rule_type == 'trend':
            item['change_threshold'] = body.get('change_threshold')
            item['days'] = body.get('days')
        
        table.put_item(Item=item)
        
        return {
            'statusCode': 201,
            'body': json.dumps({'rule_id': rule_id, 'rule': convert_decimals(item)})
        }
    
    except Exception as e:
        logger.exception(f"Failed to create rule for {tenant_id}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


def handle_delete_rules(tenant_id: str, rule_id: str) -> Dict[str, Any]:
    """DELETE /me/rules/{rule_id} — Delete a custom health rule."""
    if not CUSTOM_RULES_TABLE:
        return {'statusCode': 400, 'body': json.dumps({'error': 'Custom health rules not enabled'})}
    
    try:
        table = dynamodb.Table(CUSTOM_RULES_TABLE)
        
        # Verify the rule belongs to this tenant
        response = table.get_item(Key={'tenant_id': tenant_id, 'rule_id': rule_id})
        if 'Item' not in response:
            return {'statusCode': 404, 'body': json.dumps({'error': 'Rule not found'})}
        
        table.delete_item(Key={'tenant_id': tenant_id, 'rule_id': rule_id})
        
        return {'statusCode': 200, 'body': json.dumps({'message': f'Rule {rule_id} deleted'})}
    
    except Exception as e:
        logger.exception(f"Failed to delete rule {rule_id} for {tenant_id}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


def handle_get_webhooks(tenant_id: str) -> Dict[str, Any]:
    """GET /me/webhooks — List webhook configurations."""
    if not WEBHOOK_CONFIGS_TABLE:
        return {'statusCode': 200, 'body': json.dumps({'webhooks': [], 'count': 0})}
    
    try:
        table = dynamodb.Table(WEBHOOK_CONFIGS_TABLE)
        response = table.query(
            KeyConditionExpression='tenant_id = :tid',
            ExpressionAttributeValues={':tid': tenant_id}
        )
        webhooks = response.get('Items', [])
        
        # Mask webhook IDs (URLs are in Secrets Manager, not here)
        safe_webhooks = []
        for w in webhooks:
            safe_webhooks.append({
                'webhook_id': w.get('webhook_id'),
                'platform': w.get('platform'),
                'enabled': w.get('enabled'),
                'created_at': w.get('created_at'),
            })
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'webhooks': safe_webhooks,
                'count': len(safe_webhooks),
            })
        }
    
    except Exception as e:
        logger.exception(f"Failed to list webhooks for {tenant_id}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


def handle_post_webhooks(tenant_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """POST /me/webhooks — Create a webhook configuration."""
    if not WEBHOOK_CONFIGS_TABLE:
        return {'statusCode': 400, 'body': json.dumps({'error': 'Webhook notifications not enabled'})}
    
    try:
        body = json.loads(event.get('body', '{}') or '{}')
        
        webhook_id = body.get('webhook_id')
        platform = body.get('platform')
        
        if not webhook_id or not platform:
            return {'statusCode': 400, 'body': json.dumps({'error': 'webhook_id and platform required'})}
        
        if platform not in ('slack', 'teams', 'pagerduty', 'generic'):
            return {'statusCode': 400, 'body': json.dumps({'error': 'Invalid platform'})}
        
        # Note: The actual webhook URL must be added to the webhook_urls secret
        # by an admin. The portal only creates the config entry.
        table = dynamodb.Table(WEBHOOK_CONFIGS_TABLE)
        item = {
            'tenant_id': tenant_id,
            'webhook_id': webhook_id,
            'platform': platform,
            'enabled': body.get('enabled', True),
            'created_at': datetime.now(timezone.utc).isoformat(),
            'created_by': body.get('created_by', 'portal_user'),
        }
        
        table.put_item(Item=item)
        
        return {
            'statusCode': 201,
            'body': json.dumps({
                'webhook_id': webhook_id,
                'message': f'Webhook created. An admin must add the URL to the webhook_urls secret.',
            })
        }
    
    except Exception as e:
        logger.exception(f"Failed to create webhook for {tenant_id}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


def handle_delete_webhooks(tenant_id: str, webhook_id: str) -> Dict[str, Any]:
    """DELETE /me/webhooks/{webhook_id} — Delete a webhook configuration."""
    if not WEBHOOK_CONFIGS_TABLE:
        return {'statusCode': 400, 'body': json.dumps({'error': 'Webhook notifications not enabled'})}
    
    try:
        table = dynamodb.Table(WEBHOOK_CONFIGS_TABLE)
        
        response = table.get_item(Key={'tenant_id': tenant_id, 'webhook_id': webhook_id})
        if 'Item' not in response:
            return {'statusCode': 404, 'body': json.dumps({'error': 'Webhook not found'})}
        
        table.delete_item(Key={'tenant_id': tenant_id, 'webhook_id': webhook_id})
        
        return {'statusCode': 200, 'body': json.dumps({'message': f'Webhook {webhook_id} deleted'})}
    
    except Exception as e:
        logger.exception(f"Failed to delete webhook {webhook_id} for {tenant_id}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


def handle_get_audit(tenant_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /me/audit — Get audit log (last 100 entries)."""
    try:
        query_params = event.get('queryStringParameters') or {}
        limit = int(query_params.get('limit', '100'))
        limit = min(max(limit, 1), 500)  # Clamp between 1 and 500
        
        table = dynamodb.Table(AUDIT_LOG_TABLE)
        response = table.scan(
            FilterExpression='#t = :tid',
            ExpressionAttributeNames={'#t': 'tenant_id'},
            ExpressionAttributeValues={':tid': tenant_id},
            Limit=limit
        )
        
        items = response.get('Items', [])
        
        # Sort by timestamp descending
        items.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'audit_log': convert_decimals(items),
                'count': len(items),
            })
        }
    
    except Exception as e:
        logger.exception(f"Failed to get audit log for {tenant_id}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


# =============================================================================
# LAMBDA HANDLER
# =============================================================================

@xray_recorder.capture('tenant_portal_handler')
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main entry point for the tenant portal API."""
    try:
        # Extract tenant_id from JWT
        tenant_id = extract_tenant_from_event(event)
        if not tenant_id:
            return {'statusCode': 403, 'body': json.dumps({'error': 'No tenant context in token'})}
        
        user_email = extract_user_email(event)
        
        # Verify tenant access
        if not verify_tenant_access(tenant_id, user_email):
            logger.warning(f"User {user_email} attempted to access tenant {tenant_id}")
            return {'statusCode': 403, 'body': json.dumps({'error': 'Access denied to this tenant'})}
        
        # Route the request
        route_key = event.get('routeKey') or ''
        method, path = route_key.split(' ', 1) if ' ' in route_key else ('GET', '')
        path_parts = [p for p in path.strip('/').split('/') if p]
        
        # =========================================================================
        # /me — Tenant metadata
        # =========================================================================
        if method == 'GET' and path_parts == ['me']:
            return handle_get_me(tenant_id)
        
        elif method == 'PUT' and path_parts == ['me']:
            return handle_put_me(tenant_id, event)
        
        # =========================================================================
        # /me/status — Current status
        # =========================================================================
        elif method == 'GET' and path_parts == ['me', 'status']:
            return handle_get_status(tenant_id)
        
        # =========================================================================
        # /me/history — Status history
        # =========================================================================
        elif method == 'GET' and path_parts == ['me', 'history']:
            return handle_get_history(tenant_id, event)
        
        # =========================================================================
        # /me/rules — Custom health rules
        # =========================================================================
        elif method == 'GET' and path_parts == ['me', 'rules']:
            return handle_get_rules(tenant_id)
        
        elif method == 'POST' and path_parts == ['me', 'rules']:
            return handle_post_rules(tenant_id, event)
        
        elif method == 'DELETE' and len(path_parts) == 3 and path_parts[0:2] == ['me', 'rules']:
            rule_id = path_parts[2]
            return handle_delete_rules(tenant_id, rule_id)
        
        # =========================================================================
        # /me/webhooks — Webhook configurations
        # =========================================================================
        elif method == 'GET' and path_parts == ['me', 'webhooks']:
            return handle_get_webhooks(tenant_id)
        
        elif method == 'POST' and path_parts == ['me', 'webhooks']:
            return handle_post_webhooks(tenant_id, event)
        
        elif method == 'DELETE' and len(path_parts) == 3 and path_parts[0:2] == ['me', 'webhooks']:
            webhook_id = path_parts[2]
            return handle_delete_webhooks(tenant_id, webhook_id)
        
        # =========================================================================
        # /me/audit — Audit log
        # =========================================================================
        elif method == 'GET' and path_parts == ['me', 'audit']:
            return handle_get_audit(tenant_id, event)
        
        # =========================================================================
        # Unknown route
        # =========================================================================
        else:
            return {'statusCode': 404, 'body': json.dumps({'error': f'Not found: {method} {path}'})}
    
    except Exception as e:
        logger.exception(f"Unhandled error in portal handler")
        return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}