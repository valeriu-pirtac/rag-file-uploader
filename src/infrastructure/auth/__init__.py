"""Authentication infrastructure - JWT validation.

Implements JWT token validation middleware with:
- RS256 signature verification
- Workspace-scoped token claims
- Role-based access control (owner/collaborator)
"""
