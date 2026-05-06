"""Unit tests for RedisSessionStore - Redis-backed session persistence.

Tests serialization, deserialization, error handling, and workspace isolation.
Uses mocked Redis client to test logic without external dependencies.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import redis.exceptions

from src.domain.entities import UploadSession
from src.domain.exceptions import (
    InfrastructureError,
    SerializationError,
    SessionNotFoundError,
)
from src.domain.value_objects import SessionStatus, SHA256Hash
from src.infrastructure.redis.session_store import RedisSessionStore


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Create mock Redis client for testing."""
    mock = AsyncMock()

    # Mock pipeline - pipeline() is NOT async in redis-py, it returns a pipeline object
    # The execute() method on the pipeline IS async
    mock_pipeline = MagicMock()
    mock_pipeline.hset.return_value = mock_pipeline  # Allow chaining
    mock_pipeline.expire.return_value = mock_pipeline  # Allow chaining
    mock_pipeline.execute = AsyncMock(return_value=[True, True])  # execute() IS async

    # Set pipeline as a regular (non-async) method
    mock.pipeline = MagicMock(return_value=mock_pipeline)

    return mock


@pytest.fixture
def session_store(mock_redis: AsyncMock) -> RedisSessionStore:
    """Create RedisSessionStore with mocked Redis client."""
    return RedisSessionStore(mock_redis)


@pytest.fixture
def sample_session() -> UploadSession:
    """Create a valid UploadSession for testing."""
    return UploadSession(
        session_id=uuid4(),
        workspace_id=uuid4(),
        filename="test-document.pdf",
        size=1024 * 1024,  # 1 MB
        mime_type="application/pdf",
        sha256_checksum=SHA256Hash("a" * 64),
        offset=0,
        status=SessionStatus.PENDING,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        chunk_manifest=[],
    )


class TestRedisSessionStoreCreation:
    """Tests for RedisSessionStore initialization."""

    def test_initialization(self, mock_redis: AsyncMock) -> None:
        """Test RedisSessionStore can be initialized with Redis client."""
        store = RedisSessionStore(mock_redis)

        assert store is not None
        assert store._redis == mock_redis
        assert store._ttl_seconds == 86400  # 24 hours

    def test_ttl_is_24_hours(self, session_store: RedisSessionStore) -> None:
        """Test TTL is set to 24 hours (86400 seconds)."""
        assert session_store._ttl_seconds == 86400


