"""Unit tests for InitiateUploadUseCase.

Tests verify use case orchestration including rate limiting, validation,
session creation, and error handling with counter cleanup.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from src.application.dto.upload_request import InitiateUploadRequest
from src.application.dto.upload_response import InitiateUploadResponse
from src.application.use_cases.initiate_upload import InitiateUploadUseCase
from src.domain.entities.upload_session import (
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE_BYTES,
    UploadSession,
)
from src.domain.exceptions import (
    FileSizeLimitExceededError,
    InfrastructureError,
    RateLimitExceededError,
    UnsupportedMediaTypeError,
)
from src.domain.value_objects.session_status import SessionStatus
from src.domain.value_objects.sha256_hash import SHA256Hash


@pytest.fixture
def mock_rate_limiter() -> AsyncMock:
    """Create mock IRateLimiter protocol."""
    limiter = AsyncMock()
    limiter.check_and_increment = AsyncMock()
    limiter.decrement = AsyncMock()
    limiter.get_current_count = AsyncMock(return_value=0)
    return limiter


@pytest.fixture
def mock_session_store() -> AsyncMock:
    """Create mock ISessionStore protocol."""
    store = AsyncMock()
    store.create_session = AsyncMock()
    return store


@pytest.fixture
def use_case(
    mock_rate_limiter: AsyncMock,
    mock_session_store: AsyncMock,
) -> InitiateUploadUseCase:
    """Create InitiateUploadUseCase with mocked dependencies."""
    return InitiateUploadUseCase(
        rate_limiter=mock_rate_limiter,
        session_store=mock_session_store,
    )


@pytest.fixture
def sample_workspace_id() -> UUID:
    """Create sample workspace UUID for testing."""
    return uuid4()


@pytest.fixture
def valid_request(sample_workspace_id: UUID) -> InitiateUploadRequest:
    """Create valid InitiateUploadRequest for testing."""
    return InitiateUploadRequest(
        workspace_id=sample_workspace_id,
        filename="document.pdf",
        size=1_048_576,  # 1 MB
        mime_type="application/pdf",
        sha256_checksum="a" * 64,
    )


class TestInitiateUploadUseCaseHappyPath:
    """Test suite for successful use case execution."""

    @pytest.mark.asyncio
    async def test_successful_session_creation(
        self,
        use_case: InitiateUploadUseCase,
        mock_rate_limiter: AsyncMock,
        mock_session_store: AsyncMock,
        valid_request: InitiateUploadRequest,
        sample_workspace_id: UUID,
    ) -> None:
        """Test successful upload session creation with valid request."""
        # Act
        response = await use_case.execute(valid_request)

        # Assert: Rate limiter called first
        mock_rate_limiter.check_and_increment.assert_called_once_with(sample_workspace_id)

        # Assert: Session store called with UploadSession
        mock_session_store.create_session.assert_called_once()
        created_session = mock_session_store.create_session.call_args[0][0]
        assert isinstance(created_session, UploadSession)

        # Assert: Response structure
        assert isinstance(response, InitiateUploadResponse)
        assert isinstance(response.session_id, UUID)
        assert response.offset == 0
        assert isinstance(response.expires_at, datetime)

        # Assert: Rate limiter NOT decremented (success case)
        mock_rate_limiter.decrement.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_fields_are_correct(
        self,
        use_case: InitiateUploadUseCase,
        mock_session_store: AsyncMock,
        valid_request: InitiateUploadRequest,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that created session has all required fields set correctly."""
        # Act
        await use_case.execute(valid_request)

        # Assert: Verify session fields
        created_session: UploadSession = mock_session_store.create_session.call_args[0][0]

        assert isinstance(created_session.session_id, UUID)
        assert created_session.workspace_id == sample_workspace_id
        assert created_session.filename == "document.pdf"
        assert created_session.size == 1_048_576
        assert created_session.mime_type == "application/pdf"
        assert isinstance(created_session.sha256_checksum, SHA256Hash)
        assert created_session.sha256_checksum.value == "a" * 64
        assert created_session.offset == 0
        assert created_session.status == SessionStatus.PENDING
        assert created_session.chunk_manifest == []

    @pytest.mark.asyncio
    async def test_timestamps_are_utc_timezone_aware(
        self,
        use_case: InitiateUploadUseCase,
        mock_session_store: AsyncMock,
        valid_request: InitiateUploadRequest,
    ) -> None:
        """Test that created_at and expires_at are timezone-aware UTC."""
        # Act
        before_execution = datetime.now(UTC)
        await use_case.execute(valid_request)
        after_execution = datetime.now(UTC)

        # Assert: Verify timestamps
        created_session: UploadSession = mock_session_store.create_session.call_args[0][0]

        # created_at should be between before/after execution
        assert created_session.created_at.tzinfo == UTC
        assert before_execution <= created_session.created_at <= after_execution

        # expires_at should be 24 hours after created_at
        expected_expires = created_session.created_at + timedelta(hours=24)
        assert created_session.expires_at == expected_expires
        assert created_session.expires_at.tzinfo == UTC

    @pytest.mark.asyncio
    async def test_session_id_is_uuid_v4(
        self,
        use_case: InitiateUploadUseCase,
        mock_session_store: AsyncMock,
        valid_request: InitiateUploadRequest,
    ) -> None:
        """Test that session_id is generated as UUID v4 (cryptographically random)."""
        # Act
        await use_case.execute(valid_request)

        # Assert: Verify UUID version
        created_session: UploadSession = mock_session_store.create_session.call_args[0][0]
        assert created_session.session_id.version == 4

    @pytest.mark.asyncio
    async def test_multiple_calls_generate_unique_session_ids(
        self,
        use_case: InitiateUploadUseCase,
        mock_session_store: AsyncMock,
        valid_request: InitiateUploadRequest,
    ) -> None:
        """Test that multiple calls generate unique session IDs."""
        # Act: Execute use case twice
        response1 = await use_case.execute(valid_request)
        response2 = await use_case.execute(valid_request)

        # Assert: Session IDs are different
        assert response1.session_id != response2.session_id


