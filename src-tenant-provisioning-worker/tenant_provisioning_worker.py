"""
Tenant Provisioning Worker (Provisioning + Deprovisioning)

Processes SQS messages to manage tenant lifecycle:

PROVISIONING (slow path, 5-30 minutes):
1. Create Bedrock agent via SDK
2. Create action groups (identity, ticket, device, calendar)
3. Create agent alias
4. Attach KB (if enabled)
5. Update DynamoDB record with agent_id and agent_alias_id
6. Update status to "active"
7. Send notification email

DEPROVISIONING (Phase B, 2-10 minutes):
1. Drain period (wait for in-flight operations)
2. Delete Bedrock resources (KB disassociation, action groups, aliases, agent)
3. Optionally delete tenant data from shared tables
4. Permanently purge tenant S3 data across ALL tenant-scoped buckets,
   including version history (versioned-bucket aware)
5. Trigger KB re-ingestion to purge vectors from AOSS (hard delete only)
6. Delete secrets (7-day recovery window)
7. Update status to "deleted" or "delete_failed"
8. Send notification
"""

import json
import os
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
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
BEDROCK_AGENT_ROLE_ARN = os.environ.get('BEDROCK_AGENT_ROLE_ARN')
AGENT_MODEL_ID = os.environ.get('AGENT_MODEL_ID')
GUARDRAIL_ID = os.environ.get('GUARDRAIL_ID')
GUARDRAIL_VERSION = os.environ.get('GUARDRAIL_VERSION')
AGENT_SCHEMAS_BUCKET = os.environ.get('AGENT_SCHEMAS_BUCKET')
DEFAULT_INSTRUCTION = os.environ.get('DEFAULT_INSTRUCTION', '')
IDLE_SESSION_TTL = int(os.environ.get('IDLE_SESSION_TTL', '1800'))
ENABLE_KB = os.environ.get('ENABLE_KB', 'false').lower() == 'true'
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')
DRAIN_SECONDS = int(os.environ.get('DRAIN_SECONDS', '60'))
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')

# S3 purge coverage — all tenant-scoped buckets
FEW_SHOT_EXAMPLES_BUCKET = os.environ.get('FEW_SHOT_EXAMPLES_BUCKET', '')
CUSTOMER_BRANDING_BUCKET = os.environ.get('CUSTOMER_BRANDING_BUCKET', '')
KB_DOCUMENTS_BUCKET = os.environ.get('KB_DOCUMENTS_BUCKET', '')

# KB vector purge
KNOWLEDGE_BASE_ID = os.environ.get('KNOWLEDGE_BASE_ID', '')
DATA_SOURCE_ID = os.environ.get('DATA_SOURCE_ID', '')

# Table name configuration
AUDIT_LOG_TABLE = os.environ.get('AUDIT_LOG_TABLE', f'{ENVIRONMENT}-msp-triage-agent-audit-log')
FEEDBACK_TABLE = os.environ.get('FEEDBACK_TABLE', f'{ENVIRONMENT}-msp-triage-agent-feedback')
CONVERSATIONS_TABLE = os.environ.get('CONVERSATIONS_TABLE', f'{ENVIRONMENT}-msp-triage-agent-conversations')

# =============================================================================
# CLIENT INITIALIZATION
# =============================================================================

dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
bedrock_agent = boto3.client('bedrock-agent', region_name=AWS_REGION)
ses_client = boto3.client('ses', region_name=AWS_REGION)
lambda_client = boto3.client('lambda', region_name=AWS_REGION)
secrets_client = boto3.client('secretsmanager', region_name=AWS_REGION)
s3_client = boto3.client('s3', region_name=AWS_REGION)
s3 = boto3.resource('s3', region_name=AWS_REGION)


# =============================================================================
# TENANT RECORD HELPERS
# =============================================================================

def get_tenant_record(tenant_id: str) -> Optional[Dict[str, Any]]:
    """Fetches the tenant record from DynamoDB."""
    table = dynamodb.Table(TENANT_REGISTRY_TABLE)
    response = table.get_item(Key={'tenant_id': tenant_id})
    return response.get('Item')


