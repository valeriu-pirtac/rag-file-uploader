"""Domain protocols (interfaces).

Defines interfaces for infrastructure implementations such as:
- ISessionStore: Upload session persistence
- IStorageClient: S3/MinIO file storage
- IEventPublisher: NATS event publishing
- IVirusScanner: ClamAV integration
"""
