"""Unit tests for S3StorageClient - S3-backed file storage.

Tests multipart upload, checksum validation, error handling, and workspace
isolation. Uses mocked aioboto3 client to test logic without external
dependencies.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.domain.exceptions import InfrastructureError, IntegrityError
from src.domain.value_objects import SHA256Hash
from src.infrastructure.config.settings import AppSettings
from src.infrastructure.s3.storage_client import S3StorageClient


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
def mock_settings(test_jwt_public_key: str) -> AppSettings:
    """Create AppSettings with test configuration."""
    return AppSettings(
        minio_endpoint="http://localhost:9000",
        s3_bucket_name="test-bucket",
        minio_root_user="testuser",
        minio_root_password="testpassword",
        s3_use_ssl=False,
        s3_region="us-east-1",
        # Required fields
        jwt_public_key=test_jwt_public_key,
        clamav_host="localhost",
        # Set event_publish_mode to webhook to avoid nats_url requirement
        event_publish_mode="webhook",
        webhook_url="http://localhost:8080/webhook",
        webhook_secret="test-secret",
    )


@pytest.fixture
def storage_client(mock_settings: AppSettings) -> S3StorageClient:
    """Create S3StorageClient with mocked settings."""
    return S3StorageClient(mock_settings)


class TestS3StorageClientInitialization:
    """Tests for S3StorageClient initialization."""

    def test_initialization(self, mock_settings: AppSettings) -> None:
        """Test S3StorageClient can be initialized with settings."""
        client = S3StorageClient(mock_settings)

        assert client is not None
        assert client._endpoint == "http://localhost:9000"
        assert client._bucket == "test-bucket"
        assert client._access_key == "testuser"
        assert client._secret_key == "testpassword"
        assert client._use_ssl is False
        assert client._region == "us-east-1"

    def test_secret_key_extracted_from_secretstr(self, mock_settings: AppSettings) -> None:
        """Test that SecretStr password is properly extracted."""
        client = S3StorageClient(mock_settings)

        # SecretStr.get_secret_value() should be called
        assert isinstance(client._secret_key, str)
        assert client._secret_key == "testpassword"


class TestWorkspaceScopedKeyConstruction:
    """Tests for workspace-scoped S3 key pattern."""

    @pytest.mark.asyncio
    async def test_constructs_workspace_scoped_key(
        self,
        storage_client: S3StorageClient,
    ) -> None:
        """Test S3 key follows workspace_{workspace_id}/{file_id}.pdf pattern."""
        workspace_id = uuid4()
        file_id = uuid4()
        chunks = [b"test"]
        expected_hash = SHA256Hash.from_bytes(b"test")

        # Mock aioboto3 session and client
        with patch.object(storage_client._session, "client") as mock_client_ctx:
            mock_s3 = AsyncMock()
            mock_client_ctx.return_value.__aenter__.return_value = mock_s3

            # Mock head_object to raise 404 (file doesn't exist - pass duplicate check)
            mock_s3.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

            # Mock multipart upload responses
            mock_s3.create_multipart_upload.return_value = {"UploadId": "test-upload-id"}
            mock_s3.upload_part.return_value = {"ETag": "test-etag"}
            mock_s3.complete_multipart_upload.return_value = {}

            await storage_client.assemble_file(
                workspace_id=workspace_id,
                file_id=file_id,
                chunk_data=chunks,
                expected_checksum=expected_hash,
            )

            # Verify S3 key pattern
            expected_key = f"workspace_{workspace_id}/{file_id}.pdf"
            mock_s3.create_multipart_upload.assert_called_once()
            call_kwargs = mock_s3.create_multipart_upload.call_args[1]
            assert call_kwargs["Key"] == expected_key


class TestMultipartUploadSequence:
    """Tests for S3 multipart upload process."""

    @pytest.mark.asyncio
    async def test_initiates_multipart_upload_with_encryption(
        self,
        storage_client: S3StorageClient,
    ) -> None:
        """Test multipart upload is initiated with ServerSideEncryption."""
        workspace_id = uuid4()
        file_id = uuid4()
        chunks = [b"chunk"]
        expected_hash = SHA256Hash.from_bytes(b"chunk")

        with patch.object(storage_client._session, "client") as mock_client_ctx:
            mock_s3 = AsyncMock()
            mock_client_ctx.return_value.__aenter__.return_value = mock_s3

            # Mock duplicate check to pass
            mock_s3.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

            mock_s3.create_multipart_upload.return_value = {"UploadId": "upload-123"}
            mock_s3.upload_part.return_value = {"ETag": "etag-1"}
            mock_s3.complete_multipart_upload.return_value = {}

            await storage_client.assemble_file(
                workspace_id=workspace_id,
                file_id=file_id,
                chunk_data=chunks,
                expected_checksum=expected_hash,
            )

            # Verify ServerSideEncryption is enabled
            mock_s3.create_multipart_upload.assert_called_once()
            call_kwargs = mock_s3.create_multipart_upload.call_args[1]
            assert call_kwargs["ServerSideEncryption"] == "AES256"

    @pytest.mark.asyncio
    async def test_uploads_each_chunk_as_separate_part(
        self,
        storage_client: S3StorageClient,
    ) -> None:
        """Test each chunk is uploaded as a separate part with correct part number."""
        workspace_id = uuid4()
        file_id = uuid4()
        chunks = [b"chunk1", b"chunk2", b"chunk3"]
        expected_hash = SHA256Hash.from_bytes(b"chunk1chunk2chunk3")

        with patch.object(storage_client._session, "client") as mock_client_ctx:
            mock_s3 = AsyncMock()
            mock_client_ctx.return_value.__aenter__.return_value = mock_s3

            # Mock duplicate check to pass
            mock_s3.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

            mock_s3.create_multipart_upload.return_value = {"UploadId": "upload-123"}
            mock_s3.upload_part.return_value = {"ETag": "etag"}
            mock_s3.complete_multipart_upload.return_value = {}

            await storage_client.assemble_file(
                workspace_id=workspace_id,
                file_id=file_id,
                chunk_data=chunks,
                expected_checksum=expected_hash,
            )

            # Verify upload_part called 3 times with correct part numbers
            assert mock_s3.upload_part.call_count == 3

            # Check part numbers are 1, 2, 3 (not 0-indexed)
            call_args_list = mock_s3.upload_part.call_args_list
            for i, call_args in enumerate(call_args_list, start=1):
                kwargs = call_args[1]
                assert kwargs["PartNumber"] == i
                assert kwargs["Body"] == chunks[i - 1]

    @pytest.mark.asyncio
    async def test_completes_multipart_upload_with_parts_list(
        self,
        storage_client: S3StorageClient,
    ) -> None:
        """Test multipart upload is completed with correct parts list."""
        workspace_id = uuid4()
        file_id = uuid4()
        chunks = [b"chunk1", b"chunk2"]
        expected_hash = SHA256Hash.from_bytes(b"chunk1chunk2")

        with patch.object(storage_client._session, "client") as mock_client_ctx:
            mock_s3 = AsyncMock()
            mock_client_ctx.return_value.__aenter__.return_value = mock_s3

            # Mock duplicate check to pass
            mock_s3.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

            mock_s3.create_multipart_upload.return_value = {"UploadId": "upload-123"}
            mock_s3.upload_part.side_effect = [
                {"ETag": "etag-1"},
                {"ETag": "etag-2"},
            ]
            mock_s3.complete_multipart_upload.return_value = {}

            await storage_client.assemble_file(
                workspace_id=workspace_id,
                file_id=file_id,
                chunk_data=chunks,
                expected_checksum=expected_hash,
            )

            # Verify complete_multipart_upload called with correct parts
            mock_s3.complete_multipart_upload.assert_called_once()
            call_kwargs = mock_s3.complete_multipart_upload.call_args[1]

            assert call_kwargs["UploadId"] == "upload-123"
            parts = call_kwargs["MultipartUpload"]["Parts"]
            assert len(parts) == 2
            assert parts[0] == {"PartNumber": 1, "ETag": "etag-1"}
            assert parts[1] == {"PartNumber": 2, "ETag": "etag-2"}


class TestChecksumValidation:
    """Tests for full-file SHA-256 checksum validation."""

    @pytest.mark.asyncio
    async def test_validates_checksum_matches(
        self,
        storage_client: S3StorageClient,
    ) -> None:
        """Test successful validation when checksum matches."""
        workspace_id = uuid4()
        file_id = uuid4()
        chunks = [b"hello", b"world"]
        expected_hash = SHA256Hash.from_bytes(b"helloworld")

        with patch.object(storage_client._session, "client") as mock_client_ctx:
            mock_s3 = AsyncMock()
            mock_client_ctx.return_value.__aenter__.return_value = mock_s3

            # Mock duplicate check to pass
            mock_s3.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

            mock_s3.create_multipart_upload.return_value = {"UploadId": "upload-123"}
            mock_s3.upload_part.return_value = {"ETag": "etag"}
            mock_s3.complete_multipart_upload.return_value = {}

            s3_path, size = await storage_client.assemble_file(
                workspace_id=workspace_id,
                file_id=file_id,
                chunk_data=chunks,
                expected_checksum=expected_hash,
            )

            # Should succeed without raising IntegrityError
            assert s3_path.startswith("s3://test-bucket/workspace_")
            assert size == 10

    @pytest.mark.asyncio
    async def test_raises_integrity_error_on_checksum_mismatch(
        self,
        storage_client: S3StorageClient,
    ) -> None:
        """Test IntegrityError raised when checksum doesn't match."""
        workspace_id = uuid4()
        file_id = uuid4()
        chunks = [b"hello", b"world"]
        # Wrong checksum - expecting "hello" but got "helloworld"
        wrong_hash = SHA256Hash.from_bytes(b"hello")

        with patch.object(storage_client._session, "client") as mock_client_ctx:
            mock_s3 = AsyncMock()
            mock_client_ctx.return_value.__aenter__.return_value = mock_s3

            # Mock duplicate check to pass
            mock_s3.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

            mock_s3.create_multipart_upload.return_value = {"UploadId": "upload-123"}
            mock_s3.upload_part.return_value = {"ETag": "etag"}
            mock_s3.complete_multipart_upload.return_value = {}

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

    @pytest.mark.asyncio
    async def test_deletes_corrupt_file_on_checksum_mismatch(
        self,
        storage_client: S3StorageClient,
    ) -> None:
        """Test corrupt file is deleted when checksum validation fails."""
        workspace_id = uuid4()
        file_id = uuid4()
        chunks = [b"data"]
        wrong_hash = SHA256Hash.from_bytes(b"wrong")

        with patch.object(storage_client._session, "client") as mock_client_ctx:
            mock_s3 = AsyncMock()
            mock_client_ctx.return_value.__aenter__.return_value = mock_s3

            # Mock duplicate check to pass
            mock_s3.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

            mock_s3.create_multipart_upload.return_value = {"UploadId": "upload-123"}
            mock_s3.upload_part.return_value = {"ETag": "etag"}
            mock_s3.complete_multipart_upload.return_value = {}

            with pytest.raises(IntegrityError):
                await storage_client.assemble_file(
                    workspace_id=workspace_id,
                    file_id=file_id,
                    chunk_data=chunks,
                    expected_checksum=wrong_hash,
                )

            # Verify delete_object was called to remove corrupt file
            mock_s3.delete_object.assert_called_once()
            call_kwargs = mock_s3.delete_object.call_args[1]
            expected_key = f"workspace_{workspace_id}/{file_id}.pdf"
            assert call_kwargs["Key"] == expected_key


