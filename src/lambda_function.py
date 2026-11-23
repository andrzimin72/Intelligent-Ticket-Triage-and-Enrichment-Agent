import json
import os
import logging
import base64
import time
import random
import re
import urllib.request
import urllib.error
from typing import Dict, Any, Tuple, List
from datetime import datetime, timedelta
import boto3
from botocore.exceptions import ClientError

# X-Ray SDK
from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

# ==============================================================================
# 1. CONFIGURATION & LOGGING
# ==============================================================================

logger = logging.getLogger()
logger.setLevel(logging.INFO)

AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

MODEL_ID = os.environ.get('MODEL_ID', 'anthropic.claude-sonnet-5-5-v1:0')
FALLBACK_MODEL_ID = os.environ.get('FALLBACK_MODEL_ID')
HAIKU_MODEL_ID = os.environ.get('HAIKU_MODEL_ID')

ENABLE_COST_OPTIMIZATION = os.environ.get('ENABLE_COST_OPTIMIZATION', 'true').lower() == 'true'
SIMPLE_TICKET_CONFIDENCE_THRESHOLD = float(os.environ.get('SIMPLE_TICKET_CONFIDENCE_THRESHOLD', '0.7'))
SIMPLE_TICKET_MAX_TOKENS = int(os.environ.get('SIMPLE_TICKET_MAX_TOKENS', '512'))

MAX_RETRIES = int(os.environ.get('MAX_RETRIES', '3'))
RETRY_BASE_DELAY_MS = int(os.environ.get('RETRY_BASE_DELAY_MS', '1000'))

PSA_SECRET_NAME = os.environ.get('PSA_SECRET_NAME', 'msp/psa/api_keys')
RMM_SECRET_NAME = os.environ.get('RMM_SECRET_NAME', 'msp/rmm/api_keys')

GUARDRAIL_ID = os.environ.get('GUARDRAIL_ID')
GUARDRAIL_VERSION = os.environ.get('GUARDRAIL_VERSION')

IDEMPOTENCY_TABLE = os.environ.get('IDEMPOTENCY_TABLE')
IDEMPOTENCY_TTL_DAYS = int(os.environ.get('IDEMPOTENCY_TTL_DAYS', '30'))

METRICS_TABLE = os.environ.get('METRICS_TABLE')
METRICS_TTL_DAYS = int(os.environ.get('METRICS_TTL_DAYS', '90'))

FEW_SHOT_EXAMPLES_BUCKET = os.environ.get('FEW_SHOT_EXAMPLES_BUCKET')
FEW_SHOT_EXAMPLES_KEY = os.environ.get('FEW_SHOT_EXAMPLES_KEY', 'examples.json')
MAX_FEW_SHOT_EXAMPLES = int(os.environ.get('MAX_FEW_SHOT_EXAMPLES', '5'))
FEW_SHOT_CACHE_TTL = int(os.environ.get('FEW_SHOT_CACHE_TTL', '300'))

bedrock_runtime = boto3.client('bedrock-runtime', region_name=AWS_REGION)
secrets_client = boto3.client('secretsmanager', region_name=AWS_REGION)
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
cloudwatch = boto3.client('cloudwatch', region_name=AWS_REGION)
s3_client = boto3.client('s3', region_name=AWS_REGION)

_secret_cache = {}
_few_shot_cache = {
    'examples': [],
    'last_loaded': 0,
}

# ==============================================================================
# 2. SECRETS MANAGEMENT
# ==============================================================================

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

# ==============================================================================
# 3. FEW-SHOT EXAMPLES LOADER
# ==============================================================================

@xray_recorder.capture('load_few_shot_examples')
def load_few_shot_examples() -> List[Dict[str, Any]]:
    """Loads approved few-shot examples from S3 with in-memory caching."""
    if not FEW_SHOT_EXAMPLES_BUCKET:
        return []
    
    current_time = time.time()
    
    if (current_time - _few_shot_cache['last_loaded']) < FEW_SHOT_CACHE_TTL:
        return _few_shot_cache['examples']
    
    try:
        response = s3_client.get_object(
            Bucket=FEW_SHOT_EXAMPLES_BUCKET,
            Key=FEW_SHOT_EXAMPLES_KEY
        )
        examples = json.loads(response['Body'].read().decode('utf-8'))
        examples = examples[:MAX_FEW_SHOT_EXAMPLES]
        
        _few_shot_cache['examples'] = examples
        _few_shot_cache['last_loaded'] = current_time
        
        logger.info(f"Loaded {len(examples)} few-shot examples from S3")
        return examples
    
    except s3_client.exceptions.NoSuchKey:
        logger.info("No few-shot examples file found, starting with empty list")
        _few_shot_cache['examples'] = []
        _few_shot_cache['last_loaded'] = current_time
        return []
    except Exception as e:
        logger.warning(f"Failed to load few-shot examples from S3: {e}")
        return _few_shot_cache['examples']

