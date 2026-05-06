"""Integration tests for RedisDeduplicationStore with real Redis.

These tests require a running Redis instance (e.g., via Docker Compose).
Run: docker-compose up -d redis

Tests verify:
- Duplicate detection with real Redis
- Fingerprint registration persistence
- Workspace isolation
- Serialization/deserialization correctness
- Error handling with unavailable Redis
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import redis.asyncio as aioredis

from src.domain.exceptions import SerializationError
from src.domain.protocols.deduplication_store import FileMetadata
from src.domain.value_objects import SHA256Hash
from src.infrastructure.redis.deduplication_store import RedisDeduplicationStore


# Redis connection URL for integration tests
REDIS_TEST_URL = "redis://localhost:6379/1"  # Use DB 1 for tests


@pytest.fixture
async def redis_client() -> AsyncGenerator[aioredis.Redis]:
    """Create Redis client for integration tests.

    Connects to Redis instance at localhost:6379 (DB 1).
    Requires Redis to be running (e.g., via docker-compose up -d redis).

    Yields:
        Redis client connected to test database

    Cleanup:
        Flushes test database and closes connection
    """
    client = aioredis.from_url(REDIS_TEST_URL, decode_responses=False)

    try:
        # Verify Redis is accessible
        await client.ping()
    except Exception as e:
        pytest.skip(f"Redis not available: {e}")

    yield client

    # Cleanup: flush test DB after tests
    await client.flushdb()
    await client.aclose()


@pytest.fixture
def dedup_store(redis_client: aioredis.Redis) -> RedisDeduplicationStore:
    """Create RedisDeduplicationStore with real Redis client.

    Args:
        redis_client: Redis client fixture

    Returns:
        RedisDeduplicationStore instance for testing
    """
    return RedisDeduplicationStore(redis_client)


@pytest.fixture
def workspace_id() -> str:
    """Generate test workspace ID.

    Returns:
        Random UUID for workspace
    """
    return uuid4()


@pytest.fixture
def sha256() -> SHA256Hash:
    """Generate test SHA-256 checksum.

    Returns:
        Valid SHA256Hash for testing
    """
    return SHA256Hash("a" * 64)


@pytest.fixture
def file_metadata() -> FileMetadata:
    """Create test file metadata.

    Returns:
        FileMetadata with realistic test data
    """
    return FileMetadata(
        file_id=uuid4(),
        s3_path="workspace_123/abc-def.pdf",
        size=1024,
        uploaded_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
    )


class TestCheckDuplicateNotFound:
    """Integration tests for checking duplicates when file is new."""

    @pytest.mark.asyncio
    async def test_check_duplicate_returns_none_for_new_file(
        self,
        dedup_store: RedisDeduplicationStore,
        workspace_id: str,
        sha256: SHA256Hash,
    ) -> None:
        """Test check_duplicate returns None when file doesn't exist.

        Given a workspace with no registered files
        When check_duplicate is called
        Then None is returned (file is unique)
        """
        # Act
        result = await dedup_store.check_duplicate(workspace_id, sha256)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_check_duplicate_returns_none_for_nonexistent_workspace(
        self,
        dedup_store: RedisDeduplicationStore,
        sha256: SHA256Hash,
    ) -> None:
        """Test check_duplicate returns None for workspace that never uploaded.

        Given a workspace_id that has never uploaded any files
        When check_duplicate is called
        Then None is returned (workspace key doesn't exist)
        """
        # Arrange
        nonexistent_workspace = uuid4()

        # Act
        result = await dedup_store.check_duplicate(nonexistent_workspace, sha256)

        # Assert
        assert result is None


class TestRegisterAndCheckDuplicate:
    """Integration tests for registering files and checking duplicates."""

    @pytest.mark.asyncio
    async def test_register_file_creates_redis_entry(
        self,
        dedup_store: RedisDeduplicationStore,
        workspace_id: str,
        sha256: SHA256Hash,
        file_metadata: FileMetadata,
    ) -> None:
        """Test register_file persists data to Redis.

        Given workspace, SHA-256, and file metadata
        When register_file is called
        Then data is persisted in Redis Hash
        """
        # Act
        await dedup_store.register_file(workspace_id, sha256, file_metadata)

        # Assert - subsequent check should return metadata
        result = await dedup_store.check_duplicate(workspace_id, sha256)
        assert result is not None
        assert result.file_id == file_metadata.file_id
        assert result.s3_path == file_metadata.s3_path
        assert result.size == file_metadata.size
        assert result.uploaded_at == file_metadata.uploaded_at

    @pytest.mark.asyncio
    async def test_check_duplicate_returns_metadata_after_registration(
        self,
        dedup_store: RedisDeduplicationStore,
        workspace_id: str,
        sha256: SHA256Hash,
        file_metadata: FileMetadata,
    ) -> None:
        """Test check_duplicate returns correct metadata for registered file.

        Given a registered file
        When check_duplicate is called
        Then FileMetadata is returned with correct values
        """
        # Arrange
        await dedup_store.register_file(workspace_id, sha256, file_metadata)

        # Act
        result = await dedup_store.check_duplicate(workspace_id, sha256)

        # Assert
        assert result is not None
        assert result.file_id == file_metadata.file_id
        assert result.s3_path == file_metadata.s3_path
        assert result.size == file_metadata.size
        assert result.uploaded_at == file_metadata.uploaded_at

    @pytest.mark.asyncio
    async def test_register_file_is_idempotent(
        self,
        dedup_store: RedisDeduplicationStore,
        workspace_id: str,
        sha256: SHA256Hash,
        file_metadata: FileMetadata,
    ) -> None:
        """Test register_file can be called multiple times safely.

        Given a file already registered
        When register_file is called again with same data
        Then operation succeeds without error (idempotent)
        """
        # Arrange
        await dedup_store.register_file(workspace_id, sha256, file_metadata)

        # Act - register again (should not raise error)
        await dedup_store.register_file(workspace_id, sha256, file_metadata)

        # Assert - metadata still correct
        result = await dedup_store.check_duplicate(workspace_id, sha256)
        assert result is not None
        assert result.file_id == file_metadata.file_id


class TestWorkspaceIsolation:
    """Integration tests for workspace-scoped isolation."""

    @pytest.mark.asyncio
    async def test_same_sha256_in_different_workspaces_not_duplicate(
        self,
        dedup_store: RedisDeduplicationStore,
        sha256: SHA256Hash,
    ) -> None:
        """Test same SHA-256 in different workspaces is NOT duplicate.

        Given the same file uploaded to two different workspaces
        When checking for duplicates in each workspace
        Then each workspace returns its own metadata independently
        """
        # Arrange
        workspace_a = uuid4()
        workspace_b = uuid4()

        metadata_a = FileMetadata(
            file_id=uuid4(),
            s3_path=f"workspace_{workspace_a}/file_a.pdf",
            size=1024,
            uploaded_at=datetime.now(UTC),
        )
        metadata_b = FileMetadata(
            file_id=uuid4(),
            s3_path=f"workspace_{workspace_b}/file_b.pdf",
            size=2048,
            uploaded_at=datetime.now(UTC),
        )

        # Act - register same SHA-256 in both workspaces
        await dedup_store.register_file(workspace_a, sha256, metadata_a)
        await dedup_store.register_file(workspace_b, sha256, metadata_b)

        # Assert - each workspace has its own metadata
        result_a = await dedup_store.check_duplicate(workspace_a, sha256)
        result_b = await dedup_store.check_duplicate(workspace_b, sha256)

        assert result_a is not None
        assert result_a.file_id == metadata_a.file_id
        assert result_a.s3_path == metadata_a.s3_path
        assert result_a.size == 1024

        assert result_b is not None
        assert result_b.file_id == metadata_b.file_id
        assert result_b.s3_path == metadata_b.s3_path
        assert result_b.size == 2048

    @pytest.mark.asyncio
    async def test_different_sha256_in_same_workspace_both_unique(
        self,
        dedup_store: RedisDeduplicationStore,
        workspace_id: str,
        file_metadata: FileMetadata,
    ) -> None:
        """Test different SHA-256 checksums in same workspace are independent.

        Given two different files in the same workspace
        When registered with different SHA-256 checksums
        Then both are stored independently without collision
        """
        # Arrange
        sha256_a = SHA256Hash("a" * 64)
        sha256_b = SHA256Hash("b" * 64)

        metadata_a = FileMetadata(
            file_id=uuid4(),
            s3_path="workspace_123/file_a.pdf",
            size=1024,
            uploaded_at=datetime.now(UTC),
        )
        metadata_b = FileMetadata(
            file_id=uuid4(),
            s3_path="workspace_123/file_b.pdf",
            size=2048,
            uploaded_at=datetime.now(UTC),
        )

        # Act
        await dedup_store.register_file(workspace_id, sha256_a, metadata_a)
        await dedup_store.register_file(workspace_id, sha256_b, metadata_b)

        # Assert - both are retrievable independently
        result_a = await dedup_store.check_duplicate(workspace_id, sha256_a)
        result_b = await dedup_store.check_duplicate(workspace_id, sha256_b)

        assert result_a is not None
        assert result_a.file_id == metadata_a.file_id

        assert result_b is not None
        assert result_b.file_id == metadata_b.file_id


class TestSerializationRoundtrip:
    """Integration tests for metadata serialization/deserialization."""

    @pytest.mark.asyncio
    async def test_datetime_serialization_preserves_timezone(
        self,
        dedup_store: RedisDeduplicationStore,
        workspace_id: str,
        sha256: SHA256Hash,
    ) -> None:
        """Test datetime with timezone survives round-trip.

        Given metadata with UTC datetime
        When stored and retrieved
        Then datetime is preserved with timezone info
        """
        # Arrange
        original_datetime = datetime(2026, 5, 5, 14, 30, 45, 123456, tzinfo=UTC)
        metadata = FileMetadata(
            file_id=uuid4(),
            s3_path="workspace_abc/file.pdf",
            size=4096,
            uploaded_at=original_datetime,
        )

        # Act
        await dedup_store.register_file(workspace_id, sha256, metadata)
        result = await dedup_store.check_duplicate(workspace_id, sha256)

        # Assert
        assert result is not None
        assert result.uploaded_at == original_datetime
        assert result.uploaded_at.tzinfo == UTC

    @pytest.mark.asyncio
    async def test_large_file_size_preserved(
        self,
        dedup_store: RedisDeduplicationStore,
        workspace_id: str,
        sha256: SHA256Hash,
    ) -> None:
        """Test large file sizes are preserved correctly.

        Given metadata with large file size (5 GB)
        When stored and retrieved
        Then size is preserved exactly
        """
        # Arrange
        large_size = 5 * 1024 * 1024 * 1024  # 5 GB
        metadata = FileMetadata(
            file_id=uuid4(),
            s3_path="workspace_xyz/large-file.zip",
            size=large_size,
            uploaded_at=datetime.now(UTC),
        )

        # Act
        await dedup_store.register_file(workspace_id, sha256, metadata)
        result = await dedup_store.check_duplicate(workspace_id, sha256)

        # Assert
        assert result is not None
        assert result.size == large_size

    @pytest.mark.asyncio
    async def test_special_characters_in_s3_path_preserved(
        self,
        dedup_store: RedisDeduplicationStore,
        workspace_id: str,
        sha256: SHA256Hash,
    ) -> None:
        """Test s3_path with special characters survives round-trip.

        Given metadata with special characters in s3_path
        When stored and retrieved
        Then path is preserved exactly
        """
        # Arrange
        special_path = "workspace_abc/files/test (copy) [2026-05-01].pdf"
        metadata = FileMetadata(
            file_id=uuid4(),
            s3_path=special_path,
            size=2048,
            uploaded_at=datetime.now(UTC),
        )

        # Act
        await dedup_store.register_file(workspace_id, sha256, metadata)
        result = await dedup_store.check_duplicate(workspace_id, sha256)

        # Assert
        assert result is not None
        assert result.s3_path == special_path


class TestErrorHandling:
    """Integration tests for error handling scenarios."""

    @pytest.mark.asyncio
    async def test_corrupted_metadata_raises_serialization_error(
        self,
        dedup_store: RedisDeduplicationStore,
        redis_client: aioredis.Redis,
        workspace_id: str,
        sha256: SHA256Hash,
    ) -> None:
        """Test corrupted JSON in Redis raises SerializationError.

        Given corrupted metadata in Redis
        When check_duplicate is called
        Then SerializationError is raised
        """
        # Arrange - manually insert invalid JSON
        from src.infrastructure.redis.key_builder import dedup_key

        key = dedup_key(workspace_id)
        await redis_client.hset(key, str(sha256), b"not-valid-json{{{")

        # Act & Assert
        with pytest.raises(SerializationError):
            await dedup_store.check_duplicate(workspace_id, sha256)

    @pytest.mark.asyncio
    async def test_missing_field_in_metadata_raises_serialization_error(
        self,
        dedup_store: RedisDeduplicationStore,
        redis_client: aioredis.Redis,
        workspace_id: str,
        sha256: SHA256Hash,
    ) -> None:
        """Test metadata missing required field raises SerializationError.

        Given JSON metadata missing 'file_id' field
        When check_duplicate is called
        Then SerializationError is raised
        """
        # Arrange - manually insert incomplete JSON
        from src.infrastructure.redis.key_builder import dedup_key

        key = dedup_key(workspace_id)
        incomplete_json = '{"s3_path": "test.pdf", "size": 1024}'  # Missing file_id
        await redis_client.hset(key, str(sha256), incomplete_json)

        # Act & Assert
        with pytest.raises(SerializationError):
            await dedup_store.check_duplicate(workspace_id, sha256)

    @pytest.mark.asyncio
    async def test_negative_file_size_rejected(
        self,
        dedup_store: RedisDeduplicationStore,
        workspace_id: str,
        sha256: SHA256Hash,
    ) -> None:
        """Test negative file size is rejected during registration."""
        with pytest.raises(ValueError, match="size must be non-negative"):
            FileMetadata(
                file_id=uuid4(),
                s3_path="workspace_123/file.pdf",
                size=-1024,
                uploaded_at=datetime.now(UTC),
            )

    @pytest.mark.asyncio
    async def test_naive_datetime_rejected(
        self,
        dedup_store: RedisDeduplicationStore,
        workspace_id: str,
        sha256: SHA256Hash,
    ) -> None:
        """Test timezone-naive datetime is rejected."""
        with pytest.raises(ValueError, match="timezone-aware"):
            FileMetadata(
                file_id=uuid4(),
                s3_path="workspace_123/file.pdf",
                size=1024,
                uploaded_at=datetime(2026, 5, 1, 12, 0, 0),  # No tzinfo
            )

    @pytest.mark.asyncio
    async def test_empty_bytes_from_redis(
        self,
        dedup_store: RedisDeduplicationStore,
        redis_client: aioredis.Redis,
        workspace_id: str,
        sha256: SHA256Hash,
    ) -> None:
        """Test empty bytes (b'') from Redis returns None."""
        from src.infrastructure.redis.key_builder import dedup_key

        key = dedup_key(workspace_id)
        await redis_client.hset(key, str(sha256), b"")
        result = await dedup_store.check_duplicate(workspace_id, sha256)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_utf8_data_raises_serialization_error(
        self,
        dedup_store: RedisDeduplicationStore,
        redis_client: aioredis.Redis,
        workspace_id: str,
        sha256: SHA256Hash,
    ) -> None:
        """Test non-UTF-8 bytes in Redis raises SerializationError."""
        from src.infrastructure.redis.key_builder import dedup_key

        key = dedup_key(workspace_id)
        await redis_client.hset(key, str(sha256), b"\xff\xfe invalid utf8")
        with pytest.raises(SerializationError):
            await dedup_store.check_duplicate(workspace_id, sha256)

    @pytest.mark.asyncio
    async def test_float_size_rejected(
        self,
        dedup_store: RedisDeduplicationStore,
        redis_client: aioredis.Redis,
        workspace_id: str,
        sha256: SHA256Hash,
    ) -> None:
        """Test float size value is rejected during deserialization."""
        from src.infrastructure.redis.key_builder import dedup_key

        key = dedup_key(workspace_id)
        json_with_float = '{"file_id": "12345678-1234-1234-1234-123456789abc", "s3_path": "test.pdf", "size": 1024.5, "uploaded_at": "2026-05-01T12:00:00Z"}'
        await redis_client.hset(key, str(sha256), json_with_float)
        with pytest.raises((SerializationError, ValueError)):
            await dedup_store.check_duplicate(workspace_id, sha256)
