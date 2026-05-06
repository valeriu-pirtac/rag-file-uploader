"""Unit tests for FileLoadCompletedEvent domain entity."""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from src.domain.entities.events import FileLoadCompletedEvent
from src.domain.value_objects.sha256_hash import SHA256Hash


class TestFileLoadCompletedEventCreation:
    """Test suite for FileLoadCompletedEvent creation and validation."""

    def test_creation_with_valid_attributes(self) -> None:
        """Test that a valid FileLoadCompletedEvent can be created."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"
        sha256_checksum = SHA256Hash("a" * 64)
        size_bytes = 1048576  # 1 MB
        uploaded_at = datetime.now(UTC)
        timestamp = datetime.now(UTC)

        event = FileLoadCompletedEvent(
            event_version="1.0",
            event_type="FILE_LOAD_COMPLETED",
            timestamp=timestamp,
            file_id=file_id,
            workspace_id=workspace_id,
            s3_path=s3_path,
            sha256_checksum=sha256_checksum,
            size_bytes=size_bytes,
            uploaded_at=uploaded_at,
        )

        assert event.event_version == "1.0"
        assert event.event_type == "FILE_LOAD_COMPLETED"
        assert event.timestamp == timestamp
        assert event.file_id == file_id
        assert event.workspace_id == workspace_id
        assert event.s3_path == s3_path
        assert event.sha256_checksum == sha256_checksum
        assert event.size_bytes == size_bytes
        assert event.uploaded_at == uploaded_at

    def test_timestamp_auto_set_when_none(self) -> None:
        """Test that timestamp is automatically set to current time when None."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"

        event = FileLoadCompletedEvent(
            file_id=file_id,
            workspace_id=workspace_id,
            s3_path=s3_path,
            sha256_checksum=SHA256Hash("a" * 64),
            size_bytes=1048576,
            uploaded_at=datetime.now(UTC),
        )

        assert event.timestamp is not None
        assert event.timestamp.tzinfo is not None  # Timezone-aware
        assert isinstance(event.timestamp, datetime)

    def test_event_version_defaults_to_1_0(self) -> None:
        """Test that event_version defaults to '1.0'."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"

        event = FileLoadCompletedEvent(
            file_id=file_id,
            workspace_id=workspace_id,
            s3_path=s3_path,
            sha256_checksum=SHA256Hash("a" * 64),
            size_bytes=1048576,
            uploaded_at=datetime.now(UTC),
        )

        assert event.event_version == "1.0"

    def test_event_type_defaults_to_file_load_completed(self) -> None:
        """Test that event_type defaults to 'FILE_LOAD_COMPLETED'."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"

        event = FileLoadCompletedEvent(
            file_id=file_id,
            workspace_id=workspace_id,
            s3_path=s3_path,
            sha256_checksum=SHA256Hash("a" * 64),
            size_bytes=1048576,
            uploaded_at=datetime.now(UTC),
        )

        assert event.event_type == "FILE_LOAD_COMPLETED"


