"""Integration tests for EventPublisherWithRetry.

Tests retry logic, DLQ writes, and error recovery with real NATS and Redis
instances running in Docker Compose.

Note:
    These tests require real NATS and Redis servers running (e.g., via docker-compose).
    Run with: pytest -m integration
    Skip with: pytest -m "not integration"
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import redis.asyncio as aioredis

from src.domain.entities.events import FileLoadCompletedEvent
from src.domain.exceptions import InfrastructureError
from src.domain.value_objects.sha256_hash import SHA256Hash
from src.infrastructure.config import get_settings
from src.infrastructure.nats.event_publisher import NATSEventPublisher
from src.infrastructure.nats.event_publisher_with_retry import EventPublisherWithRetry


# Mark all tests in this module as integration tests requiring real services
pytestmark = pytest.mark.integration


@pytest.fixture
def sample_event() -> FileLoadCompletedEvent:
    """Create a sample FileLoadCompletedEvent for testing.

    Returns:
        FileLoadCompletedEvent: Test event with valid data
    """
    workspace_id = uuid4()
    file_id = uuid4()
    return FileLoadCompletedEvent(
        file_id=file_id,
        workspace_id=workspace_id,
        s3_path=f"s3://test-bucket/workspace_{workspace_id}/{file_id}/test.pdf",
        sha256_checksum=SHA256Hash("a" * 64),
        size_bytes=1048576,
        uploaded_at=datetime.now(UTC),
    )


@pytest.fixture
async def redis_client_real() -> AsyncGenerator[aioredis.Redis]:
    """Create Redis client connected to real Redis (Docker Compose).

    Yields:
        aioredis.Redis: Connected Redis client

    Note:
        Requires Redis running in Docker Compose on localhost:6379
    """
    settings = get_settings()
    redis_client = aioredis.from_url(settings.redis_url)

    yield redis_client

    # Cleanup: Remove all test DLQ entries
    async for key in redis_client.scan_iter(match="dlq:file_load_completed:*"):
        await redis_client.delete(key)

    await redis_client.aclose()


@pytest.fixture
async def nats_publisher_real() -> AsyncGenerator[NATSEventPublisher]:
    """Create NATSEventPublisher connected to real NATS (Docker Compose).

    Yields:
        NATSEventPublisher: Connected publisher instance

    Note:
        Requires NATS running in Docker Compose on nats://localhost:4222
    """
    settings = get_settings()
    nats_url = settings.nats_url or "nats://localhost:4222"

    publisher = NATSEventPublisher(
        nats_url=nats_url,
        nats_subject=settings.nats_subject,
        stream_name=settings.nats_stream_name,
        connection_timeout=settings.nats_connection_timeout,
        max_reconnect_attempts=settings.nats_max_reconnect_attempts,
    )

    await publisher.connect()
    yield publisher
    await publisher.disconnect()


@pytest.fixture
async def publisher_with_retry_real(
    nats_publisher_real: NATSEventPublisher, redis_client_real: aioredis.Redis
) -> EventPublisherWithRetry:
    """Create EventPublisherWithRetry with real NATS and Redis.

    Args:
        nats_publisher_real: Real NATS publisher
        redis_client_real: Real Redis client

    Returns:
        EventPublisherWithRetry: Publisher with real dependencies
    """
    return EventPublisherWithRetry(
        publisher=nats_publisher_real,
        redis_client=redis_client_real,
        max_retry_attempts=5,
        dlq_ttl_seconds=604800,
    )


class TestPublishWithRealNATS:
    """Test event publishing with real NATS JetStream."""

    @pytest.mark.asyncio
    async def test_publish_succeeds_with_real_nats(
        self,
        publisher_with_retry_real: EventPublisherWithRetry,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test publish succeeds with real NATS connection."""
        # Act - should not raise any exceptions
        await publisher_with_retry_real.publish(sample_event)

        # Assert - verify by consuming from NATS stream
        # (Verification happens implicitly - no exception means success)

    @pytest.mark.asyncio
    async def test_publish_multiple_events(
        self,
        publisher_with_retry_real: EventPublisherWithRetry,
    ) -> None:
        """Test publishing multiple events in sequence."""
        # Arrange
        events = [
            FileLoadCompletedEvent(
                file_id=uuid4(),
                workspace_id=uuid4(),
                s3_path=f"s3://test-bucket/file_{i}.pdf",
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )
            for i in range(5)
        ]

        # Act - publish all events
        for event in events:
            await publisher_with_retry_real.publish(event)

        # Assert - no exceptions means success


