"""Authentication dependency for FastAPI.

This module provides JWT authentication as a FastAPI dependency.
It validates JWT tokens and extracts user claims for authorization.
"""

from functools import lru_cache
from typing import Annotated

import structlog
from fastapi import Header, HTTPException

from src.domain.exceptions import AuthenticationError, InvalidTokenError, TokenExpiredError
from src.domain.value_objects.jwt_claims import JWTClaims
from src.infrastructure.auth.jwt_validator import JWTValidator
from src.infrastructure.config.settings import get_settings


log = structlog.get_logger(__name__)

# Constants for token parsing
BEARER_PREFIX = "Bearer "
MAX_TOKEN_SIZE = 8192  # Maximum JWT token size in bytes


@lru_cache(maxsize=1)
def get_jwt_validator() -> JWTValidator:
    """Get singleton JWT validator instance.

    Returns:
        JWTValidator: Cached validator instance
    """
    settings = get_settings()
    return JWTValidator(settings)


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> JWTClaims:
    """Extract and validate JWT from Authorization header.

    This dependency validates the JWT token and returns the parsed claims.
    It should be used as a dependency for protected endpoints.

    Args:
        authorization: Authorization header value (format: "Bearer <token>")

    Returns:
        JWTClaims: Validated JWT claims

    Raises:
        HTTPException: 401 if authentication fails for any reason

    Example:
        @app.get("/v1/uploads")
        async def list_uploads(
            current_user: Annotated[JWTClaims, Depends(get_current_user)]
        ) -> dict:
            workspace_id = current_user.workspace_id
            ...
    """
    # Validate Authorization header exists
    if not authorization:
        log.warning("authentication_failed", reason="missing_header")
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header",
        )

    # Validate Bearer token format
    if not authorization.startswith(BEARER_PREFIX):
        log.warning("authentication_failed", reason="invalid_format")
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
        )

    # Extract token (remove Bearer prefix)
    token = authorization[len(BEARER_PREFIX) :]

    # Validate token size to prevent DoS
    if len(token) > MAX_TOKEN_SIZE:
        log.warning("authentication_failed", reason="token_too_large", size=len(token))
        raise HTTPException(
            status_code=401,
            detail="Token size exceeds maximum allowed",
        )

    # Validate token is not empty after "Bearer "
    if not token.strip():
        log.warning("authentication_failed", reason="empty_token")
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
        )

    try:
        validator = get_jwt_validator()
        claims = await validator.validate(token)

        log.info(
            "authentication_success",
            user_id=str(claims.user_id),
            workspace_id=str(claims.workspace_id),
        )

        return claims

    except TokenExpiredError as e:
        log.warning("authentication_failed", reason="expired_token", error=str(e))
        raise HTTPException(
            status_code=401,
            detail=str(e),
        ) from e

    except (InvalidTokenError, AuthenticationError) as e:
        log.warning("authentication_failed", reason="invalid_token", error=str(e))
        raise HTTPException(
            status_code=401,
            detail=str(e),
        ) from e

    except Exception as e:
        log.error("unexpected_auth_error", error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=401,
            detail="Authentication failed",
        ) from e