# ==============================================================================
# 4. IDEMPOTENCY LAYER
# ==============================================================================

def check_idempotency(ticket_id: str) -> bool:
    """Returns True if this ticket has already been processed."""
    if not IDEMPOTENCY_TABLE:
        logger.warning("Idempotency table not configured, skipping check")
        return False
    
    try:
        table = dynamodb.Table(IDEMPOTENCY_TABLE)
        response = table.get_item(Key={'ticket_id': ticket_id})
        
        if 'Item' in response:
            item = response['Item']
            logger.info(f"Ticket {ticket_id} already processed (status: {item.get('processing_status')}, at: {item.get('processed_at')}). Skipping.")
            return True
        return False
    except ClientError as e:
        logger.error(f"Failed to check idempotency for ticket {ticket_id}: {e}")
        return False

def mark_processing(ticket_id: str) -> bool:
    """Marks the ticket as PROCESSING using a conditional write."""
    if not IDEMPOTENCY_TABLE:
        return True
    
    try:
        table = dynamodb.Table(IDEMPOTENCY_TABLE)
        ttl_timestamp = int((datetime.utcnow() + timedelta(days=IDEMPOTENCY_TTL_DAYS)).timestamp())
        
        table.put_item(
            Item={
                'ticket_id': ticket_id,
                'processing_status': 'PROCESSING',
                'processed_at': datetime.utcnow().isoformat(),
                'ttl': ttl_timestamp
            },
            ConditionExpression='attribute_not_exists(ticket_id)'
        )
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            logger.warning(f"Ticket {ticket_id} already marked as processing (race condition)")
            return False
        logger.error(f"Failed to mark ticket {ticket_id} as processing: {e}")
        raise

def mark_completed(ticket_id: str, enrichment_data: Dict[str, Any]):
    """Marks the ticket as successfully completed."""
    if not IDEMPOTENCY_TABLE:
        return
    
    try:
        table = dynamodb.Table(IDEMPOTENCY_TABLE)
        table.update_item(
            Key={'ticket_id': ticket_id},
            UpdateExpression='SET processing_status = :status, processed_at = :timestamp, enrichment_data = :data',
            ExpressionAttributeValues={
                ':status': 'COMPLETED',
                ':timestamp': datetime.utcnow().isoformat(),
                ':data': json.dumps(enrichment_data)
            }
        )
    except ClientError as e:
        logger.error(f"Failed to mark ticket {ticket_id} as completed: {e}")

def mark_failed(ticket_id: str, error_message: str):
    """Deletes the idempotency record so the ticket can be retried."""
    if not IDEMPOTENCY_TABLE:
        return
    
    try:
        table = dynamodb.Table(IDEMPOTENCY_TABLE)
        table.delete_item(Key={'ticket_id': ticket_id})
        logger.info(f"Deleted idempotency record for failed ticket {ticket_id} to allow retry")
    except ClientError as e:
        logger.error(f"Failed to delete idempotency record for ticket {ticket_id}: {e}")

def clear_idempotency_record(ticket_id: str):
    """Manually clears the idempotency record for a ticket."""
    if not IDEMPOTENCY_TABLE:
        return
    
    try:
        table = dynamodb.Table(IDEMPOTENCY_TABLE)
        table.delete_item(Key={'ticket_id': ticket_id})
        logger.info(f"Manually cleared idempotency record for ticket {ticket_id}")
    except ClientError as e:
        logger.error(f"Failed to clear idempotency record for ticket {ticket_id}: {e}")

# ==============================================================================
# 5. BEDROCK GUARDRAIL (CORRECTED - distinguishes BLOCK vs ANONYMIZE)
# ==============================================================================

