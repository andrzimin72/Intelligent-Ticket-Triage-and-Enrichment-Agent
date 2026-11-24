"""
Feedback Sync Lambda

Converts approved feedback corrections into few-shot examples and updates
the S3 examples.json file that the orchestrator reads at invocation time.

This is the final piece that closes the feedback loop:
  Technician marks "Incorrect" → Collector pulls it → Tech lead approves →
  [THIS LAMBDA] → Orchestrator uses it in prompts → AI improves

Schedule: Daily at 3 AM UTC (1 hour after the feedback collector)
"""

import json
import os
import logging
from datetime import datetime
from typing import Dict, Any, List, Tuple
import boto3
from botocore.exceptions import ClientError

# X-Ray SDK
from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
FEEDBACK_TABLE = os.environ.get('FEEDBACK_TABLE')
FEW_SHOT_EXAMPLES_BUCKET = os.environ.get('FEW_SHOT_EXAMPLES_BUCKET')
FEW_SHOT_EXAMPLES_KEY = os.environ.get('FEW_SHOT_EXAMPLES_KEY', 'examples.json')
MAX_FEW_SHOT_EXAMPLES = int(os.environ.get('MAX_FEW_SHOT_EXAMPLES', '5'))
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

# Initialize clients
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
s3_client = boto3.client('s3', region_name=AWS_REGION)


# ==============================================================================
# 1. FEEDBACK TABLE OPERATIONS
# ==============================================================================

@xray_recorder.capture('get_approved_feedback')
def get_approved_feedback() -> List[Dict[str, Any]]:
    """
    Queries the feedback table for all records with status = 'approved'.
    
    Uses the status-index GSI for efficient querying.
    """
    table = dynamodb.Table(FEEDBACK_TABLE)
    approved_records = []
    
    try:
        response = table.query(
            IndexName='status-index',
            KeyConditionExpression='#s = :status',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':status': 'approved'}
        )
        approved_records.extend(response.get('Items', []))
        
        # Handle pagination
        while 'LastEvaluatedKey' in response:
            response = table.query(
                IndexName='status-index',
                KeyConditionExpression='#s = :status',
                ExpressionAttributeNames={'#s': 'status'},
                ExpressionAttributeValues={':status': 'approved'},
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            approved_records.extend(response.get('Items', []))
        
        logger.info(f"Found {len(approved_records)} approved feedback records")
        return approved_records
    
    except ClientError as e:
        logger.error(f"Failed to query approved feedback: {e}")
        raise


@xray_recorder.capture('mark_as_injected')
def mark_as_injected(ticket_id: str) -> bool:
    """
    Updates a feedback record's status from 'approved' to 'injected'.
    
    Uses a conditional expression to ensure we only update records that
    are still in 'approved' status (prevents race conditions).
    """
    table = dynamodb.Table(FEEDBACK_TABLE)
    
    try:
        table.update_item(
            Key={'ticket_id': ticket_id},
            UpdateExpression='SET #s = :status, reviewed_at = :timestamp',
            ConditionExpression='#s = :approved',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':status': 'injected',
                ':approved': 'approved',
                ':timestamp': datetime.utcnow().isoformat()
            }
        )
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            logger.warning(f"Ticket {ticket_id} no longer in 'approved' status, skipping")
            return False
        logger.error(f"Failed to mark ticket {ticket_id} as injected: {e}")
        return False


# ==============================================================================
# 2. FEW-SHOT EXAMPLE CONVERSION
# ==============================================================================

