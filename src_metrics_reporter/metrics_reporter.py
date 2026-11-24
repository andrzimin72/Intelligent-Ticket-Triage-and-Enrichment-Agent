"""
Weekly Metrics Reporter (Phase 2: Tenant-Scoped Agent Feedback)

Queries the metrics table, feedback table, agent feedback table, and ConnectWise 
to calculate AI accuracy, override rates, fallback usage, retry statistics, 
complexity distribution, cost savings, guardrail effectiveness, feedback loop 
status, and agent feedback statistics with per-tenant breakdown.

Sends a formatted HTML email report to leadership every Monday.

Schedule: Weekly via EventBridge (Monday 8 AM UTC)
"""

import json
import os
import logging
import base64
import urllib.request
from datetime import datetime, timedelta
from typing import Dict, Any, List
from collections import Counter
import boto3
from botocore.exceptions import ClientError

# X-Ray SDK
from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
METRICS_TABLE = os.environ.get('METRICS_TABLE')
FEEDBACK_TABLE = os.environ.get('FEEDBACK_TABLE')
AGENT_FEEDBACK_TABLE = os.environ.get('AGENT_FEEDBACK_TABLE')
TENANT_REGISTRY_TABLE = os.environ.get('TENANT_REGISTRY_TABLE')  # NEW
PSA_SECRET_NAME = os.environ.get('PSA_SECRET_NAME')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
RECIPIENT_EMAIL = os.environ.get('RECIPIENT_EMAIL')
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')
AI_ACCURACY_FIELD_ID = int(os.environ.get('AI_ACCURACY_FIELD_ID', '999'))

# Initialize clients
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
secrets_client = boto3.client('secretsmanager', region_name=AWS_REGION)
ses_client = boto3.client('ses', region_name=AWS_REGION)

_secret_cache = {}


# =============================================================================
# SECRETS & API HELPERS
# =============================================================================

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


def make_api_request(url: str, headers: Dict[str, str], method: str = 'GET') -> Any:
    """Makes an HTTP request and returns the parsed JSON response."""
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        logger.error(f"API request failed: {e}")
        raise


# =============================================================================
# TENANT LOOKUP (NEW)
# =============================================================================

def get_tenant_display_name(tenant_id: str) -> str:
    """
    Looks up the display name for a tenant.
    
    Falls back to the tenant_id itself if the registry is unavailable
    or the tenant is not found.
    """
    if not TENANT_REGISTRY_TABLE:
        return tenant_id
    
    try:
        table = dynamodb.Table(TENANT_REGISTRY_TABLE)
        response = table.get_item(Key={'tenant_id': tenant_id})
        item = response.get('Item')
        
        if item and item.get('display_name'):
            return item['display_name']
        
        return tenant_id
    
    except ClientError as e:
        logger.warning(f"Failed to lookup tenant display name for {tenant_id}: {e}")
        return tenant_id


# =============================================================================
# DATA FETCHING
# =============================================================================

@xray_recorder.capture('get_weekly_metrics')
def get_weekly_metrics() -> List[Dict[str, Any]]:
    """Queries DynamoDB for all metrics records from the past 7 days."""
    table = dynamodb.Table(METRICS_TABLE)
    
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=7)
    
    response = table.scan(
        FilterExpression='#ts >= :start_date AND #ts <= :end_date',
        ExpressionAttributeNames={'#ts': 'timestamp'},
        ExpressionAttributeValues={
            ':start_date': start_date.isoformat(),
            ':end_date': end_date.isoformat()
        }
    )
    
    return response.get('Items', [])


