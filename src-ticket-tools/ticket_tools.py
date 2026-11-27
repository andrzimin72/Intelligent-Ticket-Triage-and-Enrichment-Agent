"""
Ticket Tools for Bedrock Agent (Increment 3)

Provides ConnectWise ticket operations:
- create_ticket: Create a new support ticket (conversational confirmation)
- get_ticket_status: Look up a ticket by ID
- list_my_tickets: List recent tickets for the user (scoped to their email)

All operations are scoped to the user's own email address (from trusted session attributes).
Admin override is NOT supported for tickets — users can only see their own tickets.
"""

import json
import os
import logging
import base64
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError

from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

import agent_security as sec

logger = logging.getLogger()
logger.setLevel(logging.INFO)

PSA_SECRET_NAME = os.environ.get('PSA_SECRET_NAME')
AUDIT_LOG_TABLE = os.environ.get('AUDIT_LOG_TABLE')
RATE_LIMIT_TABLE = os.environ.get('RATE_LIMIT_TABLE')
DEFAULT_BOARD_ID = int(os.environ.get('DEFAULT_BOARD_ID', '1'))
DEFAULT_STATUS_ID = int(os.environ.get('DEFAULT_STATUS_ID', '1'))
DEFAULT_TYPE_ID = int(os.environ.get('DEFAULT_TYPE_ID', '1'))
DEFAULT_PRIORITY_ID = int(os.environ.get('DEFAULT_PRIORITY_ID', '1'))
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

secrets_client = boto3.client('secretsmanager', region_name=AWS_REGION)
_secret_cache = {}


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


def _get_connectwise_headers(psa_secret: Dict[str, str]) -> Dict[str, str]:
    auth_string = f"{psa_secret['COMPANY_ID']}+{psa_secret['PUBLIC_KEY']}:{psa_secret['PRIVATE_KEY']}"
    auth_bytes = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
    return {
        'Authorization': f"Basic {auth_bytes}",
        'Accept': 'application/vnd.connectwise.com+json; version=v2024.1',
        'Content-Type': 'application/json',
        'clientId': psa_secret.get('CLIENT_ID', 'AgentTicketTools')
    }


