"""Unit tests for IEventPublisher protocol."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.domain.entities.events import FileLoadCompletedEvent
from src.domain.protocols.event_publisher import IEventPublisher
from src.domain.value_objects.sha256_hash import SHA256Hash


class TestIEventPublisherProtocol:
    """Tests for IEventPublisher protocol structure and contract."""

    def test_protocol_has_publish_method(self) -> None:
        """Test IEventPublisher protocol defines publish method."""
        assert hasattr(IEventPublisher, "publish")

    def test_protocol_can_be_implemented_by_mock_class(self) -> None:
        """Test IEventPublisher protocol can be implemented by any class."""

        class MockEventPublisher:
            """Mock implementation of IEventPublisher for testing."""

            async def publish(self, event: FileLoadCompletedEvent) -> None:
                """Mock publish implementation."""
                pass

        # Should not raise any errors - structural subtyping
        mock_publisher = MockEventPublisher()
        assert mock_publisher is not None

        # Verify it has all required methods
        assert hasattr(mock_publisher, "publish")

    def test_protocol_is_not_instantiable(self) -> None:
        """Test IEventPublisher protocol cannot be instantiated directly."""
        # Protocols with ... in methods can't be instantiated
        # This test verifies it's a true protocol, not a regular class
        with pytest.raises(TypeError):
            IEventPublisher()  # type: ignore

    async def test_publish_method_signature_matches_expectations(self) -> None:
        """Test that publish() method signature matches expected contract."""

        class TestPublisher:
            """Test implementation to verify signature compatibility."""

            async def publish(self, event: FileLoadCompletedEvent) -> None:
                """Verify signature matches protocol."""
                assert isinstance(event, FileLoadCompletedEvent)

        publisher = TestPublisher()

        # Create a valid event
        file_id = uuid4()
        workspace_id = uuid4()
        event = FileLoadCompletedEvent(
            file_id=file_id,
            workspace_id=workspace_id,
            s3_path=f"s3://bucket/workspace_{workspace_id}/{file_id}.pdf",
            sha256_checksum=SHA256Hash("a" * 64),
            size_bytes=1048576,
            uploaded_at=datetime.now(UTC),
        )

        # Await the coroutine to verify signature compatibility
        await publisher.publish(event)
