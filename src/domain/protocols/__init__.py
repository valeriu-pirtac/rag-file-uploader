"""Domain protocols (interfaces).

Defines interfaces for infrastructure implementations such as:
- ISessionStore: Upload session persistence
- IRateLimiter: Per-workspace rate limiting
- IStorageClient: S3/MinIO file storage
- IEventPublisher: NATS event publishing
- IVirusScanner: ClamAV integration
"""

from src.domain.protocols.rate_limiter import IRateLimiter
from src.domain.protocols.session_store import ISessionStore


__all__ = ["ISessionStore", "IRateLimiter"]
