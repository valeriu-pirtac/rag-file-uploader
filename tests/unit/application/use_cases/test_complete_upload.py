"""Unit tests for CompleteUploadUseCase.

Tests verify complete upload orchestration including session validation, chunk
manifest validation, file assembly, deduplication, event publication, and
session lifecycle management.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from src.application.dto.complete_upload_request import CompleteUploadRequest
from src.application.dto.complete_upload_response import CompleteUploadResponse
from src.application.use_cases.complete_upload import CompleteUploadUseCase
from src.domain.entities.events import FileLoadCompletedEvent
from src.domain.entities.upload_session import UploadSession
from src.domain.exceptions import (
    DuplicateFileError,
    InfrastructureError,
    IntegrityError,
    InvalidSessionStateError,
    SessionNotFoundError,
    WorkspaceMismatchError,
)
from src.domain.protocols.deduplication_store import FileMetadata
from src.domain.value_objects.session_status import SessionStatus
from src.domain.value_objects.sha256_hash import SHA256Hash


@pytest.fixture
def mock_session_store() -> AsyncMock:
    """Create mock ISessionStore protocol."""
    store = AsyncMock()
    store.get_session = AsyncMock()
    store.update_session = AsyncMock()
    return store


@pytest.fixture
def mock_storage_client() -> AsyncMock:
    """Create mock IStorageClient protocol."""
    client = AsyncMock()
    client.assemble_file = AsyncMock()
    return client


@pytest.fixture
def mock_dedup_store() -> AsyncMock:
    """Create mock IDeduplicationStore protocol."""
    store = AsyncMock()
    store.check_duplicate = AsyncMock()
    store.register_file = AsyncMock()
    return store


@pytest.fixture
def mock_event_publisher() -> AsyncMock:
    """Create mock IEventPublisher protocol."""
    publisher = AsyncMock()
    publisher.publish = AsyncMock()
    return publisher


@pytest.fixture
def mock_rate_limiter() -> AsyncMock:
    """Create mock IRateLimiter protocol."""
    limiter = AsyncMock()
    limiter.decrement = AsyncMock()
    return limiter


@pytest.fixture
def mock_redis_client() -> AsyncMock:
    """Create mock Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock()
    redis.delete = AsyncMock()
    return redis


