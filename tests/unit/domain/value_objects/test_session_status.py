"""Unit tests for SessionStatus value object."""

from src.domain.value_objects.session_status import SessionStatus


class TestSessionStatus:
    """Test suite for SessionStatus enum."""

    def test_all_status_values_exist(self) -> None:
        """Test that all required status values are defined."""
        assert hasattr(SessionStatus, "PENDING")
        assert hasattr(SessionStatus, "IN_PROGRESS")
        assert hasattr(SessionStatus, "COMPLETE")
        assert hasattr(SessionStatus, "FAILED")
        assert hasattr(SessionStatus, "ABORTED")

    def test_status_string_representations(self) -> None:
        """Test that enum values have correct string representations."""
        assert SessionStatus.PENDING == "pending"
        assert SessionStatus.IN_PROGRESS == "in_progress"
        assert SessionStatus.COMPLETE == "complete"
        assert SessionStatus.FAILED == "failed"
        assert SessionStatus.ABORTED == "aborted"

    def test_status_comparison_operations(self) -> None:
        """Test that enum values can be compared."""
        status = SessionStatus.PENDING
        assert status == SessionStatus.PENDING
        assert status != SessionStatus.IN_PROGRESS
        assert status == "pending"
        assert status != "in_progress"

    def test_status_is_hashable(self) -> None:
        """Test that enum values can be used as dict keys."""
        status_dict = {
            SessionStatus.PENDING: "pending state",
            SessionStatus.IN_PROGRESS: "in progress state",
        }
        assert status_dict[SessionStatus.PENDING] == "pending state"
        assert status_dict[SessionStatus.IN_PROGRESS] == "in progress state"

    def test_can_iterate_all_statuses(self) -> None:
        """Test that we can iterate over all status values."""
        all_statuses = list(SessionStatus)
        assert len(all_statuses) == 5
        assert SessionStatus.PENDING in all_statuses
        assert SessionStatus.IN_PROGRESS in all_statuses
        assert SessionStatus.COMPLETE in all_statuses
        assert SessionStatus.FAILED in all_statuses
        assert SessionStatus.ABORTED in all_statuses
