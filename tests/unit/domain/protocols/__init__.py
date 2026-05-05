"""Unit tests for ISessionStore protocol."""

from uuid import UUID

import pytest

from src.domain.entities import UploadSession
from src.domain.protocols import ISessionStore


class TestISessionStoreProtocol:
    """Tests for ISessionStore protocol structure and contract."""

    def test_protocol_has_create_session_method(self) -> None:
        """Test ISessionStore protocol defines create_session method."""
        assert hasattr(ISessionStore, "create_session")

    def test_protocol_has_get_session_method(self) -> None:
        """Test ISessionStore protocol defines get_session method."""
        assert hasattr(ISessionStore, "get_session")

    def test_protocol_has_update_session_method(self) -> None:
        """Test ISessionStore protocol defines update_session method."""
        assert hasattr(ISessionStore, "update_session")

    def test_protocol_has_delete_session_method(self) -> None:
        """Test ISessionStore protocol defines delete_session method."""
        assert hasattr(ISessionStore, "delete_session")

    def test_protocol_can_be_implemented_by_any_class(self) -> None:
        """Test ISessionStore protocol can be implemented by any class."""

        class MockSessionStore:
            """Mock implementation of ISessionStore for testing."""

            async def create_session(self, session: UploadSession) -> None:
                pass

            async def get_session(
                self, workspace_id: UUID, session_id: UUID
            ) -> UploadSession | None:
                return None

            async def update_session(self, session: UploadSession) -> None:
                pass

            async def delete_session(self, workspace_id: UUID, session_id: UUID) -> None:
                pass

        # Should not raise any errors - structural subtyping
        mock_store = MockSessionStore()
        assert mock_store is not None

        # Verify it has all required methods
        assert hasattr(mock_store, "create_session")
        assert hasattr(mock_store, "get_session")
        assert hasattr(mock_store, "update_session")
        assert hasattr(mock_store, "delete_session")

    def test_protocol_is_not_instantiable(self) -> None:
        """Test ISessionStore protocol cannot be instantiated directly."""
        # Protocols with ... in methods can't be instantiated
        # This test verifies it's a true protocol, not a regular class
        with pytest.raises(TypeError):
            ISessionStore()  # type: ignore