@xray_recorder.capture('get_connectwise_ticket_feedback')
def get_connectwise_ticket_feedback(ticket_ids: List[str]) -> Dict[str, str]:
    """Fetches AI accuracy feedback from ConnectWise for the given ticket IDs."""
    psa_secret = get_secret(PSA_SECRET_NAME)
    base_url = psa_secret['BASE_URL'].rstrip('/')
    
    auth_string = f"{psa_secret['COMPANY_ID']}+{psa_secret['PUBLIC_KEY']}:{psa_secret['PRIVATE_KEY']}"
    auth_bytes = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
    
    headers = {
        'Authorization': f"Basic {auth_bytes}",
        'Accept': 'application/vnd.connectwise.com+json; version=v2024.1',
        'clientId': psa_secret.get('CLIENT_ID', 'MetricsReporter')
    }
    
    feedback_map = {}
    
    for ticket_id in ticket_ids:
        try:
            url = f"{base_url}/v4_6_release/apis/3.0/service/tickets/{ticket_id}?fields=id,customFields"
            ticket_data = make_api_request(url, headers)
            
            for field in ticket_data.get('customFields', []):
                if field.get('id') == AI_ACCURACY_FIELD_ID:
                    feedback_map[ticket_id] = field.get('value', 'Not Set')
                    break
        except Exception as e:
            logger.warning(f"Failed to fetch feedback for ticket {ticket_id}: {e}")
    
    return feedback_map


@xray_recorder.capture('get_pending_feedback_count')
def get_pending_feedback_count() -> int:
    """Counts pending ticket triage feedback records awaiting review."""
    if not FEEDBACK_TABLE:
        return 0
    
    try:
        table = dynamodb.Table(FEEDBACK_TABLE)
        response = table.query(
            IndexName='status-index',
            KeyConditionExpression='#s = :status',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':status': 'pending_review'},
            Select='COUNT'
        )
        return response.get('Count', 0)
    except Exception as e:
        logger.warning(f"Failed to count pending ticket feedback: {e}")
        return 0


@xray_recorder.capture('get_agent_feedback_stats')
def get_agent_feedback_stats() -> Dict[str, Any]:
    """
    Calculates agent feedback statistics from the agent feedback table.
    
    Phase 2: Now returns per-tenant breakdown in addition to aggregate stats.
    """
    if not AGENT_FEEDBACK_TABLE:
        return {
            'total_feedback': 0,
            'pending_count': 0,
            'thumbs_up_count': 0,
            'thumbs_down_count': 0,
            'approval_rate': 0,
            'error_categories': {},
            'per_tenant': {},
        }
    
    try:
        table = dynamodb.Table(AGENT_FEEDBACK_TABLE)
        
        # Get all feedback from the past 7 days
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=7)
        
        response = table.scan(
            FilterExpression='#ts >= :start_date AND #ts <= :end_date',
            ExpressionAttributeNames={'#ts': 'created_at'},
            ExpressionAttributeValues={
                ':start_date': start_date.isoformat(),
                ':end_date': end_date.isoformat()
            }
        )
        
        items = response.get('Items', [])
        
        # Aggregate stats
        thumbs_up = sum(1 for item in items if item.get('feedback_type') == 'thumbs_up')
        thumbs_down = sum(1 for item in items if item.get('feedback_type') == 'thumbs_down')
        pending = sum(1 for item in items if item.get('status') == 'pending_review')
        
        total_rated = thumbs_up + thumbs_down
        approval_rate = (thumbs_up / total_rated * 100) if total_rated > 0 else 0
        
        # Error category breakdown
        categories = {}
        for item in items:
            if item.get('feedback_type') == 'thumbs_down':
                cat = item.get('error_category', 'unknown')
                categories[cat] = categories.get(cat, 0) + 1
        
        # Per-tenant breakdown (NEW)
        per_tenant = {}
        for item in items:
            tid = item.get('tenant_id', 'unknown')
            if tid not in per_tenant:
                per_tenant[tid] = {
                    'total': 0,
                    'thumbs_up': 0,
                    'thumbs_down': 0,
                    'pending': 0,
                }
            per_tenant[tid]['total'] += 1
            if item.get('feedback_type') == 'thumbs_up':
                per_tenant[tid]['thumbs_up'] += 1
            elif item.get('feedback_type') == 'thumbs_down':
                per_tenant[tid]['thumbs_down'] += 1
            if item.get('status') == 'pending_review':
                per_tenant[tid]['pending'] += 1
        
        return {
            'total_feedback': len(items),
            'pending_count': pending,
            'thumbs_up_count': thumbs_up,
            'thumbs_down_count': thumbs_down,
            'approval_rate': approval_rate,
            'error_categories': categories,
            'per_tenant': per_tenant,
        }
    
    except Exception as e:
        logger.warning(f"Failed to calculate agent feedback stats: {e}")
        return {
            'total_feedback': 0,
            'pending_count': 0,
            'thumbs_up_count': 0,
            'thumbs_down_count': 0,
            'approval_rate': 0,
            'error_categories': {},
            'per_tenant': {},
        }


