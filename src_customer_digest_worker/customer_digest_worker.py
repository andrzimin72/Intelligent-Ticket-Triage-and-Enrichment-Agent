"""
Customer Digest Worker (with branding, trends, history, and corrected guardrail handling)

Processes one customer at a time:
1. Fetches NinjaOne alerts (warning+ severity, last 24 hours)
2. If no alerts, skip (don't send empty emails)
3. Fetches alert history for trend analysis
4. Writes today's snapshot to alert history table
5. Calls Bedrock Haiku to generate a plain-English security summary with trend context
6. Applies customer-facing guardrail (PII + tone) — with correct BLOCK vs ANONYMIZE handling
7. Builds branded HTML email with unsubscribe link
8. Sends the digest email via SES
"""

import json
import os
import logging
import hmac
import hashlib
import urllib.request
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
import boto3
from botocore.exceptions import ClientError

# X-Ray SDK
from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
RMM_SECRET_NAME = os.environ.get('RMM_SECRET_NAME')
UNSUBSCRIBE_SECRET_NAME = os.environ.get('UNSUBSCRIBE_SECRET_NAME')
CUSTOMER_PREFERENCES_TABLE = os.environ.get('CUSTOMER_PREFERENCES_TABLE')
ALERT_HISTORY_TABLE = os.environ.get('ALERT_HISTORY_TABLE')
CUSTOMER_DIGEST_MODEL_ID = os.environ.get('CUSTOMER_DIGEST_MODEL_ID')
GUARDRAIL_ID = os.environ.get('GUARDRAIL_ID')
GUARDRAIL_VERSION = os.environ.get('GUARDRAIL_VERSION')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
MIN_SEVERITY = os.environ.get('MIN_SEVERITY', 'warning')
ALERT_HISTORY_RETENTION = int(os.environ.get('ALERT_HISTORY_RETENTION', '90'))
UNSUBSCRIBE_BASE_URL = os.environ.get('UNSUBSCRIBE_BASE_URL')
MSP_DEFAULT_BRANDING_JSON = os.environ.get('MSP_DEFAULT_BRANDING', '{}')
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

SEVERITY_ORDER = {'info': 0, 'warning': 1, 'error': 2, 'critical': 3}

# Guardrail action constants (must match the triage orchestrator)
GUARDRAIL_ACTION_NONE = 'NONE'
GUARDRAIL_ACTION_BLOCK = 'GUARDRAIL_INTERVENED_BLOCK'
GUARDRAIL_ACTION_ANONYMIZE = 'GUARDRAIL_INTERVENED_ANONYMIZE'

bedrock_runtime = boto3.client('bedrock-runtime', region_name=AWS_REGION)
secrets_client = boto3.client('secretsmanager', region_name=AWS_REGION)
ses_client = boto3.client('ses', region_name=AWS_REGION)
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)

_secret_cache = {}


def get_secret(secret_name: str) -> Dict[str, str]:
    """Fetches and caches secrets from AWS Secrets Manager."""
    if secret_name in _secret_cache:
        return _secret_cache[secret_name]
    
    try:
        response = secrets_client.get_secret_value(SecretId=secret_name)
        secret = json.loads(response['SecretString'])
        _secret_cache[secret_name] = secret
        return secret
    except ClientError as e:
        logger.error(f"Failed to retrieve secret {secret_name}: {e}")
        raise


def get_default_branding() -> Dict[str, str]:
    """Parses the default MSP branding from environment variable."""
    try:
        return json.loads(MSP_DEFAULT_BRANDING_JSON)
    except json.JSONDecodeError:
        return {
            'company_name': 'Your MSP',
            'logo_url': '',
            'primary_color': '#2c3e50',
            'support_email': 'support@yourmsp.com',
            'support_phone': '+1-555-0100'
        }


