"""Deduplication storage protocol for file fingerprint management.

This module defines the IDeduplicationStore protocol, which specifies the contract
for checking and registering file fingerprints to prevent duplicate uploads within
a workspace. Implementations must provide workspace-scoped duplicate detection using
SHA-256 checksums.

Protocol Contract:
    - All methods are async (storage operations are I/O bound)
    - Fingerprints MUST be isolated by workspace_id (security requirement NFR-S5)
    - check_duplicate returns None for new files (no exception)
    - check_duplicate returns FileMetadata if duplicate found
    - register_file is idempotent (can register same fingerprint multiple times)
    - No TTL on fingerprints (files are immutable on bronze layer)

Error Handling:
    - InfrastructureError: Raised for storage system failures (connection, timeout)
    - SerializationError: Raised for data corruption or invalid format

Workspace Isolation:
    - Same SHA-256 in different workspaces = NOT duplicate
    - Each workspace has its own fingerprint storage
    - Supports multi-tenant security (NFR-S5)

Implementation Notes:
    - Implementations are typically in src/infrastructure/
    - Redis implementation: src/infrastructure/redis/deduplication_store.py
    - Use dependency injection to swap implementations (testing, different backends)

Examples:
    >>> from uuid import uuid4
    >>> from datetime import datetime, timezone
    >>>
    >>> # Check for duplicate before file assembly
    >>> workspace_id = uuid4()
    >>> sha256 = SHA256Hash("a" * 64)
    >>>
    >>> metadata = await dedup_store.check_duplicate(workspace_id, sha256)
    >>> if metadata:
    ...     # File already exists - return 409 Duplicate
    ...     print(f"Duplicate found: {metadata.file_id}")
    ... else:
    ...     # New file - proceed with upload
    ...     print("File is unique, proceeding...")
    >>>
    >>> # Register fingerprint after successful upload
    >>> metadata = FileMetadata(
    ...     file_id=uuid4(),
    ...     s3_path="workspace_123/abc.pdf",
    ...     size=1024,
    ...     uploaded_at=datetime.now(timezone.utc)
    ... )
    >>> await dedup_store.register_file(workspace_id, sha256, metadata)
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.domain.value_objects import SHA256Hash


@dataclass(frozen=True)
class FileMetadata:
    """Metadata for deduplicated file.

    Represents essential information about an existing file in the workspace,
    returned when a duplicate upload is detected.

    Attributes:
        file_id: Unique identifier of the file on S3
        s3_path: Full S3 path (workspace_{id}/file_id.pdf)
        size: File size in bytes
        uploaded_at: UTC timestamp when file was successfully uploaded

    Example:
        >>> from datetime import datetime, timezone
        >>> from uuid import uuid4
        >>>
        >>> metadata = FileMetadata(
        ...     file_id=uuid4(),
        ...     s3_path="workspace_123/abc-def.pdf",
        ...     size=1048576,
        ...     uploaded_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        ... )
    """

    file_id: UUID
    s3_path: str
    size: int
    uploaded_at: datetime

    def __post_init__(self) -> None:
        """Validate field values after construction."""
        if self.size < 0:
            raise ValueError(f"size must be non-negative, got {self.size}")
        if not isinstance(self.size, int):
            raise ValueError(f"size must be integer, got {type(self.size).__name__}")
        if self.uploaded_at.tzinfo is None:
            raise ValueError("uploaded_at must be timezone-aware")
        if not self.s3_path or not self.s3_path.strip():
            raise ValueError("s3_path cannot be empty")


class IDeduplicationStore(Protocol):
    """Protocol for deduplication storage operations.

    Defines the interface for workspace-scoped duplicate detection using
    SHA-256 file fingerprints. Implementations must provide O(1) lookup
    and atomic registration operations.

    Thread Safety:
        All methods must be async-safe and support concurrent access.

    Error Handling:
        Infrastructure errors must be raised as InfrastructureError.
        Serialization errors must be raised as SerializationError.

    Workspace Isolation:
        Same SHA-256 checksum in different workspaces is NOT duplicate.
        Each workspace maintains its own set of fingerprints.

    Implementation Requirements:
        - check_duplicate must be O(1) or better
        - register_file must be atomic
        - No TTL on entries (files are immutable)
        - Must survive service restarts

    Integration Points:
        - Story 5.2: Receives SHA-256 after file assembly
        - Story 5.8: Orchestrates check before virus scan
        - Story 6.1: Metrics for duplicate detection rate

    Example Implementation:
        >>> class RedisDeduplicationStore:
        ...     def __init__(self, redis_client):
        ...         self._redis = redis_client
        ...
        ...     async def check_duplicate(self, workspace_id, sha256):
        ...         key = f"dedup:workspace_{workspace_id}"
        ...         exists = await self._redis.hexists(key, str(sha256))
        ...         if not exists:
        ...             return None
        ...         metadata_json = await self._redis.hget(key, str(sha256))
        ...         return deserialize(metadata_json)
        ...
        ...     async def register_file(self, workspace_id, sha256, metadata):
        ...         key = f"dedup:workspace_{workspace_id}"
        ...         await self._redis.hset(key, str(sha256), serialize(metadata))
    """

    async def check_duplicate(self, workspace_id: UUID, sha256: SHA256Hash) -> FileMetadata | None:
        """Check if file with SHA-256 exists in workspace.

        Performs workspace-scoped duplicate detection by looking up the SHA-256
        fingerprint in the workspace's storage. Returns metadata if file exists,
        None if file is new.

        Args:
            workspace_id: Workspace to check within
            sha256: SHA-256 checksum of file to check

        Returns:
            FileMetadata if file exists (duplicate found)
            None if file does not exist (not a duplicate)

        Raises:
            InfrastructureError: If storage system is unavailable
            SerializationError: If stored metadata is corrupted

        Example:
            >>> workspace_id = uuid4()
            >>> sha256 = SHA256Hash("a" * 64)
            >>> metadata = await store.check_duplicate(workspace_id, sha256)
            >>> if metadata:
            ...     print(f"Found duplicate: {metadata.file_id}")
            ... else:
            ...     print("File is unique")
        """
        ...

    async def register_file(
        self, workspace_id: UUID, sha256: SHA256Hash, metadata: FileMetadata
    ) -> None:
        """Register file fingerprint after successful upload.

        Stores the SHA-256 fingerprint and associated metadata for future
        duplicate detection. Should be called only after file assembly,
        virus scan, and event publication succeed.

        This operation is idempotent - registering the same fingerprint
        multiple times is safe (last write wins).

        Args:
            workspace_id: Workspace owning the file
            sha256: SHA-256 checksum of file
            metadata: File metadata (file_id, s3_path, size, uploaded_at)

        Raises:
            InfrastructureError: If storage system is unavailable

        Note:
            No TTL is set on entries. Files on bronze layer are immutable,
            so fingerprints remain valid indefinitely.

        Example:
            >>> workspace_id = uuid4()
            >>> sha256 = SHA256Hash("a" * 64)
            >>> metadata = FileMetadata(
            ...     file_id=uuid4(),
            ...     s3_path="workspace_123/abc.pdf",
            ...     size=1024,
            ...     uploaded_at=datetime.now(timezone.utc)
            ... )
            >>> await store.register_file(workspace_id, sha256, metadata)
        """
        ...
