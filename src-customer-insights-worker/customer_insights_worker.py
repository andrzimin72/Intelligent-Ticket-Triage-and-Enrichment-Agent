"""
Customer Insights Worker

Generates a strategic weekly/monthly IT health report for a single customer:
1. Fetches 7-day (or 30-day) alert history from DynamoDB
2. Fetches ticket data from ConnectWise for the same period
3. Computes trend metrics (week-over-week changes, recurring patterns)
4. Calls Bedrock Sonnet to synthesize a strategic report
5. Applies customer-facing guardrail
6. Sends branded email with unsubscribe link
"""

import json
import os
import logging
import base64
import hmac
import hashlib
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from collections import Counter
import boto3
from botocore.exceptions import ClientError

from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
RMM_SECRET_NAME = os.environ.get('RMM_SECRET_NAME')
PSA_SECRET_NAME = os.environ.get('PSA_SECRET_NAME')
UNSUBSCRIBE_SECRET_NAME = os.environ.get('UNSUBSCRIBE_SECRET_NAME')
ALERT_HISTORY_TABLE = os.environ.get('ALERT_HISTORY_TABLE')
CUSTOMER_INSIGHTS_TABLE = os.environ.get('CUSTOMER_INSIGHTS_TABLE')
INSIGHTS_MODEL_ID = os.environ.get('INSIGHTS_MODEL_ID')
GUARDRAIL_ID = os.environ.get('GUARDRAIL_ID')
GUARDRAIL_VERSION = os.environ.get('GUARDRAIL_VERSION')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
HISTORY_DAYS = int(os.environ.get('HISTORY_DAYS', '7'))
UNSUBSCRIBE_BASE_URL = os.environ.get('UNSUBSCRIBE_BASE_URL')
MSP_DEFAULT_BRANDING_JSON = os.environ.get('MSP_DEFAULT_BRANDING', '{}')
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

bedrock_runtime = boto3.client('bedrock-runtime', region_name=AWS_REGION)
secrets_client = boto3.client('secretsmanager', region_name=AWS_REGION)
ses_client = boto3.client('ses', region_name=AWS_REGION)
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)

_secret_cache = {}


# =============================================================================
# HELPERS
# =============================================================================

def get_secret(secret_name: str) -> Dict[str, str]:
    if secret_name in _secret_cache:
        return _secret_cache[secret_name]
    response = secrets_client.get_secret_value(SecretId=secret_name)
    secret = json.loads(response['SecretString'])
    _secret_cache[secret_name] = secret
    return secret


def get_default_branding() -> Dict[str, str]:
    try:
        return json.loads(MSP_DEFAULT_BRANDING_JSON)
    except json.JSONDecodeError:
        return {
            'company_name': 'Your MSP',
            'logo_url': '',
            'primary_color': '#2c3e50',
            'support_email': 'support@yourmsp.com',
            'support_phone': '+1-555-0100',
        }


def get_customer_branding(customer_id: str) -> Dict[str, str]:
    defaults = get_default_branding()
    try:
        table = dynamodb.Table(CUSTOMER_INSIGHTS_TABLE)
        response = table.get_item(Key={'customer_id': customer_id})
        item = response.get('Item', {})
        customer_branding = item.get('branding', {})
        if isinstance(customer_branding, str):
            customer_branding = json.loads(customer_branding)
        return {**defaults, **{k: v for k, v in customer_branding.items() if v}}
    except Exception as e:
        logger.warning(f"Failed to fetch branding for {customer_id}: {e}")
        return defaults


