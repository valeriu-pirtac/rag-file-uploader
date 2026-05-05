"""Pydantic schemas for upload session API endpoints.

This module defines request/response schemas for the uploads API.
Schemas handle validation and serialization between external API format
(camelCase JSON) and internal Python format (snake_case).

Architecture:
    - BaseAPISchema: Base class with camelCase conversion configuration
    - Request schemas: Validate incoming API requests
    - Response schemas: Format outgoing API responses
    - Field validators: Enforce business rules at API boundary

camelCase Conversion:
    External API uses camelCase (Vue.js friendly), internal Python uses
    snake_case (PEP 8 compliant). Pydantic's alias_generator handles automatic
    conversion:
        - Python field: upload_id → JSON field: "uploadId"
        - Python field: mime_type → JSON field: "mimeType"
        - Python field: expires_at → JSON field: "expiresAt"

Integration Points:
    - Story 3.4: Maps to/from Application DTOs (InitiateUploadRequest/Response)
    - Story 2.2: Works with JWT authentication (workspace_id from claims)
    - Story 2.4: Works with RBAC middleware (require_role dependency)

Examples:
    >>> # Request schema with camelCase JSON
    >>> request_data = {
    ...     "filename": "document.pdf",
    ...     "size": 1048576,
    ...     "mimeType": "application/pdf",
    ...     "sha256Checksum": "a" * 64
    ... }
    >>> request = InitiateUploadRequest(**request_data)
    >>> print(request.filename)
    document.pdf
    >>> print(request.mime_type)  # snake_case in Python
    application/pdf
    >>>
    >>> # Response schema converts to camelCase JSON
    >>> from uuid import uuid4
    >>> from datetime import datetime, timezone, timedelta
    >>> response = InitiateUploadResponse(
    ...     upload_id=uuid4(),
    ...     offset=0,
    ...     expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
    ... )
    >>> response_json = response.model_dump(by_alias=True, mode="json")
    >>> print("uploadId" in response_json)  # camelCase in JSON
    True
    >>> print("upload_id" in response_json)  # snake_case not present
    False
"""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer
from pydantic.alias_generators import to_camel


