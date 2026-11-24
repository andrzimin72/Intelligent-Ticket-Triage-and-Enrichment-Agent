"""
Teams Bot Adapter for Bedrock Agent (Phases 1-4 Complete)

Receives messages from Microsoft Teams, invokes the Bedrock Agent,
and returns responses to Teams via the Bot Connector.

Security & Multi-Tenant Features:
- Bot Framework JWT validation (not shared secret)
- Nonces read from bot-only table, never enter agent context
- Approval/denial via invoke activities, constant-time nonce comparison
- Trusted identity (user_aad_id) from Teams activity, never from agent parameters
- Tenant resolution from Teams channelData (trusted, signed by Microsoft)
- Tenant-scoped agent examples and audit logs (Phase 2)
- Tenant-scoped feedback submission (Phase 2)
- Dynamic per-tenant Agent ID and Alias ID lookup from Tenant Registry (Phase 4)
"""

import json
import os
import logging
import hmac
import time
import uuid
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Tuple, List
import boto3
from botocore.exceptions import ClientError

from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

import agent_security as sec
import jwt_validator
import tenant_resolver

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Note: AGENT_ID and AGENT_ALIAS_ID are REMOVED for Phase 4. 
# They are now looked up dynamically from the tenant_registry.

BOT_SECRET_NAME = os.environ.get('BOT_SECRET_NAME')
BOT_APP_ID = os.environ.get('BOT_APP_ID')
CONVERSATIONS_TABLE = os.environ.get('CONVERSATIONS_TABLE')
AUDIT_LOG_TABLE = os.environ.get('AUDIT_LOG_TABLE')
PENDING_OPERATIONS_TABLE = os.environ.get('PENDING_OPERATIONS_TABLE')
CONFIRMATION_NONCES_TABLE = os.environ.get('CONFIRMATION_NONCES_TABLE')
ENTRA_GRAPH_SECRET_NAME = os.environ.get('ENTRA_GRAPH_SECRET_NAME')
ENTRA_TENANT_ID = os.environ.get('ENTRA_TENANT_ID')
ENTRA_APP_CLIENT_ID = os.environ.get('ENTRA_APP_CLIENT_ID')
AUDIT_LOG_RETENTION = int(os.environ.get('AUDIT_LOG_RETENTION', '365'))
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

# Multi-tenant configuration
TENANT_REGISTRY_TABLE = os.environ.get('TENANT_REGISTRY_TABLE')
DEFAULT_TENANT_ID = os.environ.get('DEFAULT_TENANT_ID', 'default')

# Agent feedback loop configuration
AGENT_FEEDBACK_HANDLER = os.environ.get('AGENT_FEEDBACK_HANDLER')
AGENT_EXAMPLES_BUCKET = os.environ.get('AGENT_EXAMPLES_BUCKET')
AGENT_EXAMPLES_KEY = os.environ.get('AGENT_EXAMPLES_KEY', 'agent-examples.json')
MAX_AGENT_EXAMPLES = int(os.environ.get('MAX_AGENT_EXAMPLES', '5'))
AGENT_EXAMPLES_CACHE_TTL = int(os.environ.get('AGENT_EXAMPLES_CACHE_TTL', '300'))

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

# Initialize clients
bedrock_agent = boto3.client('bedrock-agent-runtime', region_name=AWS_REGION)
secrets_client = boto3.client('secretsmanager', region_name=AWS_REGION)
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
lambda_client = boto3.client('lambda', region_name=AWS_REGION)
s3_client = boto3.client('s3', region_name=AWS_REGION)

_secret_cache: Dict[str, Dict[str, str]] = {}
_bot_token = {"token": None, "expires_at": 0}
_graph_token = {"token": None, "expires_at": 0}
_agent_examples_cache: Dict[str, Dict[str, Any]] = {}  # Per-tenant cache


# =============================================================================
# SECRETS & AUTHENTICATION
# =============================================================================

