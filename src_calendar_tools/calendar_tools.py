"""
Calendar Tools for Bedrock Agent (Increment 3)

Provides Microsoft Graph calendar operations:
- list_my_calendar: List upcoming events (scoped to user)
- find_free_time: Find free time slots (proper implementation using getSchedule)
- list_bookable_rooms: List available meeting rooms
- request_room_booking / execute_room_booking: Two-phase room booking

Privacy: Users can only see their own calendar. Meeting subjects are included
but the audit log redacts them to protect sensitive information.
"""

import json
import os
import logging
import urllib.parse
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple
import boto3
from botocore.exceptions import ClientError

from aws_xray_sdk.core import xray_recorder, patch
patch(['boto3'])

import agent_security as sec

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# =============================================================================
# CONFIGURATION
# =============================================================================

ENTRA_GRAPH_SECRET_NAME = os.environ.get('ENTRA_GRAPH_SECRET_NAME')
ENTRA_TENANT_ID = os.environ.get('ENTRA_TENANT_ID')
ENTRA_APP_CLIENT_ID = os.environ.get('ENTRA_APP_CLIENT_ID')
AUDIT_LOG_TABLE = os.environ.get('AUDIT_LOG_TABLE')
RATE_LIMIT_TABLE = os.environ.get('RATE_LIMIT_TABLE')
PENDING_OPERATIONS_TABLE = os.environ.get('PENDING_OPERATIONS_TABLE')
CONFIRMATION_NONCES_TABLE = os.environ.get('CONFIRMATION_NONCES_TABLE')
CONFIRMATION_SECRET_NAME = os.environ.get('CONFIRMATION_SECRET_NAME')
CONFIRMATION_TTL = int(os.environ.get('CONFIRMATION_TTL_SECONDS', '600'))
DEFAULT_TIMEZONE = os.environ.get('DEFAULT_TIMEZONE', 'America/New_York')
ROOM_FILTER = os.environ.get('ROOM_FILTER', '')
AWS_REGION = os.environ.get('AWS_REGION_NAME', 'us-east-1')

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

secrets_client = boto3.client('secretsmanager', region_name=AWS_REGION)
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
_secret_cache = {}
_token_cache = {'token': None, 'expires_at': 0}


# =============================================================================
# GRAPH API HELPERS
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


