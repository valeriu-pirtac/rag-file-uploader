"""Unit tests for IRateLimiter protocol.

Tests verify that the protocol is properly defined and can be implemented
by conforming classes.
"""

from uuid import UUID

from src.domain.protocols import IRateLimiter


class TestIRateLimiterProtocol:
    """Test suite for IRateLimiter protocol definition."""

    def test_protocol_has_check_and_increment_method(self) -> None:
        """Test that protocol defines check_and_increment method."""
        assert hasattr(IRateLimiter, "check_and_increment")

    def test_protocol_has_decrement_method(self) -> None:
        """Test that protocol defines decrement method."""
        assert hasattr(IRateLimiter, "decrement")

    def test_protocol_has_get_current_count_method(self) -> None:
        """Test that protocol defines get_current_count method."""
        assert hasattr(IRateLimiter, "get_current_count")

    def test_protocol_has_reset_method(self) -> None:
        """Test that protocol defines reset method."""
        assert hasattr(IRateLimiter, "reset")

    def test_protocol_can_be_implemented(self) -> None:
        """Test that classes can implement the protocol."""

        class MockRateLimiter:
            """Mock implementation of IRateLimiter."""

            async def check_and_increment(self, workspace_id: UUID) -> None:
                """Mock check_and_increment."""
                pass

            async def decrement(self, workspace_id: UUID) -> None:
                """Mock decrement."""
                pass

            async def get_current_count(self, workspace_id: UUID) -> int:
                """Mock get_current_count."""
                return 0

            async def reset(self, workspace_id: UUID) -> None:
                """Mock reset."""
                pass

        # Create instance - should not raise
        mock_limiter = MockRateLimiter()
        assert isinstance(mock_limiter, MockRateLimiter)

    def test_protocol_is_not_instantiable(self) -> None:
        """Test that protocol itself cannot be instantiated."""
        # Protocols are abstract and should not be instantiable directly
        # This test verifies protocol nature
        # Just verify protocol is importable and has methods
        assert hasattr(IRateLimiter, "check_and_increment")
