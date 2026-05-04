"""Role-Based Access Control (RBAC) middleware for workspace authorization.

This module provides FastAPI dependencies that enforce workspace role requirements
on protected endpoints. It integrates with JWT validation to provide authorization
after authentication.

The RBAC middleware enables endpoint-level role enforcement:
- OWNER role: Full access to all operations (POST, PATCH, DELETE, GET, HEAD)
- COLLABORATOR role: Read-only access (GET, HEAD) limited by shared_file_ids

Architecture:
    JWT Validation (auth.py) → RBAC Check (this module) → Endpoint Handler

    The dependency chain ensures:
    1. JWT token is validated first (get_current_user)
    2. Role is checked against required role
    3. 401 for authentication failures, 403 for authorization failures

Usage Example:
    from typing import Annotated
    from fastapi import Depends, APIRouter
    from src.domain.value_objects.jwt_claims import JWTClaims
    from src.infrastructure.auth.rbac_middleware import require_owner

    router = APIRouter()

    @router.post("/v1/uploads")
    async def create_upload(
        current_user: Annotated[JWTClaims, Depends(require_owner())],
    ) -> dict:
        # Only workspace owners can create uploads
        workspace_id = current_user.workspace_id
        return {"workspace_id": str(workspace_id)}

    @router.get("/v1/uploads")
    async def list_uploads(
        current_user: Annotated[JWTClaims, Depends(get_current_user)],
    ) -> dict:
        # Any authenticated user can list (filtering by shared_file_ids in handler)
        workspace_id = current_user.workspace_id
        return {"uploads": []}

Rationale - Why Dependencies, Not Decorators:
    1. FastAPI-idiomatic: Dependencies are the standard pattern
    2. Type-safe: Full type inference for current_user parameter
    3. Composable: Can chain multiple dependencies
    4. Testable: Easy to override dependencies in tests
    5. OpenAPI docs: Auto-generated dependency graph

References:
    - FR28: Role-based access control requirement
    - Architecture: Write operations require owner role
    - Security: Defense in depth (authentication + authorization)
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

import structlog
from fastapi import Depends, HTTPException

from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.workspace_role import WorkspaceRole
from src.presentation.api.middleware.auth import get_current_user


log = structlog.get_logger(__name__)


def require_role(required_role: WorkspaceRole) -> Callable[..., Awaitable[JWTClaims]]:
    """Create FastAPI dependency that enforces workspace role requirement.

    This function returns a FastAPI dependency that validates the authenticated
    user has the required role. The dependency depends on get_current_user,
    ensuring RBAC checks execute after JWT validation.

    Args:
        required_role: Role required to access the endpoint (OWNER or COLLABORATOR)

    Returns:
        FastAPI dependency function that validates role and returns JWTClaims

    Raises:
        HTTPException: 403 Forbidden if user role doesn't match required role
        TypeError: If required_role is not a WorkspaceRole instance

    Example:
        # Require OWNER role for write operations
        @router.post("/v1/uploads")
        async def create_upload(
            current_user: Annotated[JWTClaims, Depends(require_role(WorkspaceRole.OWNER))],
        ) -> dict:
            workspace_id = current_user.workspace_id
            return {"workspace_id": str(workspace_id)}

        # Require COLLABORATOR role explicitly (rare - usually just use get_current_user)
        @router.get("/v1/shared-files")
        async def list_shared(
            current_user: Annotated[JWTClaims, Depends(require_role(WorkspaceRole.COLLABORATOR))],
        ) -> dict:
            return {"files": list(current_user.shared_file_ids or [])}
    """
    # Validate required_role parameter at function call time
    if not isinstance(required_role, WorkspaceRole):
        raise TypeError(
            f"required_role must be a WorkspaceRole instance, got {type(required_role).__name__}"
        )

    async def check_role(
        current_user: Annotated[JWTClaims, Depends(get_current_user)],
    ) -> JWTClaims:
        """Validate user has required role.

        Args:
            current_user: Authenticated user claims from JWT validation

        Returns:
            JWTClaims: Pass-through of current_user if authorized

        Raises:
            HTTPException: 401 if current_user is invalid, 403 if role doesn't match
        """
        # Defensive checks for None/invalid values
        if current_user is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication - no user claims",
            )

        if current_user.workspace_role is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication - missing role",
            )

        if current_user.workspace_role != required_role:
            log.warning(
                "authorization_failed",
                user_id=str(current_user.user_id),
                workspace_id=str(current_user.workspace_id),
                required_role=required_role.value,
                actual_role=current_user.workspace_role.value,
                reason="insufficient_role",
            )

            # Return structured error (no user_role for security)
            raise HTTPException(
                status_code=403,
                detail={
                    "detail": f"Insufficient permissions - {required_role.value} role required",
                    "required_role": required_role.value,
                },
            )

        log.debug(
            "authorization_success",
            user_id=str(current_user.user_id),
            workspace_id=str(current_user.workspace_id),
            role=current_user.workspace_role.value,
        )

        return current_user

    return check_role


def require_owner() -> Callable[..., Awaitable[JWTClaims]]:
    """Shorthand for requiring OWNER role.

    This is a convenience function for the common case of requiring owner role
    for write operations (POST, PATCH, DELETE).

    Returns:
        FastAPI dependency function that requires OWNER role

    Example:
        @router.post("/v1/uploads")
        async def create_upload(
            current_user: Annotated[JWTClaims, Depends(require_owner())],
        ) -> dict:
            # Only workspace owners can access
            return {"status": "created"}

        @router.patch("/v1/uploads/{upload_id}")
        async def upload_chunk(
            upload_id: str,
            current_user: Annotated[JWTClaims, Depends(require_owner())],
        ) -> dict:
            # Only workspace owners can upload chunks
            return {"status": "chunk_received"}

        @router.delete("/v1/uploads/{upload_id}")
        async def abort_upload(
            upload_id: str,
            current_user: Annotated[JWTClaims, Depends(require_owner())],
        ) -> dict:
            # Only workspace owners can abort uploads
            return {"status": "aborted"}
    """
    return require_role(WorkspaceRole.OWNER)
