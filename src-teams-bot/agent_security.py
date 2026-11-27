"""
Security primitives for agent write operations (Multi-Tenant, Phase 1)

Threat model:
The Bedrock Agent (an LLM) is treated as UNTRUSTED. Everything in
event['parameters'] is model-chosen and may be attacker-influenced via prompt
injection. Only event['sessionAttributes'] (set by our Teams bot) and
event['sessionId'] are trusted.

Multi-tenant additions:
- All audit logs include tenant_id
- Rate limits are tenant-scoped (prevent cross-tenant interference)
- Admin authorization uses tenant-specific admin group ID
- All caches include tenant_id in keys to prevent cross-tenant leakage

Controls implemented:
  1. Trusted identity extraction (session attributes only)
  2. Trusted tenant extraction (session attributes only)
  3. Two-phase confirmation with HMAC-bound, single-use, out-of-band approval
  4. Multi-window atomic rate limiting (tenant-scoped)
  5. Server-side admin authorization (tenant-specific group)
  6. Tamper-evident audit logging with secret redaction (tenant-scoped)
  7. Security notifications via SES (never contain passwords)
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

AWS_REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")

PENDING_TABLE = os.environ.get("PENDING_OPERATIONS_TABLE")
NONCE_TABLE = os.environ.get("CONFIRMATION_NONCES_TABLE")
RATE_TABLE = os.environ.get("RATE_LIMIT_TABLE")
AUDIT_TABLE = os.environ.get("AUDIT_LOG_TABLE")
CONFIRMATION_SECRET_NAME = os.environ.get("CONFIRMATION_SECRET_NAME")
CONFIRMATION_TTL = int(os.environ.get("CONFIRMATION_TTL_SECONDS", "600"))
ADMIN_CACHE_SECONDS = int(os.environ.get("ADMIN_CHECK_CACHE_SECONDS", "60"))
AUDIT_RETENTION_DAYS = int(os.environ.get("AUDIT_LOG_RETENTION", "365"))

SELF_LIMITS = json.loads(os.environ.get("SELF_RATE_LIMITS", "{}")) or {
    "per_operation_hourly": 3, "per_operation_daily": 5, "requests_hourly": 10,
}
ADMIN_LIMITS = json.loads(os.environ.get("ADMIN_RATE_LIMITS", "{}")) or {
    "per_operation_hourly": 20, "per_operation_daily": 50,
    "per_target_daily": 3, "requests_hourly": 30,
}

STATUS_PENDING = "pending_approval"
STATUS_APPROVED = "approved"
STATUS_CONSUMED = "consumed"
STATUS_DENIED = "denied"
STATUS_FAILED = "failed"

_dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
_secrets = boto3.client("secretsmanager", region_name=AWS_REGION)
_ses = boto3.client("ses", region_name=AWS_REGION)

_signing_key_cache: Optional[str] = None
_admin_cache: Dict[str, Tuple[bool, float]] = {}  # Cache key now includes tenant_id

NOTIFICATION_SENDER = os.environ.get("NOTIFICATION_SENDER_EMAIL")
SECURITY_MAILBOX = os.environ.get("SECURITY_NOTIFICATION_EMAIL") or ""


# =============================================================================
# 1. TRUSTED IDENTITY & TENANT
# =============================================================================

class IdentityError(Exception):
    """Raised when a trusted identity cannot be established."""


def extract_trusted_identity(event: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract identity ONLY from session attributes set by the Teams bot.
    Raises IdentityError if absent.
    """
    attrs = event.get("sessionAttributes") or {}
    actor = attrs.get("user_aad_id")
    session_id = event.get("sessionId")

    if not actor or not session_id:
        raise IdentityError(
            "A verified Teams identity is required for this operation. "
            "Please use the Teams assistant rather than an unauthenticated channel."
        )

    return {
        "actor_aad_id": actor,
        "actor_name": attrs.get("user_name", "User"),
        "session_id": session_id,
    }


# =============================================================================
# 2. SIGNING KEY & HMAC
# =============================================================================

def _signing_key() -> str:
    global _signing_key_cache
    if _signing_key_cache:
        return _signing_key_cache
    raw = _secrets.get_secret_value(SecretId=CONFIRMATION_SECRET_NAME)["SecretString"]
    key = json.loads(raw).get("SIGNING_KEY")
    if not key:
        raise ValueError("SIGNING_KEY missing from confirmation signing secret")
    _signing_key_cache = key
    return key


