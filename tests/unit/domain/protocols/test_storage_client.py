"""Unit tests for IStorageClient protocol contract.

Tests verify that the IStorageClient protocol defines the correct interface
and can be implemented by mock/test implementations.
"""

from typing import Protocol
from uuid import uuid4

import pytest

from src.domain.protocols import IStorageClient
from src.domain.value_objects import SHA256Hash


class MockStorageClient:
    """Mock implementation of IStorageClient for testing."""

    async def assemble_file(
        self,
        workspace_id,
        file_id,
        chunk_data: list[bytes],
        expected_checksum: SHA256Hash,
    ) -> tuple[str, int]:
        """Mock implementation that returns test data."""
        total_size = sum(len(chunk) for chunk in chunk_data)
        s3_path = f"s3://test-bucket/workspace_{workspace_id}/{file_id}.pdf"
        return (s3_path, total_size)


def test_storage_client_is_protocol():
    """Verify IStorageClient is a Protocol."""
    assert issubclass(IStorageClient, Protocol)


def test_storage_client_has_assemble_file_method():
    """Verify IStorageClient protocol defines assemble_file method."""
    assert hasattr(IStorageClient, "assemble_file")


@pytest.mark.asyncio
async def test_mock_storage_client_implements_protocol():
    """Verify MockStorageClient can implement IStorageClient."""
    # Create mock client
    mock_client = MockStorageClient()

    # Verify it has the required method
    assert hasattr(mock_client, "assemble_file")
    assert callable(mock_client.assemble_file)

    # Test the mock implementation
    workspace_id = uuid4()
    file_id = uuid4()
    chunks = [b"chunk1", b"chunk2", b"chunk3"]
    expected_hash = SHA256Hash.from_bytes(b"chunk1chunk2chunk3")

    s3_path, file_size = await mock_client.assemble_file(
        workspace_id=workspace_id,
        file_id=file_id,
        chunk_data=chunks,
        expected_checksum=expected_hash,
    )

    # Verify mock returns expected data
    assert s3_path.startswith("s3://test-bucket/workspace_")
    assert str(workspace_id) in s3_path
    assert str(file_id) in s3_path
    assert file_size == 18  # len(b"chunk1chunk2chunk3")


@pytest.mark.asyncio
async def test_mock_storage_client_with_empty_chunks():
    """Test mock storage client with empty chunk list."""
    mock_client = MockStorageClient()

    workspace_id = uuid4()
    file_id = uuid4()
    chunks: list[bytes] = []
    expected_hash = SHA256Hash.from_bytes(b"")

    s3_path, file_size = await mock_client.assemble_file(
        workspace_id=workspace_id,
        file_id=file_id,
        chunk_data=chunks,
        expected_checksum=expected_hash,
    )

    assert s3_path.startswith("s3://test-bucket/")
    assert file_size == 0


@pytest.mark.asyncio
async def test_mock_storage_client_with_single_chunk():
    """Test mock storage client with single chunk."""
    mock_client = MockStorageClient()

    workspace_id = uuid4()
    file_id = uuid4()
    chunks = [b"single chunk data"]
    expected_hash = SHA256Hash.from_bytes(b"single chunk data")

    s3_path, file_size = await mock_client.assemble_file(
        workspace_id=workspace_id,
        file_id=file_id,
        chunk_data=chunks,
        expected_checksum=expected_hash,
    )

    assert s3_path.startswith("s3://test-bucket/")
    assert file_size == 17  # len(b"single chunk data")
