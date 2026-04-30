from src.domain.exceptions import (
    ChecksumMismatchError,
    DomainException,
    DuplicateFileError,
    UploadSessionNotFoundError,
)


def test_domain_errors_inherit_from_domain_exception() -> None:
    assert issubclass(UploadSessionNotFoundError, DomainException)
    assert issubclass(ChecksumMismatchError, DomainException)
    assert issubclass(DuplicateFileError, DomainException)
