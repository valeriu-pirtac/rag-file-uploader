"""S3 implementation of storage client protocol.

This module implements the IStorageClient protocol using aioboto3 for async
S3 operations. It provides file assembly via multipart upload with workspace
isolation, server-side encryption, and full-file SHA-256 validation.

Key Features:
    - Workspace-scoped S3 key pattern: workspace_{workspace_id}/{file_id}.pdf
    - S3 multipart upload with parallel part uploads for performance
    - Server-side AES-256 encryption on all uploads (configurable)
    - Full-file SHA-256 validation after assembly
    - Duplicate file detection before upload
    - Automatic cleanup of incomplete uploads on failure
    - S3-compatible API only (portable to AWS S3)
    - PDF files only (hardcoded .pdf extension)

Storage Format:
    - S3 Key Pattern: workspace_{workspace_id}/{file_id}.pdf
    - File Type: PDF only (not validated, caller's responsibility)
    - Encryption: ServerSideEncryption=AES256 (if enabled)
    - Object Metadata: None (metadata stored in session/database)

Integration Points:
    - Story 2.3: Follows workspace isolation patterns from Redis keys
    - Story 3.1: Uses SHA256Hash value object for validation
    - Story 5.8: Called by CompleteUploadUseCase to persist files
    - Story 5.3: Assembled files scanned by ClamAV before event publish

Examples:
    >>> from src.infrastructure.config.settings import get_settings
    >>> from uuid import uuid4
    >>> from src.domain.value_objects import SHA256Hash
    >>>
    >>> # Initialize storage client
    >>> settings = get_settings()
    >>> storage_client = S3StorageClient(settings)
    >>>
    >>> # Assemble file from chunks
    >>> workspace_id = uuid4()
    >>> file_id = uuid4()
    >>> chunks = [b"chunk1", b"chunk2", b"chunk3"]
    >>> expected_hash = SHA256Hash.from_bytes(b"".join(chunks))
    >>>
    >>> s3_path, file_size = await storage_client.assemble_file(
    ...     workspace_id=workspace_id,
    ...     file_id=file_id,
    ...     chunk_data=chunks,
    ...     expected_checksum=expected_hash
    ... )
    >>>
    >>> # Result
    >>> print(s3_path)  # s3://rag-uploads/workspace_{workspace_id}/{file_id}.pdf
    >>> print(file_size)  # 18 (len(b"chunk1chunk2chunk3"))
"""

import asyncio
import hashlib
import re
from typing import Any
from uuid import UUID

import aioboto3  # type: ignore[import-untyped]
import structlog
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from src.domain.exceptions import InfrastructureError, IntegrityError
from src.domain.value_objects import SHA256Hash
from src.infrastructure.config.settings import AppSettings


logger = structlog.get_logger()


