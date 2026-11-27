"""
Tenant Onboarding, Deprovisioning, Status & Analytics API (Complete)

Handles the full tenant lifecycle, observability, and analytics:

LIFECYCLE:
- POST   /tenants              — Create new tenant OR adopt existing (Hybrid Mode)
- DELETE /tenants/{tenant_id}  — Deprovision tenant

BASIC STATUS:
- GET    /tenants              — List all tenants (raw records)
- GET    /tenants/{tenant_id}  — Get tenant record

ENHANCED STATUS (Phase C):
- GET    /status               — System-wide health
- GET    /status/tenants       — List all tenants with computed metrics
- GET    /status/tenants/{id}  — Detailed status for one tenant (cached)
- GET    /status/tenants/{id}/health — Deep health check (bypasses cache)
- GET    /status/metrics       — Aggregated metrics across all tenants

ANALYTICS (Advanced Analytics):
- GET    /analytics/health-trends       — Health trend analytics
- GET    /analytics/webhook-delivery    — Webhook delivery stats
- GET    /analytics/rule-effectiveness  — Custom rule effectiveness
- GET    /analytics/executive-summary   — Executive summary

CLOUDWATCH METRICS (Step 2):
- Emits health_score, resource counts, and API usage as custom metrics

HYBRID MODE (Phase D):
- Detects existing Terraform-managed tenants
- Verifies agent health before adoption
- Updates metadata without recreating resources
"""

import json
import os
import logging
import secrets
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
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

TENANT_REGISTRY_TABLE = os.environ.get('TENANT_REGISTRY_TABLE')
STATUS_CACHE_TABLE = os.environ.get('STATUS_CACHE_TABLE')
STATUS_CACHE_TTL = int(os.environ.get('STATUS_CACHE_TTL', '60'))
PROVISIONING_QUEUE_URL = os.environ.get('PROVISIONING_QUEUE_URL')
AGENT_SCHEMAS_BUCKET = os.environ.get('AGENT_SCHEMAS_BUCKET')
KB_DOCUMENTS_BUCKET = os.environ.get('KB_DOCUMENTS_BUCKET', '')
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', '')
DEFAULT_AGENT_MODEL = os.environ.get('DEFAULT_AGENT_MODEL')
ENABLE_KB = os.environ.get('ENABLE_KB', 'false').lower() == 'true'
DEPROVISION_REQUIRE_CONFIRMATION = os.environ.get('DEPROVISION_REQUIRE_CONFIRMATION', 'true').lower() == 'true'

# CloudWatch metrics configuration (Step 2)
ENABLE_STATUS_METRICS = os.environ.get('ENABLE_STATUS_METRICS', 'true').lower() == 'true'
STATUS_METRICS_NAMESPACE = os.environ.get('STATUS_METRICS_NAMESPACE', 'Custom/MSP-Tenant-Status')

# Analytics configuration (Advanced Analytics)
ANALYTICS_SUMMARY_TABLE = os.environ.get('ANALYTICS_SUMMARY_TABLE', '')

# Table names for status computation
AUDIT_LOG_TABLE = os.environ.get('AUDIT_LOG_TABLE', f'{ENVIRONMENT}-msp-triage-agent-audit-log')
FEEDBACK_TABLE = os.environ.get('FEEDBACK_TABLE', f'{ENVIRONMENT}-msp-triage-agent-feedback')
CONVERSATIONS_TABLE = os.environ.get('CONVERSATIONS_TABLE', f'{ENVIRONMENT}-msp-triage-agent-conversations')
METRICS_TABLE = os.environ.get('METRICS_TABLE', f'{ENVIRONMENT}-msp-triage-metrics')

# =============================================================================
# CLIENT INITIALIZATION
# =============================================================================

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
secrets_client = boto3.client('secretsmanager', region_name=AWS_REGION)
s3_client = boto3.client('s3', region_name=AWS_REGION)
sqs_client = boto3.client('sqs', region_name=AWS_REGION)
bedrock_agent = boto3.client('bedrock-agent', region_name=AWS_REGION)
cloudwatch = boto3.client('cloudwatch', region_name=AWS_REGION)

# Required fields for tenant onboarding
REQUIRED_FIELDS = ['tenant_id', 'display_name', 'entra_tenant_id', 'admin_group_id', 'contact_email']

# Validation patterns
TENANT_ID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$')
EMAIL_PATTERN = re.compile(r'^[^@]+@[^@]+\.[^@]+$')
GUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)


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


def validate_input(body: Dict[str, Any]) -> Optional[str]:
    """Validates the onboarding request body. Returns error message or None."""
    missing = [f for f in REQUIRED_FIELDS if not body.get(f)]
    if missing:
        return f"Missing required fields: {missing}"

    tenant_id = body['tenant_id']
    if not TENANT_ID_PATTERN.match(tenant_id):
        return "tenant_id must be 3-32 lowercase alphanumeric characters or hyphens, not starting/ending with hyphen"

    if not EMAIL_PATTERN.match(body['contact_email']):
        return "contact_email must be a valid email address"

    if not GUID_PATTERN.match(body['entra_tenant_id']):
        return "entra_tenant_id must be a valid GUID"

    if not GUID_PATTERN.match(body['admin_group_id']):
        return "admin_group_id must be a valid GUID"

    return None


def parse_path(path: str) -> List[str]:
    """Parses a URL path into segments, stripping leading/trailing slashes."""
    return [p for p in path.strip('/').split('/') if p]


# =============================================================================
# HYBRID MODE HELPERS (Phase D)
# =============================================================================

def check_existing_tenant(tenant_id: str) -> Optional[Dict[str, Any]]:
    """Checks if a tenant already exists in the registry."""
    try:
        table = dynamodb.Table(TENANT_REGISTRY_TABLE)
        response = table.get_item(Key={'tenant_id': tenant_id})
        return response.get('Item')
    except Exception as e:
        logger.warning(f"Failed to check existing tenant {tenant_id}: {e}")
        return None


