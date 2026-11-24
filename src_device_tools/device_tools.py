"""
Device Tools for Bedrock Agent (Increment 3)

Provides NinjaOne device operations:
- list_my_devices: List devices owned by the user
- get_device_status: Check the status of a specific device
- get_device_alerts: Get recent alerts for a device

Device ownership is resolved via:
1. NinjaOne ownership field (configurable via DEVICE_OWNER_FIELD env var)
2. Optional DynamoDB mapping table fallback (if ownership field is not populated)

All operations are scoped to the user's own devices.
"""

import json
import os
import logging
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import boto3
from botocore.exceptions import ClientError

from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

import agent_security as sec

logger = logging.getLogger()
logger.setLevel(logging.INFO)

RMM_SECRET_NAME = os.environ.get('RMM_SECRET_NAME')
AUDIT_LOG_TABLE = os.environ.get('AUDIT_LOG_TABLE')
RATE_LIMIT_TABLE = os.environ.get('RATE_LIMIT_TABLE')
DEVICE_OWNER_FIELD = os.environ.get('DEVICE_OWNER_FIELD', 'assignedUser')
DEVICE_MAPPING_TABLE = os.environ.get('DEVICE_MAPPING_TABLE', '')
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

secrets_client = boto3.client('secretsmanager', region_name=AWS_REGION)
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
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