class S3StorageClient:
    """S3 implementation of storage client protocol.

    Assembles verified chunks into complete files using S3 multipart upload
    with workspace isolation, server-side encryption, and checksum validation.

    S3 Key Pattern:
        workspace_{workspace_id}/{file_id}.pdf

        This pattern enforces workspace isolation at the S3 level, ensuring
        no workspace can access another workspace's files. Future MinIO bucket
        policies can enforce path-based access control.

    Multipart Upload Process:
        1. Create multipart upload with ServerSideEncryption=AES256
        2. Upload each chunk as a separate part (streaming, no buffering)
        3. Complete multipart upload (assembles parts into single object)
        4. Compute full-file SHA-256 from concatenated chunks
        5. Validate computed hash matches expected_checksum
        6. If mismatch: delete corrupt file and raise IntegrityError
        7. If match: return S3 path and final file size

    Error Recovery:
        - Any failure during upload: abort_multipart_upload (cleanup orphaned parts)
        - Checksum mismatch: delete_object (remove corrupt file)
        - All boto3 errors: convert to InfrastructureError

    Examples:
        >>> settings = get_settings()
        >>> client = S3StorageClient(settings)
        >>> s3_path, size = await client.assemble_file(...)
    """

    def __init__(self, settings: AppSettings) -> None:
        """Initialize S3 storage client.

        Args:
            settings: Application settings containing MinIO/S3 configuration:
                - minio_endpoint: S3 endpoint URL
                - s3_bucket_name: S3 bucket for file storage
                - minio_root_user: S3 access key
                - minio_root_password: S3 secret key (SecretStr)
                - s3_use_ssl: Use SSL for S3 connections
                - s3_region: S3 region name

        Raises:
            ValueError: If required settings are missing or invalid
        """
        # Validate required settings
        if not settings.minio_endpoint:
            raise ValueError("minio_endpoint is required")
        if not settings.s3_bucket_name:
            raise ValueError("s3_bucket_name is required")
        if not settings.minio_root_user:
            raise ValueError("minio_root_user is required")
        if not settings.minio_root_password:
            raise ValueError("minio_root_password is required")

        self._endpoint = settings.minio_endpoint
        self._bucket = settings.s3_bucket_name
        self._access_key = settings.minio_root_user
        self._secret_key = settings.minio_root_password.get_secret_value()
        self._use_ssl = settings.s3_use_ssl
        self._region = settings.s3_region
        self._server_side_encryption = settings.s3_server_side_encryption
        self._session = aioboto3.Session()

    async def assemble_file(
        self,
        workspace_id: UUID,
        file_id: UUID,
        chunk_data: list[bytes],
        expected_checksum: SHA256Hash,
    ) -> tuple[str, int]:
        """Assemble chunks into complete file and store on S3.

        Implements IStorageClient.assemble_file() using S3 multipart upload
        with parallel part uploads for performance. Validates full-file SHA-256
        checksum during assembly and returns S3 path and file size.

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
            ValueError: If chunk_data is invalid (empty, None elements, exceeds S3 limits)
            IntegrityError: If assembled file checksum doesn't match expected or file already exists
            InfrastructureError: If S3 operation fails (connection, timeout, etc.)

        Example:
            >>> s3_path, size = await storage_client.assemble_file(
            ...     workspace_id=uuid4(),
            ...     file_id=uuid4(),
            ...     chunk_data=[b"chunk1", b"chunk2"],
            ...     expected_checksum=SHA256Hash.from_bytes(b"chunk1chunk2")
            ... )
            >>> assert "workspace_" in s3_path
            >>> assert size == 12
        """
        # Validate input
        self._validate_chunk_data(chunk_data)
        self._validate_checksum_format(expected_checksum)

        # Construct workspace-scoped S3 key
        s3_key = f"workspace_{workspace_id}/{file_id}.pdf"

        # Compute checksum and size upfront (single pass)
        hasher = hashlib.sha256()
        total_size = 0
        for chunk in chunk_data:
            hasher.update(chunk)
            total_size += len(chunk)
        computed_checksum = hasher.hexdigest()
        expected_checksum_str = str(expected_checksum.value)

        logger.info(
            "file_assembly_started",
            workspace_id=str(workspace_id),
            file_id=str(file_id),
            s3_key=s3_key,
            total_chunks=len(chunk_data),
            total_size=total_size,
            expected_checksum=expected_checksum_str,
            computed_checksum=computed_checksum,
        )

        # Create async S3 client
        async with self._session.client(
            "s3",
            endpoint_url=self._endpoint,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
            use_ssl=self._use_ssl,
        ) as s3_client:
            upload_id: str | None = None

            try:
                # Check for duplicate file (prevent concurrent overwrites)
                await self._check_file_exists(s3_client, s3_key, workspace_id, file_id)

                # Initiate multipart upload with server-side encryption
                upload_params = {
                    "Bucket": self._bucket,
                    "Key": s3_key,
                }

                # Add server-side encryption if enabled (requires KMS for MinIO)
                if self._server_side_encryption:
                    upload_params["ServerSideEncryption"] = "AES256"

                multipart_response = await s3_client.create_multipart_upload(**upload_params)
                upload_id = self._get_upload_id(multipart_response, s3_key)

                logger.debug(
                    "multipart_upload_initiated",
                    workspace_id=str(workspace_id),
                    file_id=str(file_id),
                    upload_id=upload_id,
                )

                # Upload parts in parallel for better performance
                upload_tasks = [
                    self._upload_part(
                        s3_client=s3_client,
                        part_num=part_num,
                        chunk=chunk,
                        upload_id=upload_id,
                        s3_key=s3_key,
                        workspace_id=workspace_id,
                        file_id=file_id,
                    )
                    for part_num, chunk in enumerate(chunk_data, start=1)
                ]
                parts = await asyncio.gather(*upload_tasks)

                # Complete multipart upload (assembles parts into single object)
                await s3_client.complete_multipart_upload(
                    Bucket=self._bucket,
                    Key=s3_key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )

                logger.debug(
                    "multipart_upload_completed",
                    workspace_id=str(workspace_id),
                    file_id=str(file_id),
                    total_parts=len(parts),
                )

                # Validate full-file SHA-256 checksum (computed upfront)
                if computed_checksum != expected_checksum_str:
                    # Checksum mismatch — delete corrupt file
                    logger.warning(
                        "file_integrity_check_failed",
                        workspace_id=str(workspace_id),
                        file_id=str(file_id),
                        expected_checksum=expected_checksum_str,
                        computed_checksum=computed_checksum,
                    )

                    # Attempt to delete corrupt file (best effort)
                    try:
                        await s3_client.delete_object(
                            Bucket=self._bucket,
                            Key=s3_key,
                        )
                    except Exception as delete_error:
                        logger.error(
                            "corrupt_file_delete_failed",
                            workspace_id=str(workspace_id),
                            file_id=str(file_id),
                            s3_key=s3_key,
                            error=str(delete_error),
                        )

                    raise IntegrityError(
                        message=f"Assembled file checksum mismatch for {s3_key}",
                        expected_checksum=expected_checksum_str,
                        computed_checksum=computed_checksum,
                        file_id=file_id,
                    )

                # Use computed size instead of additional S3 API call
                final_size = total_size
                s3_path = f"s3://{self._bucket}/{s3_key}"

                logger.info(
                    "file_assembly_completed",
                    workspace_id=str(workspace_id),
                    file_id=str(file_id),
                    s3_path=s3_path,
                    final_size=final_size,
                    checksum_validated=True,
                )

                return (s3_path, final_size)

            except IntegrityError:
                # Re-raise domain errors as-is
                raise

            except (ClientError, BotoCoreError) as e:
                # Abort multipart upload on any S3 failure
                await self._abort_multipart_upload(
                    s3_client, upload_id, s3_key, workspace_id, file_id
                )

                # Convert boto3 errors to InfrastructureError
                error_message = self._format_boto_error(e)

                logger.error(
                    "file_assembly_failed",
                    workspace_id=str(workspace_id),
                    file_id=str(file_id),
                    s3_key=s3_key,
                    error=error_message,
                )

                raise InfrastructureError(
                    f"S3 file assembly failed for {s3_key}: {error_message}"
                ) from e

            except Exception as e:
                # Abort multipart upload on unexpected errors
                await self._abort_multipart_upload(
                    s3_client, upload_id, s3_key, workspace_id, file_id
                )

                logger.error(
                    "file_assembly_unexpected_error",
                    workspace_id=str(workspace_id),
                    file_id=str(file_id),
                    s3_key=s3_key,
                    error=str(e),
                )

                raise InfrastructureError(
                    f"Unexpected error during file assembly for {s3_key}: {e}"
                ) from e

    def _validate_chunk_data(self, chunk_data: list[bytes]) -> None:
        """Validate chunk_data input.

        Args:
            chunk_data: List of chunk bytes to validate

        Raises:
            ValueError: If chunk_data is invalid
        """
        if not chunk_data:
            raise ValueError("chunk_data cannot be empty")

        if any(chunk is None for chunk in chunk_data):
            raise ValueError("chunk_data contains None elements")

        if any(len(chunk) == 0 for chunk in chunk_data):
            raise ValueError("chunk_data contains zero-length chunks")

        if len(chunk_data) > 10000:
            raise ValueError(
                f"chunk_data has {len(chunk_data)} chunks, exceeds S3 multipart limit of 10,000 parts"
            )

    def _validate_checksum_format(self, checksum: SHA256Hash) -> None:
        """Validate checksum format.

        Args:
            checksum: SHA256Hash to validate

        Raises:
            ValueError: If checksum format is invalid
        """
        checksum_str = str(checksum.value)
        if not re.match(r"^[a-f0-9]{64}$", checksum_str):
            raise ValueError(
                f"Invalid checksum format: expected 64-character lowercase hex, got '{checksum_str}'"
            )

    async def _check_file_exists(
        self, s3_client: Any, s3_key: str, workspace_id: UUID, file_id: UUID
    ) -> None:
        """Check if file already exists on S3.

        Args:
            s3_client: Boto3 S3 client
            s3_key: S3 key to check
            workspace_id: Workspace ID for logging
            file_id: File ID for logging

        Raises:
            IntegrityError: If file already exists
        """
        try:
            await s3_client.head_object(Bucket=self._bucket, Key=s3_key)
            # File exists - this is a duplicate
            logger.warning(
                "duplicate_file_detected",
                workspace_id=str(workspace_id),
                file_id=str(file_id),
                s3_key=s3_key,
            )
            raise IntegrityError(
                message=f"File already exists at {s3_key}",
                expected_checksum=None,
                computed_checksum=None,
                file_id=file_id,
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code == "404" or error_code == "NoSuchKey":
                # File doesn't exist - this is good
                return
            # Other error - let it bubble up
            raise

    def _get_upload_id(self, response: dict[str, Any], s3_key: str) -> str:
        """Extract and validate UploadId from multipart response.

        Args:
            response: create_multipart_upload response
            s3_key: S3 key for error messages

        Returns:
            Upload ID string

        Raises:
            InfrastructureError: If UploadId is missing
        """
        upload_id: str | None = response.get("UploadId")
        if not upload_id:
            raise InfrastructureError(
                f"S3 create_multipart_upload response missing UploadId for {s3_key}"
            )
        return upload_id

    async def _upload_part(
        self,
        s3_client: Any,
        part_num: int,
        chunk: bytes,
        upload_id: str,
        s3_key: str,
        workspace_id: UUID,
        file_id: UUID,
    ) -> dict[str, Any]:
        """Upload a single part to S3.

        Args:
            s3_client: Boto3 S3 client
            part_num: Part number (1-indexed)
            chunk: Chunk data to upload
            upload_id: Multipart upload ID
            s3_key: S3 key
            workspace_id: Workspace ID for logging
            file_id: File ID for logging

        Returns:
            Part dict with PartNumber and ETag

        Raises:
            InfrastructureError: If ETag is missing from response
        """
        part_response = await s3_client.upload_part(
            Bucket=self._bucket,
            Key=s3_key,
            PartNumber=part_num,
            UploadId=upload_id,
            Body=chunk,
        )

        etag = part_response.get("ETag")
        if not etag:
            raise InfrastructureError(
                f"S3 upload_part response missing ETag for {s3_key} part {part_num}"
            )

        logger.debug(
            "multipart_part_uploaded",
            workspace_id=str(workspace_id),
            file_id=str(file_id),
            part_number=part_num,
            part_size=len(chunk),
        )

        return {"PartNumber": part_num, "ETag": etag}

    async def _abort_multipart_upload(
        self,
        s3_client: Any,
        upload_id: str | None,
        s3_key: str,
        workspace_id: UUID,
        file_id: UUID,
    ) -> None:
        """Abort multipart upload if one was started.

        Args:
            s3_client: Boto3 S3 client
            upload_id: Upload ID (None if upload not started)
            s3_key: S3 key
            workspace_id: Workspace ID for logging
            file_id: File ID for logging
        """
        if upload_id is None:
            return

        try:
            await s3_client.abort_multipart_upload(
                Bucket=self._bucket,
                Key=s3_key,
                UploadId=upload_id,
            )
            logger.debug(
                "multipart_upload_aborted",
                workspace_id=str(workspace_id),
                file_id=str(file_id),
                upload_id=upload_id,
            )
        except Exception as abort_error:
            logger.warning(
                "multipart_upload_abort_failed",
                workspace_id=str(workspace_id),
                file_id=str(file_id),
                upload_id=upload_id,
                error=str(abort_error),
            )

    def _format_boto_error(self, error: Exception) -> str:
        """Format boto3 error for logging and messages.

        Args:
            error: ClientError or BotoCoreError

        Returns:
            Formatted error message
        """
        if isinstance(error, ClientError):
            error_code = error.response.get("Error", {}).get("Code", "Unknown")
            error_msg = error.response.get("Error", {}).get("Message", str(error))

            # Special handling for common errors
            if error_code == "NoSuchBucket":
                return f"S3 bucket '{self._bucket}' does not exist. Please create it first."
            if error_code == "InvalidAccessKeyId" or error_code == "SignatureDoesNotMatch":
                return f"Invalid S3 credentials: {error_code}"

            return f"{error_code}: {error_msg}"
        return str(error)
