"""Domain exceptions for the rag-file-uploader service.

This module defines custom exceptions used across the domain layer.
"""

from uuid import UUID


class DomainException(Exception):
    """Base exception for all domain-layer errors."""

    pass


class AuthenticationError(DomainException):
    """Raised when authentication fails."""

    pass


class TokenExpiredError(AuthenticationError):
    """Raised when a JWT token has expired."""

    pass


class InvalidTokenError(AuthenticationError):
    """Raised when a JWT token is invalid or malformed."""

    pass


class UploadSessionNotFoundError(DomainException):
    """Raised when an upload session cannot be found."""

    pass


# Alias for protocol consistency (ISessionStore uses SessionNotFoundError)
SessionNotFoundError = UploadSessionNotFoundError


class InfrastructureError(DomainException):
    """Base exception for infrastructure layer failures.

    Raised when external dependencies fail (Redis, S3, NATS, ClamAV, etc.).
    This includes connection errors, timeouts, network issues, and other
    infrastructure-level problems.

    Examples:
        - Redis connection timeout
        - S3 bucket access denied
        - NATS publish failure
        - ClamAV daemon unreachable
    """

    pass


class SerializationError(InfrastructureError):
    """Raised when data serialization/deserialization fails.

    This indicates data corruption, invalid format, or incompatible schema
    changes between service versions.

    Examples:
        - Invalid JSON in Redis hash field
        - Missing required field during deserialization
        - Invalid UUID string format
        - Malformed datetime string
    """

    pass


class ChecksumMismatchError(DomainException):
    """Raised when chunk checksum verification fails.

    This exception indicates that the SHA-256 hash computed from the uploaded
    chunk data does not match the checksum provided by the client in the
    Upload-Checksum header. This can occur due to:

    - Network corruption during transmission
    - Client-side checksum computation error
    - Intentional tampering attempt
    - Partial chunk reception (incomplete data)

    Attributes:
        expected_checksum: The SHA-256 hash provided by client
        computed_checksum: The SHA-256 hash computed from received data
        chunk_index: Optional chunk sequence number
        chunk_size: Size of chunk data in bytes
    """

    def __init__(
        self,
        expected_checksum: str,
        computed_checksum: str,
        chunk_index: int | None = None,
        chunk_size: int = 0,
    ) -> None:
        """Initialize checksum mismatch error.

        Args:
            expected_checksum: The SHA-256 hash provided by client
            computed_checksum: The SHA-256 hash computed from received data
            chunk_index: Optional chunk sequence number for multi-chunk debugging
            chunk_size: Size of chunk data in bytes for diagnostic context

        Example:
            >>> error = ChecksumMismatchError(
            ...     expected_checksum="b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
            ...     computed_checksum="a948904f2f0f479b8f8197694b30184b0d2ed1c1cd2a1ec0fb85d299a192a447",
            ...     chunk_index=42,
            ...     chunk_size=5242880
            ... )
            >>> str(error)
            'Chunk checksum verification failed: expected b94d27b..., got a948904... (chunk 42) (5242880 bytes)'
        """
        # Validate inputs
        if not expected_checksum:
            raise ValueError("expected_checksum cannot be empty")
        if not computed_checksum:
            raise ValueError("computed_checksum cannot be empty")
        if chunk_index is not None and chunk_index < 0:
            raise ValueError("chunk_index cannot be negative")
        if chunk_size < 0:
            raise ValueError("chunk_size cannot be negative")

        self.expected_checksum = expected_checksum
        self.computed_checksum = computed_checksum
        self.chunk_index = chunk_index
        self.chunk_size = chunk_size

        message = (
            f"Chunk checksum verification failed: "
            f"expected {expected_checksum}, got {computed_checksum}"
        )
        if chunk_index is not None:
            message += f" (chunk {chunk_index})"
        if chunk_size > 0:
            message += f" ({chunk_size} bytes)"

        super().__init__(message)


class OffsetMismatchError(DomainException):
    """Raised when client upload offset doesn't match session offset.

    This exception indicates a synchronization issue between client and server
    state. This can occur due to:

    - Client resuming without querying HEAD /v1/uploads/{id} first
    - Client retrying a failed chunk without updating offset
    - Network issues causing client state corruption
    - Race condition with multiple concurrent clients (should never happen)

    The client MUST query HEAD /v1/uploads/{id} to get the current offset
    before retrying or resuming uploads.

    Attributes:
        expected_offset: The current session offset (server state)
        received_offset: The offset provided by client
        session_id: Upload session UUID for debugging
    """

    def __init__(
        self,
        expected_offset: int,
        received_offset: int,
        session_id: UUID,
    ) -> None:
        """Initialize offset mismatch error.

        Args:
            expected_offset: The current session offset (server state)
            received_offset: The offset provided by client
            session_id: Upload session UUID for debugging

        Raises:
            ValueError: If offsets are negative

        Example:
            >>> from uuid import uuid4
            >>> error = OffsetMismatchError(
            ...     expected_offset=5242880,
            ...     received_offset=0,
            ...     session_id=uuid4()
            ... )
            >>> str(error)
            'Upload offset mismatch: expected 5242880, received 0 (session xxxxxxxx-xxxx-...)'
        """
        if expected_offset < 0:
            raise ValueError("expected_offset cannot be negative")
        if received_offset < 0:
            raise ValueError("received_offset cannot be negative")

        self.expected_offset = expected_offset
        self.received_offset = received_offset
        self.session_id = session_id

        message = (
            f"Upload offset mismatch: "
            f"expected {expected_offset}, received {received_offset} "
            f"(session {session_id})"
        )

        super().__init__(message)


