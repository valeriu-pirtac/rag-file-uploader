"""Unit tests for RBAC middleware.

Tests role-based access control enforcement for workspace roles.
"""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.workspace_role import WorkspaceRole
from src.infrastructure.auth.rbac_middleware import require_owner, require_role


# Fixtures for test JWT claims


@pytest.fixture
def owner_claims() -> JWTClaims:
    """Fixture for OWNER role JWT claims."""
    return JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=9999999999,  # Far future
    )


@pytest.fixture
def collaborator_claims() -> JWTClaims:
    """Fixture for COLLABORATOR role JWT claims."""
    return JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(uuid4(),),
        exp=9999999999,
    )


# Test require_role() function


@pytest.mark.asyncio
async def test_require_role_allows_matching_role(owner_claims: JWTClaims) -> None:
    """Test require_role allows access when role matches."""
    # Create dependency for OWNER role
    dependency = require_role(WorkspaceRole.OWNER)

    # Get the check_role function
    check_role = dependency

    # Call with matching role
    result = await check_role(current_user=owner_claims)

    # Verify it returns the claims (pass-through)
    assert result == owner_claims
    assert result.workspace_role == WorkspaceRole.OWNER


@pytest.mark.asyncio
async def test_require_role_rejects_mismatched_role(collaborator_claims: JWTClaims) -> None:
    """Test require_role rejects access when role doesn't match."""
    # Create dependency for OWNER role
    dependency = require_role(WorkspaceRole.OWNER)

    # Get the check_role function
    check_role = dependency

    # Call with COLLABORATOR role (should fail)
    with pytest.raises(HTTPException) as exc_info:
        await check_role(current_user=collaborator_claims)

    # Verify 403 Forbidden
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_error_includes_role_details(collaborator_claims: JWTClaims) -> None:
    """Test error response includes required_role."""
    dependency = require_role(WorkspaceRole.OWNER)
    check_role = dependency

    with pytest.raises(HTTPException) as exc_info:
        await check_role(current_user=collaborator_claims)

    # Verify error detail structure
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["required_role"] == "owner"
    assert "owner role" in detail["detail"].lower()


@pytest.mark.asyncio
async def test_require_role_error_message_format(collaborator_claims: JWTClaims) -> None:
    """Test error message follows expected format."""
    dependency = require_role(WorkspaceRole.OWNER)
    check_role = dependency

    with pytest.raises(HTTPException) as exc_info:
        await check_role(current_user=collaborator_claims)

    detail = exc_info.value.detail
    assert "Insufficient permissions - owner role required" == detail["detail"]


@pytest.mark.asyncio
async def test_require_role_allows_collaborator_role_when_required(
    collaborator_claims: JWTClaims,
) -> None:
    """Test require_role allows COLLABORATOR when that role is required."""
    # Create dependency for COLLABORATOR role
    dependency = require_role(WorkspaceRole.COLLABORATOR)
    check_role = dependency

    # Call with matching COLLABORATOR role
    result = await check_role(current_user=collaborator_claims)

    # Verify it returns the claims
    assert result == collaborator_claims
    assert result.workspace_role == WorkspaceRole.COLLABORATOR


@pytest.mark.asyncio
async def test_require_role_rejects_owner_when_collaborator_required(
    owner_claims: JWTClaims,
) -> None:
    """Test require_role rejects OWNER when COLLABORATOR is required."""
    # Create dependency for COLLABORATOR role
    dependency = require_role(WorkspaceRole.COLLABORATOR)
    check_role = dependency

    # Call with OWNER role (should fail)
    with pytest.raises(HTTPException) as exc_info:
        await check_role(current_user=owner_claims)

    # Verify 403 Forbidden
    assert exc_info.value.status_code == 403
    detail = exc_info.value.detail
    assert detail["required_role"] == "collaborator"


# Test require_owner() convenience function


@pytest.mark.asyncio
async def test_require_owner_allows_owner_role(owner_claims: JWTClaims) -> None:
    """Test require_owner allows OWNER role."""
    # Create dependency
    dependency = require_owner()
    check_role = dependency

    # Call with OWNER role
    result = await check_role(current_user=owner_claims)

    # Verify it returns the claims
    assert result == owner_claims
    assert result.workspace_role == WorkspaceRole.OWNER


@pytest.mark.asyncio
async def test_require_owner_rejects_collaborator_role(
    collaborator_claims: JWTClaims,
) -> None:
    """Test require_owner rejects COLLABORATOR role with 403."""
    dependency = require_owner()
    check_role = dependency

    with pytest.raises(HTTPException) as exc_info:
        await check_role(current_user=collaborator_claims)

    # Verify 403 Forbidden
    assert exc_info.value.status_code == 403

    # Verify error includes "owner" in message
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert "owner" in detail["detail"].lower()


@pytest.mark.asyncio
async def test_require_owner_error_details(collaborator_claims: JWTClaims) -> None:
    """Test require_owner error includes correct role details."""
    dependency = require_owner()
    check_role = dependency

    with pytest.raises(HTTPException) as exc_info:
        await check_role(current_user=collaborator_claims)

    detail = exc_info.value.detail
    assert detail["required_role"] == "owner"


# Test role enforcement with different workspace contexts


@pytest.mark.asyncio
async def test_require_role_preserves_workspace_context(owner_claims: JWTClaims) -> None:
    """Test that require_role preserves workspace_id and user_id in returned claims."""
    dependency = require_role(WorkspaceRole.OWNER)
    check_role = dependency

    result = await check_role(current_user=owner_claims)

    # Verify all claim fields are preserved
    assert result.user_id == owner_claims.user_id
    assert result.workspace_id == owner_claims.workspace_id
    assert result.workspace_role == owner_claims.workspace_role
    assert result.shared_file_ids == owner_claims.shared_file_ids
    assert result.exp == owner_claims.exp


@pytest.mark.asyncio
async def test_require_role_preserves_shared_file_ids(
    collaborator_claims: JWTClaims,
) -> None:
    """Test that collaborator's shared_file_ids are preserved when role matches."""
    dependency = require_role(WorkspaceRole.COLLABORATOR)
    check_role = dependency

    result = await check_role(current_user=collaborator_claims)

    # Verify shared_file_ids preserved
    assert result.shared_file_ids == collaborator_claims.shared_file_ids
    assert result.shared_file_ids is not None
    assert len(result.shared_file_ids) > 0


# Test type safety


@pytest.mark.asyncio
async def test_require_role_returns_jwt_claims_type(owner_claims: JWTClaims) -> None:
    """Test that require_role returns JWTClaims type for type checkers."""
    dependency = require_role(WorkspaceRole.OWNER)
    check_role = dependency

    result = await check_role(current_user=owner_claims)

    # Verify return type
    assert isinstance(result, JWTClaims)


@pytest.mark.asyncio
async def test_require_owner_returns_jwt_claims_type(owner_claims: JWTClaims) -> None:
    """Test that require_owner returns JWTClaims type for type checkers."""
    dependency = require_owner()
    check_role = dependency

    result = await check_role(current_user=owner_claims)

    # Verify return type
    assert isinstance(result, JWTClaims)
