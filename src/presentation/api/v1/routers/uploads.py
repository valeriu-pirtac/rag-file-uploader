"""Uploads router for chunked file upload endpoints.

This module defines FastAPI endpoints for initiating, processing, querying,
and aborting chunked file upload sessions. Endpoints enforce authentication
and authorization via JWT validation and RBAC middleware.

Architecture:
    - Presentation Layer: Maps HTTP requests to use case DTOs
    - Clean Architecture: Depends on application layer, not infrastructure
    - Authentication: JWT validation via get_current_user dependency
    - Authorization: RBAC enforcement via require_role dependency
    - Error Handling: Converts domain exceptions to HTTP status codes

Endpoints:
    - POST /v1/uploads: Initiate new upload session (OWNER only)
    - PATCH /v1/uploads/{id}: Upload chunk (OWNER only) [Future Story 3.8]
    - HEAD /v1/uploads/{id}: Query upload offset (OWNER + COLLABORATOR) [Future Story 3.9]
    - DELETE /v1/uploads/{id}: Abort upload session (OWNER only) [Future Story 3.10]
    - GET /v1/uploads: List upload sessions (OWNER + COLLABORATOR) [Future Story 7.1]

Integration Points:
    - Story 3.4: Calls InitiateUploadUseCase for session creation
    - Story 2.2: Uses JWT authentication (get_current_user)
    - Story 2.4: Uses RBAC authorization (require_role)
    - Story 3.1: Works with UploadSession domain entities
    - Story 3.2: Session persistence via ISessionStore
    - Story 3.3: Rate limiting via IRateLimiter

Error Response Structure:
    {
        "error": "ERROR_CODE",           # Uppercase snake case
        "message": "Human-readable...",  # User-friendly message
        "details": {                     # Error-specific context
            "field": "value"
        }
    }

Examples:
    >>> # Success case - POST /v1/uploads
    >>> response = client.post(
    ...     "/v1/uploads",
    ...     json={
    ...         "filename": "document.pdf",
    ...         "size": 1048576,
    ...         "mimeType": "application/pdf",
    ...         "sha256Checksum": "a" * 64
    ...     },
    ...     headers={"Authorization": "Bearer valid-token"}
    ... )
    >>> print(response.status_code)  # 201
    >>> print("uploadId" in response.json())  # True
    >>>
    >>> # Rate limit exceeded - 429 Too Many Requests
    >>> response = client.post("/v1/uploads", ...)
    >>> print(response.status_code)  # 429
    >>> print(response.json()["details"]["current_uploads"])  # 10
"""

from functools import lru_cache
from typing import Annotated

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from structlog.contextvars import bind_contextvars, clear_contextvars

from src.application.dto.upload_request import InitiateUploadRequest as InitiateUploadRequestDTO
from src.application.dto.upload_response import InitiateUploadResponse as InitiateUploadResponseDTO
from src.application.services.rate_limiter import RedisRateLimiter
from src.application.use_cases.initiate_upload import InitiateUploadUseCase
from src.domain.exceptions import (
    FileSizeLimitExceededError,
    InfrastructureError,
    RateLimitExceededError,
    UnsupportedMediaTypeError,
)
from src.domain.protocols.rate_limiter import IRateLimiter
from src.domain.protocols.session_store import ISessionStore
from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.workspace_role import WorkspaceRole
from src.infrastructure.auth.rbac_middleware import require_role
from src.infrastructure.config.settings import get_settings
from src.infrastructure.redis.session_store import RedisSessionStore
from src.presentation.api.v1.schemas.upload_schemas import (
    InitiateUploadRequest,
    InitiateUploadResponse,
)


log = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["uploads"])


# Dependency Injection Providers


