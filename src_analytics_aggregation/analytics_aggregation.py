"""
Analytics Aggregation Lambda (Complete)

Runs daily to compute analytics summaries:
- Health trends across all tenants
- Webhook delivery rates and reliability
- Rule effectiveness metrics
- Executive summary for leadership

Stores aggregated data in analytics_summary table for fast retrieval.

Triggered by:
- EventBridge daily schedule (7 AM UTC)
- Manual invocation for testing
"""

import json
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from collections import defaultdict
import boto3
from botocore.exceptions import ClientError
from decimal import Decimal

from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# =============================================================================
# CONFIGURATION
# =============================================================================

WEBHOOK_DELIVERY_LOG_TABLE = os.environ.get('WEBHOOK_DELIVERY_LOG_TABLE')
RULE_EFFECTIVENESS_LOG_TABLE = os.environ.get('RULE_EFFECTIVENESS_LOG_TABLE')
STATUS_HISTORY_TABLE = os.environ.get('STATUS_HISTORY_TABLE')
ANALYTICS_SUMMARY_TABLE = os.environ.get('ANALYTICS_SUMMARY_TABLE')
RETENTION_DAYS = int(os.environ.get('RETENTION_DAYS', '365'))
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)


# =============================================================================
# HELPERS
# =============================================================================

def convert_decimals(obj: Any) -> Any:
    """Converts DynamoDB Decimal types to int/float for JSON serialization."""
    if isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals(v) for v in obj]
    elif isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    return obj


def store_summary(summary_type: str, summary_date: str, data: Dict[str, Any]) -> None:
    """Stores an analytics summary in the analytics_summary table."""
    if not ANALYTICS_SUMMARY_TABLE:
        logger.warning("ANALYTICS_SUMMARY_TABLE not configured, skipping storage")
        return
    
    try:
        table = dynamodb.Table(ANALYTICS_SUMMARY_TABLE)
        table.put_item(Item={
            'summary_type': summary_type,
            'summary_date': summary_date,
            'data': json.dumps(convert_decimals(data)),
            'computed_at': datetime.now(timezone.utc).isoformat(),
            'ttl': int(time.time()) + (RETENTION_DAYS * 86400),
        })
        logger.info(f"Stored {summary_type} summary for {summary_date}")
    except Exception as e:
        logger.error(f"Failed to store {summary_type} summary: {e}")


# =============================================================================
# HEALTH TRENDS ANALYTICS
# =============================================================================

