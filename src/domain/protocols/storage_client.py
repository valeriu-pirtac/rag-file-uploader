"""Storage client protocol for file assembly and S3 operations.

This module defines the IStorageClient protocol, which specifies the contract
for assembling verified chunks into complete files and storing them on S3 with
workspace isolation. Implementations must provide multipart upload, checksum
validation, and workspace-scoped key patterns.

Protocol Contract:
    - All methods are async (storage operations are I/O bound)
    - Files MUST be isolated by workspace_id (security requirement)
    - S3 key pattern: workspace_{workspace_id}/{file_id}.pdf
    - **PDF files only**: System currently only supports PDF file uploads
    - Server-side encryption (AES-256) SHOULD be enabled when supported
    - Full-file SHA-256 validation MUST be performed during assembly
    - Duplicate files MUST be detected before upload
    - Corrupt files MUST be deleted if checksum mismatch detected
    - Only S3-compatible APIs allowed (no vendor-specific calls)

Error Handling:
    - IntegrityError: Raised when checksum mismatch or duplicate file detected
    - InfrastructureError: Raised for S3 operation failures (connection, timeout)
    - ValueError: Raised for invalid input (empty chunks, None elements, exceeds limits)
    - All incomplete multipart uploads MUST be aborted on failure

Workspace Isolation:
    - S3 key prefix enforces isolation: workspace_{workspace_id}/
    - Application layer validates workspace ownership before calling storage
    - S3 bucket policies can provide additional defense-in-depth
    - Cross-workspace access prevented by application-layer authorization

Implementation Notes:
    - Implementations are typically in src/infrastructure/s3/
    - Use aioboto3 for async S3 operations
    - Use S3 multipart upload for streaming assembly (no in-memory buffering)
    - Lifecycle policy should clean up incomplete uploads after 7 days

Examples:
    >>> from uuid import uuid4
    >>> from src.domain.value_objects import SHA256Hash
    >>>
    >>> # Assemble file from verified chunks
    >>> workspace_id = uuid4()
    >>> file_id = uuid4()
    >>> chunks = [b"chunk1", b"chunk2", b"chunk3"]
    >>> expected_hash = SHA256Hash.from_bytes(b"".join(chunks))
    >>>
    >>> # Assemble and store on S3
    >>> s3_path, file_size = await storage_client.assemble_file(
    ...     workspace_id=workspace_id,
    ...     file_id=file_id,
    ...     chunk_data=chunks,
    ...     expected_checksum=expected_hash
    ... )
    >>>
    >>> # S3 path follows workspace-isolated pattern
    >>> assert s3_path == f"s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf"
    >>> assert file_size == sum(len(c) for c in chunks)
"""

from typing import Protocol
from uuid import UUID

from src.domain.value_objects import SHA256Hash


class IStorageClient(Protocol):
    """Protocol for file assembly and S3 storage operations.

    Defines the contract for assembling verified chunks into complete files
    and storing them on S3 with workspace isolation. Implementations must
    provide multipart upload, checksum validation, and workspace-scoped keys.

    All methods are async to support non-blocking I/O operations with
    external storage systems (MinIO, AWS S3).

    Workspace Isolation:
        Every file is scoped to a workspace_id. Implementations MUST enforce
        S3 key pattern: workspace_{workspace_id}/{file_id}.pdf

        This ensures:
        - No workspace can access another workspace's files
        - S3 bucket policies can enforce path-based access control
        - Consistent isolation with Redis key patterns (Story 2.3)

    Integrity Validation:
        After assembling all chunks, implementations MUST:
        1. Compute SHA-256 hash of complete file
        2. Compare with expected_checksum from session
        3. If mismatch: delete corrupt file and raise IntegrityError
        4. If match: return s3_path and final_size

    Server-Side Encryption:
        All S3 uploads MUST enable ServerSideEncryption="AES256" (NFR-S2)
        for data-at-rest encryption compliance.

    Error Recovery:
        On any failure during multipart upload, implementations MUST:
        - Call abort_multipart_upload to clean up incomplete parts
        - Convert S3 ClientError to InfrastructureError
        - Delete corrupt file if checksum validation fails
    """

    async def assemble_file(
        self,
        workspace_id: UUID,
        file_id: UUID,
        chunk_data: list[bytes],
        expected_checksum: SHA256Hash,
    ) -> tuple[str, int]:
        """Assemble chunks into complete file and store on S3.

        This method assembles verified chunks into a complete file using S3
        multipart upload, validates the full-file SHA-256 checksum, and
        returns the S3 path and file size.

        The S3 key follows workspace-isolated pattern:
            workspace_{workspace_id}/{file_id}.pdf

        Assembly Process:
            1. Construct workspace-scoped S3 key
            2. Initiate S3 multipart upload with AES-256 encryption
            3. Upload each chunk as a separate part (streaming, no buffering)
            4. Complete multipart upload (assembles parts into single object)
            5. Compute SHA-256 hash of concatenated chunks
            6. Validate computed hash matches expected_checksum
            7. If mismatch: delete corrupt file and raise IntegrityError
            8. If match: return S3 path and final file size

        Args:
            workspace_id: Workspace owning this file (for path isolation)
            file_id: Unique file identifier (becomes S3 key suffix)
            chunk_data: List of chunk bytes in upload order (index 0, 1, 2, ...)
            expected_checksum: Expected full-file SHA-256 from session

        Returns:
            Tuple of (s3_path, final_size_bytes):
                - s3_path: Full S3 URI (e.g., "s3://bucket/workspace_xxx/file_yyy.pdf")
                - final_size_bytes: Total file size in bytes

        Raises:
            IntegrityError: If assembled file checksum doesn't match expected
            InfrastructureError: If S3 operation fails (connection, timeout, etc.)

        Example:
            >>> from uuid import uuid4
            >>> from src.domain.value_objects import SHA256Hash
            >>>
            >>> workspace_id = uuid4()
            >>> file_id = uuid4()
            >>> chunks = [b"chunk1", b"chunk2", b"chunk3"]
            >>> expected_hash = SHA256Hash.from_bytes(b"".join(chunks))
            >>>
            >>> # Assemble file
            >>> s3_path, size = await storage_client.assemble_file(
            ...     workspace_id=workspace_id,
            ...     file_id=file_id,
            ...     chunk_data=chunks,
            ...     expected_checksum=expected_hash
            ... )
            >>>
            >>> # Verify workspace-isolated path
            >>> assert s3_path.startswith(f"s3://rag-uploads/workspace_{workspace_id}")
            >>> assert size == len(b"chunk1chunk2chunk3")

        Implementation Requirements:
            - Use S3 multipart upload (create → upload parts → complete)
            - Enable ServerSideEncryption="AES256" on create_multipart_upload
            - Abort multipart upload on any failure (cleanup orphaned parts)
            - Delete file if checksum validation fails
            - Convert boto3 ClientError to InfrastructureError
            - Log assembly start, completion, and errors with structured context
        """
        ...
