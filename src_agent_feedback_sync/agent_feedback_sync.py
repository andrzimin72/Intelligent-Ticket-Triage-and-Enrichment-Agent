"""
Agent Feedback Sync (Phase 2: Tenant-Scoped)

Converts approved agent feedback into few-shot examples and updates
tenant-scoped S3 files: tenants/{tenant_id}/agent-examples.json

Flow:
1. Discover all active tenants from tenant registry
2. For each tenant:
   a. Query approved feedback for that tenant
   b. Convert to few-shot examples
   c. Read existing examples from tenant-scoped S3
   d. Merge (dedup + trim)
   e. Write updated examples back to tenant-scoped S3
   f. Mark processed records as 'injected'

Schedule: Daily at 4 AM UTC (via EventBridge)
"""

import json
import os
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List
import boto3
from botocore.exceptions import ClientError

from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

import tenant_resolver  # NEW: tenant-aware

logger = logging.getLogger()
logger.setLevel(logging.INFO)

FEEDBACK_TABLE = os.environ.get('FEEDBACK_TABLE')
TENANT_REGISTRY_TABLE = os.environ.get('TENANT_REGISTRY_TABLE')  # NEW
AGENT_EXAMPLES_BUCKET = os.environ.get('AGENT_EXAMPLES_BUCKET')
AGENT_EXAMPLES_KEY = os.environ.get('AGENT_EXAMPLES_KEY', 'agent-examples.json')
MAX_AGENT_EXAMPLES = int(os.environ.get('MAX_AGENT_EXAMPLES', '5'))
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
s3_client = boto3.client('s3', region_name=AWS_REGION)


# =============================================================================
# TENANT DISCOVERY
# =============================================================================

