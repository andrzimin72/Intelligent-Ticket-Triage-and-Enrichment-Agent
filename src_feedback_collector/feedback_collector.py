"""
Daily Feedback Collector with X-Ray distributed tracing.
"""

import json
import os
import logging
import base64
import urllib.request
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import boto3
from botocore.exceptions import ClientError

# X-Ray SDK
from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
FEEDBACK_TABLE = os.environ.get('FEEDBACK_TABLE')
METRICS_TABLE = os.environ.get('METRICS_TABLE')
PSA_SECRET_NAME = os.environ.get('PSA_SECRET_NAME')
AI_ACCURACY_FIELD_ID = int(os.environ.get('AI_ACCURACY_FIELD_ID', '999'))
AI_CORRECTION_NOTES_FIELD_ID = int(os.environ.get('AI_CORRECTION_NOTES_FIELD_ID', '998'))
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')
FEEDBACK_TTL_DAYS = int(os.environ.get('FEEDBACK_TTL_DAYS', '365'))

# Initialize clients
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
secrets_client = boto3.client('secretsmanager', region_name=AWS_REGION)

_secret_cache = {}


def get_secret(secret_name: str) -> Dict[str, str]:
    if secret_name in _secret_cache:
        return _secret_cache[secret_name]
    
    response = secrets_client.get_secret_value(SecretId=secret_name)
    secret = json.loads(response['SecretString'])
    _secret_cache[secret_name] = secret
    return secret


def make_api_request(url: str, headers: Dict[str, str], method: str = 'GET') -> Any:
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        logger.error(f"API request failed: {e}")
        raise


def get_cw_headers() -> Dict[str, str]:
    """Builds ConnectWise API headers."""
    psa_secret = get_secret(PSA_SECRET_NAME)
    auth_string = f"{psa_secret['COMPANY_ID']}+{psa_secret['PUBLIC_KEY']}:{psa_secret['PRIVATE_KEY']}"
    auth_bytes = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
    
    return {
        'Authorization': f"Basic {auth_bytes}",
        'Accept': 'application/vnd.connectwise.com+json; version=v2024.1',
        'clientId': psa_secret.get('CLIENT_ID', 'FeedbackCollector')
    }


@xray_recorder.capture('find_incorrect_tickets')
def find_incorrect_tickets(days_back: int = 1) -> List[str]:
    """Queries the metrics table for tickets processed in the last N days."""
    metrics_table = dynamodb.Table(METRICS_TABLE)
    
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days_back)
    
    response = metrics_table.scan(
        FilterExpression='#ts >= :start_date AND #ts <= :end_date',
        ExpressionAttributeNames={'#ts': 'timestamp'},
        ExpressionAttributeValues={
            ':start_date': start_date.isoformat(),
            ':end_date': end_date.isoformat()
        }
    )
    
    return [item['ticket_id'] for item in response.get('Items', [])]


