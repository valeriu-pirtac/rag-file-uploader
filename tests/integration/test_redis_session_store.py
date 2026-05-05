"""Integration tests for RedisSessionStore with real Redis.

These tests require a running Redis instance (e.g., via Docker Compose).
Run: docker-compose up -d redis

Tests verify:
- Full session lifecycle with real Redis
- TTL expiry behavior
- Workspace isolation
- Concurrent updates
- Round-trip data integrity
"""

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import redis.asyncio as aioredis

from src.domain.entities import UploadSession
from src.domain.exceptions import SessionNotFoundError
from src.domain.value_objects import SessionStatus, SHA256Hash
from src.infrastructure.redis.session_store import RedisSessionStore


# Redis connection URL for integration tests
REDIS_TEST_URL = "redis://localhost:6379/1"  # Use DB 1 for tests


@pytest.fixture
async def redis_client() -> AsyncGenerator[None, aioredis.Redis]:
    """Create Redis client for integration tests.

    Connects to Redis instance at localhost:6379 (DB 1).
    Requires Redis to be running (e.g., via docker-compose up -d redis).
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
async def session_store(redis_client: aioredis.Redis) -> RedisSessionStore:
    """Create RedisSessionStore with real Redis client."""
    return RedisSessionStore(redis_client)


@pytest.fixture
def sample_session() -> UploadSession:
    """Create a valid UploadSession for testing."""
    return UploadSession(
        session_id=uuid4(),
        workspace_id=uuid4(),
        filename="integration-test.pdf",
        size=1024 * 1024,  # 1 MB
        mime_type="application/pdf",
        sha256_checksum=SHA256Hash("a" * 64),
        offset=0,
        status=SessionStatus.PENDING,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        chunk_manifest=[],
    )


class TestRedisSessionStoreIntegration:
    """Integration tests with real Redis."""

    @pytest.mark.asyncio
    async def test_full_session_lifecycle(
        self,
        session_store: RedisSessionStore,
        sample_session: UploadSession,
    ) -> None:
        """Test complete session lifecycle: create → get → update → delete."""
        # Create session
        await session_store.create_session(sample_session)

        # Retrieve session
        retrieved = await session_store.get_session(
            sample_session.workspace_id, sample_session.session_id
        )
        assert retrieved is not None
        assert retrieved.session_id == sample_session.session_id
        assert retrieved.workspace_id == sample_session.workspace_id
        assert retrieved.filename == sample_session.filename
        assert retrieved.offset == 0

        # Update session
        retrieved.offset = 512
        retrieved.status = SessionStatus.IN_PROGRESS
        retrieved.chunk_manifest = [{"index": 0, "size": 512, "checksum": "abc123"}]
        await session_store.update_session(retrieved)

        # Verify update persisted
        updated = await session_store.get_session(
            sample_session.workspace_id, sample_session.session_id
        )
        assert updated is not None
        assert updated.offset == 512
        assert updated.status == SessionStatus.IN_PROGRESS
        assert len(updated.chunk_manifest) == 1

        # Delete session
        await session_store.delete_session(sample_session.workspace_id, sample_session.session_id)

        # Verify deletion
        deleted = await session_store.get_session(
            sample_session.workspace_id, sample_session.session_id
        )
        assert deleted is None

    @pytest.mark.asyncio
    async def test_round_trip_data_integrity(
        self,
        session_store: RedisSessionStore,
        sample_session: UploadSession,
    ) -> None:
        """Test data integrity after round-trip (store → retrieve)."""
        # Add complex chunk_manifest
        sample_session.chunk_manifest = [
            {"index": 0, "size": 1024, "checksum": "abc123"},
            {"index": 1, "size": 2048, "checksum": "def456"},
            {"index": 2, "size": 512, "checksum": "ghi789"},
        ]
        sample_session.offset = 3584  # Sum of chunk sizes

        # Store session
        await session_store.create_session(sample_session)

        # Retrieve session
        retrieved = await session_store.get_session(
            sample_session.workspace_id, sample_session.session_id
        )

        # Verify all fields match
        assert retrieved is not None
        assert retrieved.session_id == sample_session.session_id
        assert retrieved.workspace_id == sample_session.workspace_id
        assert retrieved.filename == sample_session.filename
        assert retrieved.size == sample_session.size
        assert retrieved.mime_type == sample_session.mime_type
        assert retrieved.sha256_checksum.value == sample_session.sha256_checksum.value
        assert retrieved.offset == sample_session.offset
        assert retrieved.status == sample_session.status
        assert retrieved.chunk_manifest == sample_session.chunk_manifest

        # Verify datetime round-trip (may lose microsecond precision)
        assert abs((retrieved.created_at - sample_session.created_at).total_seconds()) < 1
        assert abs((retrieved.expires_at - sample_session.expires_at).total_seconds()) < 1

    @pytest.mark.asyncio
    async def test_ttl_set_correctly(
        self,
        session_store: RedisSessionStore,
        redis_client: aioredis.Redis,
        sample_session: UploadSession,
    ) -> None:
        """Test TTL is set to 24 hours (86400 seconds)."""
        await session_store.create_session(sample_session)

        # Query TTL directly from Redis
        key = (
            f"session:workspace_{sample_session.workspace_id}:document_{sample_session.session_id}"
        )
        ttl = await redis_client.ttl(key)

        # TTL should be close to 86400 (allow 5 second variance for test execution)
        assert 86395 <= ttl <= 86400

    @pytest.mark.asyncio
    async def test_ttl_not_reset_on_update(
        self,
        session_store: RedisSessionStore,
        redis_client: aioredis.Redis,
        sample_session: UploadSession,
    ) -> None:
        """Test update_session does NOT reset TTL."""
        await session_store.create_session(sample_session)

        # Wait a few seconds to let TTL decrease
        await asyncio.sleep(3)

        # Get TTL before update
        key = (
            f"session:workspace_{sample_session.workspace_id}:document_{sample_session.session_id}"
        )
        ttl_before = await redis_client.ttl(key)

        # Update session
        sample_session.offset = 1024
        await session_store.update_session(sample_session)

        # Small delay to ensure TTL changes
        await asyncio.sleep(1)

        # Get TTL after update
        ttl_after = await redis_client.ttl(key)

        # TTL should have decreased (not reset)
        # Allow <= in case we're in the same second
        assert ttl_after <= ttl_before
        assert ttl_after <= 86400 - 3  # At least 3 seconds passed

    @pytest.mark.asyncio
    async def test_session_expires_after_ttl(
        self,
        session_store: RedisSessionStore,
        redis_client: aioredis.Redis,
        sample_session: UploadSession,
    ) -> None:
        """Test session automatically expires after TTL (fast test with 2 seconds)."""
        await session_store.create_session(sample_session)

        # Manually set TTL to 2 seconds for fast test
        key = (
            f"session:workspace_{sample_session.workspace_id}:document_{sample_session.session_id}"
        )
        await redis_client.expire(key, 2)

        # Verify session exists
        retrieved = await session_store.get_session(
            sample_session.workspace_id, sample_session.session_id
        )
        assert retrieved is not None

        # Wait for expiry
        await asyncio.sleep(3)

        # Verify session expired (returns None)
        expired = await session_store.get_session(
            sample_session.workspace_id, sample_session.session_id
        )
        assert expired is None

    @pytest.mark.asyncio
    async def test_workspace_isolation(
        self,
        session_store: RedisSessionStore,
    ) -> None:
        """Test same session_id in different workspaces are isolated."""
        session_id = uuid4()
        workspace_id_1 = uuid4()
        workspace_id_2 = uuid4()

        # Create two sessions with same session_id but different workspaces
        session_1 = UploadSession(
            session_id=session_id,
            workspace_id=workspace_id_1,
            filename="workspace-1.pdf",
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
            filename="workspace-2.pdf",
            size=2048,
            mime_type="application/pdf",
            sha256_checksum=SHA256Hash("b" * 64),
            offset=0,
            status=SessionStatus.PENDING,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            chunk_manifest=[],
        )

        await session_store.create_session(session_1)
        await session_store.create_session(session_2)

        # Retrieve sessions by workspace
        retrieved_1 = await session_store.get_session(workspace_id_1, session_id)
        retrieved_2 = await session_store.get_session(workspace_id_2, session_id)

        # Verify both exist and are different
        assert retrieved_1 is not None
        assert retrieved_2 is not None
        assert retrieved_1.workspace_id == workspace_id_1
        assert retrieved_2.workspace_id == workspace_id_2
        assert retrieved_1.filename == "workspace-1.pdf"
        assert retrieved_2.filename == "workspace-2.pdf"
        assert retrieved_1.size == 1024
        assert retrieved_2.size == 2048

        # Delete one session
        await session_store.delete_session(workspace_id_1, session_id)

        # Verify only workspace_1 session deleted
        deleted_1 = await session_store.get_session(workspace_id_1, session_id)
        still_exists_2 = await session_store.get_session(workspace_id_2, session_id)

        assert deleted_1 is None
        assert still_exists_2 is not None

    @pytest.mark.asyncio
    async def test_concurrent_updates(
        self,
        session_store: RedisSessionStore,
        sample_session: UploadSession,
    ) -> None:
        """Test concurrent updates to same session are handled correctly."""
        await session_store.create_session(sample_session)

        async def update_offset(offset: int) -> None:
            """Update session offset."""
            session = await session_store.get_session(
                sample_session.workspace_id, sample_session.session_id
            )
            if session is not None:
                session.offset = offset
                await session_store.update_session(session)

        # Perform 10 concurrent updates
        await asyncio.gather(*[update_offset(i * 100) for i in range(10)])

        # Verify final state (one of the updates won)
        final = await session_store.get_session(
            sample_session.workspace_id, sample_session.session_id
        )
        assert final is not None
        assert final.offset in [i * 100 for i in range(10)]

    @pytest.mark.asyncio
    async def test_update_nonexistent_session_raises_error(
        self,
        session_store: RedisSessionStore,
        sample_session: UploadSession,
    ) -> None:
        """Test updating non-existent session raises SessionNotFoundError."""
        with pytest.raises(SessionNotFoundError):
            await session_store.update_session(sample_session)

    @pytest.mark.asyncio
    async def test_delete_is_idempotent(
        self,
        session_store: RedisSessionStore,
    ) -> None:
        """Test deleting non-existent session does not raise error."""
        # Should not raise exception
        await session_store.delete_session(uuid4(), uuid4())

        # Delete twice is also safe
        workspace_id = uuid4()
        session_id = uuid4()
        await session_store.delete_session(workspace_id, session_id)
        await session_store.delete_session(workspace_id, session_id)
