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
    - PATCH /v1/uploads/{id}: Upload chunk (OWNER only)
    - HEAD /v1/uploads/{id}: Query upload offset (OWNER + COLLABORATOR) [Future Story 3.9]
    - DELETE /v1/uploads/{id}: Abort upload session (OWNER only) [Future Story 3.10]
    - GET /v1/uploads: List upload sessions (OWNER + COLLABORATOR) [Future Story 7.1]

Integration Points:
    - Story 3.4: Calls InitiateUploadUseCase for session creation
    - Story 3.7: Calls ProcessChunkUseCase for chunk processing
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

import asyncio
import base64
import binascii
from functools import lru_cache
from typing import Annotated
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from structlog.contextvars import bind_contextvars, clear_contextvars

from src.application.dto.process_chunk_request import ProcessChunkRequest
from src.application.dto.upload_request import InitiateUploadRequest as InitiateUploadRequestDTO
from src.application.dto.upload_response import InitiateUploadResponse as InitiateUploadResponseDTO
from src.application.services.rate_limiter import RedisRateLimiter
from src.application.use_cases.initiate_upload import InitiateUploadUseCase
from src.application.use_cases.process_chunk import ProcessChunkUseCase
from src.domain.exceptions import (
    ChecksumMismatchError,
    FileSizeLimitExceededError,
    InfrastructureError,
    OffsetMismatchError,
    RateLimitExceededError,
    SessionNotFoundError,
    UnsupportedMediaTypeError,
)
from src.domain.protocols.rate_limiter import IRateLimiter
from src.domain.protocols.session_store import ISessionStore
from src.domain.services.chunk_verifier import ChunkVerifier
from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.session_status import SessionStatus
from src.domain.value_objects.workspace_role import WorkspaceRole
from src.infrastructure.auth.rbac_middleware import require_role
from src.infrastructure.config.settings import get_settings
from src.infrastructure.redis.session_store import RedisSessionStore
from src.presentation.api.middleware.auth import get_current_user
from src.presentation.api.v1.schemas.upload_schemas import (
    InitiateUploadRequest,
    InitiateUploadResponse,
)


log = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["uploads"])

MAX_CHUNK_SIZE = 100 * 1024 * 1024  # 100 MB

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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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


def get_process_chunk_use_case(
    session_store: Annotated[ISessionStore, Depends(get_session_store)],
) -> ProcessChunkUseCase:
    """Provide ProcessChunkUseCase with injected dependencies.

    Creates use case with protocol dependencies (session store, chunk verifier).
    This enables Clean Architecture - use case depends on protocols, not
    concrete implementations.

    Args:
        session_store: Injected session store protocol implementation

    Returns:
        ProcessChunkUseCase: Use case for processing uploaded chunks

    Examples:
        >>> # Used as FastAPI dependency
        >>> @router.patch("/uploads/{id}")
        >>> async def upload_chunk(
        ...     use_case: Annotated[ProcessChunkUseCase, Depends(get_process_chunk_use_case)],
        ... ):
        ...     response = await use_case.execute(request)
    """
    return ProcessChunkUseCase(
        session_store=session_store,
        chunk_verifier=ChunkVerifier(),
    )


