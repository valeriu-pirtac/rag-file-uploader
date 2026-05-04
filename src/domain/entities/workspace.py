"""Workspace domain entity."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Workspace:
    """Domain entity representing a workspace with ownership.

    A workspace is the primary isolation boundary in the system. Each workspace
    has a single owner and can have multiple collaborators with controlled access.

    Attributes:
        workspace_id: Unique identifier for the workspace
        owner_user_id: Unique identifier of the workspace owner
        created_at: Timestamp when the workspace was created (timezone-aware UTC)
    """

    workspace_id: UUID
    owner_user_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, UUID):
            raise TypeError("workspace_id must be a UUID")
        if not isinstance(self.owner_user_id, UUID):
            raise TypeError("owner_user_id must be a UUID")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