def generate_unsubscribe_token(customer_id: str) -> str:
    signing_key = get_secret(UNSUBSCRIBE_SECRET_NAME).get('SIGNING_KEY')
    if not signing_key:
        return ''
    timestamp = str(int(datetime.utcnow().timestamp()))
    message = f"insights|{customer_id}|{timestamp}"
    signature = hmac.new(
        signing_key.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"insights|{customer_id}|{timestamp}|{signature}"


# =============================================================================
# DATA FETCHING
# =============================================================================

@xray_recorder.capture('fetch_alert_history')
def fetch_alert_history(customer_id: str, days: int) -> List[Dict[str, Any]]:
    """Fetches daily alert snapshots from DynamoDB for the period."""
    try:
        table = dynamodb.Table(ALERT_HISTORY_TABLE)
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        response = table.query(
            KeyConditionExpression='customer_id = :cid AND date_key BETWEEN :start AND :end',
            ExpressionAttributeValues={
                ':cid': customer_id,
                ':start': start_date.strftime('%Y-%m-%d'),
                ':end': end_date.strftime('%Y-%m-%d'),
            }
        )
        
        items = response.get('Items', [])
        items.sort(key=lambda x: x.get('date_key', ''))
        return items
    
    except ClientError as e:
        logger.warning(f"Failed to fetch alert history for {customer_id}: {e}")
        return []


@xray_recorder.capture('fetch_tickets')
def fetch_tickets(organization_id: str, days: int) -> Dict[str, Any]:
    """
    Fetches ticket data from ConnectWise for the customer.
    
    Returns: {
        'opened': [...],
        'closed': [...],
        'still_open': [...],
        'by_category': {...},
        'by_priority': {...},
        'avg_resolution_hours': float,
    }
    """
    psa_secret = get_secret(PSA_SECRET_NAME)
    base_url = psa_secret['BASE_URL'].rstrip('/')
    
    auth_string = f"{psa_secret['COMPANY_ID']}+{psa_secret['PUBLIC_KEY']}:{psa_secret['PRIVATE_KEY']}"
    auth_bytes = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
    
    headers = {
        'Authorization': f"Basic {auth_bytes}",
        'Accept': 'application/vnd.connectwise.com+json; version=v2024.1',
        'clientId': psa_secret.get('CLIENT_ID', 'InsightsWorker'),
    }
    
    start_date = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    # Fetch tickets for the customer's company
    # Note: organization_id maps to ConnectWise company ID
    conditions = f"company/id={organization_id} AND dateEntered>=[{start_date}]"
    fields = "id,summary,board,priority,status,dateEntered,dateResolved,closeDate"
    
    try:
        url = f"{base_url}/v4_6_release/apis/3.0/service/tickets?conditions={conditions}&fields={fields}&pageSize=500"
        req = urllib.request.Request(url, headers=headers, method='GET')
        with urllib.request.urlopen(req, timeout=30) as response:
            tickets = json.loads(response.read().decode('utf-8'))
        
        opened = []
        closed = []
        still_open = []
        categories = Counter()
        priorities = Counter()
        resolution_times = []
        
        for ticket in tickets:
            ticket_summary = {
                'id': ticket.get('id'),
                'summary': ticket.get('summary', ''),
                'board': ticket.get('board', {}).get('name', ''),
                'priority': ticket.get('priority', {}).get('name', ''),
                'status': ticket.get('status', {}).get('name', ''),
                'date_entered': ticket.get('dateEntered', ''),
            }
            
            opened.append(ticket_summary)
            categories[ticket_summary['board']] += 1
            priorities[ticket_summary['priority']] += 1
            
            close_date = ticket.get('closeDate') or ticket.get('dateResolved')
            if close_date:
                closed.append(ticket_summary)
                # Compute resolution time
                try:
                    opened_dt = datetime.fromisoformat(ticket_summary['date_entered'].replace('Z', '+00:00'))
                    closed_dt = datetime.fromisoformat(close_date.replace('Z', '+00:00'))
                    hours = (closed_dt - opened_dt).total_seconds() / 3600
                    resolution_times.append(hours)
                except (ValueError, TypeError):
                    pass
            else:
                still_open.append(ticket_summary)
        
        avg_resolution = (
            sum(resolution_times) / len(resolution_times) 
            if resolution_times else 0
        )
        
        return {
            'opened': opened,
            'closed': closed,
            'still_open': still_open,
            'by_category': dict(categories),
            'by_priority': dict(priorities),
            'avg_resolution_hours': round(avg_resolution, 1),
        }
    
    except Exception as e:
        logger.error(f"Failed to fetch tickets for org {organization_id}: {e}")
        return {
            'opened': [], 'closed': [], 'still_open': [],
            'by_category': {}, 'by_priority': {},
            'avg_resolution_hours': 0,
        }


@xray_recorder.capture('fetch_previous_period_tickets')
def fetch_previous_period_tickets(organization_id: str, days: int) -> Dict[str, Any]:
    """Fetches tickets from the previous period for trend comparison."""
    psa_secret = get_secret(PSA_SECRET_NAME)
    base_url = psa_secret['BASE_URL'].rstrip('/')
    
    auth_string = f"{psa_secret['COMPANY_ID']}+{psa_secret['PUBLIC_KEY']}:{psa_secret['PRIVATE_KEY']}"
    auth_bytes = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
    
    headers = {
        'Authorization': f"Basic {auth_bytes}",
        'Accept': 'application/vnd.connectwise.com+json; version=v2024.1',
        'clientId': psa_secret.get('CLIENT_ID', 'InsightsWorker'),
    }
    
    end_date = datetime.utcnow() - timedelta(days=days)
    start_date = end_date - timedelta(days=days)
    
    conditions = (
        f"company/id={organization_id} AND "
        f"dateEntered>=[{start_date.strftime('%Y-%m-%d')}] AND "
        f"dateEntered<[{end_date.strftime('%Y-%m-%d')}]"
    )
    
    try:
        url = f"{base_url}/v4_6_release/apis/3.0/service/tickets?conditions={conditions}&fields=id&pageSize=500"
        req = urllib.request.Request(url, headers=headers, method='GET')
        with urllib.request.urlopen(req, timeout=30) as response:
            tickets = json.loads(response.read().decode('utf-8'))
        
        return {
            'opened_count': len(tickets),
        }
    
    except Exception as e:
        logger.warning(f"Failed to fetch previous period tickets: {e}")
        return {'opened_count': 0}


# =============================================================================
# TREND COMPUTATION
# =============================================================================

def compute_trend_metrics(
    alert_history: List[Dict[str, Any]],
    tickets: Dict[str, Any],
    previous_tickets: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Computes trend metrics for the report.
    
    Returns a dict with:
    - total_alerts, avg_alerts_per_day, alert_trend_pct
    - tickets_opened, tickets_closed, tickets_still_open
    - ticket_trend_pct (vs previous period)
    - avg_resolution_hours
    - top_categories, top_priorities
    - recurring_issues (tickets with similar summaries)
    """
    # Alert metrics
    total_alerts = sum(day.get('alert_count', 0) for day in alert_history)
    days_with_data = len(alert_history) or 1
    avg_alerts_per_day = round(total_alerts / days_with_data, 1)
    
    # Alert trend: compare first half vs second half of period
    if len(alert_history) >= 4:
        mid = len(alert_history) // 2
        first_half = sum(d.get('alert_count', 0) for d in alert_history[:mid])
        second_half = sum(d.get('alert_count', 0) for d in alert_history[mid:])
        if first_half > 0:
            alert_trend_pct = round((second_half - first_half) / first_half * 100, 1)
        else:
            alert_trend_pct = 0 if second_half == 0 else 100.0
    else:
        alert_trend_pct = 0
    
    # Ticket metrics
    tickets_opened = len(tickets['opened'])
    tickets_closed = len(tickets['closed'])
    tickets_still_open = len(tickets['still_open'])
    
    previous_opened = previous_tickets.get('opened_count', 0)
    if previous_opened > 0:
        ticket_trend_pct = round(
            (tickets_opened - previous_opened) / previous_opened * 100, 1
        )
    else:
        ticket_trend_pct = 0 if tickets_opened == 0 else 100.0
    
    # Top categories (top 3)
    top_categories = sorted(
        tickets['by_category'].items(),
        key=lambda x: x[1],
        reverse=True
    )[:3]
    
    # Top priorities (top 3)
    top_priorities = sorted(
        tickets['by_priority'].items(),
        key=lambda x: x[1],
        reverse=True
    )[:3]
    
    # Recurring issues: tickets with similar summaries
    # Simple heuristic: group by first 3 significant words
    summary_groups = Counter()
    for ticket in tickets['opened']:
        words = [w.lower() for w in ticket['summary'].split() if len(w) > 3]
        if len(words) >= 2:
            key = ' '.join(sorted(words[:3]))
            summary_groups[key] += 1
    
    recurring = [
        {'pattern': pattern, 'count': count}
        for pattern, count in summary_groups.items()
        if count >= 2
    ][:3]
    
    return {
        'total_alerts': total_alerts,
        'avg_alerts_per_day': avg_alerts_per_day,
        'alert_trend_pct': alert_trend_pct,
        'tickets_opened': tickets_opened,
        'tickets_closed': tickets_closed,
        'tickets_still_open': tickets_still_open,
        'ticket_trend_pct': ticket_trend_pct,
        'avg_resolution_hours': tickets['avg_resolution_hours'],
        'top_categories': top_categories,
        'top_priorities': top_priorities,
        'recurring_issues': recurring,
    }


# =============================================================================
# REPORT GENERATION
# =============================================================================

@xray_recorder.capture('generate_insights_report')
def generate_insights_report(
    customer_name: str,
    period_start: str,
    period_end: str,
    metrics: Dict[str, Any],
    cadence: str,
) -> str:
    """Calls Bedrock Sonnet to generate the strategic report."""
    
    # Build the data context for the LLM
    top_cats_text = ', '.join([f"{c[0]} ({c[1]})" for c in metrics['top_categories']]) or 'None'
    top_prio_text = ', '.join([f"{p[0]} ({p[1]})" for p in metrics['top_priorities']]) or 'None'
    recurring_text = ', '.join([
        f"'{r['pattern']}' ({r['count']}x)" for r in metrics['recurring_issues']
    ]) or 'None detected'
    
    trend_arrow = lambda pct: ('↑' if pct > 5 else '↓' if pct < -5 else '→')
    
    user_prompt = f"""Generate a strategic IT health and security summary for {customer_name}.

Period: {period_start} to {period_end} ({cadence} report)

DATA:
- Total alerts this period: {metrics['total_alerts']} (avg {metrics['avg_alerts_per_day']}/day, trend: {trend_arrow(metrics['alert_trend_pct'])}{metrics['alert_trend_pct']:+.1f}% vs prior sub-period)
- Tickets opened: {metrics['tickets_opened']} (trend: {trend_arrow(metrics['ticket_trend_pct'])}{metrics['ticket_trend_pct']:+.1f}% vs previous period)
- Tickets closed: {metrics['tickets_closed']}
- Tickets still open: {metrics['tickets_still_open']}
- Average resolution time: {metrics['avg_resolution_hours']} hours
- Top ticket categories: {top_cats_text}
- Top ticket priorities: {top_prio_text}
- Recurring issue patterns: {recurring_text}

REPORT STRUCTURE (use these exact sections):
1. EXECUTIVE SUMMARY (2-3 sentences, overall health assessment)
2. KEY METRICS (brief narrative, reference the numbers above)
3. TOP ISSUES THIS PERIOD (3-5 bullet points, plain English)
4. POSITIVE HIGHLIGHTS (what went well — uptime, resolved issues, improvements)
5. RECOMMENDATIONS (2-3 actionable items based on patterns)
6. RISK INDICATORS (use 🟢 🟡 🔴 to flag status)

RULES:
- Write for a non-technical business owner
- Be honest but reassuring — don't alarm, don't minimize
- If metrics are good, celebrate them
- If metrics are bad, frame constructively with solutions
- Never include specific IP addresses, hostnames, or user names
- Never include medical, legal, or financial advice
- Keep total length under 600 words
- Use plain English, not jargon
- End with a warm note about ongoing monitoring

Return ONLY the report text, no JSON, no markdown formatting."""

    # Apply input guardrail
    input_result = apply_guardrail(user_prompt, source='INPUT')
    if input_result['action'] == 'GUARDRAIL_INTERVENED':
        if not input_result['text']:
            raise ValueError("Input guardrail blocked the request")
        user_prompt = input_result['text']
    
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": user_prompt}]
    })
    
    try:
        response = bedrock_runtime.invoke_model(
            modelId=INSIGHTS_MODEL_ID,
            body=body
        )
        response_body = json.loads(response.get('body').read())
        report_text = response_body['content'][0]['text']
        
        output_result = apply_guardrail(report_text, source='OUTPUT')
        if output_result['action'] == 'GUARDRAIL_INTERVENED':
            if not output_result['text']:
                raise ValueError("Output guardrail blocked the response")
            report_text = output_result['text']
        
        return report_text
    
    except Exception as e:
        logger.error(f"Failed to generate insights report: {e}")
        raise


def apply_guardrail(text: str, source: str = 'INPUT') -> Dict[str, Any]:
    """Applies Bedrock Guardrail to text."""
    if not GUARDRAIL_ID or not GUARDRAIL_VERSION:
        return {'action': 'NONE', 'text': text, 'assessments': []}
    
    try:
        response = bedrock_runtime.apply_guardrail(
            guardrailIdentifier=GUARDRAIL_ID,
            guardrailVersion=GUARDRAIL_VERSION,
            source=source,
            content=[{'text': {'text': text}}]
        )
        
        action = response.get('action', 'NONE')
        outputs = response.get('outputs', [])
        
        if action == 'GUARDRAIL_INTERVENED':
            if outputs:
                return {
                    'action': 'GUARDRAIL_INTERVENED_ANONYMIZE',
                    'text': outputs[0].get('text', ''),
                    'assessments': response.get('assessments', []),
                }
            else:
                return {
                    'action': 'GUARDRAIL_INTERVENED_BLOCK',
                    'text': '',
                    'assessments': response.get('assessments', []),
                }
        return {'action': 'NONE', 'text': text, 'assessments': []}
    
    except ClientError as e:
        logger.error(f"Guardrail API error: {e}")
        raise


# =============================================================================
# EMAIL FORMATTING
# =============================================================================

@xray_recorder.capture('format_insights_email')
def format_insights_email(
    customer_name: str,
    period_start: str,
    period_end: str,
    report_text: str,
    metrics: Dict[str, Any],
    branding: Dict[str, str],
    unsubscribe_token: str,
    cadence: str,
) -> str:
    """Formats the insights report into a branded HTML email."""
    
    company_name = branding.get('company_name', 'Your MSP')
    logo_url = branding.get('logo_url', '')
    primary_color = branding.get('primary_color', '#2c3e50')
    support_email = branding.get('support_email', 'support@yourmsp.com')
    support_phone = branding.get('support_phone', '')
    
    logo_html = f'<img src="{logo_url}" alt="{company_name}" style="max-height: 50px; margin-bottom: 10px;">' if logo_url else ''
    
    # Convert newlines in report to <br> and preserve structure
    report_html = report_text.replace('\n\n', '</p><p>').replace('\n', '<br>')
    report_html = f"<p>{report_html}</p>"
    
    # Trend arrows for key metrics
    def trend_html(pct: float) -> str:
        if pct > 5:
            return f'<span style="color: #e74c3c;">↑ {pct:+.1f}%</span>'
        elif pct < -5:
            return f'<span style="color: #27ae60;">↓ {pct:+.1f}%</span>'
        else:
            return f'<span style="color: #7f8c8d;">→ {pct:+.1f}%</span>'
    
    unsubscribe_url = f"{UNSUBSCRIBE_BASE_URL}/unsubscribe-insights?token={unsubscribe_token}" if unsubscribe_token else '#'
    
    cadence_label = "Weekly" if cadence == "weekly" else "Monthly"
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 700px; margin: 0 auto; background-color: #f5f5f5;">
    <div style="background-color: {primary_color}; color: white; padding: 25px; text-align: center;">
        {logo_html}
        <h1 style="margin: 0; font-size: 22px;">{cadence_label} IT Health & Security Summary</h1>
        <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">
            {customer_name} · {period_start} to {period_end}
        </p>
    </div>
    
    <div style="padding: 25px; background-color: white;">
        <div style="background-color: #f8f9fa; padding: 20px; border-radius: 6px; margin-bottom: 25px; line-height: 1.7;">
            {report_html}
        </div>
        
        <div style="background-color: #e8f4f8; padding: 15px; border-radius: 4px; margin: 20px 0; font-size: 14px;">
            <strong>Quick Reference:</strong><br>
            • Alerts this period: {metrics['total_alerts']} ({trend_html(metrics['alert_trend_pct'])})<br>
            • Tickets opened: {metrics['tickets_opened']} ({trend_html(metrics['ticket_trend_pct'])})<br>
            • Tickets resolved: {metrics['tickets_closed']}<br>
            • Avg resolution time: {metrics['avg_resolution_hours']}h
        </div>
        
        <p style="margin-top: 25px;">
            Our team continues to monitor your environment 24/7. If you have questions 
            about this report or would like to discuss any of the recommendations, 
            please don't hesitate to reach out.
        </p>
        
        <p>
            Best regards,<br>
            <strong>{company_name} Strategic IT Team</strong><br>
            {f'<a href="mailto:{support_email}">{support_email}</a>' if support_email else ''}
            {f'<br>{support_phone}' if support_phone else ''}
        </p>
    </div>
    
    <div style="background-color: #ecf0f1; padding: 15px; text-align: center; font-size: 12px; color: #7f8c8d;">
        <p style="margin: 0 0 10px 0;">
            This {cadence_label.lower()} IT Health Summary is a premium service from {company_name}.
        </p>
        <p style="margin: 0;">
            <a href="{unsubscribe_url}" style="color: #7f8c8d; text-decoration: underline;">
                Unsubscribe from these reports
            </a>
        </p>
        <p style="margin: 10px 0 0 0;">
            &copy; {datetime.utcnow().year} {company_name}. All rights reserved.
        </p>
    </div>
</body>
</html>"""


@xray_recorder.capture('send_insights_email')
def send_insights_email(
    customer_email: str,
    customer_name: str,
    html_body: str,
    period_start: str,
    period_end: str,
    cadence: str,
):
    """Sends the insights email via SES."""
    cadence_label = "Weekly" if cadence == "weekly" else "Monthly"
    subject = f"Your {cadence_label} IT Health Summary · {period_start} to {period_end}"
    
    try:
        ses_client.send_email(
            Source=SENDER_EMAIL,
            Destination={'ToAddresses': [customer_email]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {'Html': {'Data': html_body, 'Charset': 'UTF-8'}},
            },
            Tags=[{'Name': 'report_type', 'Value': 'customer_insights'}],
        )
        logger.info(f"Insights email sent to {customer_email}")
    except ClientError as e:
        logger.error(f"Failed to send email to {customer_email}: {e}")
        raise


# =============================================================================
# MAIN PROCESSING
# =============================================================================

def process_customer(message: Dict[str, Any]):
    """Generates and sends an insights report for a single customer."""
    customer_id = message.get('customer_id')
    customer_email = message.get('email')
    customer_name = message.get('customer_name', 'Valued Customer')
    organization_id = message.get('organization_id')
    cadence = message.get('report_cadence', 'weekly')
    
    if not customer_id or not customer_email or not organization_id:
        raise ValueError(f"Missing required fields in message: {message}")
    
    xray_recorder.put_annotation('customer_id', customer_id)
    xray_recorder.put_annotation('cadence', cadence)
    
    logger.info(f"Generating insights report for {customer_name} ({customer_id})")
    
    # Determine period based on cadence
    days = HISTORY_DAYS if cadence == 'weekly' else 30
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    period_start = start_date.strftime('%b %d')
    period_end = end_date.strftime('%b %d, %Y')
    
    # Fetch data
    alert_history = fetch_alert_history(customer_id, days)
    tickets = fetch_tickets(organization_id, days)
    previous_tickets = fetch_previous_period_tickets(organization_id, days)
    
    # Skip if no data at all
    if not alert_history and not tickets['opened']:
        logger.info(f"No data for customer {customer_id}, skipping report")
        xray_recorder.put_annotation('skipped', True)
        return
    
    # Compute trend metrics
    metrics = compute_trend_metrics(alert_history, tickets, previous_tickets)
    
    xray_recorder.put_annotation('alerts_count', metrics['total_alerts'])
    xray_recorder.put_annotation('tickets_opened', metrics['tickets_opened'])
    
    # Generate strategic report via Sonnet
    report_text = generate_insights_report(
        customer_name=customer_name,
        period_start=period_start,
        period_end=period_end,
        metrics=metrics,
        cadence=cadence,
    )
    
    # Get branding
    branding = get_customer_branding(customer_id)
    
    # Generate unsubscribe token
    unsubscribe_token = generate_unsubscribe_token(customer_id)
    
    # Format and send email
    html_email = format_insights_email(
        customer_name=customer_name,
        period_start=period_start,
        period_end=period_end,
        report_text=report_text,
        metrics=metrics,
        branding=branding,
        unsubscribe_token=unsubscribe_token,
        cadence=cadence,
    )
    
    send_insights_email(
        customer_email=customer_email,
        customer_name=customer_name,
        html_body=html_email,
        period_start=period_start,
        period_end=period_end,
        cadence=cadence,
    )
    
    # Update last_report_date in preferences table
    try:
        table = dynamodb.Table(CUSTOMER_INSIGHTS_TABLE)
        table.update_item(
            Key={'customer_id': customer_id},
            UpdateExpression='SET last_report_date = :d',
            ExpressionAttributeValues={':d': datetime.utcnow().isoformat()},
        )
    except ClientError as e:
        logger.warning(f"Failed to update last_report_date for {customer_id}: {e}")
    
    xray_recorder.put_annotation('email_sent', True)
    logger.info(f"Insights report sent to {customer_name}")


@xray_recorder.capture('insights_worker_handler')
def lambda_handler(event, context):
    """Main entry point for the insights worker."""
    if "Records" in event:
        failures = []
        for record in event["Records"]:
            try:
                message = json.loads(record["body"])
                process_customer(message)
            except Exception:
                logger.exception(f"Failed to process insights for message {record.get('messageId')}")
                failures.append({"itemIdentifier": record["messageId"]})
        return {"batchItemFailures": failures}
    
    try:
        process_customer(event)
        return {'statusCode': 200, 'body': 'Report generated'}
    except Exception as e:
        logger.exception("Failed to generate insights report")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}
