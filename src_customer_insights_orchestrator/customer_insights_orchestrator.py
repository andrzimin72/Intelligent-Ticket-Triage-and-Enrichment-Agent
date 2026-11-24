"""
Customer Insights Orchestrator

Runs hourly. For each enabled customer, checks if today is their report day
(based on local timezone and cadence). If so, fans out an SQS message.

Cadence logic:
- weekly: report on customer's configured local_report_day (default Sunday)
- monthly: report on first Sunday of the month
"""

import json
import os
import logging
from datetime import datetime
from typing import Dict, Any, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import boto3
from botocore.exceptions import ClientError

from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CUSTOMER_INSIGHTS_TABLE = os.environ.get('CUSTOMER_INSIGHTS_TABLE')
INSIGHTS_QUEUE_URL = os.environ.get('INSIGHTS_QUEUE_URL')
MAX_CUSTOMERS_PER_RUN = int(os.environ.get('MAX_CUSTOMERS_PER_RUN', '500'))
DEFAULT_LOCAL_DAY = int(os.environ.get('DEFAULT_LOCAL_DAY', '6'))  # 0=Mon, 6=Sun
DEFAULT_LOCAL_HOUR = int(os.environ.get('DEFAULT_LOCAL_HOUR', '9'))
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
sqs_client = boto3.client('sqs', region_name=AWS_REGION)
cloudwatch = boto3.client('cloudwatch', region_name=AWS_REGION)


@xray_recorder.capture('get_enabled_customers')
def get_enabled_customers() -> List[Dict[str, Any]]:
    """Queries the insights preferences table for enabled customers."""
    table = dynamodb.Table(CUSTOMER_INSIGHTS_TABLE)
    customers = []
    
    try:
        response = table.query(
            IndexName='enabled-index',
            KeyConditionExpression='#e = :enabled',
            ExpressionAttributeNames={'#e': 'enabled'},
            ExpressionAttributeValues={':enabled': 1}
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
        
        return customers
    except ClientError as e:
        logger.error(f"Failed to query enabled customers: {e}")
        raise


def is_report_due(customer: Dict[str, Any], now_utc: datetime) -> bool:
    """
    Determines if a customer's report is due at the current moment.
    
    Logic:
    - Convert current UTC time to customer's local timezone
    - Check if local hour matches configured report hour
    - Check if local day matches cadence:
      - weekly: matches local_report_day
      - monthly: matches AND is first occurrence of that weekday in month
    """
    tz_name = customer.get('timezone', 'UTC')
    try:
        tz = ZoneInfo(tz_name)
        local_now = now_utc.astimezone(tz)
    except (ZoneInfoNotFoundError, ValueError):
        local_now = now_utc
    
    target_hour = int(customer.get('local_report_hour', DEFAULT_LOCAL_HOUR))
    if local_now.hour != target_hour:
        return False
    
    cadence = customer.get('report_cadence', 'weekly')
    target_day = int(customer.get('local_report_day', DEFAULT_LOCAL_DAY))
    
    if local_now.weekday() != target_day:
        return False
    
    if cadence == 'monthly':
        # Only first occurrence of this weekday in the month
        if local_now.day > 7:
            return False
    
    return True


@xray_recorder.capture('fan_out_to_sqs')
def fan_out_to_sqs(customers: List[Dict[str, Any]]) -> int:
    """Sends one SQS message per customer due for a report."""
    sent_count = 0
    customers_to_process = customers[:MAX_CUSTOMERS_PER_RUN]
    
    for customer in customers_to_process:
        customer_id = customer.get('customer_id')
        if not customer_id or not customer.get('email'):
            continue
        
        try:
            message_body = {
                'customer_id': customer_id,
                'email': customer.get('email'),
                'customer_name': customer.get('customer_name', 'Valued Customer'),
                'organization_id': customer.get('organization_id'),
                'timezone': customer.get('timezone', 'UTC'),
                'report_cadence': customer.get('report_cadence', 'weekly'),
                'branding': customer.get('branding'),
            }
            
            sqs_client.send_message(
                QueueUrl=INSIGHTS_QUEUE_URL,
                MessageBody=json.dumps(message_body),
                MessageAttributes={
                    'customer_id': {'DataType': 'String', 'StringValue': customer_id}
                }
            )
            sent_count += 1
        except ClientError as e:
            logger.error(f"Failed to send SQS message for customer {customer_id}: {e}")
    
    return sent_count


@xray_recorder.capture('insights_orchestrator_handler')
def lambda_handler(event, context):
    try:
        now_utc = datetime.now(tz=ZoneInfo('UTC'))
        logger.info(f"Starting insights orchestration at UTC {now_utc.isoformat()}")
        
        customers = get_enabled_customers()
        if not customers:
            return {'statusCode': 200, 'body': json.dumps({'messages_sent': 0})}
        
        xray_recorder.put_annotation('customers_enabled', len(customers))
        
        customers_due = [c for c in customers if is_report_due(c, now_utc)]
        logger.info(f"{len(customers_due)} customers due for report out of {len(customers)}")
        
        if not customers_due:
            return {'statusCode': 200, 'body': json.dumps({'messages_sent': 0})}
        
        sent_count = fan_out_to_sqs(customers_due)
        xray_recorder.put_annotation('messages_sent', sent_count)
        
        return {'statusCode': 200, 'body': json.dumps({'messages_sent': sent_count})}
    
    except Exception as e:
        logger.exception("Failed to orchestrate insights")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}