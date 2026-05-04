"""File access validation infrastructure for granular file-level authorization.

This module provides file-level authorization by validating that users have
explicit access to specific files. This enforces the principle of least privilege
for collaborators who should only access files explicitly shared with them.

Layer 4 of the four-layer security model:
    Layer 1: JWT Validation (get_current_user) → 401 Unauthorized
    Layer 2: RBAC (require_owner/require_role) → 403 Forbidden (role)
    Layer 3: Workspace Validation → 403 Forbidden (workspace)
    Layer 4: File Access Validation (this module) → 403 Forbidden (file access)

Usage Example:
    from typing import Annotated
    from fastapi import Depends, APIRouter
    from src.domain.value_objects.jwt_claims import JWTClaims
    from src.presentation.api.middleware.auth import get_current_user
    from src.infrastructure.auth.workspace_validator import validate_workspace_access
    from src.infrastructure.auth.file_access_validator import validate_file_access

    router = APIRouter()

    @router.get("/v1/uploads/{upload_id}")
    async def get_upload(
        upload_id: UUID,
        current_user: Annotated[JWTClaims, Depends(get_current_user)],
    ) -> dict:
        # Fetch upload session from Redis
        session = await session_store.get_session(upload_id)
        if not session:
            raise HTTPException(404, "Upload session not found")

        # Layer 3: Validate workspace access
        validate_workspace_access(current_user, session.workspace_id)

        # Layer 4: Validate file access (only needed for collaborators)
        # Owners automatically have access to all files in their workspace
        validate_file_access(current_user, session.file_id)

        return {"upload_id": str(upload_id)}

Role-Based Behavior:
    - OWNER: Always has access to all files in their workspace
    - COLLABORATOR: Only has access to files in JWT's shared_file_ids claim

Rationale - Why Helper Function, Not Dependency:
    1. Resource-specific: Validation requires file_id from fetched resource
    2. Conditional application: Only COLLABORATOR role needs strict checking
    3. Domain method reuse: Leverages JWTClaims.has_access_to_file()
    4. Flexible placement: Can be called after resource fetch and validation

References:
    - FR23: Owners grant read-only access to specific files
    - FR25: Collaborators cannot modify files (enforced by RBAC)
    - Architecture: File-level access control for collaborators
    - Security: Principle of least privilege
"""

from uuid import UUID

import structlog
from fastapi import HTTPException

from src.domain.value_objects.jwt_claims import JWTClaims


log = structlog.get_logger(__name__)


def validate_file_access(
    current_user: JWTClaims,
    file_id: UUID,
) -> None:
    """Validate user has access to specific file.

    Enforces file-level authorization by checking if the user has explicit access
    to the requested file. Uses the domain method JWTClaims.has_access_to_file()
    which implements role-specific logic:

    - OWNER role: Always returns True (full workspace access)
    - COLLABORATOR role: Returns True only if file_id in shared_file_ids

    This validation applies after workspace validation to provide defense in depth.

    Args:
        current_user: Authenticated user claims from JWT validation
        file_id: UUID of the file being accessed

    Raises:
        HTTPException: 403 Forbidden if user doesn't have access to the file

    Example:
        # Inside endpoint handler after workspace validation
        validate_workspace_access(current_user, session.workspace_id)
        validate_file_access(current_user, session.file_id)

    Security Notes:
        - Leverages domain logic: Delegates to JWTClaims.has_access_to_file()
        - Fails closed: Raises exception on access denial (no bypass possible)
        - Logs failures: All file access denials logged at WARNING level
        - No information leak: Error message doesn't reveal file_id or existence
        - Consistent behavior: OWNER always passes, COLLABORATOR validated
    """
    if file_id is None:
        raise HTTPException(
            status_code=400,
            detail={
                "detail": "Invalid request - file ID is required",
                "error": "INVALID_RESOURCE",
            },
        )

    if not current_user.has_access_to_file(file_id):
        log.warning(
            "file_access_denied",
            user_id=str(current_user.user_id),
            workspace_id=str(current_user.workspace_id),
            file_id=str(file_id),
            role=current_user.workspace_role.value,
        )

        raise HTTPException(
            status_code=403,
            detail={
                "detail": "Access denied - file not accessible to user",
                "error": "FILE_ACCESS_DENIED",
            },
        )
