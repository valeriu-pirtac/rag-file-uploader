"""Unit tests for ProcessChunkUseCase.

Tests verify use case orchestration including session retrieval, offset validation,
SHA-256 verification, chunk tracking, and session state updates.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest

from src.application.dto.process_chunk_request import ProcessChunkRequest
from src.application.dto.process_chunk_response import ProcessChunkResponse
from src.application.use_cases.process_chunk import ProcessChunkUseCase
from src.domain.entities.upload_session import UploadSession
from src.domain.exceptions import (
    ChecksumMismatchError,
    InfrastructureError,
    InvalidSessionStateError,
    OffsetMismatchError,
    SessionNotFoundError,
)
from src.domain.services.chunk_verifier import ChunkVerifier
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
def mock_chunk_verifier() -> Mock:
    """Create mock ChunkVerifier service."""
    verifier = Mock(spec=ChunkVerifier)
    verifier.verify_chunk = Mock()
    return verifier


@pytest.fixture
def mock_redis_client() -> AsyncMock:
    """Create mock Redis client."""
    redis = AsyncMock()
    redis.set = AsyncMock()
    return redis


@pytest.fixture
def use_case(
    mock_session_store: AsyncMock,
    mock_chunk_verifier: Mock,
    mock_redis_client: AsyncMock,
) -> ProcessChunkUseCase:
    """Create ProcessChunkUseCase with mocked dependencies."""
    return ProcessChunkUseCase(
        session_store=mock_session_store,
        chunk_verifier=mock_chunk_verifier,
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
def valid_chunk_data() -> bytes:
    """Create valid 5MB chunk data."""
    return b"x" * 5242880


@pytest.fixture
def valid_chunk_checksum(valid_chunk_data: bytes) -> str:
    """Compute valid checksum for test chunk."""
    return SHA256Hash.from_bytes(valid_chunk_data).value


@pytest.fixture
def valid_session(
    sample_workspace_id: UUID,
    sample_session_id: UUID,
) -> UploadSession:
    """Create valid upload session for testing."""
    return UploadSession(
        session_id=sample_session_id,
        workspace_id=sample_workspace_id,
        filename="test.pdf",
        size=10485760,  # 10 MB
        mime_type="application/pdf",
        sha256_checksum=SHA256Hash("a" * 64),
        offset=0,
        status=SessionStatus.PENDING,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        chunk_manifest=[],
    )


@pytest.fixture
def valid_request(
    sample_workspace_id: UUID,
    sample_session_id: UUID,
    valid_chunk_data: bytes,
    valid_chunk_checksum: str,
) -> ProcessChunkRequest:
    """Create valid ProcessChunkRequest for testing."""
    return ProcessChunkRequest(
        workspace_id=sample_workspace_id,
        session_id=sample_session_id,
        chunk_data=valid_chunk_data,
        chunk_offset=0,
        chunk_checksum=valid_chunk_checksum,
    )


class TestProcessChunkUseCaseHappyPath:
    """Test suite for successful use case execution."""

    @pytest.mark.asyncio
    async def test_successful_chunk_processing_first_chunk(
        self,
        use_case: ProcessChunkUseCase,
        mock_session_store: AsyncMock,
        mock_chunk_verifier: Mock,
        valid_session: UploadSession,
        valid_request: ProcessChunkRequest,
    ) -> None:
        """Test that valid first chunk is processed successfully."""
        # Arrange
        mock_session_store.get_session.return_value = valid_session
        mock_session_store.update_session.return_value = None
        mock_chunk_verifier.verify_chunk.return_value = None

        # Act
        response = await use_case.execute(valid_request)

        # Assert response
        assert isinstance(response, ProcessChunkResponse)
        assert response.new_offset == 5242880

        # Assert session state updated correctly
        assert valid_session.offset == 5242880
        assert valid_session.status == SessionStatus.IN_PROGRESS
        assert len(valid_session.chunk_manifest) == 1

        # Assert chunk manifest entry
        chunk_entry = valid_session.chunk_manifest[0]
        assert chunk_entry["index"] == 0
        assert chunk_entry["size"] == 5242880
        assert chunk_entry["checksum"] == valid_request.chunk_checksum

        # Assert session was updated in store
        mock_session_store.update_session.assert_called_once_with(valid_session)

        # Assert chunk verification was called
        mock_chunk_verifier.verify_chunk.assert_called_once_with(
            data=valid_request.chunk_data,
            expected_checksum=valid_request.chunk_checksum,
            chunk_index=0,
        )

    @pytest.mark.asyncio
    async def test_successful_chunk_processing_second_chunk(
        self,
        use_case: ProcessChunkUseCase,
        mock_session_store: AsyncMock,
        mock_chunk_verifier: Mock,
        valid_session: UploadSession,
        valid_chunk_data: bytes,
        valid_chunk_checksum: str,
    ) -> None:
        """Test that second chunk is processed successfully."""
        # Arrange: Session already has first chunk
        valid_session.offset = 5242880
        valid_session.status = SessionStatus.IN_PROGRESS
        valid_session.chunk_manifest = [{"index": 0, "size": 5242880, "checksum": "abc123"}]
        mock_session_store.get_session.return_value = valid_session

        request = ProcessChunkRequest(
            workspace_id=valid_session.workspace_id,
            session_id=valid_session.session_id,
            chunk_data=valid_chunk_data,
            chunk_offset=5242880,
            chunk_checksum=valid_chunk_checksum,
        )

        # Act
        response = await use_case.execute(request)

        # Assert response
        assert response.new_offset == 10485760

        # Assert session state
        assert valid_session.offset == 10485760
        assert valid_session.status == SessionStatus.IN_PROGRESS  # Remains IN_PROGRESS
        assert len(valid_session.chunk_manifest) == 2

        # Assert second chunk in manifest
        chunk_entry = valid_session.chunk_manifest[1]
        assert chunk_entry["index"] == 1
        assert chunk_entry["size"] == 5242880
        assert chunk_entry["checksum"] == valid_chunk_checksum

    @pytest.mark.asyncio
    async def test_chunk_manifest_tracking(
        self,
        use_case: ProcessChunkUseCase,
        mock_session_store: AsyncMock,
        mock_chunk_verifier: Mock,
        valid_session: UploadSession,
        valid_chunk_data: bytes,
    ) -> None:
        """Test that chunk manifest tracks all processed chunks."""
        # Arrange: Create session with enough size for 3 chunks
        valid_session.size = 15728640  # 15 MB (3 x 5MB chunks)
        mock_session_store.get_session.return_value = valid_session

        # Act: Process 3 chunks sequentially
        for i in range(3):
            checksum = SHA256Hash.from_bytes(valid_chunk_data).value
            request = ProcessChunkRequest(
                workspace_id=valid_session.workspace_id,
                session_id=valid_session.session_id,
                chunk_data=valid_chunk_data,
                chunk_offset=i * 5242880,
                chunk_checksum=checksum,
            )
            await use_case.execute(request)

        # Assert: All chunks in manifest
        assert len(valid_session.chunk_manifest) == 3
        for i in range(3):
            assert valid_session.chunk_manifest[i]["index"] == i
            assert valid_session.chunk_manifest[i]["size"] == 5242880


class TestProcessChunkUseCaseSessionNotFound:
    """Test suite for session not found scenarios."""

    @pytest.mark.asyncio
    async def test_session_not_found_expired(
        self,
        use_case: ProcessChunkUseCase,
        mock_session_store: AsyncMock,
        valid_request: ProcessChunkRequest,
    ) -> None:
        """Test that expired session raises SessionNotFoundError."""
        # Arrange: Session expired (get_session returns None)
        mock_session_store.get_session.return_value = None

        # Act & Assert
        with pytest.raises(SessionNotFoundError) as exc_info:
            await use_case.execute(valid_request)

        assert "not found or expired" in str(exc_info.value)
        assert str(valid_request.session_id) in str(exc_info.value)

        # Assert no session update attempted
        mock_session_store.update_session.assert_not_called()


class TestProcessChunkUseCaseOffsetMismatch:
    """Test suite for offset mismatch scenarios."""

    @pytest.mark.asyncio
    async def test_offset_mismatch_client_out_of_sync(
        self,
        use_case: ProcessChunkUseCase,
        mock_session_store: AsyncMock,
        valid_session: UploadSession,
        valid_chunk_data: bytes,
        valid_chunk_checksum: str,
    ) -> None:
        """Test that offset mismatch raises OffsetMismatchError."""
        # Arrange: Session has offset=5242880, client thinks offset=0
        valid_session.offset = 5242880
        valid_session.status = SessionStatus.IN_PROGRESS
        mock_session_store.get_session.return_value = valid_session

        request = ProcessChunkRequest(
            workspace_id=valid_session.workspace_id,
            session_id=valid_session.session_id,
            chunk_data=valid_chunk_data,
            chunk_offset=0,  # Wrong offset!
            chunk_checksum=valid_chunk_checksum,
        )

        # Act & Assert
        with pytest.raises(OffsetMismatchError) as exc_info:
            await use_case.execute(request)

        error = exc_info.value
        assert error.expected_offset == 5242880
        assert error.received_offset == 0
        assert error.session_id == valid_session.session_id

        # Assert no session update attempted
        mock_session_store.update_session.assert_not_called()


class TestProcessChunkUseCaseChecksumMismatch:
    """Test suite for checksum mismatch scenarios."""

    @pytest.mark.asyncio
    async def test_checksum_mismatch_corrupt_chunk(
        self,
        use_case: ProcessChunkUseCase,
        mock_session_store: AsyncMock,
        mock_chunk_verifier: Mock,
        valid_session: UploadSession,
        valid_request: ProcessChunkRequest,
    ) -> None:
        """Test that checksum mismatch raises ChecksumMismatchError."""
        # Arrange
        mock_session_store.get_session.return_value = valid_session
        mock_chunk_verifier.verify_chunk.side_effect = ChecksumMismatchError(
            expected_checksum="expected_hash",
            computed_checksum="computed_hash",
            chunk_index=0,
            chunk_size=5242880,
        )

        # Act & Assert
        with pytest.raises(ChecksumMismatchError) as exc_info:
            await use_case.execute(valid_request)

        error = exc_info.value
        assert error.expected_checksum == "expected_hash"
        assert error.computed_checksum == "computed_hash"
        assert error.chunk_index == 0

        # Assert no session update attempted (verification failed)
        mock_session_store.update_session.assert_not_called()


class TestProcessChunkUseCaseTerminalStates:
    """Test suite for terminal state rejection."""

    @pytest.mark.asyncio
    async def test_terminal_state_complete(
        self,
        use_case: ProcessChunkUseCase,
        mock_session_store: AsyncMock,
        mock_chunk_verifier: Mock,
        valid_session: UploadSession,
        valid_request: ProcessChunkRequest,
    ) -> None:
        """Test that COMPLETE state rejects chunk processing."""
        # Arrange
        valid_session.status = SessionStatus.COMPLETE
        mock_session_store.get_session.return_value = valid_session

        # Act & Assert
        with pytest.raises(InvalidSessionStateError) as exc_info:
            await use_case.execute(valid_request)

        error = exc_info.value
        assert error.current_state == "complete"
        assert error.operation == "process_chunk"
        assert error.session_id == valid_session.session_id

        mock_session_store.update_session.assert_not_called()
        mock_chunk_verifier.verify_chunk.assert_not_called()

    @pytest.mark.asyncio
    async def test_terminal_state_failed(
        self,
        use_case: ProcessChunkUseCase,
        mock_session_store: AsyncMock,
        mock_chunk_verifier: Mock,
        valid_session: UploadSession,
        valid_request: ProcessChunkRequest,
    ) -> None:
        """Test that FAILED state rejects chunk processing."""
        # Arrange
        valid_session.status = SessionStatus.FAILED
        mock_session_store.get_session.return_value = valid_session

        # Act & Assert
        with pytest.raises(InvalidSessionStateError) as exc_info:
            await use_case.execute(valid_request)

        error = exc_info.value
        assert error.current_state == "failed"

        mock_session_store.update_session.assert_not_called()
        mock_chunk_verifier.verify_chunk.assert_not_called()

    @pytest.mark.asyncio
    async def test_terminal_state_aborted(
        self,
        use_case: ProcessChunkUseCase,
        mock_session_store: AsyncMock,
        mock_chunk_verifier: Mock,
        valid_session: UploadSession,
        valid_request: ProcessChunkRequest,
    ) -> None:
        """Test that ABORTED state rejects chunk processing."""
        # Arrange
        valid_session.status = SessionStatus.ABORTED
        mock_session_store.get_session.return_value = valid_session

        # Act & Assert
        with pytest.raises(InvalidSessionStateError) as exc_info:
            await use_case.execute(valid_request)

        error = exc_info.value
        assert error.current_state == "aborted"
        mock_session_store.update_session.assert_not_called()
        mock_chunk_verifier.verify_chunk.assert_not_called()


class TestProcessChunkUseCaseInfrastructureErrors:
    """Test suite for infrastructure error handling."""

    @pytest.mark.asyncio
    async def test_infrastructure_error_propagates(
        self,
        use_case: ProcessChunkUseCase,
        mock_session_store: AsyncMock,
        mock_chunk_verifier: Mock,
        valid_session: UploadSession,
        valid_request: ProcessChunkRequest,
    ) -> None:
        """Test that infrastructure errors propagate to caller."""
        # Arrange
        mock_session_store.get_session.return_value = valid_session
        mock_chunk_verifier.verify_chunk.return_value = None
        mock_session_store.update_session.side_effect = InfrastructureError(
            "Redis connection timeout"
        )

        # Act & Assert
        with pytest.raises(InfrastructureError) as exc_info:
            await use_case.execute(valid_request)

        assert "Redis connection timeout" in str(exc_info.value)


class TestProcessChunkUseCaseEdgeCases:
    """Test suite for edge cases."""

    @pytest.mark.asyncio
    async def test_large_chunk_processing(
        self,
        use_case: ProcessChunkUseCase,
        mock_session_store: AsyncMock,
        mock_chunk_verifier: Mock,
        valid_session: UploadSession,
    ) -> None:
        """Test processing large chunk (10MB instead of typical 5MB)."""
        # Arrange
        large_chunk = b"y" * 10485760  # 10 MB
        checksum = SHA256Hash.from_bytes(large_chunk).value
        request = ProcessChunkRequest(
            workspace_id=valid_session.workspace_id,
            session_id=valid_session.session_id,
            chunk_data=large_chunk,
            chunk_offset=0,
            chunk_checksum=checksum,
        )

        mock_session_store.get_session.return_value = valid_session

        # Act
        response = await use_case.execute(request)

        # Assert
        assert response.new_offset == 10485760
        assert valid_session.offset == 10485760
        assert valid_session.chunk_manifest[0]["size"] == 10485760

    @pytest.mark.asyncio
    async def test_small_chunk_processing(
        self,
        use_case: ProcessChunkUseCase,
        mock_session_store: AsyncMock,
        mock_chunk_verifier: Mock,
        valid_session: UploadSession,
    ) -> None:
        """Test processing small chunk (1KB instead of typical 5MB)."""
        # Arrange
        small_chunk = b"z" * 1024  # 1 KB
        checksum = SHA256Hash.from_bytes(small_chunk).value
        request = ProcessChunkRequest(
            workspace_id=valid_session.workspace_id,
            session_id=valid_session.session_id,
            chunk_data=small_chunk,
            chunk_offset=0,
            chunk_checksum=checksum,
        )

        mock_session_store.get_session.return_value = valid_session

        # Act
        response = await use_case.execute(request)

        # Assert
        assert response.new_offset == 1024
        assert valid_session.offset == 1024
        assert valid_session.chunk_manifest[0]["size"] == 1024


class TestProcessChunkRequestValidation:
    """Test suite for DTO validation."""

    def test_negative_offset_rejected(
        self,
        sample_workspace_id: UUID,
        sample_session_id: UUID,
        valid_chunk_data: bytes,
        valid_chunk_checksum: str,
    ) -> None:
        """Test that negative chunk_offset raises ValueError."""
        with pytest.raises(ValueError, match="chunk_offset cannot be negative"):
            ProcessChunkRequest(
                workspace_id=sample_workspace_id,
                session_id=sample_session_id,
                chunk_data=valid_chunk_data,
                chunk_offset=-1,
                chunk_checksum=valid_chunk_checksum,
            )

    def test_empty_chunk_data_rejected(
        self,
        sample_workspace_id: UUID,
        sample_session_id: UUID,
        valid_chunk_checksum: str,
    ) -> None:
        """Test that empty chunk_data raises ValueError."""
        with pytest.raises(ValueError, match="chunk_data cannot be empty"):
            ProcessChunkRequest(
                workspace_id=sample_workspace_id,
                session_id=sample_session_id,
                chunk_data=b"",
                chunk_offset=0,
                chunk_checksum=valid_chunk_checksum,
            )

    def test_invalid_checksum_format_rejected(
        self,
        sample_workspace_id: UUID,
        sample_session_id: UUID,
        valid_chunk_data: bytes,
    ) -> None:
        """Test that invalid checksum format raises ValueError."""
        # Too short
        with pytest.raises(ValueError, match="chunk_checksum must be 64"):
            ProcessChunkRequest(
                workspace_id=sample_workspace_id,
                session_id=sample_session_id,
                chunk_data=valid_chunk_data,
                chunk_offset=0,
                chunk_checksum="abc123",
            )

        # Invalid characters (uppercase)
        with pytest.raises(ValueError, match="chunk_checksum must be 64"):
            ProcessChunkRequest(
                workspace_id=sample_workspace_id,
                session_id=sample_session_id,
                chunk_data=valid_chunk_data,
                chunk_offset=0,
                chunk_checksum="A" * 64,
            )

        # Non-hex characters
        with pytest.raises(ValueError, match="chunk_checksum must be 64"):
            ProcessChunkRequest(
                workspace_id=sample_workspace_id,
                session_id=sample_session_id,
                chunk_data=valid_chunk_data,
                chunk_offset=0,
                chunk_checksum="z" * 64,
            )


class TestProcessChunkUseCaseChunkSizeValidation:
    """Test suite for chunk size validation."""

    @pytest.mark.asyncio
    async def test_oversized_chunk_rejected(
        self,
        use_case: ProcessChunkUseCase,
        mock_session_store: AsyncMock,
        valid_session: UploadSession,
    ) -> None:
        """Test that oversized chunk (>10MB) raises ValueError."""
        # Arrange
        oversized_chunk = b"x" * 10485761  # 10 MB + 1 byte
        checksum = SHA256Hash.from_bytes(oversized_chunk).value
        request = ProcessChunkRequest(
            workspace_id=valid_session.workspace_id,
            session_id=valid_session.session_id,
            chunk_data=oversized_chunk,
            chunk_offset=0,
            chunk_checksum=checksum,
        )

        mock_session_store.get_session.return_value = valid_session

        # Act & Assert
        with pytest.raises(ValueError, match="exceeds maximum 10 MB"):
            await use_case.execute(request)

        # Assert no session update attempted
        mock_session_store.update_session.assert_not_called()