@lru_cache(maxsize=1)
def get_redis_client() -> aioredis.Redis:
    """Get singleton Redis client instance.

    Creates and caches Redis client connection. The client manages connection
    pooling and async operations internally.

    Returns:
        aioredis.Redis: Cached Redis client instance

    Examples:
        >>> redis_client = get_redis_client()
        >>> await redis_client.ping()  # Test connection
        True
    """
    settings = get_settings()
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def get_session_store(
    redis_client: Annotated[aioredis.Redis, Depends(get_redis_client)],
) -> ISessionStore:
    """Provide ISessionStore implementation with Redis backend.

    Creates RedisSessionStore with injected Redis client. This function
    is called per-request by FastAPI's dependency injection system.

    Args:
        redis_client: Injected Redis client from get_redis_client

    Returns:
        ISessionStore: Session store protocol implementation

    Examples:
        >>> # Used as FastAPI dependency
        >>> @router.post("/uploads")
        >>> async def create_upload(
        ...     session_store: Annotated[ISessionStore, Depends(get_session_store)],
        ... ):
        ...     await session_store.create_session(session)
    """
    return RedisSessionStore(redis_client)


def get_rate_limiter(
    redis_client: Annotated[aioredis.Redis, Depends(get_redis_client)],
) -> IRateLimiter:
    """Provide IRateLimiter implementation with Redis backend.

    Creates RedisRateLimiter with injected Redis client and settings.
    This function is called per-request by FastAPI's dependency injection.

    Args:
        redis_client: Injected Redis client from get_redis_client

    Returns:
        IRateLimiter: Rate limiter protocol implementation

    Examples:
        >>> # Used as FastAPI dependency
        >>> @router.post("/uploads")
        >>> async def create_upload(
        ...     rate_limiter: Annotated[IRateLimiter, Depends(get_rate_limiter)],
        ... ):
        ...     await rate_limiter.check_and_increment(workspace_id)
    """
    settings = get_settings()
    return RedisRateLimiter(redis_client, settings)


def get_initiate_upload_use_case(
    session_store: Annotated[ISessionStore, Depends(get_session_store)],
    rate_limiter: Annotated[IRateLimiter, Depends(get_rate_limiter)],
) -> InitiateUploadUseCase:
    """Provide InitiateUploadUseCase with injected dependencies.

    Creates use case with protocol dependencies (session store, rate limiter).
    This enables Clean Architecture - use case depends on protocols, not
    concrete implementations.

    Args:
        session_store: Injected session store protocol implementation
        rate_limiter: Injected rate limiter protocol implementation

    Returns:
        InitiateUploadUseCase: Use case for creating upload sessions

    Examples:
        >>> # Used as FastAPI dependency
        >>> @router.post("/uploads")
        >>> async def create_upload(
        ...     use_case: Annotated[InitiateUploadUseCase, Depends(get_initiate_upload_use_case)],
        ... ):
        ...     response = await use_case.execute(request)
    """
    return InitiateUploadUseCase(
        rate_limiter=rate_limiter,
        session_store=session_store,
    )


# API Endpoints