def get_customer_branding(customer_id: str) -> Dict[str, str]:
    """Fetches customer-specific branding from preferences table, falling back to defaults."""
    defaults = get_default_branding()
    
    try:
        table = dynamodb.Table(CUSTOMER_PREFERENCES_TABLE)
        response = table.get_item(Key={'customer_id': customer_id})
        item = response.get('Item', {})
        
        customer_branding = item.get('branding', {})
        if isinstance(customer_branding, str):
            try:
                customer_branding = json.loads(customer_branding)
            except json.JSONDecodeError:
                customer_branding = {}
        
        merged = {**defaults, **{k: v for k, v in customer_branding.items() if v}}
        return merged
    
    except ClientError as e:
        logger.warning(f"Failed to fetch branding for customer {customer_id}: {e}")
        return defaults


def generate_unsubscribe_token(customer_id: str) -> str:
    """Generates an HMAC-signed unsubscribe token."""
    try:
        signing_key = get_secret(UNSUBSCRIBE_SECRET_NAME).get('SIGNING_KEY')
    except Exception as e:
        logger.error(f"Failed to retrieve unsubscribe signing key: {e}")
        return ''
    
    if not signing_key:
        logger.error("Unsubscribe signing key not found")
        return ''
    
    timestamp = str(int(datetime.utcnow().timestamp()))
    message = f"{customer_id}|{timestamp}"
    signature = hmac.new(
        signing_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return f"{customer_id}|{timestamp}|{signature}"


# ==============================================================================
# GUARDRAIL (CORRECTED - distinguishes BLOCK vs ANONYMIZE)
# ==============================================================================

def apply_guardrail(text: str, source: str = 'INPUT') -> Dict[str, Any]:
    """
    Applies Bedrock Guardrail to text.
    
    Returns:
        Dict with:
        - 'action': One of 'NONE', 'GUARDRAIL_INTERVENED_BLOCK', 'GUARDRAIL_INTERVENED_ANONYMIZE'
        - 'text': 
            - For NONE: the original text (unchanged)
            - For ANONYMIZE: the sanitized text (PII replaced)
            - For BLOCK: empty string (content was rejected)
        - 'assessments': Details of what was flagged (empty for NONE)
    """
    if not GUARDRAIL_ID or not GUARDRAIL_VERSION:
        logger.warning("Guardrail not configured, skipping validation")
        return {'action': GUARDRAIL_ACTION_NONE, 'text': text, 'assessments': []}
    
    try:
        response = bedrock_runtime.apply_guardrail(
            guardrailIdentifier=GUARDRAIL_ID,
            guardrailVersion=GUARDRAIL_VERSION,
            source=source,
            content=[{'text': {'text': text}}]
        )
        
        action = response.get('action', 'NONE')
        outputs = response.get('outputs', [])
        assessments = response.get('assessments', [])
        
        if action == 'GUARDRAIL_INTERVENED':
            if outputs:
                sanitized_text = outputs[0].get('text', '')
                logger.warning(
                    f"Guardrail ANONYMIZED content on {source}: {assessments}"
                )
                return {
                    'action': GUARDRAIL_ACTION_ANONYMIZE,
                    'text': sanitized_text,
                    'assessments': assessments,
                }
            else:
                logger.warning(
                    f"Guardrail BLOCKED content on {source}: {assessments}"
                )
                return {
                    'action': GUARDRAIL_ACTION_BLOCK,
                    'text': '',
                    'assessments': assessments,
                }
        else:
            return {'action': GUARDRAIL_ACTION_NONE, 'text': text, 'assessments': []}
    
    except ClientError as e:
        logger.error(f"Guardrail API error: {e}")
        raise


# ==============================================================================
# ALERT OPERATIONS
# ==============================================================================

@xray_recorder.capture('get_customer_alerts')
def get_customer_alerts(organization_id: str) -> List[Dict[str, Any]]:
    """Fetches alerts from NinjaOne for a specific organization."""
    rmm_secret = get_secret(RMM_SECRET_NAME)
    base_url = rmm_secret['BASE_URL'].rstrip('/')
    
    headers = {
        'Authorization': f"Bearer {rmm_secret['API_TOKEN']}",
        'Accept': 'application/json'
    }
    
    alerts_url = f"{base_url}/v2/alerts?organizationId={organization_id}&state=open&limit=50"
    
    try:
        req = urllib.request.Request(alerts_url, headers=headers, method='GET')
        with urllib.request.urlopen(req, timeout=30) as response:
            alerts_data = json.loads(response.read().decode('utf-8'))
        
        all_alerts = alerts_data.get('data', [])
        
        min_severity_level = SEVERITY_ORDER.get(MIN_SEVERITY, 1)
        filtered_alerts = [
            alert for alert in all_alerts
            if SEVERITY_ORDER.get(alert.get('severity', 'info').lower(), 0) >= min_severity_level
        ]
        
        cutoff_time = datetime.utcnow() - timedelta(hours=24)
        recent_alerts = []
        for alert in filtered_alerts:
            alert_time_str = alert.get('alertTime')
            if alert_time_str:
                try:
                    alert_time = datetime.fromisoformat(alert_time_str.replace('Z', '+00:00'))
                    if alert_time.replace(tzinfo=None) >= cutoff_time:
                        recent_alerts.append(alert)
                except ValueError:
                    recent_alerts.append(alert)
        
        logger.info(f"Found {len(recent_alerts)} recent alerts for org {organization_id}")
        return recent_alerts
    
    except Exception as e:
        logger.error(f"Failed to fetch alerts for org {organization_id}: {e}")
        raise


@xray_recorder.capture('get_alert_history')
def get_alert_history(customer_id: str, days: int = 7) -> List[Dict[str, Any]]:
    """Fetches alert history for the past N days for trend analysis."""
    try:
        table = dynamodb.Table(ALERT_HISTORY_TABLE)
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        response = table.query(
            KeyConditionExpression='customer_id = :cid AND date_key BETWEEN :start AND :end',
            ExpressionAttributeValues={
                ':cid': customer_id,
                ':start': start_date.strftime('%Y-%m-%d'),
                ':end': end_date.strftime('%Y-%m-%d')
            }
        )
        
        items = response.get('Items', [])
        items.sort(key=lambda x: x.get('date_key', ''))
        return items
    
    except ClientError as e:
        logger.warning(f"Failed to fetch alert history for customer {customer_id}: {e}")
        return []


@xray_recorder.capture('write_alert_snapshot')
def write_alert_snapshot(customer_id: str, alerts: List[Dict[str, Any]]) -> None:
    """Writes today's alert snapshot to the history table."""
    try:
        table = dynamodb.Table(ALERT_HISTORY_TABLE)
        today = datetime.utcnow().strftime('%Y-%m-%d')
        ttl_timestamp = int((datetime.utcnow() + timedelta(days=ALERT_HISTORY_RETENTION)).timestamp())
        
        by_severity = {}
        for alert in alerts:
            sev = alert.get('severity', 'unknown').lower()
            by_severity[sev] = by_severity.get(sev, 0) + 1
        
        table.put_item(Item={
            'customer_id': customer_id,
            'date_key': today,
            'alert_count': len(alerts),
            'by_severity': json.dumps(by_severity),
            'alert_names': json.dumps([a.get('alertName', 'Unknown') for a in alerts[:20]]),
            'ttl': ttl_timestamp
        })
        
        logger.info(f"Wrote alert snapshot for customer {customer_id} on {today}: {len(alerts)} alerts")
    
    except ClientError as e:
        logger.error(f"Failed to write alert snapshot for customer {customer_id}: {e}")


def compute_trend_summary(history: List[Dict[str, Any]], today_count: int) -> Dict[str, Any]:
    """Computes trend statistics from alert history."""
    if not history:
        return {
            'seven_day_average': None,
            'yesterday_count': None,
            'change_from_yesterday': None,
            'change_percentage': None,
            'trend_direction': 'unknown'
        }
    
    counts = [item.get('alert_count', 0) for item in history]
    seven_day_avg = sum(counts) / len(counts) if counts else 0
    yesterday_count = counts[-1] if counts else 0
    change = today_count - yesterday_count
    change_pct = (change / yesterday_count * 100) if yesterday_count > 0 else None
    
    if len(counts) >= 3:
        recent_avg = sum(counts[-3:]) / 3
        older_avg = sum(counts[:-3]) / len(counts[:-3]) if len(counts) > 3 else recent_avg
        if recent_avg > older_avg * 1.1:
            direction = 'increasing'
        elif recent_avg < older_avg * 0.9:
            direction = 'decreasing'
        else:
            direction = 'stable'
    else:
        direction = 'unknown'
    
    return {
        'seven_day_average': round(seven_day_avg, 1),
        'yesterday_count': yesterday_count,
        'change_from_yesterday': change,
        'change_percentage': round(change_pct, 1) if change_pct is not None else None,
        'trend_direction': direction
    }


# ==============================================================================
# SUMMARY GENERATION (CORRECTED - handles all three guardrail states)
# ==============================================================================

@xray_recorder.capture('generate_digest_summary')
def generate_digest_summary(
    customer_name: str,
    alerts: List[Dict[str, Any]],
    trend: Dict[str, Any]
) -> str:
    """Calls Bedrock Haiku to generate a plain-English security summary with trend context."""
    alerts_text = "\n".join([
        f"- {alert.get('alertName', 'Unknown alert')} on {alert.get('deviceName', 'unknown device')} "
        f"(severity: {alert.get('severity', 'unknown')})"
        for alert in alerts
    ])
    
    trend_text = ""
    if trend['seven_day_average'] is not None:
        trend_text = f"""
Trend context (for your reference, do NOT mention specific numbers unless helpful):
- 7-day average: {trend['seven_day_average']} alerts/day
- Yesterday: {trend['yesterday_count']} alerts
- Today: {len(alerts)} alerts
- Trend: {trend['trend_direction']}
"""
    
    user_prompt = f"""Generate a brief, professional security digest for {customer_name}.

Recent security alerts (last 24 hours):
{alerts_text}
{trend_text}
Requirements:
1. Start with a one-sentence overall assessment
2. Summarize the alerts in plain English that a non-technical business owner can understand
3. For each alert, briefly explain what it means in business terms
4. If action is needed, clearly state what the customer should do
5. If no action is needed, reassure the customer
6. If the trend is increasing, gently note that we're monitoring closely
7. If the trend is decreasing, acknowledge the improvement
8. End with a brief note about our ongoing monitoring
9. Keep the total summary under 300 words
10. Use a professional, reassuring tone — avoid alarming language
11. Do NOT include any customer names, email addresses, IP addresses, or other PII
12. Do NOT include any medical, legal, or financial advice

Return ONLY the digest text, no JSON, no markdown formatting."""

    # --- INPUT GUARDRAIL (CORRECTED) ---
    input_result = apply_guardrail(user_prompt, source='INPUT')
    
    if input_result['action'] == GUARDRAIL_ACTION_BLOCK:
        logger.error(
            f"Input guardrail BLOCKED customer digest content: {input_result['assessments']}"
        )
        raise ValueError("Input contains sensitive or inappropriate content")
    
    if input_result['action'] == GUARDRAIL_ACTION_ANONYMIZE:
        user_prompt = input_result['text']
        logger.info("Input guardrail anonymized PII in customer digest prompt")
    
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": user_prompt}]
    })
    
    try:
        logger.info(f"Invoking Bedrock model {CUSTOMER_DIGEST_MODEL_ID}")
        response = bedrock_runtime.invoke_model(
            modelId=CUSTOMER_DIGEST_MODEL_ID,
            body=body
        )
        response_body = json.loads(response.get('body').read())
        summary_text = response_body['content'][0]['text']
        
        # --- OUTPUT GUARDRAIL (CORRECTED) ---
        output_result = apply_guardrail(summary_text, source='OUTPUT')
        
        if output_result['action'] == GUARDRAIL_ACTION_BLOCK:
            logger.error(
                f"Output guardrail BLOCKED customer digest response: {output_result['assessments']}"
            )
            raise ValueError("Output contains sensitive or inappropriate content")
        
        if output_result['action'] == GUARDRAIL_ACTION_ANONYMIZE:
            summary_text = output_result['text']
            logger.info("Output guardrail anonymized PII in customer digest response")
        
        return summary_text
    
    except Exception as e:
        logger.error(f"Failed to generate digest summary: {e}")
        raise


