"""Unit tests for WorkspaceRole enum."""

import pytest

from src.domain.value_objects.workspace_role import WorkspaceRole


def test_workspace_role_owner_value() -> None:
    """Test that OWNER enum has correct string value."""
    assert WorkspaceRole.OWNER.value == "owner"


def test_workspace_role_collaborator_value() -> None:
    """Test that COLLABORATOR enum has correct string value."""
    assert WorkspaceRole.COLLABORATOR.value == "collaborator"


def test_workspace_role_enum_values() -> None:
    """Test that enum contains exactly the expected members."""
    expected_values = {"owner", "collaborator"}
    actual_values = {role.value for role in WorkspaceRole}
    assert actual_values == expected_values


def test_workspace_role_comparison() -> None:
    """Test enum equality comparison."""
    assert WorkspaceRole.OWNER == WorkspaceRole.OWNER
    assert WorkspaceRole.COLLABORATOR == WorkspaceRole.COLLABORATOR
    assert WorkspaceRole.OWNER != WorkspaceRole.COLLABORATOR


def test_workspace_role_from_string() -> None:
    """Test creating enum from string value."""
    assert WorkspaceRole("owner") == WorkspaceRole.OWNER
    assert WorkspaceRole("collaborator") == WorkspaceRole.COLLABORATOR


def test_workspace_role_invalid_value() -> None:
    """Test that invalid string raises ValueError."""
    with pytest.raises(ValueError, match="'invalid_role' is not a valid WorkspaceRole"):
        WorkspaceRole("invalid_role")


def test_workspace_role_is_string_enum() -> None:
    """Test that WorkspaceRole inherits from str."""
    assert isinstance(WorkspaceRole.OWNER, str)
    assert isinstance(WorkspaceRole.COLLABORATOR, str)
