"""Redis implementation of deduplication store protocol.

This module implements the IDeduplicationStore protocol using Redis Hashes
for O(1) duplicate detection and atomic fingerprint registration.

Key Features:
    - Workspace-scoped isolation (one Hash per workspace)
    - O(1) duplicate check via HEXISTS
    - O(1) metadata retrieval via HGET
    - Atomic registration via HSET
    - No TTL (files are immutable on bronze layer)
    - JSON serialization for FileMetadata

Storage Format:
    - Data Structure: Redis Hash
    - Key Pattern: dedup:workspace_{workspace_id}
    - Hash Field: SHA-256 checksum (64-char hex string)
    - Hash Value: JSON {file_id, s3_path, size, uploaded_at}

Key Design Decisions:
    - Hash structure enables O(1) lookup by SHA-256
    - No TTL: Files on bronze layer are immutable, fingerprints persist forever
    - Workspace isolation: Same SHA-256 in different workspace = NOT duplicate
    - Idempotent registration: HSET can be called multiple times safely

Integration Points:
    - Story 2.3: Uses dedup_key() from key_builder for workspace isolation
    - Story 5.1: Implements IDeduplicationStore protocol
    - Story 5.8: Used by CompleteUploadUseCase for deduplication

Examples:
    >>> import redis.asyncio as aioredis
    >>> from uuid import uuid4
    >>> from datetime import datetime, timezone
    >>>
    >>> # Initialize Redis client and dedup store
    >>> redis_client = aioredis.from_url("redis://localhost:6379")
    >>> store = RedisDeduplicationStore(redis_client)
    >>>
    >>> # Check for duplicate
    >>> workspace_id = uuid4()
    >>> sha256 = SHA256Hash("a" * 64)
    >>> metadata = await store.check_duplicate(workspace_id, sha256)
    >>> if metadata:
    ...     print(f"Duplicate found: {metadata.file_id}")
    ... else:
    ...     print("File is unique")
    >>>
    >>> # Register new file fingerprint
    >>> metadata = FileMetadata(
    ...     file_id=uuid4(),
    ...     s3_path="workspace_123/abc.pdf",
    ...     size=1024,
    ...     uploaded_at=datetime.now(timezone.utc)
    ... )
    >>> await store.register_file(workspace_id, sha256, metadata)
    >>>
    >>> # Subsequent check will return metadata
    >>> result = await store.check_duplicate(workspace_id, sha256)
    >>> assert result is not None
    >>> assert result.file_id == metadata.file_id
"""

import asyncio
import json
import logging
from datetime import datetime
from uuid import UUID

import redis.asyncio as aioredis
import redis.exceptions

from src.domain.exceptions import InfrastructureError, SerializationError
from src.domain.protocols.deduplication_store import FileMetadata
from src.domain.value_objects import SHA256Hash
from src.infrastructure.redis.key_builder import dedup_key


logger = logging.getLogger(__name__)


