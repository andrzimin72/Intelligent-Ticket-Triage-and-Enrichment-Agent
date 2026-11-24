"""
Customer Insights Unsubscribe Handler

Handles one-click unsubscribe requests from customer insights emails.
Validates the HMAC-signed token, updates the customer insights preferences table,
and returns a confirmation HTML page.

Endpoint: GET /unsubscribe-insights?token=insights|<customer_id>|<timestamp>|<signature>
"""

import json
import os
import logging
import hmac
import hashlib
import html
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
import boto3
from botocore.exceptions import ClientError

# X-Ray SDK
from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
CUSTOMER_INSIGHTS_TABLE = os.environ.get('CUSTOMER_INSIGHTS_TABLE')
UNSUBSCRIBE_SECRET_NAME = os.environ.get('UNSUBSCRIBE_SECRET_NAME')
MSP_COMPANY_NAME = os.environ.get('MSP_COMPANY_NAME', 'Your MSP')
MSP_SUPPORT_EMAIL = os.environ.get('MSP_SUPPORT_EMAIL', 'support@yourmsp.com')

# Initialize clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
secrets_client = boto3.client('secretsmanager', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

_secret_cache = {}


def get_signing_key() -> Optional[str]:
    """Fetches and caches the HMAC signing key from Secrets Manager."""
    if UNSUBSCRIBE_SECRET_NAME in _secret_cache:
        return _secret_cache[UNSUBSCRIBE_SECRET_NAME]
    
    try:
        response = secrets_client.get_secret_value(SecretId=UNSUBSCRIBE_SECRET_NAME)
        secret = json.loads(response['SecretString'])
        key = secret.get('SIGNING_KEY')
        if key:
            _secret_cache[UNSUBSCRIBE_SECRET_NAME] = key
        return key
    except ClientError as e:
        logger.error(f"Failed to retrieve signing key: {e}")
        return None


def verify_token(token: str) -> Tuple[bool, Optional[str]]:
    """
    Verifies an insights unsubscribe token.
    
    Token format: insights|customer_id|timestamp|signature
    Signature = HMAC-SHA256(signing_key, "insights|customer_id|timestamp")
    """
    signing_key = get_signing_key()
    if not signing_key:
        return False, None
    
    parts = token.split('|')
    if len(parts) != 4 or parts[0] != 'insights':
        return False, None
    
    _, customer_id, timestamp, signature = parts
    
    message = f"insights|{customer_id}|{timestamp}"
    expected_signature = hmac.new(
        signing_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    if hmac.compare_digest(signature, expected_signature):
        return True, customer_id
    
    return False, None


def disable_customer(customer_id: str) -> bool:
    """Sets the customer's enabled flag to false in the insights preferences table."""
    try:
        table = dynamodb.Table(CUSTOMER_INSIGHTS_TABLE)
        table.update_item(
            Key={'customer_id': customer_id},
            UpdateExpression='SET enabled = :enabled, unsubscribed_at = :timestamp',
            ExpressionAttributeValues={
                ':enabled': 0,
                ':timestamp': datetime.utcnow().isoformat()
            },
            ConditionExpression='attribute_exists(customer_id)'
        )
        logger.info(f"Customer {customer_id} unsubscribed from insights successfully")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            logger.warning(f"Customer {customer_id} not found in insights preferences")
            return False
        logger.error(f"Failed to unsubscribe customer {customer_id}: {e}")
        return False


def build_html_response(status: str, customer_id: Optional[str] = None, message: str = '') -> Dict[str, Any]:
    """Builds an HTML response for the unsubscribe page."""
    safe_company = html.escape(MSP_COMPANY_NAME)
    safe_support = html.escape(MSP_SUPPORT_EMAIL)
    safe_message = html.escape(message)
    
    if status == 'success':
        title = "Unsubscribed from Insights"
        body = f"""
            <div class="success">
                <h2>✓ You've been unsubscribed</h2>
                <p>You will no longer receive {safe_company}'s IT Health & Security Summary reports.</p>
                <p>If you change your mind, please contact your account manager or email us at 
                   <a href="mailto:{safe_support}">{safe_support}</a>.</p>
            </div>
        """
    elif status == 'already_unsubscribed':
        title = "Already Unsubscribed"
        body = f"""
            <div class="info">
                <h2>ℹ You're already unsubscribed</h2>
                <p>Your account was already unsubscribed from IT Health & Security Summary reports.</p>
                <p>If you'd like to resubscribe, please contact your account manager.</p>
            </div>
        """
    elif status == 'invalid_token':
        title = "Invalid Link"
        body = f"""
            <div class="error">
                <h2>✗ Invalid unsubscribe link</h2>
                <p>{safe_message}</p>
                <p>If you believe this is an error, please contact us at 
                   <a href="mailto:{safe_support}">{safe_support}</a>.</p>
            </div>
        """
    else:
        title = "Error"
        body = f'<div class="error"><p>{safe_message}</p></div>'
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)} - {safe_company}</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto;
            padding: 20px; background-color: #f5f5f5;
        }}
        .container {{
            background-color: white; border-radius: 8px; padding: 40px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-top: 40px;
        }}
        .header {{
            text-align: center; margin-bottom: 30px; padding-bottom: 20px;
            border-bottom: 1px solid #eee;
        }}
        .header h1 {{ margin: 0; color: #2c3e50; font-size: 24px; }}
        h2 {{ color: #2c3e50; margin-top: 0; }}
        .success {{ background-color: #d4edda; padding: 20px; border-radius: 4px; border-left: 4px solid #28a745; }}
        .info {{ background-color: #d1ecf1; padding: 20px; border-radius: 4px; border-left: 4px solid #17a2b8; }}
        .error {{ background-color: #f8d7da; padding: 20px; border-radius: 4px; border-left: 4px solid #dc3545; }}
        a {{ color: #3498db; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .footer {{
            text-align: center; margin-top: 30px; padding-top: 20px;
            border-top: 1px solid #eee; font-size: 12px; color: #7f8c8d;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{safe_company}</h1>
        </div>
        {body}
        <div class="footer">
            <p>&copy; {datetime.utcnow().year} {safe_company}. All rights reserved.</p>
            <p>Questions? Email <a href="mailto:{safe_support}">{safe_support}</a></p>
        </div>
    </div>
</body>
</html>"""
    
    return {
        'statusCode': 200 if status != 'invalid_token' else 400,
        'headers': {'Content-Type': 'text/html; charset=utf-8'},
        'body': html_content
    }


@xray_recorder.capture('customer_insights_unsubscribe_handler')
def lambda_handler(event, context):
    """Main entry point for the insights unsubscribe handler."""
    try:
        query_params = event.get('queryStringParameters') or {}
        token = query_params.get('token')
        
        if not token:
            logger.warning("Unsubscribe request without token")
            return build_html_response('invalid_token', message="Missing unsubscribe token.")
        
        is_valid, customer_id = verify_token(token)
        
        if not is_valid:
            logger.warning("Invalid insights unsubscribe token")
            return build_html_response('invalid_token', message="This unsubscribe link is invalid or has expired.")
        
        xray_recorder.put_annotation('customer_id', customer_id)
        
        # Check if already unsubscribed
        table = dynamodb.Table(CUSTOMER_INSIGHTS_TABLE)
        try:
            response = table.get_item(Key={'customer_id': customer_id})
            item = response.get('Item')
            
            if not item:
                logger.warning(f"Customer {customer_id} not found in insights preferences")
                return build_html_response('invalid_token', message="Customer account not found.")
            
            if item.get('enabled', 1) == 0:
                logger.info(f"Customer {customer_id} already unsubscribed from insights")
                return build_html_response('already_unsubscribed', customer_id=customer_id)
            
        except ClientError as e:
            logger.error(f"Failed to check customer status: {e}")
            return build_html_response('invalid_token', message="Unable to verify your account. Please try again later.")
        
        # Disable the customer
        if disable_customer(customer_id):
            logger.info(f"Customer {customer_id} unsubscribed from insights successfully")
            return build_html_response('success', customer_id=customer_id)
        else:
            return build_html_response('invalid_token', message="Unable to process your request. Please contact support.")
    
    except Exception as e:
        xray_recorder.put_annotation('error', True)
        xray_recorder.put_metadata('error_message', str(e))
        logger.exception("Customer insights unsubscribe handler error")
        return build_html_response('invalid_token', message="An unexpected error occurred. Please try again later.")