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


# Alias for protocol consistency (ISessionStore uses SessionNotFoundError)
SessionNotFoundError = UploadSessionNotFoundError


class InfrastructureError(DomainException):
    """Base exception for infrastructure layer failures.

    Raised when external dependencies fail (Redis, S3, NATS, ClamAV, etc.).
    This includes connection errors, timeouts, network issues, and other
    infrastructure-level problems.

    Examples:
        - Redis connection timeout
        - S3 bucket access denied
        - NATS publish failure
        - ClamAV daemon unreachable
    """

    pass


class SerializationError(InfrastructureError):
    """Raised when data serialization/deserialization fails.

    This indicates data corruption, invalid format, or incompatible schema
    changes between service versions.

    Examples:
        - Invalid JSON in Redis hash field
        - Missing required field during deserialization
        - Invalid UUID string format
        - Malformed datetime string
    """

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