# Action constants for clarity
GUARDRAIL_ACTION_NONE = 'NONE'
GUARDRAIL_ACTION_BLOCK = 'GUARDRAIL_INTERVENED_BLOCK'
GUARDRAIL_ACTION_ANONYMIZE = 'GUARDRAIL_INTERVENED_ANONYMIZE'


def apply_guardrail(text: str, source: str = 'INPUT') -> Dict[str, Any]:
    """
    Applies Bedrock Guardrail to text.
    
    The Bedrock Guardrail API has two intervention modes with different response shapes:
      - BLOCK mode (content rejected entirely):
          action='GUARDRAIL_INTERVENED', outputs=[]
      - ANONYMIZE mode (PII replaced with [NAME], etc.):
          action='GUARDRAIL_INTERVENED', outputs=[{'text': '...sanitized...'}]
      - Pass mode (content allowed):
          action='NONE'
    
    This function distinguishes all three cases and returns distinct action values
    so callers can handle each correctly.
    
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
                # ANONYMIZE case: guardrail returned sanitized text
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
                # BLOCK case: guardrail rejected content entirely, no sanitized output
                # Return empty text so callers correctly detect the block
                logger.warning(
                    f"Guardrail BLOCKED content on {source}: {assessments}"
                )
                return {
                    'action': GUARDRAIL_ACTION_BLOCK,
                    'text': '',
                    'assessments': assessments,
                }
        else:
            # NONE case: content passed through unchanged
            return {'action': GUARDRAIL_ACTION_NONE, 'text': text, 'assessments': []}
    
    except ClientError as e:
        logger.error(f"Guardrail API error: {e}")
        raise  # fail closed


# ==============================================================================
# 6. RETRY LOGIC WITH EXPONENTIAL BACKOFF
# ==============================================================================

def _is_retryable_error(error: Exception) -> bool:
    """Determines if an error is retryable (transient) or non-retryable (permanent)."""
    if isinstance(error, ClientError):
        error_code = error.response.get('Error', {}).get('Code', '')
        
        retryable_codes = [
            'ThrottlingException',
            'ServiceQuotaExceededException',
            'ModelTimeoutException',
            'ServiceUnavailable',
            'InternalServerException',
        ]
        
        if error_code in retryable_codes:
            return True
        
        status_code = error.response.get('ResponseMetadata', {}).get('HTTPStatusCode', 0)
        if status_code in [429, 500, 502, 503, 504]:
            return True
    
    if 'timeout' in str(error).lower():
        return True
    
    return False


def _calculate_retry_delay(attempt: int) -> float:
    """Calculates delay for exponential backoff with jitter."""
    base_delay = RETRY_BASE_DELAY_MS * (2 ** attempt)
    jitter = random.randint(0, base_delay // 2)
    return (base_delay + jitter) / 1000.0


@xray_recorder.capture('invoke_model_with_retry')
def _invoke_model_with_retry(model_id: str, body: str) -> Tuple[Dict[str, Any], int]:
    """Invokes a Bedrock model with retry logic."""
    last_error = None
    retry_count = 0
    
    xray_recorder.put_annotation('model_id', model_id)
    
    for attempt in range(MAX_RETRIES):
        try:
            logger.info(f"Invoking model {model_id} (attempt {attempt + 1}/{MAX_RETRIES})")
            
            response = bedrock_runtime.invoke_model(
                modelId=model_id,
                body=body
            )
            
            response_body = json.loads(response.get('body').read())
            xray_recorder.put_annotation('retry_count', retry_count)
            return response_body, retry_count
        
        except Exception as e:
            last_error = e
            retry_count = attempt + 1
            
            if not _is_retryable_error(e):
                logger.error(f"Non-retryable error from model {model_id}: {e}")
                raise
            
            if attempt < MAX_RETRIES - 1:
                delay = _calculate_retry_delay(attempt)
                logger.warning(f"Retryable error from model {model_id}: {e}. Retrying in {delay:.2f}s...")
                time.sleep(delay)
            else:
                logger.error(f"All {MAX_RETRIES} retries exhausted for model {model_id}: {e}")
    
    raise last_error


def _emit_fallback_metric():
    """Emits a custom CloudWatch metric when fallback is triggered."""
    try:
        cloudwatch.put_metric_data(
            Namespace='Custom/MSP-Triage',
            MetricData=[{
                'MetricName': 'FallbackTriggered',
                'Value': 1,
                'Unit': 'Count'
            }]
        )
    except Exception as e:
        logger.warning(f"Failed to emit fallback metric: {e}")

# ==============================================================================
# 7. COMPLEXITY CLASSIFIER
# ==============================================================================

@xray_recorder.capture('classify_ticket_complexity')
def classify_ticket_complexity(context: Dict[str, Any]) -> str:
    """Classifies ticket complexity using deterministic heuristics."""
    subject = (context.get('subject') or '').lower()
    description = (context.get('description') or '').lower()
    email_thread = (context.get('email_thread') or '').lower()
    combined_text = f"{subject} {description} {email_thread}"
    
    complex_indicators = [
        r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
        r'\b[A-Z]{2,}-[A-Z0-9]+-\d+\b',
        r'\b\d{3}\s+\d{1,3}\.\d{1,3}\.\d{1,3}\b',
        r'\b0x[0-9a-fA-F]+\b',
        r'\b(ransomware|malware|breach|phishing|compromised|infected)\b',
        r'\b(critical|outage|down|production|emergency)\b',
        r'\b(domain|active directory|dns|dhcp|firewall|switch|router|vlan)\b',
        r'\b(migration|deployment|upgrade|rollback)\b',
    ]
    
    for pattern in complex_indicators:
        if re.search(pattern, combined_text):
            return 'complex'
    
    simple_patterns = [
        r'\b(password reset|reset password|forgot password|unlock account)\b',
        r'\b(how do i|how to|where is|can you show me)\b',
        r'\b(printer|print queue|toner|paper jam)\b',
        r'\b(new employee|onboarding|offboarding|new hire)\b',
        r'\b(software install|install application|request software)\b',
        r'\b(meeting room|conference room|book room)\b',
        r'\b(mouse|keyboard|monitor|laptop battery)\b',
    ]
    
    simple_match_count = sum(1 for p in simple_patterns if re.search(p, combined_text))
    text_length = len(combined_text)
    
    if simple_match_count >= 1 and text_length < 500:
        return 'simple'
    if text_length < 150 and simple_match_count >= 1:
        return 'simple'
    if simple_match_count >= 1 and text_length >= 500:
        return 'unknown'
    if text_length < 200 and simple_match_count == 0:
        return 'unknown'
    
    return 'complex'

# ==============================================================================
# 8. PROMPT BUILDERS
# ==============================================================================

def _build_haiku_prompt(context: Dict[str, Any]) -> str:
    """Builds a simpler prompt optimized for Haiku's speed."""
    return f"""Analyze this MSP ticket and return JSON.

Subject: {context.get('subject')}
Description: {context.get('description')}
Email Thread: {context.get('email_thread', 'None')}
RMM Alerts: {json.dumps(context.get('rmm_alerts', []))}

Return ONLY valid JSON:
{{
  "summary": "One-sentence summary.",
  "category": "Hardware|Software|Network|Security|User Request",
  "priority": "Low|Medium|High|Critical",
  "extracted_entities": {{"hostname": null, "error_code": null}},
  "draft_internal_notes": "Brief technical note.",
  "confidence_score": 0.0
}}"""


