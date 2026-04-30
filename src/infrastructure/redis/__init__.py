"""Redis integration - Session state persistence.

Implements ISessionStore protocol using Redis for:
- Upload session storage with 24-hour TTL
- Workspace-scoped key prefixing for isolation
- Atomic operations for concurrent safety
"""