def verify_existing_agent(agent_id: str) -> Dict[str, Any]:
    """Verifies that an existing Bedrock agent is healthy."""
    if not agent_id:
        return {'healthy': False, 'reason': 'no_agent_id'}

    try:
        response = bedrock_agent.get_agent(agentId=agent_id)
        agent = response.get('agent', {})
        status = agent.get('agentStatus', 'UNKNOWN')

        if status != 'PREPARED':
            return {'healthy': False, 'reason': f'agent_status={status}'}

        aliases = bedrock_agent.list_agent_aliases(agentId=agent_id)
        alias_count = len(aliases.get('agentAliasSummaries', []))
        if alias_count == 0:
            return {'healthy': False, 'reason': 'no_aliases'}

        groups = bedrock_agent.list_agent_action_groups(agentId=agent_id, agentVersion='DRAFT')
        group_count = len(groups.get('agentActionGroupSummaries', []))
        if group_count < 4:
            return {'healthy': False, 'reason': f'insufficient_action_groups={group_count}'}

        return {
            'healthy': True,
            'agent_status': status,
            'alias_count': alias_count,
            'action_group_count': group_count,
            'management': 'terraform',
        }

    except bedrock_agent.exceptions.ResourceNotFoundException:
        return {'healthy': False, 'reason': 'agent_not_found'}
    except Exception as e:
        logger.warning(f"Failed to verify agent {agent_id}: {e}")
        return {'healthy': False, 'reason': str(e)}


