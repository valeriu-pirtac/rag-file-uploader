"""JWT validation for authentication middleware.

This module provides RS256 JWT token validation using PyJWT library.
It extracts and validates JWT claims, converting them to domain objects.
"""

import time
from typing import Any
from uuid import UUID

import jwt
import structlog
from cryptography.hazmat.primitives import serialization

from src.domain.exceptions import InvalidTokenError, TokenExpiredError
from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.workspace_role import WorkspaceRole
from src.infrastructure.config.settings import AppSettings


log = structlog.get_logger(__name__)


class JWTValidator:
    """Validates JWT tokens using RS256 algorithm.

    This validator loads the RSA public key once at initialization and caches it
    for performance. It validates JWT tokens and converts claims to domain objects.

    Attributes:
        _public_key: Cached RSA public key for signature verification
        _algorithm: JWT algorithm (RS256 only)
    """

    def __init__(self, settings: AppSettings) -> None:
        """Initialize JWT validator with public key from settings.

        Args:
            settings: Application settings containing jwt_public_key

        Raises:
            ValueError: If jwt_public_key is empty or invalid
        """
        # Validate public key is not empty
        if not settings.jwt_public_key.strip():
            raise ValueError("jwt_public_key cannot be empty")

        # Load and cache public key at initialization for performance
        self._public_key = serialization.load_pem_public_key(
            settings.jwt_public_key.encode("utf-8")
        )
        self._algorithm = settings.jwt_algorithm

    async def validate(self, token: str) -> JWTClaims:
        """Validate JWT token and extract claims.

        Args:
            token: JWT token string to validate

        Returns:
            JWTClaims: Validated and parsed JWT claims as domain object

        Raises:
            TokenExpiredError: If token has expired
            InvalidTokenError: If token is invalid, malformed, or has invalid claims
        """
        start_time = time.perf_counter()

        try:
            # Decode and validate JWT token
            payload = jwt.decode(
                token,
                self._public_key,  # type: ignore[arg-type]
                algorithms=[self._algorithm],
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "require": ["user_id", "active_workspace_id", "workspace_role", "exp"],
                },
            )

            # Extract and convert claims to domain object
            claims = self._extract_claims(payload)

            # Measure validation duration
            duration_ms = (time.perf_counter() - start_time) * 1000

            if duration_ms > 30:
                log.warning(
                    "slow_jwt_validation",
                    duration_ms=duration_ms,
                    user_id=str(claims.user_id),
                )

            log.info(
                "jwt_validation_success",
                user_id=str(claims.user_id),
                workspace_id=str(claims.workspace_id),
                workspace_role=claims.workspace_role.value,
                duration_ms=duration_ms,
            )

            return claims

        except jwt.ExpiredSignatureError as e:
            log.warning("jwt_validation_failed", reason="expired_token", error=str(e))
            raise TokenExpiredError("JWT token has expired") from e

        except jwt.InvalidTokenError as e:
            log.warning("jwt_validation_failed", reason="invalid_token", error=str(e))
            raise InvalidTokenError(f"Invalid JWT token: {e}") from e

    def _extract_claims(self, payload: dict[str, Any]) -> JWTClaims:
        """Extract and convert JWT payload to domain JWTClaims.

        Args:
            payload: Decoded JWT payload dictionary

        Returns:
            JWTClaims: Domain value object with validated claims

        Raises:
            InvalidTokenError: If required claims missing or invalid format
            ValueError: If JWTClaims validation fails (e.g., owner with shared_file_ids)
        """
        try:
            # Extract and convert UUIDs
            user_id = UUID(payload["user_id"])
            workspace_id = UUID(payload["active_workspace_id"])  # Map from active_workspace_id

            # Convert role string to enum
            role_str = payload["workspace_role"]
            workspace_role = WorkspaceRole(role_str)

            # Handle optional shared_file_ids
            shared_file_ids = None
            if "shared_file_ids" in payload and payload["shared_file_ids"] is not None:
                # Validate shared_file_ids is iterable and contains strings
                file_ids_list = payload["shared_file_ids"]
                if not isinstance(file_ids_list, (list, tuple)):
                    raise TypeError("shared_file_ids must be a list or tuple")
                if not all(isinstance(fid, str) for fid in file_ids_list):
                    raise TypeError("shared_file_ids must contain only strings")
                if len(file_ids_list) > 1000:
                    raise ValueError("shared_file_ids cannot exceed 1000 entries")
                # Convert list[str] → tuple[UUID]
                shared_file_ids = tuple(UUID(fid) for fid in file_ids_list)

            # Extract expiration timestamp
            exp = payload["exp"]

            # Create and validate JWTClaims
            # This will raise ValueError if validation fails (e.g., owner with shared_file_ids)
            return JWTClaims(
                user_id=user_id,
                workspace_id=workspace_id,
                workspace_role=workspace_role,
                shared_file_ids=shared_file_ids,
                exp=exp,
            )

        except (KeyError, ValueError, TypeError) as e:
            raise InvalidTokenError(f"Invalid JWT claims structure: {e}") from e