def ninja_request(url: str) -> Any:
    rmm_secret = get_secret(RMM_SECRET_NAME)
    base_url = rmm_secret['BASE_URL'].rstrip('/')
    headers = {
        'Authorization': f"Bearer {rmm_secret['API_TOKEN']}",
        'Accept': 'application/json'
    }
    
    req = urllib.request.Request(f"{base_url}{url}", headers=headers, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        logger.error(f"NinjaOne API error {e.code}: {error_body}")
        raise
    except Exception as e:
        logger.error(f"NinjaOne request failed: {e}")
        raise


def find_user_devices(user_email: str, user_aad_id: str) -> List[Dict[str, Any]]:
    """
    Find devices owned by the user.
    
    Strategy:
    1. Try NinjaOne ownership field first
    2. Fall back to DynamoDB mapping table if configured
    3. Return empty list if neither works
    """
    devices = []
    
    # Strategy 1: Query NinjaOne for devices with matching ownership field
    try:
        # NinjaOne API varies by version — this is a common pattern
        # Adjust the query based on your NinjaOne deployment
        all_devices = ninja_request('/v2/devices?pageSize=500')
        
        for device in all_devices.get('data', []):
            # Check various ownership field names
            owner = (
                device.get(DEVICE_OWNER_FIELD) or
                device.get('assignedUser') or
                device.get('owner') or
                device.get('primaryUser') or
                ''
            )
            
            # Match by email or user ID
            if owner and (owner.lower() == user_email.lower() or owner == user_aad_id):
                devices.append(device)
        
        if devices:
            logger.info(f"Found {len(devices)} devices via ownership field for {user_email}")
            return devices
    
    except Exception as e:
        logger.warning(f"Failed to query NinjaOne devices by ownership: {e}")
    
    # Strategy 2: Fall back to mapping table
    if DEVICE_MAPPING_TABLE:
        try:
            table = dynamodb.Table(DEVICE_MAPPING_TABLE)
            response = table.query(
                KeyConditionExpression='user_aad_id = :uid',
                ExpressionAttributeValues={':uid': user_aad_id}
            )
            
            device_ids = [item['device_id'] for item in response.get('Items', [])]
            
            if device_ids:
                # Fetch device details from NinjaOne
                for device_id in device_ids:
                    try:
                        device = ninja_request(f'/v2/devices/{device_id}')
                        devices.append(device)
                    except Exception as e:
                        logger.warning(f"Failed to fetch device {device_id}: {e}")
                
                logger.info(f"Found {len(devices)} devices via mapping table for {user_aad_id}")
                return devices
        
        except Exception as e:
            logger.warning(f"Failed to query device mapping table: {e}")
    
    logger.info(f"No devices found for user {user_email}")
    return []


# =============================================================================
# TOOLS
# =============================================================================

@xray_recorder.capture('tool_list_my_devices')
def tool_list_my_devices(params: Dict[str, Any], identity: Dict[str, Any]) -> Dict[str, Any]:
    """List devices owned by the user."""
    user_email = identity.get('user_email')
    if not user_email:
        return {'success': False, 'error': 'User email not available.'}
    
    devices = find_user_devices(user_email, identity['actor_aad_id'])
    
    formatted = []
    for d in devices:
        formatted.append({
            'device_id': str(d.get('id')),
            'device_name': d.get('systemName') or d.get('name', 'Unknown'),
            'device_type': d.get('deviceType', 'Unknown'),
            'last_seen': d.get('lastContacted', ''),
        })
    
    return {
        'success': True,
        'devices': formatted,
        'count': len(formatted),
    }


@xray_recorder.capture('tool_get_device_status')
def tool_get_device_status(params: Dict[str, Any], identity: Dict[str, Any]) -> Dict[str, Any]:
    """Get the status of a specific device. Scoped to user's own devices."""
    device_id = params.get('device_id')
    if not device_id:
        return {'success': False, 'error': 'device_id is required'}
    
    user_email = identity.get('user_email')
    if not user_email:
        return {'success': False, 'error': 'User email not available.'}
    
    # Verify the device belongs to the user
    user_devices = find_user_devices(user_email, identity['actor_aad_id'])
    user_device_ids = {str(d.get('id')) for d in user_devices}
    
    if device_id not in user_device_ids:
        return {'success': False, 'error': 'You can only view your own devices.'}
    
    try:
        device = ninja_request(f'/v2/devices/{device_id}')
        
        return {
            'success': True,
            'device_id': str(device.get('id')),
            'device_name': device.get('systemName') or device.get('name', 'Unknown'),
            'status': device.get('deviceStatus', 'Unknown'),
            'last_seen': device.get('lastContacted', ''),
            'os': device.get('os', {}).get('name', 'Unknown'),
        }
    
    except Exception as e:
        logger.error(f"Failed to get device {device_id}: {e}")
        return {'success': False, 'error': 'Failed to retrieve device status.'}


@xray_recorder.capture('tool_get_device_alerts')
def tool_get_device_alerts(params: Dict[str, Any], identity: Dict[str, Any]) -> Dict[str, Any]:
    """Get recent alerts for a device. Scoped to user's own devices."""
    device_id = params.get('device_id')
    limit = min(int(params.get('limit', 10)), 50)
    
    if not device_id:
        return {'success': False, 'error': 'device_id is required'}
    
    user_email = identity.get('user_email')
    if not user_email:
        return {'success': False, 'error': 'User email not available.'}
    
    # Verify the device belongs to the user
    user_devices = find_user_devices(user_email, identity['actor_aad_id'])
    user_device_ids = {str(d.get('id')) for d in user_devices}
    
    if device_id not in user_device_ids:
        return {'success': False, 'error': 'You can only view alerts for your own devices.'}
    
    try:
        alerts_data = ninja_request(f'/v2/devices/{device_id}/alerts?limit={limit}')
        
        formatted = []
        for alert in alerts_data.get('data', []):
            formatted.append({
                'alert_id': alert.get('id'),
                'alert_name': alert.get('alertName', 'Unknown'),
                'severity': alert.get('severity', 'Unknown'),
                'timestamp': alert.get('alertTime', ''),
                'message': alert.get('message', ''),
            })
        
        return {
            'success': True,
            'alerts': formatted,
            'count': len(formatted),
        }
    
    except Exception as e:
        logger.error(f"Failed to get alerts for device {device_id}: {e}")
        return {'success': False, 'error': 'Failed to retrieve device alerts.'}


# =============================================================================
# HANDLER
# =============================================================================

_TOOLS = {
    '/list-my-devices': tool_list_my_devices,
    '/get-device-status': tool_get_device_status,
    '/get-device-alerts': tool_get_device_alerts,
}

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    api_path = event.get('apiPath')
    params = {p['name']: p['value'] for p in event.get('parameters', [])}
    
    for forbidden in ('user_aad_id', 'is_admin', 'actor_aad_id'):
        params.pop(forbidden, None)
    
    try:
        identity = sec.extract_trusted_identity(event)
        attrs = event.get('sessionAttributes') or {}
        identity['user_email'] = attrs.get('user_email')
        
        if api_path in _TOOLS:
            result = _TOOLS[api_path](params, identity)
        else:
            result = {'success': False, 'error': f'Unknown API path: {api_path}'}
    except sec.IdentityError as exc:
        result = {'success': False, 'error': str(exc)}
    except Exception as exc:
        logger.exception(f"Unhandled error in device_tools")
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