class TestRetryWithRealNATS:
    """Test retry logic with simulated NATS failures."""

    @pytest.mark.asyncio
    async def test_retry_with_nats_disconnect(
        self,
        nats_publisher_real: NATSEventPublisher,
        redis_client_real: aioredis.Redis,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test retry logic when NATS disconnects briefly."""
        # Arrange
        publisher_with_retry = EventPublisherWithRetry(
            publisher=nats_publisher_real,
            redis_client=redis_client_real,
            max_retry_attempts=3,  # Use fewer retries for faster test
            dlq_ttl_seconds=60,  # 1 minute for test
        )

        # Act - disconnect NATS, publish (should retry), reconnect NATS
        await nats_publisher_real.disconnect()

        # Start publish in background (will retry)
        publish_task = asyncio.create_task(publisher_with_retry.publish(sample_event))

        # Wait briefly, then reconnect NATS
        await asyncio.sleep(2)  # Allow one retry attempt
        await nats_publisher_real.connect()

        # Wait for publish to complete
        await publish_task

        # Assert - event should be published successfully (no DLQ write)
        dlq_key = f"dlq:file_load_completed:{sample_event.file_id}"
        dlq_entry = await redis_client_real.get(dlq_key)
        assert dlq_entry is None  # No DLQ entry means success


class TestDLQWithRealRedis:
    """Test dead letter queue with real Redis."""

    @pytest.mark.asyncio
    async def test_write_to_dlq_when_nats_unavailable(
        self,
        nats_publisher_real: NATSEventPublisher,
        redis_client_real: aioredis.Redis,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test event written to DLQ when NATS permanently unavailable."""
        # Arrange
        publisher_with_retry = EventPublisherWithRetry(
            publisher=nats_publisher_real,
            redis_client=redis_client_real,
            max_retry_attempts=3,  # Use fewer retries for faster test
            dlq_ttl_seconds=60,  # 1 minute for test
        )

        # Disconnect NATS permanently
        await nats_publisher_real.disconnect()

        # Act - publish event (should fail all retries and write to DLQ)
        with pytest.raises(InfrastructureError, match="Event publish failed after.*retries.*DLQ"):
            await publisher_with_retry.publish(sample_event)

        # Assert - verify DLQ entry exists
        dlq_key = f"dlq:file_load_completed:{sample_event.file_id}"
        dlq_entry_json = await redis_client_real.get(dlq_key)
        assert dlq_entry_json is not None

        # Verify DLQ entry schema
        dlq_entry = json.loads(dlq_entry_json)
        assert "event_payload" in dlq_entry
        assert "original_timestamp" in dlq_entry
        assert "retry_count" in dlq_entry
        assert "last_error" in dlq_entry
        assert "failed_at" in dlq_entry

        # Verify values
        assert dlq_entry["retry_count"] == 3
        assert dlq_entry["event_payload"]["payload"]["file_id"] == str(sample_event.file_id)
        assert dlq_entry["original_timestamp"] == sample_event.timestamp.isoformat()

        # Verify TTL
        ttl = await redis_client_real.ttl(dlq_key)
        assert ttl > 0  # TTL should be set
        assert ttl <= 60  # Should be <= 1 minute (test config)

        # Cleanup
        await redis_client_real.delete(dlq_key)

    @pytest.mark.asyncio
    async def test_dlq_entry_persists_with_ttl(
        self,
        nats_publisher_real: NATSEventPublisher,
        redis_client_real: aioredis.Redis,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test DLQ entry persists with correct TTL."""
        # Arrange
        custom_ttl = 300  # 5 minutes
        publisher_with_retry = EventPublisherWithRetry(
            publisher=nats_publisher_real,
            redis_client=redis_client_real,
            max_retry_attempts=2,
            dlq_ttl_seconds=custom_ttl,
        )

        # Disconnect NATS
        await nats_publisher_real.disconnect()

        # Act - publish event (should write to DLQ)
        with pytest.raises(InfrastructureError):
            await publisher_with_retry.publish(sample_event)

        # Assert - verify TTL
        dlq_key = f"dlq:file_load_completed:{sample_event.file_id}"
        ttl = await redis_client_real.ttl(dlq_key)
        assert ttl > 0
        assert ttl <= custom_ttl
        assert ttl >= custom_ttl - 10  # Allow small variance

        # Cleanup
        await redis_client_real.delete(dlq_key)

    @pytest.mark.asyncio
    async def test_manual_republish_from_dlq(
        self,
        nats_publisher_real: NATSEventPublisher,
        redis_client_real: aioredis.Redis,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test manual republish workflow from DLQ after NATS recovers."""
        # Arrange
        publisher_with_retry = EventPublisherWithRetry(
            publisher=nats_publisher_real,
            redis_client=redis_client_real,
            max_retry_attempts=2,
            dlq_ttl_seconds=60,
        )

        # Step 1: Write event to DLQ (NATS down)
        await nats_publisher_real.disconnect()
        with pytest.raises(InfrastructureError):
            await publisher_with_retry.publish(sample_event)

        dlq_key = f"dlq:file_load_completed:{sample_event.file_id}"
        dlq_entry_json = await redis_client_real.get(dlq_key)
        assert dlq_entry_json is not None

        # Step 2: NATS recovers
        await nats_publisher_real.connect()

        # Step 3: Manual republish from DLQ
        dlq_entry = json.loads(dlq_entry_json)
        event_payload = dlq_entry["event_payload"]["payload"]  # Access nested payload

        # Recreate event from DLQ payload
        from uuid import UUID

        recovered_event = FileLoadCompletedEvent(
            file_id=UUID(event_payload["file_id"]),
            workspace_id=UUID(event_payload["workspace_id"]),
            s3_path=event_payload["s3_path"],
            sha256_checksum=SHA256Hash(event_payload["sha256_checksum"]),
            size_bytes=event_payload["size_bytes"],
            uploaded_at=datetime.fromisoformat(event_payload["uploaded_at"]),
        )

        # Republish (should succeed now)
        await publisher_with_retry.publish(recovered_event)

        # Step 4: Delete from DLQ after successful republish
        await redis_client_real.delete(dlq_key)

        # Assert - DLQ entry removed
        final_dlq_entry = await redis_client_real.get(dlq_key)
        assert final_dlq_entry is None


class TestConcurrentPublishing:
    """Test concurrent event publishing with retry logic."""

    @pytest.mark.asyncio
    async def test_concurrent_event_publishing(
        self,
        publisher_with_retry_real: EventPublisherWithRetry,
    ) -> None:
        """Test publishing multiple events concurrently."""
        # Arrange
        events = [
            FileLoadCompletedEvent(
                file_id=uuid4(),
                workspace_id=uuid4(),
                s3_path=f"s3://test-bucket/file_{i}.pdf",
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )
            for i in range(10)
        ]

        # Act - publish all events concurrently
        await asyncio.gather(*[publisher_with_retry_real.publish(event) for event in events])

        # Assert - no exceptions means success
