"""Unit tests for authentication middleware/dependency."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.domain.exceptions import InvalidTokenError, TokenExpiredError
from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.workspace_role import WorkspaceRole
from src.presentation.api.middleware.auth import get_current_user


@pytest.fixture
def mock_jwt_validator(mocker):
    """Create a mock JWT validator with async validate method."""
    validator = mocker.Mock()
    # Make validate an AsyncMock since it's now async
    validator.validate = AsyncMock()
    mocker.patch(
        "src.presentation.api.middleware.auth.get_jwt_validator",
        return_value=validator,
    )
    return validator


@pytest.mark.asyncio
async def test_get_current_user_with_valid_token(mock_jwt_validator):
    """Test get_current_user with valid Authorization header."""
    user_id = uuid4()
    workspace_id = uuid4()

    expected_claims = JWTClaims(
        user_id=user_id,
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=9999999999,
    )

    mock_jwt_validator.validate.return_value = expected_claims

    # Call with valid Bearer token
    claims = await get_current_user(authorization="Bearer valid.jwt.token")

    assert claims == expected_claims
    mock_jwt_validator.validate.assert_called_once_with("valid.jwt.token")


@pytest.mark.asyncio
async def test_missing_authorization_header_returns_401():
    """Test that missing Authorization header raises HTTPException with 401."""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(authorization=None)

    assert exc_info.value.status_code == 401

    assert "Missing" in exc_info.value.detail


@pytest.mark.asyncio
async def test_invalid_bearer_format_returns_401():
    """Test that invalid Bearer format raises HTTPException with 401."""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(authorization="InvalidFormat token")

    assert exc_info.value.status_code == 401
    assert "invalid Authorization header" in exc_info.value.detail


@pytest.mark.asyncio
async def test_expired_token_returns_401(mock_jwt_validator):
    """Test that expired token raises HTTPException with 401."""
    mock_jwt_validator.validate.side_effect = TokenExpiredError("JWT token has expired")

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(authorization="Bearer expired.jwt.token")

    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_invalid_token_returns_401(mock_jwt_validator):
    """Test that invalid token raises HTTPException with 401."""
    mock_jwt_validator.validate.side_effect = InvalidTokenError("Invalid token signature")

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(authorization="Bearer invalid.jwt.token")

    assert exc_info.value.status_code == 401
    assert "Invalid" in exc_info.value.detail or "invalid" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_bearer_token_extracted_correctly(mock_jwt_validator):
    """Test that Bearer token is extracted correctly from Authorization header."""
    user_id = uuid4()
    workspace_id = uuid4()

    expected_claims = JWTClaims(
        user_id=user_id,
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(uuid4(), uuid4()),
        exp=9999999999,
    )

    mock_jwt_validator.validate.return_value = expected_claims

    # Call with Bearer token
    await get_current_user(authorization="Bearer my.jwt.token")

    # Verify token was extracted (without "Bearer " prefix)
    mock_jwt_validator.validate.assert_called_once_with("my.jwt.token")


@pytest.mark.asyncio
async def test_whitespace_in_bearer_token_handled():
    """Test that whitespace in Bearer token is handled correctly."""
    # Should fail with missing/invalid format
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(authorization="Bearer ")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_case_sensitive_bearer_keyword():
    """Test that Bearer keyword is case-sensitive."""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(authorization="bearer token")

    assert exc_info.value.status_code == 401
    assert "invalid Authorization header" in exc_info.value.detail
