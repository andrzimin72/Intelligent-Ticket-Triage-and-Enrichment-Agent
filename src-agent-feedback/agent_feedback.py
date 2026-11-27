"""
Agent Feedback Handler (Phase 2: Tenant-Scoped)

Receives feedback from the Teams bot (via invoke activities) and stores it
in DynamoDB for tech lead review. Every feedback record is now scoped to a
tenant to prevent cross-tenant data leakage.

Feedback types:
- thumbs_up: User found the response helpful (positive example)
- thumbs_down: User found the response unhelpful (needs correction)
- detailed_correction: IT staff provided specific correction details

The feedback is stored with status='pending_review' until a tech lead
approves it in the AWS Console. Approved feedback is synced to S3 by
the agent_feedback_sync Lambda.
"""

import json
import os
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError

from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

import tenant_resolver  # NEW: tenant-aware

logger = logging.getLogger()
logger.setLevel(logging.INFO)

FEEDBACK_TABLE = os.environ.get('FEEDBACK_TABLE')
TENANT_REGISTRY_TABLE = os.environ.get('TENANT_REGISTRY_TABLE')  # NEW
FEEDBACK_RETENTION = int(os.environ.get('FEEDBACK_RETENTION', '365'))
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)

# Valid error categories for detailed feedback
VALID_CATEGORIES = {
    'wrong_tool': 'Agent chose the wrong tool for the request',
    'wrong_parameters': 'Agent passed incorrect parameters to the tool',
    'misunderstood_intent': 'Agent misunderstood what the user wanted',
    'poor_quality': 'Response was too verbose, terse, or used jargon',
    'skipped_confirmation': 'Agent performed write operation without confirmation',
    'hallucination': 'Agent invented information that doesn\'t exist',
    'other': 'Other issue not covered above',
}


@xray_recorder.capture('store_feedback')
def store_feedback(feedback_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stores feedback in DynamoDB, scoped to a tenant.
    
    Required fields:
    - feedback_type: 'thumbs_up' or 'thumbs_down'
    - user_aad_id: AAD ID of the user providing feedback
    - session_id: Agent session ID where the feedback occurred
    - agent_response: The agent's response text being rated
    - tenant_id: The tenant this feedback belongs to (NEW)
    """
    feedback_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    ttl_timestamp = int((now + timedelta(days=FEEDBACK_RETENTION)).timestamp())
    
    # Extract tenant_id (NEW — required)
    tenant_id = feedback_data.get('tenant_id')
    if not tenant_id:
        logger.error("Feedback submission missing tenant_id — rejecting")
        return {
            'success': False,
            'error': 'Tenant context is required for feedback submission.'
        }
    
    # Validate tenant exists and is enabled
    tenant = tenant_resolver.lookup_tenant_by_id(tenant_id)
    if not tenant:
        logger.error(f"Feedback for unknown/disabled tenant: {tenant_id}")
        return {
            'success': False,
            'error': f'Tenant {tenant_id} is not registered or is disabled.'
        }
    
    item = {
        'feedback_id': feedback_id,
        'tenant_id': tenant_id,              # NEW
        'feedback_type': feedback_data.get('feedback_type'),
        'user_aad_id': feedback_data.get('user_aad_id'),
        'user_name': feedback_data.get('user_name', 'Unknown'),
        'session_id': feedback_data.get('session_id'),
        'agent_response': feedback_data.get('agent_response', '')[:2000],
        'user_message': feedback_data.get('user_message', '')[:1000],
        'tools_called': json.dumps(feedback_data.get('tools_called', [])),
        'status': 'pending_review',
        'created_at': now.isoformat(),
        'ttl': ttl_timestamp,
    }
    
    # Add optional detailed feedback fields
    if feedback_data.get('error_category'):
        category = feedback_data['error_category']
        if category not in VALID_CATEGORIES:
            return {
                'success': False,
                'error': f'Invalid error_category: {category}. Must be one of: {list(VALID_CATEGORIES.keys())}'
            }
        item['error_category'] = category
    
    if feedback_data.get('correction_text'):
        item['correction_text'] = feedback_data['correction_text'][:1000]
    
    if feedback_data.get('expected_tool'):
        item['expected_tool'] = feedback_data['expected_tool']
    
    if feedback_data.get('expected_parameters'):
        item['expected_parameters'] = json.dumps(feedback_data['expected_parameters'])
    
    try:
        dynamodb.Table(FEEDBACK_TABLE).put_item(Item=item)
        logger.info(f"Stored feedback {feedback_id} for tenant {tenant_id} (type: {item['feedback_type']})")
        return {
            'success': True,
            'feedback_id': feedback_id,
        }
    except ClientError as e:
        logger.error(f"Failed to store feedback: {e}")
        return {
            'success': False,
            'error': 'Failed to store feedback. Please try again.',
        }


@xray_recorder.capture('feedback_handler')
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main entry point for the feedback handler."""
    try:
        body = event.get('body', '{}')
        if isinstance(body, str):
            payload = json.loads(body)
        else:
            payload = body
        
        feedback_data = payload.get('feedback_data', {})
        
        if not feedback_data:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing feedback_data'}),
            }
        
        # Validate required fields
        required = ['feedback_type', 'user_aad_id', 'session_id', 'agent_response', 'tenant_id']  # tenant_id NEW
        missing = [f for f in required if not feedback_data.get(f)]
        if missing:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': f'Missing required fields: {missing}'}),
            }
        
        result = store_feedback(feedback_data)
        
        if result['success']:
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Feedback received. Thank you!',
                    'feedback_id': result['feedback_id'],
                }),
            }
        else:
            return {
                'statusCode': 500,
                'body': json.dumps({'error': result['error']}),
            }
    
    except Exception as e:
        logger.exception(f"Error in feedback handler: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal error. Please try again.'}),
        }