def get_graph_access_token() -> str:
    """Gets an OAuth2 access token for Microsoft Graph API."""
    current_time = datetime.utcnow().timestamp()
    
    if _token_cache['token'] and _token_cache['expires_at'] > current_time + 300:
        return _token_cache['token']
    
    graph_secret = get_secret(ENTRA_GRAPH_SECRET_NAME)
    client_secret = graph_secret.get('CLIENT_SECRET')
    
    if not client_secret:
        raise ValueError("CLIENT_SECRET not found in Entra Graph credentials")
    
    token_url = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/oauth2/v2.0/token"
    
    body = urllib.parse.urlencode({
        'client_id': ENTRA_APP_CLIENT_ID,
        'client_secret': client_secret,
        'scope': 'https://graph.microsoft.com/.default',
        'grant_type': 'client_credentials'
    }).encode('utf-8')
    
    req = urllib.request.Request(
        token_url,
        data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST'
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            token_response = json.loads(response.read().decode('utf-8'))
        
        access_token = token_response['access_token']
        expires_in = token_response.get('expires_in', 3600)
        
        _token_cache['token'] = access_token
        _token_cache['expires_at'] = current_time + expires_in
        
        logger.info("Successfully obtained Graph API access token")
        return access_token
    
    except Exception as e:
        logger.error(f"Failed to obtain Graph API access token: {e}")
        raise


def graph_request(endpoint: str, method: str = 'GET', body: Dict = None) -> Dict[str, Any]:
    """Makes a request to the Microsoft Graph API."""
    access_token = get_graph_access_token()
    url = f"{GRAPH_API_BASE}{endpoint}"
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    req = urllib.request.Request(url, headers=headers, method=method)
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
        logger.error(f"Graph API error {e.code}: {error_body}")
        raise
    except Exception as e:
        logger.error(f"Graph API request failed: {e}")
        raise


# =============================================================================
# FIND FREE TIME HELPERS (NEW)
# =============================================================================

def _parse_graph_datetime(dt_obj: Dict[str, Any]) -> Optional[datetime]:
    """
    Parse a Graph API dateTime object into a UTC datetime.
    
    Graph returns objects like:
      {"dateTime": "2026-11-16T14:00:00.0000000", "timeZone": "Eastern Standard Time"}
    
    We convert to UTC for consistent comparison.
    """
    if not dt_obj:
        return None
    
    dt_str = dt_obj.get('dateTime', '')
    
    try:
        # Handle various Graph datetime formats
        if '.' in dt_str:
            # Strip fractional seconds for fromisoformat compatibility
            dt_str = dt_str.split('.')[0]
        
        if dt_str.endswith('Z'):
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        elif 'T' in dt_str:
            dt = datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                # Assume UTC if no timezone
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.strptime(dt_str, '%Y-%m-%dT%H:%M:%S')
            dt = dt.replace(tzinfo=timezone.utc)
        
        # Convert to UTC
        return dt.astimezone(timezone.utc)
    
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse datetime {dt_obj}: {e}")
        return None


def _round_up_to_quarter(dt: datetime) -> datetime:
    """Round a datetime up to the next 15-minute boundary."""
    minutes = dt.minute
    if minutes == 0 and dt.second == 0:
        return dt
    elif minutes <= 15:
        return dt.replace(minute=15, second=0, microsecond=0)
    elif minutes <= 30:
        return dt.replace(minute=30, second=0, microsecond=0)
    elif minutes <= 45:
        return dt.replace(minute=45, second=0, microsecond=0)
    else:
        return (dt + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)


def _merge_overlapping(periods: List[Tuple[datetime, datetime]]) -> List[Tuple[datetime, datetime]]:
    """
    Merge overlapping or adjacent time periods.
    
    Input: [(start1, end1), (start2, end2), ...]
    Output: merged list with no overlaps
    
    Example:
      [(10:00, 11:00), (10:30, 11:30), (13:00, 14:00)]
      → [(10:00, 11:30), (13:00, 14:00)]
    """
    if not periods:
        return []
    
    sorted_periods = sorted(periods, key=lambda x: x[0])
    merged = [sorted_periods[0]]
    
    for start, end in sorted_periods[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            # Overlapping or adjacent - merge
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    
    return merged


def _find_free_slots(
    busy_periods: List[Tuple[datetime, datetime]],
    window_start: datetime,
    window_end: datetime,
    duration_minutes: int,
    limit: int,
    work_start_hour: Optional[int] = None,
    work_end_hour: Optional[int] = None,
    skip_weekends: bool = False
) -> List[Dict[str, Any]]:
    """
    Find free time slots within the window that don't overlap with busy periods.
    
    Algorithm:
    1. Round window_start up to next 15-minute boundary
    2. Walk forward in 15-minute increments
    3. For each candidate slot, check if it overlaps any busy period
    4. If no overlap, add to results
    5. If overlap, jump current time past the busy period
    6. Apply optional filters (working hours, weekends)
    7. Stop when we have `limit` slots or reach window_end
    
    Returns formatted slot objects with ISO timestamps and human-readable fields.
    """
    slots = []
    duration = timedelta(minutes=duration_minutes)
    
    # Round window_start up to the next 15-minute boundary
    current = _round_up_to_quarter(window_start)
    
    # Merge overlapping busy periods for simpler iteration
    merged_busy = _merge_overlapping(busy_periods)
    
    while current + duration <= window_end and len(slots) < limit:
        slot_end = current + duration
        
        # Skip weekends if requested
        if skip_weekends and current.weekday() >= 5:  # 5=Saturday, 6=Sunday
            days_until_monday = 7 - current.weekday()
            current = current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)
            continue
        
        # Skip outside working hours if specified
        if work_start_hour is not None and work_end_hour is not None:
            if current.hour < work_start_hour or current.hour >= work_end_hour:
                if current.hour < work_start_hour:
                    current = current.replace(hour=work_start_hour, minute=0, second=0, microsecond=0)
                else:
                    current = (current + timedelta(days=1)).replace(
                        hour=work_start_hour, minute=0, second=0, microsecond=0
                    )
                continue
        
        # Check if this slot overlaps with any busy period
        overlaps = False
        for busy_start, busy_end in merged_busy:
            if busy_start >= slot_end:
                # This and all future busy periods are after our slot
                break
            if busy_end <= current:
                # This busy period is before our slot
                continue
            # Overlap detected
            overlaps = True
            # Jump current past this busy period
            current = _round_up_to_quarter(busy_end)
            break
        
        if not overlaps:
            slots.append({
                'start': current.isoformat(),
                'end': slot_end.isoformat(),
                'duration_minutes': duration_minutes,
                'day_of_week': current.strftime('%A'),
                'date': current.strftime('%Y-%m-%d'),
                'time': current.strftime('%H:%M'),
            })
            # Move to next slot (15-minute increments for granularity)
            current += timedelta(minutes=15)
    
    return slots


# =============================================================================
# TOOLS
# =============================================================================

@xray_recorder.capture('tool_list_my_calendar')
def tool_list_my_calendar(params: Dict[str, Any], identity: Dict[str, Any]) -> Dict[str, Any]:
    """List upcoming calendar events for the user."""
    hours_ahead = min(int(params.get('hours_ahead', 24)), 168)
    limit = min(int(params.get('limit', 10)), 50)
    
    user_email = identity.get('user_email')
    if not user_email:
        return {'success': False, 'error': 'User email not available.'}
    
    try:
        now = datetime.now(timezone.utc)
        end_time = now + timedelta(hours=hours_ahead)
        
        # Use calendarView for recurring event expansion
        endpoint = (
            f"/users/{user_email}/calendarView"
            f"?startDateTime={now.isoformat()}"
            f"&endDateTime={end_time.isoformat()}"
            f"&$top={limit}"
            f"&$orderby=start/dateTime"
            f"&$select=subject,start,end,location,isAllDay"
        )
        
        events_data = graph_request(endpoint)
        
        formatted = []
        for event in events_data.get('value', []):
            formatted.append({
                'subject': event.get('subject', '(No subject)'),
                'start': event.get('start', {}).get('dateTime', ''),
                'end': event.get('end', {}).get('dateTime', ''),
                'location': event.get('location', {}).get('displayName', ''),
                'is_all_day': event.get('isAllDay', False),
            })
        
        return {
            'success': True,
            'events': formatted,
            'count': len(formatted),
        }
    
    except Exception as e:
        logger.error(f"Failed to list calendar for {user_email}: {e}")
        return {'success': False, 'error': 'Failed to retrieve your calendar.'}


@xray_recorder.capture('tool_find_free_time')
def tool_find_free_time(params: Dict[str, Any], identity: Dict[str, Any]) -> Dict[str, Any]:
    """
    Find free time slots in the user's calendar.
    
    Uses Graph API's getSchedule endpoint to retrieve busy periods,
    then finds gaps that fit the requested duration.
    
    Optional filters:
    - work_start_hour / work_end_hour: only return slots within working hours
    - skip_weekends: exclude Saturday and Sunday
    """
    duration_minutes = int(params.get('duration_minutes', 30))
    hours_ahead = min(int(params.get('hours_ahead', 48)), 168)
    limit = min(int(params.get('limit', 5)), 10)
    
    # Optional filters
    work_start_hour = params.get('work_start_hour')
    work_end_hour = params.get('work_end_hour')
    skip_weekends = params.get('skip_weekends', 'false').lower() == 'true'
    
    user_email = identity.get('user_email')
    if not user_email:
        return {'success': False, 'error': 'User email not available.'}
    
    if duration_minutes < 15 or duration_minutes > 480:
        return {'success': False, 'error': 'duration_minutes must be between 15 and 480 (8 hours).'}
    
    try:
        now = datetime.now(timezone.utc)
        end_time = now + timedelta(hours=hours_ahead)
        
        # Use getSchedule to find busy periods
        body = {
            "schedules": [user_email],
            "startTime": {
                "dateTime": now.strftime('%Y-%m-%dT%H:%M:%S'),
                "timeZone": "UTC"
            },
            "endTime": {
                "dateTime": end_time.strftime('%Y-%m-%dT%H:%M:%S'),
                "timeZone": "UTC"
            },
            "availabilityViewInterval": 15  # 15-minute granularity
        }
        
        result = graph_request("/me/calendar/getSchedule", method='POST', body=body)
        
        # Extract busy periods from scheduleItems
        schedules = result.get('value', [])
        if not schedules:
            return {
                'success': True,
                'slots': [],
                'count': 0,
                'message': 'No schedule data available. Your calendar may be empty.'
            }
        
        schedule = schedules[0]
        busy_periods = []
        
        for item in schedule.get('scheduleItems', []):
            start = _parse_graph_datetime(item.get('start', {}))
            end = _parse_graph_datetime(item.get('end', {}))
            if start and end:
                busy_periods.append((start, end))
        
        logger.info(f"Found {len(busy_periods)} busy periods for {user_email}")
        
        # Find free slots
        slots = _find_free_slots(
            busy_periods=busy_periods,
            window_start=now,
            window_end=end_time,
            duration_minutes=duration_minutes,
            limit=limit,
            work_start_hour=int(work_start_hour) if work_start_hour else None,
            work_end_hour=int(work_end_hour) if work_end_hour else None,
            skip_weekends=skip_weekends
        )
        
        return {
            'success': True,
            'slots': slots,
            'count': len(slots),
        }
    
    except Exception as e:
        logger.error(f"Failed to find free time for {user_email}: {e}")
        return {'success': False, 'error': 'Failed to find free time slots.'}


@xray_recorder.capture('tool_list_bookable_rooms')
def tool_list_bookable_rooms(params: Dict[str, Any], identity: Dict[str, Any]) -> Dict[str, Any]:
    """List bookable meeting rooms."""
    limit = min(int(params.get('limit', 20)), 100)
    
    try:
        # Query for rooms
        endpoint = f"/places/microsoft.graph.room?$top={limit}"
        if ROOM_FILTER:
            endpoint += f"&$filter=contains(displayName,'{ROOM_FILTER}')"
        
        rooms_data = graph_request(endpoint)
        
        formatted = []
        for room in rooms_data.get('value', []):
            formatted.append({
                'room_email': room.get('emailAddress', ''),
                'room_name': room.get('displayName', ''),
                'capacity': room.get('capacity', 0),
                'building': room.get('building', ''),
                'floor_label': room.get('floorLabel', ''),
            })
        
        return {
            'success': True,
            'rooms': formatted,
            'count': len(formatted),
        }
    
    except Exception as e:
        logger.error(f"Failed to list bookable rooms: {e}")
        return {'success': False, 'error': 'Failed to retrieve bookable rooms.'}


@xray_recorder.capture('tool_request_room_booking')
def tool_request_room_booking(params: Dict[str, Any], identity: Dict[str, Any]) -> Dict[str, Any]:
    """Phase 1: Request a room booking (creates pending operation)."""
    room_email = params.get('room_email', '').strip()
    subject = params.get('subject', '').strip()
    start_time = params.get('start_time', '').strip()
    duration_minutes = int(params.get('duration_minutes', 30))
    
    if not all([room_email, subject, start_time]):
        return {'success': False, 'error': 'room_email, subject, and start_time are required'}
    
    # Rate limit check
    allowed, message = sec.consume_rate_limit(
        actor=identity['actor_aad_id'],
        operation='room_booking_request',
        is_admin=False
    )
    if not allowed:
        return {'success': False, 'error': message}
    
    # Create a "target" dict for the pending operation
    target = {
        'id': room_email,
        'displayName': room_email,
        'userPrincipalName': room_email,
    }
    
    pending = sec.create_pending_operation(
        identity=identity,
        operation_type='room_booking',
        target=target,
        is_admin_override=False,
        justification=None,
    )
    
    # Store booking details in the pending operation
    # (In production, you'd extend the pending operation schema)
    # For now, we'll rely on the agent passing these to execute_room_booking
    
    sec.write_audit(
        actor_aad_id=identity['actor_aad_id'],
        tool_name='request_room_booking',
        operation_type='write',
        parameters={'room_email': room_email, 'subject': subject, 'start_time': start_time},
        result=pending,
        success=True,
        target_user_id=identity['actor_aad_id'],
        confirmation_id=pending['confirmation_id']
    )
    
    return {'success': True, **pending}


@xray_recorder.capture('tool_execute_room_booking')
def tool_execute_room_booking(params: Dict[str, Any], identity: Dict[str, Any]) -> Dict[str, Any]:
    """Phase 2: Execute a room booking for a previously approved operation."""
    confirmation_id = params.get('confirmation_id')
    if not confirmation_id:
        return {'success': False, 'error': 'confirmation_id is required.', 'retryable': False}
    
    try:
        pending = sec.claim_approved_operation(
            confirmation_id=confirmation_id,
            identity=identity,
            expected_operation='room_booking'
        )
    except ValueError as exc:
        return {'success': False, 'error': str(exc), 'retryable': False}
    
    # Rate limit check
    allowed, message = sec.consume_rate_limit(
        actor=identity['actor_aad_id'],
        operation='room_booking',
        is_admin=False
    )
    if not allowed:
        sec.mark_operation_failed(confirmation_id, 'rate_limit')
        return {'success': False, 'error': message}
    
    # Extract booking details from pending operation
    # (In production, you'd store these in the pending operation)
    # For now, we need the agent to pass them again
    room_email = pending.get('target_upn')
    subject = params.get('subject', 'Meeting')
    start_time = params.get('start_time')
    duration_minutes = int(params.get('duration_minutes', 30))
    
    if not start_time:
        return {'success': False, 'error': 'start_time is required for execution'}
    
    user_email = identity.get('user_email')
    if not user_email:
        return {'success': False, 'error': 'User email not available.'}
    
    try:
        # Parse start time and calculate end time
        start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        
        # Create the event
        event_body = {
            'subject': subject,
            'start': {
                'dateTime': start_dt.isoformat(),
                'timeZone': DEFAULT_TIMEZONE
            },
            'end': {
                'dateTime': end_dt.isoformat(),
                'timeZone': DEFAULT_TIMEZONE
            },
            'location': {
                'displayName': room_email
            },
            'attendees': [
                {
                    'emailAddress': {'address': room_email, 'name': room_email},
                    'type': 'resource'
                }
            ]
        }
        
        result = graph_request(f"/users/{user_email}/events", method='POST', body=event_body)
        event_id = result.get('id')
        
        response = {
            'success': True,
            'event_id': event_id,
            'message': f"Room {room_email} booked successfully from {start_time} for {duration_minutes} minutes."
        }
        
        sec.write_audit(
            actor_aad_id=identity['actor_aad_id'],
            tool_name='execute_room_booking',
            operation_type='write',
            parameters={'room_email': room_email, 'subject': subject, 'start_time': start_time},
            result=response,
            success=True,
            target_user_id=identity['actor_aad_id'],
            confirmation_id=confirmation_id
        )
        
        return response
    
    except Exception as e:
        logger.error(f"Failed to book room: {e}")
        sec.refund_rate_limit(actor=identity['actor_aad_id'], operation='room_booking', is_admin=False)
        sec.mark_operation_failed(confirmation_id, str(e))
        return {'success': False, 'error': 'Failed to book the room. Please try again or contact IT.'}


# =============================================================================
# HANDLER
# =============================================================================

_TOOLS = {
    '/list-my-calendar': tool_list_my_calendar,
    '/find-free-time': tool_find_free_time,
    '/list-bookable-rooms': tool_list_bookable_rooms,
    '/request-room-booking': tool_request_room_booking,
    '/execute-room-booking': tool_execute_room_booking,
}

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main entry point for the calendar tools action group.
    
    Routes to the appropriate tool based on apiPath.
    Extracts trusted identity from session attributes (never from parameters).
    Strips any identity fields the model may try to inject.
    """
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
        logger.exception(f"Unhandled error in calendar_tools")
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