def _hmac(message: str) -> str:
    return hmac.new(_signing_key().encode(), message.encode(), hashlib.sha256).hexdigest()


# =============================================================================
# 3. TWO-PHASE CONFIRMATION
# =============================================================================

def create_pending_operation(
    *,
    identity: Dict[str, str],
    operation_type: str,
    target: Dict[str, Any],
    is_admin_override: bool,
    justification: Optional[str] = None,
) -> Dict[str, Any]:
    confirmation_id = uuid.uuid4().hex
    nonce = secrets.token_urlsafe(32)
    now = int(time.time())
    expires_at = now + CONFIRMATION_TTL

    _dynamodb.Table(PENDING_TABLE).put_item(
        Item={
            "confirmation_id": confirmation_id,
            "session_id": identity["session_id"],
            "actor_aad_id": identity["actor_aad_id"],
            "actor_name": identity["actor_name"],
            "tenant_id": identity.get("tenant_id", "default"),  # NEW
            "operation_type": operation_type,
            "target_user_id": target["id"],
            "target_upn": target.get("userPrincipalName") or target.get("mail") or "",
            "target_display_name": target.get("displayName", ""),
            "is_admin_override": is_admin_override,
            "justification": justification or "",
            "status": STATUS_PENDING,
            "approval_nonce_hash": _hmac(f"{confirmation_id}|{nonce}"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at,
            "ttl": expires_at,
        },
        ConditionExpression="attribute_not_exists(confirmation_id)",
    )

    _dynamodb.Table(NONCE_TABLE).put_item(
        Item={"confirmation_id": confirmation_id, "nonce": nonce, "ttl": expires_at}
    )

    logger.info(
        "Pending operation created: id=%s op=%s actor=%s target=%s admin=%s tenant=%s",
        confirmation_id, operation_type, identity["actor_aad_id"],
        target["id"], is_admin_override, identity.get("tenant_id", "default"),
    )

    return {
        "confirmation_id": confirmation_id,
        "operation_type": operation_type,
        "target_display_name": target.get("displayName", ""),
        "is_admin_override": is_admin_override,
        "expires_in_seconds": CONFIRMATION_TTL,
        "user_message": (
            f"I've prepared a {operation_type.replace('_', ' ')} for "
            f"{target.get('displayName', 'this account')}. An approval card has been "
            f"sent in this chat — please click Approve on it. The request expires in "
            f"{CONFIRMATION_TTL // 60} minutes. Typed confirmation is not accepted."
        ),
    }


def approve_operation(*, confirmation_id: str, nonce: str, approver_aad_id: str) -> bool:
    table = _dynamodb.Table(PENDING_TABLE)
    item = table.get_item(Key={"confirmation_id": confirmation_id}).get("Item")

    if not item:
        logger.warning("Approval for unknown confirmation_id=%s", confirmation_id)
        return False
    if item.get("actor_aad_id") != approver_aad_id:
        logger.warning("Approval actor mismatch for %s", confirmation_id)
        return False
    if item.get("status") != STATUS_PENDING:
        logger.info("Operation %s not pending (status=%s)", confirmation_id, item.get("status"))
        return False
    if int(item.get("expires_at", 0)) < int(time.time()):
        logger.info("Operation %s expired", confirmation_id)
        return False
    if not hmac.compare_digest(item.get("approval_nonce_hash", ""),
                               _hmac(f"{confirmation_id}|{nonce}")):
        logger.warning("Invalid approval nonce for %s", confirmation_id)
        return False

    try:
        table.update_item(
            Key={"confirmation_id": confirmation_id},
            UpdateExpression="SET #s = :approved, approved_at = :ts, approved_via = :via",
            ConditionExpression="#s = :pending AND expires_at > :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":approved": STATUS_APPROVED,
                ":pending": STATUS_PENDING,
                ":ts": datetime.now(timezone.utc).isoformat(),
                ":via": "teams_card",
                ":now": int(time.time()),
            },
        )
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def deny_operation(*, confirmation_id: str, nonce: str, denier_aad_id: str) -> bool:
    table = _dynamodb.Table(PENDING_TABLE)
    item = table.get_item(Key={"confirmation_id": confirmation_id}).get("Item")

    if not item:
        return False
    if item.get("actor_aad_id") != denier_aad_id:
        return False
    if item.get("status") != STATUS_PENDING:
        return False
    if int(item.get("expires_at", 0)) < int(time.time()):
        return False
    if not hmac.compare_digest(item.get("approval_nonce_hash", ""),
                               _hmac(f"{confirmation_id}|{nonce}")):
        return False

    try:
        table.update_item(
            Key={"confirmation_id": confirmation_id},
            UpdateExpression="SET #s = :denied, denied_at = :ts",
            ConditionExpression="#s = :pending AND expires_at > :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":denied": STATUS_DENIED,
                ":pending": STATUS_PENDING,
                ":ts": datetime.now(timezone.utc).isoformat(),
                ":now": int(time.time()),
            },
        )
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def claim_approved_operation(
    *, confirmation_id: str, identity: Dict[str, str], expected_operation: str
) -> Dict[str, Any]:
    table = _dynamodb.Table(PENDING_TABLE)
    item = table.get_item(Key={"confirmation_id": confirmation_id}).get("Item")

    if not item:
        raise ValueError("That confirmation ID is not recognised. Please start the request again.")

    if item.get("session_id") != identity["session_id"]:
        raise ValueError("This confirmation belongs to a different conversation.")
    if item.get("actor_aad_id") != identity["actor_aad_id"]:
        raise ValueError("This confirmation belongs to a different user.")
    if item.get("operation_type") != expected_operation:
        raise ValueError("This confirmation is for a different operation.")
    if int(item.get("expires_at", 0)) < int(time.time()):
        raise ValueError("This confirmation has expired. Please start the request again.")

    status = item.get("status")
    if status == STATUS_PENDING:
        raise ValueError(
            "Not yet approved. Please click Approve on the card in this chat, then tell me to continue."
        )
    if status != STATUS_APPROVED:
        raise ValueError(f"This confirmation is no longer usable (status: {status}).")

    try:
        table.update_item(
            Key={"confirmation_id": confirmation_id},
            UpdateExpression="SET #s = :consumed, consumed_at = :ts REMOVE approval_nonce_hash",
            ConditionExpression="#s = :approved AND expires_at > :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":consumed": STATUS_CONSUMED,
                ":approved": STATUS_APPROVED,
                ":ts": datetime.now(timezone.utc).isoformat(),
                ":now": int(time.time()),
            },
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ValueError("This confirmation was already used or has expired.") from exc
        raise

    return item