class TestFileLoadCompletedEventValidation:
    """Test suite for FileLoadCompletedEvent validation rules."""

    def test_validation_rejects_invalid_event_version(self) -> None:
        """Test that invalid event_version raises ValueError."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"

        with pytest.raises(ValueError, match=r"event_version must be '1\.0'"):
            FileLoadCompletedEvent(
                event_version="2.0",  # Invalid version
                event_type="FILE_LOAD_COMPLETED",
                timestamp=datetime.now(UTC),
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=s3_path,
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )

    def test_validation_rejects_invalid_event_type(self) -> None:
        """Test that invalid event_type raises ValueError."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"

        with pytest.raises(ValueError, match=r"event_type must be 'FILE_LOAD_COMPLETED'"):
            FileLoadCompletedEvent(
                event_version="1.0",
                event_type="INVALID_EVENT_TYPE",  # Invalid type
                timestamp=datetime.now(UTC),
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=s3_path,
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )

    def test_validation_rejects_file_id_not_uuid(self) -> None:
        """Test that non-UUID file_id raises TypeError."""
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/invalid.pdf"

        with pytest.raises(TypeError) as exc_info:
            FileLoadCompletedEvent(
                timestamp=datetime.now(UTC),
                file_id="not-a-uuid",  # type: ignore
                workspace_id=workspace_id,
                s3_path=s3_path,
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )

        assert "file_id must be UUID" in str(exc_info.value)

    def test_validation_rejects_workspace_id_not_uuid(self) -> None:
        """Test that non-UUID workspace_id raises TypeError."""
        file_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_invalid/{file_id}.pdf"

        with pytest.raises(TypeError) as exc_info:
            FileLoadCompletedEvent(
                timestamp=datetime.now(UTC),
                file_id=file_id,
                workspace_id="not-a-uuid",  # type: ignore
                s3_path=s3_path,
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )

        assert "workspace_id must be UUID" in str(exc_info.value)

    def test_validation_rejects_naive_timestamp(self) -> None:
        """Test that timezone-naive timestamp raises ValueError."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"

        with pytest.raises(ValueError, match=r"timestamp must be timezone-aware"):
            FileLoadCompletedEvent(
                timestamp=datetime.now(),  # Naive datetime (no timezone)
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=s3_path,
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )

    def test_validation_rejects_naive_uploaded_at(self) -> None:
        """Test that timezone-naive uploaded_at raises ValueError."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"

        with pytest.raises(ValueError, match=r"uploaded_at must be timezone-aware"):
            FileLoadCompletedEvent(
                timestamp=datetime.now(UTC),
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=s3_path,
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(),  # Naive datetime (no timezone)
            )

    def test_validation_rejects_zero_size_bytes(self) -> None:
        """Test that size_bytes <= 0 raises ValueError."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"

        with pytest.raises(ValueError, match=r"size_bytes must be positive"):
            FileLoadCompletedEvent(
                timestamp=datetime.now(UTC),
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=s3_path,
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=0,  # Invalid: must be positive
                uploaded_at=datetime.now(UTC),
            )

    def test_validation_rejects_negative_size_bytes(self) -> None:
        """Test that negative size_bytes raises ValueError."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"

        with pytest.raises(ValueError, match=r"size_bytes must be positive"):
            FileLoadCompletedEvent(
                timestamp=datetime.now(UTC),
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=s3_path,
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=-1024,  # Invalid: must be positive
                uploaded_at=datetime.now(UTC),
            )

    def test_validation_rejects_s3_path_without_s3_scheme(self) -> None:
        """Test that s3_path without 's3://' prefix raises ValueError."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"https://bucket/workspace_{workspace_id}/{file_id}.pdf"

        with pytest.raises(ValueError, match=r"s3_path must start with 's3://'"):
            FileLoadCompletedEvent(
                timestamp=datetime.now(UTC),
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=s3_path,  # Invalid: no s3:// prefix
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )

    def test_validation_rejects_s3_path_without_workspace_prefix(self) -> None:
        """Test that s3_path without workspace_{workspace_id} prefix raises ValueError."""
        file_id = uuid4()
        workspace_id = uuid4()
        other_workspace_id = uuid4()
        s3_path = f"s3://bucket/workspace_{other_workspace_id}/{file_id}.pdf"

        with pytest.raises(ValueError, match=r"s3_path must contain workspace"):
            FileLoadCompletedEvent(
                timestamp=datetime.now(UTC),
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=s3_path,  # Invalid: wrong workspace_id
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )

    def test_validation_rejects_s3_path_with_embedded_workspace_id(self) -> None:
        """Test that workspace_id embedded in longer string is rejected."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://bucket/prefix_workspace_{workspace_id}_suffix/{file_id}.pdf"

        with pytest.raises(ValueError, match=r"s3_path must contain workspace path segment"):
            FileLoadCompletedEvent(
                timestamp=datetime.now(UTC),
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=s3_path,  # Invalid: workspace_id not a proper path segment
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )

    def test_validation_rejects_s3_path_without_path_separator(self) -> None:
        """Test that s3_path without proper path separator after workspace_id is rejected."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://bucket/workspace_{workspace_id}{file_id}.pdf"

        with pytest.raises(ValueError, match=r"s3_path must contain workspace path segment"):
            FileLoadCompletedEvent(
                timestamp=datetime.now(UTC),
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=s3_path,  # Invalid: no / after workspace_id
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )

    def test_validation_rejects_s3_path_without_file_id(self) -> None:
        """Test that s3_path without file_id is rejected."""
        file_id = uuid4()
        workspace_id = uuid4()
        other_file_id = uuid4()
        s3_path = f"s3://bucket/workspace_{workspace_id}/{other_file_id}.pdf"

        with pytest.raises(ValueError, match=r"s3_path must contain file_id"):
            FileLoadCompletedEvent(
                timestamp=datetime.now(UTC),
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=s3_path,  # Invalid: doesn't contain file_id
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )

    def test_validation_rejects_s3_path_none(self) -> None:
        """Test that s3_path=None raises ValueError."""
        file_id = uuid4()
        workspace_id = uuid4()

        with pytest.raises(ValueError, match=r"s3_path cannot be None"):
            FileLoadCompletedEvent(
                timestamp=datetime.now(UTC),
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=None,  # type: ignore
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )

    def test_validation_rejects_nil_file_id(self) -> None:
        """Test that nil UUID for file_id raises ValueError."""
        workspace_id = uuid4()
        nil_uuid = UUID("00000000-0000-0000-0000-000000000000")
        s3_path = f"s3://bucket/workspace_{workspace_id}/{nil_uuid}.pdf"

        with pytest.raises(ValueError, match=r"file_id cannot be nil UUID"):
            FileLoadCompletedEvent(
                timestamp=datetime.now(UTC),
                file_id=nil_uuid,  # Invalid: nil UUID
                workspace_id=workspace_id,
                s3_path=s3_path,
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )

    def test_validation_rejects_nil_workspace_id(self) -> None:
        """Test that nil UUID for workspace_id raises ValueError."""
        file_id = uuid4()
        nil_uuid = UUID("00000000-0000-0000-0000-000000000000")
        s3_path = f"s3://bucket/workspace_{nil_uuid}/{file_id}.pdf"

        with pytest.raises(ValueError, match=r"workspace_id cannot be nil UUID"):
            FileLoadCompletedEvent(
                timestamp=datetime.now(UTC),
                file_id=file_id,
                workspace_id=nil_uuid,  # Invalid: nil UUID
                s3_path=s3_path,
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )

    def test_validation_rejects_size_bytes_exceeding_safe_json_range(self) -> None:
        """Test that size_bytes exceeding 2^53-1 raises ValueError."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://bucket/workspace_{workspace_id}/{file_id}.pdf"
        too_large = 9007199254740992  # 2^53 (exceeds safe range)

        with pytest.raises(ValueError, match=r"exceeds safe JSON integer range"):
            FileLoadCompletedEvent(
                timestamp=datetime.now(UTC),
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=s3_path,
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=too_large,  # Invalid: exceeds 2^53-1
                uploaded_at=datetime.now(UTC),
            )

    def test_validation_rejects_uploaded_at_after_timestamp(self) -> None:
        """Test that uploaded_at > timestamp raises ValueError."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://bucket/workspace_{workspace_id}/{file_id}.pdf"
        timestamp = datetime(2026, 5, 6, 10, 0, 0, tzinfo=UTC)
        uploaded_at = datetime(2026, 5, 6, 11, 0, 0, tzinfo=UTC)  # After timestamp

        with pytest.raises(ValueError, match=r"uploaded_at cannot be after timestamp"):
            FileLoadCompletedEvent(
                timestamp=timestamp,
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=s3_path,
                sha256_checksum=SHA256Hash("a" * 64),
                size_bytes=1048576,
                uploaded_at=uploaded_at,  # Invalid: after timestamp
            )

    def test_validation_rejects_invalid_sha256_format(self) -> None:
        """Test that invalid SHA256 format raises ValueError."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://bucket/workspace_{workspace_id}/{file_id}.pdf"

        # Create a mock SHA256Hash with invalid __str__ output
        class InvalidHash:
            def __str__(self) -> str:
                return "INVALID"

        # SHA256Hash constructor validates, but event should also validate string output
        with pytest.raises(ValueError, match=r"sha256_checksum must be 64-character lowercase hex"):
            FileLoadCompletedEvent(
                timestamp=datetime.now(UTC),
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=s3_path,
                sha256_checksum=InvalidHash(),  # type: ignore
                size_bytes=1048576,
                uploaded_at=datetime.now(UTC),
            )