@xray_recorder.capture('get_ticket_feedback')
def get_ticket_feedback(ticket_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a ticket from ConnectWise and extracts feedback fields."""
    headers = get_cw_headers()
    psa_secret = get_secret(PSA_SECRET_NAME)
    base_url = psa_secret['BASE_URL'].rstrip('/')
    
    url = f"{base_url}/v4_6_release/apis/3.0/service/tickets/{ticket_id}?fields=id,summary,description,company,board,priority,customFields"
    
    try:
        ticket_data = make_api_request(url, headers)
    except Exception as e:
        logger.warning(f"Failed to fetch ticket {ticket_id}: {e}")
        return None
    
    ai_accuracy = None
    correction_notes = None
    
    for field in ticket_data.get('customFields', []):
        if field.get('id') == AI_ACCURACY_FIELD_ID:
            ai_accuracy = field.get('value')
        elif field.get('id') == AI_CORRECTION_NOTES_FIELD_ID:
            correction_notes = field.get('value')
    
    if ai_accuracy != 'Incorrect':
        return None
    
    return {
        'ticket_id': ticket_id,
        'subject': ticket_data.get('summary'),
        'description': ticket_data.get('description'),
        'customer_id': str(ticket_data.get('company', {}).get('id', 'UNKNOWN')),
        'current_priority': ticket_data.get('priority', {}).get('name'),
        'correction_notes': correction_notes or '(No notes provided)',
    }


@xray_recorder.capture('get_original_ai_output')
def get_original_ai_output(ticket_id: str) -> Optional[Dict[str, Any]]:
    """Fetches the original AI output from the metrics table."""
    metrics_table = dynamodb.Table(METRICS_TABLE)
    
    try:
        response = metrics_table.get_item(Key={'ticket_id': ticket_id})
        return response.get('Item')
    except ClientError as e:
        logger.warning(f"Failed to fetch metrics for ticket {ticket_id}: {e}")
        return None


@xray_recorder.capture('store_feedback_record')
def store_feedback_record(ticket_id: str, ticket_feedback: Dict[str, Any], ai_output: Dict[str, Any]):
    """Stores the feedback record in DynamoDB."""
    feedback_table = dynamodb.Table(FEEDBACK_TABLE)
    ttl_timestamp = int((datetime.utcnow() + timedelta(days=FEEDBACK_TTL_DAYS)).timestamp())
    
    item = {
        'ticket_id': ticket_id,
        'customer_id': ticket_feedback.get('customer_id'),
        'timestamp': datetime.utcnow().isoformat(),
        'ai_output': json.dumps({
            'category': ai_output.get('ai_category'),
            'priority': ai_output.get('ai_priority'),
            'summary': ai_output.get('ai_summary', ''),
            'draft_internal_notes': ai_output.get('ai_summary', ''),
            'confidence_score': ai_output.get('ai_confidence_score', 0),
        }),
        'human_correction': json.dumps({
            'current_priority': ticket_feedback.get('current_priority'),
            'correction_notes': ticket_feedback.get('correction_notes'),
        }),
        'original_ticket_context': json.dumps({
            'subject': ticket_feedback.get('subject'),
            'description': ticket_feedback.get('description'),
        }),
        'ai_model_used': ai_output.get('model_id_used', 'unknown'),
        'ai_confidence_score': ai_output.get('ai_confidence_score', 0),
        'complexity': ai_output.get('complexity', 'unknown'),
        'correction_notes': ticket_feedback.get('correction_notes', ''),
        'status': 'pending_review',
        'reviewed_by': None,
        'reviewed_at': None,
        'ttl': ttl_timestamp,
    }
    
    feedback_table.put_item(Item=item)
    logger.info(f"Stored feedback record for ticket {ticket_id}")


@xray_recorder.capture('feedback_collector_handler')
def lambda_handler(event, context):
    """Main entry point for the daily feedback collector."""
    try:
        logger.info("Starting daily feedback collection")
        
        ticket_ids = find_incorrect_tickets(days_back=1)
        logger.info(f"Found {len(ticket_ids)} tickets processed in the last 24 hours")
        
        # Add ticket count as annotation
        xray_recorder.put_annotation('tickets_processed', len(ticket_ids))
        
        if not ticket_ids:
            return {'statusCode': 200, 'body': 'No tickets to process'}
        
        incorrect_count = 0
        for ticket_id in ticket_ids:
            ticket_feedback = get_ticket_feedback(ticket_id)
            
            if not ticket_feedback:
                continue
            
            ai_output = get_original_ai_output(ticket_id)
            if not ai_output:
                logger.warning(f"No AI output found for ticket {ticket_id}, skipping")
                continue
            
            store_feedback_record(ticket_id, ticket_feedback, ai_output)
            incorrect_count += 1
        
        # Add incorrect count as annotation
        xray_recorder.put_annotation('incorrect_collected', incorrect_count)
        
        logger.info(f"Collected {incorrect_count} incorrect tickets")
        return {
            'statusCode': 200,
            'body': json.dumps({
                'tickets_processed': len(ticket_ids),
                'incorrect_collected': incorrect_count,
            })
        }
    
    except Exception as e:
        xray_recorder.put_annotation('error', True)
        xray_recorder.put_metadata('error_message', str(e))
        logger.exception("Failed to collect feedback")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}