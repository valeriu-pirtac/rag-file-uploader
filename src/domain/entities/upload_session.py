"""Upload session domain entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from src.domain.exceptions import (
    FileSizeLimitExceededError,
    UnsupportedMediaTypeError,
)
from src.domain.value_objects.session_status import SessionStatus
from src.domain.value_objects.sha256_hash import SHA256Hash


# Maximum file size: 1 GB in bytes
MAX_FILE_SIZE_BYTES = 1_073_741_824

# Allowed MIME types for upload
ALLOWED_MIME_TYPES = ["application/pdf"]


@dataclass(frozen=False)
class UploadSession:
    """Domain entity representing a chunked file upload session.

    An upload session manages the lifecycle of a chunked file upload, tracking
    progress, validating chunks, and maintaining session state. Sessions are
    scoped to a workspace for multi-tenancy isolation.

    Business Rules:
        - File size must be > 0 and ≤ 1 GB (enforced in validation)
        - MIME type must be "application/pdf" (enforced in validation)
        - Offset must always be ≥ 0 and ≤ size
        - All timestamps must be timezone-aware UTC
        - Session expires 24 hours after creation
        - Status transitions follow valid lifecycle paths
        - Session can only be marked complete when offset == size

    Status Lifecycle:
        PENDING → IN_PROGRESS → COMPLETE/FAILED/ABORTED
        Any state → ABORTED (explicit abort)

    Attributes:
        session_id: Unique identifier for the upload session (UUID v4)
        workspace_id: Workspace this session belongs to (isolation boundary)
        filename: Original filename for display and debugging
        size: Total file size in bytes (validated ≤ 1 GB)
        mime_type: File MIME type (must be "application/pdf")
        sha256_checksum: Expected SHA-256 hash of complete file (for deduplication)
        offset: Current verified byte offset (starts at 0, updated per chunk)
        status: Current session status (PENDING, IN_PROGRESS, etc.)
        created_at: Session creation timestamp (UTC timezone-aware)
        expires_at: Session expiry timestamp (UTC timezone-aware, 24 hours)
        chunk_manifest: List of verified chunks with metadata
            Each entry: {"index": int, "size": int, "checksum": str}

    Examples:
        >>> from uuid import uuid4
        >>> from datetime import datetime, timedelta, timezone
        >>>
        >>> # Create new upload session
        >>> session = UploadSession(
        ...     session_id=uuid4(),
        ...     workspace_id=uuid4(),
        ...     filename="document.pdf",
        ...     size=1024 * 1024,  # 1 MB
        ...     mime_type="application/pdf",
        ...     sha256_checksum=SHA256Hash("a" * 64),
        ...     offset=0,
        ...     status=SessionStatus.PENDING,
        ...     created_at=datetime.now(timezone.utc),
        ...     expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        ...     chunk_manifest=[]
        ... )
        >>>
        >>> # Track chunk uploads
        >>> session.mark_in_progress()
        >>> session.add_chunk(0, 1024, "chunk0_hash")
        >>> session.update_offset(1024)
        >>>
        >>> # Check completion
        >>> if session.is_complete():
        ...     print("Upload complete!")
    """

    session_id: UUID
    workspace_id: UUID
    filename: str  # Note: Direct mutation bypasses validation - use methods for state changes
    size: int
    mime_type: str
    sha256_checksum: SHA256Hash
    offset: int
    status: SessionStatus
    created_at: datetime
    expires_at: datetime
    chunk_manifest: list[dict[str, Any]]

    def __post_init__(self) -> None:
        """Validate invariants after initialization.

        Raises:
            TypeError: If session_id, workspace_id not UUID, or chunk_manifest not list
            ValueError: If size, offset, or timestamp validation fails
            FileSizeLimitExceededError: If size exceeds 1 GB
            UnsupportedMediaTypeError: If mime_type is not "application/pdf"
        """
        # Validate UUID types
        if not isinstance(self.session_id, UUID):
            raise TypeError("session_id must be a UUID")
        if not isinstance(self.workspace_id, UUID):
            raise TypeError("workspace_id must be a UUID")

        # Validate filename
        if not self.filename or not self.filename.strip():
            raise ValueError("filename cannot be empty")
        if "/" in self.filename or "\\" in self.filename:
            raise ValueError("filename cannot contain path separators")
        if "\x00" in self.filename:
            raise ValueError("filename cannot contain null bytes")
        if len(self.filename) > 255:
            raise ValueError("filename cannot exceed 255 characters")

        # Validate file size
        if self.size <= 0:
            raise ValueError("size must be > 0")
        if self.size > MAX_FILE_SIZE_BYTES:
            raise FileSizeLimitExceededError(self.size, MAX_FILE_SIZE_BYTES)

        # Validate MIME type
        if self.mime_type not in ALLOWED_MIME_TYPES:
            raise UnsupportedMediaTypeError(self.mime_type, ALLOWED_MIME_TYPES)

        # Validate offset
        if self.offset < 0 or self.offset > self.size:
            raise ValueError("offset must be >= 0 and <= size")

        # Validate timestamps are timezone-aware
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")

        # Validate expires_at is after created_at
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")

        # Validate chunk_manifest is a list
        if not isinstance(self.chunk_manifest, list):
            raise TypeError("chunk_manifest must be a list")

        # Validate chunk_manifest structure
        for i, chunk in enumerate(self.chunk_manifest):
            if not isinstance(chunk, dict):
                raise TypeError(f"chunk_manifest[{i}] must be a dict")
            if "index" not in chunk or "size" not in chunk or "checksum" not in chunk:
                raise ValueError(
                    f"chunk_manifest[{i}] must contain 'index', 'size', and 'checksum' keys"
                )

    def add_chunk(self, chunk_index: int, chunk_size: int, chunk_checksum: str) -> None:
        """Add a verified chunk to the chunk manifest.

        This method records metadata about a successfully verified chunk. The chunk
        manifest provides an audit trail and enables resume functionality.

        Args:
            chunk_index: Zero-based index of the chunk
            chunk_size: Size of the chunk in bytes
            chunk_checksum: SHA-256 checksum of the chunk data

        Raises:
            ValueError: If chunk_index is negative, chunk_size is non-positive,
                       chunk_checksum is empty, or chunk_index already exists

        Examples:
            >>> session.add_chunk(chunk_index=0, chunk_size=1024, chunk_checksum="abc123")
            >>> session.add_chunk(chunk_index=1, chunk_size=2048, chunk_checksum="def456")
        """
        if chunk_index < 0:
            raise ValueError("chunk_index must be >= 0")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be > 0")
        if not chunk_checksum or not chunk_checksum.strip():
            raise ValueError("chunk_checksum cannot be empty")
        if any(c["index"] == chunk_index for c in self.chunk_manifest):
            raise ValueError(f"chunk_index {chunk_index} already exists in manifest")

        self.chunk_manifest.append(
            {
                "index": chunk_index,
                "size": chunk_size,
                "checksum": chunk_checksum,
            }
        )

    def update_offset(self, new_offset: int) -> None:
        """Update the current verified byte offset.

        The offset represents how many bytes have been successfully uploaded and
        verified. It must never exceed the total file size and must not go backwards.

        Args:
            new_offset: New offset value in bytes

        Raises:
            ValueError: If new_offset is negative, > size, or < current offset

        Examples:
            >>> session.update_offset(1024)  # 1 KB uploaded
            >>> session.update_offset(5242880)  # 5 MB uploaded
        """
        if new_offset < 0:
            raise ValueError("new_offset must be >= 0")
        if new_offset < self.offset:
            raise ValueError("cannot decrease offset (non-monotonic update)")
        if new_offset > self.size:
            raise ValueError("new_offset must be <= size")
        self.offset = new_offset

    def mark_in_progress(self) -> None:
        """Transition session status to IN_PROGRESS.

        This method should be called when the first chunk is received, indicating
        that upload has begun.

        Raises:
            ValueError: If session is already in a terminal state (COMPLETE, FAILED, ABORTED)

        Examples:
            >>> session.status == SessionStatus.PENDING
            True
            >>> session.mark_in_progress()
            >>> session.status == SessionStatus.IN_PROGRESS
            True
        """
        if self.status in (SessionStatus.COMPLETE, SessionStatus.FAILED, SessionStatus.ABORTED):
            raise ValueError(
                f"Cannot transition from {self.status} to IN_PROGRESS (invalid state transition)"
            )
        self.status = SessionStatus.IN_PROGRESS

    def mark_complete(self) -> None:
        """Transition session status to COMPLETE.

        This method validates that the entire file has been uploaded (offset == size)
        before transitioning to COMPLETE status.

        Raises:
            ValueError: If offset < size (upload incomplete) or session already in terminal state

        Examples:
            >>> session.offset = session.size  # All bytes uploaded
            >>> session.mark_complete()
            >>> session.status == SessionStatus.COMPLETE
            True
        """
        if self.status in (SessionStatus.COMPLETE, SessionStatus.FAILED, SessionStatus.ABORTED):
            raise ValueError(
                f"Cannot transition from {self.status} to COMPLETE (invalid state transition)"
            )
        if self.offset < self.size:
            raise ValueError("Cannot mark complete: offset < size")
        self.status = SessionStatus.COMPLETE

    def mark_failed(self) -> None:
        """Transition session status to FAILED.

        This method should be called when an error occurs during upload or
        verification that makes the session unrecoverable.

        Examples:
            >>> session.mark_failed()
            >>> session.status == SessionStatus.FAILED
            True
        """
        self.status = SessionStatus.FAILED

    def mark_aborted(self) -> None:
        """Transition session status to ABORTED.

        This method should be called when the user explicitly cancels the upload
        or the system aborts the session (e.g., due to expiration).

        Examples:
            >>> session.mark_aborted()
            >>> session.status == SessionStatus.ABORTED
            True
        """
        self.status = SessionStatus.ABORTED

    def is_expired(self, current_time: datetime) -> bool:
        """Check if the session has expired.

        A session is expired if the current time is past the expires_at timestamp.
        Expired sessions should be cleaned up and cannot be resumed.

        Args:
            current_time: Current timestamp to check against (timezone-aware)

        Returns:
            True if session is expired, False otherwise

        Raises:
            ValueError: If current_time is not timezone-aware

        Examples:
            >>> from datetime import datetime, timezone
            >>> current = datetime.now(timezone.utc)
            >>> session.is_expired(current)
            False
            >>> # 25 hours later...
            >>> future = current + timedelta(hours=25)
            >>> session.is_expired(future)
            True
        """
        if current_time.tzinfo is None:
            raise ValueError("current_time must be timezone-aware")
        return current_time > self.expires_at

    def is_complete(self) -> bool:
        """Check if the upload is complete.

        An upload is complete when all bytes have been uploaded (offset == size)
        AND the session status is COMPLETE.

        Returns:
            True if upload is complete, False otherwise

        Examples:
            >>> session.offset = session.size
            >>> session.mark_complete()
            >>> session.is_complete()
            True
        """
        return self.offset == self.size and self.status == SessionStatus.COMPLETE
