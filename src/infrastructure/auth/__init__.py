"""Authentication infrastructure - JWT validation and RBAC.

Implements authentication and authorization middleware with:
- RS256 signature verification (JWTValidator)
- Workspace-scoped token claims (get_current_user)
- Role-based access control (require_role, require_owner)

Usage:
    from src.infrastructure.auth import JWTValidator, require_owner
    from src.presentation.api.middleware.auth import get_current_user

    @router.post("/v1/uploads")
    async def create_upload(
        current_user: Annotated[JWTClaims, Depends(require_owner())],
    ):
        # Only workspace owners can create uploads
        ...
"""

from src.infrastructure.auth.jwt_validator import JWTValidator
from src.infrastructure.auth.rbac_middleware import require_owner, require_role


__all__ = ["JWTValidator", "require_role", "require_owner"]
