"""Unit tests for UploadSession domain entity."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.domain.entities.upload_session import UploadSession
from src.domain.exceptions import (
    FileSizeLimitExceededError,
    UnsupportedMediaTypeError,
)
from src.domain.value_objects.session_status import SessionStatus
from src.domain.value_objects.sha256_hash import SHA256Hash


class TestUploadSessionCreation:
    """Test suite for UploadSession creation and validation."""

    def test_creation_with_valid_attributes(self) -> None:
        """Test that a valid upload session can be created."""
        session_id = uuid4()
        workspace_id = uuid4()
        filename = "test.pdf"
        size = 1024 * 1024  # 1 MB
        mime_type = "application/pdf"
        sha256_checksum = SHA256Hash("a" * 64)
        offset = 0
        status = SessionStatus.PENDING
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(hours=24)
        chunk_manifest: list[dict] = []

        session = UploadSession(
            session_id=session_id,
            workspace_id=workspace_id,
            filename=filename,
            size=size,
            mime_type=mime_type,
            sha256_checksum=sha256_checksum,
            offset=offset,
            status=status,
            created_at=created_at,
            expires_at=expires_at,
            chunk_manifest=chunk_manifest,
        )

        assert session.session_id == session_id
        assert session.workspace_id == workspace_id
        assert session.filename == filename
        assert session.size == size
        assert session.mime_type == mime_type
        assert session.sha256_checksum == sha256_checksum
        assert session.offset == offset
        assert session.status == status
        assert session.created_at == created_at
        assert session.expires_at == expires_at
        assert session.chunk_manifest == chunk_manifest

    def test_validation_rejects_file_size_exceeding_1gb(self) -> None:
        """Test that file size > 1 GB raises FileSizeLimitExceededError."""
        size = 1_073_741_825  # 1 GB + 1 byte
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(hours=24)

        with pytest.raises(FileSizeLimitExceededError) as exc_info:
            UploadSession(
                session_id=uuid4(),
                workspace_id=uuid4(),
                filename="large.pdf",
                size=size,
                mime_type="application/pdf",
                sha256_checksum=SHA256Hash("a" * 64),
                offset=0,
                status=SessionStatus.PENDING,
                created_at=created_at,
                expires_at=expires_at,
                chunk_manifest=[],
            )

        assert exc_info.value.file_size == size
        assert exc_info.value.max_size == 1_073_741_824

    def test_validation_accepts_file_size_exactly_1gb(self) -> None:
        """Test that file size exactly 1 GB is accepted."""
        size = 1_073_741_824  # Exactly 1 GB
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(hours=24)

        session = UploadSession(
            session_id=uuid4(),
            workspace_id=uuid4(),
            filename="exactly1gb.pdf",
            size=size,
            mime_type="application/pdf",
            sha256_checksum=SHA256Hash("a" * 64),
            offset=0,
            status=SessionStatus.PENDING,
            created_at=created_at,
            expires_at=expires_at,
            chunk_manifest=[],
        )

        assert session.size == size

    def test_validation_rejects_zero_or_negative_size(self) -> None:
        """Test that size <= 0 raises ValueError."""
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(hours=24)

        with pytest.raises(ValueError, match="size must be > 0"):
            UploadSession(
                session_id=uuid4(),
                workspace_id=uuid4(),
                filename="empty.pdf",
                size=0,
                mime_type="application/pdf",
                sha256_checksum=SHA256Hash("a" * 64),
                offset=0,
                status=SessionStatus.PENDING,
                created_at=created_at,
                expires_at=expires_at,
                chunk_manifest=[],
            )

        with pytest.raises(ValueError, match="size must be > 0"):
            UploadSession(
                session_id=uuid4(),
                workspace_id=uuid4(),
                filename="negative.pdf",
                size=-100,
                mime_type="application/pdf",
                sha256_checksum=SHA256Hash("a" * 64),
                offset=0,
                status=SessionStatus.PENDING,
                created_at=created_at,
                expires_at=expires_at,
                chunk_manifest=[],
            )

    def test_validation_rejects_non_pdf_mime_type(self) -> None:
        """Test that mime_type != 'application/pdf' raises UnsupportedMediaTypeError."""
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(hours=24)

        with pytest.raises(UnsupportedMediaTypeError) as exc_info:
            UploadSession(
                session_id=uuid4(),
                workspace_id=uuid4(),
                filename="document.docx",
                size=1024,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                sha256_checksum=SHA256Hash("a" * 64),
                offset=0,
                status=SessionStatus.PENDING,
                created_at=created_at,
                expires_at=expires_at,
                chunk_manifest=[],
            )

        assert (
            exc_info.value.provided_mime_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert exc_info.value.allowed_mime_types == ["application/pdf"]

    def test_validation_rejects_offset_greater_than_size(self) -> None:
        """Test that offset > size raises ValueError."""
        size = 1024
        offset = 2048  # Greater than size
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(hours=24)

        with pytest.raises(ValueError, match="offset must be >= 0 and <= size"):
            UploadSession(
                session_id=uuid4(),
                workspace_id=uuid4(),
                filename="test.pdf",
                size=size,
                mime_type="application/pdf",
                sha256_checksum=SHA256Hash("a" * 64),
                offset=offset,
                status=SessionStatus.PENDING,
                created_at=created_at,
                expires_at=expires_at,
                chunk_manifest=[],
            )

    def test_validation_rejects_negative_offset(self) -> None:
        """Test that negative offset raises ValueError."""
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(hours=24)

        with pytest.raises(ValueError, match="offset must be >= 0 and <= size"):
            UploadSession(
                session_id=uuid4(),
                workspace_id=uuid4(),
                filename="test.pdf",
                size=1024,
                mime_type="application/pdf",
                sha256_checksum=SHA256Hash("a" * 64),
                offset=-10,
                status=SessionStatus.PENDING,
                created_at=created_at,
                expires_at=expires_at,
                chunk_manifest=[],
            )

    def test_validation_requires_timezone_aware_created_at(self) -> None:
        """Test that created_at must be timezone-aware."""
        naive_datetime = datetime.now()  # No timezone
        expires_at = datetime.now(UTC) + timedelta(hours=24)

        with pytest.raises(ValueError, match="created_at must be timezone-aware"):
            UploadSession(
                session_id=uuid4(),
                workspace_id=uuid4(),
                filename="test.pdf",
                size=1024,
                mime_type="application/pdf",
                sha256_checksum=SHA256Hash("a" * 64),
                offset=0,
                status=SessionStatus.PENDING,
                created_at=naive_datetime,
                expires_at=expires_at,
                chunk_manifest=[],
            )

    def test_validation_requires_timezone_aware_expires_at(self) -> None:
        """Test that expires_at must be timezone-aware."""
        created_at = datetime.now(UTC)
        naive_expires = datetime.now()  # No timezone

        with pytest.raises(ValueError, match="expires_at must be timezone-aware"):
            UploadSession(
                session_id=uuid4(),
                workspace_id=uuid4(),
                filename="test.pdf",
                size=1024,
                mime_type="application/pdf",
                sha256_checksum=SHA256Hash("a" * 64),
                offset=0,
                status=SessionStatus.PENDING,
                created_at=created_at,
                expires_at=naive_expires,
                chunk_manifest=[],
            )

    def test_validation_requires_expires_at_after_created_at(self) -> None:
        """Test that expires_at must be after created_at."""
        created_at = datetime.now(UTC)
        expires_at = created_at - timedelta(hours=1)  # Before created_at

        with pytest.raises(ValueError, match="expires_at must be after created_at"):
            UploadSession(
                session_id=uuid4(),
                workspace_id=uuid4(),
                filename="test.pdf",
                size=1024,
                mime_type="application/pdf",
                sha256_checksum=SHA256Hash("a" * 64),
                offset=0,
                status=SessionStatus.PENDING,
                created_at=created_at,
                expires_at=expires_at,
                chunk_manifest=[],
            )

    def test_validation_requires_chunk_manifest_to_be_list(self) -> None:
        """Test that chunk_manifest must be a list."""
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(hours=24)

        with pytest.raises(TypeError, match="chunk_manifest must be a list"):
            UploadSession(
                session_id=uuid4(),
                workspace_id=uuid4(),
                filename="test.pdf",
                size=1024,
                mime_type="application/pdf",
                sha256_checksum=SHA256Hash("a" * 64),
                offset=0,
                status=SessionStatus.PENDING,
                created_at=created_at,
                expires_at=expires_at,
                chunk_manifest="not a list",  # type: ignore[arg-type]
            )


class TestUploadSessionBusinessLogic:
    """Test suite for UploadSession business logic methods."""

    def _create_valid_session(self, size: int = 1024 * 1024, offset: int = 0) -> UploadSession:
        """Helper method to create a valid upload session."""
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(hours=24)

        return UploadSession(
            session_id=uuid4(),
            workspace_id=uuid4(),
            filename="test.pdf",
            size=size,
            mime_type="application/pdf",
            sha256_checksum=SHA256Hash("a" * 64),
            offset=offset,
            status=SessionStatus.PENDING,
            created_at=created_at,
            expires_at=expires_at,
            chunk_manifest=[],
        )

    def test_add_chunk_appends_to_manifest(self) -> None:
        """Test that add_chunk() appends chunk metadata to manifest."""
        session = self._create_valid_session()

        session.add_chunk(chunk_index=0, chunk_size=1024, chunk_checksum="abc123")

        assert len(session.chunk_manifest) == 1
        assert session.chunk_manifest[0]["index"] == 0
        assert session.chunk_manifest[0]["size"] == 1024
        assert session.chunk_manifest[0]["checksum"] == "abc123"

    def test_add_chunk_appends_multiple_chunks(self) -> None:
        """Test that multiple chunks can be added in order."""
        session = self._create_valid_session()

        session.add_chunk(chunk_index=0, chunk_size=1024, chunk_checksum="chunk0")
        session.add_chunk(chunk_index=1, chunk_size=2048, chunk_checksum="chunk1")
        session.add_chunk(chunk_index=2, chunk_size=512, chunk_checksum="chunk2")

        assert len(session.chunk_manifest) == 3
        assert session.chunk_manifest[0]["index"] == 0
        assert session.chunk_manifest[1]["index"] == 1
        assert session.chunk_manifest[2]["index"] == 2

    def test_update_offset_updates_value_when_valid(self) -> None:
        """Test that update_offset() updates the offset when valid."""
        session = self._create_valid_session(size=10000, offset=0)

        session.update_offset(5000)

        assert session.offset == 5000

    def test_update_offset_accepts_offset_equal_to_size(self) -> None:
        """Test that update_offset() accepts offset equal to size (complete)."""
        session = self._create_valid_session(size=10000, offset=0)

        session.update_offset(10000)

        assert session.offset == 10000

    def test_update_offset_rejects_offset_greater_than_size(self) -> None:
        """Test that update_offset() raises ValueError when offset > size."""
        session = self._create_valid_session(size=10000, offset=0)

        with pytest.raises(ValueError, match="new_offset must be <= size"):
            session.update_offset(10001)

    def test_mark_in_progress_transitions_status(self) -> None:
        """Test that mark_in_progress() transitions status to IN_PROGRESS."""
        session = self._create_valid_session()
        assert session.status == SessionStatus.PENDING

        session.mark_in_progress()

        assert session.status == SessionStatus.IN_PROGRESS

    def test_mark_complete_transitions_status_when_offset_equals_size(
        self,
    ) -> None:
        """Test that mark_complete() transitions status when offset == size."""
        size = 10000
        session = self._create_valid_session(size=size, offset=size)

        session.mark_complete()

        assert session.status == SessionStatus.COMPLETE

    def test_mark_complete_raises_error_when_offset_less_than_size(self) -> None:
        """Test that mark_complete() raises ValueError when offset < size."""
        session = self._create_valid_session(size=10000, offset=5000)

        with pytest.raises(ValueError, match="Cannot mark complete: offset < size"):
            session.mark_complete()

    def test_mark_failed_transitions_status(self) -> None:
        """Test that mark_failed() transitions status to FAILED."""
        session = self._create_valid_session()

        session.mark_failed()

        assert session.status == SessionStatus.FAILED

    def test_mark_aborted_transitions_status(self) -> None:
        """Test that mark_aborted() transitions status to ABORTED."""
        session = self._create_valid_session()

        session.mark_aborted()

        assert session.status == SessionStatus.ABORTED

    def test_is_expired_returns_true_when_past_expiry(self) -> None:
        """Test that is_expired() returns True when current_time > expires_at."""
        session = self._create_valid_session()
        # Check with time 25 hours after creation (past 24-hour expiry)
        future_time = session.expires_at + timedelta(hours=1)

        assert session.is_expired(future_time) is True

    def test_is_expired_returns_false_when_before_expiry(self) -> None:
        """Test that is_expired() returns False when current_time < expires_at."""
        session = self._create_valid_session()
        # Check with time 1 hour after creation (before 24-hour expiry)
        current_time = session.created_at + timedelta(hours=1)

        assert session.is_expired(current_time) is False

    def test_is_expired_returns_false_exactly_at_expiry(self) -> None:
        """Test that is_expired() returns False exactly at expiry time."""
        session = self._create_valid_session()

        assert session.is_expired(session.expires_at) is False

    def test_is_complete_returns_true_when_complete(self) -> None:
        """Test that is_complete() returns True when status=COMPLETE and offset=size."""
        size = 10000
        session = self._create_valid_session(size=size, offset=size)
        session.mark_complete()

        assert session.is_complete() is True

    def test_is_complete_returns_false_when_offset_not_equal_size(self) -> None:
        """Test that is_complete() returns False when offset != size."""
        session = self._create_valid_session(size=10000, offset=5000)
        session.mark_in_progress()

        assert session.is_complete() is False

    def test_is_complete_returns_false_when_status_not_complete(self) -> None:
        """Test that is_complete() returns False when status != COMPLETE."""
        size = 10000
        session = self._create_valid_session(size=size, offset=size)
        # Offset equals size but status is not COMPLETE

        assert session.is_complete() is False

    def test_session_is_mutable_for_business_logic(self) -> None:
        """Test that UploadSession is mutable (not frozen) for business operations."""
        session = self._create_valid_session()

        # Should be able to modify offset and status
        session.offset = 1024
        session.status = SessionStatus.IN_PROGRESS

        assert session.offset == 1024
        assert session.status == SessionStatus.IN_PROGRESS
