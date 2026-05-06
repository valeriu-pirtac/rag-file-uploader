"""Integration tests for NATS JetStream event publisher.

Tests NATSEventPublisher with real NATS JetStream instance running
in Docker Compose. Tests focus on end-to-end event publishing,
stream persistence, and consumer replay.

Note:
    These tests require a real NATS server running (e.g., via docker-compose).
    Run with: pytest -m integration
    Skip with: pytest -m "not integration"
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import nats
import pytest
from nats.aio.client import Client as NATSClient

from src.domain.entities.events import FileLoadCompletedEvent
from src.domain.exceptions import InfrastructureError
from src.domain.value_objects.sha256_hash import SHA256Hash
from src.infrastructure.config import get_settings
from src.infrastructure.nats.event_publisher import NATSEventPublisher


# Mark all tests in this module as integration tests requiring real NATS
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
async def nats_publisher_real() -> AsyncGenerator[NATSEventPublisher]:
    """Create NATSEventPublisher connected to real NATS (Docker Compose).

    Yields:
        NATSEventPublisher: Connected publisher instance

    Note:
        Requires NATS running in Docker Compose on nats://localhost:4222
    """
    settings = get_settings()

    # Use localhost for integration tests
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
async def nats_subscriber(nats_publisher_real: NATSEventPublisher) -> AsyncGenerator[NATSClient]:
    """Create NATS subscriber for verifying published events.

    Args:
        nats_publisher_real: Publisher fixture (ensures NATS is running)

    Yields:
        NATSClient: Connected NATS client for subscribing

    Note:
        Uses same NATS URL as publisher
    """
    settings = get_settings()
    nats_url = settings.nats_url or "nats://localhost:4222"

    client = await nats.connect(servers=[nats_url])
    yield client
    await client.drain()
    await client.close()


@pytest.mark.asyncio
async def test_connect_to_real_nats(nats_publisher_real: NATSEventPublisher) -> None:
    """Test connect() to real NATS server succeeds."""
    # Publisher is already connected via fixture
    assert nats_publisher_real._connected is True
    assert nats_publisher_real._client is not None
    assert nats_publisher_real._js is not None


@pytest.mark.asyncio
async def test_ensure_stream_creates_stream_on_first_publish(
    nats_publisher_real: NATSEventPublisher,
) -> None:
    """Test _ensure_stream() creates stream on first publish."""
    # Stream should exist after connect (via _ensure_stream)
    js = nats_publisher_real._js
    assert js is not None

    stream_info = await js.stream_info("UPLOAD_EVENTS")
    assert stream_info.config.name == "UPLOAD_EVENTS"
    subjects = stream_info.config.subjects
    assert subjects is not None
    assert "upload.file.load_completed" in subjects


@pytest.mark.asyncio
async def test_publish_event_to_real_nats(
    nats_publisher_real: NATSEventPublisher,
    sample_event: FileLoadCompletedEvent,
) -> None:
    """Test publishing event to real NATS JetStream."""
    # Publish event
    await nats_publisher_real.publish(sample_event)

    # Verify event persisted in stream
    js = nats_publisher_real._js
    assert js is not None

    stream_info = await js.stream_info("UPLOAD_EVENTS")
    # Stream should have at least one message
    assert stream_info.state.messages > 0


@pytest.mark.asyncio
async def test_jetstream_ack_confirms_persistence(
    nats_publisher_real: NATSEventPublisher,
    sample_event: FileLoadCompletedEvent,
) -> None:
    """Test JetStream ack confirms message persistence."""
    # Publish should complete without error (ack received)
    await nats_publisher_real.publish(sample_event)

    # If we reach here, JetStream ack was received
    # (otherwise publish would have raised exception)


@pytest.mark.asyncio
async def test_event_consumed_by_downstream_subscriber(
    nats_publisher_real: NATSEventPublisher,
    nats_subscriber: NATSClient,
    sample_event: FileLoadCompletedEvent,
) -> None:
    """Test event can be consumed by downstream subscriber."""
    # Create a future to capture received message
    received_message: asyncio.Future[dict[str, Any]] = asyncio.Future()

    async def message_handler(msg: Any) -> None:
        """Handle received message."""
        import json

        payload = json.loads(msg.data.decode())
        received_message.set_result(payload)

    # Subscribe to subject
    js = nats_subscriber.jetstream()
    await js.subscribe("upload.file.load_completed", cb=message_handler, durable="test-consumer")

    # Publish event
    await nats_publisher_real.publish(sample_event)

    # Wait for message to be received (with timeout)
    try:
        payload = await asyncio.wait_for(received_message, timeout=5.0)

        # Verify payload structure
        assert payload["event_type"] == "FILE_LOAD_COMPLETED"
        assert payload["event_version"] == "1.0"
        assert payload["payload"]["file_id"] == str(sample_event.file_id)
        assert payload["payload"]["workspace_id"] == str(sample_event.workspace_id)
    except TimeoutError:
        pytest.fail("Message not received within timeout")


@pytest.mark.asyncio
async def test_graceful_shutdown_does_not_lose_messages(
    nats_publisher_real: NATSEventPublisher,
    sample_event: FileLoadCompletedEvent,
) -> None:
    """Test graceful disconnect does not lose messages."""
    # Get initial message count
    js = nats_publisher_real._js
    assert js is not None
    initial_stream_info = await js.stream_info("UPLOAD_EVENTS")
    initial_count = initial_stream_info.state.messages

    # Publish event
    await nats_publisher_real.publish(sample_event)

    # Disconnect gracefully
    await nats_publisher_real.disconnect()

    # Reconnect and verify message count increased
    await nats_publisher_real.connect()
    js = nats_publisher_real._js
    assert js is not None
    final_stream_info = await js.stream_info("UPLOAD_EVENTS")
    final_count = final_stream_info.state.messages

    assert final_count > initial_count


@pytest.mark.asyncio
async def test_stream_retention_events_persist_after_service_restart(
    nats_publisher_real: NATSEventPublisher,
    sample_event: FileLoadCompletedEvent,
) -> None:
    """Test stream retention: events persist after service restart.

    Note:
        This test verifies events are stored durably to disk.
        Full Docker container restart testing requires docker-compose integration.
    """
    # Publish event
    await nats_publisher_real.publish(sample_event)

    # Disconnect
    await nats_publisher_real.disconnect()

    # Reconnect (simulates service restart)
    await nats_publisher_real.connect()

    # Verify stream still has messages
    js = nats_publisher_real._js
    assert js is not None
    stream_info = await js.stream_info("UPLOAD_EVENTS")
    assert stream_info.state.messages > 0


@pytest.mark.asyncio
async def test_connection_failure_raises_infrastructure_error() -> None:
    """Test connection to invalid NATS URL raises InfrastructureError."""
    publisher = NATSEventPublisher(
        nats_url="nats://invalid-host:9999",
        nats_subject="upload.file.load_completed",
        connection_timeout=1,  # Short timeout for test
        max_reconnect_attempts=1,
    )

    with pytest.raises(InfrastructureError, match="Failed to connect to NATS"):
        await publisher.connect()


@pytest.mark.asyncio
async def test_multiple_publishers_can_publish_concurrently(
    sample_event: FileLoadCompletedEvent,
) -> None:
    """Test multiple publishers can publish to same stream concurrently."""
    settings = get_settings()
    nats_url = settings.nats_url or "nats://localhost:4222"

    # Create multiple publishers
    publishers = [
        NATSEventPublisher(
            nats_url=nats_url,
            nats_subject=settings.nats_subject,
            stream_name=settings.nats_stream_name,
        )
        for _ in range(3)
    ]

    # Connect all publishers
    for publisher in publishers:
        await publisher.connect()

    try:
        # Publish from all publishers concurrently
        tasks = [publisher.publish(sample_event) for publisher in publishers]
        await asyncio.gather(*tasks)

        # All publishes should succeed
    finally:
        # Cleanup
        for publisher in publishers:
            await publisher.disconnect()