@router.post(
    "/uploads",
    status_code=status.HTTP_201_CREATED,
    response_model=InitiateUploadResponse,
    summary="Initiate chunked upload session",
    description=(
        "Creates a new upload session for workspace owner. "
        "Returns session ID, upload offset (0), and expiry timestamp. "
        "Requires OWNER role. Subject to per-workspace rate limiting."
    ),
    responses={
        201: {
            "description": "Upload session created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "uploadId": "550e8400-e29b-41d4-a716-446655440000",
                        "offset": 0,
                        "expiresAt": "2026-05-06T12:00:00.123456Z",
                    }
                }
            },
        },
        401: {
            "description": "Authentication failed (missing/invalid/expired JWT)",
            "content": {"application/json": {"example": {"detail": "Authentication failed"}}},
        },
        403: {
            "description": "Authorization failed (OWNER role required)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {"detail": "Insufficient permissions - owner role required"}
                    }
                }
            },
        },
        413: {
            "description": "Payload too large (file size > 1 GB)",
            "content": {
                "application/json": {
                    "example": {
                        "error": "FILE_SIZE_LIMIT_EXCEEDED",
                        "message": "File size 1073741825 bytes exceeds maximum allowed size of 1073741824 bytes",
                        "details": {
                            "file_size": 1073741825,
                            "max_size": 1073741824,
                        },
                    }
                }
            },
        },
        415: {
            "description": "Unsupported media type (MIME type not allowed)",
            "content": {
                "application/json": {
                    "example": {
                        "error": "UNSUPPORTED_MEDIA_TYPE",
                        "message": "MIME type 'application/msword' is not supported. Allowed types: application/pdf",
                        "details": {
                            "provided_mime_type": "application/msword",
                            "allowed_mime_types": ["application/pdf"],
                        },
                    }
                }
            },
        },
        422: {
            "description": "Validation error (invalid request body)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
                            {
                                "type": "string_pattern_mismatch",
                                "loc": ["body", "sha256Checksum"],
                                "msg": "String should match pattern '^[a-f0-9]{64}$'",
                                "input": "INVALID",
                            }
                        ]
                    }
                }
            },
        },
        429: {
            "description": "Rate limit exceeded (too many concurrent uploads)",
            "content": {
                "application/json": {
                    "example": {
                        "error": "RATE_LIMIT_EXCEEDED",
                        "message": "Workspace has 10 active uploads (limit: 10). Retry after 60 seconds.",
                        "details": {
                            "current_uploads": 10,
                            "limit": 10,
                            "retry_after_seconds": 60,
                        },
                    }
                }
            },
        },
        503: {
            "description": "Service unavailable (infrastructure failure)",
            "content": {
                "application/json": {
                    "example": {
                        "error": "INFRASTRUCTURE_ERROR",
                        "message": "Storage system temporarily unavailable. Please retry.",
                        "details": {"retry_guidance": "Retry after a few seconds"},
                    }
                }
            },
        },
    },
)
async def initiate_upload(
    request: InitiateUploadRequest,
    current_user: Annotated[JWTClaims, Depends(require_role(WorkspaceRole.OWNER))],
    use_case: Annotated[InitiateUploadUseCase, Depends(get_initiate_upload_use_case)],
) -> InitiateUploadResponse:
    """Initiate new chunked upload session.

    Creates a new upload session for the authenticated workspace owner.
    The session is valid for 24 hours and allows resumable chunked uploads.
    Rate limiting is enforced per-workspace (max 10 concurrent uploads).

    Authentication & Authorization:
        - Requires valid JWT in Authorization header (Bearer token)
        - Requires OWNER role (403 Forbidden for COLLABORATOR)
        - workspace_id extracted from JWT claims

    Request Validation:
        - filename: 1-255 characters, no path separators
        - size: 1 byte to 1 GB (1073741824 bytes)
        - mimeType: Must be "application/pdf"
        - sha256Checksum: 64 lowercase hexadecimal characters

    Rate Limiting:
        - Maximum 10 concurrent active uploads per workspace
        - 429 response includes current count and retry_after_seconds
        - Counter decremented when upload completes/aborts

    Response Fields:
        - uploadId: UUID v4 session identifier (use in PATCH/HEAD/DELETE)
        - offset: Current verified offset (always 0 for new sessions)
        - expiresAt: Session expiry timestamp (24 hours, ISO 8601 UTC)

    Error Handling:
        - 401: Authentication failed (missing/invalid/expired JWT)
        - 403: Authorization failed (COLLABORATOR role)
        - 413: File size > 1 GB
        - 415: MIME type not "application/pdf"
        - 422: Pydantic validation error (invalid request body)
        - 429: Rate limit exceeded (max concurrent uploads reached)
        - 503: Infrastructure failure (Redis connection error)

    Args:
        request: Pydantic request schema with filename, size, mime_type, sha256_checksum
        current_user: JWT claims from authentication (contains workspace_id)
        use_case: Injected InitiateUploadUseCase with dependencies

    Returns:
        InitiateUploadResponse: Pydantic response schema with upload_id, offset, expires_at

    Raises:
        HTTPException: 401/403/413/415/429/503 with structured error details

    Examples:
        >>> # Success case
        >>> POST /v1/uploads
        >>> Authorization: Bearer <token>
        >>> {
        ...     "filename": "document.pdf",
        ...     "size": 1048576,
        ...     "mimeType": "application/pdf",
        ...     "sha256Checksum": "a" * 64
        ... }
        >>>
        >>> # Response 201 Created
        >>> {
        ...     "uploadId": "550e8400-e29b-41d4-a716-446655440000",
        ...     "offset": 0,
        ...     "expiresAt": "2026-05-06T12:00:00.123456Z"
        ... }
    """
    # Bind user context for structured logging (applies to all log calls in this request)
    bind_contextvars(
        user_id=str(current_user.user_id),
        workspace_id=str(current_user.workspace_id),
    )

    # Log incoming request (structured logging with sanitized filename)
    # Sanitize filename to avoid logging PII - show only extension and size
    filename_parts = request.filename.rsplit(".", 1)
    sanitized_filename = (
        f"<redacted>.{filename_parts[-1]}" if len(filename_parts) > 1 else "<redacted>"
    )

    log.info(
        "initiate_upload_request",
        filename_sanitized=sanitized_filename,
        size=request.size,
        mime_type=request.mime_type,
    )

    # Map Pydantic schema to application DTO
    # Inject workspace_id from JWT claims (AC: #6)
    dto_request = InitiateUploadRequestDTO(
        workspace_id=current_user.workspace_id,
        filename=request.filename,
        size=request.size,
        mime_type=request.mime_type,
        sha256_checksum=request.sha256_checksum,
    )

    # Execute use case with error handling
    try:
        dto_response: InitiateUploadResponseDTO = await use_case.execute(dto_request)

        # Map DTO response to Pydantic schema
        response = InitiateUploadResponse(
            upload_id=dto_response.session_id,
            offset=dto_response.offset,
            expires_at=dto_response.expires_at,
        )

        log.info(
            "initiate_upload_success",
            session_id=str(dto_response.session_id),
            expires_at=dto_response.expires_at.isoformat(),
        )

        # Clear context vars after successful completion
        clear_contextvars()
        return response

    except RateLimitExceededError as e:
        # AC: #7 - 429 response includes current active upload count
        log.warning(
            "initiate_upload_rate_limit_exceeded",
            current_count=e.current_count,
            limit=e.limit,
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "RATE_LIMIT_EXCEEDED",
                "message": str(e),
                "details": {
                    "current_uploads": e.current_count,
                    "limit": e.limit,
                    "retry_after_seconds": e.retry_after_seconds,
                },
            },
            headers={"Retry-After": str(e.retry_after_seconds)},
        ) from e

    except FileSizeLimitExceededError as e:
        # 413 Payload Too Large - file size > 1 GB
        log.warning(
            "initiate_upload_file_size_exceeded",
            file_size=e.file_size,
            max_size=e.max_size,
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "error": "FILE_SIZE_LIMIT_EXCEEDED",
                "message": str(e),
                "details": {
                    "file_size": e.file_size,
                    "max_size": e.max_size,
                },
            },
        ) from e

    except UnsupportedMediaTypeError as e:
        # 415 Unsupported Media Type - MIME type not allowed
        log.warning(
            "initiate_upload_unsupported_media_type",
            provided_mime_type=e.provided_mime_type,
            allowed_mime_types=e.allowed_mime_types,
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "error": "UNSUPPORTED_MEDIA_TYPE",
                "message": str(e),
                "details": {
                    "provided_mime_type": e.provided_mime_type,
                    "allowed_mime_types": e.allowed_mime_types,
                },
            },
        ) from e

    except InfrastructureError as e:
        # 503 Service Unavailable - Redis/storage failure
        log.error(
            "initiate_upload_infrastructure_error",
            error=str(e),
            error_type=type(e).__name__,
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "INFRASTRUCTURE_ERROR",
                "message": "Storage system temporarily unavailable. Please retry.",
                "details": {
                    "retry_guidance": "Retry after a few seconds",
                },
            },
        ) from e

    except ValueError as e:
        # 422 Unprocessable Entity - validation error from DTO
        log.warning(
            "initiate_upload_validation_error",
            error=str(e),
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "VALIDATION_ERROR",
                "message": str(e),
                "details": {},
            },
        ) from e

    except Exception as e:
        # Catch-all for unexpected errors
        log.error(
            "initiate_upload_unexpected_error",
            error=str(e),
            error_type=type(e).__name__,
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred. Please retry or contact support.",
                "details": {},
            },
        ) from e