# ==============================================================================
# EMAIL FORMATTING
# ==============================================================================

def build_trend_badge(trend: Dict[str, Any]) -> str:
    """Builds an HTML snippet for the trend badge."""
    if trend['trend_direction'] == 'increasing':
        color = '#e74c3c'
        icon = '↑'
        label = 'Increasing'
    elif trend['trend_direction'] == 'decreasing':
        color = '#27ae60'
        icon = '↓'
        label = 'Decreasing'
    elif trend['trend_direction'] == 'stable':
        color = '#3498db'
        icon = '→'
        label = 'Stable'
    else:
        return ''
    
    return f"""
        <div style="display: inline-block; background-color: {color}; color: white; 
                    padding: 5px 12px; border-radius: 15px; font-size: 13px; margin-left: 10px;">
            {icon} {label}
        </div>
    """


def build_trend_section(trend: Dict[str, Any]) -> str:
    """Builds an HTML snippet for the trend section."""
    if trend['seven_day_average'] is None:
        return ''
    
    change_text = ""
    if trend['change_from_yesterday'] is not None:
        change = trend['change_from_yesterday']
        if change > 0:
            change_text = f"<span style='color: #e74c3c;'>+{change}</span> from yesterday"
        elif change < 0:
            change_text = f"<span style='color: #27ae60;'>{change}</span> from yesterday"
        else:
            change_text = "same as yesterday"
    
    return f"""
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 4px; 
                    margin: 20px 0; border-left: 4px solid #3498db;">
            <h3 style="margin: 0 0 10px 0; font-size: 16px; color: #2c3e50;">
                7-Day Trend {build_trend_badge(trend)}
            </h3>
            <p style="margin: 5px 0; font-size: 14px;">
                <strong>Average:</strong> {trend['seven_day_average']} alerts/day<br>
                <strong>Yesterday:</strong> {trend['yesterday_count']} alerts ({change_text})
            </p>
        </div>
    """


