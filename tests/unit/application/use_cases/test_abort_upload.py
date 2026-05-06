"""Unit tests for AbortUploadUseCase.

Tests verify use case orchestration including session retrieval, validation,
status update, deletion, and rate limit counter decrement.
"""

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from src.application.use_cases.abort_upload import AbortUploadUseCase
from src.domain.entities.upload_session import UploadSession
from src.domain.exceptions import (
    InfrastructureError,
    SessionNotFoundError,
    WorkspaceMismatchError,
)
from src.domain.value_objects.session_status import SessionStatus
from src.domain.value_objects.sha256_hash import SHA256Hash


@pytest.fixture
def mock_session_store() -> AsyncMock:
    """Create mock ISessionStore protocol."""
    store = AsyncMock()
    store.get_session = AsyncMock()
    store.update_session = AsyncMock()
    store.delete_session = AsyncMock()
    return store


@pytest.fixture
def mock_rate_limiter() -> AsyncMock:
    """Create mock IRateLimiter protocol."""
    limiter = AsyncMock()
    limiter.decrement = AsyncMock()
    return limiter


@pytest.fixture
def use_case(
    mock_session_store: AsyncMock,
    mock_rate_limiter: AsyncMock,
) -> AbortUploadUseCase:
    """Create AbortUploadUseCase with mocked dependencies."""
    return AbortUploadUseCase(
        session_store=mock_session_store,
        rate_limiter=mock_rate_limiter,
    )


@pytest.fixture
def sample_workspace_id() -> UUID:
    """Create sample workspace UUID for testing."""
    return uuid4()


@pytest.fixture
def sample_session_id() -> UUID:
    """Create sample session UUID for testing."""
    return uuid4()


@pytest.fixture
def sample_session(
    sample_workspace_id: UUID,
    sample_session_id: UUID,
) -> UploadSession:
    """Create sample UploadSession for testing."""
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    return UploadSession(
        session_id=sample_session_id,
        workspace_id=sample_workspace_id,
        filename="document.pdf",
        size=1_048_576,  # 1 MB
        mime_type="application/pdf",
        sha256_checksum=SHA256Hash("a" * 64),
        offset=0,
        status=SessionStatus.PENDING,
        created_at=now,
        expires_at=now + timedelta(hours=24),
        chunk_manifest=[],
    )


class TestAbortUploadUseCaseHappyPath:
    """Test suite for successful use case execution."""

    @pytest.mark.asyncio
    async def test_successful_abort_session(
        self,
        use_case: AbortUploadUseCase,
        mock_session_store: AsyncMock,
        mock_rate_limiter: AsyncMock,
        sample_workspace_id: UUID,
        sample_session_id: UUID,
        sample_session: UploadSession,
    ) -> None:
        """Test successful session abort with all cleanup steps."""
        # Arrange
        mock_session_store.get_session.return_value = sample_session

        # Act
        result = await use_case.execute(sample_workspace_id, sample_session_id)

        # Assert: Result is None (204 No Content)
        assert result is None

        # Assert: get_session called with correct params
        mock_session_store.get_session.assert_called_once_with(
            sample_workspace_id, sample_session_id
        )

        # Assert: update_session called to set ABORTED status
        mock_session_store.update_session.assert_called_once()
        updated_session = mock_session_store.update_session.call_args[0][0]
        assert updated_session.status == SessionStatus.ABORTED

        # Assert: delete_session called with correct params
        mock_session_store.delete_session.assert_called_once_with(
            sample_workspace_id, sample_session_id
        )

        # Assert: rate limiter decremented
        mock_rate_limiter.decrement.assert_called_once_with(sample_workspace_id)

    @pytest.mark.asyncio
    async def test_operations_called_in_correct_order(
        self,
        use_case: AbortUploadUseCase,
        mock_session_store: AsyncMock,
        mock_rate_limiter: AsyncMock,
        sample_workspace_id: UUID,
        sample_session_id: UUID,
        sample_session: UploadSession,
    ) -> None:
        """Test that operations are called in the correct order."""
        # Arrange
        mock_session_store.get_session.return_value = sample_session
        call_order = []

        # Track call order
        async def track_get_session(*args, **kwargs):
            call_order.append("get_session")
            return sample_session

        async def track_update_session(*args, **kwargs):
            call_order.append("update_session")

        async def track_delete_session(*args, **kwargs):
            call_order.append("delete_session")

        async def track_decrement(*args, **kwargs):
            call_order.append("decrement")

        mock_session_store.get_session.side_effect = track_get_session
        mock_session_store.update_session.side_effect = track_update_session
        mock_session_store.delete_session.side_effect = track_delete_session
        mock_rate_limiter.decrement.side_effect = track_decrement

        # Act
        await use_case.execute(sample_workspace_id, sample_session_id)

        # Assert: Operations called in correct order
        assert call_order == [
            "get_session",
            "update_session",
            "delete_session",
            "decrement",
        ]