class InvalidSessionStateError(DomainException):
    """Raised when attempting an operation on a session in invalid state.

    This exception indicates a session state transition or operation that is
    not allowed given the current session status. Common scenarios:

    - Uploading chunks to a COMPLETE session (upload already finished)
    - Uploading chunks to a FAILED session (upload failed, cannot continue)
    - Uploading chunks to an ABORTED session (upload cancelled by client)
    - Any operation requiring specific status that doesn't match current state

    Terminal states (COMPLETE, FAILED, ABORTED) cannot accept new chunks.

    Attributes:
        session_id: Upload session UUID for debugging
        current_state: The actual session status that caused rejection
        operation: The operation that was attempted (e.g., "process_chunk")
    """

    def __init__(
        self,
        session_id: UUID,
        current_state: str,
        operation: str,
    ) -> None:
        """Initialize invalid session state error.

        Args:
            session_id: Upload session UUID for debugging
            current_state: The actual session status that caused rejection
            operation: The operation that was attempted

        Example:
            >>> from uuid import uuid4
            >>> error = InvalidSessionStateError(
            ...     session_id=uuid4(),
            ...     current_state="COMPLETE",
            ...     operation="process_chunk"
            ... )
            >>> str(error)
            'Cannot process_chunk for session ... in COMPLETE state'
        """
        self.session_id = session_id
        self.current_state = current_state
        self.operation = operation

        message = f"Cannot {operation} for session {session_id} in {current_state} state"

        super().__init__(message)


class RateLimitExceededError(DomainException):
    """Raised when workspace exceeds concurrent upload limit.

    This exception is thrown when a workspace attempts to start a new upload
    session but has already reached the maximum number of concurrent active
    uploads (MAX_CONCURRENT_UPLOADS).

    Attributes:
        workspace_id: The workspace that exceeded the limit
        current_count: Current number of active uploads for the workspace
        limit: Maximum allowed concurrent uploads per workspace
        retry_after_seconds: Suggested retry delay in seconds (default: 60)
    """

    def __init__(
        self,
        workspace_id: str,
        current_count: int,
        limit: int,
        retry_after_seconds: int = 60,
    ) -> None:
        """Initialize rate limit exceeded error.

        Args:
            workspace_id: The workspace UUID as string
            current_count: Current number of active uploads
            limit: Maximum allowed concurrent uploads
            retry_after_seconds: Suggested retry delay (default: 60 seconds)

        Raises:
            ValueError: If current_count < 0, limit <= 0, or retry_after_seconds <= 0
        """
        if current_count < 0:
            raise ValueError("current_count cannot be negative")
        if limit <= 0:
            raise ValueError("limit must be positive")
        if retry_after_seconds <= 0:
            raise ValueError("retry_after_seconds must be positive")

        self.workspace_id = workspace_id
        self.current_count = current_count
        self.limit = limit
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Workspace {workspace_id} has {current_count} active uploads "
            f"(limit: {limit}). Retry after {retry_after_seconds} seconds."
        )


class DuplicateFileError(DomainException):
    """Raised when a file with the same SHA-256 already exists in the workspace."""

    pass


class FileSizeLimitExceededError(DomainException):
    """Raised when a file size exceeds the maximum allowed limit.

    Attributes:
        file_size: The size of the file in bytes
        max_size: The maximum allowed file size in bytes
    """

    def __init__(self, file_size: int, max_size: int) -> None:
        self.file_size = file_size
        self.max_size = max_size
        super().__init__(
            f"File size {file_size} bytes exceeds maximum allowed size of {max_size} bytes"
        )


class UnsupportedMediaTypeError(DomainException):
    """Raised when a file's MIME type is not supported.

    Attributes:
        provided_mime_type: The MIME type that was provided
        allowed_mime_types: The list of allowed MIME types
    """

    def __init__(self, provided_mime_type: str, allowed_mime_types: list[str]) -> None:
        self.provided_mime_type = provided_mime_type
        self.allowed_mime_types = allowed_mime_types
        super().__init__(
            f"MIME type '{provided_mime_type}' is not supported. "
            f"Allowed types: {', '.join(allowed_mime_types)}"
        )
