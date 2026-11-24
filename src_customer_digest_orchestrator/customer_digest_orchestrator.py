"""
Customer Digest Orchestrator (with per-customer timezone support)

Runs hourly via EventBridge. For each enabled customer, computes their local
time and fans out a message only if the local hour matches their configured
digest hour. This gives true per-timezone morning delivery.

Schedule: Hourly (5 minutes past every hour) via EventBridge
"""

import json
import os
import logging
from datetime import datetime
from typing import Dict, Any, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import boto3
from botocore.exceptions import ClientError

# X-Ray SDK
from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
CUSTOMER_PREFERENCES_TABLE = os.environ.get('CUSTOMER_PREFERENCES_TABLE')
CUSTOMER_DIGEST_QUEUE_URL = os.environ.get('CUSTOMER_DIGEST_QUEUE_URL')
MAX_CUSTOMERS_PER_RUN = int(os.environ.get('MAX_CUSTOMERS_PER_RUN', '500'))
DEFAULT_LOCAL_HOUR = int(os.environ.get('DEFAULT_LOCAL_HOUR', '7'))
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

# Initialize clients
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
sqs_client = boto3.client('sqs', region_name=AWS_REGION)
cloudwatch = boto3.client('cloudwatch', region_name=AWS_REGION)


@xray_recorder.capture('get_enabled_customers')
def get_enabled_customers() -> List[Dict[str, Any]]:
    """Queries the customer preferences table for all enabled customers."""
    table = dynamodb.Table(CUSTOMER_PREFERENCES_TABLE)
    customers = []
    
    try:
        response = table.query(
            IndexName='enabled-index',
            KeyConditionExpression='#e = :enabled',
            ExpressionAttributeNames={'#e': 'enabled'},
            ExpressionAttributeValues={':enabled': 1}  # DynamoDB stores bools as 0/1 in GSI
        )
        customers.extend(response.get('Items', []))
        
        while 'LastEvaluatedKey' in response:
            response = table.query(
                IndexName='enabled-index',
                KeyConditionExpression='#e = :enabled',
                ExpressionAttributeNames={'#e': 'enabled'},
                ExpressionAttributeValues={':enabled': 1},
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            customers.extend(response.get('Items', []))
        
        logger.info(f"Found {len(customers)} enabled customers")
        return customers
    
    except ClientError as e:
        logger.error(f"Failed to query enabled customers: {e}")
        raise


def get_customer_local_hour(customer: Dict[str, Any], now_utc: datetime) -> int:
    """
    Computes the current local hour for a customer based on their timezone.
    
    Falls back to UTC if timezone is invalid or missing.
    """
    tz_name = customer.get('timezone', 'UTC')
    
    try:
        tz = ZoneInfo(tz_name)
        local_now = now_utc.astimezone(tz)
        return local_now.hour
    except (ZoneInfoNotFoundError, ValueError) as e:
        logger.warning(f"Invalid timezone '{tz_name}' for customer {customer.get('customer_id')}, falling back to UTC: {e}")
        return now_utc.hour


def should_send_digest(customer: Dict[str, Any], now_utc: datetime) -> bool:
    """
    Determines if a customer should receive their digest at the current moment.
    
    A customer receives their digest when their local hour matches their
    configured digest_local_hour (default: DEFAULT_LOCAL_HOUR).
    """
    customer_local_hour = get_customer_local_hour(customer, now_utc)
    target_hour = int(customer.get('digest_local_hour', DEFAULT_LOCAL_HOUR))
    
    return customer_local_hour == target_hour


@xray_recorder.capture('fan_out_to_sqs')
def fan_out_to_sqs(customers: List[Dict[str, Any]]) -> int:
    """Sends one SQS message per customer that should receive a digest now."""
    sent_count = 0
    customers_to_process = customers[:MAX_CUSTOMERS_PER_RUN]
    
    if len(customers) > MAX_CUSTOMERS_PER_RUN:
        logger.warning(
            f"Safety cap applied: {len(customers)} customers found, "
            f"processing only {MAX_CUSTOMERS_PER_RUN}"
        )
    
    for customer in customers_to_process:
        customer_id = customer.get('customer_id')
        
        if not customer_id or not customer.get('email'):
            logger.warning(f"Skipping customer {customer_id}: missing required fields")
            continue
        
        try:
            message_body = {
                'customer_id': customer_id,
                'email': customer.get('email'),
                'customer_name': customer.get('customer_name', 'Valued Customer'),
                'organization_id': customer.get('organization_id'),
                'timezone': customer.get('timezone', 'UTC'),
                'digest_local_hour': int(customer.get('digest_local_hour', DEFAULT_LOCAL_HOUR)),
                'branding': customer.get('branding'),  # Optional per-customer branding
            }
            
            sqs_client.send_message(
                QueueUrl=CUSTOMER_DIGEST_QUEUE_URL,
                MessageBody=json.dumps(message_body),
                MessageAttributes={
                    'customer_id': {'DataType': 'String', 'StringValue': customer_id}
                }
            )
            sent_count += 1
        
        except ClientError as e:
            logger.error(f"Failed to send SQS message for customer {customer_id}: {e}")
    
    return sent_count


def emit_custom_metrics(total_enabled: int, sent_count: int, skipped_count: int):
    """Emits custom CloudWatch metrics for monitoring."""
    try:
        cloudwatch.put_metric_data(
            Namespace='Custom/MSP-Triage',
            MetricData=[
                {'MetricName': 'CustomerDigestEnabledCount', 'Value': total_enabled, 'Unit': 'Count'},
                {'MetricName': 'CustomerDigestSentCount', 'Value': sent_count, 'Unit': 'Count'},
                {'MetricName': 'CustomerDigestSkippedCount', 'Value': skipped_count, 'Unit': 'Count'},
            ]
        )
    except Exception as e:
        logger.warning(f"Failed to emit custom metrics: {e}")


@xray_recorder.capture('customer_digest_orchestrator_handler')
def lambda_handler(event, context):
    """Main entry point for the customer digest orchestrator."""
    try:
        now_utc = datetime.now(tz=ZoneInfo('UTC'))
        logger.info(f"Starting customer digest orchestration at UTC {now_utc.isoformat()}")
        
        # Step 1: Get enabled customers
        customers = get_enabled_customers()
        
        if not customers:
            logger.info("No enabled customers found, nothing to do")
            xray_recorder.put_annotation('customers_enabled', 0)
            xray_recorder.put_annotation('messages_sent', 0)
            return {'statusCode': 200, 'body': json.dumps({
                'message': 'No enabled customers',
                'customers_enabled': 0,
                'messages_sent': 0
            })}
        
        xray_recorder.put_annotation('customers_enabled', len(customers))
        
        # Step 2: Filter to customers whose local hour matches their digest hour
        customers_due = [c for c in customers if should_send_digest(c, now_utc)]
        skipped_count = len(customers) - len(customers_due)
        
        logger.info(
            f"Timezone filter: {len(customers_due)} customers due now, "
            f"{skipped_count} skipped (not their local digest hour)"
        )
        
        xray_recorder.put_annotation('customers_due', len(customers_due))
        
        if not customers_due:
            return {'statusCode': 200, 'body': json.dumps({
                'message': 'No customers due for digest at this hour',
                'customers_enabled': len(customers),
                'customers_due': 0,
                'messages_sent': 0
            })}
        
        # Step 3: Fan out to SQS
        sent_count = fan_out_to_sqs(customers_due)
        
        xray_recorder.put_annotation('messages_sent', sent_count)
        
        # Step 4: Emit custom metrics
        emit_custom_metrics(len(customers), sent_count, skipped_count)
        
        logger.info(f"Customer digest orchestration complete: {sent_count} messages sent")
        return {'statusCode': 200, 'body': json.dumps({
            'message': 'Customer digest orchestration complete',
            'customers_enabled': len(customers),
            'customers_due': len(customers_due),
            'messages_sent': sent_count,
            'skipped_count': skipped_count
        })}
    
    except Exception as e:
        xray_recorder.put_annotation('error', True)
        xray_recorder.put_metadata('error_message', str(e))
        logger.exception("Failed to orchestrate customer digests")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}