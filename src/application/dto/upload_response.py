"""Data Transfer Objects for upload session responses.

This module defines DTOs for upload session responses returned to clients.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class InitiateUploadResponse:
    """DTO for initiate upload session response.

    Contains session information returned to client after successfully
    creating a new upload session. Client uses this data to begin chunked
    upload process.

    This DTO will be serialized to JSON with camelCase field names in the
    API layer (via Pydantic alias_generator). Internal Python code uses
    snake_case as per Python conventions.

    Attributes:
        session_id: Unique upload session identifier (UUID v4)
        offset: Current upload offset in bytes (always 0 for new sessions)
        expires_at: Session expiration timestamp (24 hours from creation,
            UTC timezone-aware)

    API Response Format (camelCase JSON):
        {
            "sessionId": "550e8400-e29b-41d4-a716-446655440000",
            "offset": 0,
            "expiresAt": "2026-05-06T12:00:00.123456Z"
        }

    Examples:
        >>> from uuid import uuid4
        >>> from datetime import datetime, timezone, timedelta
        >>> session_id = uuid4()
        >>> expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        >>> response = InitiateUploadResponse(
        ...     session_id=session_id,
        ...     offset=0,
        ...     expires_at=expires_at
        ... )
        >>> print(f"Session: {response.session_id}")
        Session: 550e8400-e29b-41d4-a716-446655440000
        >>> print(f"Offset: {response.offset}")
        Offset: 0
    """

    session_id: UUID
    offset: int
    expires_at: datetime

    def __post_init__(self) -> None:
        """Validate response fields.

        Raises:
            ValueError: If offset is negative or expires_at is not timezone-aware
        """
        if self.offset < 0:
            raise ValueError(f"offset must be >= 0, got {self.offset}")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware (UTC)")