def cw_request(url: str, method: str = 'GET', body: Dict = None) -> Any:
    psa_secret = get_secret(PSA_SECRET_NAME)
    base_url = psa_secret['BASE_URL'].rstrip('/')
    headers = _get_connectwise_headers(psa_secret)
    
    req = urllib.request.Request(f"{base_url}{url}", headers=headers, method=method)
    if body:
        req.data = json.dumps(body).encode('utf-8')
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read()
            if response.status == 204 or not raw:
                return {}
            return json.loads(raw.decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        logger.error(f"ConnectWise API error {e.code}: {error_body}")
        raise
    except Exception as e:
        logger.error(f"ConnectWise request failed: {e}")
        raise


def get_user_email_from_graph(user_aad_id: str) -> Optional[str]:
    """
    Resolve the user's email address from Entra ID via the Graph API.
    We need this to scope ticket queries to the user's own tickets.
    
    Note: This requires the identity_tools Lambda's Graph credentials.
    For simplicity, we reuse the same Entra app registration.
    """
    # Import Graph helpers from identity_tools
    # In production, you'd refactor these into a shared module
    try:
        from identity_tools import get_graph_access_token, graph_api_request
        # But we need to set up the token cache first
        # For now, we'll make a direct Graph call
        import urllib.parse
        
        graph_secret = get_secret(os.environ.get('ENTRA_GRAPH_SECRET_NAME', 'msp/entra/graph_credentials'))
        # This is a simplification — in production, share the Graph client
        # For now, we'll assume the user's email is in session attributes
        # (set by teams_bot.py from the Teams activity)
        return None  # Placeholder — see note below
    except Exception as e:
        logger.error(f"Failed to get user email from Graph: {e}")
        return None


# =============================================================================
# TOOLS
# =============================================================================

@xray_recorder.capture('tool_create_ticket')
def tool_create_ticket(params: Dict[str, Any], identity: Dict[str, str]) -> Dict[str, Any]:
    """Create a new support ticket. Conversational confirmation only."""
    summary = params.get('summary', '').strip()
    description = params.get('description', '').strip()
    
    if not summary or not description:
        return {'success': False, 'error': 'summary and description are required'}
    
    # Rate limit check
    allowed, message = sec.consume_rate_limit(
        actor=identity['actor_aad_id'],
        operation='ticket_create',
        is_admin=False
    )
    if not allowed:
        return {'success': False, 'error': message}
    
    # Get user email from session attributes (set by teams_bot)
    user_email = identity.get('user_email')
    if not user_email:
        return {'success': False, 'error': 'User email not available. Please restart the conversation.'}
    
    # Create the ticket
    try:
        ticket_body = {
            'summary': summary[:100],  # CW has a limit
            'description': description[:2000],
            'board': {'id': DEFAULT_BOARD_ID},
            'status': {'id': DEFAULT_STATUS_ID},
            'type': {'id': DEFAULT_TYPE_ID},
            'priority': {'id': DEFAULT_PRIORITY_ID},
            'contactEmailAddress': user_email,
        }
        
        result = cw_request('/v4_6_release/apis/3.0/service/tickets', method='POST', body=ticket_body)
        ticket_id = result.get('id')
        
        response = {
            'success': True,
            'ticket_id': ticket_id,
            'message': f"Ticket #{ticket_id} created successfully. A technician will review it shortly."
        }
        
        sec.write_audit(
            actor_aad_id=identity['actor_aad_id'],
            tool_name='create_ticket',
            operation_type='write',
            parameters={'summary': summary, 'description': description[:100]},
            result=response,
            success=True,
            target_user_id=identity['actor_aad_id']
        )
        
        return response
    
    except Exception as e:
        logger.error(f"Failed to create ticket: {e}")
        sec.refund_rate_limit(actor=identity['actor_aad_id'], operation='ticket_create', is_admin=False)
        return {'success': False, 'error': 'Failed to create ticket. Please contact IT support directly.'}


@xray_recorder.capture('tool_get_ticket_status')
def tool_get_ticket_status(params: Dict[str, Any], identity: Dict[str, Any]) -> Dict[str, Any]:
    """Get the status of a specific ticket. Scoped to user's own tickets."""
    ticket_id = params.get('ticket_id')
    if not ticket_id:
        return {'success': False, 'error': 'ticket_id is required'}
    
    try:
        ticket_id = int(ticket_id)
    except (ValueError, TypeError):
        return {'success': False, 'error': 'ticket_id must be an integer'}
    
    user_email = identity.get('user_email')
    if not user_email:
        return {'success': False, 'error': 'User email not available.'}
    
    try:
        ticket = cw_request(f'/v4_6_release/apis/3.0/service/tickets/{ticket_id}')
        
        # Scope check: user can only see their own tickets
        ticket_email = ticket.get('contactEmailAddress') or ticket.get('contact', {}).get('email')
        if ticket_email and ticket_email.lower() != user_email.lower():
            return {'success': False, 'error': 'You can only view your own tickets.'}
        
        return {
            'success': True,
            'ticket_id': ticket.get('id'),
            'status': ticket.get('status', {}).get('name', 'Unknown'),
            'summary': ticket.get('summary', ''),
            'board': ticket.get('board', {}).get('name', ''),
        }
    
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {'success': False, 'error': f'Ticket #{ticket_id} not found.'}
        logger.error(f"Failed to get ticket {ticket_id}: {e}")
        return {'success': False, 'error': 'Failed to retrieve ticket status.'}
    except Exception as e:
        logger.error(f"Failed to get ticket {ticket_id}: {e}")
        return {'success': False, 'error': 'Failed to retrieve ticket status.'}


@xray_recorder.capture('tool_list_my_tickets')
def tool_list_my_tickets(params: Dict[str, Any], identity: Dict[str, Any]) -> Dict[str, Any]:
    """List recent tickets for the user. Scoped to their email."""
    limit = min(int(params.get('limit', 5)), 20)
    
    user_email = identity.get('user_email')
    if not user_email:
        return {'success': False, 'error': 'User email not available.'}
    
    try:
        # Query tickets where contact email matches user
        conditions = f'contactEmailAddress="{user_email}"'
        url = f'/v4_6_release/apis/3.0/service/tickets?conditions={conditions}&pageSize={limit}&orderBy=id desc'
        
        tickets = cw_request(url)
        
        # Format the response
        formatted = []
        for t in tickets:
            formatted.append({
                'ticket_id': t.get('id'),
                'summary': t.get('summary', ''),
                'status': t.get('status', {}).get('name', 'Unknown'),
                'board': t.get('board', {}).get('name', ''),
                'created': t.get('enteredTimeStamp', ''),
            })
        
        return {
            'success': True,
            'tickets': formatted,
            'count': len(formatted),
        }
    
    except Exception as e:
        logger.error(f"Failed to list tickets for {user_email}: {e}")
        return {'success': False, 'error': 'Failed to retrieve your tickets.'}


# =============================================================================
# HANDLER
# =============================================================================

_TOOLS = {
    '/create-ticket': tool_create_ticket,
    '/get-ticket-status': tool_get_ticket_status,
    '/list-my-tickets': tool_list_my_tickets,
}

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    api_path = event.get('apiPath')
    params = {p['name']: p['value'] for p in event.get('parameters', [])}
    
    # Strip forbidden fields
    for forbidden in ('user_aad_id', 'is_admin', 'actor_aad_id'):
        params.pop(forbidden, None)
    
    try:
        identity = sec.extract_trusted_identity(event)
        # Add user email from session attributes (set by teams_bot)
        attrs = event.get('sessionAttributes') or {}
        identity['user_email'] = attrs.get('user_email')
        
        if api_path in _TOOLS:
            result = _TOOLS[api_path](params, identity)
        else:
            result = {'success': False, 'error': f'Unknown API path: {api_path}'}
    except sec.IdentityError as exc:
        result = {'success': False, 'error': str(exc)}
    except Exception as exc:
        logger.exception(f"Unhandled error in ticket_tools")
        result = {'success': False, 'error': 'An internal error occurred.'}
    
    return {
        'messageVersion': '1.0',
        'response': {
            'actionGroup': event.get('actionGroup'),
            'apiPath': api_path,
            'httpMethod': event.get('httpMethod'),
            'httpStatusCode': 200 if result.get('success') else 400,
            'responseBody': {'application/json': {'body': json.dumps(result)}},
        },
    }