class TestFileLoadCompletedEventSerialization:
    """Test suite for FileLoadCompletedEvent serialization methods."""

    def test_to_dict_returns_correct_structure(self) -> None:
        """Test that to_dict() returns correct dictionary structure."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"
        sha256_checksum = SHA256Hash("b" * 64)
        size_bytes = 2097152  # 2 MB
        uploaded_at = datetime(2026, 5, 6, 15, 30, 0, tzinfo=UTC)
        timestamp = datetime(2026, 5, 6, 15, 35, 0, tzinfo=UTC)

        event = FileLoadCompletedEvent(
            timestamp=timestamp,
            file_id=file_id,
            workspace_id=workspace_id,
            s3_path=s3_path,
            sha256_checksum=sha256_checksum,
            size_bytes=size_bytes,
            uploaded_at=uploaded_at,
        )

        result = event.to_dict()

        # Verify envelope fields (camelCase per AC #2)
        assert result["eventVersion"] == "1.0"
        assert result["eventType"] == "FILE_LOAD_COMPLETED"
        assert result["timestamp"] == timestamp.isoformat()

        # Verify payload structure
        assert "payload" in result
        payload = result["payload"]
        assert payload["file_id"] == str(file_id)
        assert payload["workspace_id"] == str(workspace_id)
        assert payload["s3_path"] == s3_path
        assert payload["sha256_checksum"] == "b" * 64
        assert payload["size_bytes"] == size_bytes
        assert payload["uploaded_at"] == uploaded_at.isoformat()

    def test_to_dict_serializes_uuids_to_strings(self) -> None:
        """Test that UUIDs are serialized to string format."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"

        event = FileLoadCompletedEvent(
            file_id=file_id,
            workspace_id=workspace_id,
            s3_path=s3_path,
            sha256_checksum=SHA256Hash("a" * 64),
            size_bytes=1048576,
            uploaded_at=datetime.now(UTC),
        )

        result = event.to_dict()

        assert isinstance(result["payload"]["file_id"], str)
        assert isinstance(result["payload"]["workspace_id"], str)
        assert result["payload"]["file_id"] == str(file_id)
        assert result["payload"]["workspace_id"] == str(workspace_id)

    def test_to_dict_serializes_timestamps_to_iso8601(self) -> None:
        """Test that timestamps are serialized to ISO 8601 format."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"
        uploaded_at = datetime(2026, 5, 6, 15, 30, 0, tzinfo=UTC)
        timestamp = datetime(2026, 5, 6, 15, 35, 0, tzinfo=UTC)

        event = FileLoadCompletedEvent(
            timestamp=timestamp,
            file_id=file_id,
            workspace_id=workspace_id,
            s3_path=s3_path,
            sha256_checksum=SHA256Hash("a" * 64),
            size_bytes=1048576,
            uploaded_at=uploaded_at,
        )

        result = event.to_dict()

        # ISO 8601 format: 2026-05-06T15:30:00+00:00
        assert result["timestamp"] == "2026-05-06T15:35:00+00:00"
        assert result["payload"]["uploaded_at"] == "2026-05-06T15:30:00+00:00"

    def test_to_dict_serializes_sha256_hash_to_string(self) -> None:
        """Test that SHA256Hash is serialized to hex string."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"
        sha256_checksum = SHA256Hash("c" * 64)

        event = FileLoadCompletedEvent(
            file_id=file_id,
            workspace_id=workspace_id,
            s3_path=s3_path,
            sha256_checksum=sha256_checksum,
            size_bytes=1048576,
            uploaded_at=datetime.now(UTC),
        )

        result = event.to_dict()

        assert isinstance(result["payload"]["sha256_checksum"], str)
        assert result["payload"]["sha256_checksum"] == "c" * 64

    def test_to_json_returns_valid_json_string(self) -> None:
        """Test that to_json() returns valid JSON string."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"

        event = FileLoadCompletedEvent(
            file_id=file_id,
            workspace_id=workspace_id,
            s3_path=s3_path,
            sha256_checksum=SHA256Hash("d" * 64),
            size_bytes=1048576,
            uploaded_at=datetime.now(UTC),
        )

        json_str = event.to_json()

        # Verify it's valid JSON by parsing it
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        assert parsed["eventVersion"] == "1.0"
        assert parsed["eventType"] == "FILE_LOAD_COMPLETED"
        assert "timestamp" in parsed
        assert "payload" in parsed

    def test_to_json_includes_all_required_fields(self) -> None:
        """Test that to_json() includes all required fields."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"
        sha256_checksum = SHA256Hash("e" * 64)
        size_bytes = 3145728  # 3 MB
        uploaded_at = datetime.now(UTC)

        event = FileLoadCompletedEvent(
            file_id=file_id,
            workspace_id=workspace_id,
            s3_path=s3_path,
            sha256_checksum=sha256_checksum,
            size_bytes=size_bytes,
            uploaded_at=uploaded_at,
        )

        json_str = event.to_json()
        parsed = json.loads(json_str)

        # Verify envelope fields (camelCase per AC #2)
        assert "eventVersion" in parsed
        assert "eventType" in parsed
        assert "timestamp" in parsed

        # Verify payload fields
        payload = parsed["payload"]
        assert "file_id" in payload
        assert "workspace_id" in payload
        assert "s3_path" in payload
        assert "sha256_checksum" in payload
        assert "size_bytes" in payload
        assert "uploaded_at" in payload


