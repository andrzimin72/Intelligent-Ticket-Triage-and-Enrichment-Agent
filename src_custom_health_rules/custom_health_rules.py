"""
Custom Health Rules Manager (Sub-Phase 3)

API for managing tenant-defined custom health check rules.

Endpoints:
- POST   /tenants/{tenant_id}/rules          — Create a rule
- GET    /tenants/{tenant_id}/rules          — List rules for a tenant
- DELETE /tenants/{tenant_id}/rules/{rule_id} — Delete a rule

Rule types:
- threshold: Alert if metric is above/below a value
- presence: Alert if a condition exists
- trend: Alert if metric changed significantly over time

Safety:
- Rules are validated before being saved
- Max impact capped at MAX_SCORE_IMPACT points
- Max rules per tenant enforced
"""

import json
import os
import logging
import uuid
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import boto3
from botocore.exceptions import ClientError

from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CUSTOM_RULES_TABLE = os.environ.get('CUSTOM_RULES_TABLE')
TENANT_REGISTRY_TABLE = os.environ.get('TENANT_REGISTRY_TABLE')
MAX_RULES_PER_TENANT = int(os.environ.get('MAX_RULES_PER_TENANT', '10'))
MAX_SCORE_IMPACT = int(os.environ.get('MAX_SCORE_IMPACT', '30'))
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)

# Valid rule types and their required fields
VALID_RULE_TYPES = {
    'threshold': {
        'required': ['metric', 'operator', 'value'],
        'metrics': ['health_score', 'audit_records', 'conversations', 'kb_documents', 'action_group_count'],
        'operators': ['<', '<=', '>', '>=', '==', '!='],
    },
    'presence': {
        'required': ['metric', 'expected_value'],
        'metrics': ['agent_status', 'secrets_populated', 'overall_health'],
    },
    'trend': {
        'required': ['metric', 'change_threshold', 'days'],
        'metrics': ['health_score', 'audit_records', 'conversations', 'kb_documents'],
    },
}

TENANT_ID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$')


def validate_rule(rule: Dict[str, Any]) -> Optional[str]:
    """Validates a custom health rule. Returns error message or None."""
    rule_type = rule.get('type')
    if rule_type not in VALID_RULE_TYPES:
        return f"Invalid rule type: {rule_type}. Must be one of: {list(VALID_RULE_TYPES.keys())}"
    
    spec = VALID_RULE_TYPES[rule_type]
    
    # Check required fields
    missing = [f for f in spec['required'] if f not in rule]
    if missing:
        return f"Missing required fields for {rule_type}: {missing}"
    
    # Check metric is valid
    metric = rule.get('metric')
    if metric not in spec['metrics']:
        return f"Invalid metric for {rule_type}: {metric}. Must be one of: {spec['metrics']}"
    
    # Type-specific validation
    if rule_type == 'threshold':
        operator = rule.get('operator')
        if operator not in spec['operators']:
            return f"Invalid operator: {operator}. Must be one of: {spec['operators']}"
        
        value = rule.get('value')
        if not isinstance(value, (int, float)):
            return "Threshold value must be a number"
    
    elif rule_type == 'presence':
        expected = rule.get('expected_value')
        if expected is None:
            return "expected_value is required for presence rules"
    
    elif rule_type == 'trend':
        change_threshold = rule.get('change_threshold')
        if not isinstance(change_threshold, (int, float)) or change_threshold <= 0:
            return "change_threshold must be a positive number"
        
        days = rule.get('days')
        if not isinstance(days, int) or days < 1 or days > 90:
            return "days must be an integer between 1 and 90"
    
    # Validate impact
    impact = rule.get('impact', 0)
    if not isinstance(impact, int) or abs(impact) > MAX_SCORE_IMPACT:
        return f"impact must be an integer between -{MAX_SCORE_IMPACT} and {MAX_SCORE_IMPACT}"
    
    return None


def verify_tenant_exists(tenant_id: str) -> bool:
    """Verifies that a tenant exists in the registry."""
    try:
        table = dynamodb.Table(TENANT_REGISTRY_TABLE)
        response = table.get_item(Key={'tenant_id': tenant_id})
        return 'Item' in response
    except Exception as e:
        logger.error(f"Failed to verify tenant {tenant_id}: {e}")
        return False


