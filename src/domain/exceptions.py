"""Domain exceptions for the rag-file-uploader service.

This module defines custom exceptions used across the domain layer.
"""


class DomainException(Exception):
    """Base exception for all domain-layer errors."""

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