@xray_recorder.capture('discover_active_tenants')
def discover_active_tenants() -> List[str]:
    """
    Returns a list of active tenant IDs from the tenant registry.
    
    This ensures we only process feedback for tenants that still exist
    and are enabled.
    """
    if not TENANT_REGISTRY_TABLE:
        logger.warning("TENANT_REGISTRY_TABLE not configured, falling back to ['default']")
        return ['default']
    
    try:
        table = dynamodb.Table(TENANT_REGISTRY_TABLE)
        response = table.query(
            IndexName='enabled-index',
            KeyConditionExpression='#e = :enabled',
            ExpressionAttributeNames={'#e': 'enabled'},
            ExpressionAttributeValues={':enabled': 1}
        )
        
        tenants = [item['tenant_id'] for item in response.get('Items', [])]
        
        # Handle pagination
        while 'LastEvaluatedKey' in response:
            response = table.query(
                IndexName='enabled-index',
                KeyConditionExpression='#e = :enabled',
                ExpressionAttributeNames={'#e': 'enabled'},
                ExpressionAttributeValues={':enabled': 1},
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            tenants.extend([item['tenant_id'] for item in response.get('Items', [])])
        
        logger.info(f"Discovered {len(tenants)} active tenants: {tenants}")
        return tenants
    
    except ClientError as e:
        logger.error(f"Failed to discover tenants: {e}")
        return ['default']  # Fallback to default tenant


# =============================================================================
# PER-TENANT FEEDBACK QUERY
# =============================================================================

@xray_recorder.capture('get_approved_feedback_for_tenant')
def get_approved_feedback_for_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    """Queries the feedback table for approved records belonging to a specific tenant."""
    table = dynamodb.Table(FEEDBACK_TABLE)
    approved = []
    
    try:
        # Use the tenant-status-index GSI for efficient per-tenant queries
        response = table.query(
            IndexName='tenant-status-index',
            KeyConditionExpression='#t = :tenant AND #s = :status',
            ExpressionAttributeNames={'#t': 'tenant_id', '#s': 'status'},
            ExpressionAttributeValues={
                ':tenant': tenant_id,
                ':status': 'approved'
            }
        )
        approved.extend(response.get('Items', []))
        
        while 'LastEvaluatedKey' in response:
            response = table.query(
                IndexName='tenant-status-index',
                KeyConditionExpression='#t = :tenant AND #s = :status',
                ExpressionAttributeNames={'#t': 'tenant_id', '#s': 'status'},
                ExpressionAttributeValues={
                    ':tenant': tenant_id,
                    ':status': 'approved'
                },
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            approved.extend(response.get('Items', []))
        
        logger.info(f"Found {len(approved)} approved feedback records for tenant {tenant_id}")
        return approved
    
    except ClientError as e:
        # Fallback: if the GSI doesn't exist yet (during migration), scan with filter
        if 'tenant-status-index' in str(e):
            logger.warning(f"tenant-status-index not found, falling back to scan for tenant {tenant_id}")
            return _fallback_scan_approved_for_tenant(tenant_id)
        logger.error(f"Failed to query approved feedback for tenant {tenant_id}: {e}")
        raise


def _fallback_scan_approved_for_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    """Fallback scan for environments where the GSI hasn't been created yet."""
    table = dynamodb.Table(FEEDBACK_TABLE)
    approved = []
    
    response = table.scan(
        FilterExpression='#s = :status AND #t = :tenant',
        ExpressionAttributeNames={'#s': 'status', '#t': 'tenant_id'},
        ExpressionAttributeValues={
            ':status': 'approved',
            ':tenant': tenant_id
        }
    )
    approved.extend(response.get('Items', []))
    
    while 'LastEvaluatedKey' in response:
        response = table.scan(
            FilterExpression='#s = :status AND #t = :tenant',
            ExpressionAttributeNames={'#s': 'status', '#t': 'tenant_id'},
            ExpressionAttributeValues={
                ':status': 'approved',
                ':tenant': tenant_id
            },
            ExclusiveStartKey=response['LastEvaluatedKey']
        )
        approved.extend(response.get('Items', []))
    
    return approved


# =============================================================================
# EXAMPLE CONVERSION (unchanged from before, just included for completeness)
# =============================================================================

@xray_recorder.capture('convert_to_example')
def convert_to_example(feedback: Dict[str, Any]) -> Dict[str, Any]:
    """Converts a feedback record into a few-shot example."""
    feedback_type = feedback.get('feedback_type')
    
    if feedback_type == 'thumbs_up':
        return {
            'id': feedback.get('feedback_id'),
            'user_input': feedback.get('user_message', ''),
            'wrong_behavior': 'N/A (this was a positive example)',
            'correct_behavior': feedback.get('agent_response', ''),
            'rationale': 'This response was marked as helpful by the user.',
            'error_category': 'positive_example',
            'added_at': datetime.now(timezone.utc).isoformat(),
        }
    
    correction_text = feedback.get('correction_text', '')
    expected_tool = feedback.get('expected_tool', '')
    expected_params = feedback.get('expected_parameters', '')
    error_category = feedback.get('error_category', 'other')
    
    if expected_tool:
        correct_behavior = f"Agent should have called {expected_tool}"
        if expected_params:
            try:
                params = json.loads(expected_params)
                correct_behavior += f" with parameters: {json.dumps(params)}"
            except json.JSONDecodeError:
                correct_behavior += f" with parameters: {expected_params}"
    elif correction_text:
        correct_behavior = correction_text
    else:
        correct_behavior = "Agent should have handled this differently (see rationale)"
    
    tools_called = json.loads(feedback.get('tools_called', '[]'))
    if tools_called:
        tool_names = [t.get('tool', 'unknown') for t in tools_called]
        wrong_behavior = f"Agent called: {', '.join(tool_names)}"
    else:
        wrong_behavior = feedback.get('agent_response', '')[:200]
    
    rationale_parts = []
    if correction_text:
        rationale_parts.append(correction_text)
    rationale_parts.append(f"Error category: {error_category}")
    rationale = ". ".join(rationale_parts)
    
    return {
        'id': feedback.get('feedback_id'),
        'user_input': feedback.get('user_message', ''),
        'wrong_behavior': wrong_behavior,
        'correct_behavior': correct_behavior,
        'rationale': rationale,
        'error_category': error_category,
        'added_at': datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# TENANT-SCOPED S3 OPERATIONS
# =============================================================================

def _tenant_s3_key(tenant_id: str) -> str:
    """Returns the tenant-scoped S3 key for agent examples."""
    return f"tenants/{tenant_id}/{AGENT_EXAMPLES_KEY}"


@xray_recorder.capture('read_existing_examples')
def read_existing_examples(tenant_id: str) -> List[Dict[str, Any]]:
    """Reads the existing tenant-scoped agent-examples.json from S3."""
    key = _tenant_s3_key(tenant_id)
    
    try:
        response = s3_client.get_object(
            Bucket=AGENT_EXAMPLES_BUCKET,
            Key=key
        )
        examples = json.loads(response['Body'].read().decode('utf-8'))
        logger.info(f"Read {len(examples)} existing agent examples for tenant {tenant_id}")
        return examples
    except s3_client.exceptions.NoSuchKey:
        logger.info(f"No existing agent examples for tenant {tenant_id}, starting with empty list")
        return []
    except Exception as e:
        logger.error(f"Failed to read existing agent examples for tenant {tenant_id}: {e}")
        raise


@xray_recorder.capture('write_examples_to_s3')
def write_examples_to_s3(tenant_id: str, examples: List[Dict[str, Any]]) -> None:
    """Writes the updated examples list to tenant-scoped S3."""
    key = _tenant_s3_key(tenant_id)
    
    try:
        s3_client.put_object(
            Bucket=AGENT_EXAMPLES_BUCKET,
            Key=key,
            Body=json.dumps(examples, indent=2),
            ContentType='application/json',
            Metadata={
                'tenant-id': tenant_id,
                'example-count': str(len(examples)),
                'updated-at': datetime.now(timezone.utc).isoformat(),
                'updated-by': 'agent-feedback-sync-lambda'
            }
        )
        logger.info(f"Wrote {len(examples)} agent examples for tenant {tenant_id} to {key}")
    except Exception as e:
        logger.error(f"Failed to write agent examples for tenant {tenant_id}: {e}")
        raise


# =============================================================================
# MERGE LOGIC (unchanged)
# =============================================================================

@xray_recorder.capture('merge_examples')
def merge_examples(existing: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merges new examples with existing ones, dedup by feedback_id, trim to MAX."""
    merged = {ex['id']: ex for ex in existing}
    
    added_count = 0
    for ex in new:
        if ex['id'] not in merged:
            merged[ex['id']] = ex
            added_count += 1
        else:
            logger.info(f"Skipping duplicate example for feedback {ex['id']}")
    
    logger.info(f"Added {added_count} new examples, total before trim: {len(merged)}")
    
    sorted_examples = sorted(
        merged.values(),
        key=lambda x: x.get('added_at', ''),
        reverse=True
    )
    
    trimmed = sorted_examples[:MAX_AGENT_EXAMPLES]
    
    if len(sorted_examples) > MAX_AGENT_EXAMPLES:
        logger.info(
            f"Trimmed {len(sorted_examples) - MAX_AGENT_EXAMPLES} older examples "
            f"to respect MAX_AGENT_EXAMPLES={MAX_AGENT_EXAMPLES}"
        )
    
    return trimmed


# =============================================================================
# MARK AS INJECTED (unchanged)
# =============================================================================

@xray_recorder.capture('mark_as_injected')
def mark_as_injected(feedback_id: str) -> bool:
    """Updates a feedback record's status from 'approved' to 'injected'."""
    table = dynamodb.Table(FEEDBACK_TABLE)
    
    try:
        table.update_item(
            Key={'feedback_id': feedback_id},
            UpdateExpression='SET #s = :status, injected_at = :timestamp',
            ConditionExpression='#s = :approved',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':status': 'injected',
                ':approved': 'approved',
                ':timestamp': datetime.now(timezone.utc).isoformat()
            }
        )
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            logger.warning(f"Feedback {feedback_id} no longer in 'approved' status, skipping")
            return False
        logger.error(f"Failed to mark feedback {feedback_id} as injected: {e}")
        return False


# =============================================================================
# PER-TENANT PROCESSING
# =============================================================================

@xray_recorder.capture('process_tenant')
def process_tenant(tenant_id: str) -> Dict[str, int]:
    """
    Processes all approved feedback for a single tenant.
    
    Returns stats: {approved, converted, injected, total_examples}
    """
    logger.info(f"Processing tenant {tenant_id}")
    
    # Step 1: Get approved feedback for this tenant
    approved = get_approved_feedback_for_tenant(tenant_id)
    
    if not approved:
        logger.info(f"No approved feedback for tenant {tenant_id}")
        return {'approved': 0, 'converted': 0, 'injected': 0, 'total_examples': 0}
    
    # Step 2: Convert to few-shot format
    new_examples = []
    for feedback in approved:
        try:
            example = convert_to_example(feedback)
            new_examples.append(example)
        except Exception as e:
            logger.error(f"Failed to convert feedback {feedback.get('feedback_id')}: {e}")
    
    if not new_examples:
        logger.warning(f"No examples converted for tenant {tenant_id}")
        return {'approved': len(approved), 'converted': 0, 'injected': 0, 'total_examples': 0}
    
    # Step 3: Read existing examples for this tenant
    existing = read_existing_examples(tenant_id)
    
    # Step 4: Merge
    merged = merge_examples(existing, new_examples)
    
    # Step 5: Write to tenant-scoped S3
    write_examples_to_s3(tenant_id, merged)
    
    # Step 6: Mark records as injected
    injected_count = 0
    for feedback in approved:
        feedback_id = feedback.get('feedback_id')
        if any(ex['id'] == feedback_id for ex in merged):
            if mark_as_injected(feedback_id):
                injected_count += 1
    
    logger.info(
        f"Tenant {tenant_id} complete: "
        f"{len(approved)} approved, {len(new_examples)} converted, "
        f"{injected_count} injected, {len(merged)} total examples"
    )
    
    return {
        'approved': len(approved),
        'converted': len(new_examples),
        'injected': injected_count,
        'total_examples': len(merged),
    }


# =============================================================================
# LAMBDA HANDLER
# =============================================================================

@xray_recorder.capture('agent_feedback_sync_handler')
def lambda_handler(event, context):
    """
    Main entry point for the agent feedback sync Lambda.
    
    Processes all active tenants, one at a time.
    """
    try:
        logger.info("Starting tenant-scoped agent feedback sync")
        
        # Discover all active tenants
        tenants = discover_active_tenants()
        
        if not tenants:
            logger.warning("No active tenants found")
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'No active tenants'})
            }
        
        # Process each tenant
        total_stats = {
            'tenants_processed': 0,
            'total_approved': 0,
            'total_converted': 0,
            'total_injected': 0,
        }
        
        for tenant_id in tenants:
            try:
                stats = process_tenant(tenant_id)
                total_stats['tenants_processed'] += 1
                total_stats['total_approved'] += stats['approved']
                total_stats['total_converted'] += stats['converted']
                total_stats['total_injected'] += stats['injected']
            except Exception as e:
                logger.error(f"Failed to process tenant {tenant_id}: {e}")
                # Continue with other tenants — don't let one failure block the rest
        
        xray_recorder.put_annotation('tenants_processed', total_stats['tenants_processed'])
        xray_recorder.put_annotation('total_injected', total_stats['total_injected'])
        
        logger.info(f"Agent feedback sync complete: {total_stats}")
        
        return {
            'statusCode': 200,
            'body': json.dumps(total_stats)
        }
    
    except Exception as e:
        xray_recorder.put_annotation('error', True)
        xray_recorder.put_metadata('error_message', str(e))
        logger.exception("Failed to sync agent feedback")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}