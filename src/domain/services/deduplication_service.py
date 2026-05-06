"""Deduplication service for workspace-scoped file fingerprint detection.

This service coordinates duplicate file detection by checking SHA-256 fingerprints
against workspace-specific storage. Prevents redundant storage and processing of
identical files within a workspace.

Architecture Position:
    Domain Layer - Pure business logic with no infrastructure dependencies.
    Infrastructure implementations inject IDeduplicationStore protocol.

Integration:
    - Story 5.2: Receives final SHA-256 after file assembly
    - Story 5.8: Orchestrates check before virus scan, register after event publish
    - Story 6.1: Instrumented with deduplication metrics

Security:
    - Workspace isolation: Same SHA-256 in different workspace = NOT duplicate
    - Tenant boundary enforcement (NFR-S5)

Performance:
    - check_for_duplicate: O(1) lookup via Redis HEXISTS
    - register_upload: O(1) insert via Redis HSET
    - Hot path: No logging on non-duplicate (log only duplicates)

Examples:
    >>> from uuid import uuid4
    >>> from datetime import datetime, timezone
    >>>
    >>> # Initialize service with store implementation
    >>> service = DeduplicationService(dedup_store)
    >>>
    >>> # Check for duplicate during upload completion
    >>> workspace_id = uuid4()
    >>> sha256 = SHA256Hash("a" * 64)
    >>> try:
    ...     await service.check_for_duplicate(workspace_id, sha256)
    ... except DuplicateFileError as e:
    ...     # File already exists - return 409 to client
    ...     return {
    ...         "error": "DUPLICATE_FILE",
    ...         "existing_file_id": str(e.existing_file_id),
    ...         "existing_s3_path": e.existing_s3_path,
    ...         "uploaded_at": e.uploaded_at.isoformat()
    ...     }
    >>>
    >>> # Register fingerprint after successful upload
    >>> metadata = FileMetadata(
    ...     file_id=uuid4(),
    ...     s3_path="workspace_123/abc.pdf",
    ...     size=1024,
    ...     uploaded_at=datetime.now(timezone.utc)
    ... )
    >>> await service.register_upload(workspace_id, sha256, metadata)
"""

from __future__ import annotations

from uuid import UUID

import structlog

from src.domain.exceptions import DuplicateFileError
from src.domain.protocols.deduplication_store import (
    FileMetadata,
    IDeduplicationStore,
)
from src.domain.value_objects import SHA256Hash


logger = structlog.get_logger()