@xray_recorder.capture('convert_to_few_shot')
def convert_to_few_shot_example(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converts a feedback record into the few-shot example format expected
    by the orchestrator's prompt builder.
    
    Format:
    {
      "id": "ticket_id",
      "input_summary": "one-line summary of the ticket",
      "output": { ... corrected AI output ... },
      "rationale": "why the AI was wrong"
    }
    
    Known limitation:
    We don't have the human's category choice (only their priority and notes).
    We use the AI's category and note in the rationale that the human
    primarily corrected priority/notes. This is imperfect but workable.
    """
    ticket_id = record.get('ticket_id')
    
    # Parse JSON fields (they're stored as strings in DynamoDB)
    ai_output = json.loads(record.get('ai_output', '{}'))
    human_correction = json.loads(record.get('human_correction', '{}'))
    ticket_context = json.loads(record.get('original_ticket_context', '{}'))
    
    # Build input_summary from ticket context
    subject = ticket_context.get('subject', 'Unknown ticket')
    description = ticket_context.get('description', '')
    # Truncate description to keep the example concise
    if len(description) > 100:
        description = description[:100] + '...'
    input_summary = f"{subject}"
    if description:
        input_summary += f" - {description}"
    
    # Build corrected output
    # Use human's priority if available, otherwise AI's
    corrected_priority = (
        human_correction.get('current_priority') or 
        ai_output.get('priority') or 
        'Medium'
    )
    
    corrected_output = {
        'category': ai_output.get('category', 'Unknown'),  # We don't have human's choice
        'priority': corrected_priority,
        'summary': ai_output.get('summary', ''),
        'draft_internal_notes': ai_output.get('draft_internal_notes', ''),
        'confidence_score': 0.0  # We don't know human's confidence
    }
    
    # Build rationale from correction notes
    rationale = record.get('correction_notes', '')
    if not rationale:
        rationale = human_correction.get('correction_notes', 'No rationale provided')
    
    return {
        'id': ticket_id,
        'input_summary': input_summary,
        'output': corrected_output,
        'rationale': rationale,
        'added_at': datetime.utcnow().isoformat()
    }


# ==============================================================================
# 3. S3 OPERATIONS
# ==============================================================================

@xray_recorder.capture('read_existing_examples')
def read_existing_examples() -> List[Dict[str, Any]]:
    """Reads the existing examples.json from S3."""
    try:
        response = s3_client.get_object(
            Bucket=FEW_SHOT_EXAMPLES_BUCKET,
            Key=FEW_SHOT_EXAMPLES_KEY
        )
        examples = json.loads(response['Body'].read().decode('utf-8'))
        logger.info(f"Read {len(examples)} existing examples from S3")
        return examples
    except s3_client.exceptions.NoSuchKey:
        logger.info("No existing examples file found, starting with empty list")
        return []
    except Exception as e:
        logger.error(f"Failed to read existing examples from S3: {e}")
        raise


@xray_recorder.capture('write_examples_to_s3')
def write_examples_to_s3(examples: List[Dict[str, Any]]) -> None:
    """Writes the updated examples list to S3."""
    try:
        s3_client.put_object(
            Bucket=FEW_SHOT_EXAMPLES_BUCKET,
            Key=FEW_SHOT_EXAMPLES_KEY,
            Body=json.dumps(examples, indent=2),
            ContentType='application/json',
            # Metadata for audit trail
            Metadata={
                'example-count': str(len(examples)),
                'updated-at': datetime.utcnow().isoformat(),
                'updated-by': 'feedback-sync-lambda'
            }
        )
        logger.info(f"Wrote {len(examples)} examples to S3")
    except Exception as e:
        logger.error(f"Failed to write examples to S3: {e}")
        raise


# ==============================================================================
# 4. MERGE LOGIC
# ==============================================================================

@xray_recorder.capture('merge_examples')
def merge_examples(
    existing: List[Dict[str, Any]], 
    new: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Merges new examples with existing ones.
    
    Rules:
    1. Deduplicate by ticket_id (existing wins to preserve order)
    2. Sort by added_at descending (most recent first)
    3. Trim to MAX_FEW_SHOT_EXAMPLES
    
    Returns the merged list.
    """
    # Build a dict keyed by ticket_id for dedup
    merged = {ex['id']: ex for ex in existing}
    
    # Add new examples (skip if already present)
    added_count = 0
    for ex in new:
        if ex['id'] not in merged:
            merged[ex['id']] = ex
            added_count += 1
        else:
            logger.info(f"Skipping duplicate example for ticket {ex['id']}")
    
    logger.info(f"Added {added_count} new examples, total before trim: {len(merged)}")
    
    # Sort by added_at descending (most recent first)
    sorted_examples = sorted(
        merged.values(),
        key=lambda x: x.get('added_at', ''),
        reverse=True
    )
    
    # Trim to MAX
    trimmed = sorted_examples[:MAX_FEW_SHOT_EXAMPLES]
    
    if len(sorted_examples) > MAX_FEW_SHOT_EXAMPLES:
        logger.info(
            f"Trimmed {len(sorted_examples) - MAX_FEW_SHOT_EXAMPLES} older examples "
            f"to respect MAX_FEW_SHOT_EXAMPLES={MAX_FEW_SHOT_EXAMPLES}"
        )
    
    return trimmed


# ==============================================================================
# 5. LAMBDA HANDLER
# ==============================================================================

@xray_recorder.capture('feedback_sync_handler')
def lambda_handler(event, context):
    """
    Main entry point for the feedback sync Lambda.
    
    Flow:
    1. Query approved feedback records
    2. Convert each to few-shot format
    3. Read existing examples from S3
    4. Merge (dedup + trim)
    5. Write updated examples to S3
    6. Mark processed records as 'injected'
    """
    try:
        logger.info("Starting feedback sync")
        
        # Step 1: Get approved feedback records
        approved_records = get_approved_feedback()
        
        if not approved_records:
            logger.info("No approved feedback records to sync")
            xray_recorder.put_annotation('records_processed', 0)
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No approved records to sync',
                    'records_processed': 0,
                    'examples_added': 0
                })
            }
        
        # Step 2: Convert to few-shot format
        new_examples = []
        for record in approved_records:
            try:
                example = convert_to_few_shot_example(record)
                new_examples.append(example)
            except Exception as e:
                logger.error(f"Failed to convert record {record.get('ticket_id')}: {e}")
                # Continue with other records
        
        xray_recorder.put_annotation('new_examples_count', len(new_examples))
        
        if not new_examples:
            logger.warning("No examples were successfully converted")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No examples converted',
                    'records_processed': len(approved_records),
                    'examples_added': 0
                })
            }
        
        # Step 3: Read existing examples
        existing_examples = read_existing_examples()
        
        # Step 4: Merge
        merged_examples = merge_examples(existing_examples, new_examples)
        
        # Step 5: Write to S3
        write_examples_to_s3(merged_examples)
        
        # Step 6: Mark records as injected
        injected_count = 0
        for record in approved_records:
            ticket_id = record.get('ticket_id')
            # Only mark as injected if this ticket's example is in the final list
            # (it might have been trimmed if we exceeded MAX)
            if any(ex['id'] == ticket_id for ex in merged_examples):
                if mark_as_injected(ticket_id):
                    injected_count += 1
        
        xray_recorder.put_annotation('records_injected', injected_count)
        xray_recorder.put_annotation('final_example_count', len(merged_examples))
        
        logger.info(
            f"Feedback sync complete: "
            f"{len(approved_records)} approved, "
            f"{len(new_examples)} converted, "
            f"{injected_count} injected, "
            f"{len(merged_examples)} total examples in S3"
        )
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Feedback sync complete',
                'records_approved': len(approved_records),
                'examples_converted': len(new_examples),
                'examples_injected': injected_count,
                'total_examples_in_s3': len(merged_examples)
            })
        }
    
    except Exception as e:
        xray_recorder.put_annotation('error', True)
        xray_recorder.put_metadata('error_message', str(e))
        logger.exception("Failed to sync feedback")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}