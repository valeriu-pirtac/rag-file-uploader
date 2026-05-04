import pytest

from src.domain.exceptions import (
    AuthenticationError,
    ChecksumMismatchError,
    DomainException,
    InvalidTokenError,
    TokenExpiredError,
    UploadSessionNotFoundError,
)


def test_domain_errors_inherit_from_domain_exception() -> None:
    assert issubclass(UploadSessionNotFoundError, DomainException)
    assert issubclass(ChecksumMismatchError, DomainException)


def test_authentication_error_inherits_from_domain_exception() -> None:
    """Test that AuthenticationError is a DomainException."""
    error = AuthenticationError("test message")
    assert isinstance(error, DomainException)
    assert str(error) == "test message"


def test_token_expired_error_inherits_from_authentication_error() -> None:
    """Test that TokenExpiredError is an AuthenticationError."""
    error = TokenExpiredError("token expired")
    assert isinstance(error, AuthenticationError)
    assert isinstance(error, DomainException)
    assert str(error) == "token expired"


def test_invalid_token_error_inherits_from_authentication_error() -> None:
    """Test that InvalidTokenError is an AuthenticationError."""
    error = InvalidTokenError("invalid token")
    assert isinstance(error, AuthenticationError)
    assert isinstance(error, DomainException)
    assert str(error) == "invalid token"


def test_authentication_errors_can_be_raised() -> None:
    """Test that authentication errors can be raised and caught."""
    with pytest.raises(AuthenticationError):
        raise AuthenticationError("auth failed")

    with pytest.raises(TokenExpiredError):
        raise TokenExpiredError("token expired")

    with pytest.raises(InvalidTokenError):
        raise InvalidTokenError("invalid token")


def test_token_expired_error_can_be_caught_as_authentication_error() -> None:
    """Test that TokenExpiredError can be caught as AuthenticationError."""
    with pytest.raises(AuthenticationError):
        raise TokenExpiredError("token expired")


def test_invalid_token_error_can_be_caught_as_authentication_error() -> None:
    """Test that InvalidTokenError can be caught as AuthenticationError."""
    with pytest.raises(AuthenticationError):
        raise InvalidTokenError("invalid token")
