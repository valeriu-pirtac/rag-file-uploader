"""Unit tests for InitiateUploadRequest DTO.

Tests verify DTO validation logic for file size and MIME type.
"""

from uuid import uuid4

import pytest

from src.application.dto.upload_request import InitiateUploadRequest
from src.domain.entities.upload_session import (
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE_BYTES,
)
from src.domain.exceptions import (
    FileSizeLimitExceededError,
    UnsupportedMediaTypeError,
)


@pytest.fixture
def valid_request() -> InitiateUploadRequest:
    """Create a valid InitiateUploadRequest for testing."""
    return InitiateUploadRequest(
        workspace_id=uuid4(),
        filename="document.pdf",
        size=1_048_576,  # 1 MB
        mime_type="application/pdf",
        sha256_checksum="a" * 64,
    )


class TestInitiateUploadRequestValidateSize:
    """Test suite for validate_size method."""

    def test_valid_size_within_limit(self, valid_request: InitiateUploadRequest) -> None:
        """Test that valid file size (1 MB) passes validation."""
        # Act & Assert: Should not raise exception
        valid_request.validate_size()

    def test_size_at_maximum_limit(self) -> None:
        """Test that file size exactly at 1 GB limit passes validation."""
        # Arrange
        request = InitiateUploadRequest(
            workspace_id=uuid4(),
            filename="large.pdf",
            size=MAX_FILE_SIZE_BYTES,  # Exactly 1 GB
            mime_type="application/pdf",
            sha256_checksum="a" * 64,
        )

        # Act & Assert: Should not raise exception
        request.validate_size()

    def test_size_one_byte_over_limit_raises_error(self) -> None:
        """Test that file size 1 byte over limit raises FileSizeLimitExceededError."""
        # Arrange
        over_limit_size = MAX_FILE_SIZE_BYTES + 1
        request = InitiateUploadRequest(
            workspace_id=uuid4(),
            filename="too_large.pdf",
            size=over_limit_size,
            mime_type="application/pdf",
            sha256_checksum="a" * 64,
        )

        # Act & Assert
        with pytest.raises(FileSizeLimitExceededError) as exc_info:
            request.validate_size()

        # Verify exception details
        assert exc_info.value.file_size == over_limit_size
        assert exc_info.value.max_size == MAX_FILE_SIZE_BYTES

    def test_zero_size_raises_value_error(self) -> None:
        """Test that zero file size raises ValueError."""
        # Arrange
        request = InitiateUploadRequest(
            workspace_id=uuid4(),
            filename="empty.pdf",
            size=0,
            mime_type="application/pdf",
            sha256_checksum="a" * 64,
        )

        # Act & Assert
        with pytest.raises(ValueError, match="File size must be positive"):
            request.validate_size()

    def test_negative_size_raises_value_error(self) -> None:
        """Test that negative file size raises ValueError."""
        # Arrange
        request = InitiateUploadRequest(
            workspace_id=uuid4(),
            filename="invalid.pdf",
            size=-1,
            mime_type="application/pdf",
            sha256_checksum="a" * 64,
        )

        # Act & Assert
        with pytest.raises(ValueError, match="File size must be positive"):
            request.validate_size()


class TestInitiateUploadRequestValidateMimeType:
    """Test suite for validate_mime_type method."""

    def test_valid_pdf_mime_type(self, valid_request: InitiateUploadRequest) -> None:
        """Test that PDF MIME type passes validation."""
        # Act & Assert: Should not raise exception
        valid_request.validate_mime_type()

    def test_json_mime_type_raises_error(self) -> None:
        """Test that non-PDF MIME type raises UnsupportedMediaTypeError."""
        # Arrange
        request = InitiateUploadRequest(
            workspace_id=uuid4(),
            filename="data.json",
            size=1024,
            mime_type="application/json",
            sha256_checksum="a" * 64,
        )

        # Act & Assert
        with pytest.raises(UnsupportedMediaTypeError) as exc_info:
            request.validate_mime_type()

        # Verify exception details
        assert exc_info.value.provided_mime_type == "application/json"
        assert exc_info.value.allowed_mime_types == ALLOWED_MIME_TYPES

    def test_text_mime_type_raises_error(self) -> None:
        """Test that text MIME type raises UnsupportedMediaTypeError."""
        # Arrange
        request = InitiateUploadRequest(
            workspace_id=uuid4(),
            filename="document.txt",
            size=1024,
            mime_type="text/plain",
            sha256_checksum="a" * 64,
        )

        # Act & Assert
        with pytest.raises(UnsupportedMediaTypeError) as exc_info:
            request.validate_mime_type()

        assert exc_info.value.provided_mime_type == "text/plain"

    def test_image_mime_type_raises_error(self) -> None:
        """Test that image MIME type raises UnsupportedMediaTypeError."""
        # Arrange
        request = InitiateUploadRequest(
            workspace_id=uuid4(),
            filename="photo.png",
            size=1024,
            mime_type="image/png",
            sha256_checksum="a" * 64,
        )

        # Act & Assert
        with pytest.raises(UnsupportedMediaTypeError):
            request.validate_mime_type()