# =============================================================================
# METRICS CALCULATION
# =============================================================================

@xray_recorder.capture('calculate_metrics')
def calculate_metrics(metrics_records: List[Dict[str, Any]], feedback_map: Dict[str, str]) -> Dict[str, Any]:
    """
    Calculates aggregate metrics from the raw records.
    
    Includes:
    - Core metrics (total tickets, accuracy, confidence, processing time)
    - Guardrail effectiveness (anonymizations, blocks, block rate)
    - Resilience metrics (fallback usage, retry counts)
    - Cost optimization metrics (Haiku routing, savings)
    - Ticket triage feedback loop status
    - Agent feedback loop statistics (with per-tenant breakdown)
    - Complexity distribution
    - Model distribution
    """
    if not metrics_records:
        return {
            'total_tickets': 0,
            'accuracy_rate': 0,
            'avg_confidence': 0,
            'avg_processing_time_ms': 0,
            'guardrail_anonymizations': 0,
            'guardrail_blocks': 0,
            'guardrail_block_rate': 0,
            'top_categories': [],
            'feedback_breakdown': {},
            'tickets_with_feedback': 0,
            'tickets_without_feedback': 0,
            'fallback_usage': 0,
            'fallback_percentage': 0,
            'avg_retries': 0,
            'model_distribution': {},
            'complexity_distribution': {},
            'haiku_tickets': 0,
            'haiku_savings_estimate_usd': 0,
            'haiku_safety_net_count': 0,
            'pending_feedback_count': 0,
            'agent_feedback': {
                'total_feedback': 0,
                'pending_count': 0,
                'thumbs_up_count': 0,
                'thumbs_down_count': 0,
                'approval_rate': 0,
                'error_categories': {},
                'per_tenant': {},
            },
        }
    
    total = len(metrics_records)
    
    # Confidence scores
    confidence_scores = [r.get('ai_confidence_score', 0) for r in metrics_records]
    avg_confidence = sum(confidence_scores) / total
    
    # Processing time
    processing_times = [r.get('processing_duration_ms', 0) for r in metrics_records]
    avg_processing_time = sum(processing_times) / total
    
    # Guardrail effectiveness
    total_anonymizations = sum(
        r.get('guardrail_interventions', 0) or r.get('guardrail_anonymizations', 0)
        for r in metrics_records
    )
    total_blocks = sum(r.get('guardrail_blocks', 0) for r in metrics_records)
    block_rate = (total_blocks / (total_blocks + total) * 100) if (total_blocks + total) > 0 else 0
    
    # Category distribution
    categories = [r.get('ai_category', 'Unknown') for r in metrics_records]
    category_counts = Counter(categories)
    top_categories = category_counts.most_common(5)
    
    # Feedback breakdown
    feedback_counts = Counter(feedback_map.values())
    correct_count = feedback_counts.get('Correct', 0)
    incorrect_count = feedback_counts.get('Incorrect', 0)
    total_feedback = correct_count + incorrect_count
    accuracy_rate = (correct_count / total_feedback * 100) if total_feedback > 0 else 0
    
    # Fallback and retry statistics
    fallback_count = sum(1 for r in metrics_records if r.get('fallback_triggered', False))
    retry_counts = [r.get('retry_count', 0) for r in metrics_records]
    avg_retries = sum(retry_counts) / total
    
    # Model distribution
    model_counts = Counter([r.get('model_id_used', 'unknown') for r in metrics_records])
    
    # Complexity distribution
    complexity_counts = Counter([r.get('complexity', 'unknown') for r in metrics_records])
    
    # Cost savings estimate
    haiku_tickets = sum(
        1 for r in metrics_records 
        if 'haiku' in r.get('model_id_used', '').lower()
    )
    estimated_savings_per_haiku_ticket = 0.01
    haiku_savings = haiku_tickets * estimated_savings_per_haiku_ticket
    
    # Count tickets where safety net triggered
    haiku_safety_net_count = sum(
        1 for r in metrics_records 
        if r.get('haiku_safety_net_triggered', False)
    )
    
    # Pending feedback count (ticket triage)
    pending_feedback_count = get_pending_feedback_count()
    
    # Agent feedback statistics (with per-tenant breakdown)
    agent_feedback_stats = get_agent_feedback_stats()
    
    return {
        'total_tickets': total,
        'accuracy_rate': accuracy_rate,
        'avg_confidence': avg_confidence,
        'avg_processing_time_ms': avg_processing_time,
        'guardrail_anonymizations': total_anonymizations,
        'guardrail_blocks': total_blocks,
        'guardrail_block_rate': block_rate,
        'top_categories': top_categories,
        'feedback_breakdown': dict(feedback_counts),
        'tickets_with_feedback': total_feedback,
        'tickets_without_feedback': total - total_feedback,
        'fallback_usage': fallback_count,
        'fallback_percentage': (fallback_count / total * 100) if total > 0 else 0,
        'avg_retries': avg_retries,
        'model_distribution': dict(model_counts),
        'complexity_distribution': dict(complexity_counts),
        'haiku_tickets': haiku_tickets,
        'haiku_savings_estimate_usd': haiku_savings,
        'haiku_safety_net_count': haiku_safety_net_count,
        'pending_feedback_count': pending_feedback_count,
        'agent_feedback': agent_feedback_stats,
    }


