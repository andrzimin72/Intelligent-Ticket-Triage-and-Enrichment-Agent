"""
Status History Snapshot Lambda (with Rule Effectiveness Tracking)

Takes daily snapshots of all tenant statuses and stores them in DynamoDB
for trend analysis. Triggered by EventBridge on a daily schedule.

Features:
- Sub-Phase 1: Daily status snapshots with TTL-based retention
- Sub-Phase 2: Triggers webhook notifier after snapshot completion
- Sub-Phase 3: Evaluates tenant-defined custom health rules
- Analytics: Tracks rule effectiveness to rule_effectiveness_log table
"""

import json
import os
import logging
import time
from datetime import datetime, timezone, timedelta
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

TENANT_REGISTRY_TABLE = os.environ.get('TENANT_REGISTRY_TABLE')
STATUS_HISTORY_TABLE = os.environ.get('STATUS_HISTORY_TABLE')
STATUS_CACHE_TABLE = os.environ.get('STATUS_CACHE_TABLE')
AGENT_SCHEMAS_BUCKET = os.environ.get('AGENT_SCHEMAS_BUCKET')
KB_DOCUMENTS_BUCKET = os.environ.get('KB_DOCUMENTS_BUCKET', '')
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')
ENABLE_KB = os.environ.get('ENABLE_KB', 'false').lower() == 'true'
RETENTION_DAYS = int(os.environ.get('RETENTION_DAYS', '90'))
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

# Sub-Phase 2: Webhook notifier
WEBHOOK_NOTIFIER_FUNCTION = os.environ.get('WEBHOOK_NOTIFIER_FUNCTION', '')

# Sub-Phase 3: Custom health rules
CUSTOM_RULES_TABLE = os.environ.get('CUSTOM_RULES_TABLE', '')
MAX_SCORE_IMPACT = int(os.environ.get('MAX_SCORE_IMPACT', '30'))

# Analytics tracking (NEW)
RULE_EFFECTIVENESS_LOG_TABLE = os.environ.get('RULE_EFFECTIVENESS_LOG_TABLE', '')

# Table names for status computation
AUDIT_LOG_TABLE = os.environ.get('AUDIT_LOG_TABLE', f'{ENVIRONMENT}-msp-triage-agent-audit-log')
FEEDBACK_TABLE = os.environ.get('FEEDBACK_TABLE', f'{ENVIRONMENT}-msp-triage-agent-feedback')
CONVERSATIONS_TABLE = os.environ.get('CONVERSATIONS_TABLE', f'{ENVIRONMENT}-msp-triage-agent-conversations')

# =============================================================================
# CLIENT INITIALIZATION
# =============================================================================

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
bedrock_agent = boto3.client('bedrock-agent', region_name=AWS_REGION)
secrets_client = boto3.client('secretsmanager', region_name=AWS_REGION)
s3_client = boto3.client('s3', region_name=AWS_REGION)
lambda_client = boto3.client('lambda', region_name=AWS_REGION)


# =============================================================================
# STATUS COMPUTATION HELPERS
# =============================================================================

def check_agent_health(agent_id: Optional[str]) -> Dict[str, Any]:
    """Checks the health of a Bedrock agent."""
    if not agent_id:
        return {'status': 'unknown', 'reason': 'no_agent_id'}
    
    try:
        response = bedrock_agent.get_agent(agentId=agent_id)
        agent = response.get('agent', {})
        agent_status = agent.get('agentStatus', 'UNKNOWN')
        
        aliases = bedrock_agent.list_agent_aliases(agentId=agent_id)
        groups = bedrock_agent.list_agent_action_groups(agentId=agent_id, agentVersion='DRAFT')
        
        return {
            'status': 'healthy' if agent_status == 'PREPARED' else 'unhealthy',
            'agent_status': agent_status,
            'alias_count': len(aliases.get('agentAliasSummaries', [])),
            'action_group_count': len(groups.get('agentActionGroupSummaries', [])),
        }
    except bedrock_agent.exceptions.ResourceNotFoundException:
        return {'status': 'missing', 'reason': 'agent_not_found'}
    except Exception as e:
        logger.warning(f"Failed to check agent health for {agent_id}: {e}")
        return {'status': 'unknown', 'reason': str(e)}


