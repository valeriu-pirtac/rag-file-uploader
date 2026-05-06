"""Unit tests for DeduplicationService."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.domain.exceptions import DuplicateFileError, InfrastructureError
from src.domain.protocols.deduplication_store import FileMetadata
from src.domain.services.deduplication_service import DeduplicationService
from src.domain.value_objects import SHA256Hash


@pytest.fixture
def mock_store() -> AsyncMock:
    """Create mock IDeduplicationStore.

    Returns:
        AsyncMock that implements IDeduplicationStore protocol
    """
    return AsyncMock()


@pytest.fixture
def service(mock_store: AsyncMock) -> DeduplicationService:
    """Create DeduplicationService with mock store.

    Args:
        mock_store: Mock deduplication store fixture

    Returns:
        DeduplicationService instance for testing
    """
    return DeduplicationService(mock_store)


@pytest.fixture
def workspace_id() -> str:
    """Generate test workspace ID.

    Returns:
        Random UUID for workspace
    """
    return uuid4()


@pytest.fixture
def sha256() -> SHA256Hash:
    """Generate test SHA-256 checksum.

    Returns:
        Valid SHA256Hash for testing
    """
    return SHA256Hash("a" * 64)


@pytest.fixture
def existing_metadata() -> FileMetadata:
    """Create existing file metadata for duplicate tests.

    Returns:
        FileMetadata representing an existing file
    """
    return FileMetadata(
        file_id=uuid4(),
        s3_path="workspace_123/abc.pdf",
        size=1024,
        uploaded_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
    )


class TestDeduplicationServiceInit:
    """Tests for DeduplicationService initialization."""

    def test_init_with_valid_store(self, mock_store: AsyncMock) -> None:
        """Test initialization with valid store.

        Given a valid IDeduplicationStore implementation
        When DeduplicationService is initialized
        Then service is created successfully
        """
        # Act
        service = DeduplicationService(mock_store)

        # Assert
        assert service._store == mock_store

    def test_init_with_none_store_raises_error(self) -> None:
        """Test initialization with None store raises TypeError.

        Given None as store parameter
        When DeduplicationService is initialized
        Then TypeError is raised
        """
        # Act & Assert
        with pytest.raises(TypeError) as exc_info:
            DeduplicationService(None)  # type: ignore

        assert "store cannot be None" in str(exc_info.value)


class TestCheckForDuplicateNotFound:
    """Tests for check_for_duplicate when file is unique."""

    @pytest.mark.asyncio
    async def test_check_for_duplicate_not_found(
        self,
        service: DeduplicationService,
        mock_store: AsyncMock,
        workspace_id: str,
        sha256: SHA256Hash,
    ) -> None:
        """Test check_for_duplicate when file is unique.

        Given a workspace and SHA-256 checksum
        When store returns None (no duplicate)
        Then no exception is raised (passes silently)
        """
        # Arrange
        mock_store.check_duplicate.return_value = None

        # Act - should not raise exception
        await service.check_for_duplicate(workspace_id, sha256)

        # Assert
        mock_store.check_duplicate.assert_called_once_with(workspace_id, sha256)

    @pytest.mark.asyncio
    async def test_check_for_duplicate_with_none_workspace_id_raises_error(
        self,
        service: DeduplicationService,
        sha256: SHA256Hash,
    ) -> None:
        """Test check_for_duplicate with None workspace_id raises TypeError.

        Given None as workspace_id
        When check_for_duplicate is called
        Then TypeError is raised
        """
        # Act & Assert
        with pytest.raises(TypeError) as exc_info:
            await service.check_for_duplicate(None, sha256)  # type: ignore

        assert "workspace_id cannot be None" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_check_for_duplicate_with_none_sha256_raises_error(
        self,
        service: DeduplicationService,
        workspace_id: str,
    ) -> None:
        """Test check_for_duplicate with None sha256 raises TypeError.

        Given None as sha256
        When check_for_duplicate is called
        Then TypeError is raised
        """
        # Act & Assert
        with pytest.raises(TypeError) as exc_info:
            await service.check_for_duplicate(workspace_id, None)  # type: ignore

        assert "sha256 cannot be None" in str(exc_info.value)


class TestCheckForDuplicateFound:
    """Tests for check_for_duplicate when duplicate is found."""

    @pytest.mark.asyncio
    async def test_check_for_duplicate_found_raises_error(
        self,
        service: DeduplicationService,
        mock_store: AsyncMock,
        workspace_id: str,
        sha256: SHA256Hash,
        existing_metadata: FileMetadata,
    ) -> None:
        """Test check_for_duplicate raises error when duplicate found.

        Given a workspace and SHA-256 checksum
        When store returns existing file metadata
        Then DuplicateFileError is raised with correct details
        """
        # Arrange
        mock_store.check_duplicate.return_value = existing_metadata

        # Act & Assert
        with pytest.raises(DuplicateFileError) as exc_info:
            await service.check_for_duplicate(workspace_id, sha256)

        # Verify exception details
        error = exc_info.value
        assert error.sha256_checksum == sha256
        assert error.existing_file_id == existing_metadata.file_id
        assert error.existing_s3_path == existing_metadata.s3_path
        assert error.uploaded_at == existing_metadata.uploaded_at

        # Verify store was called
        mock_store.check_duplicate.assert_called_once_with(workspace_id, sha256)

    @pytest.mark.asyncio
    async def test_check_for_duplicate_includes_all_metadata_fields(
        self,
        service: DeduplicationService,
        mock_store: AsyncMock,
        workspace_id: str,
        sha256: SHA256Hash,
    ) -> None:
        """Test DuplicateFileError includes all required metadata fields.

        Given an existing file with specific metadata
        When duplicate is detected
        Then error contains file_id, s3_path, size, and uploaded_at
        """
        # Arrange
        metadata = FileMetadata(
            file_id=uuid4(),
            s3_path="workspace_abc/file-xyz.pdf",
            size=2048,
            uploaded_at=datetime(2026, 5, 5, 10, 30, 45, tzinfo=UTC),
        )
        mock_store.check_duplicate.return_value = metadata

        # Act & Assert
        with pytest.raises(DuplicateFileError) as exc_info:
            await service.check_for_duplicate(workspace_id, sha256)

        error = exc_info.value
        assert error.existing_file_id == metadata.file_id
        assert error.existing_s3_path == "workspace_abc/file-xyz.pdf"
        assert error.uploaded_at == datetime(2026, 5, 5, 10, 30, 45, tzinfo=UTC)


class TestCheckForDuplicateInfrastructureError:
    """Tests for check_for_duplicate infrastructure error handling."""

    @pytest.mark.asyncio
    async def test_check_for_duplicate_propagates_infrastructure_error(
        self,
        service: DeduplicationService,
        mock_store: AsyncMock,
        workspace_id: str,
        sha256: SHA256Hash,
    ) -> None:
        """Test check_for_duplicate propagates InfrastructureError.

        Given store that raises InfrastructureError
        When check_for_duplicate is called
        Then InfrastructureError is propagated to caller
        """
        # Arrange
        mock_store.check_duplicate.side_effect = InfrastructureError("Redis connection timeout")

        # Act & Assert
        with pytest.raises(InfrastructureError) as exc_info:
            await service.check_for_duplicate(workspace_id, sha256)

        assert "Redis connection timeout" in str(exc_info.value)


class TestRegisterUploadSuccess:
    """Tests for successful file fingerprint registration."""

    @pytest.mark.asyncio
    async def test_register_upload_success(
        self,
        service: DeduplicationService,
        mock_store: AsyncMock,
        workspace_id: str,
        sha256: SHA256Hash,
        existing_metadata: FileMetadata,
    ) -> None:
        """Test register_upload calls store with correct arguments.

        Given workspace, SHA-256, and file metadata
        When register_upload is called
        Then store.register_file is called with correct parameters
        """
        # Act
        await service.register_upload(workspace_id, sha256, existing_metadata)

        # Assert
        mock_store.register_file.assert_called_once_with(workspace_id, sha256, existing_metadata)

    @pytest.mark.asyncio
    async def test_register_upload_with_none_workspace_id_raises_error(
        self,
        service: DeduplicationService,
        sha256: SHA256Hash,
        existing_metadata: FileMetadata,
    ) -> None:
        """Test register_upload with None workspace_id raises TypeError.

        Given None as workspace_id
        When register_upload is called
        Then TypeError is raised
        """
        # Act & Assert
        with pytest.raises(TypeError) as exc_info:
            await service.register_upload(None, sha256, existing_metadata)  # type: ignore

        assert "workspace_id cannot be None" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_upload_with_none_sha256_raises_error(
        self,
        service: DeduplicationService,
        workspace_id: str,
        existing_metadata: FileMetadata,
    ) -> None:
        """Test register_upload with None sha256 raises TypeError.

        Given None as sha256
        When register_upload is called
        Then TypeError is raised
        """
        # Act & Assert
        with pytest.raises(TypeError) as exc_info:
            await service.register_upload(workspace_id, None, existing_metadata)  # type: ignore

        assert "sha256 cannot be None" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_upload_with_none_metadata_raises_error(
        self,
        service: DeduplicationService,
        workspace_id: str,
        sha256: SHA256Hash,
    ) -> None:
        """Test register_upload with None metadata raises TypeError.

        Given None as metadata
        When register_upload is called
        Then TypeError is raised
        """
        # Act & Assert
        with pytest.raises(TypeError) as exc_info:
            await service.register_upload(workspace_id, sha256, None)  # type: ignore

        assert "metadata cannot be None" in str(exc_info.value)


class TestRegisterUploadInfrastructureError:
    """Tests for register_upload infrastructure error handling."""

    @pytest.mark.asyncio
    async def test_register_upload_propagates_infrastructure_error(
        self,
        service: DeduplicationService,
        mock_store: AsyncMock,
        workspace_id: str,
        sha256: SHA256Hash,
        existing_metadata: FileMetadata,
    ) -> None:
        """Test register_upload propagates InfrastructureError.

        Given store that raises InfrastructureError
        When register_upload is called
        Then InfrastructureError is propagated to caller
        """
        # Arrange
        mock_store.register_file.side_effect = InfrastructureError("Redis write failed")

        # Act & Assert
        with pytest.raises(InfrastructureError) as exc_info:
            await service.register_upload(workspace_id, sha256, existing_metadata)

        assert "Redis write failed" in str(exc_info.value)
