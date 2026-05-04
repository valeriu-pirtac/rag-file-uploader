"""Authentication infrastructure - JWT validation.

Implements JWT token validation middleware with:
- RS256 signature verification
- Workspace-scoped token claims
- Role-based access control (owner/collaborator)
"""

from src.infrastructure.auth.jwt_validator import JWTValidator


__all__ = ["JWTValidator"]