@xray_recorder.capture('format_digest_email')
def format_digest_email(
    customer_name: str,
    summary: str,
    alert_count: int,
    branding: Dict[str, str],
    trend: Dict[str, Any],
    unsubscribe_token: str
) -> str:
    """Formats the digest into a branded HTML email with trend section and unsubscribe link."""
    today = datetime.utcnow().strftime('%B %d, %Y')
    
    company_name = branding.get('company_name', 'Your MSP')
    logo_url = branding.get('logo_url', '')
    primary_color = branding.get('primary_color', '#2c3e50')
    support_email = branding.get('support_email', 'support@yourmsp.com')
    support_phone = branding.get('support_phone', '')
    
    logo_html = f'<img src="{logo_url}" alt="{company_name}" style="max-height: 50px; margin-bottom: 10px;">' if logo_url else ''
    trend_section = build_trend_section(trend)
    unsubscribe_url = f"{UNSUBSCRIBE_BASE_URL}/unsubscribe?token={unsubscribe_token}" if unsubscribe_token else '#'
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Security Digest - {today}</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; background-color: #f5f5f5;">
    <div style="background-color: {primary_color}; color: white; padding: 20px; text-align: center;">
        {logo_html}
        <h1 style="margin: 0; font-size: 24px;">Daily Security Digest</h1>
        <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">{today}</p>
    </div>
    
    <div style="padding: 20px; background-color: white;">
        <p>Dear {customer_name},</p>
        
        <p>
            Here's your daily security summary. We monitored your systems over the past 24 hours 
            and detected <strong>{alert_count} alert{'s' if alert_count != 1 else ''}</strong> 
            requiring your attention.
        </p>
        
        {trend_section}
        
        <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid {primary_color}; margin: 20px 0;">
            {summary}
        </div>
        
        <p>
            Our team continues to monitor your environment 24/7. If you have any questions 
            about this digest or need assistance, please don't hesitate to reach out.
        </p>
        
        <p>
            Best regards,<br>
            <strong>{company_name} Security Team</strong><br>
            {f'<a href="mailto:{support_email}">{support_email}</a>' if support_email else ''}
            {f'<br>{support_phone}' if support_phone else ''}
        </p>
    </div>
    
    <div style="background-color: #ecf0f1; padding: 15px; text-align: center; font-size: 12px; color: #7f8c8d;">
        <p style="margin: 0 0 10px 0;">
            This is an automated daily security digest from {company_name}.
        </p>
        <p style="margin: 0;">
            <a href="{unsubscribe_url}" style="color: #7f8c8d; text-decoration: underline;">
                Unsubscribe from these digests
            </a>
        </p>
        <p style="margin: 10px 0 0 0;">
            &copy; {datetime.utcnow().year} {company_name}. All rights reserved.
        </p>
    </div>