class RedisDeduplicationStore:
    """Redis implementation of deduplication store.

    Stores file fingerprints as workspace-scoped Redis Hashes.
    Each workspace has one Hash containing SHA-256 → metadata mappings.

    Performance Characteristics:
        - check_duplicate: O(1) via HEXISTS + HGET
        - register_file: O(1) via HSET
        - Memory: ~264 bytes per file (64-byte SHA + 200-byte JSON)
        - Scale: 10,000 files = ~2.6 MB per workspace

    Thread Safety:
        All Redis operations are atomic. Safe for concurrent access
        from multiple service instances.

    Error Handling:
        - Redis connection errors → InfrastructureError
        - JSON deserialization errors → SerializationError
        - Invalid data format → SerializationError

    Args:
        redis_client: Async Redis connection

    Examples:
        >>> import redis.asyncio as aioredis
        >>> redis_client = aioredis.from_url("redis://localhost:6379")
        >>> store = RedisDeduplicationStore(redis_client)
        >>>
        >>> # Check and register workflow
        >>> workspace_id = uuid4()
        >>> sha256 = SHA256Hash("b" * 64)
        >>>
        >>> # Check returns None for new files
        >>> result = await store.check_duplicate(workspace_id, sha256)
        >>> assert result is None
        >>>
        >>> # Register fingerprint
        >>> metadata = FileMetadata(
        ...     file_id=uuid4(),
        ...     s3_path="workspace_abc/file.pdf",
        ...     size=2048,
        ...     uploaded_at=datetime.now(timezone.utc)
        ... )
        >>> await store.register_file(workspace_id, sha256, metadata)
        >>>
        >>> # Check returns metadata for existing files
        >>> result = await store.check_duplicate(workspace_id, sha256)
        >>> assert result.file_id == metadata.file_id
    """

    def __init__(self, redis_client: aioredis.Redis) -> None:
        """Initialize Redis deduplication store.

        Args:
            redis_client: Async Redis connection

        Raises:
            TypeError: If redis_client is None

        Example:
            >>> import redis.asyncio as aioredis
            >>> client = aioredis.from_url("redis://localhost:6379")
            >>> store = RedisDeduplicationStore(client)
        """
        if redis_client is None:
            raise TypeError("redis_client cannot be None")

        self._redis = redis_client

    async def check_duplicate(self, workspace_id: UUID, sha256: SHA256Hash) -> FileMetadata | None:
        """Check if file with SHA-256 exists in workspace.

        Performs workspace-scoped duplicate detection using Redis Hash lookup.
        Returns metadata if file exists, None if file is new.

        Redis Operations:
            1. HEXISTS dedup:workspace_{id} {sha256} - Check existence (O(1))
            2. HGET dedup:workspace_{id} {sha256} - Retrieve metadata if exists (O(1))

        Race Condition Handling:
            If key is deleted between HEXISTS and HGET, returns None gracefully.

        Args:
            workspace_id: Workspace to check within
            sha256: SHA-256 checksum of file to check

        Returns:
            FileMetadata if duplicate found, None otherwise

        Raises:
            InfrastructureError: If Redis unavailable
            SerializationError: If stored metadata is corrupted

        Examples:
            >>> workspace_id = uuid4()
            >>> sha256 = SHA256Hash("c" * 64)
            >>>
            >>> # New file returns None
            >>> result = await store.check_duplicate(workspace_id, sha256)
            >>> assert result is None
            >>>
            >>> # After registration, returns metadata
            >>> await store.register_file(workspace_id, sha256, metadata)
            >>> result = await store.check_duplicate(workspace_id, sha256)
            >>> assert result.file_id == metadata.file_id
        """
        try:
            key = dedup_key(workspace_id)
            if sha256 is None:
                raise ValueError("sha256 cannot be None")
            sha256_str = str(sha256)

            # Check if fingerprint exists (O(1)) with timeout
            exists = await asyncio.wait_for(
                self._redis.hexists(key, sha256_str),  # type: ignore[arg-type]
                timeout=5.0,
            )
            if not exists:
                return None

            # Retrieve metadata (O(1)) with timeout
            metadata_json = await asyncio.wait_for(
                self._redis.hget(key, sha256_str),  # type: ignore[arg-type]
                timeout=5.0,
            )
            if not metadata_json or (isinstance(metadata_json, bytes) and metadata_json == b""):
                # Race condition: key deleted between HEXISTS and HGET
                # Or empty bytes stored (corrupted data)
                # Return None gracefully (file will be treated as unique)
                return None

            return self._deserialize_metadata(metadata_json)

        except redis.exceptions.RedisError as e:
            # Redis connection, timeout, or other infrastructure failure
            raise InfrastructureError(
                f"Deduplication check failed for workspace {workspace_id}: {e}"
            ) from e

    async def register_file(
        self, workspace_id: UUID, sha256: SHA256Hash, metadata: FileMetadata
    ) -> None:
        """Register file fingerprint after successful upload.

        Stores SHA-256 fingerprint and metadata in workspace-scoped Hash.
        Called only after file assembly, virus scan, and event publication succeed.

        Redis Operations:
            1. HSET dedup:workspace_{id} {sha256} {json} - Store metadata (O(1))
            No TTL set - files are immutable, fingerprints persist forever

        Idempotency:
            Safe to call multiple times with same fingerprint.
            HSET overwrites existing value (last write wins).

        Args:
            workspace_id: Workspace owning the file
            sha256: SHA-256 checksum of file
            metadata: File metadata to store

        Raises:
            InfrastructureError: If Redis unavailable

        Examples:
            >>> workspace_id = uuid4()
            >>> sha256 = SHA256Hash("d" * 64)
            >>> metadata = FileMetadata(
            ...     file_id=uuid4(),
            ...     s3_path="workspace_xyz/file.pdf",
            ...     size=4096,
            ...     uploaded_at=datetime.now(timezone.utc)
            ... )
            >>>
            >>> # Register fingerprint
            >>> await store.register_file(workspace_id, sha256, metadata)
            >>>
            >>> # Idempotent - can register again safely
            >>> await store.register_file(workspace_id, sha256, metadata)
        """
        try:
            key = dedup_key(workspace_id)
            if sha256 is None:
                raise ValueError("sha256 cannot be None")
            sha256_str = str(sha256)
            metadata_json = self._serialize_metadata(metadata)

            # Store fingerprint (no TTL - files are immutable) with timeout
            await asyncio.wait_for(
                self._redis.hset(key, sha256_str, metadata_json),  # type: ignore[arg-type]
                timeout=5.0,
            )

            logger.debug(
                "File fingerprint registered in Redis",
                extra={
                    "workspace_id": str(workspace_id),
                    "sha256": sha256_str,
                    "file_id": str(metadata.file_id),
                },
            )

        except redis.exceptions.RedisError as e:
            # Redis connection, timeout, or other infrastructure failure
            raise InfrastructureError(
                f"Fingerprint registration failed for workspace {workspace_id}: {e}"
            ) from e

    def _serialize_metadata(self, metadata: FileMetadata) -> str:
        """Serialize FileMetadata to JSON string for Redis storage.

        Converts FileMetadata dataclass to JSON with ISO 8601 datetime format.
        Datetime is stored with 'Z' suffix (UTC) per Architecture.md standards.

        Args:
            metadata: FileMetadata to serialize

        Returns:
            JSON string

        Format:
            {
                "file_id": "uuid-string",
                "s3_path": "workspace_{id}/file.ext",
                "size": 1024,
                "uploaded_at": "2026-05-06T12:00:00.123456Z"
            }

        Example:
            >>> metadata = FileMetadata(
            ...     file_id=UUID("12345678-1234-1234-1234-123456789abc"),
            ...     s3_path="workspace_123/abc.pdf",
            ...     size=1024,
            ...     uploaded_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
            ... )
            >>> json_str = store._serialize_metadata(metadata)
            >>> assert '"file_id": "12345678-1234-1234-1234-123456789abc"' in json_str
        """
        # Validate metadata fields before serialization
        if metadata.file_id is None:
            raise ValueError("metadata.file_id cannot be None")
        if metadata.s3_path is None:
            raise ValueError("metadata.s3_path cannot be None")
        if metadata.uploaded_at is None:
            raise ValueError("metadata.uploaded_at cannot be None")
        if metadata.uploaded_at.tzinfo is None:
            raise ValueError("metadata.uploaded_at must be timezone-aware")

        return json.dumps(
            {
                "file_id": str(metadata.file_id),
                "s3_path": metadata.s3_path,
                "size": metadata.size,
                "uploaded_at": metadata.uploaded_at.isoformat().replace("+00:00", "Z"),
            }
        )

    def _deserialize_metadata(self, metadata_json: bytes | str) -> FileMetadata:
        """Deserialize JSON string to FileMetadata.

        Converts JSON from Redis to FileMetadata dataclass.
        Handles both bytes and string input (Redis may return either).

        Args:
            metadata_json: JSON string or bytes from Redis

        Returns:
            FileMetadata dataclass

        Raises:
            SerializationError: If JSON is invalid or missing required fields

        Format:
            {
                "file_id": "uuid-string",
                "s3_path": "workspace_{id}/file.ext",
                "size": 1024,
                "uploaded_at": "2026-05-06T12:00:00.123456Z"
            }

        Example:
            >>> json_str = '{"file_id": "12345678-1234-1234-1234-123456789abc", "s3_path": "workspace_123/abc.pdf", "size": 1024, "uploaded_at": "2026-05-01T12:00:00Z"}'
            >>> metadata = store._deserialize_metadata(json_str)
            >>> assert isinstance(metadata, FileMetadata)
        """
        try:
            # Handle bytes or string input
            if isinstance(metadata_json, bytes):
                metadata_json = metadata_json.decode("utf-8")

            # Parse JSON
            data = json.loads(metadata_json)

            # Construct FileMetadata with type conversions
            metadata = FileMetadata(
                file_id=UUID(data["file_id"]),
                s3_path=data["s3_path"],
                size=data["size"],
                uploaded_at=datetime.fromisoformat(data["uploaded_at"].replace("Z", "+00:00")),
            )

            # Post-deserialization validation
            if metadata.size < 0:
                raise SerializationError(f"Deserialized size is negative: {metadata.size}")
            if not isinstance(metadata.size, int):
                raise SerializationError(
                    f"Deserialized size is not an integer: {type(metadata.size).__name__}"
                )

            return metadata

        except (json.JSONDecodeError, KeyError, ValueError, TypeError, UnicodeDecodeError) as e:
            # JSON parse error, missing field, invalid UUID, or invalid datetime
            raise SerializationError(f"Failed to deserialize file metadata: {e}") from e
