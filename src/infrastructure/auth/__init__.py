"""Authentication infrastructure - JWT validation, RBAC, and access control.

Implements authentication and authorization with four security layers:

Layer 1: JWT Validation
    - RS256 signature verification (JWTValidator)
    - Workspace-scoped token claims (get_current_user)
    - Returns: JWTClaims or raises 401 Unauthorized

Layer 2: Role-Based Access Control (RBAC)
    - Workspace role enforcement (require_role, require_owner)
    - OWNER: Full CRUD access to workspace resources
    - COLLABORATOR: Read-only access to shared files
    - Returns: JWTClaims or raises 403 Forbidden (role)

Layer 3: Workspace Validation
    - Multi-tenant isolation (validate_workspace_access)
    - Ensures user's workspace_id matches resource's workspace_id
    - Prevents cross-tenant access attacks
    - Returns: None or raises 403 Forbidden (workspace)

Layer 4: File Access Validation
    - Granular file-level authorization (validate_file_access)
    - OWNER: Access to all files in workspace
    - COLLABORATOR: Access only to files in shared_file_ids
    - Returns: None or raises 403 Forbidden (file access)

Usage Example - Write Operation (Owner Only):
    from typing import Annotated
    from fastapi import Depends
    from src.infrastructure.auth import require_owner

    @router.post("/v1/uploads")
    async def create_upload(
        current_user: Annotated[JWTClaims, Depends(require_owner())],
    ):
        # Only workspace owners can create uploads
        workspace_id = current_user.workspace_id
        ...

Usage Example - Read Operation with File Access Control:
    from typing import Annotated
    from fastapi import Depends
    from src.infrastructure.auth import (
        get_current_user,
        validate_workspace_access,
        validate_file_access,
    )

    @router.get("/v1/uploads/{upload_id}")
    async def get_upload(
        upload_id: UUID,
        current_user: Annotated[JWTClaims, Depends(get_current_user)],
    ):
        # Any authenticated user can call this endpoint
        session = await session_store.get_session(upload_id)
        if not session:
            raise HTTPException(404, "Upload not found")

        # Layer 3: Validate workspace access
        validate_workspace_access(current_user, session.workspace_id)

        # Layer 4: Validate file access
        validate_file_access(current_user, session.file_id)

        return session

Security Architecture:
    - Defense in depth: Multiple validation layers
    - Fail closed: Validators raise exceptions (no bypass)
    - Zero-trust: Every request validated at every layer
    - Audit logging: All access violations logged

References:
    - FR22-FR26: Workspace isolation and access control requirements
    - Architecture: Four-layer security model
"""

from src.infrastructure.auth.file_access_validator import validate_file_access
from src.infrastructure.auth.jwt_validator import JWTValidator
from src.infrastructure.auth.rbac_middleware import require_owner, require_role
from src.infrastructure.auth.workspace_validator import validate_workspace_access


__all__ = [
    "JWTValidator",
    "require_role",
    "require_owner",
    "validate_workspace_access",
    "validate_file_access",
]
