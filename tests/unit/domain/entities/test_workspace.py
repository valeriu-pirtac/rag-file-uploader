"""Unit tests for Workspace entity."""

import dataclasses
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from src.domain.entities.workspace import Workspace


def test_workspace_creation_with_valid_data() -> None:
    """Test creating a workspace with all required fields."""
    workspace_id = uuid4()
    owner_id = uuid4()
    created_at = datetime.now(UTC)

    workspace = Workspace(workspace_id=workspace_id, owner_user_id=owner_id, created_at=created_at)

    assert workspace.workspace_id == workspace_id
    assert workspace.owner_user_id == owner_id
    assert workspace.created_at == created_at


def test_workspace_immutability() -> None:
    """Test that Workspace is immutable (frozen dataclass)."""
    workspace = Workspace(workspace_id=uuid4(), owner_user_id=uuid4(), created_at=datetime.now(UTC))

    with pytest.raises(dataclasses.FrozenInstanceError):
        workspace.workspace_id = uuid4()  # Should fail - frozen

    with pytest.raises(dataclasses.FrozenInstanceError):
        workspace.owner_user_id = uuid4()  # Should fail - frozen

    with pytest.raises(dataclasses.FrozenInstanceError):
        workspace.created_at = datetime.now(UTC)  # Should fail - frozen


def test_workspace_field_types() -> None:
    """Test that workspace fields have correct types."""
    workspace_id = uuid4()
    owner_id = uuid4()
    created_at = datetime.now(UTC)

    workspace = Workspace(workspace_id=workspace_id, owner_user_id=owner_id, created_at=created_at)

    assert isinstance(workspace.workspace_id, UUID)
    assert isinstance(workspace.owner_user_id, UUID)
    assert isinstance(workspace.created_at, datetime)


def test_workspace_equality() -> None:
    """Test workspace equality based on field values."""
    workspace_id = uuid4()
    owner_id = uuid4()
    created_at = datetime.now(UTC)

    workspace1 = Workspace(workspace_id=workspace_id, owner_user_id=owner_id, created_at=created_at)

    workspace2 = Workspace(workspace_id=workspace_id, owner_user_id=owner_id, created_at=created_at)

    assert workspace1 == workspace2


def test_workspace_inequality() -> None:
    """Test workspace inequality with different IDs."""
    created_at = datetime.now(UTC)

    workspace1 = Workspace(workspace_id=uuid4(), owner_user_id=uuid4(), created_at=created_at)

    workspace2 = Workspace(workspace_id=uuid4(), owner_user_id=uuid4(), created_at=created_at)

    assert workspace1 != workspace2


def test_workspace_with_timezone_aware_datetime() -> None:
    """Test workspace creation with timezone-aware datetime."""
    created_at = datetime.now(UTC)

    workspace = Workspace(workspace_id=uuid4(), owner_user_id=uuid4(), created_at=created_at)

    assert workspace.created_at.tzinfo is not None
    assert workspace.created_at.tzinfo == UTC


def test_workspace_validates_workspace_id_type() -> None:
    """Test that invalid workspace_id type raises TypeError."""
    with pytest.raises(TypeError, match="workspace_id must be a UUID"):
        Workspace(
            workspace_id="not-a-uuid",  # type: ignore
            owner_user_id=uuid4(),
            created_at=datetime.now(UTC),
        )


def test_workspace_validates_owner_id_type() -> None:
    """Test that invalid owner_user_id type raises TypeError."""
    with pytest.raises(TypeError, match="owner_user_id must be a UUID"):
        Workspace(
            workspace_id=uuid4(),
            owner_user_id="not-a-uuid",  # type: ignore
            created_at=datetime.now(UTC),
        )


def test_workspace_validates_timezone_aware_datetime() -> None:
    """Test that naive datetime raises ValueError."""
    with pytest.raises(ValueError, match="created_at must be timezone-aware"):
        Workspace(
            workspace_id=uuid4(),
            owner_user_id=uuid4(),
            created_at=datetime.now(),  # naive datetime
        )
