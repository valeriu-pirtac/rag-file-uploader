"""Unit tests for file access validation infrastructure."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.workspace_role import WorkspaceRole
from src.infrastructure.auth.file_access_validator import validate_file_access


def test_validate_file_access_allows_owner_any_file():
    """Test OWNER role always passes file access validation."""
    workspace_id = uuid4()
    file_id = uuid4()
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=9999999999,
    )

    # Should not raise any exception - owners have access to all files
    validate_file_access(claims, file_id)


def test_validate_file_access_allows_collaborator_shared_file():
    """Test COLLABORATOR with file_id in shared_file_ids passes validation."""
    workspace_id = uuid4()
    file_id = uuid4()
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(file_id,),
        exp=9999999999,
    )

    # Should not raise any exception - file is in shared_file_ids
    validate_file_access(claims, file_id)


def test_validate_file_access_rejects_collaborator_non_shared_file():
    """Test COLLABORATOR without file_id in shared_file_ids receives 403."""
    workspace_id = uuid4()
    shared_file = uuid4()
    non_shared_file = uuid4()
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(shared_file,),
        exp=9999999999,
    )

    with pytest.raises(HTTPException) as exc_info:
        validate_file_access(claims, non_shared_file)

    assert exc_info.value.status_code == 403
    assert "detail" in exc_info.value.detail
    assert "file" in exc_info.value.detail["detail"].lower()
    assert "error" in exc_info.value.detail
    assert exc_info.value.detail["error"] == "FILE_ACCESS_DENIED"


def test_validate_file_access_rejects_collaborator_empty_shared_files():
    """Test COLLABORATOR with empty shared_file_ids tuple receives 403."""
    workspace_id = uuid4()
    file_id = uuid4()
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(),  # Empty tuple
        exp=9999999999,
    )

    with pytest.raises(HTTPException) as exc_info:
        validate_file_access(claims, file_id)

    assert exc_info.value.status_code == 403


def test_validate_file_access_allows_collaborator_multiple_shared_files():
    """Test COLLABORATOR can access any file in their shared_file_ids list."""
    workspace_id = uuid4()
    file1 = uuid4()
    file2 = uuid4()
    file3 = uuid4()
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(file1, file2, file3),
        exp=9999999999,
    )

    # All three files should be accessible
    validate_file_access(claims, file1)
    validate_file_access(claims, file2)
    validate_file_access(claims, file3)

    # File not in list should be denied
    file4 = uuid4()
    with pytest.raises(HTTPException):
        validate_file_access(claims, file4)


def test_validate_file_access_error_includes_file_context():
    """Test error response includes appropriate context for debugging."""
    workspace_id = uuid4()
    file_id = uuid4()
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(),
        exp=9999999999,
    )

    with pytest.raises(HTTPException) as exc_info:
        validate_file_access(claims, file_id)

    error_detail = exc_info.value.detail
    assert isinstance(error_detail, dict)
    assert "detail" in error_detail
    # Error message should mention file access but not leak specific IDs
    assert "file" in error_detail["detail"].lower()


def test_validate_file_access_uses_has_access_to_file_method():
    """Test validation leverages JWTClaims.has_access_to_file() domain method."""
    workspace_id = uuid4()
    file_id = uuid4()

    # Test OWNER (has_access_to_file returns True)
    owner_claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=9999999999,
    )
    assert owner_claims.has_access_to_file(file_id) is True
    validate_file_access(owner_claims, file_id)  # Should not raise

    # Test COLLABORATOR with access (has_access_to_file returns True)
    collab_with_access = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(file_id,),
        exp=9999999999,
    )
    assert collab_with_access.has_access_to_file(file_id) is True
    validate_file_access(collab_with_access, file_id)  # Should not raise

    # Test COLLABORATOR without access (has_access_to_file returns False)
    collab_without_access = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(),
        exp=9999999999,
    )
    assert collab_without_access.has_access_to_file(file_id) is False
    with pytest.raises(HTTPException):
        validate_file_access(collab_without_access, file_id)


@pytest.mark.parametrize(
    "num_shared_files",
    [1, 5, 10, 100],
)
def test_validate_file_access_scales_with_shared_files(num_shared_files: int):
    """Test file access validation works with various shared_file_ids sizes."""
    workspace_id = uuid4()
    shared_files = tuple(uuid4() for _ in range(num_shared_files))
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=shared_files,
        exp=9999999999,
    )

    # All shared files should be accessible
    for file_id in shared_files:
        validate_file_access(claims, file_id)

    # Non-shared file should be denied
    non_shared_file = uuid4()
    with pytest.raises(HTTPException):
        validate_file_access(claims, non_shared_file)
