"""Domain value objects.

Contains immutable value objects such as SHA256Hash, WorkspaceId, ChunkIndex, etc.
Value objects are compared by their values, not identity.
"""

from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.workspace_role import WorkspaceRole


__all__ = ["JWTClaims", "WorkspaceRole"]