def _build_sonnet_prompt(context: Dict[str, Any]) -> str:
    """Builds the full prompt for Sonnet models, with few-shot examples."""
    examples = load_few_shot_examples()
    
    examples_section = ""
    if examples:
        examples_section = "\n\nLearn from these past corrections:\n"
        for i, ex in enumerate(examples, 1):
            examples_section += f"""
Example {i}:
Input: {ex.get('input_summary', 'N/A')}
Correct Output: {json.dumps(ex.get('output', {}))}
Rationale: {ex.get('rationale', 'N/A')}
"""
    
    return f"""Analyze the following MSP ticket context and return the JSON payload.
{examples_section}
Context:
- Subject: {context.get('subject')}
- Description: {context.get('description')}
- Email Thread: {context.get('email_thread', 'No thread available')}
- Recent RMM Alerts: {json.dumps(context.get('rmm_alerts', []))}

Required JSON Schema:
{{
  "summary": "A concise 2-sentence summary of the issue.",
  "category": "Choose one: [Hardware, Software, Network, Security, User Request]",
  "priority": "Choose one: [Low, Medium, High, Critical]",
  "extracted_entities": {{"hostname": "string or null", "error_code": "string or null"}},
  "draft_internal_notes": "Technical notes for the assigning engineer, including any relevant RMM alert context.",
  "confidence_score": 0.0
}}"""

