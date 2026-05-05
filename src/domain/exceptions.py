"""Domain exceptions for the rag-file-uploader service.

This module defines custom exceptions used across the domain layer.
"""


class DomainException(Exception):
    """Base exception for all domain-layer errors."""

    pass


class AuthenticationError(DomainException):
    """Raised when authentication fails."""

    pass


class TokenExpiredError(AuthenticationError):
    """Raised when a JWT token has expired."""

    pass


class InvalidTokenError(AuthenticationError):
    """Raised when a JWT token is invalid or malformed."""

    pass


class UploadSessionNotFoundError(DomainException):
    """Raised when an upload session cannot be found."""

    pass


class ChecksumMismatchError(DomainException):
    """Raised when chunk checksum verification fails."""

    pass


class DuplicateFileError(DomainException):
    """Raised when a file with the same SHA-256 already exists in the workspace."""

    pass


class FileSizeLimitExceededError(DomainException):
    """Raised when a file size exceeds the maximum allowed limit.

    Attributes:
        file_size: The size of the file in bytes
        max_size: The maximum allowed file size in bytes
    """

    def __init__(self, file_size: int, max_size: int) -> None:
        self.file_size = file_size
        self.max_size = max_size
        super().__init__(
            f"File size {file_size} bytes exceeds maximum allowed size of {max_size} bytes"
        )


class UnsupportedMediaTypeError(DomainException):
    """Raised when a file's MIME type is not supported.

    Attributes:
        provided_mime_type: The MIME type that was provided
        allowed_mime_types: The list of allowed MIME types
    """

    def __init__(self, provided_mime_type: str, allowed_mime_types: list[str]) -> None:
        self.provided_mime_type = provided_mime_type
        self.allowed_mime_types = allowed_mime_types
        super().__init__(
            f"MIME type '{provided_mime_type}' is not supported. "
            f"Allowed types: {', '.join(allowed_mime_types)}"
        )