class TestErrorHandling:
    """Tests for error handling and recovery."""

    @pytest.mark.asyncio
    async def test_aborts_multipart_upload_on_client_error(
        self,
        storage_client: S3StorageClient,
    ) -> None:
        """Test multipart upload is aborted when S3 error occurs."""
        workspace_id = uuid4()
        file_id = uuid4()
        chunks = [b"data"]
        expected_hash = SHA256Hash.from_bytes(b"data")

        with patch.object(storage_client._session, "client") as mock_client_ctx:
            mock_s3 = AsyncMock()
            mock_client_ctx.return_value.__aenter__.return_value = mock_s3

            # Mock duplicate check to pass
            mock_s3.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

            mock_s3.create_multipart_upload.return_value = {"UploadId": "upload-123"}
            # Simulate upload_part failure
            mock_s3.upload_part.side_effect = ClientError(
                {"Error": {"Code": "NoSuchBucket", "Message": "Bucket not found"}},
                "UploadPart",
            )

            with pytest.raises(InfrastructureError):
                await storage_client.assemble_file(
                    workspace_id=workspace_id,
                    file_id=file_id,
                    chunk_data=chunks,
                    expected_checksum=expected_hash,
                )

            # Verify abort_multipart_upload was called
            mock_s3.abort_multipart_upload.assert_called_once()
            call_kwargs = mock_s3.abort_multipart_upload.call_args[1]
            assert call_kwargs["UploadId"] == "upload-123"

    @pytest.mark.asyncio
    async def test_converts_client_error_to_infrastructure_error(
        self,
        storage_client: S3StorageClient,
    ) -> None:
        """Test boto3 ClientError is converted to InfrastructureError."""
        workspace_id = uuid4()
        file_id = uuid4()
        chunks = [b"data"]
        expected_hash = SHA256Hash.from_bytes(b"data")

        with patch.object(storage_client._session, "client") as mock_client_ctx:
            mock_s3 = AsyncMock()
            mock_client_ctx.return_value.__aenter__.return_value = mock_s3

            # Mock duplicate check to pass
            mock_s3.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

            # Simulate error during initiate
            mock_s3.create_multipart_upload.side_effect = ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
                "CreateMultipartUpload",
            )

            with pytest.raises(InfrastructureError) as exc_info:
                await storage_client.assemble_file(
                    workspace_id=workspace_id,
                    file_id=file_id,
                    chunk_data=chunks,
                    expected_checksum=expected_hash,
                )

            # Verify error message contains S3 error details
            error_message = str(exc_info.value)
            assert "S3 file assembly failed" in error_message
            assert "AccessDenied" in error_message


class TestReturnValues:
    """Tests for assemble_file return values."""

    @pytest.mark.asyncio
    async def test_returns_s3_path_and_size(
        self,
        storage_client: S3StorageClient,
    ) -> None:
        """Test assemble_file returns correct S3 path and file size."""
        workspace_id = uuid4()
        file_id = uuid4()
        chunks = [b"chunk1", b"chunk2"]
        expected_hash = SHA256Hash.from_bytes(b"chunk1chunk2")

        with patch.object(storage_client._session, "client") as mock_client_ctx:
            mock_s3 = AsyncMock()
            mock_client_ctx.return_value.__aenter__.return_value = mock_s3

            # Mock duplicate check to pass
            mock_s3.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

            mock_s3.create_multipart_upload.return_value = {"UploadId": "upload-123"}
            mock_s3.upload_part.return_value = {"ETag": "etag"}
            mock_s3.complete_multipart_upload.return_value = {}

            s3_path, file_size = await storage_client.assemble_file(
                workspace_id=workspace_id,
                file_id=file_id,
                chunk_data=chunks,
                expected_checksum=expected_hash,
            )

            # Verify S3 path format
            assert s3_path == f"s3://test-bucket/workspace_{workspace_id}/{file_id}.pdf"
            assert file_size == 12
