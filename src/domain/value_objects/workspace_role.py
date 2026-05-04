"""Workspace role value object for authorization."""

from enum import StrEnum


class WorkspaceRole(StrEnum):
    """Workspace role determining user permissions.

    Attributes:
        OWNER: Full access to all workspace resources
        COLLABORATOR: Limited access based on shared_file_ids
    """

    OWNER = "owner"
    COLLABORATOR = "collaborator"