def update_tenant_status(tenant_id: str, status: str, **kwargs) -> None:
    """Updates the tenant status and optional fields in DynamoDB."""
    table = dynamodb.Table(TENANT_REGISTRY_TABLE)

    update_expr = "SET #s = :status, updated_at = :ts"
    expr_names = {'#s': 'status'}
    expr_values = {
        ':status': status,
        ':ts': datetime.now(timezone.utc).isoformat()
    }

    for key, value in kwargs.items():
        update_expr += f", {key} = :{key}"
        expr_values[f":{key}"] = value

    table.update_item(
        Key={'tenant_id': tenant_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values
    )


# =============================================================================
# PROVISIONING HELPERS
# =============================================================================

def wait_for_agent_prepared(agent_id: str, max_wait_seconds: int = 600) -> None:
    """Waits for the agent to reach PREPARED status."""
    logger.info(f"Waiting for agent {agent_id} to be prepared...")
    start = time.time()

    while time.time() - start < max_wait_seconds:
        response = bedrock_agent.get_agent(agentId=agent_id)
        status = response['agent']['agentStatus']

        if status == 'PREPARED':
            logger.info(f"Agent {agent_id} is PREPARED")
            return
        elif status in ('FAILED', 'DELETING', 'DELETE_FAILED'):
            raise RuntimeError(f"Agent {agent_id} entered terminal status: {status}")

        logger.info(f"Agent status: {status}, waiting...")
        time.sleep(15)

    raise TimeoutError(f"Agent {agent_id} did not reach PREPARED status within {max_wait_seconds}s")


def find_agent_id_by_name(agent_name: str) -> Optional[str]:
    """Finds an existing agent by name. Returns agent_id if found."""
    try:
        paginator = bedrock_agent.get_paginator('list_agents')
        for page in paginator.paginate():
            for agent in page.get('agentSummaries', []):
                if agent.get('agentName') == agent_name:
                    return agent['agentId']
        return None
    except Exception as e:
        logger.warning(f"Failed to list agents: {e}")
        return None


@xray_recorder.capture('create_bedrock_agent')
def create_bedrock_agent(tenant_id: str, tenant_record: Dict[str, Any]) -> str:
    """Creates a Bedrock agent for the tenant. Returns agent_id."""
    agent_name = f"{ENVIRONMENT}-it-concierge-{tenant_id}"
    display_name = tenant_record.get('display_name', tenant_id)

    existing_agent_id = find_agent_id_by_name(agent_name)
    if existing_agent_id:
        logger.info(f"Agent {agent_name} already exists (id: {existing_agent_id}), reusing")
        wait_for_agent_prepared(existing_agent_id)
        return existing_agent_id

    logger.info(f"Creating Bedrock agent for tenant {tenant_id}")

    response = bedrock_agent.create_agent(
        agentName=agent_name,
        agentResourceRoleArn=BEDROCK_AGENT_ROLE_ARN,
        foundationModel=AGENT_MODEL_ID,
        instruction=DEFAULT_INSTRUCTION,
        description=f"AI IT Concierge for {display_name}",
        idleSessionTTLInSeconds=IDLE_SESSION_TTL,
        guardrailConfiguration={
            'guardrailIdentifier': GUARDRAIL_ID,
            'guardrailVersion': GUARDRAIL_VERSION
        }
    )

    agent_id = response['agent']['agentId']
    logger.info(f"Created agent {agent_id} for tenant {tenant_id}")

    wait_for_agent_prepared(agent_id)
    return agent_id


@xray_recorder.capture('create_action_group')
def create_action_group(agent_id: str, agent_version: str, group_name: str,
                       schema_key: str, lambda_arn: str, description: str) -> str:
    """Creates an action group for the agent. Returns action_group_id."""
    try:
        response = bedrock_agent.create_agent_action_group(
            agentId=agent_id,
            agentVersion=agent_version,
            actionGroupName=group_name,
            description=description,
            actionGroupExecutor={'lambda': lambda_arn},
            apiSchema={'s3': {'s3BucketName': AGENT_SCHEMAS_BUCKET, 's3ObjectKey': schema_key}}
        )
        return response['agentActionGroup']['agentActionGroupId']
    except ClientError as e:
        if 'already exists' in str(e).lower():
            logger.warning(f"Action group {group_name} already exists, skipping")
            return 'existing'
        raise


@xray_recorder.capture('create_agent_alias')
def create_agent_alias(agent_id: str) -> str:
    """Creates an agent alias. Returns alias_id."""
    try:
        response = bedrock_agent.create_agent_alias(
            agentId=agent_id,
            agentAliasName='latest',
            description='Latest version'
        )
        return response['agentAlias']['agentAliasId']
    except ClientError as e:
        if 'already exists' in str(e).lower():
            logger.warning("Alias 'latest' already exists")
            aliases = bedrock_agent.list_agent_aliases(agentId=agent_id)
            for alias in aliases.get('agentAliasSummaries', []):
                if alias['agentAliasName'] == 'latest':
                    return alias['agentAliasId']
        raise


@xray_recorder.capture('provision_tenant')
def provision_tenant(tenant_id: str) -> Dict[str, Any]:
    """Provisions all Bedrock resources for a tenant."""
    tenant_record = get_tenant_record(tenant_id)
    if not tenant_record:
        raise ValueError(f"Tenant {tenant_id} not found")

    agent_id = create_bedrock_agent(tenant_id, tenant_record)
    update_tenant_status(tenant_id, 'provisioning', agent_id=agent_id)

    agent_response = bedrock_agent.get_agent(agentId=agent_id)
    agent_version = agent_response['agent']['agentVersion']

    logger.info(f"Preparing agent {agent_id}")
    bedrock_agent.prepare_agent(agentId=agent_id)
    wait_for_agent_prepared(agent_id)

    project = 'msp-triage'
    action_groups = [
        {
            'name': 'identity_tools',
            'schema_key': 'identity-tools-schema.json',
            'lambda_name': f"{project}-{ENVIRONMENT}-identity-tools",
            'description': 'Identity operations (verify, reset password, unlock account)'
        },
        {
            'name': 'ticket_tools',
            'schema_key': 'ticket-tools-schema.json',
            'lambda_name': f"{project}-{ENVIRONMENT}-ticket-tools",
            'description': 'Ticket operations (create, check status, list)'
        },
        {
            'name': 'device_tools',
            'schema_key': 'device-tools-schema.json',
            'lambda_name': f"{project}-{ENVIRONMENT}-device-tools",
            'description': 'Device operations (list, status, alerts)'
        },
        {
            'name': 'calendar_tools',
            'schema_key': 'calendar-tools-schema.json',
            'lambda_name': f"{project}-{ENVIRONMENT}-calendar-tools",
            'description': 'Calendar operations (view, free time, book rooms)'
        },
    ]

    for group in action_groups:
        try:
            lambda_response = lambda_client.get_function(FunctionName=group['lambda_name'])
            lambda_arn = lambda_response['Configuration']['FunctionArn']

            create_action_group(
                agent_id=agent_id,
                agent_version=agent_version,
                group_name=group['name'],
                schema_key=group['schema_key'],
                lambda_arn=lambda_arn,
                description=group['description']
            )
            logger.info(f"Created action group {group['name']}")

            try:
                lambda_client.add_permission(
                    FunctionName=group['lambda_name'],
                    StatementId=f"AllowBedrockAgent-{tenant_id}-{group['name']}",
                    Action='lambda:InvokeFunction',
                    Principal='bedrock.amazonaws.com',
                    SourceArn=f"arn:aws:bedrock:{AWS_REGION}:{os.environ.get('AWS_ACCOUNT_ID', '')}:agent/{agent_id}"
                )
            except ClientError as e:
                if 'already exists' not in str(e).lower():
                    logger.warning(f"Failed to add Lambda permission: {e}")

        except Exception as e:
            logger.error(f"Failed to create action group {group['name']}: {e}")

    logger.info(f"Re-preparing agent {agent_id} after action group attachment")
    bedrock_agent.prepare_agent(agentId=agent_id)
    wait_for_agent_prepared(agent_id)

    alias_id = create_agent_alias(agent_id)

    return {
        'agent_id': agent_id,
        'agent_alias_id': alias_id,
    }


# =============================================================================
# DEPROVISIONING HELPERS (PHASE B)
# =============================================================================

@xray_recorder.capture('cleanup_bedrock_resources')
def cleanup_bedrock_resources(tenant_id: str, agent_id: Optional[str]) -> Dict[str, Any]:
    """Deletes all Bedrock resources for a tenant in correct order."""
    results = {
        'agent_id': agent_id,
        'action_groups_deleted': [],
        'aliases_deleted': [],
        'knowledge_bases_disassociated': [],
        'agent_deleted': False,
        'errors': [],
    }

    if not agent_id:
        logger.warning(f"No agent_id for tenant {tenant_id}, skipping Bedrock cleanup")
        return results

    try:
        bedrock_agent.get_agent(agentId=agent_id)
    except bedrock_agent.exceptions.ResourceNotFoundException:
        logger.info(f"Agent {agent_id} already deleted")
        results['agent_deleted'] = True
        return results
    except ClientError as e:
        results['errors'].append(f"Failed to get agent: {str(e)}")
        return results

    try:
        kb_response = bedrock_agent.list_agent_knowledge_bases(
            agentId=agent_id, agentVersion='DRAFT'
        )
        for kb in kb_response.get('agentKnowledgeBaseSummaries', []):
            try:
                bedrock_agent.disassociate_agent_knowledge_base(
                    agentId=agent_id,
                    agentVersion='DRAFT',
                    knowledgeBaseId=kb['knowledgeBaseId']
                )
                results['knowledge_bases_disassociated'].append(kb['knowledgeBaseId'])
                logger.info(f"Disassociated KB {kb['knowledgeBaseId']} from agent {agent_id}")
            except Exception as e:
                results['errors'].append(f"Failed to disassociate KB {kb['knowledgeBaseId']}: {str(e)}")
    except Exception as e:
        logger.info(f"Could not list KBs for agent {agent_id}: {e}")

    try:
        groups = bedrock_agent.list_agent_action_groups(
            agentId=agent_id, agentVersion='DRAFT'
        )
        for group in groups.get('agentActionGroupSummaries', []):
            group_name = group['actionGroupName']
            try:
                bedrock_agent.delete_agent_action_group(
                    agentId=agent_id,
                    agentVersion='DRAFT',
                    actionGroupName=group_name
                )
                results['action_groups_deleted'].append(group_name)
                logger.info(f"Deleted action group {group_name}")
            except Exception as e:
                results['errors'].append(f"Failed to delete action group {group_name}: {str(e)}")
    except Exception as e:
        results['errors'].append(f"Failed to list action groups: {str(e)}")

    try:
        aliases = bedrock_agent.list_agent_aliases(agentId=agent_id)
        for alias in aliases.get('agentAliasSummaries', []):
            alias_id = alias['agentAliasId']
            alias_name = alias['agentAliasName']
            try:
                bedrock_agent.delete_agent_alias(
                    agentId=agent_id, agentAliasId=alias_id
                )
                results['aliases_deleted'].append(alias_name)
                logger.info(f"Deleted alias {alias_name}")
            except Exception as e:
                results['errors'].append(f"Failed to delete alias {alias_name}: {str(e)}")
    except Exception as e:
        results['errors'].append(f"Failed to list aliases: {str(e)}")

    try:
        bedrock_agent.delete_agent(agentId=agent_id)
        results['agent_deleted'] = True
        logger.info(f"Deleted agent {agent_id}")
    except Exception as e:
        results['errors'].append(f"Failed to delete agent: {str(e)}")

    return results


@xray_recorder.capture('cleanup_tenant_data')
def cleanup_tenant_data(tenant_id: str) -> Dict[str, Any]:
    """Deletes tenant-specific data from shared tables (preserve_data=false only)."""
    results = {
        'audit_records_deleted': 0,
        'feedback_records_deleted': 0,
        'conversations_deleted': 0,
        'errors': [],
    }

    tables_to_clean = [
        {
            'name': AUDIT_LOG_TABLE,
            'tenant_field': 'tenant_id',
            'key_schema': ['audit_id', 'timestamp'],
            'result_key': 'audit_records_deleted',
        },
        {
            'name': FEEDBACK_TABLE,
            'tenant_field': 'tenant_id',
            'key_schema': ['feedback_id'],
            'result_key': 'feedback_records_deleted',
        },
        {
            'name': CONVERSATIONS_TABLE,
            'tenant_field': None,
            'key_schema': ['session_id'],
            'result_key': 'conversations_deleted',
            'key_prefix': f"{tenant_id}:",
        },
    ]

    for table_config in tables_to_clean:
        table_name = table_config['name']
        tenant_field = table_config['tenant_field']
        key_schema = table_config['key_schema']
        result_key = table_config['result_key']
        key_prefix = table_config.get('key_prefix')

        try:
            table = dynamodb.Table(table_name)

            if tenant_field:
                scan_kwargs = {
                    'FilterExpression': '#t = :tid',
                    'ExpressionAttributeNames': {'#t': tenant_field},
                    'ExpressionAttributeValues': {':tid': tenant_id},
                }
            elif key_prefix:
                scan_kwargs = {
                    'FilterExpression': 'begins_with(session_id, :prefix)',
                    'ExpressionAttributeValues': {':prefix': key_prefix},
                }
            else:
                continue

            deleted_count = 0
            response = table.scan(**scan_kwargs)

            while True:
                for item in response.get('Items', []):
                    try:
                        key = {k: item[k] for k in key_schema if k in item}
                        if len(key) == len(key_schema):
                            table.delete_item(Key=key)
                            deleted_count += 1
                    except Exception as e:
                        results['errors'].append(f"Failed to delete item from {table_name}: {str(e)}")

                if 'LastEvaluatedKey' not in response:
                    break
                response = table.scan(
                    ExclusiveStartKey=response['LastEvaluatedKey'], **scan_kwargs
                )

            results[result_key] = deleted_count
            logger.info(f"Deleted {deleted_count} records from {table_name} for tenant {tenant_id}")

        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                logger.warning(f"Table {table_name} not found, skipping")
            else:
                results['errors'].append(f"Failed to scan {table_name}: {str(e)}")
        except Exception as e:
            results['errors'].append(f"Unexpected error cleaning {table_name}: {str(e)}")

    return results


# =============================================================================
# S3 TENANT PURGE (version-aware, batch, multi-bucket)
# =============================================================================

def _tenant_bucket_targets(tenant_id: str) -> List[Dict[str, Any]]:
    """
    Builds the list of (bucket, prefixes) pairs holding tenant data.

    Each entry tries BOTH prefix conventions because the platform is
    inconsistent: schemas/KB/examples use 'tenants/{id}/', branding may
    use bare '{id}/'. Listing a non-existent prefix is a harmless no-op,
    so trying both is safe and guarantees coverage.
    """
    candidates = [
        ('agent_schemas', AGENT_SCHEMAS_BUCKET),
        ('kb_documents', KB_DOCUMENTS_BUCKET),
        ('few_shot_examples', FEW_SHOT_EXAMPLES_BUCKET),
        ('customer_branding', CUSTOMER_BRANDING_BUCKET),
    ]

    targets = []
    for label, bucket in candidates:
        if not bucket:
            logger.info(f"Bucket '{label}' not configured, skipping")
            continue
        targets.append({
            'label': label,
            'bucket': bucket,
            'prefixes': [f"tenants/{tenant_id}/", f"{tenant_id}/"],
        })
    return targets


def _purge_prefix(bucket: str, prefix: str) -> Tuple[int, List[str]]:
    """
    Permanently deletes ALL objects, ALL versions, and ALL delete markers
    under a prefix. Works on both versioned and unversioned buckets
    (unversioned objects report VersionId='null').

    Returns (deleted_count, errors).
    """
    deleted = 0
    errors: List[str] = []

    try:
        paginator = s3_client.get_paginator('list_object_versions')

        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            batch: List[Dict[str, str]] = []

            for v in page.get('Versions', []):
                batch.append({'Key': v['Key'], 'VersionId': v['VersionId']})
            for m in page.get('DeleteMarkers', []):
                batch.append({'Key': m['Key'], 'VersionId': m['VersionId']})

            if not batch:
                continue

            # delete_objects caps at 1000 per call
            for i in range(0, len(batch), 1000):
                chunk = batch[i:i + 1000]
                try:
                    resp = s3_client.delete_objects(
                        Bucket=bucket,
                        Delete={'Objects': chunk, 'Quiet': True},
                    )
                    failed = resp.get('Errors', [])
                    deleted += len(chunk) - len(failed)
                    for f in failed:
                        errors.append(
                            f"{bucket}/{f.get('Key')} "
                            f"({f.get('VersionId')}): {f.get('Code')} {f.get('Message')}"
                        )
                except ClientError as e:
                    errors.append(f"Batch delete failed on {bucket}/{prefix}: {e}")

    except ClientError as e:
        code = e.response['Error']['Code']
        if code in ('NoSuchBucket', 'AccessDenied'):
            errors.append(f"Cannot list versions for {bucket}/{prefix}: {code}")
        else:
            errors.append(f"Failed to purge {bucket}/{prefix}: {e}")
    except Exception as e:
        errors.append(f"Unexpected error purging {bucket}/{prefix}: {e}")

    return deleted, errors


def _verify_prefix_empty(bucket: str, prefix: str) -> bool:
    """Confirms no versions or markers remain under a prefix."""
    try:
        resp = s3_client.list_object_versions(
            Bucket=bucket, Prefix=prefix, MaxKeys=1
        )
        return not resp.get('Versions') and not resp.get('DeleteMarkers')
    except ClientError:
        return False


@xray_recorder.capture('cleanup_secrets_and_s3')
def cleanup_secrets_and_s3(tenant_id: str) -> Dict[str, Any]:
    """
    Deletes tenant-scoped secrets and permanently purges all tenant S3 data
    across every tenant-scoped bucket, including version history.
    """
    results: Dict[str, Any] = {
        'secrets_deleted': [],
        's3_objects_deleted': 0,
        's3_by_bucket': {},
        's3_verification_failed': [],
        'errors': [],
    }

    # --- Secrets ---
    for secret_type in ('psa', 'rmm', 'graph'):
        secret_name = f"{ENVIRONMENT}/tenants/{tenant_id}/{secret_type}"
        try:
            secrets_client.delete_secret(
                SecretId=secret_name,
                RecoveryWindowInDays=7,
            )
            results['secrets_deleted'].append(secret_name)
            logger.info(f"Deleted secret {secret_name}")
        except ClientError as e:
            if e.response['Error']['Code'] in (
                'ResourceNotFoundException', 'InvalidRequestException'
            ):
                logger.info(f"Secret {secret_name} already deleted/pending")
            else:
                results['errors'].append(f"Secret {secret_name}: {e}")

    # --- S3 ---
    for target in _tenant_bucket_targets(tenant_id):
        bucket = target['bucket']
        label = target['label']
        bucket_total = 0

        for prefix in target['prefixes']:
            count, errs = _purge_prefix(bucket, prefix)
            bucket_total += count
            results['errors'].extend(errs)

            if count > 0:
                logger.info(f"Purged {count} object versions from {bucket}/{prefix}")
                if not _verify_prefix_empty(bucket, prefix):
                    results['s3_verification_failed'].append(f"{bucket}/{prefix}")
                    results['errors'].append(
                        f"Verification failed: objects remain at {bucket}/{prefix}"
                    )

        results['s3_by_bucket'][label] = bucket_total
        results['s3_objects_deleted'] += bucket_total

    logger.info(
        f"S3 purge for {tenant_id}: {results['s3_objects_deleted']} versions "
        f"across {len(results['s3_by_bucket'])} buckets, "
        f"{len(results['errors'])} errors"
    )
    return results


# =============================================================================
# KB VECTOR PURGE (AOSS)
# =============================================================================

@xray_recorder.capture('purge_kb_vectors')
def purge_kb_vectors(tenant_id: str) -> Dict[str, Any]:
    """
    Triggers a Knowledge Base re-ingestion so vectors for deleted S3
    documents are removed from the vector store.

    NOTE: With a SHARED knowledge base, this is a full re-sync of all
    tenants' documents. It is asynchronous — completion is not confirmed
    here.
    """
    results: Dict[str, Any] = {'ingestion_job_id': None, 'errors': []}

    if not ENABLE_KB or not KNOWLEDGE_BASE_ID or not DATA_SOURCE_ID:
        logger.info("KB not configured, skipping vector purge")
        return results

    try:
        resp = bedrock_agent.start_ingestion_job(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            dataSourceId=DATA_SOURCE_ID,
            description=f"Purge vectors for deprovisioned tenant {tenant_id}",
        )
        job_id = resp['ingestionJob']['ingestionJobId']
        results['ingestion_job_id'] = job_id
        logger.info(f"Started KB re-ingestion {job_id} to purge {tenant_id} vectors")
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConflictException':
            logger.warning("Ingestion job already running; vector purge deferred")
            results['errors'].append(
                "Ingestion job already in progress — vector purge must be re-verified"
            )
        else:
            results['errors'].append(f"Failed to start KB re-ingestion: {e}")
    except Exception as e:
        results['errors'].append(f"Unexpected error starting re-ingestion: {e}")

    return results


# =============================================================================
# DEPROVISIONING ORCHESTRATOR
# =============================================================================

@xray_recorder.capture('deprovision_tenant')
def deprovision_tenant(tenant_id: str, preserve_data: bool) -> Dict[str, Any]:
    """
    Full deprovisioning workflow for a tenant.

    Steps:
    1. Drain period (wait for in-flight operations)
    2. Clean up Bedrock resources
    3. Optionally clean up tenant data
    4. Clean up secrets and S3 (version-aware purge)
    4b. Purge KB vectors (hard delete only)
    5. Update tenant status
    6. Send notification
    """
    tenant = get_tenant_record(tenant_id)
    if not tenant:
        raise ValueError(f"Tenant {tenant_id} not found")

    agent_id = tenant.get('agent_id')
    results = {
        'tenant_id': tenant_id,
        'preserve_data': preserve_data,
        'bedrock': {},
        'data': {},
        'secrets_s3': {},
        'kb_vectors': {},
        'final_status': 'deleted',
    }

    # Step 1: Drain period
    if DRAIN_SECONDS > 0:
        logger.info(f"Draining in-flight operations for {DRAIN_SECONDS}s")
        time.sleep(DRAIN_SECONDS)

    # Step 2: Clean up Bedrock resources
    try:
        results['bedrock'] = cleanup_bedrock_resources(tenant_id, agent_id)
    except Exception as e:
        logger.error(f"Bedrock cleanup failed: {e}")
        results['bedrock'] = {'errors': [str(e)]}

    # Step 3: Optionally clean up tenant data
    if not preserve_data:
        try:
            results['data'] = cleanup_tenant_data(tenant_id)
        except Exception as e:
            logger.error(f"Data cleanup failed: {e}")
            results['data'] = {'errors': [str(e)]}
    else:
        logger.info(f"Preserving data for tenant {tenant_id}")
        results['data'] = {'preserved': True}

    # Step 4: Clean up secrets and S3 (version-aware)
    try:
        results['secrets_s3'] = cleanup_secrets_and_s3(tenant_id)
    except Exception as e:
        logger.error(f"Secrets/S3 cleanup failed: {e}")
        results['secrets_s3'] = {'errors': [str(e)]}

    # Step 4b: Purge KB vectors (only on hard delete)
    if not preserve_data:
        try:
            results['kb_vectors'] = purge_kb_vectors(tenant_id)
        except Exception as e:
            logger.error(f"KB vector purge failed: {e}")
            results['kb_vectors'] = {'errors': [str(e)]}
    else:
        results['kb_vectors'] = {'skipped': 'preserve_data=true'}

    # Step 5: Determine final status
    all_errors = (
        results['bedrock'].get('errors', []) +
        results['data'].get('errors', []) +
        results['secrets_s3'].get('errors', []) +
        results.get('kb_vectors', {}).get('errors', [])
    )

    if all_errors:
        final_status = 'delete_failed'
        logger.warning(
            f"Deprovisioning completed with {len(all_errors)} errors for tenant {tenant_id}"
        )
    else:
        final_status = 'deleted'
        logger.info(f"Deprovisioning completed successfully for tenant {tenant_id}")

    try:
        update_tenant_status(
            tenant_id,
            final_status,
            deprovision_completed_at=datetime.now(timezone.utc).isoformat(),
            deprovision_results=json.dumps(results)
        )
    except Exception as e:
        logger.error(f"Failed to update tenant status: {e}")

    # Step 6: Send notification
    try:
        send_notification(tenant_id, final_status, {
            'bedrock_errors': len(results['bedrock'].get('errors', [])),
            'data_errors': len(results['data'].get('errors', [])),
            'secrets_s3_errors': len(results['secrets_s3'].get('errors', [])),
            'kb_vectors_errors': len(results.get('kb_vectors', {}).get('errors', [])),
            'preserve_data': preserve_data,
        })
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")

    results['final_status'] = final_status
    return results


# =============================================================================
# NOTIFICATIONS
# =============================================================================

@xray_recorder.capture('send_notification')
def send_notification(tenant_id: str, status: str, details: Dict[str, Any]) -> None:
    """Sends a notification email about tenant provisioning/deprovisioning status."""
    admin_email = os.environ.get('ADMIN_EMAIL', '')
    if not admin_email:
        return

    tenant = get_tenant_record(tenant_id)
    if not tenant:
        return

    contact_email = tenant.get('contact_email', '')
    display_name = tenant.get('display_name', tenant_id)

    subject = f"Tenant {tenant_id} {status}"
    body = f"""
Tenant: {display_name} ({tenant_id})
Status: {status}
Details: {json.dumps(details, indent=2)}
Timestamp: {datetime.now(timezone.utc).isoformat()}
"""

    try:
        ses_client.send_email(
            Source=admin_email,
            Destination={'ToAddresses': [admin_email]},
            Message={
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {'Text': {'Data': body, 'Charset': 'UTF-8'}}
            }
        )

        if status == 'active' and contact_email:
            welcome_body = f"""
Hello,

Your AI IT Concierge has been successfully provisioned and is ready to use.

Tenant ID: {tenant_id}
Display Name: {display_name}

Next steps:
1. Populate your credentials in the secrets provided to you
2. Upload your internal documentation to the S3 bucket
3. Test the agent in Microsoft Teams

If you have any questions, please contact our support team.

Best regards,
Your MSP Team
"""
            ses_client.send_email(
                Source=admin_email,
                Destination={'ToAddresses': [contact_email]},
                Message={
                    'Subject': {'Data': f'Your AI IT Concierge is ready ({tenant_id})', 'Charset': 'UTF-8'},
                    'Body': {'Text': {'Data': welcome_body, 'Charset': 'UTF-8'}}
                }
            )

        elif status == 'deleted' and contact_email:
            goodbye_body = f"""
Hello,

Your AI IT Concierge for tenant "{display_name}" ({tenant_id}) has been decommissioned.

If this was unexpected, please contact our support team immediately.

Best regards,
Your MSP Team
"""
            ses_client.send_email(
                Source=admin_email,
                Destination={'ToAddresses': [contact_email]},
                Message={
                    'Subject': {'Data': f'Your AI IT Concierge has been decommissioned ({tenant_id})', 'Charset': 'UTF-8'},
                    'Body': {'Text': {'Data': goodbye_body, 'Charset': 'UTF-8'}}
                }
            )

    except ClientError as e:
        logger.error(f"Failed to send notification: {e}")


# =============================================================================
# LAMBDA HANDLER
# =============================================================================

@xray_recorder.capture('provisioning_worker_handler')
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main entry point for the provisioning worker."""
    failures = []

    for record in event.get('Records', []):
        try:
            message = json.loads(record['body'])
            tenant_id = message.get('tenant_id')
            action = message.get('action', 'provision')

            if not tenant_id:
                logger.error(f"Missing tenant_id in message: {message}")
                continue

            logger.info(f"Processing {action} for tenant {tenant_id}")

            if action == 'provision':
                result = provision_tenant(tenant_id)
                update_tenant_status(
                    tenant_id,
                    'active',
                    agent_id=result['agent_id'],
                    agent_alias_id=result['agent_alias_id'],
                    provisioned_at=datetime.now(timezone.utc).isoformat()
                )
                send_notification(tenant_id, 'active', result)
                logger.info(f"Tenant {tenant_id} provisioning complete")

            elif action == 'deprovision':
                preserve_data = message.get('preserve_data', True)
                result = deprovision_tenant(tenant_id, preserve_data)
                logger.info(f"Tenant {tenant_id} deprovisioning complete: {result['final_status']}")

            else:
                logger.error(f"Unknown action: {action}")

        except Exception as e:
            logger.exception(f"Failed to process message: {e}")
            failures.append({'itemIdentifier': record['messageId']})

    return {'batchItemFailures': failures}