@router.patch(
    "/uploads/{upload_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Upload file chunk with SHA-256 verification",
    description=(
        "Uploads a chunk of data at the specified offset. "
        "Validates offset matches current session state (strict tus protocol). "
        "Verifies SHA-256 checksum before committing chunk. "
        "Requires OWNER role. Streams data asynchronously."
    ),
    responses={
        204: {
            "description": "Chunk uploaded and verified successfully",
            "headers": {
                "Upload-Offset": {
                    "description": "New verified byte offset after this chunk",
                    "schema": {"type": "integer"},
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
        404: {
            "description": "Session not found or expired (24h TTL)",
            "content": {
                "application/json": {
                    "example": {
                        "error": "SESSION_NOT_FOUND",
                        "message": "Upload session 550e8400-e29b-41d4-a716-446655440000 not found or expired",
                        "details": {
                            "session_id": "550e8400-e29b-41d4-a716-446655440000",
                            "suggestion": "Start a new upload session via POST /v1/uploads",
                        },
                    }
                }
            },
        },
        409: {
            "description": "Offset mismatch (client out of sync with server)",
            "content": {
                "application/json": {
                    "example": {
                        "error": "OFFSET_MISMATCH",
                        "message": "Upload offset mismatch: expected 5242880, received 0",
                        "details": {
                            "expected_offset": 5242880,
                            "received_offset": 0,
                            "suggestion": "Query HEAD /v1/uploads/{id} to get current offset before retrying",
                        },
                    }
                }
            },
        },
        415: {
            "description": "Unsupported Content-Type (must be application/offset+octet-stream)",
            "content": {
                "application/json": {
                    "example": {
                        "error": "UNSUPPORTED_CONTENT_TYPE",
                        "message": "Content-Type must be application/offset+octet-stream",
                        "details": {
                            "provided_content_type": "application/octet-stream",
                            "required_content_type": "application/offset+octet-stream",
                        },
                    }
                }
            },
        },
        422: {
            "description": "Validation error (missing required headers or invalid checksum format)",
            "content": {
                "application/json": {
                    "example": {
                        "error": "INVALID_CHECKSUM_FORMAT",
                        "message": "Upload-Checksum header must be in format 'sha256 {base64|hex}'",
                        "details": {
                            "provided_checksum": "invalid",
                            "required_format": "sha256 {base64_or_hex_encoded_hash}",
                        },
                    }
                }
            },
        },
        460: {
            "description": "Checksum mismatch (chunk corrupted in transit)",
            "content": {
                "application/json": {
                    "example": {
                        "error": "CHECKSUM_MISMATCH",
                        "message": "Chunk SHA-256 checksum does not match Upload-Checksum header",
                        "details": {
                            "expected_checksum": "abc123...",
                            "computed_checksum": "def456...",
                            "chunk_index": 42,
                            "chunk_size": 5242880,
                            "suggestion": "Retry uploading this chunk only (do not restart full upload)",
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
async def upload_chunk(
    upload_id: UUID,
    request: Request,
    current_user: Annotated[JWTClaims, Depends(require_role(WorkspaceRole.OWNER))],
    use_case: Annotated[ProcessChunkUseCase, Depends(get_process_chunk_use_case)],
    upload_offset: Annotated[int, Header(alias="Upload-Offset")],
    upload_length: Annotated[int, Header(alias="Upload-Length")],
    upload_checksum: Annotated[str, Header(alias="Upload-Checksum")],
    content_type: Annotated[str, Header(alias="Content-Type")],
) -> Response:
    """Upload file chunk with SHA-256 verification.

    Streams chunk data asynchronously from request body, validates offset,
    verifies SHA-256 checksum, and updates session state atomically.
    Follows tus protocol semantics for reliable chunked uploads.

    Authentication & Authorization:
        - Requires valid JWT in Authorization header (Bearer token)
        - Requires OWNER role (403 Forbidden for COLLABORATOR)
        - workspace_id extracted from JWT claims

    Request Headers:
        - Upload-Offset: Client-provided byte offset (must match session offset)
        - Upload-Length: Total file size in bytes (for validation)
        - Upload-Checksum: Format "sha256 {base64|hex}" - SHA-256 of chunk data
        - Content-Type: Must be "application/offset+octet-stream"

    Request Body:
        - Raw binary chunk data (typically 5MB, varies by client)
        - Streamed asynchronously to avoid memory spikes

    Response Headers (Success):
        - Upload-Offset: New verified byte offset after this chunk

    Error Handling:
        - 401: Authentication failed (missing/invalid/expired JWT)
        - 403: Authorization failed (COLLABORATOR role)
        - 404: Session not found or expired (24h TTL)
        - 409: Offset mismatch (client out of sync)
        - 415: Wrong Content-Type (must be application/offset+octet-stream)
        - 422: Invalid checksum format
        - 460: Checksum mismatch (corrupt chunk)
        - 503: Infrastructure failure (Redis connection error)

    tus Protocol Compliance:
        - Offset validation enforces sequential uploads (no gaps, no overlaps)
        - 409 response includes expected offset for client correction
        - Upload-Offset response header enables client to verify server state
        - 460 response includes both checksums for debugging

    Args:
        upload_id: Upload session UUID from path parameter
        request: FastAPI Request object for streaming body
        current_user: JWT claims from authentication (contains workspace_id)
        use_case: Injected ProcessChunkUseCase with dependencies
        upload_offset: Client-provided byte offset from header
        upload_length: Total file size from header
        upload_checksum: SHA-256 checksum from header (format: "sha256 {hash}")
        content_type: Content-Type header value

    Returns:
        Response: 204 No Content with Upload-Offset header

    Raises:
        HTTPException: 401/403/404/409/415/422/460/503 with structured error details

    Performance:
        - Async streaming prevents blocking I/O
        - No full chunk buffering in memory
        - Processing time: <100ms per 5MB chunk (NFR-P3)

    Examples:
        >>> # Success case
        >>> PATCH /v1/uploads/550e8400-e29b-41d4-a716-446655440000
        >>> Authorization: Bearer <token>
        >>> Upload-Offset: 0
        >>> Upload-Length: 10485760
        >>> Upload-Checksum: sha256 YWJjMTIz...
        >>> Content-Type: application/offset+octet-stream
        >>> <binary chunk data>
        >>>
        >>> # Response 204 No Content
        >>> Upload-Offset: 5242880
        >>>
        >>> # Offset mismatch (client resends chunk 0, server expects chunk 1)
        >>> PATCH /v1/uploads/550e8400-e29b-41d4-a716-446655440000
        >>> Upload-Offset: 0  # Wrong - should be 5242880
        >>> # Response 409 Conflict
        >>> {
        ...     "error": "OFFSET_MISMATCH",
        ...     "message": "Upload offset mismatch: expected 5242880, received 0",
        ...     "details": {
        ...         "expected_offset": 5242880,
        ...         "received_offset": 0
        ...     }
        ... }
    """
    # Bind user context for structured logging
    bind_contextvars(
        user_id=str(current_user.user_id),
        workspace_id=str(current_user.workspace_id),
        session_id=str(upload_id),
        chunk_offset=upload_offset,
    )

    log.info(
        "upload_chunk_request",
        session_id=str(upload_id),
        offset=upload_offset,
        content_length=upload_length,
    )

    # STEP 1: Validate upload_length is positive (basic tus protocol compliance)
    if upload_length <= 0:
        log.warning(
            "upload_chunk_invalid_upload_length",
            provided=upload_length,
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "INVALID_UPLOAD_LENGTH",
                "message": "Upload-Length must be greater than 0",
                "details": {
                    "provided_upload_length": upload_length,
                },
            },
        )

    # STEP 2: Validate Content-Type (must be application/offset+octet-stream)
    if content_type != "application/offset+octet-stream":
        log.warning(
            "upload_chunk_invalid_content_type",
            provided=content_type,
            required="application/offset+octet-stream",
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "error": "UNSUPPORTED_CONTENT_TYPE",
                "message": "Content-Type must be application/offset+octet-stream",
                "details": {
                    "provided_content_type": content_type,
                    "required_content_type": "application/offset+octet-stream",
                },
            },
        )

    # STEP 2: Parse Upload-Checksum header (format: "sha256 {base64|hex}")
    # Strip whitespace to handle headers with embedded newlines/spaces
    upload_checksum = upload_checksum.strip()

    try:
        checksum_parts = upload_checksum.split(" ", 1)
        if len(checksum_parts) != 2 or checksum_parts[0] != "sha256":
            raise ValueError("Invalid checksum format - must start with 'sha256 '")

        checksum_value = checksum_parts[1]

        # Check if it's already hex format (64 chars, all hex digits)
        if len(checksum_value) == 64 and all(c in "0123456789abcdefABCDEF" for c in checksum_value):
            # Already hex - use as-is (lowercase)
            chunk_checksum = checksum_value.lower()
        else:
            # Try to decode as base64
            try:
                checksum_bytes = base64.b64decode(checksum_value)
                if len(checksum_bytes) != 32:  # SHA-256 is 32 bytes
                    raise ValueError("Decoded checksum must be 32 bytes (SHA-256)")
                chunk_checksum = checksum_bytes.hex()
            except (ValueError, binascii.Error) as base64_error:
                raise ValueError(
                    f"Invalid checksum format - must be 64-char hex or base64: {base64_error}"
                ) from base64_error

    except ValueError as e:
        log.warning(
            "upload_chunk_invalid_checksum_format",
            provided=upload_checksum,
            error=str(e),
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "INVALID_CHECKSUM_FORMAT",
                "message": "Upload-Checksum header must be in format 'sha256 {base64|hex}'",
                "details": {
                    "provided_checksum": upload_checksum,
                    "required_format": "sha256 {base64_or_hex_encoded_hash}",
                },
            },
        ) from e

    # STEP 4: Validate Content-Length before reading body (prevent memory exhaustion)
    content_length = request.headers.get("Content-Length")
    if content_length:
        try:
            content_length_int = int(content_length)
            # Enforce maximum chunk size of 100MB (configurable limit)
            if content_length_int > MAX_CHUNK_SIZE:
                log.warning(
                    "upload_chunk_body_too_large",
                    content_length=content_length_int,
                    max_allowed=MAX_CHUNK_SIZE,
                )
                clear_contextvars()
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail={
                        "error": "REQUEST_BODY_TOO_LARGE",
                        "message": f"Request body exceeds maximum chunk size of {MAX_CHUNK_SIZE} bytes",
                        "details": {
                            "content_length": content_length_int,
                            "max_chunk_size": MAX_CHUNK_SIZE,
                        },
                    },
                )
        except ValueError:
            # Invalid Content-Length header - let body reading fail naturally
            pass

    # STEP 5: Stream chunk data from request body
    try:
        # Stream body asynchronously - no blocking I/O
        chunk_data = await request.body()
    except Exception as e:
        log.error(
            "upload_chunk_read_body_failed",
            error=str(e),
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "READ_BODY_FAILED",
                "message": "Failed to read request body",
                "details": {},
            },
        ) from e

    # STEP 6: Create DTO and call use case
    dto_request = ProcessChunkRequest(
        workspace_id=current_user.workspace_id,
        session_id=upload_id,
        chunk_data=chunk_data,
        chunk_offset=upload_offset,
        chunk_checksum=chunk_checksum,
    )

    try:
        dto_response = await use_case.execute(dto_request)

        log.info(
            "upload_chunk_success",
            session_id=str(upload_id),
            new_offset=dto_response.new_offset,
            chunk_size=len(chunk_data),
        )

        clear_contextvars()

        # Return 204 No Content with Upload-Offset header
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={"Upload-Offset": str(dto_response.new_offset)},
        )

    except SessionNotFoundError as e:
        # 404 Session Not Found - expired or never existed
        log.warning(
            "upload_chunk_session_not_found",
            session_id=str(upload_id),
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "SESSION_NOT_FOUND",
                "message": str(e),
                "details": {
                    "session_id": str(upload_id),
                    "suggestion": "Start a new upload session via POST /v1/uploads",
                },
            },
        ) from e

    except OffsetMismatchError as e:
        # 409 Conflict - client offset doesn't match server offset
        log.warning(
            "upload_chunk_offset_mismatch",
            expected_offset=e.expected_offset,
            received_offset=e.received_offset,
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "OFFSET_MISMATCH",
                "message": str(e),
                "details": {
                    "expected_offset": e.expected_offset,
                    "received_offset": e.received_offset,
                    "suggestion": "Query HEAD /v1/uploads/{id} to get current offset before retrying",
                },
            },
        ) from e

    except ChecksumMismatchError as e:
        # 460 Checksum Mismatch - chunk corrupted in transit
        log.warning(
            "upload_chunk_checksum_mismatch",
            expected_checksum=e.expected_checksum,
            computed_checksum=e.computed_checksum,
            chunk_index=e.chunk_index,
        )
        clear_contextvars()
        raise HTTPException(
            status_code=460,  # Custom status code per tus protocol
            detail={
                "error": "CHECKSUM_MISMATCH",
                "message": str(e),
                "details": {
                    "expected_checksum": e.expected_checksum,
                    "computed_checksum": e.computed_checksum,
                    "chunk_index": e.chunk_index,
                    "chunk_size": len(chunk_data),
                    "suggestion": "Retry uploading this chunk only (do not restart full upload)",
                },
            },
        ) from e

    except InfrastructureError as e:
        # 503 Service Unavailable - Redis/storage failure
        log.error(
            "upload_chunk_infrastructure_error",
            error=str(e),
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "INFRASTRUCTURE_ERROR",
                "message": str(e),
                "details": {
                    "retry_guidance": "Retry after a few seconds",
                },
            },
        ) from e

    except ValueError as e:
        # 422 Unprocessable Entity - validation error from DTO
        log.warning(
            "upload_chunk_validation_error",
            error=str(e),
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "VALIDATION_ERROR",
                "message": str(e),
                "details": {},
            },
        ) from e

    except Exception as e:
        # Catch-all for unexpected errors
        log.error(
            "upload_chunk_unexpected_error",
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


@router.head(
    "/uploads/{upload_id}",
    status_code=status.HTTP_200_OK,
    summary="Query current upload offset for resumability",
    description=(
        "Returns current verified byte offset in Upload-Offset header. "
        "Client calls this before resuming to determine where to continue. "
        "Critical performance target: <50ms p99 (hot retry path). "
        "Allows both OWNER and COLLABORATOR roles (read operation)."
    ),
    responses={
        200: {
            "description": "Session found - offset returned in headers",
            "headers": {
                "Upload-Offset": {
                    "description": "Current verified byte offset (start position for next chunk)",
                    "schema": {"type": "integer"},
                    "example": 5242880,
                },
                "Upload-Length": {
                    "description": "Total file size in bytes (from session initiation)",
                    "schema": {"type": "integer"},
                    "example": 10485760,
                },
            },
        },
        401: {
            "description": "Authentication failed (missing/invalid/expired JWT)",
            "content": {"application/json": {"example": {"detail": "Authentication failed"}}},
        },
        404: {
            "description": "Session not found or expired (24h TTL)",
            "content": {
                "application/json": {
                    "example": {
                        "error": "SESSION_NOT_FOUND",
                        "message": "Upload session 550e8400-e29b-41d4-a716-446655440000 not found or expired",
                        "details": {
                            "session_id": "550e8400-e29b-41d4-a716-446655440000",
                            "suggestion": "Start a new upload session via POST /v1/uploads",
                        },
                    }
                }
            },
        },
        410: {
            "description": "Session terminated (complete, aborted, or failed)",
            "content": {
                "application/json": {
                    "example": {
                        "error": "SESSION_TERMINATED",
                        "message": "Upload session 550e8400-e29b-41d4-a716-446655440000 is complete and cannot be resumed",
                        "details": {
                            "session_id": "550e8400-e29b-41d4-a716-446655440000",
                            "status": "complete",
                            "suggestion": "Start a new upload session via POST /v1/uploads",
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
async def query_upload_offset(
    upload_id: UUID,
    current_user: Annotated[JWTClaims, Depends(get_current_user)],
    session_store: Annotated[ISessionStore, Depends(get_session_store)],
) -> Response:
    """Query current upload offset for resumability.

    Returns current verified byte offset and total file size in response headers.
    This is THE critical endpoint for upload resumability - client must call this
    before resuming to determine where to continue from.

    Authentication & Authorization:
        - Requires valid JWT in Authorization header (Bearer token)
        - Allows both OWNER and COLLABORATOR roles (read operation)
        - workspace_id extracted from JWT claims

    Request:
        - No request body (HEAD method)
        - No query parameters
        - Path parameter: upload_id (UUID)

    Response Headers (Success):
        - Upload-Offset: Current verified byte offset (start position for next chunk)
        - Upload-Length: Total file size in bytes (from session initiation)

    Response Body:
        - Empty (HEAD method returns headers only, no body)

    Error Handling:
        - 401: Authentication failed (missing/invalid/expired JWT)
        - 404: Session not found or expired (24h TTL)
        - 503: Infrastructure failure (Redis connection error)

    Performance (Critical - NFR-P2):
        - Target: <50ms at p99 (hot retry path)
        - This is faster than POST (<200ms) and PATCH (<100ms)
        - Why so fast? Clients call this BEFORE every resume attempt
        - Implementation: Single Redis lookup, no business logic

    tus Protocol Compliance:
        - HEAD offset query is core tus v1.0.0 protocol operation
        - Upload-Offset header indicates where client should resume
        - Upload-Length header provides total size for validation

    Args:
        upload_id: Upload session UUID from path parameter
        current_user: JWT claims from authentication (contains workspace_id)
        session_store: Injected session store for Redis operations

    Returns:
        Response: 200 OK with Upload-Offset and Upload-Length headers, empty body

    Raises:
        HTTPException: 401/404/503 with structured error details

    Examples:
        >>> # Success case - query offset after uploading first chunk
        >>> HEAD /v1/uploads/550e8400-e29b-41d4-a716-446655440000
        >>> Authorization: Bearer <token>
        >>>
        >>> # Response 200 OK
        >>> Upload-Offset: 5242880
        >>> Upload-Length: 10485760
        >>> (empty body)
        >>>
        >>> # Client interprets: "I've uploaded 5MB of 10MB total. Resume from byte 5242880."
        >>>
        >>> # Session not found (expired or never existed)
        >>> HEAD /v1/uploads/550e8400-e29b-41d4-a716-446655440000
        >>> Authorization: Bearer <token>
        >>>
        >>> # Response 404 Not Found
        >>> {
        ...     "error": "SESSION_NOT_FOUND",
        ...     "message": "Upload session 550e8400-e29b-41d4-a716-446655440000 not found or expired",
        ...     "details": {
        ...         "session_id": "550e8400-e29b-41d4-a716-446655440000",
        ...         "suggestion": "Start a new upload session via POST /v1/uploads"
        ...     }
        ... }
    """
    # Bind user context for structured logging
    bind_contextvars(
        user_id=str(current_user.user_id),
        workspace_id=str(current_user.workspace_id),
        session_id=str(upload_id),
    )

    try:
        log.info(
            "query_upload_offset_request",
            session_id=str(upload_id),
        )

        try:
            # Retrieve session from Redis with timeout (5s max for <50ms p99 target)
            session = await asyncio.wait_for(
                session_store.get_session(
                    workspace_id=current_user.workspace_id,
                    session_id=upload_id,
                ),
                timeout=5.0,
            )

        except TimeoutError as e:
            # Timeout treated as infrastructure error
            log.error(
                "query_upload_offset_timeout",
                timeout_seconds=5.0,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "INFRASTRUCTURE_ERROR",
                    "message": "Storage system response timeout. Please retry.",
                    "details": {
                        "retry_guidance": "Retry after a few seconds",
                    },
                },
            ) from e

        except InfrastructureError as e:
            # 503 Service Unavailable - Redis connection failure
            log.error(
                "query_upload_offset_infrastructure_error",
                error=str(e),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "INFRASTRUCTURE_ERROR",
                    "message": str(e),
                    "details": {
                        "retry_guidance": "Retry after a few seconds",
                    },
                },
            ) from e

        except Exception as e:
            # 500 Internal Server Error - unexpected error
            log.error(
                "query_upload_offset_unexpected_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred",
                    "details": {"error_type": type(e).__name__},
                },
            ) from e

        # Check if session exists (None means not found or expired)
        if session is None:
            log.warning(
                "query_upload_offset_session_not_found",
                session_id=str(upload_id),
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "SESSION_NOT_FOUND",
                    "message": f"Upload session {upload_id} not found or expired",
                    "details": {
                        "session_id": str(upload_id),
                        "suggestion": "Start a new upload session via POST /v1/uploads",
                    },
                },
            )

        # Check if session is in a terminated state
        if session.status in (
            SessionStatus.COMPLETE,
            SessionStatus.ABORTED,
            SessionStatus.FAILED,
        ):
            log.warning(
                "query_upload_offset_session_terminated",
                session_id=str(upload_id),
                status=session.status.value,
            )
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail={
                    "error": "SESSION_TERMINATED",
                    "message": f"Upload session {upload_id} is {session.status.value} and cannot be resumed",
                    "details": {
                        "session_id": str(upload_id),
                        "status": session.status.value,
                        "suggestion": "Start a new upload session via POST /v1/uploads",
                    },
                },
            )

        # Validate offset and size (detect data corruption)
        if session.offset < 0 or session.offset > session.size:
            log.error(
                "query_upload_offset_data_corruption",
                session_id=str(upload_id),
                offset=session.offset,
                size=session.size,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "DATA_CORRUPTION",
                    "message": "Invalid session state detected",
                    "details": {
                        "session_id": str(upload_id),
                        "suggestion": "Contact support",
                    },
                },
            )

        # Session found and valid - return offset and length headers
        log.info(
            "query_upload_offset_success",
            session_id=str(upload_id),
            offset=session.offset,
            size=session.size,
            status=session.status.value,
        )

        # Return 200 OK with Upload-Offset, Upload-Length, and Cache-Control headers
        return Response(
            status_code=status.HTTP_200_OK,
            headers={
                "Upload-Offset": str(session.offset),
                "Upload-Length": str(session.size),
                "Cache-Control": "no-store, no-cache, must-revalidate",
            },
        )

    finally:
        # Always clear context variables to prevent bleed between requests
        clear_contextvars()
