"""
Bot Framework JWT Validator

Validates JWT tokens from Microsoft Bot Framework using their public keys.
Caches the JWKS (JSON Web Key Set) to avoid fetching on every request.

Security properties:
- Verifies signature using Microsoft's public keys
- Validates issuer (must be https://api.botframework.com)
- Validates audience (must match bot's App ID)
- Validates expiration (token must not be expired)
- Caches JWKS for 24 hours (per OpenID Connect spec)
"""

import json
import time
import logging
from typing import Dict, Any, Optional
import requests
import jwt
from jwt import PyJWKClient, InvalidTokenError

logger = logging.getLogger(__name__)

# Bot Framework OpenID Connect metadata
BOTFRAMEWORK_OPENID_METADATA_URL = "https://login.botframework.com/v1/.well-known/openidconfiguration"

# Expected issuer for Bot Framework tokens
EXPECTED_ISSUER = "https://api.botframework.com"

# Cache for JWKS (refreshed every 24 hours per OpenID Connect spec)
_jwks_cache = {
    'keys': None,
    'fetched_at': 0,
}

# Cache TTL: 24 hours
JWKS_CACHE_TTL = 86400


class JWTValidationError(Exception):
    """Raised when JWT validation fails."""
    pass


def _fetch_jwks() -> Dict[str, Any]:
    """
    Fetch the JWKS from Bot Framework's OpenID Connect endpoint.
    
    Returns the JWKS as a dict with a 'keys' array.
    """
    current_time = time.time()
    
    # Return cached JWKS if still valid
    if _jwks_cache['keys'] and (current_time - _jwks_cache['fetched_at']) < JWKS_CACHE_TTL:
        logger.debug("Using cached JWKS")
        return _jwks_cache['keys']
    
    try:
        # Fetch OpenID Connect metadata
        logger.info("Fetching Bot Framework OpenID Connect metadata")
        metadata_response = requests.get(BOTFRAMEWORK_OPENID_METADATA_URL, timeout=10)
        metadata_response.raise_for_status()
        metadata = metadata_response.json()
        
        # Fetch JWKS from the jwks_uri
        jwks_uri = metadata.get('jwks_uri')
        if not jwks_uri:
            raise JWTValidationError("OpenID metadata missing jwks_uri")
        
        logger.info(f"Fetching JWKS from {jwks_uri}")
        jwks_response = requests.get(jwks_uri, timeout=10)
        jwks_response.raise_for_status()
        jwks = jwks_response.json()
        
        # Cache the JWKS
        _jwks_cache['keys'] = jwks
        _jwks_cache['fetched_at'] = current_time
        
        logger.info(f"Cached JWKS with {len(jwks.get('keys', []))} keys")
        return jwks
    
    except requests.RequestException as e:
        logger.error(f"Failed to fetch JWKS: {e}")
        raise JWTValidationError(f"Failed to fetch JWKS: {e}")


def _get_signing_key(token: str) -> Any:
    """
    Get the signing key for the given JWT.
    
    Extracts the kid (key ID) from the token header and finds the matching
    key in the JWKS.
    """
    try:
        # Decode the header to get the kid
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get('kid')
        
        if not kid:
            raise JWTValidationError("JWT header missing kid (key ID)")
        
        # Fetch JWKS
        jwks = _fetch_jwks()
        
        # Find the matching key
        for key_data in jwks.get('keys', []):
            if key_data.get('kid') == kid:
                # Convert to a PyJWK object
                from jwt.algorithms import RSAAlgorithm
                public_key = RSAAlgorithm.from_jwk(json.dumps(key_data))
                return public_key
        
        raise JWTValidationError(f"No matching key found for kid: {kid}")
    
    except jwt.exceptions.DecodeError as e:
        raise JWTValidationError(f"Failed to decode JWT header: {e}")


def validate_bot_framework_jwt(token: str, bot_app_id: str) -> Dict[str, Any]:
    """
    Validate a Bot Framework JWT token.
    
    Args:
        token: The JWT token string (without "Bearer " prefix)
        bot_app_id: The bot's App ID (expected audience)
    
    Returns:
        The decoded JWT payload (claims)
    
    Raises:
        JWTValidationError: If validation fails
    """
    try:
        # Get the signing key
        signing_key = _get_signing_key(token)
        
        # Decode and validate the token
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=['RS256'],
            audience=bot_app_id,
            issuer=EXPECTED_ISSUER,
            options={
                'verify_aud': True,
                'verify_iss': True,
                'verify_exp': True,
                'verify_signature': True,
            }
        )
        
        logger.info(f"JWT validated successfully for audience: {bot_app_id}")
        return payload
    
    except InvalidTokenError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise JWTValidationError(f"JWT validation failed: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during JWT validation: {e}")
        raise JWTValidationError(f"JWT validation failed: {e}")


def extract_token_from_header(auth_header: str) -> Optional[str]:
    """
    Extract the JWT token from an Authorization header.
    
    Args:
        auth_header: The Authorization header value (e.g., "Bearer <token>")
    
    Returns:
        The token string, or None if the header is malformed
    """
    if not auth_header:
        return None
    
    parts = auth_header.split(' ', 1)
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return None
    
    return parts[1].strip()


def validate_teams_request_with_jwt(event: Dict[str, Any], bot_app_id: str) -> bool:
    """
    Validate a Teams request using Bot Framework JWT validation.
    
    This is the main entry point for request validation.
    
    Args:
        event: The API Gateway event
        bot_app_id: The bot's App ID
    
    Returns:
        True if the request is valid, False otherwise
    """
    try:
        headers = event.get('headers', {})
        auth_header = headers.get('authorization') or headers.get('Authorization', '')
        
        token = extract_token_from_header(auth_header)
        if not token:
            logger.warning("Missing or malformed Authorization header")
            return False
        
        # Validate the JWT
        payload = validate_bot_framework_jwt(token, bot_app_id)
        
        # Additional validation: check serviceurl claim if present
        # (This is optional but recommended for extra security)
        activity = json.loads(event.get('body', '{}'))
        service_url = activity.get('serviceUrl')
        token_service_url = payload.get('serviceurl')
        
        if service_url and token_service_url:
            if service_url.rstrip('/') != token_service_url.rstrip('/'):
                logger.warning(f"Service URL mismatch: activity={service_url}, token={token_service_url}")
                return False
        
        return True
    
    except JWTValidationError as e:
        logger.warning(f"JWT validation failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during request validation: {e}")
        return False