class TestAbortUploadUseCaseErrorHandling:
    """Test suite for error scenarios."""

    @pytest.mark.asyncio
    async def test_session_not_found_raises_exception(
        self,
        use_case: AbortUploadUseCase,
        mock_session_store: AsyncMock,
        mock_rate_limiter: AsyncMock,
        sample_workspace_id: UUID,
        sample_session_id: UUID,
    ) -> None:
        """Test that SessionNotFoundError is raised when session doesn't exist."""
        # Arrange: get_session returns None (session not found)
        mock_session_store.get_session.return_value = None

        # Act & Assert: Raises SessionNotFoundError
        with pytest.raises(SessionNotFoundError) as exc_info:
            await use_case.execute(sample_workspace_id, sample_session_id)

        # Assert: Error message includes session ID
        assert str(sample_session_id) in str(exc_info.value)

        # Assert: No other operations called
        mock_session_store.update_session.assert_not_called()
        mock_session_store.delete_session.assert_not_called()
        mock_rate_limiter.decrement.assert_not_called()

    @pytest.mark.asyncio
    async def test_workspace_mismatch_raises_exception(
        self,
        use_case: AbortUploadUseCase,
        mock_session_store: AsyncMock,
        mock_rate_limiter: AsyncMock,
        sample_workspace_id: UUID,
        sample_session_id: UUID,
        sample_session: UploadSession,
    ) -> None:
        """Test that WorkspaceMismatchError is raised when session belongs to different workspace."""
        # Arrange: Session belongs to different workspace
        different_workspace_id = uuid4()
        sample_session.workspace_id = different_workspace_id
        mock_session_store.get_session.return_value = sample_session

        # Act & Assert: Raises WorkspaceMismatchError
        with pytest.raises(WorkspaceMismatchError) as exc_info:
            await use_case.execute(sample_workspace_id, sample_session_id)

        # Assert: Error attributes are correct
        assert exc_info.value.resource_id == sample_session_id
        assert exc_info.value.resource_type == "upload_session"
        assert exc_info.value.expected_workspace_id == sample_workspace_id
        assert exc_info.value.actual_workspace_id == different_workspace_id

        # Assert: No cleanup operations called (security violation)
        mock_session_store.update_session.assert_not_called()
        mock_session_store.delete_session.assert_not_called()
        mock_rate_limiter.decrement.assert_not_called()

    @pytest.mark.asyncio
    async def test_infrastructure_error_during_get_session(
        self,
        use_case: AbortUploadUseCase,
        mock_session_store: AsyncMock,
        mock_rate_limiter: AsyncMock,
        sample_workspace_id: UUID,
        sample_session_id: UUID,
    ) -> None:
        """Test that InfrastructureError is raised when get_session fails."""
        # Arrange: get_session raises InfrastructureError
        mock_session_store.get_session.side_effect = InfrastructureError("Redis connection timeout")

        # Act & Assert: Raises InfrastructureError
        with pytest.raises(InfrastructureError) as exc_info:
            await use_case.execute(sample_workspace_id, sample_session_id)

        # Assert: Error message preserved
        assert "Redis connection timeout" in str(exc_info.value)

        # Assert: No other operations called
        mock_session_store.update_session.assert_not_called()
        mock_session_store.delete_session.assert_not_called()
        mock_rate_limiter.decrement.assert_not_called()

    @pytest.mark.asyncio
    async def test_infrastructure_error_during_update_session(
        self,
        use_case: AbortUploadUseCase,
        mock_session_store: AsyncMock,
        mock_rate_limiter: AsyncMock,
        sample_workspace_id: UUID,
        sample_session_id: UUID,
        sample_session: UploadSession,
    ) -> None:
        """Test that InfrastructureError is raised when update_session fails."""
        # Arrange: get_session succeeds, update_session fails
        mock_session_store.get_session.return_value = sample_session
        mock_session_store.update_session.side_effect = InfrastructureError("Redis write timeout")

        # Act & Assert: Raises InfrastructureError
        with pytest.raises(InfrastructureError) as exc_info:
            await use_case.execute(sample_workspace_id, sample_session_id)

        # Assert: Error message preserved
        assert "Redis write timeout" in str(exc_info.value)

        # Assert: delete_session and decrement NOT called (update failed)
        mock_session_store.delete_session.assert_not_called()
        mock_rate_limiter.decrement.assert_not_called()

    @pytest.mark.asyncio
    async def test_infrastructure_error_during_delete_session(
        self,
        use_case: AbortUploadUseCase,
        mock_session_store: AsyncMock,
        mock_rate_limiter: AsyncMock,
        sample_workspace_id: UUID,
        sample_session_id: UUID,
        sample_session: UploadSession,
    ) -> None:
        """Test that InfrastructureError is raised when delete_session fails."""
        # Arrange: get_session and update_session succeed, delete_session fails
        mock_session_store.get_session.return_value = sample_session
        mock_session_store.delete_session.side_effect = InfrastructureError("Redis delete failed")

        # Act & Assert: Raises InfrastructureError
        with pytest.raises(InfrastructureError) as exc_info:
            await use_case.execute(sample_workspace_id, sample_session_id)

        # Assert: Error message preserved
        assert "Redis delete failed" in str(exc_info.value)

        # Assert: update_session WAS called (before delete failed)
        mock_session_store.update_session.assert_called_once()

        # Assert: decrement NOT called (delete failed before decrement)
        mock_rate_limiter.decrement.assert_not_called()

    @pytest.mark.asyncio
    async def test_infrastructure_error_during_decrement(
        self,
        use_case: AbortUploadUseCase,
        mock_session_store: AsyncMock,
        mock_rate_limiter: AsyncMock,
        sample_workspace_id: UUID,
        sample_session_id: UUID,
        sample_session: UploadSession,
    ) -> None:
        """Test partial success when decrement fails - session deleted, counter leaked.

        Per code review finding P-4: If decrement fails after successful delete,
        use case accepts partial success (session cleanup succeeded). Counter leak
        is logged at infrastructure layer and monitored via metrics (Epic 6).
        """
        # Arrange: All session store operations succeed, decrement fails
        mock_session_store.get_session.return_value = sample_session
        mock_rate_limiter.decrement.side_effect = InfrastructureError(
            "Redis counter decrement failed"
        )

        # Act: Execute use case - should complete successfully despite decrement error
        result = await use_case.execute(sample_workspace_id, sample_session_id)

        # Assert: Use case completes successfully (partial success acceptable)
        assert result is None

        # Assert: All session store operations were called successfully
        mock_session_store.get_session.assert_called_once()
        mock_session_store.update_session.assert_called_once()
        mock_session_store.delete_session.assert_called_once()

        # Assert: Decrement was attempted (even though it failed)
        mock_rate_limiter.decrement.assert_called_once_with(sample_workspace_id)