@pytest.fixture
def use_case(
    mock_session_store: AsyncMock,
    mock_storage_client: AsyncMock,
    mock_dedup_store: AsyncMock,
    mock_event_publisher: AsyncMock,
    mock_rate_limiter: AsyncMock,
    mock_redis_client: AsyncMock,
) -> CompleteUploadUseCase:
    """Create CompleteUploadUseCase with mocked dependencies."""
    return CompleteUploadUseCase(
        session_store=mock_session_store,
        storage_client=mock_storage_client,
        dedup_store=mock_dedup_store,
        event_publisher=mock_event_publisher,
        rate_limiter=mock_rate_limiter,
        redis_client=mock_redis_client,
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
def sample_sha256() -> SHA256Hash:
    """Create sample SHA256 hash for testing."""
    return SHA256Hash("a" * 64)


@pytest.fixture
def sample_session(
    sample_workspace_id: UUID,
    sample_session_id: UUID,
    sample_sha256: SHA256Hash,
) -> UploadSession:
    """Create sample UploadSession for testing with complete manifest."""
    now = datetime.now(UTC)
    chunk_manifest = [
        {"index": 0, "size": 5242880, "checksum": "chunk0hash"},
        {"index": 1, "size": 5242880, "checksum": "chunk1hash"},
        {"index": 2, "size": 2621440, "checksum": "chunk2hash"},  # Last chunk smaller
    ]
    total_size = sum(c["size"] for c in chunk_manifest)

    return UploadSession(
        session_id=sample_session_id,
        workspace_id=sample_workspace_id,
        filename="document.pdf",
        size=total_size,  # 13107200 bytes (~12.5 MB)
        mime_type="application/pdf",
        sha256_checksum=sample_sha256,
        offset=total_size,  # All bytes uploaded
        status=SessionStatus.IN_PROGRESS,
        created_at=now,
        expires_at=now + timedelta(hours=24),
        chunk_manifest=chunk_manifest,
    )


@pytest.fixture
def sample_request(
    sample_workspace_id: UUID,
    sample_session_id: UUID,
) -> CompleteUploadRequest:
    """Create sample CompleteUploadRequest for testing."""
    return CompleteUploadRequest(
        workspace_id=sample_workspace_id,
        session_id=sample_session_id,
    )


@pytest.fixture
def sample_chunks() -> list[bytes]:
    """Create sample chunk data matching sample_session manifest."""
    return [
        b"x" * 5242880,  # Chunk 0: 5 MB
        b"y" * 5242880,  # Chunk 1: 5 MB
        b"z" * 2621440,  # Chunk 2: 2.5 MB
    ]


class TestCompleteUploadUseCaseHappyPath:
    """Test suite for successful use case execution."""

    @pytest.mark.asyncio
    async def test_successful_complete_upload(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        mock_storage_client: AsyncMock,
        mock_dedup_store: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_rate_limiter: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
        sample_chunks: list[bytes],
    ) -> None:
        """Test successful complete upload with all orchestration steps."""
        # Arrange
        mock_session_store.get_session.return_value = sample_session

        # Mock Redis chunk retrieval
        async def mock_redis_get(key: str):
            if "index_0" in key:
                return sample_chunks[0]
            elif "index_1" in key:
                return sample_chunks[1]
            elif "index_2" in key:
                return sample_chunks[2]
            return None

        mock_redis_client.get.side_effect = mock_redis_get

        # Mock S3 assembly
        s3_path = (
            f"s3://bucket/workspace_{sample_session.workspace_id}/{sample_session.session_id}.pdf"
        )
        mock_storage_client.assemble_file.return_value = (s3_path, sample_session.size)

        # Mock dedup check (no duplicate)
        mock_dedup_store.check_duplicate.return_value = None

        # Act
        response = await use_case.execute(sample_request)

        # Assert: Response is correct
        assert isinstance(response, CompleteUploadResponse)
        assert response.file_id == sample_session.session_id
        assert response.s3_path == s3_path
        assert response.size_bytes == sample_session.size

        # Assert: Session retrieved
        mock_session_store.get_session.assert_called_once_with(
            sample_request.workspace_id, sample_request.session_id
        )

        # Assert: Chunks retrieved from Redis (3 chunks)
        assert mock_redis_client.get.call_count == 3

        # Assert: File assembled
        mock_storage_client.assemble_file.assert_called_once()
        assembly_call = mock_storage_client.assemble_file.call_args
        assert assembly_call[1]["workspace_id"] == sample_session.workspace_id
        assert assembly_call[1]["file_id"] == sample_session.session_id
        assert len(assembly_call[1]["chunk_data"]) == 3
        assert assembly_call[1]["expected_checksum"] == sample_session.sha256_checksum

        # Assert: Dedup check performed
        mock_dedup_store.check_duplicate.assert_called_once_with(
            sample_session.workspace_id, sample_session.sha256_checksum
        )

        # Assert: Event published
        mock_event_publisher.publish.assert_called_once()
        published_event = mock_event_publisher.publish.call_args[0][0]
        assert isinstance(published_event, FileLoadCompletedEvent)
        assert published_event.file_id == sample_session.session_id
        assert published_event.workspace_id == sample_session.workspace_id
        assert published_event.s3_path == s3_path

        # Assert: Session marked COMPLETE
        assert mock_session_store.update_session.call_count >= 1
        final_session = mock_session_store.update_session.call_args_list[-1][0][0]
        assert final_session.status == SessionStatus.COMPLETE

        # Assert: Rate limiter decremented
        mock_rate_limiter.decrement.assert_called_once_with(sample_session.workspace_id)

        # Assert: Dedup fingerprint registered
        mock_dedup_store.register_file.assert_called_once()
        register_call = mock_dedup_store.register_file.call_args
        assert register_call[0][0] == sample_session.workspace_id
        assert register_call[0][1] == sample_session.sha256_checksum
        assert isinstance(register_call[0][2], FileMetadata)

        # Assert: Chunks cleaned up
        assert mock_redis_client.delete.call_count == 3


class TestCompleteUploadUseCaseSessionValidation:
    """Test suite for session validation errors."""

    @pytest.mark.asyncio
    async def test_session_not_found(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        sample_request: CompleteUploadRequest,
    ) -> None:
        """Test error when session does not exist."""
        # Arrange
        mock_session_store.get_session.return_value = None

        # Act & Assert
        with pytest.raises(SessionNotFoundError):
            await use_case.execute(sample_request)

    @pytest.mark.asyncio
    async def test_workspace_mismatch(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
    ) -> None:
        """Test error when session belongs to different workspace."""
        # Arrange
        different_workspace_id = uuid4()
        sample_session.workspace_id = different_workspace_id
        mock_session_store.get_session.return_value = sample_session

        # Act & Assert
        with pytest.raises(WorkspaceMismatchError):
            await use_case.execute(sample_request)

    @pytest.mark.asyncio
    async def test_invalid_session_status_pending(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
    ) -> None:
        """Test error when session is still PENDING."""
        # Arrange
        sample_session.status = SessionStatus.PENDING
        mock_session_store.get_session.return_value = sample_session

        # Act & Assert
        with pytest.raises(InvalidSessionStateError):
            await use_case.execute(sample_request)

    @pytest.mark.asyncio
    async def test_invalid_session_status_complete(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
    ) -> None:
        """Test error when session is already COMPLETE."""
        # Arrange
        sample_session.status = SessionStatus.COMPLETE
        mock_session_store.get_session.return_value = sample_session

        # Act & Assert
        with pytest.raises(InvalidSessionStateError):
            await use_case.execute(sample_request)

    @pytest.mark.asyncio
    async def test_invalid_session_status_failed(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
    ) -> None:
        """Test error when session is FAILED."""
        # Arrange
        sample_session.status = SessionStatus.FAILED
        mock_session_store.get_session.return_value = sample_session

        # Act & Assert
        with pytest.raises(InvalidSessionStateError):
            await use_case.execute(sample_request)


class TestCompleteUploadUseCaseChunkManifestValidation:
    """Test suite for chunk manifest validation."""

    @pytest.mark.asyncio
    async def test_chunk_manifest_empty(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
    ) -> None:
        """Test error when chunk manifest is empty."""
        # Arrange
        sample_session.chunk_manifest = []
        mock_session_store.get_session.return_value = sample_session

        # Act & Assert
        with pytest.raises(InvalidSessionStateError) as exc_info:
            await use_case.execute(sample_request)
        assert "chunk_manifest is empty" in str(exc_info.value.current_state)

    @pytest.mark.asyncio
    async def test_chunk_manifest_missing_indices(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
    ) -> None:
        """Test error when chunk manifest has missing indices."""
        # Arrange
        # Manifest with indices 0, 1, 3 (missing 2)
        sample_session.chunk_manifest = [
            {"index": 0, "size": 5242880, "checksum": "hash0"},
            {"index": 1, "size": 5242880, "checksum": "hash1"},
            {"index": 3, "size": 2621440, "checksum": "hash3"},  # Skip index 2
        ]
        mock_session_store.get_session.return_value = sample_session

        # Act & Assert
        with pytest.raises(InvalidSessionStateError) as exc_info:
            await use_case.execute(sample_request)
        assert "missing=" in str(exc_info.value.current_state)

    @pytest.mark.asyncio
    async def test_chunk_manifest_extra_indices(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
    ) -> None:
        """Test error when chunk manifest has extra indices."""
        # Arrange
        # Manifest with indices 0, 1, 2, 5 (extra 5)
        sample_session.chunk_manifest = [
            {"index": 0, "size": 5242880, "checksum": "hash0"},
            {"index": 1, "size": 5242880, "checksum": "hash1"},
            {"index": 2, "size": 2621440, "checksum": "hash2"},
            {"index": 5, "size": 1024, "checksum": "hash5"},  # Extra
        ]
        sample_session.offset = 13107200 + 1024
        sample_session.size = 13107200 + 1024
        mock_session_store.get_session.return_value = sample_session

        # Act & Assert
        with pytest.raises(InvalidSessionStateError) as exc_info:
            await use_case.execute(sample_request)
        assert "extra=" in str(exc_info.value.current_state)

    @pytest.mark.asyncio
    async def test_offset_size_mismatch(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
    ) -> None:
        """Test error when offset != size (upload incomplete)."""
        # Arrange
        sample_session.offset = sample_session.size - 1024  # 1 KB short
        mock_session_store.get_session.return_value = sample_session

        # Act & Assert
        with pytest.raises(InvalidSessionStateError) as exc_info:
            await use_case.execute(sample_request)
        assert "offset=" in str(exc_info.value.current_state)


class TestCompleteUploadUseCaseChunkRetrieval:
    """Test suite for chunk retrieval from Redis."""

    @pytest.mark.asyncio
    async def test_chunk_not_found_in_redis(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
    ) -> None:
        """Test error when chunk data not found in Redis."""
        # Arrange
        mock_session_store.get_session.return_value = sample_session

        # Mock: First chunk exists, second chunk missing
        async def mock_redis_get(key: str):
            if "index_0" in key:
                return b"x" * 5242880
            return None  # Chunk 1 missing

        mock_redis_client.get.side_effect = mock_redis_get

        # Act & Assert
        with pytest.raises(InvalidSessionStateError) as exc_info:
            await use_case.execute(sample_request)
        assert "not found in Redis" in str(exc_info.value.current_state)


class TestCompleteUploadUseCaseFileAssembly:
    """Test suite for file assembly errors."""

    @pytest.mark.asyncio
    async def test_file_assembly_integrity_error(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        mock_storage_client: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
        sample_chunks: list[bytes],
    ) -> None:
        """Test error when file assembly checksum validation fails."""
        # Arrange
        mock_session_store.get_session.return_value = sample_session

        async def mock_redis_get(key: str):
            if "index_0" in key:
                return sample_chunks[0]
            elif "index_1" in key:
                return sample_chunks[1]
            elif "index_2" in key:
                return sample_chunks[2]
            return None

        mock_redis_client.get.side_effect = mock_redis_get

        # Mock: S3 assembly raises IntegrityError
        mock_storage_client.assemble_file.side_effect = IntegrityError(
            message="Checksum mismatch after assembly",
            expected_checksum="a" * 64,
            computed_checksum="b" * 64,
            file_id=sample_session.session_id,
        )

        # Act & Assert
        with pytest.raises(IntegrityError):
            await use_case.execute(sample_request)

        # Assert: Session marked FAILED
        assert mock_session_store.update_session.called

    @pytest.mark.asyncio
    async def test_file_assembly_infrastructure_error(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        mock_storage_client: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
        sample_chunks: list[bytes],
    ) -> None:
        """Test error when S3 connection fails during assembly."""
        # Arrange
        mock_session_store.get_session.return_value = sample_session

        async def mock_redis_get(key: str):
            if "index_0" in key:
                return sample_chunks[0]
            elif "index_1" in key:
                return sample_chunks[1]
            elif "index_2" in key:
                return sample_chunks[2]
            return None

        mock_redis_client.get.side_effect = mock_redis_get

        # Mock: S3 connection failure
        mock_storage_client.assemble_file.side_effect = InfrastructureError("S3 connection timeout")

        # Act & Assert
        with pytest.raises(InfrastructureError):
            await use_case.execute(sample_request)


class TestCompleteUploadUseCaseDeduplication:
    """Test suite for deduplication detection."""

    @pytest.mark.asyncio
    async def test_duplicate_file_detected(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        mock_storage_client: AsyncMock,
        mock_dedup_store: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
        sample_chunks: list[bytes],
    ) -> None:
        """Test error when duplicate file is detected."""
        # Arrange
        mock_session_store.get_session.return_value = sample_session

        async def mock_redis_get(key: str):
            if "index_0" in key:
                return sample_chunks[0]
            elif "index_1" in key:
                return sample_chunks[1]
            elif "index_2" in key:
                return sample_chunks[2]
            return None

        mock_redis_client.get.side_effect = mock_redis_get

        s3_path = (
            f"s3://bucket/workspace_{sample_session.workspace_id}/{sample_session.session_id}.pdf"
        )
        mock_storage_client.assemble_file.return_value = (s3_path, sample_session.size)

        # Mock: Duplicate detected
        existing_file_id = uuid4()
        duplicate_metadata = FileMetadata(
            file_id=existing_file_id,
            s3_path=f"s3://bucket/workspace_{sample_session.workspace_id}/{existing_file_id}.pdf",
            size=sample_session.size,
            uploaded_at=datetime.now(UTC),
        )
        mock_dedup_store.check_duplicate.return_value = duplicate_metadata

        # Act & Assert
        with pytest.raises(DuplicateFileError) as exc_info:
            await use_case.execute(sample_request)

        assert exc_info.value.existing_file_id == existing_file_id

        # Assert: Session marked FAILED
        assert mock_session_store.update_session.called
        failed_session = mock_session_store.update_session.call_args[0][0]
        assert failed_session.status == SessionStatus.FAILED


class TestCompleteUploadUseCaseEventPublication:
    """Test suite for event publication errors."""

    @pytest.mark.asyncio
    async def test_event_publish_failure(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        mock_storage_client: AsyncMock,
        mock_dedup_store: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
        sample_chunks: list[bytes],
    ) -> None:
        """Test error when event publishing fails after max retries."""
        # Arrange
        mock_session_store.get_session.return_value = sample_session

        async def mock_redis_get(key: str):
            if "index_0" in key:
                return sample_chunks[0]
            elif "index_1" in key:
                return sample_chunks[1]
            elif "index_2" in key:
                return sample_chunks[2]
            return None

        mock_redis_client.get.side_effect = mock_redis_get

        s3_path = (
            f"s3://bucket/workspace_{sample_session.workspace_id}/{sample_session.session_id}.pdf"
        )
        mock_storage_client.assemble_file.return_value = (s3_path, sample_session.size)
        mock_dedup_store.check_duplicate.return_value = None

        # Mock: Event publish fails after retries
        mock_event_publisher.publish.side_effect = InfrastructureError(
            "NATS publish failed after max retries"
        )

        # Act & Assert
        with pytest.raises(InfrastructureError):
            await use_case.execute(sample_request)

        # Assert: Session marked FAILED (NOT COMPLETE)
        assert mock_session_store.update_session.called
        failed_session = mock_session_store.update_session.call_args[0][0]
        assert failed_session.status == SessionStatus.FAILED


class TestCompleteUploadUseCaseGracefulFailures:
    """Test suite for best-effort cleanup operations."""

    @pytest.mark.asyncio
    async def test_rate_limit_decrement_failure_does_not_fail_completion(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        mock_storage_client: AsyncMock,
        mock_dedup_store: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_rate_limiter: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
        sample_chunks: list[bytes],
    ) -> None:
        """Test that rate limit decrement failure does not fail completion."""
        # Arrange
        mock_session_store.get_session.return_value = sample_session

        async def mock_redis_get(key: str):
            if "index_0" in key:
                return sample_chunks[0]
            elif "index_1" in key:
                return sample_chunks[1]
            elif "index_2" in key:
                return sample_chunks[2]
            return None

        mock_redis_client.get.side_effect = mock_redis_get

        s3_path = (
            f"s3://bucket/workspace_{sample_session.workspace_id}/{sample_session.session_id}.pdf"
        )
        mock_storage_client.assemble_file.return_value = (s3_path, sample_session.size)
        mock_dedup_store.check_duplicate.return_value = None

        # Mock: Rate limiter fails
        mock_rate_limiter.decrement.side_effect = InfrastructureError("Redis connection failed")

        # Act - Should NOT raise exception
        response = await use_case.execute(sample_request)

        # Assert: Completion succeeds despite rate limiter failure
        assert response.file_id == sample_session.session_id
        assert response.s3_path == s3_path

    @pytest.mark.asyncio
    async def test_dedup_registration_failure_does_not_fail_completion(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        mock_storage_client: AsyncMock,
        mock_dedup_store: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_rate_limiter: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
        sample_chunks: list[bytes],
    ) -> None:
        """Test that dedup registration failure does not fail completion."""
        # Arrange
        mock_session_store.get_session.return_value = sample_session

        async def mock_redis_get(key: str):
            if "index_0" in key:
                return sample_chunks[0]
            elif "index_1" in key:
                return sample_chunks[1]
            elif "index_2" in key:
                return sample_chunks[2]
            return None

        mock_redis_client.get.side_effect = mock_redis_get

        s3_path = (
            f"s3://bucket/workspace_{sample_session.workspace_id}/{sample_session.session_id}.pdf"
        )
        mock_storage_client.assemble_file.return_value = (s3_path, sample_session.size)
        mock_dedup_store.check_duplicate.return_value = None

        # Mock: Dedup registration fails
        mock_dedup_store.register_file.side_effect = InfrastructureError("Redis connection failed")

        # Act - Should NOT raise exception
        response = await use_case.execute(sample_request)

        # Assert: Completion succeeds despite dedup registration failure
        assert response.file_id == sample_session.session_id
        assert response.s3_path == s3_path

    @pytest.mark.asyncio
    async def test_chunk_cleanup_failure_does_not_fail_completion(
        self,
        use_case: CompleteUploadUseCase,
        mock_session_store: AsyncMock,
        mock_storage_client: AsyncMock,
        mock_dedup_store: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_rate_limiter: AsyncMock,
        mock_redis_client: AsyncMock,
        sample_request: CompleteUploadRequest,
        sample_session: UploadSession,
        sample_chunks: list[bytes],
    ) -> None:
        """Test that chunk cleanup failure does not fail completion."""
        # Arrange
        mock_session_store.get_session.return_value = sample_session

        async def mock_redis_get(key: str):
            if "index_0" in key:
                return sample_chunks[0]
            elif "index_1" in key:
                return sample_chunks[1]
            elif "index_2" in key:
                return sample_chunks[2]
            return None

        mock_redis_client.get.side_effect = mock_redis_get

        s3_path = (
            f"s3://bucket/workspace_{sample_session.workspace_id}/{sample_session.session_id}.pdf"
        )
        mock_storage_client.assemble_file.return_value = (s3_path, sample_session.size)
        mock_dedup_store.check_duplicate.return_value = None

        # Mock: Chunk delete fails
        mock_redis_client.delete.side_effect = Exception("Redis connection failed")

        # Act - Should NOT raise exception
        response = await use_case.execute(sample_request)

        # Assert: Completion succeeds despite chunk cleanup failure
        assert response.file_id == sample_session.session_id
        assert response.s3_path == s3_path
