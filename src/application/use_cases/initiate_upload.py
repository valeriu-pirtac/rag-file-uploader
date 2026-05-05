"""Use case for initiating new chunked upload sessions.

This module implements the InitiateUploadUseCase, which orchestrates the
creation of new upload sessions including rate limiting, validation, session
creation, and counter management.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.application.dto.upload_request import InitiateUploadRequest
from src.application.dto.upload_response import InitiateUploadResponse
from src.domain.entities.upload_session import UploadSession
from src.domain.protocols.rate_limiter import IRateLimiter
from src.domain.protocols.session_store import ISessionStore
from src.domain.value_objects.session_status import SessionStatus
from src.domain.value_objects.sha256_hash import SHA256Hash


class InitiateUploadUseCase:
    """Use case for initiating new chunked upload sessions.

    This use case orchestrates the creation of a new upload session,
    including rate limiting, validation, session creation, and counter
    management. This is the entry point for all file uploads.

    Business Rules:
        - Rate limit check MUST happen first (fail fast)
        - File size MUST be ≤ 1 GB (FR14)
        - MIME type MUST be "application/pdf" (FR15)
        - Session ID generated with UUID v4 (NFR-S3)
        - Session TTL set to 24 hours (FR10)
        - Rate limit counter incremented atomically

    Performance Target:
        - Complete in <200ms at p99 (NFR-P1)
        - Includes: rate limit check, validation, Redis create, counter increment

    Error Handling:
        - RateLimitExceededError: Workspace at concurrent upload limit
        - FileSizeLimitExceededError: File size > 1 GB
        - UnsupportedMediaTypeError: MIME type not "application/pdf"
        - InfrastructureError: Redis connection failure

    Counter Management:
        - Rate limit counter incremented by check_and_increment (step 1)
        - Counter MUST be decremented if session creation fails (prevent leak)
        - Counter cleanup also includes validation failures (best practice)

    Integration Points:
        - Story 3.3: Uses IRateLimiter for rate limit enforcement
        - Story 3.2: Uses ISessionStore for session persistence
        - Story 3.1: Creates UploadSession entity
        - Future Story 3.5: Called by POST /v1/uploads API endpoint

    Attributes:
        _rate_limiter: Rate limiter protocol implementation
        _session_store: Session store protocol implementation

    Examples:
        >>> # Create use case with dependencies
        >>> use_case = InitiateUploadUseCase(
        ...     rate_limiter=redis_rate_limiter,
        ...     session_store=redis_session_store
        ... )
        >>>
        >>> # Initiate upload session
        >>> request = InitiateUploadRequest(
        ...     workspace_id=uuid4(),
        ...     filename="document.pdf",
        ...     size=1048576,  # 1 MB
        ...     mime_type="application/pdf",
        ...     sha256_checksum="a" * 64
        ... )
        >>> response = await use_case.execute(request)
        >>> print(f"Session ID: {response.session_id}")
        >>> print(f"Expires at: {response.expires_at}")
    """

    def __init__(
        self,
        rate_limiter: IRateLimiter,
        session_store: ISessionStore,
    ) -> None:
        """Initialize the use case with protocol dependencies.

        Args:
            rate_limiter: Rate limiter protocol implementation for enforcing
                per-workspace concurrent upload limits
            session_store: Session store protocol implementation for persisting
                upload session state in durable storage
        """
        self._rate_limiter = rate_limiter
        self._session_store = session_store

    async def execute(self, request: InitiateUploadRequest) -> InitiateUploadResponse:
        """Execute the initiate upload use case.

        Orchestrates the complete flow of creating a new upload session:
        1. Validate file size, MIME type, filename, and checksum (fail fast)
        2. Check and increment rate limit (only for valid requests)
        3. Generate cryptographically random session ID (UUID v4)
        4. Create timestamps (created_at, expires_at with 24h TTL)
        5. Create UploadSession entity
        6. Persist session to storage with 24-hour TTL
        7. Return response with session_id, offset, expires_at

        Rate Limit Counter Management:
            The counter is incremented in step 2 (check_and_increment).
            If any subsequent step fails, the counter MUST be decremented
            to prevent counter leaks that would artificially constrain
            workspace capacity.

        Execution Order (Critical):
            Validation happens FIRST to fail fast for invalid requests
            without consuming Redis operations. Rate limit check happens
            after validation, only for valid requests.

        Args:
            request: InitiateUploadRequest DTO containing workspace_id,
                filename, size, mime_type, and sha256_checksum

        Returns:
            InitiateUploadResponse with session_id, offset (0), and
            expires_at timestamp (24 hours from now)

        Raises:
            RateLimitExceededError: Workspace has reached concurrent upload
                limit. Contains retry_after_seconds suggestion.
            FileSizeLimitExceededError: File size exceeds 1 GB limit.
                Contains file_size and max_size for error message.
            UnsupportedMediaTypeError: MIME type not in allowed list.
                Contains provided_mime_type and allowed_mime_types.
            InfrastructureError: Storage system failure (Redis connection,
                timeout, etc.). Rate limit counter is decremented before
                re-raising.

        Examples:
            >>> # Success case
            >>> request = InitiateUploadRequest(
            ...     workspace_id=uuid4(),
            ...     filename="document.pdf",
            ...     size=1048576,
            ...     mime_type="application/pdf",
            ...     sha256_checksum="a" * 64
            ... )
            >>> response = await use_case.execute(request)
            >>> assert response.offset == 0
            >>> assert response.session_id is not None
            >>>
            >>> # Rate limit exceeded
            >>> try:
            ...     await use_case.execute(request)
            ... except RateLimitExceededError as e:
            ...     print(f"Retry after {e.retry_after_seconds} seconds")
        """
        # STEP 1: Validation (MUST be first - fail fast for invalid requests)
        # Validate before rate limiting to avoid Redis ops for invalid data
        request.validate_filename()
        request.validate_checksum()
        request.validate_size()
        request.validate_mime_type()

        # STEP 2: Rate limit check (only for valid requests)
        # This increments the counter atomically if below limit
        await self._rate_limiter.check_and_increment(request.workspace_id)

        try:
            # STEP 3: Generate session ID (UUID v4 for cryptographic randomness)
            session_id = uuid4()

            # STEP 4: Create timestamps (must be timezone-aware UTC)
            created_at = datetime.now(UTC)
            expires_at = created_at + timedelta(hours=24)

            # STEP 5: Create UploadSession entity
            session = UploadSession(
                session_id=session_id,
                workspace_id=request.workspace_id,
                filename=request.filename,
                size=request.size,
                mime_type=request.mime_type,
                sha256_checksum=SHA256Hash(request.sha256_checksum),
                offset=0,
                status=SessionStatus.PENDING,
                created_at=created_at,
                expires_at=expires_at,
                chunk_manifest=[],
            )

            # STEP 6: Persist session (sets 24-hour TTL in Redis)
            await self._session_store.create_session(session)

            # STEP 7: Return response
            return InitiateUploadResponse(
                session_id=session_id,
                offset=0,
                expires_at=expires_at,
            )

        except Exception:
            # CRITICAL: Cleanup rate limit counter on any failure after increment
            # This prevents counter leaks that would artificially reduce capacity
            #
            # Catches all exceptions including:
            # - InfrastructureError: Redis connection/timeout failures
            # - ValueError/TypeError: Entity validation failures from UploadSession
            # - Any unexpected errors during session creation
            #
            # We must cleanup the counter before re-raising the original exception.
            # If decrement itself fails, we log but still re-raise the original error.
            try:
                await self._rate_limiter.decrement(request.workspace_id)
            except Exception:
                # Decrement failed (Redis down, network issue)
                # Log this but don't mask the original exception
                # TODO: Add proper logging when observability layer is implemented
                pass

            # Re-raise the original exception
            raise
