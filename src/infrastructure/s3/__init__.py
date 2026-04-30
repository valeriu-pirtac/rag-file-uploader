"""S3/MinIO integration - Bronze-layer file storage.

Implements IStorageClient protocol using aioboto3 for:
- Multipart upload assembly
- Workspace-scoped path isolation
- Server-side encryption (AES-256)
"""