</body>
</html>"""
    
    return html


@xray_recorder.capture('send_digest_email')
def send_digest_email(customer_email: str, customer_name: str, html_body: str, alert_count: int):
    """Sends the digest email via SES."""
    today = datetime.utcnow().strftime('%B %d, %Y')
    subject = f"Your Daily Security Digest - {today}"
    
    try:
        ses_client.send_email(
            Source=SENDER_EMAIL,
            Destination={'ToAddresses': [customer_email]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {'Html': {'Data': html_body, 'Charset': 'UTF-8'}}
            },
            Tags=[{'Name': 'digest_type', 'Value': 'daily_security'}]
        )
        logger.info(f"Digest email sent to {customer_email} ({alert_count} alerts)")
    except ClientError as e:
        logger.error(f"Failed to send email to {customer_email}: {e}")
        raise


# ==============================================================================
# LAMBDA HANDLER
# ==============================================================================

@xray_recorder.capture('customer_digest_worker_handler')
def lambda_handler(event, context):
    """Main entry point for the customer digest worker."""
    if "Records" in event:
        failures = []
        for record in event["Records"]:
            try:
                message = json.loads(record["body"])
                process_customer(message)
            except Exception:
                logger.exception(f"Failed to process customer message: {record.get('messageId')}")
                failures.append({"itemIdentifier": record["messageId"]})
        return {"batchItemFailures": failures}
    
    try:
        process_customer(event)
        return {'statusCode': 200, 'body': 'Digest processed'}
    except Exception as e:
        logger.exception("Failed to process customer digest")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}


def process_customer(message: Dict[str, Any]):
    """Processes a single customer digest."""
    customer_id = message.get('customer_id')
    customer_email = message.get('email')
    customer_name = message.get('customer_name', 'Valued Customer')
    organization_id = message.get('organization_id')
    
    if not customer_id or not customer_email or not organization_id:
        raise ValueError(f"Missing required fields in message: {message}")
    
    xray_recorder.put_annotation('customer_id', customer_id)
    
    logger.info(f"Processing digest for customer {customer_id} ({customer_name})")
    
    alerts = get_customer_alerts(organization_id)
    
    if not alerts:
        logger.info(f"No alerts for customer {customer_id}, skipping email")
        xray_recorder.put_annotation('alerts_count', 0)
        xray_recorder.put_annotation('email_sent', False)
        return
    
    xray_recorder.put_annotation('alerts_count', len(alerts))
    
    history = get_alert_history(customer_id, days=7)
    trend = compute_trend_summary(history, len(alerts))
    
    write_alert_snapshot(customer_id, alerts)
    
    branding = get_customer_branding(customer_id)
    
    summary = generate_digest_summary(customer_name, alerts, trend)
    
    unsubscribe_token = generate_unsubscribe_token(customer_id)
    
    html_email = format_digest_email(
        customer_name=customer_name,
        summary=summary,
        alert_count=len(alerts),
        branding=branding,
        trend=trend,
        unsubscribe_token=unsubscribe_token
    )
    
    send_digest_email(customer_email, customer_name, html_email, len(alerts))
    
    xray_recorder.put_annotation('email_sent', True)
    xray_recorder.put_annotation('trend_direction', trend['trend_direction'])
    
    logger.info(f"Digest sent to customer {customer_id} with {len(alerts)} alerts, trend: {trend['trend_direction']}")