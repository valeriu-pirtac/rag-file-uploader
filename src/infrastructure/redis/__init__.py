"""Redis integration - Session state persistence and workspace isolation.

Implements ISessionStore protocol using Redis for:
- Upload session storage with 24-hour TTL
- Workspace-scoped key prefixing for isolation (FR26, NFR-S5)
- Atomic operations for concurrent safety

Key Builder:
Provides workspace-scoped key generation functions ensuring multi-tenant isolation:
- session_key(): Upload session storage keys
- dedup_key(): File deduplication scope keys
- rate_limit_key(): Rate limit counter keys
"""

from src.infrastructure.redis.key_builder import (
    dedup_key,
    rate_limit_key,
    session_key,
)


__all__ = [
    "session_key",
    "dedup_key",
    "rate_limit_key",
]