# ==============================================================================
# 9. EXTERNAL API INTEGRATIONS
# ==============================================================================

def make_api_request(url: str, headers: Dict[str, str], method: str = 'GET', data: Dict = None) -> Any:
    """Generic helper for making REST API calls using standard library urllib."""
    req = urllib.request.Request(url, headers=headers, method=method)
    if data:
        req.data = json.dumps(data).encode('utf-8')
        req.add_header('Content-Type', 'application/json')
        
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        logger.error(f"API Error {e.code}: {error_body}")
        raise
    except Exception as e:
        logger.error(f"Request failed: {str(e)}")
        raise

def _get_connectwise_headers(psa_secret: Dict[str, str]) -> Dict[str, str]:
    """Builds ConnectWise API headers with Basic Auth."""
    auth_string = f"{psa_secret['COMPANY_ID']}+{psa_secret['PUBLIC_KEY']}:{psa_secret['PRIVATE_KEY']}"
    auth_bytes = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
    
    return {
        'Authorization': f"Basic {auth_bytes}",
        'Accept': 'application/vnd.connectwise.com+json; version=v2024.1',
        'Content-Type': 'application/json',
        'clientId': psa_secret.get('CLIENT_ID', 'MSP_Triage_Agent')
    }

@xray_recorder.capture('get_psa_ticket_context')
def get_psa_ticket_context(ticket_id: str) -> Dict[str, Any]:
    """Fetches ticket details and email thread from ConnectWise Manage."""
    psa_secret = get_secret(PSA_SECRET_NAME)
    base_url = psa_secret['BASE_URL'].rstrip('/')
    headers = _get_connectwise_headers(psa_secret)
    
    conditions = f"id={ticket_id}"
    fields = "id,summary,description,company,board,priority,customFields"
    ticket_url = f"{base_url}/v4_6_release/apis/3.0/service/tickets?conditions={conditions}&fields={fields}"
    
    activities_url = f"{base_url}/v4_6_release/apis/3.0/service/tickets/{ticket_id}/activities?conditions=communicationType='Email'&orderBy=dateEntered desc"
    
    try:
        ticket_data = make_api_request(ticket_url, headers)
        ticket = ticket_data[0] if ticket_data else {}
        
        activities_data = make_api_request(activities_url, headers)
        email_thread = "\n---\n".join([
            f"[{act.get('dateEntered', 'Unknown')}] {act.get('contactName', 'Unknown')}: {act.get('notes', '')}" 
            for act in activities_data
        ])
        
        return {
            "subject": ticket.get("summary", "No Subject"),
            "description": ticket.get("description", ""),
            "customer_id": str(ticket.get("company", {}).get("id", "UNKNOWN")),
            "email_thread": email_thread if email_thread else "No email thread available"
        }
    except Exception as e:
        logger.error(f"Failed to fetch ConnectWise context for ticket {ticket_id}: {e}")
        raise

@xray_recorder.capture('update_psa_ticket')
def update_psa_ticket(ticket_id: str, enrichment_data: Dict[str, Any]) -> bool:
    """Updates the ticket in ConnectWise Manage with AI enrichment data."""
    psa_secret = get_secret(PSA_SECRET_NAME)
    base_url = psa_secret['BASE_URL'].rstrip('/')
    headers = _get_connectwise_headers(psa_secret)
    
    # IMPORTANT: Replace these IDs with your actual ConnectWise custom field IDs
    custom_field_ids = {
        "category": 123,
        "priority": 124,
        "summary": 125
    }
    
    custom_fields_payload = {
        "customFields": [
            {"id": custom_field_ids["category"], "value": enrichment_data.get("category")},
            {"id": custom_field_ids["priority"], "value": enrichment_data.get("priority")},
            {"id": custom_field_ids["summary"], "value": enrichment_data.get("summary")}
        ]
    }
    
    ticket_url = f"{base_url}/v4_6_release/apis/3.0/service/tickets/{ticket_id}"
    make_api_request(ticket_url, headers, method='PATCH', data=custom_fields_payload)
    
    activity_payload = {
        "action": "Internal Note",
        "notes": f"🤖 AI Triage Enrichment:\n{enrichment_data.get('draft_internal_notes')}",
        "internalAnalysisFlag": True
    }
    
    activities_url = f"{base_url}/v4_6_release/apis/3.0/service/tickets/{ticket_id}/activities"
    make_api_request(activities_url, headers, method='POST', data=activity_payload)
    
    return True

