"""Unit tests for JWTClaims value object."""

import dataclasses
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.workspace_role import WorkspaceRole


def test_jwt_claims_creation_with_all_fields() -> None:
    """Test creating JWTClaims with all fields populated."""
    user_id = uuid4()
    workspace_id = uuid4()
    file_ids = (uuid4(), uuid4(), uuid4())
    exp = int(datetime.now(UTC).timestamp()) + 3600

    claims = JWTClaims(
        user_id=user_id,
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=file_ids,
        exp=exp,
    )

    assert claims.user_id == user_id
    assert claims.workspace_id == workspace_id
    assert claims.workspace_role == WorkspaceRole.COLLABORATOR
    assert claims.shared_file_ids == file_ids
    assert claims.exp == exp


def test_jwt_claims_with_none_shared_file_ids() -> None:
    """Test JWTClaims creation with None shared_file_ids (owner scenario)."""
    user_id = uuid4()
    workspace_id = uuid4()
    exp = int(datetime.now(UTC).timestamp()) + 3600

    claims = JWTClaims(
        user_id=user_id,
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=exp,
    )

    assert claims.user_id == user_id
    assert claims.workspace_id == workspace_id
    assert claims.workspace_role == WorkspaceRole.OWNER
    assert claims.shared_file_ids is None
    assert claims.exp == exp


def test_jwt_claims_immutability() -> None:
    """Test that JWTClaims is immutable (frozen dataclass)."""
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=int(datetime.now(UTC).timestamp()) + 3600,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        claims.user_id = uuid4()  # Should fail - frozen

    with pytest.raises(dataclasses.FrozenInstanceError):
        claims.workspace_role = WorkspaceRole.COLLABORATOR  # Should fail - frozen


def test_is_expired_with_past_timestamp() -> None:
    """Test is_expired returns True for expired token."""
    # Create token that expired 1 hour ago
    past_time = datetime.now(UTC) - timedelta(hours=1)
    exp = int(past_time.timestamp())

    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=exp,
    )

    assert claims.is_expired() is True


def test_is_expired_with_future_timestamp() -> None:
    """Test is_expired returns False for valid token."""
    # Create token that expires 1 hour from now
    future_time = datetime.now(UTC) + timedelta(hours=1)
    exp = int(future_time.timestamp())

    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=exp,
    )

    assert claims.is_expired() is False


def test_is_expired_at_exact_expiration() -> None:
    """Test is_expired at exact expiration boundary."""
    # Create token that expires at a specific time
    exp = 1000000000

    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=exp,
    )

    # At exact expiration, token should still be valid (not yet expired)
    assert claims.is_expired(current_timestamp=exp) is False
    # One second past expiration, token should be expired
    assert claims.is_expired(current_timestamp=exp + 1) is True


def test_has_access_to_file_owner_has_access() -> None:
    """Test that workspace owner has access to all files."""
    file_id = uuid4()

    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=int(datetime.now(UTC).timestamp()) + 3600,
    )

    assert claims.has_access_to_file(file_id) is True


def test_has_access_to_file_collaborator_with_access() -> None:
    """Test that collaborator has access to files in shared_file_ids."""
    file_id = uuid4()
    shared_file_ids = (file_id, uuid4(), uuid4())

    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=shared_file_ids,
        exp=int(datetime.now(UTC).timestamp()) + 3600,
    )

    assert claims.has_access_to_file(file_id) is True


def test_has_access_to_file_collaborator_without_access() -> None:
    """Test that collaborator does not have access to files not in shared_file_ids."""
    file_id = uuid4()
    other_file_id = uuid4()
    shared_file_ids = (other_file_id, uuid4())

    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=shared_file_ids,
        exp=int(datetime.now(UTC).timestamp()) + 3600,
    )

    assert claims.has_access_to_file(file_id) is False


def test_has_access_to_file_collaborator_with_none_shared_files() -> None:
    """Test that collaborator with None shared_file_ids raises validation error."""

    # This should now fail validation in __post_init__
    with pytest.raises(ValueError, match="COLLABORATOR role must have shared_file_ids"):
        JWTClaims(
            user_id=uuid4(),
            workspace_id=uuid4(),
            workspace_role=WorkspaceRole.COLLABORATOR,
            shared_file_ids=None,
            exp=int(datetime.now(UTC).timestamp()) + 3600,
        )


def test_has_access_to_file_collaborator_with_empty_tuple() -> None:
    """Test that collaborator with empty shared_file_ids tuple has no file access."""
    file_id = uuid4()

    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(),
        exp=int(datetime.now(UTC).timestamp()) + 3600,
    )

    assert claims.has_access_to_file(file_id) is False


def test_jwt_claims_field_types() -> None:
    """Test that JWTClaims fields have correct types."""
    user_id = uuid4()
    workspace_id = uuid4()
    file_ids = (uuid4(), uuid4())
    exp = int(datetime.now(UTC).timestamp()) + 3600

    claims = JWTClaims(
        user_id=user_id,
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=file_ids,
        exp=exp,
    )

    assert isinstance(claims.user_id, UUID)
    assert isinstance(claims.workspace_id, UUID)
    assert isinstance(claims.workspace_role, WorkspaceRole)
    assert isinstance(claims.shared_file_ids, tuple)
    assert all(isinstance(fid, UUID) for fid in claims.shared_file_ids)
    assert isinstance(claims.exp, int)


def test_jwt_claims_equality() -> None:
    """Test JWTClaims equality based on field values."""
    user_id = uuid4()
    workspace_id = uuid4()
    file_ids = (uuid4(), uuid4())
    exp = int(datetime.now(UTC).timestamp()) + 3600

    claims1 = JWTClaims(
        user_id=user_id,
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=file_ids,
        exp=exp,
    )

    claims2 = JWTClaims(
        user_id=user_id,
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=file_ids,
        exp=exp,
    )

    assert claims1 == claims2


def test_jwt_claims_inequality() -> None:
    """Test JWTClaims inequality with different values."""
    exp = int(datetime.now(UTC).timestamp()) + 3600

    claims1 = JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=exp,
    )

    claims2 = JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(uuid4(),),
        exp=exp,
    )

    assert claims1 != claims2


def test_jwt_claims_owner_cannot_have_shared_files() -> None:
    """Test that OWNER role cannot have shared_file_ids."""
    with pytest.raises(ValueError, match="OWNER role cannot have shared_file_ids"):
        JWTClaims(
            user_id=uuid4(),
            workspace_id=uuid4(),
            workspace_role=WorkspaceRole.OWNER,
            shared_file_ids=(uuid4(),),
            exp=int(datetime.now(UTC).timestamp()) + 3600,
        )


def test_jwt_claims_validates_user_id_type() -> None:
    """Test that invalid user_id type raises TypeError."""
    with pytest.raises(TypeError, match="user_id must be a UUID"):
        JWTClaims(
            user_id="not-a-uuid",  # type: ignore
            workspace_id=uuid4(),
            workspace_role=WorkspaceRole.OWNER,
            shared_file_ids=None,
            exp=int(datetime.now(UTC).timestamp()) + 3600,
        )


def test_jwt_claims_validates_workspace_id_type() -> None:
    """Test that invalid workspace_id type raises TypeError."""
    with pytest.raises(TypeError, match="workspace_id must be a UUID"):
        JWTClaims(
            user_id=uuid4(),
            workspace_id="not-a-uuid",  # type: ignore
            workspace_role=WorkspaceRole.OWNER,
            shared_file_ids=None,
            exp=int(datetime.now(UTC).timestamp()) + 3600,
        )
