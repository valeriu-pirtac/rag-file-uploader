"""Unit tests for EventPublisherWithRetry.

Tests retry logic, exponential backoff, DLQ writes, and error handling.
Uses mocked publisher and Redis client for isolation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import redis.asyncio as aioredis

from src.domain.entities.events import FileLoadCompletedEvent
from src.domain.exceptions import InfrastructureError
from src.domain.value_objects.sha256_hash import SHA256Hash
from src.infrastructure.nats.event_publisher import NATSEventPublisher
from src.infrastructure.nats.event_publisher_with_retry import EventPublisherWithRetry


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
def mock_nats_publisher() -> AsyncMock:
    """Create mock NATS publisher for testing.

    Returns:
        AsyncMock: Mocked NATSEventPublisher
    """
    mock_publisher = AsyncMock(spec=NATSEventPublisher)
    return mock_publisher


@pytest.fixture
def mock_redis_client() -> AsyncMock:
    """Create mock Redis client for testing.

    Returns:
        AsyncMock: Mocked Redis async client
    """
    mock_redis = AsyncMock(spec=aioredis.Redis)
    return mock_redis


@pytest.fixture
def publisher_with_retry(
    mock_nats_publisher: AsyncMock, mock_redis_client: AsyncMock
) -> EventPublisherWithRetry:
    """Create EventPublisherWithRetry with mocked dependencies.

    Args:
        mock_nats_publisher: Mocked NATS publisher
        mock_redis_client: Mocked Redis client

    Returns:
        EventPublisherWithRetry: Test instance with mocked dependencies
    """
    return EventPublisherWithRetry(
        publisher=mock_nats_publisher,
        redis_client=mock_redis_client,
        max_retry_attempts=5,
        dlq_ttl_seconds=604800,
    )


class TestEventPublisherWithRetryInitialization:
    """Test EventPublisherWithRetry initialization."""

    def test_initialization_with_valid_config(
        self, mock_nats_publisher: AsyncMock, mock_redis_client: AsyncMock
    ) -> None:
        """Test publisher initialization with valid configuration."""
        publisher = EventPublisherWithRetry(
            publisher=mock_nats_publisher,
            redis_client=mock_redis_client,
            max_retry_attempts=5,
            dlq_ttl_seconds=604800,
        )

        assert publisher._publisher == mock_nats_publisher
        assert publisher._redis_client == mock_redis_client
        assert publisher._max_retry_attempts == 5
        assert publisher._dlq_ttl_seconds == 604800

    def test_initialization_with_custom_retry_config(
        self, mock_nats_publisher: AsyncMock, mock_redis_client: AsyncMock
    ) -> None:
        """Test publisher initialization with custom retry configuration."""
        publisher = EventPublisherWithRetry(
            publisher=mock_nats_publisher,
            redis_client=mock_redis_client,
            max_retry_attempts=3,
            dlq_ttl_seconds=86400,  # 1 day
        )

        assert publisher._max_retry_attempts == 3
        assert publisher._dlq_ttl_seconds == 86400

    def test_initialization_rejects_invalid_max_retry_attempts(
        self, mock_nats_publisher: AsyncMock, mock_redis_client: AsyncMock
    ) -> None:
        """Test initialization rejects max_retry_attempts < 1."""
        with pytest.raises(ValueError, match="max_retry_attempts must be >= 1"):
            EventPublisherWithRetry(
                publisher=mock_nats_publisher,
                redis_client=mock_redis_client,
                max_retry_attempts=0,
                dlq_ttl_seconds=604800,
            )

    def test_initialization_rejects_invalid_dlq_ttl(
        self, mock_nats_publisher: AsyncMock, mock_redis_client: AsyncMock
    ) -> None:
        """Test initialization rejects dlq_ttl_seconds < 1."""
        with pytest.raises(ValueError, match="dlq_ttl_seconds must be >= 1"):
            EventPublisherWithRetry(
                publisher=mock_nats_publisher,
                redis_client=mock_redis_client,
                max_retry_attempts=5,
                dlq_ttl_seconds=0,
            )


class TestPublishSuccessScenarios:
    """Test successful event publishing scenarios."""

    @pytest.mark.asyncio
    async def test_publish_succeeds_first_attempt(
        self,
        publisher_with_retry: EventPublisherWithRetry,
        mock_nats_publisher: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test publish succeeds on first attempt (no retries)."""
        # Arrange
        mock_nats_publisher.publish = AsyncMock()

        # Act
        await publisher_with_retry.publish(sample_event)

        # Assert
        mock_nats_publisher.publish.assert_called_once_with(sample_event)

    @pytest.mark.asyncio
    async def test_publish_succeeds_on_retry_attempt_2(
        self,
        publisher_with_retry: EventPublisherWithRetry,
        mock_nats_publisher: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test publish succeeds on retry attempt 2 after first failure."""
        # Arrange
        mock_nats_publisher.publish = AsyncMock(
            side_effect=[
                InfrastructureError("Connection refused"),  # Attempt 1 fails
                None,  # Attempt 2 succeeds
            ]
        )

        # Act
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await publisher_with_retry.publish(sample_event)

        # Assert
        assert mock_nats_publisher.publish.call_count == 2
        mock_sleep.assert_called_once_with(1)  # 2^(1-1) = 1s delay
        mock_redis_client.setex.assert_not_called()  # No DLQ write

    @pytest.mark.asyncio
    async def test_publish_succeeds_on_retry_attempt_3(
        self,
        publisher_with_retry: EventPublisherWithRetry,
        mock_nats_publisher: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test publish succeeds on retry attempt 3 after two failures."""
        # Arrange
        mock_nats_publisher.publish = AsyncMock(
            side_effect=[
                InfrastructureError("Connection refused"),  # Attempt 1 fails
                InfrastructureError("Connection refused"),  # Attempt 2 fails
                None,  # Attempt 3 succeeds
            ]
        )

        # Act
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await publisher_with_retry.publish(sample_event)

        # Assert
        assert mock_nats_publisher.publish.call_count == 3
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1)  # First retry: 2^(1-1) = 1s
        mock_sleep.assert_any_call(2)  # Second retry: 2^(2-1) = 2s
        mock_redis_client.setex.assert_not_called()  # No DLQ write

    @pytest.mark.asyncio
    async def test_publish_succeeds_on_final_attempt_5(
        self,
        publisher_with_retry: EventPublisherWithRetry,
        mock_nats_publisher: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test publish succeeds on final attempt 5 after four failures."""
        # Arrange
        mock_nats_publisher.publish = AsyncMock(
            side_effect=[
                InfrastructureError("Connection refused"),  # Attempt 1 fails
                InfrastructureError("Connection refused"),  # Attempt 2 fails
                InfrastructureError("Connection refused"),  # Attempt 3 fails
                InfrastructureError("Connection refused"),  # Attempt 4 fails
                None,  # Attempt 5 succeeds
            ]
        )

        # Act
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await publisher_with_retry.publish(sample_event)

        # Assert
        assert mock_nats_publisher.publish.call_count == 5
        assert mock_sleep.call_count == 4
        mock_sleep.assert_any_call(1)  # First retry: 2^(1-1) = 1s
        mock_sleep.assert_any_call(2)  # Second retry: 2^(2-1) = 2s
        mock_sleep.assert_any_call(4)  # Third retry: 2^(3-1) = 4s
        mock_sleep.assert_any_call(8)  # Fourth retry: 2^(4-1) = 8s
        mock_redis_client.setex.assert_not_called()  # No DLQ write


class TestPublishRetryFailureScenarios:
    """Test publish retry failure scenarios with DLQ writes."""

    @pytest.mark.asyncio
    async def test_publish_writes_to_dlq_after_all_retries_fail(
        self,
        publisher_with_retry: EventPublisherWithRetry,
        mock_nats_publisher: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test publish writes to DLQ after 5 failed attempts and raises exception."""
        # Arrange
        mock_nats_publisher.publish = AsyncMock(
            side_effect=InfrastructureError("Connection refused")
        )
        mock_redis_client.setex = AsyncMock()

        # Act & Assert
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(
                InfrastructureError, match="Event publish failed after.*retries.*DLQ"
            ):
                await publisher_with_retry.publish(sample_event)

        # Assert
        assert mock_nats_publisher.publish.call_count == 5
        mock_redis_client.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_dlq_entry_has_correct_key_pattern(
        self,
        publisher_with_retry: EventPublisherWithRetry,
        mock_nats_publisher: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test DLQ entry uses correct key pattern: dlq:file_load_completed:{file_id}."""
        # Arrange
        mock_nats_publisher.publish = AsyncMock(
            side_effect=InfrastructureError("Connection refused")
        )
        mock_redis_client.setex = AsyncMock()

        # Act
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(InfrastructureError):
                await publisher_with_retry.publish(sample_event)

        # Assert
        dlq_key = mock_redis_client.setex.call_args[0][0]
        assert dlq_key == f"dlq:file_load_completed:{sample_event.file_id}"

    @pytest.mark.asyncio
    async def test_dlq_entry_has_correct_ttl(
        self,
        publisher_with_retry: EventPublisherWithRetry,
        mock_nats_publisher: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test DLQ entry has 7-day TTL (604800 seconds)."""
        # Arrange
        mock_nats_publisher.publish = AsyncMock(
            side_effect=InfrastructureError("Connection refused")
        )
        mock_redis_client.setex = AsyncMock()

        # Act
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(InfrastructureError):
                await publisher_with_retry.publish(sample_event)

        # Assert
        dlq_ttl = mock_redis_client.setex.call_args[0][1]
        assert dlq_ttl == 604800  # 7 days

    @pytest.mark.asyncio
    async def test_dlq_entry_schema_is_correct(
        self,
        publisher_with_retry: EventPublisherWithRetry,
        mock_nats_publisher: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test DLQ entry has correct schema with all required fields."""
        # Arrange
        mock_nats_publisher.publish = AsyncMock(
            side_effect=InfrastructureError("NATS connection timeout")
        )
        mock_redis_client.setex = AsyncMock()

        # Act
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(InfrastructureError):
                await publisher_with_retry.publish(sample_event)

        # Assert
        dlq_entry_json = mock_redis_client.setex.call_args[0][2]
        dlq_entry = json.loads(dlq_entry_json)

        # Verify schema
        assert "event_payload" in dlq_entry
        assert "original_timestamp" in dlq_entry
        assert "retry_count" in dlq_entry
        assert "last_error" in dlq_entry
        assert "failed_at" in dlq_entry

        # Verify values
        assert dlq_entry["retry_count"] == 5
        assert "NATS connection timeout" in dlq_entry["last_error"]
        assert dlq_entry["original_timestamp"] == sample_event.timestamp.isoformat()

        # Verify event_payload contains full event (with nested payload structure)
        event_payload = dlq_entry["event_payload"]
        assert event_payload["eventVersion"] == "1.0"
        assert event_payload["eventType"] == "FILE_LOAD_COMPLETED"
        assert "payload" in event_payload

        # Verify nested payload fields
        payload = event_payload["payload"]
        assert payload["file_id"] == str(sample_event.file_id)
        assert payload["workspace_id"] == str(sample_event.workspace_id)

    @pytest.mark.asyncio
    async def test_dlq_write_failure_raises_infrastructure_error(
        self,
        publisher_with_retry: EventPublisherWithRetry,
        mock_nats_publisher: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test DLQ write failure raises InfrastructureError."""
        # Arrange
        mock_nats_publisher.publish = AsyncMock(
            side_effect=InfrastructureError("Connection refused")
        )
        mock_redis_client.setex = AsyncMock(side_effect=Exception("Redis unavailable"))

        # Act & Assert
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(InfrastructureError, match="Failed to write event to DLQ"):
                await publisher_with_retry.publish(sample_event)


class TestExponentialBackoffDelays:
    """Test exponential backoff delay calculations."""

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays_are_correct(
        self,
        publisher_with_retry: EventPublisherWithRetry,
        mock_nats_publisher: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test exponential backoff delays: 1s, 2s, 4s, 8s."""
        # Arrange
        mock_nats_publisher.publish = AsyncMock(
            side_effect=InfrastructureError("Connection refused")
        )
        mock_redis_client.setex = AsyncMock()

        # Act
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(InfrastructureError):
                await publisher_with_retry.publish(sample_event)

        # Assert - verify all delay calls
        expected_delays = [1, 2, 4, 8]  # 4 delays for 5 attempts
        actual_delays = [call_args[0][0] for call_args in mock_sleep.call_args_list]
        assert actual_delays == expected_delays

    @pytest.mark.asyncio
    async def test_no_delay_before_first_attempt(
        self,
        publisher_with_retry: EventPublisherWithRetry,
        mock_nats_publisher: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test first publish attempt has no delay."""
        # Arrange
        mock_nats_publisher.publish = AsyncMock()

        # Act
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await publisher_with_retry.publish(sample_event)

        # Assert
        mock_sleep.assert_not_called()  # No delay before first attempt


class TestErrorHandling:
    """Test error handling and exception types."""

    @pytest.mark.asyncio
    async def test_handles_infrastructure_error(
        self,
        publisher_with_retry: EventPublisherWithRetry,
        mock_nats_publisher: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test retry logic handles InfrastructureError."""
        # Arrange
        mock_nats_publisher.publish = AsyncMock(
            side_effect=[
                InfrastructureError("NATS unavailable"),
                None,
            ]
        )

        # Act
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await publisher_with_retry.publish(sample_event)

        # Assert
        assert mock_nats_publisher.publish.call_count == 2
        mock_redis_client.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_generic_exception(
        self,
        publisher_with_retry: EventPublisherWithRetry,
        mock_nats_publisher: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test retry logic handles generic Exception."""
        # Arrange
        mock_nats_publisher.publish = AsyncMock(
            side_effect=[
                Exception("Unexpected error"),
                None,
            ]
        )

        # Act
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await publisher_with_retry.publish(sample_event)

        # Assert
        assert mock_nats_publisher.publish.call_count == 2
        mock_redis_client.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_network_timeout(
        self,
        publisher_with_retry: EventPublisherWithRetry,
        mock_nats_publisher: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test retry logic handles asyncio.TimeoutError."""
        # Arrange
        mock_nats_publisher.publish = AsyncMock(
            side_effect=[
                TimeoutError("Network timeout"),
                None,
            ]
        )

        # Act
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await publisher_with_retry.publish(sample_event)

        # Assert
        assert mock_nats_publisher.publish.call_count == 2
        mock_redis_client.setex.assert_not_called()


class TestCustomRetryConfiguration:
    """Test custom retry configuration."""

    @pytest.mark.asyncio
    async def test_custom_max_retry_attempts(
        self,
        mock_nats_publisher: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test publisher respects custom max_retry_attempts."""
        # Arrange
        publisher = EventPublisherWithRetry(
            publisher=mock_nats_publisher,
            redis_client=mock_redis_client,
            max_retry_attempts=3,  # Custom: 3 attempts instead of 5
            dlq_ttl_seconds=604800,
        )
        mock_nats_publisher.publish = AsyncMock(
            side_effect=InfrastructureError("Connection refused")
        )
        mock_redis_client.setex = AsyncMock()

        # Act
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(InfrastructureError):
                await publisher.publish(sample_event)

        # Assert
        assert mock_nats_publisher.publish.call_count == 3  # Only 3 attempts
        mock_redis_client.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_custom_dlq_ttl(
        self,
        mock_nats_publisher: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test publisher respects custom dlq_ttl_seconds."""
        # Arrange
        custom_ttl = 86400  # 1 day instead of 7
        publisher = EventPublisherWithRetry(
            publisher=mock_nats_publisher,
            redis_client=mock_redis_client,
            max_retry_attempts=5,
            dlq_ttl_seconds=custom_ttl,
        )
        mock_nats_publisher.publish = AsyncMock(
            side_effect=InfrastructureError("Connection refused")
        )
        mock_redis_client.setex = AsyncMock()

        # Act
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(InfrastructureError):
                await publisher.publish(sample_event)

        # Assert
        dlq_ttl = mock_redis_client.setex.call_args[0][1]
        assert dlq_ttl == custom_ttl