@xray_recorder.capture('get_rmm_alerts')
def get_rmm_alerts(customer_id: str) -> list:
    """Fetches recent, open alerts from NinjaOne for a specific organization."""
    rmm_secret = get_secret(RMM_SECRET_NAME)
    base_url = rmm_secret['BASE_URL'].rstrip('/')
    
    headers = {
        'Authorization': f"Bearer {rmm_secret['API_TOKEN']}",
        'Accept': 'application/json'
    }
    
    alerts_url = f"{base_url}/v2/alerts?organizationId={customer_id}&state=open&limit=10"
    
    try:
        alerts_data = make_api_request(alerts_url, headers)
        formatted_alerts = []
        for alert in alerts_data.get('data', []):
            formatted_alerts.append({
                "device": alert.get('deviceName', 'Unknown Device'),
                "alert_name": alert.get('alertName', 'Unknown Alert'),
                "severity": alert.get('severity', 'Unknown'),
                "timestamp": alert.get('alertTime', 'Unknown')
            })
        return formatted_alerts
    except Exception as e:
        logger.warning(f"Failed to fetch NinjaOne alerts for org {customer_id}, proceeding without them: {e}")
        return []

# ==============================================================================
# 10. AMAZON BEDROCK AI REASONING (CORRECTED - handles all three guardrail states)
# ==============================================================================

@xray_recorder.capture('invoke_bedrock_llm')
def invoke_bedrock_llm(context: Dict[str, Any], complexity: str = 'complex') -> Tuple[Dict[str, Any], int, str, int, str, bool, int]:
    """
    Invokes Claude with guardrail protection, retry logic, fallback, and cost optimization.
    
    Returns:
        Tuple of:
        - enrichment_data
        - guardrail_anonymizations: Number of ANONYMIZE interventions (PII sanitized)
        - model_used
        - total_retries
        - final_complexity
        - fallback_used
        - guardrail_blocks: Number of BLOCK interventions (content rejected)
    """
    anonymizations = 0
    blocks = 0
    total_retries = 0
    final_complexity = complexity
    fallback_used = False
    
    if ENABLE_COST_OPTIMIZATION and complexity == 'simple' and HAIKU_MODEL_ID:
        primary_model = HAIKU_MODEL_ID
        fallback_model = MODEL_ID
        max_tokens = SIMPLE_TICKET_MAX_TOKENS
        user_prompt = _build_haiku_prompt(context)
        logger.info(f"Routing to Haiku (simple ticket)")
    else:
        primary_model = MODEL_ID
        fallback_model = FALLBACK_MODEL_ID
        max_tokens = 1024
        user_prompt = _build_sonnet_prompt(context)
        logger.info(f"Routing to Sonnet (complexity: {complexity})")
    
    # --- INPUT GUARDRAIL (CORRECTED) ---
    input_result = apply_guardrail(user_prompt, source='INPUT')
    
    if input_result['action'] == GUARDRAIL_ACTION_BLOCK:
        # Guardrail rejected the content entirely — fail the ticket
        logger.error(
            f"Input guardrail BLOCKED ticket content: {input_result['assessments']}"
        )
        raise ValueError("Input contains sensitive or inappropriate content")
    
    if input_result['action'] == GUARDRAIL_ACTION_ANONYMIZE:
        # Guardrail sanitized the content — proceed with sanitized version
        anonymizations += 1
        user_prompt = input_result['text']
        logger.info("Input guardrail anonymized PII, proceeding with sanitized text")
    
    # --- LLM INVOCATION ---
    system_prompt = """You are an expert MSP Service Desk Dispatcher. Analyze ticket data and return ONLY valid JSON matching the schema. Do not include markdown formatting or explanations."""
    
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}]
    })
    
    model_used = None
    response_body = None
    
    try:
        response_body, retries = _invoke_model_with_retry(primary_model, body)
        model_used = primary_model
        total_retries += retries
    except Exception as e:
        logger.warning(f"Primary model {primary_model} failed: {e}")
        
        if fallback_model:
            fallback_used = True
            logger.info(f"Switching to fallback model: {fallback_model}")
            _emit_fallback_metric()
            try:
                response_body, retries = _invoke_model_with_retry(fallback_model, body)
                model_used = fallback_model
                total_retries += retries + MAX_RETRIES
            except Exception as e2:
                raise e2
        else:
            raise
    
    if not model_used or response_body is None:
        raise Exception("All models failed")
    
    # --- PARSE RESPONSE ---
    try:
        llm_output_text = response_body['content'][0]['text']
        
        # --- OUTPUT GUARDRAIL (CORRECTED) ---
        output_result = apply_guardrail(llm_output_text, source='OUTPUT')
        
        if output_result['action'] == GUARDRAIL_ACTION_BLOCK:
            logger.error(
                f"Output guardrail BLOCKED LLM response: {output_result['assessments']}"
            )
            raise ValueError("Output contains sensitive or inappropriate content")
        
        if output_result['action'] == GUARDRAIL_ACTION_ANONYMIZE:
            anonymizations += 1
            llm_output_text = output_result['text']
            logger.info("Output guardrail anonymized PII, proceeding with sanitized text")
        
        # Parse JSON (handling potential markdown code blocks)
        clean_text = llm_output_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:-3]
        elif clean_text.startswith("```"):
            clean_text = clean_text[3:-3]
        
        enrichment_data = json.loads(clean_text)
        
        xray_recorder.put_annotation('model_used', model_used)
        xray_recorder.put_annotation('fallback_used', fallback_used)
        xray_recorder.put_annotation('guardrail_anonymizations', anonymizations)
        xray_recorder.put_annotation('guardrail_blocks', blocks)
        
        return enrichment_data, anonymizations, model_used, total_retries, final_complexity, fallback_used, blocks
    
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"Error parsing Bedrock response: {e}")
        raise

