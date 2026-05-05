"""Data Transfer Objects for upload session requests.

This module defines DTOs for initiating and managing upload sessions.
DTOs are plain dataclasses for data transfer between application layers.
"""

from dataclasses import dataclass
from uuid import UUID

from src.domain.entities.upload_session import (
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE_BYTES,
)
from src.domain.exceptions import (
    FileSizeLimitExceededError,
    UnsupportedMediaTypeError,
)


@dataclass
class InitiateUploadRequest:
    """DTO for initiate upload session request.

    Contains all data required to create a new upload session. Validation
    methods ensure data integrity before use case execution.

    This DTO is created from API layer input (after authentication/authorization)
    and passed to the InitiateUploadUseCase for processing.

    Attributes:
        workspace_id: Workspace UUID (extracted from JWT claims)
        filename: Original filename for display purposes
        size: Total file size in bytes (must be ≤ 1 GB)
        mime_type: MIME type (must be "application/pdf")
        sha256_checksum: Full file SHA-256 checksum as 64-char hex string
            (used for deduplication)

    Validation Rules:
        - File size must be > 0 and ≤ 1 GB (MAX_FILE_SIZE_BYTES)
        - MIME type must be in ALLOWED_MIME_TYPES list
        - All other validations delegated to domain layer

    Examples:
        >>> from uuid import uuid4
        >>> request = InitiateUploadRequest(
        ...     workspace_id=uuid4(),
        ...     filename="document.pdf",
        ...     size=1048576,  # 1 MB
        ...     mime_type="application/pdf",
        ...     sha256_checksum="a" * 64
        ... )
        >>> request.validate_size()  # No error - size is valid
        >>> request.validate_mime_type()  # No error - PDF is allowed
    """

    workspace_id: UUID
    filename: str
    size: int
    mime_type: str
    sha256_checksum: str

    def validate_filename(self) -> None:
        """Validate filename meets requirements.

        Filename must not be empty, contain path separators, null bytes,
        or exceed maximum length of 255 characters.

        Raises:
            ValueError: If filename is invalid

        Examples:
            >>> request = InitiateUploadRequest(
            ...     workspace_id=uuid4(),
            ...     filename="",
            ...     size=1024,
            ...     mime_type="application/pdf",
            ...     sha256_checksum="a" * 64
            ... )
            >>> request.validate_filename()
            Traceback (most recent call last):
                ...
            ValueError: filename cannot be empty
        """
        if not self.filename or not self.filename.strip():
            raise ValueError("filename cannot be empty")
        if "/" in self.filename or "\\" in self.filename:
            raise ValueError("filename cannot contain path separators")
        if "\x00" in self.filename:
            raise ValueError("filename cannot contain null bytes")
        if len(self.filename) > 255:
            raise ValueError("filename cannot exceed 255 characters")

    def validate_checksum(self) -> None:
        """Validate SHA-256 checksum format.

        Checksum must be exactly 64 lowercase hexadecimal characters.
        This validation prevents failures later in SHA256Hash value object
        after rate limit has been incremented.

        Raises:
            ValueError: If checksum format is invalid

        Examples:
            >>> request = InitiateUploadRequest(
            ...     workspace_id=uuid4(),
            ...     filename="document.pdf",
            ...     size=1024,
            ...     mime_type="application/pdf",
            ...     sha256_checksum="INVALID"
            ... )
            >>> request.validate_checksum()
            Traceback (most recent call last):
                ...
            ValueError: sha256_checksum must be exactly 64 characters
        """
        if len(self.sha256_checksum) != 64:
            raise ValueError("sha256_checksum must be exactly 64 characters")
        if not all(c in "0123456789abcdef" for c in self.sha256_checksum):
            raise ValueError("sha256_checksum must be lowercase hexadecimal")

    def validate_size(self) -> None:
        """Validate file size is within allowed limit.

        File size must be positive and not exceed MAX_FILE_SIZE_BYTES (1 GB).
        This validation ensures resource limits are respected before creating
        expensive session state.

        Raises:
            FileSizeLimitExceededError: If size > MAX_FILE_SIZE_BYTES (1 GB)
            ValueError: If size <= 0 (invalid file size)

        Examples:
            >>> request = InitiateUploadRequest(
            ...     workspace_id=uuid4(),
            ...     filename="large.pdf",
            ...     size=1073741825,  # 1 GB + 1 byte
            ...     mime_type="application/pdf",
            ...     sha256_checksum="a" * 64
            ... )
            >>> request.validate_size()
            Traceback (most recent call last):
                ...
            FileSizeLimitExceededError: File size 1073741825 bytes exceeds...
        """
        if self.size <= 0:
            raise ValueError(f"File size must be positive, got {self.size}")

        if self.size > MAX_FILE_SIZE_BYTES:
            raise FileSizeLimitExceededError(file_size=self.size, max_size=MAX_FILE_SIZE_BYTES)

    def validate_mime_type(self) -> None:
        """Validate MIME type is in allowed list.

        Only PDF files are currently supported for upload. This ensures
        downstream processing (virus scanning, RAG pipeline) receives
        expected file types.

        Raises:
            UnsupportedMediaTypeError: If mime_type not in ALLOWED_MIME_TYPES

        Examples:
            >>> request = InitiateUploadRequest(
            ...     workspace_id=uuid4(),
            ...     filename="document.json",
            ...     size=1024,
            ...     mime_type="application/json",
            ...     sha256_checksum="a" * 64
            ... )
            >>> request.validate_mime_type()
            Traceback (most recent call last):
                ...
            UnsupportedMediaTypeError: MIME type 'application/json' is not supported...
        """
        # Normalize to lowercase for case-insensitive comparison
        normalized_mime = self.mime_type.lower()
        normalized_allowed = [m.lower() for m in ALLOWED_MIME_TYPES]

        if normalized_mime not in normalized_allowed:
            raise UnsupportedMediaTypeError(
                provided_mime_type=self.mime_type,
                allowed_mime_types=ALLOWED_MIME_TYPES,
            )