class DeduplicationService:
    """Service for workspace-scoped file deduplication.

    Coordinates duplicate detection and fingerprint registration using
    SHA-256 checksums. Enforces workspace isolation (same file in different
    workspace is NOT considered duplicate).

    This service is a thin coordination layer over IDeduplicationStore.
    It adds logging and converts storage responses to domain exceptions.

    Thread Safety:
        Safe for concurrent access. All operations are delegated to the
        async-safe IDeduplicationStore implementation.

    Args:
        store: Deduplication storage implementation (typically Redis)

    Examples:
        >>> from uuid import uuid4
        >>> service = DeduplicationService(redis_store)
        >>> workspace_id = uuid4()
        >>> sha256 = SHA256Hash("b94d27b9" + "0" * 56)
        >>>
        >>> # Will raise DuplicateFileError if file exists
        >>> await service.check_for_duplicate(workspace_id, sha256)
        >>>
        >>> # Register after successful upload
        >>> metadata = FileMetadata(
        ...     file_id=uuid4(),
        ...     s3_path="workspace_abc/file.pdf",
        ...     size=2048,
        ...     uploaded_at=datetime.now(timezone.utc)
        ... )
        >>> await service.register_upload(workspace_id, sha256, metadata)
    """

    def __init__(self, store: IDeduplicationStore) -> None:
        """Initialize deduplication service.

        Args:
            store: Deduplication storage implementation

        Raises:
            TypeError: If store is not provided or is None

        Example:
            >>> from src.infrastructure.redis.deduplication_store import RedisDeduplicationStore
            >>> redis_store = RedisDeduplicationStore(redis_client)
            >>> service = DeduplicationService(redis_store)
        """
        if store is None:
            raise TypeError("store cannot be None")

        self._store = store

    async def check_for_duplicate(self, workspace_id: UUID, sha256: SHA256Hash) -> None:
        """Check for duplicate and raise error if found.

        Called during upload completion, after file assembly but before
        virus scan. Raises DuplicateFileError if file already exists in
        workspace.

        Hot Path Optimization:
            - No logging when file is unique (expected common case)
            - Logs only when duplicate detected (rare, actionable)

        Args:
            workspace_id: Workspace to check within
            sha256: SHA-256 checksum of assembled file

        Raises:
            DuplicateFileError: If file with same SHA-256 exists in workspace
            InfrastructureError: If storage system is unavailable
            TypeError: If arguments are None or wrong type

        Timing:
            Story 5.8 orchestration sequence:
                1. Assemble file on S3 (Story 5.2)
                2. Validate full-file SHA-256
                3. → check_for_duplicate() ← (THIS METHOD)
                   - If duplicate: raise error → 409 to client
                4. Scan for virus (Story 5.3)
                5. Publish event (Story 5.5)
                6. register_upload() ← (below)

        Examples:
            >>> from uuid import uuid4
            >>> workspace_id = uuid4()
            >>> sha256 = SHA256Hash("a" * 64)
            >>>
            >>> # Unique file - returns silently
            >>> await service.check_for_duplicate(workspace_id, sha256)
            >>>
            >>> # Duplicate file - raises DuplicateFileError
            >>> try:
            ...     await service.check_for_duplicate(workspace_id, sha256)
            ... except DuplicateFileError as e:
            ...     print(f"Duplicate: {e.existing_file_id}")
        """
        # Input validation
        if workspace_id is None:
            raise TypeError("workspace_id cannot be None")
        if sha256 is None:
            raise TypeError("sha256 cannot be None")

        # Check for duplicate in workspace-scoped storage
        metadata = await self._store.check_duplicate(workspace_id, sha256)

        if metadata is not None:
            # Validate returned metadata is correct type
            if not isinstance(metadata, FileMetadata):
                raise TypeError(
                    f"store.check_duplicate returned {type(metadata).__name__}, expected FileMetadata"
                )
            # Duplicate found - log warning and raise domain exception
            logger.warning(
                "duplicate_file_detected",
                workspace_id=str(workspace_id),
                sha256=str(sha256),
                existing_file_id=str(metadata.file_id),
                existing_s3_path=metadata.s3_path,
                uploaded_at=metadata.uploaded_at.isoformat(),
            )
            raise DuplicateFileError(
                sha256_checksum=sha256,
                existing_file_id=metadata.file_id,
                existing_s3_path=metadata.s3_path,
                uploaded_at=metadata.uploaded_at,
            )

        # Not duplicate - return silently (hot path, no logging)

    async def register_upload(
        self, workspace_id: UUID, sha256: SHA256Hash, metadata: FileMetadata
    ) -> None:
        """Register file fingerprint after successful upload.

        Called after file assembly, virus scan, and event publication succeed.
        Registers SHA-256 fingerprint so future uploads can detect duplicate.

        This is the FINAL step in upload completion (Story 5.8 orchestration).
        Only called when all previous steps succeed.

        Args:
            workspace_id: Workspace owning the file
            sha256: SHA-256 checksum of file
            metadata: File metadata (file_id, s3_path, size, uploaded_at)

        Raises:
            InfrastructureError: If storage system is unavailable
            TypeError: If any argument is None or wrong type

        Timing:
            Story 5.8 orchestration sequence:
                1. Assemble file on S3
                2. Validate SHA-256
                3. check_for_duplicate() ← (above)
                4. Scan for virus
                5. Publish event
                6. → register_upload() ← (THIS METHOD, final step)
                7. Update session status to COMPLETE

        Idempotency:
            Safe to call multiple times with same fingerprint.
            Last write wins (Redis HSET behavior).

        Examples:
            >>> from uuid import uuid4
            >>> from datetime import datetime, timezone
            >>>
            >>> workspace_id = uuid4()
            >>> sha256 = SHA256Hash("b" * 64)
            >>> metadata = FileMetadata(
            ...     file_id=uuid4(),
            ...     s3_path="workspace_123/file.pdf",
            ...     size=2048,
            ...     uploaded_at=datetime.now(timezone.utc)
            ... )
            >>>
            >>> await service.register_upload(workspace_id, sha256, metadata)
        """
        # Input validation
        if workspace_id is None:
            raise TypeError("workspace_id cannot be None")
        if not isinstance(workspace_id, UUID):
            raise TypeError(f"workspace_id must be UUID, got {type(workspace_id).__name__}")
        if sha256 is None:
            raise TypeError("sha256 cannot be None")
        if not isinstance(sha256, SHA256Hash):
            raise TypeError(f"sha256 must be SHA256Hash, got {type(sha256).__name__}")
        if metadata is None:
            raise TypeError("metadata cannot be None")
        if not isinstance(metadata, FileMetadata):
            raise TypeError(f"metadata must be FileMetadata, got {type(metadata).__name__}")

        # Register fingerprint in workspace-scoped storage
        await self._store.register_file(workspace_id, sha256, metadata)

        # Log completion (registration happens once per successful upload)
        logger.info(
            "file_fingerprint_registered",
            workspace_id=str(workspace_id),
            sha256=str(sha256),
            file_id=str(metadata.file_id),
            s3_path=metadata.s3_path,
            size=metadata.size,
        )