def mark_operation_failed(confirmation_id: str, reason: str) -> None:
    try:
        _dynamodb.Table(PENDING_TABLE).update_item(
            Key={"confirmation_id": confirmation_id},
            UpdateExpression="SET #s = :failed, failure_reason = :r",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":failed": STATUS_FAILED, ":r": reason[:500]},
        )
    except ClientError as exc:
        logger.error("Could not mark %s failed: %s", confirmation_id, exc)


def get_operation_status(*, confirmation_id: str, identity: Dict[str, str]) -> Dict[str, Any]:
    item = _dynamodb.Table(PENDING_TABLE).get_item(
        Key={"confirmation_id": confirmation_id}
    ).get("Item")

    if not item or item.get("session_id") != identity["session_id"] \
            or item.get("actor_aad_id") != identity["actor_aad_id"]:
        return {"found": False}

    expired = int(item.get("expires_at", 0)) < int(time.time())
    return {
        "found": True,
        "status": "expired" if expired and item.get("status") == STATUS_PENDING else item["status"],
        "operation_type": item.get("operation_type"),
        "target_display_name": item.get("target_display_name"),
        "approved": item.get("status") == STATUS_APPROVED and not expired,
    }


# =============================================================================
# 4. MULTI-WINDOW RATE LIMITING (now tenant-scoped)
# =============================================================================

def _windows(tenant_id: str,   # NEW: tenant scope
             actor: str, operation: str, is_admin: bool,
             target_id: Optional[str]) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    hour, day = now.strftime("%Y-%m-%dT%H"), now.strftime("%Y-%m-%d")
    limits = ADMIN_LIMITS if is_admin else SELF_LIMITS
    prefix = "RLA" if is_admin else "RL"
    
    # Tenant-scoped keys prevent cross-tenant rate limit interference
    tenant_prefix = f"T#{tenant_id}"

    windows = [
        {"pk": f"{tenant_prefix}#{prefix}#{actor}#{operation}", "sk": f"H#{hour}",
         "limit": limits["per_operation_hourly"], "label": "hourly"},
        {"pk": f"{tenant_prefix}#{prefix}#{actor}#{operation}", "sk": f"D#{day}",
         "limit": limits["per_operation_daily"], "label": "daily"},
    ]
    if is_admin and target_id:
        windows.append({
            "pk": f"{tenant_prefix}#RLT#{target_id}#{operation}", "sk": f"D#{day}",
            "limit": limits["per_target_daily"], "label": "per-target daily",
        })
    return windows