# =============================================================================
# EMAIL FORMATTING
# =============================================================================

def format_email_report(metrics: Dict[str, Any], start_date: datetime, end_date: datetime) -> str:
    """Formats the metrics into an HTML email."""
    feedback_table_name = FEEDBACK_TABLE or 'feedback-table-not-configured'
    agent_feedback_table_name = AGENT_FEEDBACK_TABLE or 'agent-feedback-table-not-configured'
    
    # Agent feedback section (with per-tenant breakdown)
    agent_feedback = metrics.get('agent_feedback', {})
    agent_feedback_section = ""
    
    if agent_feedback.get('total_feedback', 0) > 0:
        # Build error categories table
        error_cats_html = ""
        for category, count in agent_feedback.get('error_categories', {}).items():
            error_cats_html += f"""
                <tr>
                    <td>{category}</td>
                    <td>{count}</td>
                </tr>
            """
        
        if error_cats_html:
            error_cats_html = f"""
                <h3 style="margin-top: 20px; font-size: 16px; color: #2c3e50;">Error Category Breakdown</h3>
                <table>
                    <tr>
                        <th>Error Category</th>
                        <th>Count</th>
                    </tr>
                    {error_cats_html}
                </table>
            """
        
        # Build per-tenant table (NEW)
        per_tenant_html = ""
        per_tenant = agent_feedback.get('per_tenant', {})
        if per_tenant:
            per_tenant_rows = ""
            for tid, stats in per_tenant.items():
                # Look up display name for the tenant
                display_name = get_tenant_display_name(tid)
                
                tenant_approval = 0
                total_rated = stats['thumbs_up'] + stats['thumbs_down']
                if total_rated > 0:
                    tenant_approval = (stats['thumbs_up'] / total_rated) * 100
                
                per_tenant_rows += f"""
                    <tr>
                        <td>{display_name}</td>
                        <td>{stats['total']}</td>
                        <td>{stats['thumbs_up']}</td>
                        <td>{stats['thumbs_down']}</td>
                        <td>{tenant_approval:.1f}%</td>
                        <td>{stats['pending']}</td>
                    </tr>
                """
            
            per_tenant_html = f"""
                <h3 style="margin-top: 20px; font-size: 16px; color: #2c3e50;">Per-Tenant Breakdown</h3>
                <table>
                    <tr>
                        <th>Tenant</th>
                        <th>Total Feedback</th>
                        <th>Thumbs Up</th>
                        <th>Thumbs Down</th>
                        <th>Approval Rate</th>
                        <th>Pending</th>
                    </tr>
                    {per_tenant_rows}
                </table>
            """
        
        agent_feedback_section = f"""
            <h2>Agent Feedback Loop</h2>
            
            <div class="metric">
                <div class="metric-value neutral">{agent_feedback.get('total_feedback', 0)}</div>
                <div class="metric-label">Total Agent Feedback (past 7 days)</div>
            </div>
            
            <div class="metric">
                <div class="metric-value success">{agent_feedback.get('thumbs_up_count', 0)}</div>
                <div class="metric-label">Thumbs Up (positive feedback)</div>
            </div>
            
            <div class="metric">
                <div class="metric-value {'warning' if agent_feedback.get('thumbs_down_count', 0) > 10 else 'neutral'}">
                    {agent_feedback.get('thumbs_down_count', 0)}
                </div>
                <div class="metric-label">Thumbs Down (needs improvement)</div>
            </div>
            
            <div class="metric">
                <div class="metric-value {'success' if agent_feedback.get('approval_rate', 0) >= 80 else 'warning' if agent_feedback.get('approval_rate', 0) > 0 else 'neutral'}">
                    {agent_feedback.get('approval_rate', 0):.1f}%
                </div>
                <div class="metric-label">Agent Approval Rate (thumbs up / total rated)</div>
            </div>
            
            <div class="metric">
                <div class="metric-value {'warning' if agent_feedback.get('pending_count', 0) > 10 else 'neutral'}">
                    {agent_feedback.get('pending_count', 0)}
                </div>
                <div class="metric-label">Pending Agent Feedback Awaiting Review</div>
            </div>
            
            {error_cats_html}
            
            {per_tenant_html}
            
            <p style="margin-top: 15px;">
                <strong>Review pending agent feedback:</strong><br>
                <a href="https://console.aws.amazon.com/dynamodbv2/home?region={AWS_REGION}#table?name={agent_feedback_table_name}" 
                   style="color: #3498db;">
                   Open Agent Feedback Table in AWS Console →
                </a>
            </p>
            
            <p style="margin-top: 15px; font-size: 13px; color: #7f8c8d;">
                <strong>How to approve agent feedback:</strong><br>
                1. Click the link above to open the agent feedback table<br>
                2. Find records with status = "pending_review"<br>
                3. Review the user_message, agent_response, and correction_text fields<br>
                4. Update the status field to "approved" (or "rejected" if the feedback is invalid)<br>
                5. The daily sync will automatically add approved feedback to the tenant's few-shot examples
            </p>
        """
    
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .header {{ background-color: #2c3e50; color: white; padding: 20px; }}
            .metric {{ margin: 15px 0; padding: 15px; background-color: #f8f9fa; border-left: 4px solid #3498db; }}
            .metric-value {{ font-size: 24px; font-weight: bold; color: #2c3e50; }}
            .metric-label {{ font-size: 14px; color: #7f8c8d; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
            th {{ background-color: #3498db; color: white; }}
            .warning {{ color: #e74c3c; }}
            .success {{ color: #27ae60; }}
            .neutral {{ color: #2c3e50; }}
            .info-box {{ background-color: #e3f2fd; padding: 15px; border-radius: 4px; margin: 20px 0; border-left: 4px solid #2196f3; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>AI Triage Weekly Report</h1>
            <p>Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}</p>
        </div>
        
        <h2>Core Metrics</h2>
        
        <div class="metric">
            <div class="metric-value neutral">{metrics['total_tickets']}</div>
            <div class="metric-label">Total Tickets Processed</div>
        </div>
        
        <div class="metric">
            <div class="metric-value {'success' if metrics['accuracy_rate'] >= 80 else 'warning' if metrics['accuracy_rate'] > 0 else 'neutral'}">
                {metrics['accuracy_rate']:.1f}%
            </div>
            <div class="metric-label">AI Accuracy Rate (based on {metrics['tickets_with_feedback']} feedback responses)</div>
        </div>
        
        <div class="metric">
            <div class="metric-value neutral">{metrics['avg_confidence']:.2f}</div>
            <div class="metric-label">Average Confidence Score</div>
        </div>
        
        <div class="metric">
            <div class="metric-value neutral">{metrics['avg_processing_time_ms'] / 1000:.1f}s</div>
            <div class="metric-label">Average Processing Time</div>
        </div>
        
        <h2>Guardrail Effectiveness</h2>
        
        <div class="metric">
            <div class="metric-value neutral">{metrics['guardrail_anonymizations']}</div>
            <div class="metric-label">PII Anonymizations (content sanitized and processed)</div>
        </div>
        
        <div class="metric">
            <div class="metric-value {'warning' if metrics['guardrail_blocks'] > 10 else 'neutral'}">
                {metrics['guardrail_blocks']}
            </div>
            <div class="metric-label">Content Blocks (tickets rejected due to sensitive content)</div>
        </div>
        
        <div class="metric">
            <div class="metric-value {'warning' if metrics['guardrail_block_rate'] > 5 else 'neutral'}">
                {metrics['guardrail_block_rate']:.1f}%
            </div>
            <div class="metric-label">Block Rate (percentage of tickets blocked by guardrail)</div>
        </div>
        
        <div class="info-box">
            <strong>Note:</strong> PII anonymizations represent tickets where sensitive content was detected 
            and sanitized before processing. Content blocks represent tickets where the guardrail detected 
            content that could not be safely processed (e.g., severe PII violations, prompt injection attempts). 
            A high block rate may indicate customers are sending sensitive data via email that should be 
            transmitted through secure channels instead.
        </div>
        
        <h2>Resilience Metrics</h2>
        
        <div class="metric">
            <div class="metric-value {'warning' if metrics['fallback_percentage'] > 10 else 'success'}">
                {metrics['fallback_percentage']:.1f}%
            </div>
            <div class="metric-label">Fallback Model Usage ({metrics['fallback_usage']} tickets)</div>
        </div>
        
        <div class="metric">
            <div class="metric-value neutral">{metrics['avg_retries']:.2f}</div>
            <div class="metric-label">Average Retry Count per Ticket</div>
        </div>
        
        <h2>Cost Optimization</h2>
        
        <div class="metric">
            <div class="metric-value success">${metrics.get('haiku_savings_estimate_usd', 0):.2f}</div>
            <div class="metric-label">Estimated Weekly Savings from Haiku Routing</div>
        </div>
        
        <div class="metric">
            <div class="metric-value neutral">{metrics.get('haiku_tickets', 0)}</div>
            <div class="metric-label">Tickets Processed by Haiku (cheaper model)</div>
        </div>
        
        <div class="metric">
            <div class="metric-value {'warning' if metrics.get('haiku_safety_net_count', 0) > 10 else 'neutral'}">
                {metrics.get('haiku_safety_net_count', 0)}
            </div>
            <div class="metric-label">Haiku Safety Net Triggered (re-run with Sonnet due to low confidence)</div>
        </div>
        
        <h2>Ticket Triage Feedback Loop</h2>
        
        <div class="metric">
            <div class="metric-value {'warning' if metrics.get('pending_feedback_count', 0) > 20 else 'neutral'}">
                {metrics.get('pending_feedback_count', 0)}
            </div>
            <div class="metric-label">Pending Ticket Corrections Awaiting Review</div>
        </div>
        
        <p style="margin-top: 15px;">
            <strong>Review pending ticket corrections:</strong><br>
            <a href="https://console.aws.amazon.com/dynamodbv2/home?region={AWS_REGION}#table?name={feedback_table_name}" 
               style="color: #3498db;">
               Open Ticket Feedback Table in AWS Console →
            </a>
        </p>
        
        {agent_feedback_section}
        
        <h2>Model Distribution</h2>
        <table>
            <tr>
                <th>Model</th>
                <th>Tickets Processed</th>
                <th>Percentage</th>
            </tr>
    """
    
    for model_id, count in metrics['model_distribution'].items():
        percentage = (count / metrics['total_tickets'] * 100) if metrics['total_tickets'] > 0 else 0
        html += f"""
            <tr>
                <td>{model_id}</td>
                <td>{count}</td>
                <td>{percentage:.1f}%</td>
            </tr>
        """
    
    html += """
        </table>
        
        <h2>Ticket Complexity Distribution</h2>
        <table>
            <tr>
                <th>Complexity</th>
                <th>Count</th>
                <th>Percentage</th>
            </tr>
    """
    
    for complexity, count in metrics.get('complexity_distribution', {}).items():
        percentage = (count / metrics['total_tickets'] * 100) if metrics['total_tickets'] > 0 else 0
        html += f"""
            <tr>
                <td>{complexity}</td>
                <td>{count}</td>
                <td>{percentage:.1f}%</td>
            </tr>
        """
    
    html += """
        </table>
        
        <h2>Top Categories</h2>
        <table>
            <tr>
                <th>Category</th>
                <th>Count</th>
                <th>Percentage</th>
            </tr>
    """
    
    for category, count in metrics['top_categories']:
        percentage = (count / metrics['total_tickets'] * 100) if metrics['total_tickets'] > 0 else 0
        html += f"""
            <tr>
                <td>{category}</td>
                <td>{count}</td>
                <td>{percentage:.1f}%</td>
            </tr>
        """
    
    html += """
        </table>
        
        <h2>Technician Feedback Breakdown</h2>
        <table>
            <tr>
                <th>Feedback</th>
                <th>Count</th>
            </tr>
    """
    
    for feedback, count in metrics['feedback_breakdown'].items():
        html += f"""
            <tr>
                <td>{feedback}</td>
                <td>{count}</td>
            </tr>
        """
    
    html += f"""
        </table>
        
        <p style="margin-top: 30px; color: #7f8c8d; font-size: 12px;">
            Note: {metrics['tickets_without_feedback']} tickets did not receive technician feedback.
            Encourage technicians to set the "AI Accuracy" field to improve reporting accuracy.
        </p>
        
        <p style="margin-top: 20px;">
            <strong>Next Steps:</strong><br>
            - Review tickets marked as "Incorrect" to identify patterns<br>
            - If fallback usage is above 10%, investigate primary model stability<br>
            - If average retries are above 0.5, check Bedrock throttling limits<br>
            - If Haiku safety net triggers frequently, consider tuning the complexity classifier<br>
            - If guardrail block rate is above 5%, educate customers on secure data transmission<br>
            - <strong>Review pending ticket feedback corrections</strong> to improve triage quality<br>
            - <strong>Review pending agent feedback</strong> to improve agent behavior<br>
            - Ensure technicians are providing feedback on AI categorizations
        </p>
    </body>
    </html>
    """
    
    return html


# =============================================================================
# EMAIL SENDING
# =============================================================================

def send_email(subject: str, html_body: str):
    """Sends the email report via SES."""
    try:
        ses_client.send_email(
            Source=SENDER_EMAIL,
            Destination={'ToAddresses': [RECIPIENT_EMAIL]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Html': {'Data': html_body, 'Charset': 'UTF-8'}
                }
            }
        )
        logger.info(f"Email sent successfully to {RECIPIENT_EMAIL}")
    except ClientError as e:
        logger.error(f"Failed to send email: {e}")
        raise


# =============================================================================
# LAMBDA HANDLER
# =============================================================================

@xray_recorder.capture('metrics_reporter_handler')
def lambda_handler(event, context):
    """Main entry point for the weekly metrics reporter."""
    try:
        logger.info("Starting weekly metrics report generation")
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=7)
        
        metrics_records = get_weekly_metrics()
        logger.info(f"Fetched {len(metrics_records)} metrics records")
        
        xray_recorder.put_annotation('metrics_records_count', len(metrics_records))
        
        if not metrics_records:
            logger.info("No metrics records found for the past week, skipping report")
            return {'statusCode': 200, 'body': 'No data'}
        
        ticket_ids = [r['ticket_id'] for r in metrics_records]
        feedback_map = get_connectwise_ticket_feedback(ticket_ids)
        logger.info(f"Fetched feedback for {len(feedback_map)} tickets")
        
        metrics = calculate_metrics(metrics_records, feedback_map)
        
        html_report = format_email_report(metrics, start_date, end_date)
        subject = f"AI Triage Weekly Report: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        send_email(subject, html_report)
        
        logger.info("Weekly metrics report sent successfully")
        return {'statusCode': 200, 'body': 'Report sent'}
    
    except Exception as e:
        xray_recorder.put_annotation('error', True)
        xray_recorder.put_metadata('error_message', str(e))
        logger.exception("Failed to generate weekly metrics report")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}