class TestAbortUploadUseCaseEdgeCases:
    """Test suite for edge cases and defensive scenarios."""

    @pytest.mark.asyncio
    async def test_abort_session_with_in_progress_status(
        self,
        use_case: AbortUploadUseCase,
        mock_session_store: AsyncMock,
        mock_rate_limiter: AsyncMock,
        sample_workspace_id: UUID,
        sample_session_id: UUID,
        sample_session: UploadSession,
    ) -> None:
        """Test aborting a session that is IN_PROGRESS."""
        # Arrange: Session with IN_PROGRESS status
        sample_session.status = SessionStatus.IN_PROGRESS
        mock_session_store.get_session.return_value = sample_session

        # Act
        await use_case.execute(sample_workspace_id, sample_session_id)

        # Assert: Status updated to ABORTED
        updated_session = mock_session_store.update_session.call_args[0][0]
        assert updated_session.status == SessionStatus.ABORTED

        # Assert: All cleanup operations called
        mock_session_store.delete_session.assert_called_once()
        mock_rate_limiter.decrement.assert_called_once()

    @pytest.mark.asyncio
    async def test_abort_session_with_partial_upload(
        self,
        use_case: AbortUploadUseCase,
        mock_session_store: AsyncMock,
        mock_rate_limiter: AsyncMock,
        sample_workspace_id: UUID,
        sample_session_id: UUID,
        sample_session: UploadSession,
    ) -> None:
        """Test aborting a session with partial upload progress."""
        # Arrange: Session with some chunks uploaded
        sample_session.offset = 524288  # 512 KB uploaded
        sample_session.status = SessionStatus.IN_PROGRESS
        mock_session_store.get_session.return_value = sample_session

        # Act
        await use_case.execute(sample_workspace_id, sample_session_id)

        # Assert: All cleanup operations called regardless of offset
        mock_session_store.update_session.assert_called_once()
        mock_session_store.delete_session.assert_called_once()
        mock_rate_limiter.decrement.assert_called_once()