@xray_recorder.capture('compute_health_trends')
def compute_health_trends(days: int = 30) -> Dict[str, Any]:
    """
    Computes health trends across all tenants over the specified period.
    
    Returns:
    - Average health score per day
    - Distribution of health statuses (healthy/degraded/unhealthy)
    - Tenants with significant changes
    - Systemic issues (multiple tenants degraded on same day)
    """
    if not STATUS_HISTORY_TABLE:
        return {'error': 'Status history table not configured'}
    
    try:
        history_table = dynamodb.Table(STATUS_HISTORY_TABLE)
        start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
        
        # Scan all history records in the date range
        response = history_table.scan(
            FilterExpression='snapshot_date >= :start',
            ExpressionAttributeValues={':start': start_date}
        )
        items = response.get('Items', [])
        
        while 'LastEvaluatedKey' in response:
            response = history_table.scan(
                FilterExpression='snapshot_date >= :start',
                ExpressionAttributeValues={':start': start_date},
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            items.extend(response.get('Items', []))
        
        if not items:
            return {
                'period_days': days,
                'message': 'No status history in the specified period',
                'daily_averages': [],
                'systemic_issues': [],
                'significant_changes': [],
            }
        
        # Aggregate by date
        daily_stats = defaultdict(lambda: {
            'scores': [],
            'healthy': 0,
            'degraded': 0,
            'unhealthy': 0,
        })
        
        for item in items:
            date = item.get('snapshot_date')
            score = item.get('health_score', 0)
            health = item.get('overall_health', 'unknown')
            
            daily_stats[date]['scores'].append(score)
            if health == 'healthy':
                daily_stats[date]['healthy'] += 1
            elif health == 'degraded':
                daily_stats[date]['degraded'] += 1
            elif health == 'unhealthy':
                daily_stats[date]['unhealthy'] += 1
        
        # Compute daily averages
        daily_averages = []
        for date in sorted(daily_stats.keys()):
            stats = daily_stats[date]
            avg_score = sum(stats['scores']) / len(stats['scores']) if stats['scores'] else 0
            daily_averages.append({
                'date': date,
                'avg_health_score': round(avg_score, 2),
                'tenant_count': len(stats['scores']),
                'healthy': stats['healthy'],
                'degraded': stats['degraded'],
                'unhealthy': stats['unhealthy'],
            })
        
        # Identify systemic issues (days where >20% of tenants are unhealthy)
        systemic_issues = []
        for day in daily_averages:
            if day['tenant_count'] > 0:
                unhealthy_pct = day['unhealthy'] / day['tenant_count']
                if unhealthy_pct > 0.2:
                    systemic_issues.append({
                        'date': day['date'],
                        'unhealthy_percentage': round(unhealthy_pct * 100, 1),
                        'unhealthy_count': day['unhealthy'],
                    })
        
        # Identify tenants with significant score changes
        tenant_changes = defaultdict(list)
        for item in items:
            tenant_id = item.get('tenant_id')
            date = item.get('snapshot_date')
            score = item.get('health_score', 0)
            tenant_changes[tenant_id].append({'date': date, 'score': score})
        
        significant_changes = []
        for tenant_id, scores in tenant_changes.items():
            if len(scores) >= 2:
                scores.sort(key=lambda x: x['date'])
                first_score = scores[0]['score']
                last_score = scores[-1]['score']
                change = last_score - first_score
                if abs(change) >= 20:
                    significant_changes.append({
                        'tenant_id': tenant_id,
                        'first_date': scores[0]['date'],
                        'last_date': scores[-1]['date'],
                        'first_score': first_score,
                        'last_score': last_score,
                        'change': change,
                    })
        
        return {
            'period_days': days,
            'daily_averages': daily_averages,
            'systemic_issues': systemic_issues,
            'significant_changes': significant_changes,
            'computed_at': datetime.now(timezone.utc).isoformat(),
        }
    
    except Exception as e:
        logger.exception(f"Failed to compute health trends: {e}")
        return {'error': str(e)}


# =============================================================================
# WEBHOOK DELIVERY ANALYTICS
# =============================================================================

@xray_recorder.capture('compute_webhook_delivery_stats')
def compute_webhook_delivery_stats(days: int = 30) -> Dict[str, Any]:
    """
    Computes webhook delivery statistics.
    
    Returns:
    - Overall delivery success rate
    - Per-tenant delivery rates
    - Per-platform delivery rates
    - Average delivery latency
    - Common error patterns
    """
    if not WEBHOOK_DELIVERY_LOG_TABLE:
        return {'error': 'Webhook delivery log table not configured'}
    
    try:
        delivery_table = dynamodb.Table(WEBHOOK_DELIVERY_LOG_TABLE)
        start_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        # Scan all delivery logs in the date range
        response = delivery_table.scan(
            FilterExpression='#ts >= :start',
            ExpressionAttributeNames={'#ts': 'timestamp'},
            ExpressionAttributeValues={':start': start_date}
        )
        items = response.get('Items', [])
        
        while 'LastEvaluatedKey' in response:
            response = delivery_table.scan(
                FilterExpression='#ts >= :start',
                ExpressionAttributeNames={'#ts': 'timestamp'},
                ExpressionAttributeValues={':start': start_date},
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            items.extend(response.get('Items', []))
        
        if not items:
            return {
                'period_days': days,
                'total_deliveries': 0,
                'message': 'No webhook deliveries in the specified period',
            }
        
        # Overall stats
        total = len(items)
        successful = sum(1 for item in items if item.get('success'))
        success_rate = (successful / total * 100) if total > 0 else 0
        
        # Per-tenant stats
        tenant_stats = defaultdict(lambda: {'total': 0, 'successful': 0})
        for item in items:
            tenant_id = item.get('tenant_id')
            tenant_stats[tenant_id]['total'] += 1
            if item.get('success'):
                tenant_stats[tenant_id]['successful'] += 1
        
        tenant_delivery_rates = []
        for tenant_id, stats in tenant_stats.items():
            rate = (stats['successful'] / stats['total'] * 100) if stats['total'] > 0 else 0
            tenant_delivery_rates.append({
                'tenant_id': tenant_id,
                'total_deliveries': stats['total'],
                'successful_deliveries': stats['successful'],
                'success_rate': round(rate, 2),
            })
        
        # Per-platform stats
        platform_stats = defaultdict(lambda: {'total': 0, 'successful': 0, 'durations': []})
        for item in items:
            platform = item.get('platform', 'unknown')
            platform_stats[platform]['total'] += 1
            if item.get('success'):
                platform_stats[platform]['successful'] += 1
            duration = item.get('duration_ms', 0)
            if duration:
                platform_stats[platform]['durations'].append(duration)
        
        platform_delivery_stats = []
        for platform, stats in platform_stats.items():
            rate = (stats['successful'] / stats['total'] * 100) if stats['total'] > 0 else 0
            avg_duration = sum(stats['durations']) / len(stats['durations']) if stats['durations'] else 0
            platform_delivery_stats.append({
                'platform': platform,
                'total_deliveries': stats['total'],
                'successful_deliveries': stats['successful'],
                'success_rate': round(rate, 2),
                'avg_duration_ms': round(avg_duration, 2),
            })
        
        # Error patterns
        error_counts = defaultdict(int)
        for item in items:
            if not item.get('success'):
                error_msg = item.get('error_message', 'unknown')
                # Simplify error messages
                if 'timeout' in error_msg.lower():
                    error_counts['timeout'] += 1
                elif '404' in error_msg:
                    error_counts['not_found'] += 1
                elif '500' in error_msg or '502' in error_msg or '503' in error_msg:
                    error_counts['server_error'] += 1
                else:
                    error_counts['other'] += 1
        
        # Overall average latency
        all_durations = [item.get('duration_ms', 0) for item in items if item.get('duration_ms')]
        avg_latency = sum(all_durations) / len(all_durations) if all_durations else 0
        
        return {
            'period_days': days,
            'total_deliveries': total,
            'successful_deliveries': successful,
            'overall_success_rate': round(success_rate, 2),
            'avg_latency_ms': round(avg_latency, 2),
            'tenant_delivery_rates': tenant_delivery_rates,
            'platform_delivery_stats': platform_delivery_stats,
            'error_patterns': dict(error_counts),
            'computed_at': datetime.now(timezone.utc).isoformat(),
        }
    
    except Exception as e:
        logger.exception(f"Failed to compute webhook delivery stats: {e}")
        return {'error': str(e)}


# =============================================================================
# RULE EFFECTIVENESS ANALYTICS
# =============================================================================

@xray_recorder.capture('compute_rule_effectiveness')
def compute_rule_effectiveness(days: int = 30) -> Dict[str, Any]:
    """
    Computes custom health rule effectiveness metrics.
    
    Returns:
    - Most frequently triggered rules
    - Rules with highest impact on health scores
    - Tenants with most active rules
    - Rule type distribution
    """
    if not RULE_EFFECTIVENESS_LOG_TABLE:
        return {'error': 'Rule effectiveness log table not configured'}
    
    try:
        rule_table = dynamodb.Table(RULE_EFFECTIVENESS_LOG_TABLE)
        start_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
        
        # Scan all rule effectiveness logs in the date range
        response = rule_table.scan(
            FilterExpression='evaluation_date >= :start',
            ExpressionAttributeValues={':start': start_date}
        )
        items = response.get('Items', [])
        
        while 'LastEvaluatedKey' in response:
            response = rule_table.scan(
                FilterExpression='evaluation_date >= :start',
                ExpressionAttributeValues={':start': start_date},
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            items.extend(response.get('Items', []))
        
        if not items:
            return {
                'period_days': days,
                'message': 'No rule effectiveness data in the specified period',
            }
        
        # Count rule triggers
        rule_trigger_counts = defaultdict(int)
        rule_impact_totals = defaultdict(float)
        rule_type_counts = defaultdict(int)
        tenant_rule_activity = defaultdict(int)
        
        for item in items:
            tenant_id = item.get('tenant_id')
            triggered_rules = item.get('triggered_rules', [])
            rule_details = item.get('rule_details', [])
            score_delta = item.get('score_delta', 0)
            
            tenant_rule_activity[tenant_id] += len(triggered_rules)
            
            for rule_id in triggered_rules:
                rule_trigger_counts[rule_id] += 1
            
            for detail in rule_details:
                if detail.get('triggered'):
                    rule_id = detail.get('rule_id')
                    rule_type = detail.get('type', 'unknown')
                    impact = detail.get('impact', 0)
                    
                    rule_type_counts[rule_type] += 1
                    rule_impact_totals[rule_id] += impact
        
        # Most frequently triggered rules
        most_triggered = sorted(
            rule_trigger_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        # Rules with highest impact
        highest_impact = sorted(
            rule_impact_totals.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )[:10]
        
        # Tenants with most active rules
        most_active_tenants = sorted(
            tenant_rule_activity.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        # Total evaluations
        total_evaluations = len(items)
        evaluations_with_triggers = sum(1 for item in items if item.get('triggered_rules'))
        trigger_rate = (evaluations_with_triggers / total_evaluations * 100) if total_evaluations > 0 else 0
        
        return {
            'period_days': days,
            'total_evaluations': total_evaluations,
            'evaluations_with_triggers': evaluations_with_triggers,
            'trigger_rate': round(trigger_rate, 2),
            'most_triggered_rules': [
                {'rule_id': rule_id, 'trigger_count': count}
                for rule_id, count in most_triggered
            ],
            'highest_impact_rules': [
                {'rule_id': rule_id, 'total_impact': round(impact, 2)}
                for rule_id, impact in highest_impact
            ],
            'most_active_tenants': [
                {'tenant_id': tenant_id, 'trigger_count': count}
                for tenant_id, count in most_active_tenants
            ],
            'rule_type_distribution': dict(rule_type_counts),
            'computed_at': datetime.now(timezone.utc).isoformat(),
        }
    
    except Exception as e:
        logger.exception(f"Failed to compute rule effectiveness: {e}")
        return {'error': str(e)}


# =============================================================================
# EXECUTIVE SUMMARY
# =============================================================================

@xray_recorder.capture('compute_executive_summary')
def compute_executive_summary() -> Dict[str, Any]:
    """
    Computes an executive summary combining all analytics.
    
    Returns a high-level overview suitable for leadership review.
    """
    # Compute all analytics
    health_trends = compute_health_trends(days=7)
    webhook_stats = compute_webhook_delivery_stats(days=7)
    rule_stats = compute_rule_effectiveness(days=7)
    
    # Extract key metrics
    summary = {
        'period': 'Last 7 days',
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }
    
    # Health trends summary
    if 'error' not in health_trends and health_trends.get('daily_averages'):
        daily_avgs = health_trends['daily_averages']
        if daily_avgs:
            latest = daily_avgs[-1]
            first = daily_avgs[0]
            summary['health'] = {
                'latest_avg_score': latest['avg_health_score'],
                'score_trend': round(latest['avg_health_score'] - first['avg_health_score'], 2),
                'total_tenants': latest['tenant_count'],
                'currently_healthy': latest['healthy'],
                'currently_degraded': latest['degraded'],
                'currently_unhealthy': latest['unhealthy'],
                'systemic_issues_count': len(health_trends.get('systemic_issues', [])),
                'significant_changes_count': len(health_trends.get('significant_changes', [])),
            }
    
    # Webhook delivery summary
    if 'error' not in webhook_stats:
        summary['webhooks'] = {
            'total_deliveries': webhook_stats.get('total_deliveries', 0),
            'success_rate': webhook_stats.get('overall_success_rate', 0),
            'avg_latency_ms': webhook_stats.get('avg_latency_ms', 0),
            'platforms': len(webhook_stats.get('platform_delivery_stats', [])),
        }
    
    # Rule effectiveness summary
    if 'error' not in rule_stats:
        summary['rules'] = {
            'total_evaluations': rule_stats.get('total_evaluations', 0),
            'trigger_rate': rule_stats.get('trigger_rate', 0),
            'most_triggered_rule': rule_stats.get('most_triggered_rules', [{}])[0].get('rule_id', 'none'),
            'most_active_tenant': rule_stats.get('most_active_tenants', [{}])[0].get('tenant_id', 'none'),
        }
    
    # Overall platform health assessment
    health_score = summary.get('health', {}).get('latest_avg_score', 0)
    webhook_success = summary.get('webhooks', {}).get('success_rate', 0)
    
    if health_score >= 80 and webhook_success >= 95:
        summary['overall_assessment'] = 'EXCELLENT'
        summary['recommendation'] = 'Platform is operating optimally. Continue monitoring.'
    elif health_score >= 60 and webhook_success >= 80:
        summary['overall_assessment'] = 'GOOD'
        summary['recommendation'] = 'Platform is stable. Review degraded tenants and webhook failures.'
    elif health_score >= 40:
        summary['overall_assessment'] = 'NEEDS_ATTENTION'
        summary['recommendation'] = 'Multiple issues detected. Prioritize unhealthy tenants and investigate systemic issues.'
    else:
        summary['overall_assessment'] = 'CRITICAL'
        summary['recommendation'] = 'Immediate action required. High number of unhealthy tenants and/or webhook failures.'
    
    return summary


# =============================================================================
# LAMBDA HANDLER
# =============================================================================

@xray_recorder.capture('analytics_aggregation_handler')
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main entry point for analytics aggregation.
    
    Computes all analytics summaries and stores them in the analytics_summary table.
    
    Can be invoked with:
    - Empty event (compute all analytics)
    - {"analytics_type": "health_trends"} (compute specific analytics)
    - {"days": 7} (compute for specific time period)
    """
    try:
        logger.info("Starting analytics aggregation")
        
        # Parse event parameters
        analytics_type = event.get('analytics_type', 'all')
        days = event.get('days', 30)
        summary_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        
        results = {}
        
        # =========================================================================
        # Compute Health Trends
        # =========================================================================
        if analytics_type in ('all', 'health_trends'):
            logger.info(f"Computing health trends for last {days} days")
            health_trends = compute_health_trends(days=days)
            results['health_trends'] = health_trends
            
            if 'error' not in health_trends:
                store_summary('health_trends', summary_date, health_trends)
        
        # =========================================================================
        # Compute Webhook Delivery Stats
        # =========================================================================
        if analytics_type in ('all', 'webhook_delivery'):
            logger.info(f"Computing webhook delivery stats for last {days} days")
            webhook_stats = compute_webhook_delivery_stats(days=days)
            results['webhook_delivery'] = webhook_stats
            
            if 'error' not in webhook_stats:
                store_summary('webhook_delivery', summary_date, webhook_stats)
        
        # =========================================================================
        # Compute Rule Effectiveness
        # =========================================================================
        if analytics_type in ('all', 'rule_effectiveness'):
            logger.info(f"Computing rule effectiveness for last {days} days")
            rule_stats = compute_rule_effectiveness(days=days)
            results['rule_effectiveness'] = rule_stats
            
            if 'error' not in rule_stats:
                store_summary('rule_effectiveness', summary_date, rule_stats)
        
        # =========================================================================
        # Compute Executive Summary
        # =========================================================================
        if analytics_type in ('all', 'executive_summary'):
            logger.info("Computing executive summary")
            exec_summary = compute_executive_summary()
            results['executive_summary'] = exec_summary
            store_summary('executive_summary', summary_date, exec_summary)
        
        # =========================================================================
        # Return results
        # =========================================================================
        logger.info(f"Analytics aggregation complete: {list(results.keys())}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Analytics aggregation complete',
                'analytics_types': list(results.keys()),
                'summary_date': summary_date,
                'results': convert_decimals(results),
            })
        }
    
    except Exception as e:
        logger.exception("Analytics aggregation failed")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }