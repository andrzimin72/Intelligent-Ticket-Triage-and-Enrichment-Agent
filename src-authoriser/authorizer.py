"""
Webhook Authorizer for API Gateway HTTP API

Validates incoming webhook requests using a shared token stored in AWS Secrets Manager.
Uses constant-time comparison to prevent timing attacks.
Fails closed: any error results in authorization denial.

Security features:
- Constant-time token comparison (prevents timing attacks)
- Fail-closed error handling (any error = denial)
- Secret caching (reduces Secrets Manager API calls)
- Case-insensitive header matching (handles API Gateway normalization)
- Optional HMAC signature validation (for enhanced security)
"""

import json
import os
import logging
import hmac
import hashlib
import time
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError

# ==============================================================================
# 1. CONFIGURATION & LOGGING
# ==============================================================================

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
WEBHOOK_SECRET_NAME = os.environ.get("WEBHOOK_SECRET_NAME")
HEADER_NAME = os.environ.get("HEADER_NAME", "x-psa-token").lower()

# Validate required environment variables at import time
if not WEBHOOK_SECRET_NAME:
    logger.error("WEBHOOK_SECRET_NAME environment variable is required")
    raise ValueError("WEBHOOK_SECRET_NAME environment variable is required")

# Initialize Boto3 client
secrets_client = boto3.client("secretsmanager")

# Global cache for secrets to avoid hitting Secrets Manager API limits
# In Lambda, this persists across warm invocations
_secret_cache: Dict[str, str] = {}


# ==============================================================================
# 2. SECRETS MANAGEMENT
# ==============================================================================

def get_expected_token() -> Optional[str]:
    """
    Fetches and caches the expected webhook token from AWS Secrets Manager.
    
    Returns:
        The expected token string, or None if retrieval fails.
    
    Security Note:
        We cache the token in memory to avoid hitting Secrets Manager rate limits.
        The cache persists across Lambda warm invocations, reducing latency and cost.
        If the secret is rotated, the Lambda must be redeployed or the cache manually cleared.
    """
    if WEBHOOK_SECRET_NAME in _secret_cache:
        return _secret_cache[WEBHOOK_SECRET_NAME]
    
    try:
        logger.info(f"Fetching secret from Secrets Manager: {WEBHOOK_SECRET_NAME}")
        response = secrets_client.get_secret_value(SecretId=WEBHOOK_SECRET_NAME)
        secret_data = json.loads(response["SecretString"])
        token = secret_data.get("TOKEN")
        
        if not token:
            logger.error(f"Secret {WEBHOOK_SECRET_NAME} does not contain a 'TOKEN' field")
            return None
        
        _secret_cache[WEBHOOK_SECRET_NAME] = token
        logger.info("Successfully cached webhook token")
        return token
    
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        logger.error(f"Failed to retrieve secret {WEBHOOK_SECRET_NAME}: {error_code} - {e}")
        return None
    
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to parse secret {WEBHOOK_SECRET_NAME}: {e}")
        return None
    
    except Exception as e:
        logger.exception(f"Unexpected error retrieving secret {WEBHOOK_SECRET_NAME}: {e}")
        return None


def clear_secret_cache():
    """
    Manually clears the secret cache.
    
    Useful for:
    - Testing
    - Forcing a secret refresh after rotation
    - Debugging authentication issues
    
    Note: In production, this should only be called by administrative functions,
    not by the authorizer itself.
    """
    _secret_cache.clear()
    logger.info("Secret cache cleared")


# ==============================================================================
# 3. AUTHENTICATION LOGIC
# ==============================================================================

def extract_token_from_event(event: Dict[str, Any]) -> Optional[str]:
    """
    Extracts the authentication token from the API Gateway event.
    
    Args:
        event: The API Gateway event dictionary
    
    Returns:
        The token string, or None if not present or empty.
    
    Note:
        Header names are case-insensitive in HTTP, but API Gateway normalizes them.
        We convert to lowercase for consistency.
    """
    headers = event.get("headers") or {}
    
    # API Gateway may provide headers in various cases
    # Try exact match first, then case-insensitive search
    token = headers.get(HEADER_NAME)
    
    if token is None:
        # Case-insensitive fallback
        for key, value in headers.items():
            if key.lower() == HEADER_NAME:
                token = value
                break
    
    if not token or not isinstance(token, str):
        logger.warning(f"Missing or empty token in header: {HEADER_NAME}")
        return None
    
    return token.strip()