def adopt_existing_tenant(tenant_id: str, body: Dict[str, Any], existing: Dict[str, Any]) -> Dict[str, Any]:
    """Adopts an existing Terraform-managed tenant into hybrid mode."""
    table = dynamodb.Table(TENANT_REGISTRY_TABLE)

    update_parts = ["updated_at = :ts", "management_mode = :mode"]
    expr_values = {
        ':ts': datetime.now(timezone.utc).isoformat(),
        ':mode': 'hybrid',
    }

    if body.get('display_name'):
        update_parts.append("display_name = :dn")
        expr_values[':dn'] = body['display_name']
    if body.get('contact_email'):
        update_parts.append("contact_email = :ce")
        expr_values[':ce'] = body['contact_email']
    if body.get('branding'):
        update_parts.append("branding = :br")
        expr_values[':br'] = json.dumps(body['branding'])
    if body.get('timezone'):
        update_parts.append("timezone = :tz")
        expr_values[':tz'] = body['timezone']

    update_expr = "SET " + ", ".join(update_parts)

    table.update_item(
        Key={'tenant_id': tenant_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
    )

    return {
        'tenant_id': tenant_id,
        'status': existing.get('status'),
        'agent_id': existing.get('agent_id'),
        'agent_alias_id': existing.get('agent_alias_id'),
        'management_mode': 'hybrid',
        'message': 'Existing Terraform-managed tenant adopted into hybrid mode.',
        'next_steps': [
            'Tenant is now managed by both Terraform (infrastructure) and the API (metadata)',
            'To fully migrate to API management, see Phase D Strategy 2',
        ],
    }


# =============================================================================
# PROVISIONING (FAST PATH)
# =============================================================================

def create_tenant_secrets(tenant_id: str) -> Dict[str, str]:
    """Creates tenant-scoped secrets in Secrets Manager."""
    secret_types = {
        'psa': {
            'name': f"{ENVIRONMENT}/tenants/{tenant_id}/psa",
            'description': f"ConnectWise PSA credentials for tenant {tenant_id}",
            'value': {'BASE_URL': '', 'COMPANY_ID': '', 'PUBLIC_KEY': '', 'PRIVATE_KEY': '', 'CLIENT_ID': ''}
        },
        'rmm': {
            'name': f"{ENVIRONMENT}/tenants/{tenant_id}/rmm",
            'description': f"NinjaOne RMM credentials for tenant {tenant_id}",
            'value': {'BASE_URL': '', 'API_TOKEN': ''}
        },
        'graph': {
            'name': f"{ENVIRONMENT}/tenants/{tenant_id}/graph",
            'description': f"Entra ID Graph API credentials for tenant {tenant_id}",
            'value': {'CLIENT_ID': '', 'CLIENT_SECRET': '', 'TENANT_ID': ''}
        },
    }

    created = {}
    for secret_type, config in secret_types.items():
        try:
            response = secrets_client.create_secret(
                Name=config['name'],
                Description=config['description'],
                SecretString=json.dumps(config['value']),
                Tags=[
                    {'Key': 'tenant_id', 'Value': tenant_id},
                    {'Key': 'secret_type', 'Value': secret_type},
                    {'Key': 'environment', 'Value': ENVIRONMENT},
                ]
            )
            created[secret_type] = response['ARN']
            logger.info(f"Created secret {config['name']}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceExistsException':
                logger.warning(f"Secret {config['name']} already exists, skipping")
            else:
                raise

    return created


def create_s3_folders(tenant_id: str) -> None:
    """
    Creates tenant-scoped S3 folder structure.

    NOTE: Agent examples are written to AGENT_SCHEMAS_BUCKET (Option A fix).
    The Teams Bot reads examples from the same bucket, ensuring consistency.
    """
    try:
        s3_client.put_object(
            Bucket=AGENT_SCHEMAS_BUCKET,
            Key=f"tenants/{tenant_id}/agent-examples.json",
            Body=b'[]',
            ContentType='application/json'
        )
        logger.info(f"Created S3 folder for agent examples: tenants/{tenant_id}/")
    except ClientError as e:
        logger.error(f"Failed to create agent examples folder: {e}")
        raise

    if ENABLE_KB and KB_DOCUMENTS_BUCKET:
        try:
            s3_client.put_object(
                Bucket=KB_DOCUMENTS_BUCKET,
                Key=f"tenants/{tenant_id}/.keep",
                Body=b'placeholder'
            )
            logger.info(f"Created S3 folder for KB documents: tenants/{tenant_id}/")
        except ClientError as e:
            logger.error(f"Failed to create KB documents folder: {e}")
            raise


def create_tenant_record(tenant_id: str, body: Dict[str, Any], secret_arns: Dict[str, str]) -> None:
    """Creates the tenant record in DynamoDB with status='provisioning'."""
    table = dynamodb.Table(TENANT_REGISTRY_TABLE)

    item = {
        'tenant_id': tenant_id,
        'enabled': 1,
        'status': 'provisioning',
        'management_mode': 'api',
        'display_name': body['display_name'],
        'entra_tenant_id': body['entra_tenant_id'],
        'admin_group_id': body['admin_group_id'],
        'contact_email': body['contact_email'],
        'psa_secret_name': f"{ENVIRONMENT}/tenants/{tenant_id}/psa",
        'rmm_secret_name': f"{ENVIRONMENT}/tenants/{tenant_id}/rmm",
        'graph_secret_name': f"{ENVIRONMENT}/tenants/{tenant_id}/graph",
        'branding': json.dumps(body.get('branding', {})),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'provisioning_started_at': datetime.now(timezone.utc).isoformat(),
    }

    if body.get('timezone'):
        item['timezone'] = body['timezone']
    if body.get('report_cadence'):
        item['report_cadence'] = body['report_cadence']

    try:
        table.put_item(
            Item=item,
            ConditionExpression='attribute_not_exists(tenant_id)'
        )
        logger.info(f"Created tenant record for {tenant_id}")
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            raise ValueError(f"Tenant {tenant_id} already exists")
        raise


def queue_provisioning(tenant_id: str) -> str:
    """Sends a message to the provisioning queue. Returns message ID."""
    response = sqs_client.send_message(
        QueueUrl=PROVISIONING_QUEUE_URL,
        MessageBody=json.dumps({'tenant_id': tenant_id, 'action': 'provision'}),
        MessageAttributes={'tenant_id': {'DataType': 'String', 'StringValue': tenant_id}}
    )
    return response['MessageId']


# =============================================================================
# DEPROVISIONING (PHASE B — FAST PATH)
# =============================================================================

def validate_deprovision_request(event: Dict[str, Any]) -> Tuple[Optional[str], bool, Optional[str]]:
    """Validates a deprovision request. Returns (tenant_id, preserve_data, error_message)."""
    path = event.get('rawPath', '') or event.get('requestContext', {}).get('http', {}).get('path', '')
    path_parts = parse_path(path)

    if len(path_parts) < 2 or path_parts[0] != 'tenants':
        return None, False, "Invalid path"

    tenant_id = path_parts[1]
    if not TENANT_ID_PATTERN.match(tenant_id):
        return None, False, "Invalid tenant_id format"

    query_params = event.get('queryStringParameters') or {}

    if DEPROVISION_REQUIRE_CONFIRMATION:
        if query_params.get('confirm') != 'true':
            return None, False, "Missing required ?confirm=true parameter."

    preserve_data = query_params.get('preserve_data', 'true').lower() == 'true'
    return tenant_id, preserve_data, None


def start_deprovisioning(tenant_id: str, preserve_data: bool) -> Dict[str, Any]:
    """Initiates tenant deprovisioning (Phase 1: synchronous)."""
    table = dynamodb.Table(TENANT_REGISTRY_TABLE)

    response = table.get_item(Key={'tenant_id': tenant_id})
    tenant = response.get('Item')

    if not tenant:
        raise ValueError(f"Tenant {tenant_id} not found")

    current_status = tenant.get('status')

    if current_status == 'deprovisioning':
        raise ValueError(f"Tenant {tenant_id} is already being deprovisioned")
    if current_status == 'deleted':
        raise ValueError(f"Tenant {tenant_id} is already deleted")
    if current_status == 'provisioning':
        raise ValueError(f"Tenant {tenant_id} is still provisioning")
    if current_status not in ('active', 'disabled', 'delete_failed'):
        raise ValueError(f"Tenant {tenant_id} is in unexpected state: {current_status}")

    table.update_item(
        Key={'tenant_id': tenant_id},
        UpdateExpression='SET #s = :status, deprovision_started_at = :ts, preserve_data = :pd',
        ConditionExpression='#s IN (:active, :disabled, :delete_failed)',
        ExpressionAttributeNames={'#s': 'status'},
        ExpressionAttributeValues={
            ':status': 'deprovisioning',
            ':active': 'active',
            ':disabled': 'disabled',
            ':delete_failed': 'delete_failed',
            ':ts': datetime.now(timezone.utc).isoformat(),
            ':pd': 1 if preserve_data else 0,
        }
    )

    message_id = sqs_client.send_message(
        QueueUrl=PROVISIONING_QUEUE_URL,
        MessageBody=json.dumps({
            'tenant_id': tenant_id,
            'action': 'deprovision',
            'preserve_data': preserve_data,
        }),
        MessageAttributes={
            'tenant_id': {'DataType': 'String', 'StringValue': tenant_id},
            'action': {'DataType': 'String', 'StringValue': 'deprovision'},
        }
    )['MessageId']

    logger.info(f"Queued deprovisioning for tenant {tenant_id}")

    return {
        'tenant_id': tenant_id,
        'status': 'deprovisioning',
        'preserve_data': preserve_data,
        'message_id': message_id,
        'message': 'Deprovisioning initiated.',
        'estimated_completion_minutes': 5,
    }


# =============================================================================
# STATUS COMPUTATION (PHASE C + STEP 2: CLOUDWATCH METRICS)
# =============================================================================

def get_cached_status(cache_key: str) -> Optional[Dict[str, Any]]:
    """Retrieves cached status if fresh (< STATUS_CACHE_TTL seconds old)."""
    if not STATUS_CACHE_TABLE:
        return None

    try:
        table = dynamodb.Table(STATUS_CACHE_TABLE)
        response = table.get_item(Key={'cache_key': cache_key})
        item = response.get('Item')

        if not item:
            return None

        computed_at = item.get('computed_at', '')
        if not computed_at:
            return None

        computed_dt = datetime.fromisoformat(computed_at.replace('Z', '+00:00'))
        age_seconds = (datetime.now(timezone.utc) - computed_dt).total_seconds()

        if age_seconds > STATUS_CACHE_TTL:
            return None

        return item.get('status')

    except Exception as e:
        logger.warning(f"Failed to read status cache: {e}")
        return None


def store_cached_status(cache_key: str, status: Dict[str, Any]) -> None:
    """Stores computed status in cache with TTL."""
    if not STATUS_CACHE_TABLE:
        return

    try:
        table = dynamodb.Table(STATUS_CACHE_TABLE)
        table.put_item(Item={
            'cache_key': cache_key,
            'status': status,
            'computed_at': datetime.now(timezone.utc).isoformat(),
            'ttl': int(time.time()) + STATUS_CACHE_TTL * 2,
        })
    except Exception as e:
        logger.warning(f"Failed to write status cache: {e}")


def count_table_items_by_tenant(table_name: str, tenant_field: str, tenant_id: str,
                                 time_field: Optional[str] = None,
                                 hours_back: Optional[int] = None) -> int:
    """Counts items in a DynamoDB table matching tenant_id (and optionally time window)."""
    try:
        table = dynamodb.Table(table_name)

        if time_field and hours_back:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()
            response = table.scan(
                FilterExpression='#t = :tid AND #tf >= :cutoff',
                ExpressionAttributeNames={'#t': tenant_field, '#tf': time_field},
                ExpressionAttributeValues={':tid': tenant_id, ':cutoff': cutoff},
                Select='COUNT'
            )
        else:
            response = table.scan(
                FilterExpression='#t = :tid',
                ExpressionAttributeNames={'#t': tenant_field},
                ExpressionAttributeValues={':tid': tenant_id},
                Select='COUNT'
            )

        count = response.get('Count', 0)

        while 'LastEvaluatedKey' in response:
            if time_field and hours_back:
                response = table.scan(
                    FilterExpression='#t = :tid AND #tf >= :cutoff',
                    ExpressionAttributeNames={'#t': tenant_field, '#tf': time_field},
                    ExpressionAttributeValues={':tid': tenant_id, ':cutoff': cutoff},
                    Select='COUNT',
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
            else:
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
    except Exception as e:
        logger.warning(f"Unexpected error counting {table_name}: {e}")
        return 0


def count_s3_objects(bucket: str, prefix: str) -> int:
    """Counts objects in an S3 bucket with given prefix."""
    if not bucket:
        return 0

    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        count = 0
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            count += page.get('KeyCount', 0)
        return count
    except Exception as e:
        logger.warning(f"Failed to count S3 objects in {bucket}/{prefix}: {e}")
        return 0


def check_agent_health(agent_id: Optional[str]) -> Dict[str, Any]:
    """Checks the health of a Bedrock agent."""
    if not agent_id:
        return {'status': 'unknown', 'reason': 'no_agent_id'}

    try:
        response = bedrock_agent.get_agent(agentId=agent_id)
        agent = response.get('agent', {})
        agent_status = agent.get('agentStatus', 'UNKNOWN')

        aliases = bedrock_agent.list_agent_aliases(agentId=agent_id)
        alias_count = len(aliases.get('agentAliasSummaries', []))

        groups = bedrock_agent.list_agent_action_groups(agentId=agent_id, agentVersion='DRAFT')
        group_count = len(groups.get('agentActionGroupSummaries', []))

        return {
            'status': 'healthy' if agent_status == 'PREPARED' else 'unhealthy',
            'agent_status': agent_status,
            'alias_count': alias_count,
            'action_group_count': group_count,
            'expected_action_groups': 4,
        }

    except bedrock_agent.exceptions.ResourceNotFoundException:
        return {'status': 'missing', 'reason': 'agent_not_found'}
    except Exception as e:
        logger.warning(f"Failed to check agent health for {agent_id}: {e}")
        return {'status': 'unknown', 'reason': str(e)}


def check_secrets_populated(tenant_id: str) -> Dict[str, Any]:
    """Checks if tenant secrets have been populated."""
    results = {}
    secret_types = ['psa', 'rmm', 'graph']

    for secret_type in secret_types:
        secret_name = f"{ENVIRONMENT}/tenants/{tenant_id}/{secret_type}"
        try:
            response = secrets_client.describe_secret(SecretId=secret_name)
            versions = response.get('VersionIdsToStages', {})
            has_values = len(versions) > 0

            populated = False
            if has_values:
                try:
                    value = secrets_client.get_secret_value(SecretId=secret_name)
                    secret_data = json.loads(value['SecretString'])
                    populated = any(v for v in secret_data.values() if v)
                except Exception:
                    populated = False

            results[secret_type] = {
                'exists': True,
                'populated': populated,
            }

        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                results[secret_type] = {'exists': False, 'populated': False}
            else:
                results[secret_type] = {'exists': False, 'populated': False, 'error': str(e)}

    all_populated = all(r.get('populated', False) for r in results.values())
    return {
        'secrets': results,
        'all_populated': all_populated,
    }


def emit_cloudwatch_metrics(tenant_id: str, tenant_record: Dict[str, Any],
                            health_score: int, overall_health: str,
                            audit_count: int, conversations_count: int,
                            kb_doc_count: int) -> None:
    """Emits tenant health metrics to CloudWatch (Step 2)."""
    if not ENABLE_STATUS_METRICS:
        return

    try:
        cloudwatch.put_metric_data(
            Namespace=STATUS_METRICS_NAMESPACE,
            MetricData=[
                {
                    'MetricName': 'HealthScore',
                    'Dimensions': [
                        {'Name': 'tenant_id', 'Value': tenant_id},
                        {'Name': 'status', 'Value': tenant_record.get('status', 'unknown')},
                    ],
                    'Value': float(health_score),
                    'Unit': 'None',
                },
                {
                    'MetricName': 'AuditRecords',
                    'Dimensions': [{'Name': 'tenant_id', 'Value': tenant_id}],
                    'Value': float(audit_count),
                    'Unit': 'Count',
                },
                {
                    'MetricName': 'Conversations',
                    'Dimensions': [{'Name': 'tenant_id', 'Value': tenant_id}],
                    'Value': float(conversations_count),
                    'Unit': 'Count',
                },
                {
                    'MetricName': 'KBDocuments',
                    'Dimensions': [{'Name': 'tenant_id', 'Value': tenant_id}],
                    'Value': float(kb_doc_count),
                    'Unit': 'Count',
                },
            ]
        )

        if overall_health == 'unhealthy':
            cloudwatch.put_metric_data(
                Namespace=STATUS_METRICS_NAMESPACE,
                MetricData=[{
                    'MetricName': 'UnhealthyTenants',
                    'Dimensions': [{'Name': 'tenant_id', 'Value': tenant_id}],
                    'Value': 1.0,
                    'Unit': 'Count',
                }]
            )
        elif overall_health == 'degraded':
            cloudwatch.put_metric_data(
                Namespace=STATUS_METRICS_NAMESPACE,
                MetricData=[{
                    'MetricName': 'DegradedTenants',
                    'Dimensions': [{'Name': 'tenant_id', 'Value': tenant_id}],
                    'Value': 1.0,
                    'Unit': 'Count',
                }]
            )

        cloudwatch.put_metric_data(
            Namespace=STATUS_METRICS_NAMESPACE,
            MetricData=[{
                'MetricName': 'StatusApiRequests',
                'Dimensions': [{'Name': 'endpoint', 'Value': 'tenant_status'}],
                'Value': 1.0,
                'Unit': 'Count',
            }]
        )

        logger.info(f"Emitted CloudWatch metrics for tenant {tenant_id} (health={health_score})")
    except Exception as e:
        logger.warning(f"Failed to emit CloudWatch metrics: {e}")


@xray_recorder.capture('compute_tenant_status')
def compute_tenant_status(tenant_id: str, tenant_record: Dict[str, Any]) -> Dict[str, Any]:
    """Computes comprehensive status for a tenant."""
    agent_id = tenant_record.get('agent_id')

    agent_health = check_agent_health(agent_id)
    secrets_status = check_secrets_populated(tenant_id)

    audit_count = count_table_items_by_tenant(AUDIT_LOG_TABLE, 'tenant_id', tenant_id)
    feedback_count = count_table_items_by_tenant(FEEDBACK_TABLE, 'tenant_id', tenant_id)

    conversations_count = 0
    try:
        table = dynamodb.Table(CONVERSATIONS_TABLE)
        response = table.scan(
            FilterExpression='begins_with(session_id, :prefix)',
            ExpressionAttributeValues={':prefix': f'{tenant_id}:'},
            Select='COUNT'
        )
        conversations_count = response.get('Count', 0)
    except Exception as e:
        logger.warning(f"Failed to count conversations for {tenant_id}: {e}")

    kb_doc_count = 0
    if ENABLE_KB and KB_DOCUMENTS_BUCKET:
        kb_doc_count = count_s3_objects(KB_DOCUMENTS_BUCKET, f"tenants/{tenant_id}/")
        kb_doc_count = max(0, kb_doc_count - 1)

    recent_activity = count_table_items_by_tenant(
        AUDIT_LOG_TABLE, 'tenant_id', tenant_id,
        time_field='timestamp', hours_back=24
    )

    health_issues = []
    health_score = 100

    if tenant_record.get('status') != 'active':
        health_score -= 50
        health_issues.append(f"tenant_status={tenant_record.get('status')}")

    if agent_health.get('status') != 'healthy':
        health_score -= 30
        health_issues.append(f"agent={agent_health.get('status')}")

    if not secrets_status.get('all_populated'):
        health_score -= 20
        health_issues.append("secrets_not_populated")

    if agent_health.get('action_group_count', 0) < agent_health.get('expected_action_groups', 4):
        health_score -= 10
        health_issues.append("missing_action_groups")

    health_score = max(0, health_score)

    if health_score >= 80:
        overall_health = 'healthy'
    elif health_score >= 50:
        overall_health = 'degraded'
    else:
        overall_health = 'unhealthy'

    emit_cloudwatch_metrics(
        tenant_id=tenant_id,
        tenant_record=tenant_record,
        health_score=health_score,
        overall_health=overall_health,
        audit_count=audit_count,
        conversations_count=conversations_count,
        kb_doc_count=kb_doc_count,
    )

    return {
        'tenant_id': tenant_id,
        'display_name': tenant_record.get('display_name', tenant_id),
        'status': tenant_record.get('status'),
        'management_mode': tenant_record.get('management_mode', 'unknown'),
        'overall_health': overall_health,
        'health_score': health_score,
        'health_issues': health_issues,
        'agent': agent_health,
        'secrets': secrets_status,
        'resources': {
            'audit_records': audit_count,
            'feedback_records': feedback_count,
            'conversations': conversations_count,
            'kb_documents': kb_doc_count,
        },
        'activity': {
            'last_24h_operations': recent_activity,
        },
        'computed_at': datetime.now(timezone.utc).isoformat(),
    }


@xray_recorder.capture('get_tenant_status')
def get_tenant_status(tenant_id: str, deep: bool = False) -> Optional[Dict[str, Any]]:
    """Gets status for a tenant, using cache if available."""
    table = dynamodb.Table(TENANT_REGISTRY_TABLE)
    response = table.get_item(Key={'tenant_id': tenant_id})
    tenant = response.get('Item')

    if not tenant:
        return None

    cache_key = f"tenant:{tenant_id}"

    if not deep:
        cached = get_cached_status(cache_key)
        if cached:
            cached['from_cache'] = True
            return cached

    status = compute_tenant_status(tenant_id, tenant)
    status['from_cache'] = False

    store_cached_status(cache_key, status)

    return status


@xray_recorder.capture('get_system_status')
def get_system_status() -> Dict[str, Any]:
    """Computes system-wide health status."""
    table = dynamodb.Table(TENANT_REGISTRY_TABLE)
    response = table.scan(ProjectionExpression='tenant_id, #s, display_name, management_mode',
                         ExpressionAttributeNames={'#s': 'status'})
    tenants = response.get('Items', [])

    while 'LastEvaluatedKey' in response:
        response = table.scan(
            ProjectionExpression='tenant_id, #s, display_name, management_mode',
            ExpressionAttributeNames={'#s': 'status'},
            ExclusiveStartKey=response['LastEvaluatedKey']
        )
        tenants.extend(response.get('Items', []))

    status_counts = {}
    management_counts = {}
    for t in tenants:
        s = t.get('status', 'unknown')
        status_counts[s] = status_counts.get(s, 0) + 1

        m = t.get('management_mode', 'unknown')
        management_counts[m] = management_counts.get(m, 0) + 1

    lambda_healthy = True
    try:
        response = cloudwatch.get_metric_statistics(
            Namespace='AWS/Lambda',
            MetricName='Errors',
            Dimensions=[{'Name': 'FunctionName', 'Value': f'{ENVIRONMENT}-msp-triage-tenant-onboarding'}],
            StartTime=datetime.now(timezone.utc) - timedelta(hours=1),
            EndTime=datetime.now(timezone.utc),
            Period=3600,
            Statistics=['Sum']
        )
        error_count = sum(dp.get('Sum', 0) for dp in response.get('Datapoints', []))
        lambda_healthy = error_count == 0
    except Exception as e:
        logger.warning(f"Failed to check Lambda health: {e}")

    active_tenants = status_counts.get('active', 0)
    total_tenants = len(tenants)

    if total_tenants == 0:
        system_health = 'idle'
    elif active_tenants == total_tenants and lambda_healthy:
        system_health = 'healthy'
    elif active_tenants > 0:
        system_health = 'degraded'
    else:
        system_health = 'unhealthy'

    if ENABLE_STATUS_METRICS:
        try:
            cloudwatch.put_metric_data(
                Namespace=STATUS_METRICS_NAMESPACE,
                MetricData=[
                    {'MetricName': 'TotalTenants', 'Value': float(total_tenants), 'Unit': 'Count'},
                    {'MetricName': 'ActiveTenants', 'Value': float(active_tenants), 'Unit': 'Count'},
                ]
            )
        except Exception as e:
            logger.warning(f"Failed to emit system metrics: {e}")

    return {
        'system_health': system_health,
        'api_healthy': True,
        'lambda_healthy': lambda_healthy,
        'tenants': {
            'total': total_tenants,
            'by_status': status_counts,
            'by_management_mode': management_counts,
        },
        'computed_at': datetime.now(timezone.utc).isoformat(),
    }


@xray_recorder.capture('get_all_tenant_statuses')
def get_all_tenant_statuses() -> Dict[str, Any]:
    """Gets status for all tenants (uses cache where possible)."""
    table = dynamodb.Table(TENANT_REGISTRY_TABLE)
    response = table.scan()
    tenants = response.get('Items', [])

    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        tenants.extend(response.get('Items', []))

    statuses = []
    for tenant in tenants:
        tenant_id = tenant.get('tenant_id')
        status = get_tenant_status(tenant_id, deep=False)
        if status:
            statuses.append(status)

    statuses.sort(key=lambda s: s.get('health_score', 0))

    return {
        'tenants': statuses,
        'count': len(statuses),
        'computed_at': datetime.now(timezone.utc).isoformat(),
    }


@xray_recorder.capture('get_aggregated_metrics')
def get_aggregated_metrics() -> Dict[str, Any]:
    """Computes aggregated metrics across all tenants."""
    all_statuses = get_all_tenant_statuses()

    total_audit = sum(t.get('resources', {}).get('audit_records', 0) for t in all_statuses['tenants'])
    total_feedback = sum(t.get('resources', {}).get('feedback_records', 0) for t in all_statuses['tenants'])
    total_conversations = sum(t.get('resources', {}).get('conversations', 0) for t in all_statuses['tenants'])
    total_kb_docs = sum(t.get('resources', {}).get('kb_documents', 0) for t in all_statuses['tenants'])
    total_24h_ops = sum(t.get('activity', {}).get('last_24h_operations', 0) for t in all_statuses['tenants'])

    health_distribution = {}
    management_distribution = {}
    for t in all_statuses['tenants']:
        h = t.get('overall_health', 'unknown')
        health_distribution[h] = health_distribution.get(h, 0) + 1

        m = t.get('management_mode', 'unknown')
        management_distribution[m] = management_distribution.get(m, 0) + 1

    return {
        'totals': {
            'tenants': len(all_statuses['tenants']),
            'audit_records': total_audit,
            'feedback_records': total_feedback,
            'conversations': total_conversations,
            'kb_documents': total_kb_docs,
            'operations_last_24h': total_24h_ops,
        },
        'health_distribution': health_distribution,
        'management_distribution': management_distribution,
        'computed_at': datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# ANALYTICS ENDPOINTS (Advanced Analytics)
# =============================================================================

@xray_recorder.capture('get_analytics_health_trends')
def get_analytics_health_trends(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /analytics/health-trends — Get health trend analytics."""
    if not ANALYTICS_SUMMARY_TABLE:
        return {'statusCode': 400, 'body': json.dumps({'error': 'Analytics not enabled'})}

    try:
        query_params = event.get('queryStringParameters') or {}
        days = int(query_params.get('days', '30'))
        days = min(max(days, 1), 365)

        table = dynamodb.Table(ANALYTICS_SUMMARY_TABLE)
        response = table.query(
            KeyConditionExpression='#st = :type',
            ExpressionAttributeNames={'#st': 'summary_type'},
            ExpressionAttributeValues={':type': 'health_trends'},
            ScanIndexForward=False,
            Limit=1
        )

        items = response.get('Items', [])
        if not items:
            return {'statusCode': 404, 'body': json.dumps({'error': 'No health trends data available. Run analytics aggregation first.'})}

        data = json.loads(items[0].get('data', '{}'))

        if 'daily_averages' in data:
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
            data['daily_averages'] = [
                d for d in data['daily_averages']
                if d.get('date', '') >= cutoff_date
            ]

        return {
            'statusCode': 200,
            'body': json.dumps({
                'health_trends': convert_decimals(data),
                'computed_at': items[0].get('computed_at'),
                'requested_days': days,
            })
        }

    except Exception as e:
        logger.exception(f"Failed to get health trends")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


@xray_recorder.capture('get_analytics_webhook_delivery')
def get_analytics_webhook_delivery(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /analytics/webhook-delivery — Get webhook delivery analytics."""
    if not ANALYTICS_SUMMARY_TABLE:
        return {'statusCode': 400, 'body': json.dumps({'error': 'Analytics not enabled'})}

    try:
        table = dynamodb.Table(ANALYTICS_SUMMARY_TABLE)
        response = table.query(
            KeyConditionExpression='#st = :type',
            ExpressionAttributeNames={'#st': 'summary_type'},
            ExpressionAttributeValues={':type': 'webhook_delivery'},
            ScanIndexForward=False,
            Limit=1
        )

        items = response.get('Items', [])
        if not items:
            return {'statusCode': 404, 'body': json.dumps({'error': 'No webhook delivery data available. Run analytics aggregation first.'})}

        data = json.loads(items[0].get('data', '{}'))

        return {
            'statusCode': 200,
            'body': json.dumps({
                'webhook_delivery': convert_decimals(data),
                'computed_at': items[0].get('computed_at'),
            })
        }

    except Exception as e:
        logger.exception(f"Failed to get webhook delivery stats")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


@xray_recorder.capture('get_analytics_rule_effectiveness')
def get_analytics_rule_effectiveness(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /analytics/rule-effectiveness — Get rule effectiveness analytics."""
    if not ANALYTICS_SUMMARY_TABLE:
        return {'statusCode': 400, 'body': json.dumps({'error': 'Analytics not enabled'})}

    try:
        table = dynamodb.Table(ANALYTICS_SUMMARY_TABLE)
        response = table.query(
            KeyConditionExpression='#st = :type',
            ExpressionAttributeNames={'#st': 'summary_type'},
            ExpressionAttributeValues={':type': 'rule_effectiveness'},
            ScanIndexForward=False,
            Limit=1
        )

        items = response.get('Items', [])
        if not items:
            return {'statusCode': 404, 'body': json.dumps({'error': 'No rule effectiveness data available. Run analytics aggregation first.'})}

        data = json.loads(items[0].get('data', '{}'))

        return {
            'statusCode': 200,
            'body': json.dumps({
                'rule_effectiveness': convert_decimals(data),
                'computed_at': items[0].get('computed_at'),
            })
        }

    except Exception as e:
        logger.exception(f"Failed to get rule effectiveness stats")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


@xray_recorder.capture('get_analytics_executive_summary')
def get_analytics_executive_summary(event: Dict[str, Any]) -> Dict[str, Any]:
    """GET /analytics/executive-summary — Get executive summary."""
    if not ANALYTICS_SUMMARY_TABLE:
        return {'statusCode': 400, 'body': json.dumps({'error': 'Analytics not enabled'})}

    try:
        table = dynamodb.Table(ANALYTICS_SUMMARY_TABLE)
        response = table.query(
            KeyConditionExpression='#st = :type',
            ExpressionAttributeNames={'#st': 'summary_type'},
            ExpressionAttributeValues={':type': 'executive_summary'},
            ScanIndexForward=False,
            Limit=1
        )

        items = response.get('Items', [])
        if not items:
            return {'statusCode': 404, 'body': json.dumps({'error': 'No executive summary available. Run analytics aggregation first.'})}

        data = json.loads(items[0].get('data', '{}'))

        return {
            'statusCode': 200,
            'body': json.dumps({
                'executive_summary': convert_decimals(data),
                'computed_at': items[0].get('computed_at'),
            })
        }

    except Exception as e:
        logger.exception(f"Failed to get executive summary")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


# =============================================================================
# LAMBDA HANDLER
# =============================================================================

@xray_recorder.capture('onboarding_handler')
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main entry point for the onboarding/status/analytics API.

    Routes:
    - POST   /tenants              → Create tenant OR adopt existing (Hybrid Mode)
    - GET    /tenants              → List tenants (basic)
    - GET    /tenants/{id}         → Get tenant record
    - DELETE /tenants/{id}         → Deprovision tenant
    - GET    /status               → System-wide health
    - GET    /status/tenants       → List tenants with metrics
    - GET    /status/tenants/{id}  → Detailed tenant status
    - GET    /status/tenants/{id}/health → Deep health check
    - GET    /status/metrics       → Aggregated metrics
    - GET    /analytics/health-trends       → Health trend analytics
    - GET    /analytics/webhook-delivery    → Webhook delivery stats
    - GET    /analytics/rule-effectiveness  → Custom rule effectiveness
    - GET    /analytics/executive-summary   → Executive summary
    """
    try:
        route_key = event.get('routeKey') or event.get('requestContext', {}).get('routeKey', '')
        method = route_key.split(' ')[0] if route_key else event.get('httpMethod', 'GET')
        path = route_key.split(' ')[1] if route_key else event.get('path', '')
        path_parts = parse_path(path)

        # =========================================================================
        # POST /tenants — Create new tenant OR adopt existing (Phase D Hybrid Mode)
        # =========================================================================
        if method == 'POST' and path_parts == ['tenants']:
            body = json.loads(event.get('body', '{}') or '{}')

            error = validate_input(body)
            if error:
                return {'statusCode': 400, 'body': json.dumps({'error': error})}

            tenant_id = body['tenant_id']

            # HYBRID MODE: Check if tenant already exists
            existing = check_existing_tenant(tenant_id)
            if existing:
                logger.info(f"Tenant {tenant_id} already exists, checking for hybrid adoption")

                agent_id = existing.get('agent_id')
                if agent_id:
                    verification = verify_existing_agent(agent_id)

                    if verification.get('healthy'):
                        try:
                            result = adopt_existing_tenant(tenant_id, body, existing)
                            result['agent_verification'] = verification
                            return {'statusCode': 200, 'body': json.dumps(result)}
                        except Exception as e:
                            logger.exception(f"Failed to adopt existing tenant {tenant_id}")
                            return {'statusCode': 500, 'body': json.dumps({'error': f'Adoption failed: {str(e)}'})}
                    else:
                        return {
                            'statusCode': 409,
                            'body': json.dumps({
                                'error': f'Tenant {tenant_id} exists but agent is unhealthy',
                                'verification': verification,
                                'suggestion': 'Fix the agent health issues before adopting, or delete the tenant and recreate via API',
                            })
                        }
                else:
                    current_status = existing.get('status')
                    if current_status == 'provisioning':
                        return {
                            'statusCode': 409,
                            'body': json.dumps({
                                'error': f'Tenant {tenant_id} is still provisioning',
                                'suggestion': 'Wait for provisioning to complete, then retry',
                            })
                        }
                    else:
                        return {
                            'statusCode': 409,
                            'body': json.dumps({
                                'error': f'Tenant {tenant_id} exists in unexpected state: {current_status}',
                                'suggestion': 'Check tenant status via GET /tenants/{tenant_id}',
                            })
                        }

            # STANDARD PATH: Create new tenant via API
            try:
                secret_arns = create_tenant_secrets(tenant_id)
                create_s3_folders(tenant_id)
                create_tenant_record(tenant_id, body, secret_arns)
                message_id = queue_provisioning(tenant_id)

                return {
                    'statusCode': 202,
                    'body': json.dumps({
                        'tenant_id': tenant_id,
                        'status': 'provisioning',
                        'management_mode': 'api',
                        'message': 'Tenant creation initiated via API.',
                        'message_id': message_id,
                        'estimated_completion_minutes': 15,
                    })
                }

            except ValueError as e:
                return {'statusCode': 409, 'body': json.dumps({'error': str(e)})}
            except Exception as e:
                logger.exception(f"Failed to onboard tenant {tenant_id}")
                return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}

        # =========================================================================
        # GET /tenants — List all tenants (basic)
        # =========================================================================
        elif method == 'GET' and path_parts == ['tenants']:
            try:
                table = dynamodb.Table(TENANT_REGISTRY_TABLE)
                response = table.scan()
                items = response.get('Items', [])

                while 'LastEvaluatedKey' in response:
                    response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
                    items.extend(response.get('Items', []))

                return {
                    'statusCode': 200,
                    'body': json.dumps({
                        'tenants': convert_decimals(items),
                        'count': len(items)
                    })
                }

            except Exception as e:
                logger.exception(f"Failed to list tenants")
                return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}

        # =========================================================================
        # GET /tenants/{tenant_id} — Get tenant record (basic)
        # =========================================================================
        elif method == 'GET' and len(path_parts) == 2 and path_parts[0] == 'tenants':
            tenant_id = path_parts[1]
            try:
                table = dynamodb.Table(TENANT_REGISTRY_TABLE)
                response = table.get_item(Key={'tenant_id': tenant_id})
                item = response.get('Item')

                if not item:
                    return {'statusCode': 404, 'body': json.dumps({'error': f'Tenant {tenant_id} not found'})}

                return {'statusCode': 200, 'body': json.dumps(convert_decimals(item))}

            except Exception as e:
                logger.exception(f"Failed to get tenant {tenant_id}")
                return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}

        # =========================================================================
        # DELETE /tenants/{tenant_id} — Deprovision tenant (Phase B)
        # =========================================================================
        elif method == 'DELETE' and len(path_parts) == 2 and path_parts[0] == 'tenants':
            tenant_id, preserve_data, error = validate_deprovision_request(event)

            if error:
                return {'statusCode': 400, 'body': json.dumps({'error': error})}

            try:
                result = start_deprovisioning(tenant_id, preserve_data)
                return {'statusCode': 202, 'body': json.dumps(result)}

            except ValueError as e:
                return {'statusCode': 409, 'body': json.dumps({'error': str(e)})}
            except ClientError as e:
                if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                    return {
                        'statusCode': 409,
                        'body': json.dumps({'error': f'Tenant {tenant_id} state changed during request. Please retry.'})
                    }
                logger.exception(f"Failed to start deprovisioning for {tenant_id}")
                return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}
            except Exception as e:
                logger.exception(f"Unhandled error deprovisioning {tenant_id}")
                return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}

        # =========================================================================
        # STATUS ENDPOINTS (Phase C)
        # =========================================================================

        # GET /status — System-wide health
        elif method == 'GET' and path_parts == ['status']:
            try:
                status = get_system_status()
                return {'statusCode': 200, 'body': json.dumps(status)}
            except Exception as e:
                logger.exception(f"Failed to get system status")
                return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}

        # GET /status/tenants — List all tenants with computed metrics
        elif method == 'GET' and path_parts == ['status', 'tenants']:
            try:
                statuses = get_all_tenant_statuses()
                return {'statusCode': 200, 'body': json.dumps(convert_decimals(statuses))}
            except Exception as e:
                logger.exception(f"Failed to get all tenant statuses")
                return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}

        # GET /status/tenants/{tenant_id}/health — Deep health check (bypasses cache)
        elif method == 'GET' and len(path_parts) == 4 and path_parts[0:3] == ['status', 'tenants'] and path_parts[3] == 'health':
            tenant_id = path_parts[2]
            try:
                status = get_tenant_status(tenant_id, deep=True)
                if not status:
                    return {'statusCode': 404, 'body': json.dumps({'error': f'Tenant {tenant_id} not found'})}
                return {'statusCode': 200, 'body': json.dumps(convert_decimals(status))}
            except Exception as e:
                logger.exception(f"Failed to get health for tenant {tenant_id}")
                return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}

        # GET /status/tenants/{tenant_id} — Detailed status for one tenant (cached)
        elif method == 'GET' and len(path_parts) == 3 and path_parts[0:2] == ['status', 'tenants']:
            tenant_id = path_parts[2]
            try:
                status = get_tenant_status(tenant_id, deep=False)
                if not status:
                    return {'statusCode': 404, 'body': json.dumps({'error': f'Tenant {tenant_id} not found'})}
                return {'statusCode': 200, 'body': json.dumps(convert_decimals(status))}
            except Exception as e:
                logger.exception(f"Failed to get status for tenant {tenant_id}")
                return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}

        # GET /status/metrics — Aggregated metrics
        elif method == 'GET' and path_parts == ['status', 'metrics']:
            try:
                metrics = get_aggregated_metrics()
                return {'statusCode': 200, 'body': json.dumps(convert_decimals(metrics))}
            except Exception as e:
                logger.exception(f"Failed to get aggregated metrics")
                return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}

        # =========================================================================
        # ANALYTICS ENDPOINTS (Advanced Analytics)
        # =========================================================================

        # GET /analytics/health-trends
        elif method == 'GET' and path_parts == ['analytics', 'health-trends']:
            return get_analytics_health_trends(event)

        # GET /analytics/webhook-delivery
        elif method == 'GET' and path_parts == ['analytics', 'webhook-delivery']:
            return get_analytics_webhook_delivery(event)

        # GET /analytics/rule-effectiveness
        elif method == 'GET' and path_parts == ['analytics', 'rule-effectiveness']:
            return get_analytics_rule_effectiveness(event)

        # GET /analytics/executive-summary
        elif method == 'GET' and path_parts == ['analytics', 'executive-summary']:
            return get_analytics_executive_summary(event)

        # =========================================================================
        # Unknown route
        # =========================================================================
        else:
            return {'statusCode': 404, 'body': json.dumps({'error': f'Not found: {method} {path}'})}

    except Exception as e:
        logger.exception(f"Unhandled error in handler")
        return {'statusCode': 500, 'body': json.dumps({'error': f'Internal error: {str(e)}'})}