def get_secret(secret_name: str) -> Dict[str, str]:
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


def get_bot_token() -> str:
    if _bot_token["token"] and _bot_token["expires_at"] > time.time() + 300:
        return _bot_token["token"]
    
    creds = get_secret(BOT_SECRET_NAME)
    body = urllib.parse.urlencode({
        "client_id": creds["BOT_APP_ID"],
        "client_secret": creds["BOT_APP_PASSWORD"],
        "grant_type": "client_credentials",
        "scope": "https://api.botframework.com/.default",
    }).encode()
    
    req = urllib.request.Request(
        "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            payload = json.loads(r.read())
        
        _bot_token.update(
            token=payload["access_token"],
            expires_at=time.time() + payload.get("expires_in", 3600)
        )
        return _bot_token["token"]
    except Exception as e:
        logger.error(f"Failed to obtain Bot Framework token: {e}")
        raise


def get_graph_token() -> str:
    if _graph_token["token"] and _graph_token["expires_at"] > time.time() + 300:
        return _graph_token["token"]
    
    creds = get_secret(ENTRA_GRAPH_SECRET_NAME)
    client_secret = creds.get("CLIENT_SECRET")
    
    if not client_secret:
        raise ValueError("CLIENT_SECRET not found in Entra Graph credentials")
    
    body = urllib.parse.urlencode({
        "client_id": ENTRA_APP_CLIENT_ID,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode()
    
    req = urllib.request.Request(
        f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/oauth2/v2.0/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            payload = json.loads(r.read())
        
        _graph_token.update(
            token=payload["access_token"],
            expires_at=time.time() + payload.get("expires_in", 3600)
        )
        return _graph_token["token"]
    except Exception as e:
        logger.error(f"Failed to obtain Graph token: {e}")
        raise


def graph_request(endpoint: str) -> Dict[str, Any]:
    token = get_graph_token()
    url = f"{GRAPH_API_BASE}{endpoint}"
    
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        method="GET"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read()
            if response.status == 204 or not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        logger.error(f"Graph API error {e.code}: {error_body}")
        raise
    except Exception as e:
        logger.error(f"Graph API request failed: {e}")
        raise


def validate_teams_request(event: Dict[str, Any]) -> bool:
    if not BOT_APP_ID:
        logger.error("BOT_APP_ID not configured — cannot validate JWT")
        return False
    
    return jwt_validator.validate_teams_request_with_jwt(event, BOT_APP_ID)


# =============================================================================
# TENANT RESOLUTION
# =============================================================================

def resolve_tenant(activity: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Resolves the tenant from the Teams activity.
    Returns: (tenant_record_dict, source)
    """
    entra_tenant_id = tenant_resolver.resolve_tenant_from_teams_activity(activity)
    
    if entra_tenant_id:
        tenant = tenant_resolver.lookup_tenant_by_entra_id(entra_tenant_id)
        if tenant:
            logger.info(f"Resolved tenant: {tenant.get('tenant_id')} from Entra tenant {entra_tenant_id}")
            return tenant, 'teams_activity'
        
        logger.warning(
            f"Unregistered Entra tenant ID received: {entra_tenant_id}. "
            f"Falling back to default tenant."
        )
    
    # Fall back to default tenant for backward compatibility
    default_tenant = tenant_resolver.lookup_tenant_by_id(DEFAULT_TENANT_ID)
    if default_tenant:
        logger.info(f"Using default tenant: {DEFAULT_TENANT_ID}")
        return default_tenant, 'default_fallback'
    
    logger.error("Could not resolve any tenant — default tenant not found")
    return None, 'unresolved'


# =============================================================================
# USER EMAIL RESOLUTION
# =============================================================================

def resolve_user_email(activity: Dict[str, Any], user_aad_id: Optional[str]) -> Tuple[Optional[str], str]:
    from_field = activity.get('from') or {}
    email = from_field.get('email') or from_field.get('userPrincipalName')
    
    if email:
        logger.info(f"Resolved user email from Teams activity: {email}")
        return email, 'activity'
    
    if user_aad_id:
        conversation_id = activity.get('conversation', {}).get('id')
        if conversation_id:
            try:
                table = dynamodb.Table(CONVERSATIONS_TABLE)
                response = table.get_item(Key={'session_id': conversation_id})
                item = response.get('Item')
                
                if item and item.get('user_email'):
                    logger.info(f"Resolved user email from conversation cache: {item['user_email']}")
                    return item['user_email'], 'cache'
            except ClientError as e:
                logger.warning(f"Failed to check conversation cache: {e}")
    
    if user_aad_id:
        try:
            user = graph_request(f"/users/{user_aad_id}?$select=mail,userPrincipalName")
            email = user.get('mail') or user.get('userPrincipalName')
            
            if email:
                logger.info(f"Resolved user email from Graph API: {email}")
                return email, 'graph'
        except Exception as e:
            logger.warning(f"Failed to resolve user email via Graph: {e}")
    
    logger.warning(f"Could not resolve user email for AAD ID: {user_aad_id}")
    return None, 'unresolved'


def cache_user_email(conversation_id: str, user_aad_id: str, user_email: str) -> None:
    if not conversation_id or not user_email:
        return
    
    try:
        table = dynamodb.Table(CONVERSATIONS_TABLE)
        table.update_item(
            Key={'session_id': conversation_id},
            UpdateExpression='SET user_email = :email, user_aad_id = :aad',
            ExpressionAttributeValues={
                ':email': user_email,
                ':aad': user_aad_id or 'unknown'
            }
        )
    except ClientError as e:
        logger.warning(f"Failed to cache user email: {e}")


# =============================================================================
# BOT CONNECTOR REPLIES
# =============================================================================

def reply_to_teams(service_url: str, conversation_id: str, activity: Dict[str, Any]) -> None:
    url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities"
    
    req = urllib.request.Request(
        url,
        data=json.dumps(activity).encode(),
        headers={
            "Authorization": f"Bearer {get_bot_token()}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
    except Exception as e:
        logger.error(f"Failed to send reply to Teams: {e}")
        raise


# =============================================================================
# CONVERSATION STATE MANAGEMENT
# =============================================================================

def get_or_create_session(session_key: str, user_aad_id: str) -> str:
    try:
        table = dynamodb.Table(CONVERSATIONS_TABLE)
        response = table.get_item(Key={'session_id': session_key})
        item = response.get('Item')
        
        if item:
            ttl = item.get('ttl', 0)
            if ttl > datetime.now(timezone.utc).timestamp():
                return item.get('agent_session_id')
        
        agent_session_id = str(uuid.uuid4())
        ttl_timestamp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
        
        table.put_item(Item={
            'session_id': session_key,
            'agent_session_id': agent_session_id,
            'user_aad_id': user_aad_id or 'unknown',
            'user_email': '',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'ttl': ttl_timestamp
        })
        
        logger.info(f"Created new agent session {agent_session_id} for {session_key}")
        return agent_session_id
    
    except ClientError as e:
        logger.error(f"Failed to get/create session: {e}")
        return str(uuid.uuid4())


# =============================================================================
# AUDIT LOGGING
# =============================================================================

def write_audit_log(tenant_id: str, user_aad_id: str, user_email: Optional[str],
                    user_message: str, agent_response: str, session_id: str) -> None:
    if not AUDIT_LOG_TABLE:
        return
    
    try:
        table = dynamodb.Table(AUDIT_LOG_TABLE)
        timestamp = datetime.now(timezone.utc).isoformat()
        ttl_timestamp = int((datetime.now(timezone.utc) + timedelta(days=AUDIT_LOG_RETENTION)).timestamp())
        
        table.put_item(Item={
            'audit_id': str(uuid.uuid4()),
            'timestamp': timestamp,
            'tenant_id': tenant_id,
            'user_id': user_aad_id or 'unknown',
            'user_email': user_email or 'unknown',
            'tool_name': 'teams_bot',
            'parameters': json.dumps({
                'user_message': user_message[:500],
                'session_id': session_id
            }),
            'result_summary': json.dumps({
                'agent_response': agent_response[:500],
                'response_length': len(agent_response)
            }),
            'ttl': ttl_timestamp
        })
    except ClientError as e:
        logger.error(f"Failed to write audit log: {e}")


# =============================================================================
# APPROVAL CARD ATTACHMENT
# =============================================================================

def attach_pending_approval_cards(session_id: str, service_url: str, conversation_id: str) -> int:
    try:
        pending = dynamodb.Table(PENDING_OPERATIONS_TABLE).query(
            IndexName="session-index",
            KeyConditionExpression="session_id = :sid",
            FilterExpression="#s = :pending AND expires_at > :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":sid": session_id,
                ":pending": "pending_approval",
                ":now": int(time.time()),
            },
        ).get("Items", [])
    except ClientError as e:
        logger.error(f"Failed to query pending operations: {e}")
        return 0
    
    if not pending:
        return 0
    
    nonces_table = dynamodb.Table(CONFIRMATION_NONCES_TABLE)
    sent = 0
    
    for op in pending:
        cid = op["confirmation_id"]
        try:
            item = nonces_table.get_item(Key={"confirmation_id": cid}).get("Item")
        except ClientError as e:
            logger.warning(f"Failed to read nonce for {cid}: {e}")
            continue
        
        if not item:
            continue
        
        action = op["operation_type"].replace("_", " ")
        card = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "text": f"Approve {action}?", "weight": "Bolder", "size": "Medium"},
                        {"type": "TextBlock", "text": f"Account: {op.get('target_display_name', '')}", "wrap": True},
                        {"type": "TextBlock",
                         "text": ("Administrator action — the user and security team will be notified."
                                  if op.get("is_admin_override") else "This will change your account credentials."),
                         "wrap": True, "isSubtle": True},
                        {"type": "TextBlock", "text": "Expires in 10 minutes. If you did not request this, click Deny.", "wrap": True, "color": "Attention"},
                    ],
                    "actions": [
                        {"type": "Action.Execute", "title": "Approve", "verb": "approve_operation", "data": {"confirmation_id": cid, "nonce": item["nonce"]}},
                        {"type": "Action.Execute", "title": "Deny", "verb": "deny_operation", "data": {"confirmation_id": cid, "nonce": item["nonce"]}},
                    ],
                },
            }],
        }
        
        try:
            reply_to_teams(service_url, conversation_id, card)
            nonces_table.delete_item(Key={"confirmation_id": cid})
            sent += 1
        except Exception as e:
            logger.error(f"Failed to send approval card for {cid}: {e}")
    
    return sent


# =============================================================================
# AGENT EXAMPLES LOADER
# =============================================================================

def load_agent_examples(tenant_id: str) -> List[Dict[str, Any]]:
    if not AGENT_EXAMPLES_BUCKET:
        return []
    
    examples_key = f"tenants/{tenant_id}/{AGENT_EXAMPLES_KEY}"
    cache_key = f"{tenant_id}:{examples_key}"
    current_time = time.time()
    
    if cache_key in _agent_examples_cache:
        cached = _agent_examples_cache[cache_key]
        if (current_time - cached['last_loaded']) < AGENT_EXAMPLES_CACHE_TTL:
            return cached['examples']
    
    try:
        response = s3_client.get_object(Bucket=AGENT_EXAMPLES_BUCKET, Key=examples_key)
        examples = json.loads(response['Body'].read().decode('utf-8'))
        examples = examples[:MAX_AGENT_EXAMPLES]
        
        _agent_examples_cache[cache_key] = {'examples': examples, 'last_loaded': current_time}
        logger.info(f"Loaded {len(examples)} agent examples for tenant {tenant_id}")
        return examples
    
    except s3_client.exceptions.NoSuchKey:
        logger.info(f"No agent examples for tenant {tenant_id}, starting with empty list")
        _agent_examples_cache[cache_key] = {'examples': [], 'last_loaded': current_time}
        return []
    except Exception as e:
        logger.warning(f"Failed to load agent examples for tenant {tenant_id}: {e}")
        cached = _agent_examples_cache.get(cache_key, {'examples': []})
        return cached['examples']


# =============================================================================
# FEEDBACK CARD BUILDERS & SUBMISSION
# =============================================================================

def build_feedback_card(agent_response: str, session_id: str, user_aad_id: str,
                       user_message: str, tools_called: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {"type": "TextBlock", "text": "Was this response helpful?", "weight": "Bolder", "size": "Medium"},
                    {"type": "ActionSet", "actions": [
                        {"type": "Action.Execute", "title": "👍 Yes, helpful", "verb": "feedback_thumbs_up",
                         "data": {"feedback_type": "thumbs_up", "session_id": session_id, "user_aad_id": user_aad_id,
                                  "agent_response": agent_response[:500], "user_message": user_message[:200], "tools_called": tools_called}},
                        {"type": "Action.Execute", "title": "👎 No, needs improvement", "verb": "feedback_thumbs_down",
                         "data": {"feedback_type": "thumbs_down", "session_id": session_id, "user_aad_id": user_aad_id,
                                  "agent_response": agent_response[:500], "user_message": user_message[:200], "tools_called": tools_called}}
                    ]}
                ]
            }
        }]
    }


def build_detailed_feedback_card(initial_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {"type": "TextBlock", "text": "Help us improve", "weight": "Bolder", "size": "Medium"},
                    {"type": "TextBlock", "text": "What went wrong?", "wrap": True},
                    {"type": "Input.ChoiceSet", "id": "error_category", "style": "compact",
                     "choices": [
                         {"title": "Wrong tool chosen", "value": "wrong_tool"},
                         {"title": "Wrong parameters", "value": "wrong_parameters"},
                         {"title": "Misunderstood intent", "value": "misunderstood_intent"},
                         {"title": "Poor response quality", "value": "poor_quality"},
                         {"title": "Skipped confirmation", "value": "skipped_confirmation"},
                         {"title": "Hallucinated information", "value": "hallucination"},
                         {"title": "Other", "value": "other"},
                     ], "placeholder": "Select error type"},
                    {"type": "Input.Text", "id": "correction_text", "label": "What should have happened?", "isMultiline": True, "placeholder": "Describe the correct behavior..."},
                    {"type": "Input.Text", "id": "expected_tool", "label": "Expected tool (optional, for IT staff)", "placeholder": "e.g., find_free_time"},
                    {"type": "Input.Text", "id": "expected_parameters", "label": "Expected parameters (optional, JSON)", "isMultiline": True, "placeholder": "e.g., {\"duration_minutes\": 30}"}
                ],
                "actions": [
                    {"type": "Action.Execute", "title": "Submit Feedback", "verb": "feedback_submit_detailed", "data": initial_data},
                    {"type": "Action.Execute", "title": "Cancel", "verb": "feedback_cancel"}
                ]
            }
        }]
    }


def submit_feedback_to_handler(feedback_data: Dict[str, Any], tenant_id: str) -> bool:
    if not AGENT_FEEDBACK_HANDLER:
        logger.error("AGENT_FEEDBACK_HANDLER not configured")
        return False
    
    feedback_data['tenant_id'] = tenant_id
    
    try:
        response = lambda_client.invoke(
            FunctionName=AGENT_FEEDBACK_HANDLER,
            InvocationType='Event',
            Payload=json.dumps({'body': json.dumps({'feedback_data': feedback_data})})
        )
        logger.info(f"Submitted feedback to handler for tenant {tenant_id} (status: {response.get('StatusCode')})")
        return True
    except Exception as e:
        logger.error(f"Failed to submit feedback to handler: {e}")
        return False


# =============================================================================
# INVOKE HANDLING
# =============================================================================

def handle_invoke(activity: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    value = activity.get("value") or {}
    data = value.get("data") or {}
    verb = value.get("verb")
    user_aad_id = (activity.get("from") or {}).get("aadObjectId")
    user_name = (activity.get("from") or {}).get("name", "User")
    
    if verb in ("approve_operation", "deny_operation"):
        cid = data.get("confirmation_id")
        nonce = data.get("nonce")
        
        if not (cid and nonce and user_aad_id):
            return {"status": 400, "body": {"error": "malformed approval"}}
        
        if verb == "approve_operation":
            ok = sec.approve_operation(confirmation_id=cid, nonce=nonce, approver_aad_id=user_aad_id)
            text = "Approved. Return to the assistant and tell it to continue." if ok else "This request is no longer valid or was already used."
        else:
            ok = sec.deny_operation(confirmation_id=cid, nonce=nonce, denier_aad_id=user_aad_id)
            text = "Request denied." if ok else "This request is no longer valid."
        
        return {"status": 200, "body": {"statusCode": 200, "type": "application/vnd.microsoft.card.adaptive", "value": {"type": "AdaptiveCard", "version": "1.4", "body": [{"type": "TextBlock", "text": text, "wrap": True}]}}}
    
    if verb == "feedback_thumbs_up":
        feedback_data = {'feedback_type': 'thumbs_up', 'user_aad_id': user_aad_id, 'user_name': user_name, 'session_id': data.get('session_id'), 'agent_response': data.get('agent_response'), 'user_message': data.get('user_message'), 'tools_called': data.get('tools_called', [])}
        submit_feedback_to_handler(feedback_data, tenant_id)
        return {"status": 200, "body": {"statusCode": 200, "type": "application/vnd.microsoft.card.adaptive", "value": {"type": "AdaptiveCard", "version": "1.4", "body": [{"type": "TextBlock", "text": "✓ Thanks for your feedback!", "wrap": True}]}}}
    
    if verb == "feedback_thumbs_down":
        initial_data = {'feedback_type': 'thumbs_down', 'user_aad_id': user_aad_id, 'session_id': data.get('session_id'), 'agent_response': data.get('agent_response'), 'user_message': data.get('user_message'), 'tools_called': data.get('tools_called', [])}
        card = build_detailed_feedback_card(initial_data)
        return {"status": 200, "body": {"statusCode": 200, "type": "application/vnd.microsoft.card.adaptive", "value": card["attachments"][0]["content"]}}
    
    if verb == "feedback_submit_detailed":
        form_data = value
        feedback_data = {'feedback_type': data.get('feedback_type', 'thumbs_down'), 'user_aad_id': user_aad_id, 'user_name': user_name, 'session_id': data.get('session_id'), 'agent_response': data.get('agent_response'), 'user_message': data.get('user_message'), 'tools_called': data.get('tools_called', []), 'error_category': form_data.get('error_category'), 'correction_text': form_data.get('correction_text'), 'expected_tool': form_data.get('expected_tool'), 'expected_parameters': form_data.get('expected_parameters')}
        submit_feedback_to_handler(feedback_data, tenant_id)
        return {"status": 200, "body": {"statusCode": 200, "type": "application/vnd.microsoft.card.adaptive", "value": {"type": "AdaptiveCard", "version": "1.4", "body": [{"type": "TextBlock", "text": "✓ Thanks for the detailed feedback! We'll use this to improve.", "wrap": True}]}}}
    
    if verb == "feedback_cancel":
        return {"status": 200, "body": {"statusCode": 200, "type": "application/vnd.microsoft.card.adaptive", "value": {"type": "AdaptiveCard", "version": "1.4", "body": [{"type": "TextBlock", "text": "Feedback cancelled.", "wrap": True}]}}}
    
    logger.warning(f"Unknown invoke verb: {verb}")
    return {"status": 400, "body": {"error": "unknown verb"}}


# =============================================================================
# BEDROCK AGENT INVOCATION (PHASE 4: DYNAMIC AGENT LOOKUP)
# =============================================================================

def _extract_tools_from_trace(completion: list) -> List[Dict[str, Any]]:
    tools_called = []
    for event in completion:
        if 'trace' not in event:
            continue
        trace = event['trace']
        if 'orchestrationTrace' in trace:
            orch = trace['orchestrationTrace']
            if 'invocationInput' in orch and 'actionGroupInvocationInput' in orch['invocationInput']:
                action = orch['invocationInput']['actionGroupInvocationInput']
                tools_called.append({'tool': action.get('apiPath'), 'action_group': action.get('actionGroup'), 'parameters': action.get('parameters', {})})
        if 'toolUse' in trace:
            tool_use = trace['toolUse']
            tools_called.append({'tool': tool_use.get('name'), 'parameters': tool_use.get('input', {})})
    return tools_called


@xray_recorder.capture('invoke_agent')
def invoke_agent(session_id: str, user_message: str, user_aad_id: str,
                 user_name: str, user_email: str, tenant_record: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Invokes the Bedrock Agent with the user's message.
    
    Phase 4: Uses tenant-specific agent_id and agent_alias_id from the tenant_record.
    """
    tenant_id = tenant_record['tenant_id']
    agent_id = tenant_record.get('agent_id')
    agent_alias_id = tenant_record.get('agent_alias_id')
    
    if not agent_id or not agent_alias_id:
        logger.error(f"Agent ID or Alias ID missing for tenant {tenant_id}")
        return ("I'm sorry, the AI assistant is not fully configured for your organization. Please contact IT support.", [])
    
    try:
        logger.info(f"Invoking agent {agent_id} for session {session_id}, tenant {tenant_id}: {user_message[:100]}")
        
        examples = load_agent_examples(tenant_id)
        
        session_attributes = {
            'tenant_id': tenant_id,
            'user_aad_id': user_aad_id,
            'user_name': user_name or 'User',
            'user_email': user_email or '',
        }
        
        if examples:
            examples_text = "\n\n".join([
                f"Example {i+1}:\nUser Input: {ex.get('user_input', 'N/A')}\nWrong Behavior: {ex.get('wrong_behavior', 'N/A')}\nCorrect Behavior: {ex.get('correct_behavior', 'N/A')}\nRationale: {ex.get('rationale', 'N/A')}"
                for i, ex in enumerate(examples)
            ])
            session_attributes['few_shot_examples'] = examples_text
            logger.info(f"Injected {len(examples)} few-shot examples for tenant {tenant_id}")
        
        session_state = {'sessionAttributes': session_attributes}
        
        invoke_params = {
            'agentId': agent_id,             # Phase 4: Dynamic
            'agentAliasId': agent_alias_id,  # Phase 4: Dynamic
            'sessionId': session_id,
            'inputText': user_message,
            'sessionState': session_state,
            'enableTrace': True,
        }
        
        response = bedrock_agent.invoke_agent(**invoke_params)
        
        completion = response.get('completion', [])
        response_text = ""
        tools_called = _extract_tools_from_trace(completion)
        
        for event in completion:
            if 'chunk' in event:
                chunk = event['chunk']
                response_text += chunk.get('bytes', b'').decode('utf-8')
        
        logger.info(f"Agent response: {response_text[:200]}, tools called: {len(tools_called)}")
        return response_text, tools_called
    
    except ClientError as e:
        logger.error(f"Failed to invoke agent: {e}")
        return ("I'm sorry, I encountered an error processing your request. Please try again or contact your IT admin."), []


# =============================================================================
# LAMBDA HANDLER
# =============================================================================

@xray_recorder.capture('teams_bot_handler')
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        logger.info(f"Received Teams activity: {json.dumps(event, default=str)[:500]}")
        
        if not validate_teams_request(event):
            logger.warning("Invalid Teams request")
            return {'statusCode': 401, 'body': json.dumps({'error': 'Unauthorized'})}
        
        body = event.get('body', '{}')
        activity = json.loads(body) if isinstance(body, str) else body
        activity_type = activity.get('type')
        
        if activity_type == 'invoke':
            tenant_record, _ = resolve_tenant(activity)
            tenant_id = tenant_record['tenant_id'] if tenant_record else DEFAULT_TENANT_ID
            return handle_invoke(activity, tenant_id)
        
        if activity_type != 'message':
            logger.info(f"Ignoring non-message activity: {activity_type}")
            return {'statusCode': 200, 'body': json.dumps({'status': 'ignored'})}
        
        # Resolve tenant from Teams activity
        tenant_record, tenant_source = resolve_tenant(activity)
        
        if not tenant_record:
            logger.error("Could not resolve tenant — rejecting request")
            return {
                'statusCode': 403,
                'body': json.dumps({'type': 'message', 'text': "This Teams tenant is not registered with our service. Please contact your IT administrator.", 'textFormat': 'plain'})
            }
        
        tenant_id = tenant_record['tenant_id']
        
        conversation_id = activity.get('conversation', {}).get('id')
        user_aad_id = (activity.get('from') or {}).get('aadObjectId')
        user_name = (activity.get('from') or {}).get('name', 'User')
        user_message = activity.get('text', '')
        service_url = activity.get('serviceUrl')
        
        if not user_message:
            return {'statusCode': 200, 'body': json.dumps({'status': 'empty'})}
        
        if not user_aad_id:
            logger.warning("Message received without user AAD ID - write operations will be disabled")
        
        user_email, email_source = resolve_user_email(activity, user_aad_id)
        
        logger.info(f"Processing message from {user_name} (tenant: {tenant_id}, source: {tenant_source}, AAD: {user_aad_id}): {user_message[:100]}")
        
        session_key = f"{tenant_id}:{conversation_id}"
        agent_session_id = get_or_create_session(session_key, user_aad_id or 'unknown')
        
        if user_email and email_source != 'cache':
            cache_user_email(session_key, user_aad_id or 'unknown', user_email)
        
        # Phase 4: Pass the entire tenant_record so invoke_agent can extract the dynamic agent_id
        agent_response, tools_called = invoke_agent(
            agent_session_id, user_message, user_aad_id, user_name, user_email, tenant_record
        )
        
        write_audit_log(tenant_id, user_aad_id or 'unknown', user_email, user_message, agent_response, agent_session_id)
        
        reply_to_teams(service_url, conversation_id, {'type': 'message', 'text': agent_response, 'textFormat': 'plain'})
        
        feedback_card = build_feedback_card(agent_response, agent_session_id, user_aad_id or 'unknown', user_message, tools_called)
        reply_to_teams(service_url, conversation_id, feedback_card)
        
        cards_sent = attach_pending_approval_cards(agent_session_id, service_url, conversation_id)
        if cards_sent > 0:
            logger.info(f"Attached {cards_sent} approval card(s) to conversation")
        
        return {'statusCode': 200, 'body': json.dumps({'status': 'ok'})}
    
    except Exception as e:
        logger.exception(f"Error in Teams bot: {e}")
        return {'statusCode': 500, 'body': json.dumps({'type': 'message', 'text': "I'm sorry, I encountered an error. Please try again later.", 'textFormat': 'plain'})}