def check_secrets_populated(tenant_id: str) -> Dict[str, Any]:
    """Checks if tenant secrets have been populated."""
    results = {}
    for secret_type in ['psa', 'rmm', 'graph']:
        secret_name = f"{ENVIRONMENT}/tenants/{tenant_id}/{secret_type}"
        try:
            secrets_client.describe_secret(SecretId=secret_name)
            value = secrets_client.get_secret_value(SecretId=secret_name)
            secret_data = json.loads(value['SecretString'])
            populated = any(v for v in secret_data.values() if v)
            results[secret_type] = {'exists': True, 'populated': populated}
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                results[secret_type] = {'exists': False, 'populated': False}
            else:
                results[secret_type] = {'exists': False, 'populated': False}
    
    return {
        'secrets': results,
        'all_populated': all(r.get('populated', False) for r in results.values()),
    }


def count_table_items(table_name: str, tenant_field: str, tenant_id: str) -> int:
    """Counts items in a DynamoDB table matching tenant_id."""
    try:
        table = dynamodb.Table(table_name)
        response = table.scan(
            FilterExpression='#t = :tid',
            ExpressionAttributeNames={'#t': tenant_field},
            ExpressionAttributeValues={':tid': tenant_id},
            Select='COUNT'
        )
        count = response.get('Count', 0)
        while 'LastEvaluatedKey' in response:
            response = table.scan(
                FilterExpression='#t = :tid',
                ExpressionAttributeNames={'#t': tenant_field},
                ExpressionAttributeValues={':tid': tenant_id},
                Select='COUNT',
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            count += response.get('Count', 0)
        return count
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            return 0
        logger.warning(f"Failed to count items in {table_name}: {e}")
        return 0


def count_conversations(tenant_id: str) -> int:
    """Counts conversations for a tenant (uses session_id prefix)."""
    try:
        table = dynamodb.Table(CONVERSATIONS_TABLE)
        response = table.scan(
            FilterExpression='begins_with(session_id, :prefix)',
            ExpressionAttributeValues={':prefix': f'{tenant_id}:'},
            Select='COUNT'
        )
        return response.get('Count', 0)
    except Exception as e:
        logger.warning(f"Failed to count conversations for {tenant_id}: {e}")
        return 0


def count_kb_documents(tenant_id: str) -> int:
    """Counts KB documents for a tenant."""
    if not ENABLE_KB or not KB_DOCUMENTS_BUCKET:
        return 0
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        count = 0
        for page in paginator.paginate(Bucket=KB_DOCUMENTS_BUCKET, Prefix=f"tenants/{tenant_id}/"):
            count += page.get('KeyCount', 0)
        return max(0, count - 1)
    except Exception as e:
        logger.warning(f"Failed to count KB docs for {tenant_id}: {e}")
        return 0


# =============================================================================
# CUSTOM HEALTH RULES EVALUATION (with Analytics Tracking)
# =============================================================================

def evaluate_custom_rules(tenant_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluates custom health rules for a tenant and adjusts the health score.
    
    Also logs rule effectiveness to the rule_effectiveness_log table
    for analytics (most-triggered rules, impact analysis, etc.).
    """
    if not CUSTOM_RULES_TABLE:
        return {
            'adjusted_score': snapshot['health_score'],
            'triggered_rules': [],
            'rule_details': [],
        }
    
    try:
        table = dynamodb.Table(CUSTOM_RULES_TABLE)
        response = table.query(
            KeyConditionExpression='tenant_id = :tid',
            ExpressionAttributeValues={':tid': tenant_id}
        )
        rules = [r for r in response.get('Items', []) if r.get('enabled', True)]
    except Exception as e:
        logger.warning(f"Failed to load custom rules for {tenant_id}: {e}")
        return {
            'adjusted_score': snapshot['health_score'],
            'triggered_rules': [],
            'rule_details': [],
        }
    
    if not rules:
        return {
            'adjusted_score': snapshot['health_score'],
            'triggered_rules': [],
            'rule_details': [],
        }
    
    original_score = snapshot['health_score']
    adjusted_score = original_score
    triggered_rules = []
    rule_details = []
    evaluation_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    for rule in rules:
        rule_id = rule.get('rule_id')
        rule_type = rule.get('type')
        metric = rule.get('metric')
        impact = rule.get('impact', 0)
        
        # Cap impact to configured maximum
        impact = max(-MAX_SCORE_IMPACT, min(MAX_SCORE_IMPACT, impact))
        
        triggered = False
        current_value = snapshot.get(metric)
        
        try:
            if rule_type == 'threshold':
                operator = rule.get('operator')
                threshold = rule.get('value')
                
                if current_value is not None and threshold is not None:
                    if operator == '<' and current_value < threshold:
                        triggered = True
                    elif operator == '<=' and current_value <= threshold:
                        triggered = True
                    elif operator == '>' and current_value > threshold:
                        triggered = True
                    elif operator == '>=' and current_value >= threshold:
                        triggered = True
                    elif operator == '==' and current_value == threshold:
                        triggered = True
                    elif operator == '!=' and current_value != threshold:
                        triggered = True
            
            elif rule_type == 'presence':
                expected = rule.get('expected_value')
                if current_value == expected:
                    triggered = True
            
            elif rule_type == 'trend':
                # Trend rules require historical data queries
                # Not yet implemented — skip with log
                logger.info(f"Trend rule {rule_id} not yet implemented, skipping")
        
        except Exception as e:
            logger.warning(f"Failed to evaluate rule {rule_id}: {e}")
            continue
        
        rule_details.append({
            'rule_id': rule_id,
            'type': rule_type,
            'metric': metric,
            'triggered': triggered,
            'impact': impact if triggered else 0,
            'current_value': current_value,
            'description': rule.get('description', ''),
        })
        
        if triggered:
            triggered_rules.append(rule_id)
            adjusted_score += impact
    
    # Clamp final score to valid range
    adjusted_score = max(0, min(100, adjusted_score))
    score_delta = adjusted_score - original_score
    
    # =========================================================================
    # Log rule effectiveness for analytics (NEW)
    # =========================================================================
    if RULE_EFFECTIVENESS_LOG_TABLE and triggered_rules:
        try:
            dynamodb.Table(RULE_EFFECTIVENESS_LOG_TABLE).put_item(Item={
                'tenant_id': tenant_id,
                'evaluation_date': evaluation_date,
                'triggered_rules': triggered_rules,
                'rule_details': rule_details,
                'original_score': original_score,
                'adjusted_score': adjusted_score,
                'score_delta': score_delta,
                'total_rules_evaluated': len(rules),
                'ttl': int(time.time()) + (RETENTION_DAYS * 86400),
            })
            logger.info(
                f"Logged rule effectiveness for {tenant_id}: "
                f"{len(triggered_rules)} triggered, score delta {score_delta:+d}"
            )
        except Exception as e:
            logger.warning(f"Failed to log rule effectiveness: {e}")
    
    return {
        'adjusted_score': adjusted_score,
        'triggered_rules': triggered_rules,
        'rule_details': rule_details,
    }


# =============================================================================
# SNAPSHOT COMPUTATION
# =============================================================================

@xray_recorder.capture('compute_tenant_snapshot')
def compute_tenant_snapshot(tenant_id: str, tenant_record: Dict[str, Any]) -> Dict[str, Any]:
    """Computes a snapshot of tenant status for historical tracking."""
    agent_id = tenant_record.get('agent_id')
    
    agent_health = check_agent_health(agent_id)
    secrets_status = check_secrets_populated(tenant_id)
    
    audit_count = count_table_items(AUDIT_LOG_TABLE, 'tenant_id', tenant_id)
    feedback_count = count_table_items(FEEDBACK_TABLE, 'tenant_id', tenant_id)
    conversations_count = count_conversations(tenant_id)
    kb_doc_count = count_kb_documents(tenant_id)
    
    # Compute base health score
    health_score = 100
    health_issues = []
    
    if tenant_record.get('status') != 'active':
        health_score -= 50
        health_issues.append(f"tenant_status={tenant_record.get('status')}")
    
    if agent_health.get('status') != 'healthy':
        health_score -= 30
        health_issues.append(f"agent={agent_health.get('status')}")
    
    if not secrets_status.get('all_populated'):
        health_score -= 20
        health_issues.append("secrets_not_populated")
    
    if agent_health.get('action_group_count', 0) < 4:
        health_score -= 10
        health_issues.append("missing_action_groups")
    
    health_score = max(0, health_score)
    
    if health_score >= 80:
        overall_health = 'healthy'
    elif health_score >= 50:
        overall_health = 'degraded'
    else:
        overall_health = 'unhealthy'
    
    # Apply custom health rules (with analytics tracking)
    custom_result = evaluate_custom_rules(tenant_id, {
        'health_score': health_score,
        'audit_records': audit_count,
        'feedback_records': feedback_count,
        'conversations': conversations_count,
        'kb_documents': kb_doc_count,
        'action_group_count': agent_health.get('action_group_count', 0),
        'agent_status': agent_health.get('agent_status'),
        'secrets_populated': secrets_status.get('all_populated', False),
        'overall_health': overall_health,
    })
    
    if custom_result['triggered_rules']:
        logger.info(
            f"Custom rules for {tenant_id}: {len(custom_result['triggered_rules'])} triggered, "
            f"score adjusted {health_score} → {custom_result['adjusted_score']}"
        )
        health_score = custom_result['adjusted_score']
        
        if health_score >= 80:
            overall_health = 'healthy'
        elif health_score >= 50:
            overall_health = 'degraded'
        else:
            overall_health = 'unhealthy'
    
    return {
        'tenant_id': tenant_id,
        'display_name': tenant_record.get('display_name', tenant_id),
        'status': tenant_record.get('status'),
        'overall_health': overall_health,
        'health_score': health_score,
        'health_issues': health_issues,
        'agent_status': agent_health.get('agent_status'),
        'action_group_count': agent_health.get('action_group_count', 0),
        'secrets_populated': secrets_status.get('all_populated', False),
        'audit_records': audit_count,
        'feedback_records': feedback_count,
        'conversations': conversations_count,
        'kb_documents': kb_doc_count,
        'custom_rules_triggered': custom_result['triggered_rules'],
        'custom_rules_details': custom_result['rule_details'],
        'snapshot_date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'snapshot_timestamp': datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# WEBHOOK NOTIFIER INVOCATION
# =============================================================================

@xray_recorder.capture('invoke_webhook_notifier')
def invoke_webhook_notifier(snapshots: List[Dict[str, Any]]) -> bool:
    """Invokes the webhook notifier Lambda asynchronously with the batch of snapshots."""
    if not WEBHOOK_NOTIFIER_FUNCTION:
        logger.info("Webhook notifier not configured, skipping")
        return False
    
    if not snapshots:
        logger.info("No snapshots to send to webhook notifier")
        return False
    
    try:
        lambda_client.invoke(
            FunctionName=WEBHOOK_NOTIFIER_FUNCTION,
            InvocationType='Event',
            Payload=json.dumps({'snapshots': snapshots})
        )
        logger.info(f"Invoked webhook notifier for {len(snapshots)} snapshots")
        return True
    except Exception as e:
        logger.error(f"Failed to invoke webhook notifier: {e}")
        return False


# =============================================================================
# LAMBDA HANDLER
# =============================================================================

@xray_recorder.capture('status_history_snapshot_handler')
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main entry point — takes daily snapshots of all tenant statuses."""
    try:
        logger.info("Starting daily status snapshot")
        
        # Step 1: Get all tenants
        registry = dynamodb.Table(TENANT_REGISTRY_TABLE)
        response = registry.scan()
        tenants = response.get('Items', [])
        while 'LastEvaluatedKey' in response:
            response = registry.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            tenants.extend(response.get('Items', []))
        
        logger.info(f"Found {len(tenants)} tenants to snapshot")
        
        # Step 2 & 3: Compute and store snapshots
        history_table = dynamodb.Table(STATUS_HISTORY_TABLE)
        snapshot_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        ttl_timestamp = int((datetime.now(timezone.utc) + timedelta(days=RETENTION_DAYS)).timestamp())
        
        snapshots_taken = 0
        snapshots_failed = 0
        all_snapshots = []
        health_distribution = {'healthy': 0, 'degraded': 0, 'unhealthy': 0, 'unknown': 0}
        
        for tenant in tenants:
            tenant_id = tenant.get('tenant_id')
            if not tenant_id:
                continue
            
            try:
                snapshot = compute_tenant_snapshot(tenant_id, tenant)
                snapshot['ttl'] = ttl_timestamp
                
                history_table.put_item(Item=snapshot)
                snapshots_taken += 1
                all_snapshots.append(snapshot)
                
                health = snapshot.get('overall_health', 'unknown')
                health_distribution[health] = health_distribution.get(health, 0) + 1
                
                logger.info(
                    f"Snapshot for {tenant_id}: health={snapshot['health_score']}, "
                    f"status={snapshot['overall_health']}, "
                    f"custom_rules={len(snapshot.get('custom_rules_triggered', []))}"
                )
            
            except Exception as e:
                logger.error(f"Failed to snapshot tenant {tenant_id}: {e}")
                snapshots_failed += 1
        
        # Step 4: Trigger webhook notifier
        webhook_invoked = False
        if all_snapshots:
            webhook_invoked = invoke_webhook_notifier(all_snapshots)
        
        # Step 5: Return summary
        summary = {
            'snapshot_date': snapshot_date,
            'tenants_total': len(tenants),
            'snapshots_taken': snapshots_taken,
            'snapshots_failed': snapshots_failed,
            'health_distribution': health_distribution,
            'webhook_notifier_invoked': webhook_invoked,
        }
        
        logger.info(f"Status snapshot complete: {summary}")
        
        return {
            'statusCode': 200,
            'body': json.dumps(summary)
        }
    
    except Exception as e:
        logger.exception("Failed to take status snapshots")
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}
