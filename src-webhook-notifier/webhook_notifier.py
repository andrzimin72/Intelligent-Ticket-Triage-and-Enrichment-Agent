"""
Webhook Notifier Lambda (with Analytics Tracking)

Detects status changes between snapshots and sends notifications to
configured webhooks (Slack, Teams, PagerDuty).

Triggered by:
- Status history snapshot Lambda (after each daily snapshot)
- Manual invocation for testing

Features:
- Per-tenant webhook configuration
- Cooldown to prevent alert fatigue
- Platform-specific message formatting
- Retry with exponential backoff
- Delivery tracking to webhook_delivery_log table (Analytics)
"""

import json
import os
import logging
import time
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import boto3
from botocore.exceptions import ClientError

from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# =============================================================================
# CONFIGURATION
# =============================================================================

WEBHOOK_CONFIGS_TABLE = os.environ.get('WEBHOOK_CONFIGS_TABLE')
WEBHOOK_COOLDOWNS_TABLE = os.environ.get('WEBHOOK_COOLDOWNS_TABLE')
STATUS_HISTORY_TABLE = os.environ.get('STATUS_HISTORY_TABLE')
WEBHOOK_URLS_SECRET = os.environ.get('WEBHOOK_URLS_SECRET')
COOLDOWN_SECONDS = int(os.environ.get('COOLDOWN_SECONDS', '3600'))
RETRY_ATTEMPTS = int(os.environ.get('RETRY_ATTEMPTS', '3'))
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

# Analytics tracking (NEW)
WEBHOOK_DELIVERY_LOG_TABLE = os.environ.get('WEBHOOK_DELIVERY_LOG_TABLE', '')
RETENTION_DAYS = int(os.environ.get('RETENTION_DAYS', '365'))

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
secrets_client = boto3.client('secretsmanager', region_name=AWS_REGION)

_webhook_urls_cache: Optional[Dict[str, str]] = None


# =============================================================================
# HELPERS
# =============================================================================

def get_webhook_urls() -> Dict[str, str]:
    """Fetches webhook URLs from Secrets Manager (cached in memory)."""
    global _webhook_urls_cache
    if _webhook_urls_cache is not None:
        return _webhook_urls_cache
    
    try:
        response = secrets_client.get_secret_value(SecretId=WEBHOOK_URLS_SECRET)
        _webhook_urls_cache = json.loads(response['SecretString'])
        return _webhook_urls_cache
    except Exception as e:
        logger.error(f"Failed to fetch webhook URLs: {e}")
        return {}


def get_tenant_webhooks(tenant_id: str) -> List[Dict[str, Any]]:
    """Gets webhook configurations for a tenant."""
    try:
        table = dynamodb.Table(WEBHOOK_CONFIGS_TABLE)
        response = table.query(
            KeyConditionExpression='tenant_id = :tid',
            ExpressionAttributeValues={':tid': tenant_id}
        )
        return response.get('Items', [])
    except Exception as e:
        logger.error(f"Failed to get webhooks for tenant {tenant_id}: {e}")
        return []


def is_in_cooldown(tenant_id: str, issue_type: str) -> bool:
    """Checks if an alert for this tenant+issue is still in cooldown."""
    cooldown_key = f"{tenant_id}#{issue_type}"
    try:
        table = dynamodb.Table(WEBHOOK_COOLDOWNS_TABLE)
        response = table.get_item(Key={'cooldown_key': cooldown_key})
        item = response.get('Item')
        
        if not item:
            return False
        
        last_alert = item.get('last_alert_at', 0)
        return (time.time() - last_alert) < COOLDOWN_SECONDS
    except Exception as e:
        logger.warning(f"Failed to check cooldown: {e}")
        return False


def set_cooldown(tenant_id: str, issue_type: str) -> None:
    """Sets cooldown for a tenant+issue."""
    cooldown_key = f"{tenant_id}#{issue_type}"
    try:
        table = dynamodb.Table(WEBHOOK_COOLDOWNS_TABLE)
        table.put_item(Item={
            'cooldown_key': cooldown_key,
            'last_alert_at': int(time.time()),
            'ttl': int(time.time()) + COOLDOWN_SECONDS * 2,
        })
    except Exception as e:
        logger.warning(f"Failed to set cooldown: {e}")


def get_previous_snapshot(tenant_id: str, current_date: str) -> Optional[Dict[str, Any]]:
    """Gets the most recent snapshot before the current date."""
    try:
        table = dynamodb.Table(STATUS_HISTORY_TABLE)
        response = table.query(
            KeyConditionExpression='tenant_id = :tid AND snapshot_date < :date',
            ExpressionAttributeValues={
                ':tid': tenant_id,
                ':date': current_date,
            },
            ScanIndexForward=False,
            Limit=1
        )
        items = response.get('Items', [])
        return items[0] if items else None
    except Exception as e:
        logger.warning(f"Failed to get previous snapshot for {tenant_id}: {e}")
        return None


def detect_changes(current: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detects significant changes between snapshots."""
    changes = []
    
    if not previous:
        return changes
    
    prev_health = previous.get('overall_health', 'unknown')
    curr_health = current.get('overall_health', 'unknown')
    
    health_order = {'healthy': 3, 'degraded': 2, 'unhealthy': 1, 'unknown': 0}
    prev_score = health_order.get(prev_health, 0)
    curr_score = health_order.get(curr_health, 0)
    
    if curr_score < prev_score:
        changes.append({
            'type': 'health_degradation',
            'severity': 'high' if curr_health == 'unhealthy' else 'medium',
            'from': prev_health,
            'to': curr_health,
            'prev_score': previous.get('health_score', 0),
            'curr_score': current.get('health_score', 0),
        })
    elif curr_score > prev_score:
        changes.append({
            'type': 'health_improvement',
            'severity': 'info',
            'from': prev_health,
            'to': curr_health,
            'prev_score': previous.get('health_score', 0),
            'curr_score': current.get('health_score', 0),
        })
    
    prev_issues = set(previous.get('health_issues', []))
    curr_issues = set(current.get('health_issues', []))
    
    for issue in curr_issues - prev_issues:
        changes.append({
            'type': 'new_issue',
            'severity': 'medium',
            'issue': issue,
        })
    
    for issue in prev_issues - curr_issues:
        changes.append({
            'type': 'resolved_issue',
            'severity': 'info',
            'issue': issue,
        })
    
    score_diff = current.get('health_score', 0) - previous.get('health_score', 0)
    if abs(score_diff) >= 20 and not any(c['type'] in ('health_degradation', 'health_improvement') for c in changes):
        change_type = 'health_degradation' if score_diff < 0 else 'health_improvement'
        changes.append({
            'type': change_type,
            'severity': 'medium',
            'score_change': score_diff,
        })
    
    return changes


# =============================================================================
# PLATFORM-SPECIFIC FORMATTERS
# =============================================================================

def format_slack_message(tenant_id: str, display_name: str, changes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Formats a message for Slack."""
    severity_emoji = {'high': '🚨', 'medium': '⚠️', 'info': 'ℹ️'}
    
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Tenant Status Change: {display_name}"}
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Tenant ID: `{tenant_id}`"}]
        },
        {"type": "divider"},
    ]
    
    for change in changes:
        emoji = severity_emoji.get(change.get('severity', 'info'), 'ℹ️')
        text = _format_change_text(change)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{emoji} {text}"}
        })
    
    return {"blocks": blocks}