class TestInitiateUploadUseCaseRateLimitExceeded:
    """Test suite for rate limit exceeded scenarios."""

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_propagates_exception(
        self,
        use_case: InitiateUploadUseCase,
        mock_rate_limiter: AsyncMock,
        mock_session_store: AsyncMock,
        valid_request: InitiateUploadRequest,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that RateLimitExceededError propagates when workspace at limit."""
        # Arrange: Rate limiter raises RateLimitExceededError
        mock_rate_limiter.check_and_increment.side_effect = RateLimitExceededError(
            workspace_id=str(sample_workspace_id),
            current_count=10,
            limit=10,
            retry_after_seconds=60,
        )

        # Act & Assert: Exception propagates
        with pytest.raises(RateLimitExceededError) as exc_info:
            await use_case.execute(valid_request)

        # Assert: Exception details
        assert exc_info.value.workspace_id == str(sample_workspace_id)
        assert exc_info.value.current_count == 10
        assert exc_info.value.limit == 10
        assert exc_info.value.retry_after_seconds == 60

        # Assert: Session store NOT called (fail fast)
        mock_session_store.create_session.assert_not_called()

        # Assert: Rate limiter NOT decremented (never incremented)
        mock_rate_limiter.decrement.assert_not_called()


class TestInitiateUploadUseCaseValidationErrors:
    """Test suite for file size and MIME type validation errors."""

    @pytest.mark.asyncio
    async def test_file_size_exceeds_limit(
        self,
        use_case: InitiateUploadUseCase,
        mock_rate_limiter: AsyncMock,
        mock_session_store: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that file size > 1 GB raises FileSizeLimitExceededError."""
        # Arrange: Request with file size over limit
        over_limit_size = MAX_FILE_SIZE_BYTES + 1
        request = InitiateUploadRequest(
            workspace_id=sample_workspace_id,
            filename="large.pdf",
            size=over_limit_size,
            mime_type="application/pdf",
            sha256_checksum="a" * 64,
        )

        # Act & Assert: Exception raised
        with pytest.raises(FileSizeLimitExceededError) as exc_info:
            await use_case.execute(request)

        # Assert: Exception details
        assert exc_info.value.file_size == over_limit_size
        assert exc_info.value.max_size == MAX_FILE_SIZE_BYTES

        # Assert: Session store NOT called (validation failed)
        mock_session_store.create_session.assert_not_called()

        # Assert: Rate limiter NOT called (validation failed before rate limit check)
        mock_rate_limiter.check_and_increment.assert_not_called()
        mock_rate_limiter.decrement.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsupported_mime_type(
        self,
        use_case: InitiateUploadUseCase,
        mock_rate_limiter: AsyncMock,
        mock_session_store: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that non-PDF MIME type raises UnsupportedMediaTypeError."""
        # Arrange: Request with JSON MIME type
        request = InitiateUploadRequest(
            workspace_id=sample_workspace_id,
            filename="data.json",
            size=1024,
            mime_type="application/json",
            sha256_checksum="a" * 64,
        )

        # Act & Assert: Exception raised
        with pytest.raises(UnsupportedMediaTypeError) as exc_info:
            await use_case.execute(request)

        # Assert: Exception details
        assert exc_info.value.provided_mime_type == "application/json"
        assert exc_info.value.allowed_mime_types == ALLOWED_MIME_TYPES

        # Assert: Session store NOT called (validation failed)
        mock_session_store.create_session.assert_not_called()

        # Assert: Rate limiter NOT called (validation failed before rate limit check)
        mock_rate_limiter.check_and_increment.assert_not_called()
        mock_rate_limiter.decrement.assert_not_called()


class TestInitiateUploadUseCaseInfrastructureError:
    """Test suite for infrastructure failure scenarios with counter cleanup."""

    @pytest.mark.asyncio
    async def test_session_store_failure_decrements_counter(
        self,
        use_case: InitiateUploadUseCase,
        mock_rate_limiter: AsyncMock,
        mock_session_store: AsyncMock,
        valid_request: InitiateUploadRequest,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that session store failure triggers counter decrement."""
        # Arrange: Session store raises InfrastructureError
        mock_session_store.create_session.side_effect = InfrastructureError(
            "Redis connection timeout"
        )

        # Act & Assert: Exception propagates
        with pytest.raises(InfrastructureError, match="Redis connection timeout"):
            await use_case.execute(valid_request)

        # Assert: Rate limiter called first
        mock_rate_limiter.check_and_increment.assert_called_once_with(sample_workspace_id)

        # Assert: Session store was attempted
        mock_session_store.create_session.assert_called_once()

        # Assert: Rate limiter decremented (cleanup after infrastructure failure)
        mock_rate_limiter.decrement.assert_called_once_with(sample_workspace_id)

    @pytest.mark.asyncio
    async def test_decrement_called_exactly_once_on_failure(
        self,
        use_case: InitiateUploadUseCase,
        mock_rate_limiter: AsyncMock,
        mock_session_store: AsyncMock,
        valid_request: InitiateUploadRequest,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that decrement is called exactly once even if store fails multiple times."""
        # Arrange: Session store raises InfrastructureError
        mock_session_store.create_session.side_effect = InfrastructureError("Connection failed")

        # Act & Assert: First call
        with pytest.raises(InfrastructureError):
            await use_case.execute(valid_request)

        # Assert: Decrement called once
        assert mock_rate_limiter.decrement.call_count == 1

        # Reset mock
        mock_rate_limiter.reset_mock()

        # Act & Assert: Second call (new execution)
        with pytest.raises(InfrastructureError):
            await use_case.execute(valid_request)

        # Assert: Decrement called once again (independent execution)
        assert mock_rate_limiter.decrement.call_count == 1


class TestInitiateUploadUseCaseExecutionOrder:
    """Test suite for verifying execution order of operations."""

    @pytest.mark.asyncio
    async def test_rate_limit_check_happens_first(
        self,
        use_case: InitiateUploadUseCase,
        mock_rate_limiter: AsyncMock,
        mock_session_store: AsyncMock,
        valid_request: InitiateUploadRequest,
    ) -> None:
        """Test that rate limit check is the first operation (fail fast)."""
        # Arrange: Track call order
        call_order = []

        async def track_rate_limiter(*args, **kwargs):
            call_order.append("rate_limiter")

        async def track_session_store(*args, **kwargs):
            call_order.append("session_store")

        mock_rate_limiter.check_and_increment.side_effect = track_rate_limiter
        mock_session_store.create_session.side_effect = track_session_store

        # Act
        await use_case.execute(valid_request)

        # Assert: Rate limiter called before session store
        assert call_order == ["rate_limiter", "session_store"]

    @pytest.mark.asyncio
    async def test_validation_happens_before_rate_limit_check(
        self,
        use_case: InitiateUploadUseCase,
        mock_rate_limiter: AsyncMock,
        mock_session_store: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that validation happens before rate limit check (fail fast)."""
        # Arrange: Invalid request (over size limit)
        request = InitiateUploadRequest(
            workspace_id=sample_workspace_id,
            filename="large.pdf",
            size=MAX_FILE_SIZE_BYTES + 1,
            mime_type="application/pdf",
            sha256_checksum="a" * 64,
        )

        # Act & Assert: Validation error raised
        with pytest.raises(FileSizeLimitExceededError):
            await use_case.execute(request)

        # Assert: Rate limiter NOT called (validation failed first)
        mock_rate_limiter.check_and_increment.assert_not_called()
        mock_rate_limiter.decrement.assert_not_called()