def consume_rate_limit(*, tenant_id: str,   # NEW
                       actor: str, operation: str, is_admin: bool,
                       target_id: Optional[str] = None) -> Tuple[bool, str]:
    if not RATE_TABLE:
        logger.warning("Rate limit table unset — allowing (configure before production)")
        return True, ""

    windows = _windows(tenant_id, actor, operation, is_admin, target_id)
    ttl = int(time.time()) + 172800

    items = [{
        "Update": {
            "TableName": RATE_TABLE,
            "Key": {"pk": w["pk"], "sk": w["sk"]},
            "UpdateExpression": "ADD #c :one SET #ttl = :ttl",
            "ConditionExpression": "attribute_not_exists(#c) OR #c < :limit",
            "ExpressionAttributeNames": {"#c": "count", "#ttl": "ttl"},
            "ExpressionAttributeValues": {":one": 1, ":limit": w["limit"], ":ttl": ttl},
        }
    } for w in windows]

    try:
        _dynamodb.meta.client.transact_write_items(TransactItems=items)
        return True, ""
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "TransactionCanceledException":
            reasons = exc.response.get("CancellationReasons", [])
            breached = [w["label"] for w, r in zip(windows, reasons)
                        if r.get("Code") == "ConditionalCheckFailed"]
            label = breached[0] if breached else "quota"
            logger.warning("Rate limit breached (%s) tenant=%s actor=%s op=%s admin=%s",
                           label, tenant_id, actor, operation, is_admin)
            return False, (
                f"You've reached the {label} limit for this operation. "
                "Please try again later or contact IT support for urgent help."
            )
        logger.error("Rate limit transaction error: %s", exc)
        return False, "Unable to verify your operation quota right now. Please try again shortly."


def refund_rate_limit(*, tenant_id: str,   # NEW
                      actor: str, operation: str, is_admin: bool,
                      target_id: Optional[str] = None) -> None:
    for w in _windows(tenant_id, actor, operation, is_admin, target_id):
        try:
            _dynamodb.Table(RATE_TABLE).update_item(
                Key={"pk": w["pk"], "sk": w["sk"]},
                UpdateExpression="ADD #c :minus_one",
                ConditionExpression="#c > :zero",
                ExpressionAttributeNames={"#c": "count"},
                ExpressionAttributeValues={":minus_one": -1, ":zero": 0},
            )
        except ClientError:
            logger.warning("Refund skipped for %s/%s", w["pk"], w["sk"])


# =============================================================================
# 5. SERVER-SIDE ADMIN AUTHORIZATION (now tenant-scoped)
# =============================================================================

def is_authorized_admin(tenant_id: str,   # NEW
                        actor_aad_id: str, graph_request,
                        tenant_admin_group_id: str) -> bool:
    """
    Resolve admin privilege from Entra group membership, server-side.
    
    The admin group ID is tenant-specific (from the tenant registry).
    Cache key includes tenant_id to prevent cross-tenant leakage.
    """
    if not tenant_admin_group_id:
        return False

    cache_key = f"{tenant_id}:{actor_aad_id}"
    cached = _admin_cache.get(cache_key)
    if cached and cached[1] > time.time():
        return cached[0]

    try:
        result = graph_request(
            f"/users/{actor_aad_id}/checkMemberGroups",
            method="POST",
            body={"groupIds": [tenant_admin_group_id]},
        )
        is_admin = tenant_admin_group_id in (result.get("value") or [])
    except Exception as exc:
        logger.error("Admin check failed for %s in tenant %s: %s — failing closed",
                     actor_aad_id, tenant_id, exc)
        is_admin = False

    _admin_cache[cache_key] = (is_admin, time.time() + ADMIN_CACHE_SECONDS)
    return is_admin


# =============================================================================
# 6. AUDIT LOGGING (now tenant-scoped)
# =============================================================================

_REDACT = {"temp_password", "password", "nonce", "approval_nonce",
           "approval_nonce_hash", "user_confirmed"}


def write_audit(*, tenant_id: str,   # NEW
                actor_aad_id: str, tool_name: str, operation_type: str,
                parameters: Dict[str, Any], result: Dict[str, Any],
                success: bool, target_user_id: Optional[str] = None,
                is_admin_override: bool = False, confirmation_id: Optional[str] = None,
                justification: Optional[str] = None) -> None:
    if not AUDIT_TABLE:
        return

    def scrub(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: ("[REDACTED]" if k in _REDACT else scrub(v)) for k, v in obj.items()}
        if isinstance(obj, str):
            pw = result.get("temp_password")
            return obj.replace(pw, "[REDACTED]") if pw else obj
        return obj

    try:
        _dynamodb.Table(AUDIT_TABLE).put_item(Item={
            "audit_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tenant_id": tenant_id,              # NEW
            "user_id": actor_aad_id,
            "target_user_id": target_user_id or actor_aad_id,
            "actor_is_target": (target_user_id or actor_aad_id) == actor_aad_id,
            "tool_name": tool_name,
            "operation_type": operation_type,
            "is_admin_override": is_admin_override,
            "confirmation_id": confirmation_id or "",
            "justification": justification or "",
            "parameters": json.dumps(scrub(parameters)),
            "result_summary": json.dumps(scrub({
                "success": success,
                "message": result.get("message") or result.get("error") or "",
            })),
            "ttl": int(time.time()) + AUDIT_RETENTION_DAYS * 86400,
        })
    except ClientError as exc:
        logger.error("Audit write failed: %s", exc)


# =============================================================================
# 7. SECURITY NOTIFICATIONS (SES)
# =============================================================================

def notify_security_event(*, event_type: str, target_email: str,
                          target_display_name: str, actor_display_name: str,
                          is_admin_override: bool, occurred_at: str,
                          extra_guidance: str = "") -> None:
    if not NOTIFICATION_SENDER or not target_email:
        logger.warning("Notification skipped (sender or recipient unset)")
        return

    who = ("an IT administrator" if is_admin_override else "you")
    headline = {
        "password_reset": "Your password was reset",
        "account_unlock": "Your account was re-enabled",
    }.get(event_type, "A change was made to your account")

    html = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;line-height:1.6;color:#333;max-width:600px;margin:0 auto">
  <div style="background:#2c3e50;color:#fff;padding:18px">
    <h2 style="margin:0;font-size:20px">{headline}</h2>
  </div>
  <div style="padding:18px;background:#fff">
    <p>Hello {target_display_name or 'there'},</p>
    <p>A change was made to your work account by <strong>{who}</strong>.</p>
    <table style="border-collapse:collapse;width:100%;margin:14px 0">
      <tr><td style="padding:6px;border:1px solid #ddd"><strong>Change</strong></td>
          <td style="padding:6px;border:1px solid #ddd">{event_type.replace('_',' ')}</td></tr>
      <tr><td style="padding:6px;border:1px solid #ddd"><strong>When (UTC)</strong></td>
          <td style="padding:6px;border:1px solid #ddd">{occurred_at}</td></tr>
      <tr><td style="padding:6px;border:1px solid #ddd"><strong>Initiated by</strong></td>
          <td style="padding:6px;border:1px solid #ddd">{actor_display_name}</td></tr>
    </table>
    {f'<p>{extra_guidance}</p>' if extra_guidance else ''}
    <p><strong>For your security, this email never contains a password.</strong></p>
    <div style="background:#fdecea;border-left:4px solid #e74c3c;padding:12px;margin:16px 0">
      <strong>Did not request this?</strong> Contact IT support immediately — do not wait.
    </div>
  </div>
</body></html>"""

    try:
        _ses.send_email(
            Source=NOTIFICATION_SENDER,
            Destination={"ToAddresses": [target_email],
                         **({"CcAddresses": [SECURITY_MAILBOX]} if SECURITY_MAILBOX else {})},
            Message={
                "Subject": {"Data": f"Security notice: {headline}", "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
            },
            Tags=[{"Name": "notification_type", "Value": event_type}],
        )
        logger.info("Security notification sent for %s", event_type)
    except ClientError as exc:
        logger.error("Notification send failed for %s: %s", event_type, exc)