def count_tenant_rules(tenant_id: str) -> int:
    """Counts existing rules for a tenant."""
    try:
        table = dynamodb.Table(CUSTOM_RULES_TABLE)
        response = table.query(
            KeyConditionExpression='tenant_id = :tid',
            ExpressionAttributeValues={':tid': tenant_id},
            Select='COUNT'
        )
        return response.get('Count', 0)
    except Exception as e:
        logger.error(f"Failed to count rules for {tenant_id}: {e}")
        return 0


@xray_recorder.capture('custom_health_rules_handler')
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main entry point for custom health rules API."""
    try:
        route_key = event.get('routeKey') or ''
        method, path = route_key.split(' ', 1) if ' ' in route_key else ('GET', '')
        path_parts = [p for p in path.strip('/').split('/') if p]
        
        # =====================================================================
        # POST /tenants/{tenant_id}/rules — Create a rule
        # =====================================================================
        if method == 'POST' and len(path_parts) == 3 and path_parts[0] == 'tenants' and path_parts[2] == 'rules':
            tenant_id = path_parts[1]
            
            if not TENANT_ID_PATTERN.match(tenant_id):
                return {'statusCode': 400, 'body': json.dumps({'error': 'Invalid tenant_id format'})}
            
            if not verify_tenant_exists(tenant_id):
                return {'statusCode': 404, 'body': json.dumps({'error': f'Tenant {tenant_id} not found'})}
            
            # Check rule limit
            current_count = count_tenant_rules(tenant_id)
            if current_count >= MAX_RULES_PER_TENANT:
                return {
                    'statusCode': 409,
                    'body': json.dumps({'error': f'Tenant already has {current_count} rules (max: {MAX_RULES_PER_TENANT})'})
                }
            
            body = json.loads(event.get('body', '{}') or '{}')
            
            # Validate the rule
            error = validate_rule(body)
            if error:
                return {'statusCode': 400, 'body': json.dumps({'error': error})}
            
            # Create the rule
            rule_id = str(uuid.uuid4())[:8]
            item = {
                'tenant_id': tenant_id,
                'rule_id': rule_id,
                'type': body['type'],
                'metric': body['metric'],
                'impact': body.get('impact', 0),
                'description': body.get('description', ''),
                'enabled': body.get('enabled', True),
                'created_at': datetime.now(timezone.utc).isoformat(),
            }
            
            # Add type-specific fields
            if body['type'] == 'threshold':
                item['operator'] = body['operator']
                item['value'] = body['value']
            elif body['type'] == 'presence':
                item['expected_value'] = body['expected_value']
            elif body['type'] == 'trend':
                item['change_threshold'] = body['change_threshold']
                item['days'] = body['days']
            
            try:
                table = dynamodb.Table(CUSTOM_RULES_TABLE)
                table.put_item(Item=item)
                
                return {
                    'statusCode': 201,
                    'body': json.dumps({
                        'rule_id': rule_id,
                        'tenant_id': tenant_id,
                        'rule': item,
                    })
                }
            except Exception as e:
                logger.exception(f"Failed to create rule for tenant {tenant_id}")
                return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}
        
        # =====================================================================
        # GET /tenants/{tenant_id}/rules — List rules
        # =====================================================================
        elif method == 'GET' and len(path_parts) == 3 and path_parts[0] == 'tenants' and path_parts[2] == 'rules':
            tenant_id = path_parts[1]
            
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
                        'tenant_id': tenant_id,
                        'rules': rules,
                        'count': len(rules),
                    })
                }
            except Exception as e:
                logger.exception(f"Failed to list rules for tenant {tenant_id}")
                return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}
        
        # =====================================================================
        # DELETE /tenants/{tenant_id}/rules/{rule_id} — Delete a rule
        # =====================================================================
        elif method == 'DELETE' and len(path_parts) == 4 and path_parts[0] == 'tenants' and path_parts[2] == 'rules':
            tenant_id = path_parts[1]
            rule_id = path_parts[3]
            
            try:
                table = dynamodb.Table(CUSTOM_RULES_TABLE)
                table.delete_item(Key={
                    'tenant_id': tenant_id,
                    'rule_id': rule_id,
                })
                
                return {
                    'statusCode': 200,
                    'body': json.dumps({
                        'message': f'Rule {rule_id} deleted for tenant {tenant_id}',
                    })
                }
            except Exception as e:
                logger.exception(f"Failed to delete rule {rule_id} for tenant {tenant_id}")
                return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}
        
        # =====================================================================
        # Unknown route
        # =====================================================================
        else:
            return {'statusCode': 404, 'body': json.dumps({'error': f'Not found: {method} {path}'})}
    
    except Exception as e:
        logger.exception(f"Unhandled error in custom health rules handler")
        return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}