class BaseAPISchema(BaseModel):
    """Base schema for all API request/response models.

    Provides common configuration for automatic camelCase conversion
    between external API format and internal Python format.

    Configuration:
        - alias_generator=to_camel: Converts snake_case to camelCase
        - populate_by_name=True: Accepts both snake_case and camelCase in input

    Examples:
        >>> class MySchema(BaseAPISchema):
        ...     user_id: UUID
        ...     created_at: datetime
        >>> # JSON will use: {"userId": "...", "createdAt": "..."}
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class InitiateUploadRequest(BaseAPISchema):
    """Request schema for POST /v1/uploads endpoint.

    Validates incoming request to create a new upload session. Enforces
    business rules at API boundary before passing to application layer.

    JSON Format (camelCase):
        {
            "filename": "document.pdf",
            "size": 1048576,
            "mimeType": "application/pdf",
            "sha256Checksum": "a" * 64
        }

    Validation Rules:
        - filename: Non-empty, 1-255 characters, no path separators
        - size: Positive integer, ≤ 1 GB (1073741824 bytes)
        - mime_type: Must be "application/pdf"
        - sha256_checksum: Exactly 64 lowercase hexadecimal characters

    Attributes:
        filename: Original filename for display purposes (1-255 characters)
        size: Total file size in bytes (must be > 0 and ≤ 1 GB)
        mime_type: MIME type (must be "application/pdf")
        sha256_checksum: Full file SHA-256 checksum as 64-char hex string

    Examples:
        >>> request = InitiateUploadRequest(
        ...     filename="document.pdf",
        ...     size=1048576,
        ...     mime_type="application/pdf",
        ...     sha256_checksum="a" * 64
        ... )
        >>> print(request.filename)
        document.pdf
        >>> print(request.mime_type)
        application/pdf
        >>>
        >>> # Invalid size raises ValidationError
        >>> invalid_request = InitiateUploadRequest(
        ...     filename="large.pdf",
        ...     size=2147483648,  # > 1 GB
        ...     mime_type="application/pdf",
        ...     sha256_checksum="a" * 64
        ... )
        Traceback (most recent call last):
            ...
        pydantic.ValidationError: ...
    """

    filename: Annotated[
        str,
        Field(
            min_length=1,
            max_length=255,
            description="Original filename for display purposes",
            examples=["document.pdf", "report-2026.pdf"],
        ),
    ]

    size: Annotated[
        int,
        Field(
            gt=0,
            le=1073741824,  # 1 GB in bytes
            description="Total file size in bytes (max 1 GB)",
            examples=[1048576, 10485760],
        ),
    ]

    mime_type: Annotated[
        str,
        Field(
            pattern=r"^application/pdf$",
            description="MIME type (must be application/pdf)",
            examples=["application/pdf"],
        ),
    ]

    sha256_checksum: Annotated[
        str,
        Field(
            pattern=r"^[a-f0-9]{64}$",
            description="SHA-256 checksum (64 lowercase hex characters)",
            examples=[
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            ],
        ),
    ]


class InitiateUploadResponse(BaseAPISchema):
    """Response schema for POST /v1/uploads endpoint.

    Returns session information after successfully creating a new upload
    session. Client uses this data to begin chunked upload process.

    JSON Format (camelCase):
        {
            "uploadId": "550e8400-e29b-41d4-a716-446655440000",
            "offset": 0,
            "expiresAt": "2026-05-06T12:00:00.123456Z"
        }

    Attributes:
        upload_id: Unique upload session identifier (UUID v4)
            Maps to "uploadId" in JSON
        offset: Current upload offset in bytes (always 0 for new sessions)
        expires_at: Session expiration timestamp (24 hours from creation, UTC)
            Maps to "expiresAt" in JSON with ISO 8601 format and Z suffix

    Examples:
        >>> from uuid import uuid4
        >>> from datetime import datetime, timezone, timedelta
        >>> response = InitiateUploadResponse(
        ...     upload_id=uuid4(),
        ...     offset=0,
        ...     expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
        ... )
        >>> print(f"Upload ID: {response.upload_id}")
        Upload ID: 550e8400-e29b-41d4-a716-446655440000
        >>>
        >>> # Serialize to JSON with camelCase
        >>> json_data = response.model_dump(by_alias=True, mode="json")
        >>> print("uploadId" in json_data)
        True
        >>> print("expiresAt" in json_data)
        True
    """

    upload_id: Annotated[
        UUID,
        Field(
            description="Unique upload session identifier",
            examples=["550e8400-e29b-41d4-a716-446655440000"],
        ),
    ]

    offset: Annotated[
        int,
        Field(
            ge=0,
            description="Current upload offset in bytes (0 for new sessions)",
            examples=[0],
        ),
    ]

    expires_at: Annotated[
        datetime,
        Field(
            description="Session expiration timestamp (ISO 8601 UTC)",
            examples=["2026-05-06T12:00:00.123456Z"],
        ),
    ]

    @field_serializer("expires_at")
    def serialize_datetime(self, dt: datetime) -> str:
        """Serialize datetime to ISO 8601 with Z suffix.

        Converts datetime to ISO 8601 format and replaces +00:00 with Z
        for UTC timezone indicator.

        Args:
            dt: Datetime to serialize

        Returns:
            ISO 8601 string with Z suffix (e.g., "2026-05-06T12:00:00.123456Z")
        """
        return dt.isoformat().replace("+00:00", "Z")


class ErrorResponse(BaseAPISchema):
    """Standard error response schema for all API error responses.

    Provides consistent error structure across all endpoints.
    Used for 4xx and 5xx HTTP error responses.

    JSON Format (camelCase):
        {
            "error": "ERROR_CODE",
            "message": "Human-readable error description",
            "details": {"field": "value"}
        }

    Attributes:
        error: Error code in UPPER_SNAKE_CASE format
        message: Human-readable error message for end users
        details: Additional error-specific context (optional)

    Examples:
        >>> error = ErrorResponse(
        ...     error="RATE_LIMIT_EXCEEDED",
        ...     message="Too many concurrent uploads",
        ...     details={"current_uploads": 10, "limit": 10}
        ... )
        >>> print(error.error)
        RATE_LIMIT_EXCEEDED
    """

    error: Annotated[
        str,
        Field(
            description="Error code in UPPER_SNAKE_CASE format",
            examples=["RATE_LIMIT_EXCEEDED", "FILE_SIZE_LIMIT_EXCEEDED"],
        ),
    ]

    message: Annotated[
        str,
        Field(
            description="Human-readable error message",
            examples=["Workspace has reached maximum concurrent uploads"],
        ),
    ]

    details: Annotated[
        dict[str, Any],
        Field(
            default_factory=dict,
            description="Additional error-specific context",
            examples=[{"current_uploads": 10, "limit": 10, "retry_after_seconds": 60}],
        ),
    ]