def format_teams_message(tenant_id: str, display_name: str, changes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Formats a message for Microsoft Teams."""
    facts = [{"name": "Tenant ID", "value": tenant_id}]
    text_parts = []
    
    for change in changes:
        text_parts.append(_format_change_text(change))
    
    return {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "FF0000" if any(c.get('severity') == 'high' for c in changes) else "FFA500",
        "summary": f"Tenant status change: {display_name}",
        "sections": [{
            "activityTitle": f"Tenant Status Change: {display_name}",
            "facts": facts,
            "text": "\n\n".join(text_parts),
            "markdown": True,
        }]
    }


def format_pagerduty_message(tenant_id: str, display_name: str, changes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Formats a message for PagerDuty Events API v2."""
    severity_map = {'high': 'critical', 'medium': 'warning', 'info': 'info'}
    max_severity = 'info'
    for change in changes:
        s = change.get('severity', 'info')
        if s == 'high':
            max_severity = 'critical'
            break
        elif s == 'medium' and max_severity != 'critical':
            max_severity = 'warning'
    
    summary = f"Tenant {display_name} ({tenant_id}): " + "; ".join(_format_change_text(c) for c in changes)
    
    return {
        "routing_key": "{{PAGERDUTY_ROUTING_KEY}}",
        "event_action": "trigger",
        "payload": {
            "summary": summary[:1024],
            "severity": severity_map.get(max_severity, 'info'),
            "source": f"msp-tenant-status-{tenant_id}",
            "component": display_name,
            "custom_details": {
                "tenant_id": tenant_id,
                "changes": changes,
            }
        }
    }


def _format_change_text(change: Dict[str, Any]) -> str:
    """Formats a single change as human-readable text."""
    change_type = change.get('type')
    
    if change_type == 'health_degradation':
        if 'from' in change:
            return f"Health degraded: {change['from']} → {change['to']} (score: {change.get('prev_score')} → {change.get('curr_score')})"
        return f"Health score dropped by {abs(change.get('score_change', 0))} points"
    
    if change_type == 'health_improvement':
        if 'from' in change:
            return f"Health improved: {change['from']} → {change['to']} (score: {change.get('prev_score')} → {change.get('curr_score')})"
        return f"Health score increased by {change.get('score_change', 0)} points"
    
    if change_type == 'new_issue':
        return f"New issue detected: {change.get('issue')}"
    
    if change_type == 'resolved_issue':
        return f"Issue resolved: {change.get('issue')}"
    
    return f"Change: {change}"


# =============================================================================
# WEBHOOK DELIVERY WITH ANALYTICS TRACKING (ENHANCED)
# =============================================================================

def log_webhook_delivery(
    tenant_id: str,
    webhook_id: str,
    platform: str,
    success: bool,
    status_code: int,
    error_message: str,
    duration_ms: int,
    attempt: int,
) -> None:
    """
    Logs a webhook delivery attempt to the analytics table.
    
    This enables tracking of delivery success rates, latency, and error patterns.
    """
    if not WEBHOOK_DELIVERY_LOG_TABLE:
        return
    
    try:
        dynamodb.Table(WEBHOOK_DELIVERY_LOG_TABLE).put_item(Item={
            'delivery_id': str(uuid.uuid4()),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'tenant_id': tenant_id,
            'webhook_id': webhook_id,
            'platform': platform,
            'success': success,
            'status_code': status_code,
            'error_message': error_message[:500] if error_message else '',
            'duration_ms': duration_ms,
            'attempt': attempt,
            'ttl': int(time.time()) + (RETENTION_DAYS * 86400),
        })
    except Exception as e:
        logger.warning(f"Failed to log webhook delivery: {e}")


def send_webhook(url: str, payload: Dict[str, Any], platform: str,
                 tenant_id: str, webhook_id: str) -> bool:
    """
    Sends a webhook with retry, exponential backoff, and delivery tracking.
    
    Logs each delivery attempt (success or failure) to the webhook_delivery_log
    table for analytics.
    
    Returns True if delivery succeeded, False otherwise.
    """
    delivery_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    
    for attempt in range(RETRY_ATTEMPTS):
        start_time = time.time()
        success = False
        error_message = None
        status_code = 0
        
        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                url,
                data=data,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                status_code = response.status
                if status_code < 300:
                    success = True
                    logger.info(f"Webhook delivered to {platform} (attempt {attempt + 1})")
                else:
                    error_message = f"HTTP {status_code}"
                    logger.warning(f"Webhook returned {status_code} from {platform}")
        except urllib.error.HTTPError as e:
            status_code = e.code
            error_message = f"HTTP {e.code}: {e.reason}"
            logger.warning(f"Webhook HTTP error {e.code} from {platform} (attempt {attempt + 1})")
            if e.code >= 500 and attempt < RETRY_ATTEMPTS - 1:
                duration_ms = int((time.time() - start_time) * 1000)
                log_webhook_delivery(tenant_id, webhook_id, platform, False, status_code, error_message, duration_ms, attempt + 1)
                time.sleep(2 ** attempt)
                continue
        except Exception as e:
            error_message = str(e)
            logger.warning(f"Webhook error from {platform} (attempt {attempt + 1}): {e}")
            if attempt < RETRY_ATTEMPTS - 1:
                duration_ms = int((time.time() - start_time) * 1000)
                log_webhook_delivery(tenant_id, webhook_id, platform, False, 0, error_message, duration_ms, attempt + 1)
                time.sleep(2 ** attempt)
                continue
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Log this delivery attempt (for analytics)
        log_webhook_delivery(
            tenant_id=tenant_id,
            webhook_id=webhook_id,
            platform=platform,
            success=success,
            status_code=status_code,
            error_message=error_message or '',
            duration_ms=duration_ms,
            attempt=attempt + 1,
        )
        
        if success:
            return True
    
    return False


def format_message(platform: str, tenant_id: str, display_name: str, changes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Formats a message for the specified platform."""
    if platform == 'slack':
        return format_slack_message(tenant_id, display_name, changes)
    elif platform == 'teams':
        return format_teams_message(tenant_id, display_name, changes)
    elif platform == 'pagerduty':
        return format_pagerduty_message(tenant_id, display_name, changes)
    else:
        return {
            'tenant_id': tenant_id,
            'display_name': display_name,
            'changes': changes,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }


# =============================================================================
# MAIN PROCESSING
# =============================================================================

@xray_recorder.capture('process_tenant_changes')
def process_tenant_changes(tenant_id: str, current_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Processes changes for a single tenant."""
    display_name = current_snapshot.get('display_name', tenant_id)
    current_date = current_snapshot.get('snapshot_date')
    
    previous = get_previous_snapshot(tenant_id, current_date)
    changes = detect_changes(current_snapshot, previous)
    
    if not changes:
        logger.info(f"No significant changes for tenant {tenant_id}")
        return {'tenant_id': tenant_id, 'changes_detected': 0, 'alerts_sent': 0}
    
    logger.info(f"Detected {len(changes)} changes for tenant {tenant_id}")
    
    webhooks = get_tenant_webhooks(tenant_id)
    if not webhooks:
        logger.info(f"No webhooks configured for tenant {tenant_id}")
        return {'tenant_id': tenant_id, 'changes_detected': len(changes), 'alerts_sent': 0}
    
    webhook_urls = get_webhook_urls()
    alerts_sent = 0
    
    for webhook in webhooks:
        webhook_id = webhook.get('webhook_id')
        platform = webhook.get('platform', 'generic')
        url = webhook_urls.get(webhook_id)
        
        if not url:
            logger.warning(f"Webhook URL not found for {webhook_id}")
            continue
        
        # Check cooldown
        max_severity_issue = 'general'
        for change in changes:
            if change.get('severity') == 'high':
                max_severity_issue = 'high_severity'
                break
            elif change.get('severity') == 'medium' and max_severity_issue != 'high_severity':
                max_severity_issue = 'medium_severity'
        
        cooldown_key = f"{webhook_id}#{max_severity_issue}"
        if is_in_cooldown(tenant_id, cooldown_key):
            logger.info(f"Skipping webhook {webhook_id} — in cooldown")
            continue
        
        payload = format_message(platform, tenant_id, display_name, changes)
        
        if platform == 'pagerduty':
            routing_key = webhook.get('pagerduty_routing_key', '')
            payload['routing_key'] = routing_key
        
        # Pass tenant_id and webhook_id for analytics tracking (NEW)
        if send_webhook(url, payload, platform, tenant_id, webhook_id):
            set_cooldown(tenant_id, cooldown_key)
            alerts_sent += 1
        else:
            logger.error(f"Failed to deliver webhook to {webhook_id} for tenant {tenant_id}")
    
    return {
        'tenant_id': tenant_id,
        'changes_detected': len(changes),
        'alerts_sent': alerts_sent,
        'changes': changes,
    }


@xray_recorder.capture('webhook_notifier_handler')
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main entry point for the webhook notifier."""
    try:
        results = []
        
        if 'tenant_id' in event and 'snapshot' in event:
            result = process_tenant_changes(event['tenant_id'], event['snapshot'])
            results.append(result)
        
        elif 'snapshots' in event:
            for snapshot in event['snapshots']:
                tenant_id = snapshot.get('tenant_id')
                if tenant_id:
                    result = process_tenant_changes(tenant_id, snapshot)
                    results.append(result)
        
        else:
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            history_table = dynamodb.Table(STATUS_HISTORY_TABLE)
            response = history_table.scan(
                FilterExpression='snapshot_date = :date',
                ExpressionAttributeValues={':date': today}
            )
            snapshots = response.get('Items', [])
            
            for snapshot in snapshots:
                tenant_id = snapshot.get('tenant_id')
                if tenant_id:
                    result = process_tenant_changes(tenant_id, snapshot)
                    results.append(result)
        
        summary = {
            'tenants_processed': len(results),
            'total_changes': sum(r.get('changes_detected', 0) for r in results),
            'total_alerts': sum(r.get('alerts_sent', 0) for r in results),
        }
        
        logger.info(f"Webhook notifier complete: {summary}")
        return {'statusCode': 200, 'body': json.dumps(summary)}
    
    except Exception as e:
        logger.exception("Webhook notifier failed")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}