# ==============================================================================
# 11. METRICS WRITER
# ==============================================================================

@xray_recorder.capture('write_metrics_record')
def write_metrics_record(
    ticket_id: str,
    customer_id: str,
    enrichment_data: Dict[str, Any],
    model_id: str,
    processing_duration_ms: int,
    guardrail_interventions: int,
    fallback_triggered: bool = False,
    retry_count: int = 0,
    complexity: str = 'complex',
    haiku_safety_net_triggered: bool = False,
    guardrail_blocks: int = 0
):
    """Writes a metrics record to DynamoDB for weekly reporting."""
    if not METRICS_TABLE:
        logger.warning("Metrics table not configured, skipping metrics write")
        return
    
    try:
        table = dynamodb.Table(METRICS_TABLE)
        ttl_timestamp = int((datetime.utcnow() + timedelta(days=METRICS_TTL_DAYS)).timestamp())
        
        table.put_item(Item={
            'ticket_id': ticket_id,
            'customer_id': customer_id,
            'timestamp': datetime.utcnow().isoformat(),
            'ai_category': enrichment_data.get('category'),
            'ai_priority': enrichment_data.get('priority'),
            'ai_confidence_score': enrichment_data.get('confidence_score', 0),
            'model_id_used': model_id,
            'processing_duration_ms': processing_duration_ms,
            'guardrail_interventions': guardrail_interventions,
            'guardrail_blocks': guardrail_blocks,
            'fallback_triggered': fallback_triggered,
            'retry_count': retry_count,
            'complexity': complexity,
            'haiku_safety_net_triggered': haiku_safety_net_triggered,
            'ttl': ttl_timestamp
        })
        
        logger.info(
            f"Metrics record written for ticket {ticket_id} "
            f"(model: {model_id}, complexity: {complexity}, fallback: {fallback_triggered}, "
            f"safety_net: {haiku_safety_net_triggered}, guardrail_blocks: {guardrail_blocks})"
        )
    except ClientError as e:
        logger.error(f"Failed to write metrics record for ticket {ticket_id}: {e}")

# ==============================================================================
# 12. LAMBDA HANDLER
# ==============================================================================