class TestFileLoadCompletedEventSubjectName:
    """Test suite for FileLoadCompletedEvent subject_name property."""

    def test_subject_name_returns_correct_nats_subject(self) -> None:
        """Test that subject_name returns 'upload.file.load_completed'."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"

        event = FileLoadCompletedEvent(
            file_id=file_id,
            workspace_id=workspace_id,
            s3_path=s3_path,
            sha256_checksum=SHA256Hash("f" * 64),
            size_bytes=1048576,
            uploaded_at=datetime.now(UTC),
        )

        assert event.subject_name == "upload.file.load_completed"

    def test_subject_name_is_consistent_across_instances(self) -> None:
        """Test that subject_name is consistent across different event instances."""
        workspace_id_1 = uuid4()
        file_id_1 = uuid4()
        workspace_id_2 = uuid4()
        file_id_2 = uuid4()

        event1 = FileLoadCompletedEvent(
            file_id=file_id_1,
            workspace_id=workspace_id_1,
            s3_path=f"s3://bucket/workspace_{workspace_id_1}/{file_id_1}.pdf",
            sha256_checksum=SHA256Hash("a" * 64),
            size_bytes=1048576,
            uploaded_at=datetime.now(UTC),
        )

        event2 = FileLoadCompletedEvent(
            file_id=file_id_2,
            workspace_id=workspace_id_2,
            s3_path=f"s3://bucket/workspace_{workspace_id_2}/{file_id_2}.pdf",
            sha256_checksum=SHA256Hash("b" * 64),
            size_bytes=2097152,
            uploaded_at=datetime.now(UTC),
        )

        assert event1.subject_name == event2.subject_name
        assert event1.subject_name == "upload.file.load_completed"


class TestFileLoadCompletedEventImmutability:
    """Test suite for FileLoadCompletedEvent immutability."""

    def test_event_is_frozen(self) -> None:
        """Test that event attributes cannot be modified after creation."""
        file_id = uuid4()
        workspace_id = uuid4()
        s3_path = f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"

        event = FileLoadCompletedEvent(
            file_id=file_id,
            workspace_id=workspace_id,
            s3_path=s3_path,
            sha256_checksum=SHA256Hash("a" * 64),
            size_bytes=1048576,
            uploaded_at=datetime.now(UTC),
        )

        # Attempt to modify frozen attribute should raise FrozenInstanceError
        with pytest.raises(
            (AttributeError, Exception),
            match=r"cannot assign to field|can't set attribute|property.*has no setter",
        ):
            event.size_bytes = 2097152  # type: ignore
