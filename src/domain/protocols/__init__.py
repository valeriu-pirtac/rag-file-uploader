"""Domain protocols (interfaces).

Defines interfaces for infrastructure implementations such as:
- ISessionStore: Upload session persistence
- IRateLimiter: Per-workspace rate limiting
- IDeduplicationStore: File deduplication storage
- IStorageClient: S3/MinIO file storage
- IEventPublisher: NATS event publishing
- IVirusScanner: ClamAV integration
"""

from src.domain.protocols.deduplication_store import (
    FileMetadata,
    IDeduplicationStore,
)
from src.domain.protocols.event_publisher import IEventPublisher
from src.domain.protocols.rate_limiter import IRateLimiter
from src.domain.protocols.session_store import ISessionStore
from src.domain.protocols.storage_client import IStorageClient


__all__ = [
    "ISessionStore",
    "IRateLimiter",
    "IDeduplicationStore",
    "FileMetadata",
    "IStorageClient",
    "IEventPublisher",
]