class TestCreateSession:
    """Tests for create_session method."""

    @pytest.mark.asyncio
    async def test_creates_session_with_correct_key_pattern(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test create_session uses correct key pattern."""
        await session_store.create_session(sample_session)

        expected_key = (
            f"session:workspace_{sample_session.workspace_id}:document_{sample_session.session_id}"
        )

        # Check pipeline was called
        mock_redis.pipeline.assert_called_once()
        pipeline = mock_redis.pipeline.return_value
        # Now expects 2 hset calls: one for session, one for expiry metadata (Story 4.1)
        assert pipeline.hset.call_count == 2
        # First call is for session data
        call_args = pipeline.hset.call_args_list[0]
        assert call_args[0][0] == expected_key

    @pytest.mark.asyncio
    async def test_stores_all_session_fields(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test create_session stores all UploadSession fields."""
        await session_store.create_session(sample_session)

        pipeline = mock_redis.pipeline.return_value
        # Story 4.1: Now creates two entries (session + expiry metadata)
        # First call is session data
        call_args = pipeline.hset.call_args_list[0]
        data = call_args[1]["mapping"]

        assert data["session_id"] == str(sample_session.session_id)
        assert data["workspace_id"] == str(sample_session.workspace_id)
        assert data["filename"] == sample_session.filename
        assert data["size"] == str(sample_session.size)
        assert data["mime_type"] == sample_session.mime_type
        assert data["sha256_checksum"] == sample_session.sha256_checksum.value
        assert data["offset"] == str(sample_session.offset)
        assert data["status"] == sample_session.status.value
        assert data["created_at"] == sample_session.created_at.isoformat()
        assert data["expires_at"] == sample_session.expires_at.isoformat()

    @pytest.mark.asyncio
    async def test_serializes_chunk_manifest_as_json(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test chunk_manifest is serialized as JSON string."""
        sample_session.chunk_manifest = [
            {"index": 0, "size": 1024, "checksum": "abc123"},
            {"index": 1, "size": 512, "checksum": "def456"},
        ]

        await session_store.create_session(sample_session)

        pipeline = mock_redis.pipeline.return_value
        # Story 4.1: First call is session data
        call_args = pipeline.hset.call_args_list[0]
        data = call_args[1]["mapping"]
        chunk_manifest_json = data["chunk_manifest"]

        # Verify it's valid JSON
        parsed = json.loads(chunk_manifest_json)
        assert parsed == sample_session.chunk_manifest

    @pytest.mark.asyncio
    async def test_sets_24_hour_ttl(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test create_session sets 24-hour TTL via pipeline."""
        await session_store.create_session(sample_session)

        expected_key = (
            f"session:workspace_{sample_session.workspace_id}:document_{sample_session.session_id}"
        )

        pipeline = mock_redis.pipeline.return_value
        # Story 4.1: Now expects 2 expire calls (session 24h, metadata 7d)
        assert pipeline.expire.call_count == 2
        # First expire call is for session (24 hours)
        pipeline.expire.call_args_list[0] = (expected_key, 86400)
        pipeline.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_infrastructure_error_on_redis_failure(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test create_session raises InfrastructureError on Redis failure."""
        # Make pipeline.execute() raise an error
        pipeline = mock_redis.pipeline.return_value
        pipeline.execute.side_effect = redis.exceptions.ConnectionError("Connection refused")

        with pytest.raises(InfrastructureError, match="Failed to create session"):
            await session_store.create_session(sample_session)

    @pytest.mark.asyncio
    async def test_handles_empty_chunk_manifest(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test empty chunk_manifest [] is serialized correctly."""
        sample_session.chunk_manifest = []

        await session_store.create_session(sample_session)

        pipeline = mock_redis.pipeline.return_value
        # Story 4.1: First call is session data
        call_args = pipeline.hset.call_args_list[0]
        data = call_args[1]["mapping"]
        chunk_manifest_json = data["chunk_manifest"]

        # Verify it's JSON array "[]"
        assert chunk_manifest_json == "[]"
        assert json.loads(chunk_manifest_json) == []


class TestGetSession:
    """Tests for get_session method."""

    @pytest.mark.asyncio
    async def test_retrieves_session_with_correct_key(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test get_session uses correct key pattern."""
        # Mock Redis return value
        redis_data = {
            b"session_id": str(sample_session.session_id).encode(),
            b"workspace_id": str(sample_session.workspace_id).encode(),
            b"filename": sample_session.filename.encode(),
            b"size": str(sample_session.size).encode(),
            b"mime_type": sample_session.mime_type.encode(),
            b"sha256_checksum": sample_session.sha256_checksum.value.encode(),
            b"offset": str(sample_session.offset).encode(),
            b"status": sample_session.status.value.encode(),
            b"created_at": sample_session.created_at.isoformat().encode(),
            b"expires_at": sample_session.expires_at.isoformat().encode(),
            b"chunk_manifest": json.dumps(sample_session.chunk_manifest).encode(),
        }
        mock_redis.hgetall.return_value = redis_data

        await session_store.get_session(sample_session.workspace_id, sample_session.session_id)

        expected_key = (
            f"session:workspace_{sample_session.workspace_id}:document_{sample_session.session_id}"
        )
        mock_redis.hgetall.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_deserializes_all_fields_correctly(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test get_session deserializes all fields correctly."""
        redis_data = {
            b"session_id": str(sample_session.session_id).encode(),
            b"workspace_id": str(sample_session.workspace_id).encode(),
            b"filename": sample_session.filename.encode(),
            b"size": str(sample_session.size).encode(),
            b"mime_type": sample_session.mime_type.encode(),
            b"sha256_checksum": sample_session.sha256_checksum.value.encode(),
            b"offset": str(sample_session.offset).encode(),
            b"status": sample_session.status.value.encode(),
            b"created_at": sample_session.created_at.isoformat().encode(),
            b"expires_at": sample_session.expires_at.isoformat().encode(),
            b"chunk_manifest": json.dumps(sample_session.chunk_manifest).encode(),
        }
        mock_redis.hgetall.return_value = redis_data

        result = await session_store.get_session(
            sample_session.workspace_id, sample_session.session_id
        )

        assert result is not None
        assert result.session_id == sample_session.session_id
        assert result.workspace_id == sample_session.workspace_id
        assert result.filename == sample_session.filename
        assert result.size == sample_session.size
        assert result.mime_type == sample_session.mime_type
        assert result.sha256_checksum.value == sample_session.sha256_checksum.value
        assert result.offset == sample_session.offset
        assert result.status == sample_session.status

    @pytest.mark.asyncio
    async def test_returns_none_when_key_not_found(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
    ) -> None:
        """Test get_session returns None when session doesn't exist."""
        mock_redis.hgetall.return_value = {}  # Empty dict = key not found

        result = await session_store.get_session(uuid4(), uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_raises_infrastructure_error_on_redis_failure(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
    ) -> None:
        """Test get_session raises InfrastructureError on Redis failure."""
        mock_redis.hgetall.side_effect = redis.exceptions.ConnectionError("Connection timeout")

        with pytest.raises(InfrastructureError, match="Failed to retrieve session"):
            await session_store.get_session(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_raises_serialization_error_on_invalid_json(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test get_session raises SerializationError on invalid JSON."""
        redis_data = {
            b"session_id": str(sample_session.session_id).encode(),
            b"workspace_id": str(sample_session.workspace_id).encode(),
            b"filename": sample_session.filename.encode(),
            b"size": str(sample_session.size).encode(),
            b"mime_type": sample_session.mime_type.encode(),
            b"sha256_checksum": sample_session.sha256_checksum.value.encode(),
            b"offset": str(sample_session.offset).encode(),
            b"status": sample_session.status.value.encode(),
            b"created_at": sample_session.created_at.isoformat().encode(),
            b"expires_at": sample_session.expires_at.isoformat().encode(),
            b"chunk_manifest": b"{invalid json}",  # Invalid JSON
        }
        mock_redis.hgetall.return_value = redis_data

        with pytest.raises(SerializationError, match="Invalid session data"):
            await session_store.get_session(sample_session.workspace_id, sample_session.session_id)

    @pytest.mark.asyncio
    async def test_raises_serialization_error_on_invalid_uuid(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test get_session raises SerializationError on invalid UUID."""
        redis_data = {
            b"session_id": b"not-a-uuid",  # Invalid UUID
            b"workspace_id": str(sample_session.workspace_id).encode(),
            b"filename": sample_session.filename.encode(),
            b"size": str(sample_session.size).encode(),
            b"mime_type": sample_session.mime_type.encode(),
            b"sha256_checksum": sample_session.sha256_checksum.value.encode(),
            b"offset": str(sample_session.offset).encode(),
            b"status": sample_session.status.value.encode(),
            b"created_at": sample_session.created_at.isoformat().encode(),
            b"expires_at": sample_session.expires_at.isoformat().encode(),
            b"chunk_manifest": json.dumps(sample_session.chunk_manifest).encode(),
        }
        mock_redis.hgetall.return_value = redis_data

        with pytest.raises(SerializationError, match="Invalid session data"):
            await session_store.get_session(sample_session.workspace_id, sample_session.session_id)

    @pytest.mark.asyncio
    async def test_parses_chunk_manifest_from_json(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test get_session parses chunk_manifest from JSON."""
        chunk_manifest = [
            {"index": 0, "size": 1024, "checksum": "abc123"},
            {"index": 1, "size": 512, "checksum": "def456"},
        ]
        sample_session.chunk_manifest = chunk_manifest

        redis_data = {
            b"session_id": str(sample_session.session_id).encode(),
            b"workspace_id": str(sample_session.workspace_id).encode(),
            b"filename": sample_session.filename.encode(),
            b"size": str(sample_session.size).encode(),
            b"mime_type": sample_session.mime_type.encode(),
            b"sha256_checksum": sample_session.sha256_checksum.value.encode(),
            b"offset": str(sample_session.offset).encode(),
            b"status": sample_session.status.value.encode(),
            b"created_at": sample_session.created_at.isoformat().encode(),
            b"expires_at": sample_session.expires_at.isoformat().encode(),
            b"chunk_manifest": json.dumps(chunk_manifest).encode(),
        }
        mock_redis.hgetall.return_value = redis_data

        result = await session_store.get_session(
            sample_session.workspace_id, sample_session.session_id
        )

        assert result is not None
        assert result.chunk_manifest == chunk_manifest

    @pytest.mark.asyncio
    async def test_raises_serialization_error_on_non_list_chunk_manifest(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test get_session raises SerializationError if chunk_manifest is not a list."""
        redis_data = {
            b"session_id": str(sample_session.session_id).encode(),
            b"workspace_id": str(sample_session.workspace_id).encode(),
            b"filename": sample_session.filename.encode(),
            b"size": str(sample_session.size).encode(),
            b"mime_type": sample_session.mime_type.encode(),
            b"sha256_checksum": sample_session.sha256_checksum.value.encode(),
            b"offset": str(sample_session.offset).encode(),
            b"status": sample_session.status.value.encode(),
            b"created_at": sample_session.created_at.isoformat().encode(),
            b"expires_at": sample_session.expires_at.isoformat().encode(),
            b"chunk_manifest": b'"not a list"',  # String instead of list
        }
        mock_redis.hgetall.return_value = redis_data

        with pytest.raises(SerializationError, match="chunk_manifest must be a list"):
            await session_store.get_session(sample_session.workspace_id, sample_session.session_id)


class TestUpdateSession:
    """Tests for update_session method."""

    @pytest.mark.asyncio
    async def test_checks_session_exists_before_update(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test update_session checks if session exists and has valid TTL."""
        mock_redis.ttl.return_value = 3600  # Session exists with 1 hour remaining

        await session_store.update_session(sample_session)

        expected_key = (
            f"session:workspace_{sample_session.workspace_id}:document_{sample_session.session_id}"
        )
        mock_redis.ttl.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_raises_session_not_found_error_if_not_exists(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test update_session raises SessionNotFoundError if session doesn't exist."""
        mock_redis.ttl.return_value = -2  # Key doesn't exist

        with pytest.raises(SessionNotFoundError, match="Session not found"):
            await session_store.update_session(sample_session)

    @pytest.mark.asyncio
    async def test_updates_all_fields(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test update_session updates all session fields."""
        mock_redis.ttl.return_value = 3600  # Session exists

        await session_store.update_session(sample_session)

        call_args = mock_redis.hset.call_args
        data = call_args[1]["mapping"]

        assert data["offset"] == str(sample_session.offset)
        assert data["status"] == sample_session.status.value

    @pytest.mark.asyncio
    async def test_does_not_reset_ttl(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test update_session does NOT reset TTL."""
        mock_redis.ttl.return_value = 3600  # Session exists

        await session_store.update_session(sample_session)

        # Verify EXPIRE was NOT called (only called during create)
        mock_redis.expire.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_infrastructure_error_on_redis_failure(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test update_session raises InfrastructureError on Redis failure."""
        mock_redis.ttl.return_value = 3600  # Session exists
        mock_redis.hset.side_effect = redis.exceptions.ConnectionError("Timeout")

        with pytest.raises(InfrastructureError, match="Failed to update session"):
            await session_store.update_session(sample_session)


class TestDeleteSession:
    """Tests for delete_session method."""

    @pytest.mark.asyncio
    async def test_deletes_session_with_correct_key(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
    ) -> None:
        """Test delete_session deletes both session and expiry metadata keys."""
        workspace_id = uuid4()
        session_id = uuid4()
        mock_redis.delete.return_value = 2  # Both keys deleted

        await session_store.delete_session(workspace_id, session_id)

        expected_session_key = f"session:workspace_{workspace_id}:document_{session_id}"
        expected_expiry_key = f"session:expiry:{session_id}"
        mock_redis.delete.assert_called_once_with(expected_session_key, expected_expiry_key)

    @pytest.mark.asyncio
    async def test_is_idempotent_when_key_not_exists(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
    ) -> None:
        """Test delete_session is idempotent (no error if key doesn't exist)."""
        mock_redis.delete.return_value = 0  # Key didn't exist

        # Should not raise exception
        await session_store.delete_session(uuid4(), uuid4())

        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_infrastructure_error_on_redis_failure(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
    ) -> None:
        """Test delete_session raises InfrastructureError on Redis failure."""
        mock_redis.delete.side_effect = redis.exceptions.ConnectionError("Timeout")

        with pytest.raises(InfrastructureError, match="Failed to delete session"):
            await session_store.delete_session(uuid4(), uuid4())


class TestKeyGeneration:
    """Tests for workspace isolation via key patterns."""

    @pytest.mark.asyncio
    async def test_different_workspaces_produce_different_keys(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
    ) -> None:
        """Test same session_id in different workspaces uses different keys."""
        session_id = uuid4()
        workspace_id_1 = uuid4()
        workspace_id_2 = uuid4()

        # Create two sessions with same session_id but different workspace_ids
        session_1 = UploadSession(
            session_id=session_id,
            workspace_id=workspace_id_1,
            filename="test.pdf",
            size=1024,
            mime_type="application/pdf",
            sha256_checksum=SHA256Hash("a" * 64),
            offset=0,
            status=SessionStatus.PENDING,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            chunk_manifest=[],
        )

        session_2 = UploadSession(
            session_id=session_id,
            workspace_id=workspace_id_2,
            filename="test.pdf",
            size=1024,
            mime_type="application/pdf",
            sha256_checksum=SHA256Hash("a" * 64),
            offset=0,
            status=SessionStatus.PENDING,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            chunk_manifest=[],
        )

        await session_store.create_session(session_1)
        pipeline = mock_redis.pipeline.return_value
        # Story 4.1: Each session creates 2 hset calls (session + metadata)
        # First session's session data is at index 0
        key_1 = pipeline.hset.call_args_list[0][0][0]

        await session_store.create_session(session_2)
        # Second session's session data is at index 2 (indices 0,1 = session_1, indices 2,3 = session_2)
        key_2 = pipeline.hset.call_args_list[2][0][0]

        # Keys must be different (workspace isolation)
        assert key_1 != key_2
        assert str(workspace_id_1) in key_1
        assert str(workspace_id_2) in key_2


class TestSerializationEdgeCases:
    """Tests for edge cases in serialization/deserialization."""

    @pytest.mark.asyncio
    async def test_empty_chunk_manifest_serializes_correctly(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test empty chunk_manifest [] serializes and deserializes correctly."""
        sample_session.chunk_manifest = []

        redis_data = {
            b"session_id": str(sample_session.session_id).encode(),
            b"workspace_id": str(sample_session.workspace_id).encode(),
            b"filename": sample_session.filename.encode(),
            b"size": str(sample_session.size).encode(),
            b"mime_type": sample_session.mime_type.encode(),
            b"sha256_checksum": sample_session.sha256_checksum.value.encode(),
            b"offset": str(sample_session.offset).encode(),
            b"status": sample_session.status.value.encode(),
            b"created_at": sample_session.created_at.isoformat().encode(),
            b"expires_at": sample_session.expires_at.isoformat().encode(),
            b"chunk_manifest": b"[]",
        }
        mock_redis.hgetall.return_value = redis_data

        result = await session_store.get_session(
            sample_session.workspace_id, sample_session.session_id
        )

        assert result is not None
        assert result.chunk_manifest == []

    @pytest.mark.asyncio
    async def test_large_chunk_manifest_serializes_correctly(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test large chunk_manifest (1000+ chunks) serializes correctly."""
        large_manifest = [{"index": i, "size": 1024, "checksum": f"hash{i}"} for i in range(1000)]
        sample_session.chunk_manifest = large_manifest

        await session_store.create_session(sample_session)

        pipeline = mock_redis.pipeline.return_value
        # Story 4.1: First call is session data
        call_args = pipeline.hset.call_args_list[0]
        data = call_args[1]["mapping"]
        chunk_manifest_json = data["chunk_manifest"]

        parsed = json.loads(chunk_manifest_json)
        assert len(parsed) == 1000
        assert parsed == large_manifest

    @pytest.mark.asyncio
    async def test_special_characters_in_filename(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test special characters in filename are handled correctly."""
        sample_session.filename = 'test "file"\nwith\nnewlines.pdf'

        await session_store.create_session(sample_session)

        pipeline = mock_redis.pipeline.return_value
        # Story 4.1: First call is session data
        call_args = pipeline.hset.call_args_list[0]
        data = call_args[1]["mapping"]

        assert data["filename"] == sample_session.filename

    @pytest.mark.asyncio
    async def test_offset_at_size_boundary(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test offset == size (upload complete) handled correctly."""
        sample_session.offset = sample_session.size

        await session_store.create_session(sample_session)

        pipeline = mock_redis.pipeline.return_value
        # Story 4.1: First call is session data
        call_args = pipeline.hset.call_args_list[0]
        data = call_args[1]["mapping"]

        assert data["offset"] == str(sample_session.size)
        assert data["size"] == str(sample_session.size)


class TestExpiryMetadata:
    """Tests for session expiry metadata functionality (Story 4.1)."""

    @pytest.mark.asyncio
    async def test_create_session_writes_expiry_metadata(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test create_session writes expiry metadata with 7-day TTL."""
        await session_store.create_session(sample_session)

        pipeline = mock_redis.pipeline.return_value

        # Verify two HSET calls: one for session, one for expiry metadata
        hset_calls = pipeline.hset.call_args_list
        assert len(hset_calls) == 2

        # First call: session data
        session_key = (
            f"session:workspace_{sample_session.workspace_id}:document_{sample_session.session_id}"
        )
        assert hset_calls[0][0][0] == session_key

        # Second call: expiry metadata
        expiry_key = f"session:expiry:{sample_session.session_id}"
        assert hset_calls[1][0][0] == expiry_key

        # Verify expiry metadata content
        expiry_data = hset_calls[1][1]["mapping"]
        assert expiry_data["session_id"] == str(sample_session.session_id)
        assert expiry_data["workspace_id"] == str(sample_session.workspace_id)
        assert expiry_data["expires_at"] == sample_session.expires_at.isoformat()
        assert expiry_data["filename"] == sample_session.filename

        # Verify two EXPIRE calls: one with 86400s (24h), one with 604800s (7d)
        expire_calls = pipeline.expire.call_args_list
        assert len(expire_calls) == 2
        assert expire_calls[0][0] == (session_key, 86400)  # 24-hour TTL for session
        assert expire_calls[1][0] == (expiry_key, 604800)  # 7-day TTL for metadata

    @pytest.mark.asyncio
    async def test_get_session_with_expiry_info_returns_active_session(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test get_session_with_expiry_info returns (session, None) for active session."""
        # Mock session exists
        redis_data = {
            b"session_id": str(sample_session.session_id).encode(),
            b"workspace_id": str(sample_session.workspace_id).encode(),
            b"filename": sample_session.filename.encode(),
            b"size": str(sample_session.size).encode(),
            b"mime_type": sample_session.mime_type.encode(),
            b"sha256_checksum": sample_session.sha256_checksum.value.encode(),
            b"offset": str(sample_session.offset).encode(),
            b"status": sample_session.status.value.encode(),
            b"created_at": sample_session.created_at.isoformat().encode(),
            b"expires_at": sample_session.expires_at.isoformat().encode(),
            b"chunk_manifest": b"[]",
        }
        mock_redis.hgetall.return_value = redis_data

        session, expiry_metadata = await session_store.get_session_with_expiry_info(
            sample_session.workspace_id, sample_session.session_id
        )

        assert session is not None
        assert session.session_id == sample_session.session_id
        assert expiry_metadata is None

    @pytest.mark.asyncio
    async def test_get_session_with_expiry_info_returns_metadata_for_expired_session(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
        sample_session: UploadSession,
    ) -> None:
        """Test get_session_with_expiry_info returns (None, metadata) for expired session."""

        # Mock session doesn't exist (expired)
        # But expiry metadata exists
        def hgetall_side_effect(key):
            session_key = f"session:workspace_{sample_session.workspace_id}:document_{sample_session.session_id}"
            expiry_key = f"session:expiry:{sample_session.session_id}"

            if key == session_key:
                # Session expired (returns empty dict)
                return {}
            elif key == expiry_key:
                # Expiry metadata exists
                return {
                    b"session_id": str(sample_session.session_id).encode(),
                    b"workspace_id": str(sample_session.workspace_id).encode(),
                    b"expires_at": sample_session.expires_at.isoformat().encode(),
                    b"filename": sample_session.filename.encode(),
                }
            return {}

        mock_redis.hgetall.side_effect = hgetall_side_effect

        session, expiry_metadata = await session_store.get_session_with_expiry_info(
            sample_session.workspace_id, sample_session.session_id
        )

        assert session is None
        assert expiry_metadata is not None
        assert expiry_metadata["session_id"] == str(sample_session.session_id)
        assert expiry_metadata["workspace_id"] == str(sample_session.workspace_id)
        assert expiry_metadata["expires_at"] == sample_session.expires_at.isoformat()
        assert expiry_metadata["filename"] == sample_session.filename

    @pytest.mark.asyncio
    async def test_get_session_with_expiry_info_returns_none_for_never_existed(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
    ) -> None:
        """Test get_session_with_expiry_info returns (None, None) for never-existed session."""
        # Mock both session and expiry metadata don't exist
        mock_redis.hgetall.return_value = {}

        session, expiry_metadata = await session_store.get_session_with_expiry_info(
            uuid4(), uuid4()
        )

        assert session is None
        assert expiry_metadata is None

    @pytest.mark.asyncio
    async def test_get_session_with_expiry_info_raises_infrastructure_error_on_redis_failure(
        self,
        session_store: RedisSessionStore,
        mock_redis: AsyncMock,
    ) -> None:
        """Test get_session_with_expiry_info raises InfrastructureError on Redis failure."""
        mock_redis.hgetall.side_effect = redis.exceptions.ConnectionError("Timeout")

        with pytest.raises(
            InfrastructureError, match="Failed to retrieve session with expiry info"
        ):
            await session_store.get_session_with_expiry_info(uuid4(), uuid4())
