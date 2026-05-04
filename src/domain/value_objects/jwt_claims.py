"""JWT claims value object for authentication and authorization."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from src.domain.value_objects.workspace_role import WorkspaceRole


@dataclass(frozen=True)
class JWTClaims:
    """Value object representing parsed and validated JWT token claims.

    Maps JWT token fields from the platform authentication service to domain types.
    This provides type-safe access to authentication and authorization data.

    JWT Token Structure:
        {
            "user_id": "uuid",
            "active_workspace_id": "uuid",
            "workspace_role": "owner | collaborator",
            "shared_file_ids": ["uuid"],
            "exp": 1234567890
        }

    Attributes:
        user_id: Unique identifier of the authenticated user
        workspace_id: Active workspace ID (maps from active_workspace_id in JWT)
        workspace_role: User's role in the active workspace
        shared_file_ids: List of file IDs accessible to collaborators (None for owners)
        exp: Token expiration time as Unix timestamp (seconds since epoch)
    """

    user_id: UUID
    workspace_id: UUID
    workspace_role: WorkspaceRole
    shared_file_ids: tuple[UUID, ...] | None
    exp: int

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, UUID):
            raise TypeError("user_id must be a UUID")
        if not isinstance(self.workspace_id, UUID):
            raise TypeError("workspace_id must be a UUID")
        if self.workspace_role == WorkspaceRole.OWNER and self.shared_file_ids is not None:
            raise ValueError("OWNER role cannot have shared_file_ids")
        if self.workspace_role == WorkspaceRole.COLLABORATOR and self.shared_file_ids is None:
            raise ValueError("COLLABORATOR role must have shared_file_ids")

    def is_expired(self, current_timestamp: int | None = None) -> bool:
        """Check if the JWT token has expired based on exp claim.

        Args:
            current_timestamp: Optional override for current timestamp for testing

        Returns:
            True if current time is past the expiration time, False otherwise
        """
        if current_timestamp is None:
            current_timestamp = int(datetime.now(UTC).timestamp())
        return current_timestamp > self.exp

    def has_access_to_file(self, file_id: UUID) -> bool:
        """Check if user has access to a specific file.

        Owners have access to all files in their workspace.
        Collaborators only have access to files in shared_file_ids list.

        Args:
            file_id: UUID of the file to check access for

        Returns:
            True if user has access to the file, False otherwise
        """
        if self.workspace_role == WorkspaceRole.OWNER:
            return True
        return self.shared_file_ids is not None and file_id in self.shared_file_ids
