"""Unit tests for InitiateUploadResponse DTO.

Tests verify DTO structure and field types.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from src.application.dto.upload_response import InitiateUploadResponse


@pytest.fixture
def sample_session_id() -> UUID:
    """Create sample session UUID for testing."""
    return uuid4()


@pytest.fixture
def sample_expires_at() -> datetime:
    """Create sample expiry timestamp (24 hours from now)."""
    return datetime.now(UTC) + timedelta(hours=24)


class TestInitiateUploadResponse:
    """Test suite for InitiateUploadResponse DTO."""

    def test_creates_response_with_all_fields(
        self,
        sample_session_id: UUID,
        sample_expires_at: datetime,
    ) -> None:
        """Test that response DTO can be created with all required fields."""
        # Act
        response = InitiateUploadResponse(
            session_id=sample_session_id,
            offset=0,
            expires_at=sample_expires_at,
        )

        # Assert
        assert response.session_id == sample_session_id
        assert response.offset == 0
        assert response.expires_at == sample_expires_at

    def test_offset_is_zero_for_new_session(
        self,
        sample_session_id: UUID,
        sample_expires_at: datetime,
    ) -> None:
        """Test that offset is always 0 for newly created sessions."""
        # Act
        response = InitiateUploadResponse(
            session_id=sample_session_id,
            offset=0,
            expires_at=sample_expires_at,
        )

        # Assert
        assert response.offset == 0

    def test_session_id_is_uuid_type(
        self,
        sample_session_id: UUID,
        sample_expires_at: datetime,
    ) -> None:
        """Test that session_id is UUID type."""
        # Act
        response = InitiateUploadResponse(
            session_id=sample_session_id,
            offset=0,
            expires_at=sample_expires_at,
        )

        # Assert
        assert isinstance(response.session_id, UUID)

    def test_expires_at_is_datetime_type(
        self,
        sample_session_id: UUID,
        sample_expires_at: datetime,
    ) -> None:
        """Test that expires_at is datetime type."""
        # Act
        response = InitiateUploadResponse(
            session_id=sample_session_id,
            offset=0,
            expires_at=sample_expires_at,
        )

        # Assert
        assert isinstance(response.expires_at, datetime)

    def test_expires_at_is_timezone_aware(
        self,
        sample_session_id: UUID,
    ) -> None:
        """Test that expires_at timestamp is timezone-aware (UTC)."""
        # Arrange
        expires_at = datetime.now(UTC) + timedelta(hours=24)

        # Act
        response = InitiateUploadResponse(
            session_id=sample_session_id,
            offset=0,
            expires_at=expires_at,
        )

        # Assert
        assert response.expires_at.tzinfo is not None
        assert response.expires_at.tzinfo == UTC
