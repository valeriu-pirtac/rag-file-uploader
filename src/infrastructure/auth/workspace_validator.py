"""Workspace validation infrastructure for access control.

This module provides workspace-level authorization by validating that the
authenticated user's workspace matches the resource's workspace. This enforces
multi-tenant isolation at the HTTP endpoint level.

Layer 3 of the four-layer security model:
    Layer 1: JWT Validation (get_current_user) → 401 Unauthorized
    Layer 2: RBAC (require_owner/require_role) → 403 Forbidden (role)
    Layer 3: Workspace Validation (this module) → 403 Forbidden (workspace)
    Layer 4: File Access Validation → 403 Forbidden (file access)

Usage Example:
    from typing import Annotated
    from fastapi import Depends, APIRouter
    from src.domain.value_objects.jwt_claims import JWTClaims
    from src.presentation.api.middleware.auth import get_current_user
    from src.infrastructure.auth.workspace_validator import validate_workspace_access

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

        # Validate user's workspace matches resource workspace
        validate_workspace_access(current_user, session.workspace_id)

        return {"upload_id": str(upload_id)}

Rationale - Why Helper Function, Not Dependency:
    1. Flexibility: Can be called inside handler after fetching resource
    2. Conditional: Can apply different logic based on resource properties
    3. Control flow: Works with if/else branches and error handling
    4. Resource-specific: Validates against fetched resource's workspace_id

References:
    - FR26: Complete workspace isolation requirement
    - Architecture: Multi-tenant isolation at all layers
    - Security: Zero-trust model - validate every request
"""

from uuid import UUID

import structlog
from fastapi import HTTPException

from src.domain.value_objects.jwt_claims import JWTClaims


log = structlog.get_logger(__name__)


def validate_workspace_access(
    current_user: JWTClaims,
    resource_workspace_id: UUID,
) -> None:
    """Validate user's workspace matches resource workspace.

    Enforces workspace isolation by ensuring the authenticated user can only
    access resources that belong to their active workspace. This prevents
    cross-tenant access attacks where users attempt to access resources by
    guessing or enumerating resource IDs.

    This validation applies to ALL roles (OWNER and COLLABORATOR). It's the
    first resource-level check after RBAC validation.

    Args:
        current_user: Authenticated user claims from JWT validation
        resource_workspace_id: Workspace ID of the resource being accessed

    Raises:
        HTTPException: 403 Forbidden if workspace IDs don't match

    Example:
        # Inside endpoint handler after fetching resource
        session = await session_store.get_session(upload_id)
        validate_workspace_access(current_user, session.workspace_id)

    Security Notes:
        - Fails closed: Raises exception on mismatch (no bypass possible)
        - Logs failures: All workspace access violations are logged at WARNING level
        - No information leak: Error message doesn't reveal specific workspace IDs
        - Applied uniformly: Same validation for all roles and operations
    """
    if resource_workspace_id is None:
        raise HTTPException(
            status_code=400,
            detail={
                "detail": "Invalid request - resource workspace ID is required",
                "error": "INVALID_RESOURCE",
            },
        )

    if current_user.workspace_id != resource_workspace_id:
        log.warning(
            "workspace_access_denied",
            user_id=str(current_user.user_id),
            user_workspace_id=str(current_user.workspace_id),
            resource_workspace_id=str(resource_workspace_id),
            role=current_user.workspace_role.value,
        )

        raise HTTPException(
            status_code=403,
            detail={
                "detail": "Access denied - resource belongs to different workspace",
                "error": "WORKSPACE_MISMATCH",
            },
        )
