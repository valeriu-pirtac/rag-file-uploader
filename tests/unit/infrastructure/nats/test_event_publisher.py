"""Unit tests for NATS JetStream event publisher.

Tests NATSEventPublisher implementation with mocked NATS client.
Tests focus on business logic, error handling, and protocol compliance.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import nats.js.errors
import pytest

from src.domain.entities.events import FileLoadCompletedEvent
from src.domain.exceptions import InfrastructureError, SerializationError
from src.domain.value_objects.sha256_hash import SHA256Hash
from src.infrastructure.nats.event_publisher import NATSEventPublisher


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
def mock_nats_client() -> AsyncMock:
    """Create mock NATS client for testing.

    Returns:
        AsyncMock: Mocked NATS client with JetStream context
    """
    mock_client = AsyncMock()
    mock_js = AsyncMock()

    # Mock JetStream publish with PubAck
    mock_ack = MagicMock()
    mock_ack.stream = "UPLOAD_EVENTS"
    mock_ack.seq = 42
    mock_js.publish = AsyncMock(return_value=mock_ack)

    # Mock stream info (stream exists)
    mock_stream_info = MagicMock()
    mock_stream_info.config.subjects = ["upload.file.load_completed"]
    mock_js.stream_info = AsyncMock(return_value=mock_stream_info)

    # Mock add_stream (create new stream)
    mock_js.add_stream = AsyncMock()

    # Mock client.jetstream() returns JetStream context
    mock_client.jetstream = MagicMock(return_value=mock_js)

    # Mock drain and close
    mock_client.drain = AsyncMock()
    mock_client.close = AsyncMock()

    return mock_client


@pytest.fixture
def nats_publisher() -> NATSEventPublisher:
    """Create NATSEventPublisher instance for testing.

    Returns:
        NATSEventPublisher: Publisher instance with test configuration
    """
    return NATSEventPublisher(
        nats_url="nats://localhost:4222",
        nats_subject="upload.file.load_completed",
        stream_name="UPLOAD_EVENTS",
        connection_timeout=5,
        max_reconnect_attempts=3,
    )


class TestNATSEventPublisherInitialization:
    """Test NATSEventPublisher initialization."""

    def test_initialization_with_valid_config(self) -> None:
        """Test publisher initialization with valid configuration."""
        publisher = NATSEventPublisher(
            nats_url="nats://localhost:4222",
            nats_subject="upload.file.load_completed",
            stream_name="UPLOAD_EVENTS",
            connection_timeout=5,
            max_reconnect_attempts=3,
        )

        assert publisher._nats_url == "nats://localhost:4222"
        assert publisher._nats_subject == "upload.file.load_completed"
        assert publisher._stream_name == "UPLOAD_EVENTS"
        assert publisher._connection_timeout == 5
        assert publisher._max_reconnect_attempts == 3
        assert publisher._connected is False
        assert publisher._client is None
        assert publisher._js is None

    def test_initialization_with_default_values(self) -> None:
        """Test publisher initialization with default values."""
        publisher = NATSEventPublisher(
            nats_url="nats://localhost:4222",
            nats_subject="upload.file.load_completed",
        )

        assert publisher._stream_name == "UPLOAD_EVENTS"
        assert publisher._connection_timeout == 5
        assert publisher._max_reconnect_attempts == 3

    def test_initialization_rejects_empty_nats_url(self) -> None:
        """Test publisher initialization rejects empty nats_url."""
        with pytest.raises(ValueError, match="nats_url cannot be empty"):
            NATSEventPublisher(
                nats_url="",
                nats_subject="upload.file.load_completed",
            )

        with pytest.raises(ValueError, match="nats_url cannot be empty"):
            NATSEventPublisher(
                nats_url="   ",
                nats_subject="upload.file.load_completed",
            )

    def test_initialization_rejects_empty_nats_subject(self) -> None:
        """Test publisher initialization rejects empty nats_subject."""
        with pytest.raises(ValueError, match="nats_subject cannot be empty"):
            NATSEventPublisher(
                nats_url="nats://localhost:4222",
                nats_subject="",
            )

        with pytest.raises(ValueError, match="nats_subject cannot be empty"):
            NATSEventPublisher(
                nats_url="nats://localhost:4222",
                nats_subject="   ",
            )

    def test_initialization_rejects_empty_stream_name(self) -> None:
        """Test publisher initialization rejects empty stream_name."""
        with pytest.raises(ValueError, match="stream_name cannot be empty"):
            NATSEventPublisher(
                nats_url="nats://localhost:4222",
                nats_subject="upload.file.load_completed",
                stream_name="",
            )


class TestNATSEventPublisherConnection:
    """Test NATSEventPublisher connection management."""

    @pytest.mark.asyncio
    async def test_connect_establishes_connection(
        self, nats_publisher: NATSEventPublisher, mock_nats_client: AsyncMock
    ) -> None:
        """Test connect() establishes NATS connection."""
        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect", return_value=mock_nats_client
        ):
            await nats_publisher.connect()

            assert nats_publisher._connected is True
            assert nats_publisher._client is not None
            assert nats_publisher._js is not None

    @pytest.mark.asyncio
    async def test_connect_is_idempotent(
        self, nats_publisher: NATSEventPublisher, mock_nats_client: AsyncMock
    ) -> None:
        """Test connect() is idempotent (safe to call multiple times)."""
        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect", return_value=mock_nats_client
        ) as mock_connect:
            await nats_publisher.connect()
            await nats_publisher.connect()  # Second call should not reconnect

            # connect should only be called once
            mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_raises_on_failure(self, nats_publisher: NATSEventPublisher) -> None:
        """Test connect() raises InfrastructureError on NATS connection failure."""
        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect",
            side_effect=Exception("Connection refused"),
        ):
            with pytest.raises(InfrastructureError, match="Failed to connect to NATS"):
                await nats_publisher.connect()

            assert nats_publisher._connected is False


class TestNATSEventPublisherStreamManagement:
    """Test JetStream stream creation and management."""

    @pytest.mark.asyncio
    async def test_ensure_stream_creates_stream_if_not_exists(
        self, nats_publisher: NATSEventPublisher, mock_nats_client: AsyncMock
    ) -> None:
        """Test _ensure_stream() creates stream if not exists."""
        # Mock stream_info to raise NotFoundError (stream doesn't exist)
        mock_js = mock_nats_client.jetstream()
        mock_js.stream_info = AsyncMock(side_effect=nats.js.errors.NotFoundError)

        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect", return_value=mock_nats_client
        ):
            await nats_publisher.connect()

            # Verify add_stream was called
            mock_js.add_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_stream_uses_existing_stream(
        self, nats_publisher: NATSEventPublisher, mock_nats_client: AsyncMock
    ) -> None:
        """Test _ensure_stream() uses existing stream if already exists."""
        mock_js = mock_nats_client.jetstream()

        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect", return_value=mock_nats_client
        ):
            await nats_publisher.connect()

            # stream_info returned a stream (exists)
            mock_js.stream_info.assert_called_once_with("UPLOAD_EVENTS")
            # add_stream should not be called
            mock_js.add_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_stream_raises_on_creation_failure(
        self, nats_publisher: NATSEventPublisher, mock_nats_client: AsyncMock
    ) -> None:
        """Test _ensure_stream() raises InfrastructureError on stream creation failure."""
        mock_js = mock_nats_client.jetstream()
        mock_js.stream_info = AsyncMock(side_effect=nats.js.errors.NotFoundError)
        mock_js.add_stream = AsyncMock(side_effect=Exception("Stream creation failed"))

        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect", return_value=mock_nats_client
        ):
            with pytest.raises(InfrastructureError, match="Failed to create JetStream stream"):
                await nats_publisher.connect()


class TestNATSEventPublisherPublish:
    """Test event publishing functionality."""

    @pytest.mark.asyncio
    async def test_publish_serializes_event_using_to_json(
        self,
        nats_publisher: NATSEventPublisher,
        mock_nats_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test publish() serializes event using event.to_json()."""
        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect", return_value=mock_nats_client
        ):
            await nats_publisher.connect()
            await nats_publisher.publish(sample_event)

            mock_js = mock_nats_client.jetstream()
            mock_js.publish.assert_called_once()

            # Verify payload is JSON-encoded
            call_args = mock_js.publish.call_args
            assert call_args.kwargs["subject"] == "upload.file.load_completed"
            assert isinstance(call_args.kwargs["payload"], bytes)

    @pytest.mark.asyncio
    async def test_publish_uses_correct_subject(
        self,
        nats_publisher: NATSEventPublisher,
        mock_nats_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test publish() uses correct NATS subject: upload.file.load_completed."""
        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect", return_value=mock_nats_client
        ):
            await nats_publisher.connect()
            await nats_publisher.publish(sample_event)

            mock_js = mock_nats_client.jetstream()
            call_args = mock_js.publish.call_args
            assert call_args.kwargs["subject"] == "upload.file.load_completed"

    @pytest.mark.asyncio
    async def test_publish_waits_for_jetstream_puback(
        self,
        nats_publisher: NATSEventPublisher,
        mock_nats_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test publish() waits for JetStream PubAck."""
        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect", return_value=mock_nats_client
        ):
            await nats_publisher.connect()
            result = await nats_publisher.publish(sample_event)

            # Verify returns True on success
            assert result is True

            mock_js = mock_nats_client.jetstream()
            # publish was awaited (returns ack)
            mock_js.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publish_raises_infrastructure_error_on_nats_failure(
        self,
        nats_publisher: NATSEventPublisher,
        mock_nats_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test publish() raises InfrastructureError on NATS connection failure."""
        mock_js = mock_nats_client.jetstream()
        mock_js.publish = AsyncMock(side_effect=Exception("NATS timeout"))

        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect", return_value=mock_nats_client
        ):
            await nats_publisher.connect()

            with pytest.raises(InfrastructureError, match="Failed to publish event to NATS"):
                await nats_publisher.publish(sample_event)

    @pytest.mark.asyncio
    async def test_publish_raises_infrastructure_error_if_not_connected(
        self, nats_publisher: NATSEventPublisher, sample_event: FileLoadCompletedEvent
    ) -> None:
        """Test publish() raises InfrastructureError if not connected."""
        with pytest.raises(InfrastructureError, match="Not connected to NATS"):
            await nats_publisher.publish(sample_event)

    @pytest.mark.asyncio
    async def test_publish_raises_serialization_error_on_json_failure(
        self,
        nats_publisher: NATSEventPublisher,
        mock_nats_client: AsyncMock,
    ) -> None:
        """Test publish() raises SerializationError on JSON serialization failure."""
        # Create a fresh event for this test
        workspace_id = uuid4()
        file_id = uuid4()
        sample_event = FileLoadCompletedEvent(
            file_id=file_id,
            workspace_id=workspace_id,
            s3_path=f"s3://test-bucket/workspace_{workspace_id}/{file_id}/test.pdf",
            sha256_checksum=SHA256Hash("a" * 64),
            size_bytes=1048576,
            uploaded_at=datetime.now(UTC),
        )

        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect", return_value=mock_nats_client
        ):
            await nats_publisher.connect()

            # Mock the to_json method at class level to raise SerializationError
            with patch(
                "src.domain.entities.events.FileLoadCompletedEvent.to_json",
                side_effect=SerializationError("JSON serialization failed"),
            ):
                with pytest.raises(SerializationError, match="JSON serialization failed"):
                    await nats_publisher.publish(sample_event)


class TestNATSEventPublisherDisconnect:
    """Test disconnect and resource cleanup."""

    @pytest.mark.asyncio
    async def test_disconnect_closes_connection_gracefully(
        self, nats_publisher: NATSEventPublisher, mock_nats_client: AsyncMock
    ) -> None:
        """Test disconnect() closes NATS connection gracefully."""
        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect", return_value=mock_nats_client
        ):
            await nats_publisher.connect()
            await nats_publisher.disconnect()

            # Verify drain and close were called
            mock_nats_client.drain.assert_awaited_once()
            mock_nats_client.close.assert_awaited_once()
            assert nats_publisher._connected is False
            assert nats_publisher._client is None
            assert nats_publisher._js is None

    @pytest.mark.asyncio
    async def test_disconnect_is_idempotent(
        self, nats_publisher: NATSEventPublisher, mock_nats_client: AsyncMock
    ) -> None:
        """Test disconnect() is idempotent (safe to call multiple times)."""
        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect", return_value=mock_nats_client
        ):
            await nats_publisher.connect()
            await nats_publisher.disconnect()
            await nats_publisher.disconnect()  # Second call should be safe

            # drain/close should only be called once
            mock_nats_client.drain.assert_awaited_once()
            mock_nats_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_handles_errors_gracefully(
        self, nats_publisher: NATSEventPublisher, mock_nats_client: AsyncMock
    ) -> None:
        """Test disconnect() handles errors gracefully (best effort)."""
        mock_nats_client.drain = AsyncMock(side_effect=Exception("Drain failed"))

        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect", return_value=mock_nats_client
        ):
            await nats_publisher.connect()
            # Should not raise, just log error
            await nats_publisher.disconnect()


class TestNATSEventPublisherProtocolCompliance:
    """Test protocol compliance and idempotency."""

    @pytest.mark.asyncio
    async def test_multiple_publishes_of_same_event_succeed(
        self,
        nats_publisher: NATSEventPublisher,
        mock_nats_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test idempotency: multiple publishes of same event succeed."""
        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect", return_value=mock_nats_client
        ):
            await nats_publisher.connect()
            await nats_publisher.publish(sample_event)
            await nats_publisher.publish(sample_event)  # Publish again

            mock_js = mock_nats_client.jetstream()
            # Both publishes should succeed
            assert mock_js.publish.await_count == 2

    @pytest.mark.asyncio
    async def test_error_handling_nats_timeout(
        self,
        nats_publisher: NATSEventPublisher,
        mock_nats_client: AsyncMock,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test error handling: NATS timeout raises InfrastructureError."""
        mock_js = mock_nats_client.jetstream()
        mock_js.publish = AsyncMock(side_effect=TimeoutError("NATS timeout"))

        with patch(
            "src.infrastructure.nats.event_publisher.nats.connect", return_value=mock_nats_client
        ):
            await nats_publisher.connect()

            with pytest.raises(InfrastructureError, match="Failed to publish event to NATS"):
                await nats_publisher.publish(sample_event)
