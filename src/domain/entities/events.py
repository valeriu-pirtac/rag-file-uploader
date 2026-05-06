"""Event domain entities for file upload lifecycle.

This module defines versioned event entities for the FILE_LOAD_COMPLETED event
that signals downstream RAG pipeline services when files are ready for processing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.domain.exceptions import SerializationError
from src.domain.value_objects.sha256_hash import SHA256Hash


@dataclass(frozen=True)
class FileLoadCompletedEvent:
    """FILE_LOAD_COMPLETED event entity (v1.0).

    This event is published when a file upload completes successfully
    and the file is ready for downstream RAG pipeline processing.

    This is a STABLE API CONTRACT. Any changes to this schema must
    consider backward compatibility and versioning.

    Event Lifecycle:
        1. Upload session completes (all chunks verified)
        2. File assembled on S3 (Story 5.2)
        3. Deduplication check passes (Story 5.1)
        4. Virus scan passes (Story 5.3) — optional
        5. Event created with file metadata
        6. Event published to NATS/webhook (Stories 5.5/5.7)
        7. RAG pipeline consumes event and processes file

    Schema Version: 1.0
    Subject Name: upload.file.load_completed

    Attributes:
        event_version: Schema version string (always "1.0" for v1)
        event_type: Event type identifier (always "FILE_LOAD_COMPLETED")
        timestamp: Event creation timestamp (UTC, ISO 8601)
        file_id: Unique file identifier (UUID v4)
        workspace_id: Workspace owning this file (UUID v4)
        s3_path: Full S3 path to assembled file
        sha256_checksum: Full-file SHA-256 hash (64 hex chars)
        size_bytes: Final file size in bytes
        uploaded_at: Upload completion timestamp (UTC, ISO 8601)

    Invariants:
        - event_version is always "1.0"
        - event_type is always "FILE_LOAD_COMPLETED"
        - All timestamps are timezone-aware UTC
        - file_id and workspace_id are valid UUIDs
        - s3_path follows pattern: workspace_{workspace_id}/{file_id}
        - sha256_checksum is 64-character hex string
        - size_bytes is positive integer

    Serialization:
        - to_json() returns JSON string for NATS/webhook publishing
        - to_dict() returns dictionary for programmatic access
        - Timestamps serialize to ISO 8601 format
        - UUIDs serialize to string format
        - SHA256Hash serializes to hex string

    Examples:
        >>> from uuid import uuid4
        >>> from datetime import datetime, timezone
        >>> from src.domain.value_objects import SHA256Hash
        >>>
        >>> # Create event after successful upload
        >>> event = FileLoadCompletedEvent(
        ...     file_id=uuid4(),
        ...     workspace_id=uuid4(),
        ...     s3_path="s3://bucket/workspace_abc123/file_xyz789.pdf",
        ...     sha256_checksum=SHA256Hash("a" * 64),
        ...     size_bytes=1048576,
        ...     uploaded_at=datetime.now(timezone.utc)
        ... )
        >>>
        >>> # Serialize for publishing
        >>> json_str = event.to_json()
        >>> print(json_str)
        {
            "event_version": "1.0",
            "event_type": "FILE_LOAD_COMPLETED",
            "timestamp": "2026-05-06T15:30:00Z",
            "payload": {...}
        }
        >>>
        >>> # Get NATS subject name
        >>> print(event.subject_name)
        "upload.file.load_completed"
    """

    # Payload fields (file metadata) - required, no defaults
    file_id: UUID
    workspace_id: UUID
    s3_path: str
    sha256_checksum: SHA256Hash
    size_bytes: int
    uploaded_at: datetime

    # Envelope fields (metadata) - optional, with defaults
    event_version: str = "1.0"
    event_type: str = "FILE_LOAD_COMPLETED"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate invariants after initialization.

        Raises:
            ValueError: If validation fails for any field
            TypeError: If field types are incorrect
        """
        # Validate event_version
        if self.event_version != "1.0":
            raise ValueError("event_version must be '1.0' for v1 events")

        # Validate event_type
        if self.event_type != "FILE_LOAD_COMPLETED":
            raise ValueError("event_type must be 'FILE_LOAD_COMPLETED'")

        # Validate UUIDs
        if not isinstance(self.file_id, UUID):
            raise TypeError("file_id must be UUID")
        if not isinstance(self.workspace_id, UUID):
            raise TypeError("workspace_id must be UUID")

        # Validate nil UUIDs (all zeros)
        nil_uuid = UUID("00000000-0000-0000-0000-000000000000")
        if self.file_id == nil_uuid:
            raise ValueError("file_id cannot be nil UUID")
        if self.workspace_id == nil_uuid:
            raise ValueError("workspace_id cannot be nil UUID")

        # Validate timestamps are timezone-aware
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        if self.uploaded_at.tzinfo is None:
            raise ValueError("uploaded_at must be timezone-aware")

        # Validate size_bytes is positive and within safe JSON integer range
        if self.size_bytes <= 0:
            raise ValueError("size_bytes must be positive")
        max_safe_json_integer = 9007199254740991  # 2^53 - 1
        if self.size_bytes > max_safe_json_integer:
            raise ValueError(f"size_bytes {self.size_bytes} exceeds safe JSON integer range")

        # Validate SHA256 checksum format (64-char lowercase hex)
        checksum_str = str(self.sha256_checksum)
        if not re.match(r"^[a-f0-9]{64}$", checksum_str):
            raise ValueError(
                f"sha256_checksum must be 64-character lowercase hex string, got: {checksum_str}"
            )

        # Validate s3_path is not None
        if self.s3_path is None:
            raise ValueError("s3_path cannot be None")

        # Validate s3_path pattern (workspace isolation)
        if not self.s3_path.startswith("s3://"):
            raise ValueError("s3_path must start with 's3://'")

        # Validate workspace_id appears as a proper path segment
        if f"/workspace_{self.workspace_id}/" not in self.s3_path:
            raise ValueError(
                f"s3_path must contain workspace path segment: /workspace_{self.workspace_id}/"
            )

        # Validate file_id appears in s3_path
        if str(self.file_id) not in self.s3_path:
            raise ValueError(f"s3_path must contain file_id: {self.file_id}")

        # Validate temporal consistency (upload must complete before event created)
        # This is checked last so other field validations fail first
        if self.uploaded_at > self.timestamp:
            raise ValueError(
                "uploaded_at cannot be after timestamp (file cannot be uploaded in the future)"
            )

    @property
    def subject_name(self) -> str:
        """Return NATS subject name for this event.

        Subject: upload.file.load_completed

        Follows NATS hierarchical naming convention:
        - Namespace: upload (service domain)
        - Resource: file (resource type)
        - Action: load_completed (lifecycle event)

        Returns:
            str: NATS subject name for publishing
        """
        return "upload.file.load_completed"

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary representation.

        Returns dictionary with envelope fields and nested payload.
        Timestamps normalized to UTC and converted to ISO 8601 strings.
        UUIDs converted to string format.
        SHA256Hash converted to hex string.

        Note: Uses camelCase for eventType and eventVersion per AC requirements.

        Returns:
            dict: Event as dictionary with envelope and payload structure
        """
        # Normalize timestamps to UTC before serialization
        timestamp_utc = self.timestamp.astimezone(UTC)
        uploaded_at_utc = self.uploaded_at.astimezone(UTC)

        return {
            "eventVersion": self.event_version,  # camelCase per AC #2
            "eventType": self.event_type,  # camelCase per AC #2
            "timestamp": timestamp_utc.isoformat(),
            "payload": {
                "file_id": str(self.file_id),
                "workspace_id": str(self.workspace_id),
                "s3_path": self.s3_path,
                "sha256_checksum": str(self.sha256_checksum),
                "size_bytes": self.size_bytes,
                "uploaded_at": uploaded_at_utc.isoformat(),
            },
        }

    def to_json(self) -> str:
        """Serialize event to JSON string for NATS/webhook publishing.

        Returns compact JSON (no indentation) with ISO 8601 timestamps.

        Returns:
            str: JSON-serialized event string

        Raises:
            SerializationError: If JSON serialization fails
        """
        try:
            return json.dumps(self.to_dict())
        except Exception as e:
            raise SerializationError(
                f"Failed to serialize FileLoadCompletedEvent to JSON: {e}"
            ) from e
