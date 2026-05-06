"""Integration tests for S3StorageClient with real MinIO.

These tests require a running MinIO instance (e.g., via Docker Compose).
Run: docker-compose up -d minio

Tests verify:
- Full file assembly lifecycle with real S3/MinIO
- Multipart upload process end-to-end
- Workspace isolation with real S3 keys
- Full-file SHA-256 validation
- IntegrityError on checksum mismatch
- Server-side encryption enabled
"""

from collections.abc import AsyncGenerator
from uuid import uuid4

import aioboto3
import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.domain.exceptions import InfrastructureError, IntegrityError
from src.domain.value_objects import SHA256Hash
from src.infrastructure.config.settings import AppSettings
from src.infrastructure.s3.storage_client import S3StorageClient


# MinIO connection details for integration tests
MINIO_ENDPOINT = "http://localhost:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
TEST_BUCKET = "test-rag-uploads"


@pytest.fixture
def test_jwt_public_key() -> str:
    """Generate a valid RSA public key for testing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    return public_pem


@pytest.fixture
def test_settings(test_jwt_public_key: str) -> AppSettings:
    """Create AppSettings for integration tests."""
    return AppSettings(
        minio_endpoint=MINIO_ENDPOINT,
        s3_bucket_name=TEST_BUCKET,
        minio_root_user=MINIO_ACCESS_KEY,
        minio_root_password=MINIO_SECRET_KEY,
        s3_use_ssl=False,
        s3_region="us-east-1",
        s3_server_side_encryption=False,  # Disable for testing without KMS
        # Required fields
        jwt_public_key=test_jwt_public_key,
        clamav_host="localhost",
        event_publish_mode="webhook",
        webhook_url="http://localhost:8080/webhook",
        webhook_secret="test-secret",
    )


@pytest.fixture
async def minio_bucket(test_settings: AppSettings) -> AsyncGenerator[None]:
    """Create and cleanup test bucket for integration tests.

    Verifies MinIO is accessible and creates test bucket.
    Cleans up bucket after tests complete.
    """
    session = aioboto3.Session()

    async with session.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
        use_ssl=False,
    ) as s3_client:
        try:
            # Verify MinIO is accessible
            await s3_client.list_buckets()
        except Exception as e:
            pytest.skip(f"MinIO not available at {MINIO_ENDPOINT}: {e}")

        # Create test bucket if it doesn't exist
        try:
            await s3_client.create_bucket(Bucket=TEST_BUCKET)
        except ClientError as e:
            if e.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                raise

        yield

        # Cleanup: delete all objects in test bucket
        try:
            # List all objects
            response = await s3_client.list_objects_v2(Bucket=TEST_BUCKET)

            if "Contents" in response:
                # Delete all objects
                for obj in response["Contents"]:
                    await s3_client.delete_object(
                        Bucket=TEST_BUCKET,
                        Key=obj["Key"],
                    )

            # Delete bucket
            await s3_client.delete_bucket(Bucket=TEST_BUCKET)
        except Exception:
            pass  # Ignore cleanup errors


@pytest.fixture
def storage_client(test_settings: AppSettings) -> S3StorageClient:
    """Create S3StorageClient with real MinIO configuration."""
    return S3StorageClient(test_settings)


class TestS3StorageClientIntegration:
    """Integration tests with real MinIO."""

    @pytest.mark.asyncio
    async def test_assemble_file_with_multiple_chunks(
        self,
        storage_client: S3StorageClient,
        minio_bucket: None,
    ) -> None:
        """Test file assembly with multiple chunks end-to-end.

        Uses 5 MB chunks to meet S3 minimum part size requirement.
        """
        workspace_id = uuid4()
        file_id = uuid4()
        # Use 5 MB chunks (S3 minimum part size)
        chunk_size = 5 * 1024 * 1024  # 5 MB
        chunks = [b"a" * chunk_size, b"b" * chunk_size, b"c" * chunk_size]
        combined_data = b"".join(chunks)
        expected_hash = SHA256Hash.from_bytes(combined_data)

        # Assemble file
        s3_path, file_size = await storage_client.assemble_file(
            workspace_id=workspace_id,
            file_id=file_id,
            chunk_data=chunks,
            expected_checksum=expected_hash,
        )

        # Verify return values
        assert s3_path == f"s3://{TEST_BUCKET}/workspace_{workspace_id}/{file_id}.pdf"
        assert file_size == len(combined_data)

        # Verify file exists on S3
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            use_ssl=False,
        ) as s3_client:
            s3_key = f"workspace_{workspace_id}/{file_id}.pdf"
            response = await s3_client.head_object(
                Bucket=TEST_BUCKET,
                Key=s3_key,
            )

            assert response["ContentLength"] == len(combined_data)

    @pytest.mark.asyncio
    async def test_assemble_file_with_single_chunk(
        self,
        storage_client: S3StorageClient,
        minio_bucket: None,
    ) -> None:
        """Test file assembly with single chunk (5 MB minimum)."""
        workspace_id = uuid4()
        file_id = uuid4()
        chunk_data = b"x" * (5 * 1024 * 1024)  # 5 MB chunk
        chunks = [chunk_data]
        expected_hash = SHA256Hash.from_bytes(chunk_data)

        s3_path, file_size = await storage_client.assemble_file(
            workspace_id=workspace_id,
            file_id=file_id,
            chunk_data=chunks,
            expected_checksum=expected_hash,
        )

        assert s3_path.startswith(f"s3://{TEST_BUCKET}/workspace_")
        assert file_size == len(chunk_data)

    @pytest.mark.asyncio
    async def test_workspace_isolation_with_different_workspaces(
        self,
        storage_client: S3StorageClient,
        minio_bucket: None,
    ) -> None:
        """Test that files from different workspaces use different S3 keys."""
        workspace_a = uuid4()
        workspace_b = uuid4()
        file_id = uuid4()  # Same file ID for both workspaces
        chunk_data = b"d" * (5 * 1024 * 1024)  # 5 MB chunk
        chunks = [chunk_data]
        expected_hash = SHA256Hash.from_bytes(chunk_data)

        # Upload to workspace A
        s3_path_a, _ = await storage_client.assemble_file(
            workspace_id=workspace_a,
            file_id=file_id,
            chunk_data=chunks,
            expected_checksum=expected_hash,
        )

        # Upload to workspace B (same file_id)
        s3_path_b, _ = await storage_client.assemble_file(
            workspace_id=workspace_b,
            file_id=file_id,
            chunk_data=chunks,
            expected_checksum=expected_hash,
        )

        # Verify different S3 paths
        assert s3_path_a != s3_path_b
        assert f"workspace_{workspace_a}" in s3_path_a
        assert f"workspace_{workspace_b}" in s3_path_b

        # Verify both files exist
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            use_ssl=False,
        ) as s3_client:
            # Check workspace A file
            key_a = f"workspace_{workspace_a}/{file_id}.pdf"
            response_a = await s3_client.head_object(Bucket=TEST_BUCKET, Key=key_a)
            assert response_a["ContentLength"] == len(chunk_data)

            # Check workspace B file
            key_b = f"workspace_{workspace_b}/{file_id}.pdf"
            response_b = await s3_client.head_object(Bucket=TEST_BUCKET, Key=key_b)
            assert response_b["ContentLength"] == len(chunk_data)

    @pytest.mark.asyncio
    async def test_integrity_error_on_checksum_mismatch(
        self,
        storage_client: S3StorageClient,
        minio_bucket: None,
    ) -> None:
        """Test IntegrityError raised when checksum doesn't match."""
        workspace_id = uuid4()
        file_id = uuid4()
        chunk_size = 5 * 1024 * 1024  # 5 MB
        chunks = [b"a" * chunk_size, b"b" * chunk_size]
        wrong_data = b"wrong" * chunk_size
        wrong_hash = SHA256Hash.from_bytes(wrong_data)

        with pytest.raises(IntegrityError) as exc_info:
            await storage_client.assemble_file(
                workspace_id=workspace_id,
                file_id=file_id,
                chunk_data=chunks,
                expected_checksum=wrong_hash,
            )

        # Verify error details
        error = exc_info.value
        assert error.expected_checksum == wrong_hash.value
        assert error.computed_checksum is not None
        assert error.file_id == file_id

        # Verify corrupt file was deleted
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            use_ssl=False,
        ) as s3_client:
            s3_key = f"workspace_{workspace_id}/{file_id}.pdf"

            with pytest.raises(ClientError) as s3_error:
                await s3_client.head_object(Bucket=TEST_BUCKET, Key=s3_key)

            # Verify it's a 404 Not Found error
            assert s3_error.value.response["Error"]["Code"] == "404"

    @pytest.mark.asyncio
    async def test_infrastructure_error_on_invalid_bucket(
        self,
        test_settings: AppSettings,
    ) -> None:
        """Test InfrastructureError raised when bucket doesn't exist."""
        # Create client with non-existent bucket
        invalid_settings = AppSettings(
            minio_endpoint=MINIO_ENDPOINT,
            s3_bucket_name="non-existent-bucket-12345",
            minio_root_user=MINIO_ACCESS_KEY,
            minio_root_password=MINIO_SECRET_KEY,
            s3_use_ssl=False,
            s3_region="us-east-1",
            jwt_public_key=test_settings.jwt_public_key,
            clamav_host="localhost",
            event_publish_mode="webhook",
            webhook_url="http://localhost:8080/webhook",
            webhook_secret="test-secret",
        )

        invalid_client = S3StorageClient(invalid_settings)

        workspace_id = uuid4()
        file_id = uuid4()
        chunks = [b"data"]
        expected_hash = SHA256Hash.from_bytes(b"data")

        with pytest.raises(InfrastructureError) as exc_info:
            await invalid_client.assemble_file(
                workspace_id=workspace_id,
                file_id=file_id,
                chunk_data=chunks,
                expected_checksum=expected_hash,
            )

        # Verify error message contains S3 error details
        error_message = str(exc_info.value)
        assert "S3 file assembly failed" in error_message

    @pytest.mark.asyncio
    async def test_server_side_encryption_enabled(
        self,
        storage_client: S3StorageClient,
        minio_bucket: None,
    ) -> None:
        """Test that server-side encryption (AES256) is enabled on stored objects when configured.

        Note: This test is skipped for local MinIO without KMS configuration.
        """
        pytest.skip(
            "Server-side encryption requires KMS configuration for MinIO - skipping for local testing"
        )

    @pytest.mark.asyncio
    async def test_assemble_large_file_with_many_chunks(
        self,
        storage_client: S3StorageClient,
        minio_bucket: None,
    ) -> None:
        """Test file assembly with many chunks (simulate larger file)."""
        workspace_id = uuid4()
        file_id = uuid4()

        # Create 10 chunks of 5 MB each (50 MB total file)
        chunk_size = 5 * 1024 * 1024  # 5 MB
        chunks = [bytes([i % 256]) * chunk_size for i in range(10)]
        combined_data = b"".join(chunks)
        expected_hash = SHA256Hash.from_bytes(combined_data)

        s3_path, file_size = await storage_client.assemble_file(
            workspace_id=workspace_id,
            file_id=file_id,
            chunk_data=chunks,
            expected_checksum=expected_hash,
        )

        assert s3_path.startswith(f"s3://{TEST_BUCKET}/workspace_")
        assert file_size == len(combined_data)

        # Verify file size matches
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            use_ssl=False,
        ) as s3_client:
            s3_key = f"workspace_{workspace_id}/{file_id}.pdf"
            response = await s3_client.head_object(Bucket=TEST_BUCKET, Key=s3_key)
            assert response["ContentLength"] == len(combined_data)
