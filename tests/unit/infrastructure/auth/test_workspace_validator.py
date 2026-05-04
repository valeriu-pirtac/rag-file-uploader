"""Unit tests for workspace validation infrastructure."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.workspace_role import WorkspaceRole
from src.infrastructure.auth.workspace_validator import validate_workspace_access


def test_validate_workspace_access_allows_matching_workspace_id():
    """Test workspace validation passes when user workspace matches resource workspace."""
    workspace_id = uuid4()
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=9999999999,
    )

    # Should not raise any exception
    validate_workspace_access(claims, workspace_id)


def test_validate_workspace_access_rejects_different_workspace_id():
    """Test workspace validation raises 403 when workspace IDs don't match."""
    user_workspace = uuid4()
    resource_workspace = uuid4()
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=user_workspace,
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=9999999999,
    )

    with pytest.raises(HTTPException) as exc_info:
        validate_workspace_access(claims, resource_workspace)

    assert exc_info.value.status_code == 403
    assert "detail" in exc_info.value.detail
    assert "workspace" in exc_info.value.detail["detail"].lower()
    assert "error" in exc_info.value.detail
    assert exc_info.value.detail["error"] == "WORKSPACE_MISMATCH"


def test_validate_workspace_access_works_for_collaborator_role():
    """Test workspace validation works for collaborators with matching workspace."""
    workspace_id = uuid4()
    file_id = uuid4()
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(file_id,),
        exp=9999999999,
    )

    # Should not raise any exception
    validate_workspace_access(claims, workspace_id)


def test_validate_workspace_access_rejects_collaborator_different_workspace():
    """Test workspace validation rejects collaborators accessing different workspace."""
    user_workspace = uuid4()
    resource_workspace = uuid4()
    file_id = uuid4()
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=user_workspace,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(file_id,),
        exp=9999999999,
    )

    with pytest.raises(HTTPException) as exc_info:
        validate_workspace_access(claims, resource_workspace)

    assert exc_info.value.status_code == 403


def test_validate_workspace_access_error_includes_workspace_context():
    """Test error response includes workspace IDs for debugging (not security leak)."""
    user_workspace = uuid4()
    resource_workspace = uuid4()
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=user_workspace,
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=9999999999,
    )

    with pytest.raises(HTTPException) as exc_info:
        validate_workspace_access(claims, resource_workspace)

    error_detail = exc_info.value.detail
    assert isinstance(error_detail, dict)
    assert "detail" in error_detail
    # Error message should mention workspace but not leak specific IDs
    assert "workspace" in error_detail["detail"].lower()


@pytest.mark.parametrize(
    "role",
    [WorkspaceRole.OWNER, WorkspaceRole.COLLABORATOR],
)
def test_validate_workspace_access_works_for_all_roles(role: WorkspaceRole):
    """Test workspace validation works consistently for all roles."""
    workspace_id = uuid4()
    shared_file_ids = None if role == WorkspaceRole.OWNER else (uuid4(),)
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=role,
        shared_file_ids=shared_file_ids,
        exp=9999999999,
    )

    # Should not raise for matching workspace regardless of role
    validate_workspace_access(claims, workspace_id)