@xray_recorder.capture('enrich_ticket')
def _enrich_ticket(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Core enrichment logic with complexity classification, cost optimization, and safety net."""
    ticket_id = payload.get("ticket_id")
    if not ticket_id:
        raise ValueError("Missing ticket_id")

    xray_recorder.put_annotation('ticket_id', ticket_id)
    
    logger.info(f"Starting enrichment for ticket: {ticket_id}")

    if check_idempotency(ticket_id):
        return {"status": "SKIPPED", "reason": "Already processed"}

    if not mark_processing(ticket_id):
        logger.warning(f"Ticket {ticket_id} is already being processed by another instance")
        return {"status": "SKIPPED", "reason": "Currently being processed"}

    start_time = time.time()
    guardrail_anonymizations = 0
    guardrail_blocks = 0
    model_used = MODEL_ID
    retry_count = 0
    complexity = 'complex'
    fallback_used = False
    haiku_safety_net_triggered = False
    
    try:
        psa_context = get_psa_ticket_context(ticket_id)
        psa_context["rmm_alerts"] = get_rmm_alerts(psa_context.get("customer_id"))

        complexity = classify_ticket_complexity(psa_context)
        logger.info(f"Ticket {ticket_id} classified as: {complexity}")
        
        xray_recorder.put_annotation('complexity', complexity)

        (enrichment, guardrail_anonymizations, model_used, retry_count, 
         final_complexity, fallback_used, guardrail_blocks) = \
            invoke_bedrock_llm(psa_context, complexity=complexity)
        
        if model_used == HAIKU_MODEL_ID:
            confidence = enrichment.get("confidence_score", 0)
            if confidence < SIMPLE_TICKET_CONFIDENCE_THRESHOLD:
                haiku_safety_net_triggered = True
                logger.warning(
                    f"Haiku confidence ({confidence}) below threshold "
                    f"({SIMPLE_TICKET_CONFIDENCE_THRESHOLD}), re-running with Sonnet"
                )
                (enrichment, guardrail_anonymizations, model_used, retry_count, 
                 final_complexity, fallback_used, guardrail_blocks) = \
                    invoke_bedrock_llm(psa_context, complexity='unknown')
                complexity = final_complexity
        
        confidence = enrichment.get("confidence_score", 0)
        if confidence < 0.7:
            enrichment["draft_internal_notes"] += " [FLAG: Low confidence, requires human dispatcher review]"
            logger.warning(f"Low confidence score ({confidence}) for ticket {ticket_id}")
        
        xray_recorder.put_annotation('confidence_score', confidence)

        update_psa_ticket(ticket_id, enrichment)
        mark_completed(ticket_id, enrichment)
        
        processing_duration_ms = int((time.time() - start_time) * 1000)
        
        xray_recorder.put_metadata('processing_duration_ms', processing_duration_ms)
        xray_recorder.put_metadata('final_model_used', model_used)
        xray_recorder.put_metadata('retry_count', retry_count)
        
        write_metrics_record(
            ticket_id=ticket_id,
            customer_id=psa_context.get("customer_id", "UNKNOWN"),
            enrichment_data=enrichment,
            model_id=model_used,
            processing_duration_ms=processing_duration_ms,
            guardrail_interventions=guardrail_anonymizations,
            fallback_triggered=fallback_used,
            retry_count=retry_count,
            complexity=complexity,
            haiku_safety_net_triggered=haiku_safety_net_triggered,
            guardrail_blocks=guardrail_blocks
        )
        
        return enrichment

    except Exception as e:
        xray_recorder.put_annotation('error', True)
        xray_recorder.put_metadata('error_message', str(e))
        mark_failed(ticket_id, str(e))
        raise


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main entry point for the Lambda function."""
    
    if "Records" in event:
        failures = []
        for record in event["Records"]:
            try:
                _enrich_ticket(json.loads(record["body"]))
            except Exception:
                logger.exception("Enrichment failed for message %s", record.get("messageId"))
                failures.append({"itemIdentifier": record["messageId"]})
        return {"batchItemFailures": failures}

    try:
        payload = json.loads(event["body"]) if "body" in event else event
        
        if payload.get("force_reprocess"):
            ticket_id = payload.get("ticket_id")
            if ticket_id:
                clear_idempotency_record(ticket_id)
                logger.info(f"Force reprocessing requested for ticket {ticket_id}")
        
        return {"statusCode": 200, "body": json.dumps({"data": _enrich_ticket(payload)})}
    except Exception as exc:
        logger.exception("Fatal error")
        return {"statusCode": 500, "body": json.dumps({"error": str(exc)})}