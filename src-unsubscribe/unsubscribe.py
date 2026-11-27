"""
Unsubscribe Handler

Handles one-click unsubscribe requests from customer digest emails.
Validates the HMAC-signed token, updates the customer preferences table,
and returns a confirmation HTML page.

Endpoint: GET /unsubscribe?token=<customer_id>|<timestamp>|<signature>
"""

import json
import os
import logging
import hmac
import hashlib
import html
from typing import Dict, Any, Optional, Tuple
import boto3
from botocore.exceptions import ClientError

# X-Ray SDK
from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
CUSTOMER_PREFERENCES_TABLE = os.environ.get('CUSTOMER_PREFERENCES_TABLE')
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
    Verifies an unsubscribe token.
    
    Token format: customer_id|timestamp|signature
    Signature = HMAC-SHA256(signing_key, customer_id|timestamp)
    
    Returns:
        Tuple of (is_valid, customer_id)
    """
    signing_key = get_signing_key()
    if not signing_key:
        return False, None
    
    parts = token.split('|')
    if len(parts) != 3:
        return False, None
    
    customer_id, timestamp, signature = parts
    
    # Reconstruct the message
    message = f"{customer_id}|{timestamp}"
    
    # Compute expected signature
    expected_signature = hmac.new(
        signing_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # Constant-time comparison
    if hmac.compare_digest(signature, expected_signature):
        return True, customer_id
    
    return False, None


def disable_customer(customer_id: str) -> bool:
    """Sets the customer's enabled flag to false in DynamoDB."""
    try:
        table = dynamodb.Table(CUSTOMER_PREFERENCES_TABLE)
        table.update_item(
            Key={'customer_id': customer_id},
            UpdateExpression='SET enabled = :enabled, unsubscribed_at = :timestamp',
            ExpressionAttributeValues={
                ':enabled': 0,
                ':timestamp': __import__('datetime').datetime.utcnow().isoformat()
            },
            ConditionExpression='attribute_exists(customer_id)'
        )
        logger.info(f"Customer {customer_id} unsubscribed successfully")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            logger.warning(f"Customer {customer_id} not found")
            return False
        logger.error(f"Failed to unsubscribe customer {customer_id}: {e}")
        return False


def build_html_response(status: str, customer_id: Optional[str] = None, message: str = '') -> Dict[str, Any]:
    """Builds an HTML response for the unsubscribe page."""
    safe_company = html.escape(MSP_COMPANY_NAME)
    safe_support = html.escape(MSP_SUPPORT_EMAIL)
    safe_message = html.escape(message)
    
    if status == 'success':
        title = "Unsubscribed Successfully"
        body = f"""
            <div class="success">
                <h2>✓ You've been unsubscribed</h2>
                <p>You will no longer receive daily security digest emails from {safe_company}.</p>
                <p>If you change your mind, please contact your account manager or email us at 
                   <a href="mailto:{safe_support}">{safe_support}</a>.</p>
            </div>
        """
    elif status == 'already_unsubscribed':
        title = "Already Unsubscribed"
        body = f"""
            <div class="info">
                <h2>ℹ You're already unsubscribed</h2>
                <p>Your account was already unsubscribed from daily security digest emails.</p>
                <p>If you'd like to resubscribe, please contact your account manager or email us at 
                   <a href="mailto:{safe_support}">{safe_support}</a>.</p>
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
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            background-color: white;
            border-radius: 8px;
            padding: 40px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-top: 40px;
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid #eee;
        }}
        .header h1 {{
            margin: 0;
            color: #2c3e50;
            font-size: 24px;
        }}
        h2 {{
            color: #2c3e50;
            margin-top: 0;
        }}
        .success {{ background-color: #d4edda; padding: 20px; border-radius: 4px; border-left: 4px solid #28a745; }}
        .info {{ background-color: #d1ecf1; padding: 20px; border-radius: 4px; border-left: 4px solid #17a2b8; }}
        .error {{ background-color: #f8d7da; padding: 20px; border-radius: 4px; border-left: 4px solid #dc3545; }}
        a {{ color: #3498db; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .footer {{
            text-align: center;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #eee;
            font-size: 12px;
            color: #7f8c8d;
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
            <p>&copy; {__import__('datetime').datetime.utcnow().year} {safe_company}. All rights reserved.</p>
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


@xray_recorder.capture('unsubscribe_handler')
def lambda_handler(event, context):
    """Main entry point for the unsubscribe handler."""
    try:
        # Extract token from query string
        query_params = event.get('queryStringParameters') or {}
        token = query_params.get('token')
        
        if not token:
            logger.warning("Unsubscribe request without token")
            return build_html_response('invalid_token', message="Missing unsubscribe token.")
        
        # Verify token
        is_valid, customer_id = verify_token(token)
        
        if not is_valid:
            logger.warning("Invalid unsubscribe token")
            return build_html_response('invalid_token', message="This unsubscribe link is invalid or has expired.")
        
        xray_recorder.put_annotation('customer_id', customer_id)
        
        # Check if already unsubscribed
        table = dynamodb.Table(CUSTOMER_PREFERENCES_TABLE)
        try:
            response = table.get_item(Key={'customer_id': customer_id})
            item = response.get('Item')
            
            if not item:
                logger.warning(f"Customer {customer_id} not found")
                return build_html_response('invalid_token', message="Customer account not found.")
            
            if item.get('enabled', 1) == 0:
                logger.info(f"Customer {customer_id} already unsubscribed")
                return build_html_response('already_unsubscribed', customer_id=customer_id)
            
        except ClientError as e:
            logger.error(f"Failed to check customer status: {e}")
            return build_html_response('invalid_token', message="Unable to verify your account. Please try again later.")
        
        # Disable the customer
        if disable_customer(customer_id):
            logger.info(f"Customer {customer_id} unsubscribed successfully")
            return build_html_response('success', customer_id=customer_id)
        else:
            return build_html_response('invalid_token', message="Unable to process your request. Please contact support.")
    
    except Exception as e:
        xray_recorder.put_annotation('error', True)
        xray_recorder.put_metadata('error_message', str(e))
        logger.exception("Unsubscribe handler error")
        return build_html_response('invalid_token', message="An unexpected error occurred. Please try again later.")