def validate_token(supplied_token: str, expected_token: str) -> bool:
    """
    Validates the supplied token against the expected token using constant-time comparison.
    
    Args:
        supplied_token: The token from the incoming request
        expected_token: The token from Secrets Manager
    
    Returns:
        True if tokens match, False otherwise.
    
    Security Note:
        We use hmac.compare_digest() instead of == to prevent timing attacks.
        A naive string comparison can leak information about how many characters match
        based on the time it takes to return False.
    """
    if not supplied_token or not expected_token:
        return False
    
    try:
        # hmac.compare_digest is constant-time and safe for secret comparison
        return hmac.compare_digest(supplied_token, expected_token)
    except Exception as e:
        logger.error(f"Error during token comparison: {e}")
        return False


# ==============================================================================
# 4. HMAC SIGNATURE VALIDATION (OPTIONAL ENHANCEMENT)
# ==============================================================================

def validate_hmac_signature(event: Dict[str, Any], secret_key: str) -> bool:
    """
    Validates an HMAC signature instead of a simple token.
    
    This is more secure than a shared token because:
    - The signature is unique per request (includes timestamp and body hash)
    - Replay attacks are prevented via timestamp validation
    - The secret key is never transmitted
    
    To use this instead of token validation:
    1. Update the PSA webhook configuration to send:
       - X-Signature: <hmac-sha256-signature>
       - X-Timestamp: <unix-timestamp>
    2. The signature should be: HMAC-SHA256(secret_key, timestamp + "." + body_hash)
    3. Replace the call to validate_token() with validate_hmac_signature()
    
    Args:
        event: The API Gateway event
        secret_key: The HMAC secret key from Secrets Manager
    
    Returns:
        True if signature is valid, False otherwise.
    
    Note:
        This is provided as a future enhancement. The current implementation uses
        simple token validation, which is sufficient for most MSP use cases.
    """
    headers = event.get("headers") or {}
    signature = headers.get("x-signature")
    timestamp = headers.get("x-timestamp")
    
    if not signature or not timestamp:
        logger.warning("Missing signature or timestamp headers")
        return False
    
    # Validate timestamp is within 5 minutes (prevent replay attacks)
    try:
        request_time = int(timestamp)
        current_time = int(time.time())
        if abs(current_time - request_time) > 300:  # 5 minutes
            logger.warning(f"Timestamp too old or too far in future: {timestamp}")
            return False
    except ValueError:
        logger.warning(f"Invalid timestamp format: {timestamp}")
        return False
    
    # Compute expected signature
    body = event.get("body", "")
    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    message = f"{timestamp}.{body_hash}"
    
    expected_signature = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_signature)


# ==============================================================================
# 5. AUTHORIZER HANDLER
# ==============================================================================

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, bool]:
    """
    Main entry point for the API Gateway authorizer.
    
    Args:
        event: The API Gateway event dictionary containing headers
        context: The Lambda context object (unused)
    
    Returns:
        A dictionary with 'isAuthorized' key (True/False).
        API Gateway expects this exact format for simple responses.
    
    Security Posture:
        - Fail closed: Any error results in authorization denial
        - No information leakage: Error messages are logged but not returned to client
        - Constant-time comparison: Prevents timing attacks
        - Secret caching: Reduces Secrets Manager API calls and latency
    
    Example Response:
        {"isAuthorized": true}
        {"isAuthorized": false}
    """
    request_id = getattr(context, "aws_request_id", "unknown")
    logger.info(f"Authorizer invoked. RequestId: {request_id}")
    
    try:
        # Step 1: Extract the token from the request
        supplied_token = extract_token_from_event(event)
        
        if not supplied_token:
            logger.warning(f"Authorization denied: Missing token. RequestId: {request_id}")
            return {"isAuthorized": False}
        
        # Step 2: Get the expected token from Secrets Manager
        expected_token = get_expected_token()
        
        if not expected_token:
            # Fail closed: if we can't retrieve the secret, deny access
            logger.error(f"Authorization denied: Unable to retrieve expected token. RequestId: {request_id}")
            return {"isAuthorized": False}
        
        # Step 3: Validate the token
        is_valid = validate_token(supplied_token, expected_token)
        
        if is_valid:
            logger.info(f"Authorization granted. RequestId: {request_id}")
        else:
            logger.warning(f"Authorization denied: Invalid token. RequestId: {request_id}")
        
        return {"isAuthorized": is_valid}
    
    except Exception as e:
        # Catch-all: fail closed on any unexpected error
        logger.exception(f"Authorization denied: Unexpected error. RequestId: {request_id}")
        return {"isAuthorized": False}
