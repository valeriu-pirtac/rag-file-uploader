"""Unit tests for ChunkVerifier domain service."""

from __future__ import annotations

import time

import pytest

from src.domain.exceptions import ChecksumMismatchError
from src.domain.services.chunk_verifier import ChunkVerifier
from src.domain.value_objects.sha256_hash import SHA256Hash


@pytest.fixture
def verifier() -> ChunkVerifier:
    """Create ChunkVerifier instance.

    Returns:
        Fresh ChunkVerifier instance for each test
    """
    return ChunkVerifier()


@pytest.fixture
def valid_chunk_data() -> bytes:
    """Create valid test chunk data.

    Returns:
        Simple test bytes for verification testing
    """
    return b"hello world"


@pytest.fixture
def valid_checksum(valid_chunk_data: bytes) -> str:
    """Compute valid checksum for test data.

    Args:
        valid_chunk_data: Test data fixture

    Returns:
        SHA-256 hash of valid_chunk_data as hex string
    """
    return SHA256Hash.from_bytes(valid_chunk_data).value


class TestChunkVerifierSuccessfulVerification:
    """Tests for successful chunk verification (happy path)."""

    def test_successful_verification_passes_silently(
        self,
        verifier: ChunkVerifier,
        valid_chunk_data: bytes,
        valid_checksum: str,
    ) -> None:
        """Test that valid chunk passes verification silently.

        Given a chunk and its correct checksum
        When verify_chunk is called
        Then no exception is raised (success is silent)
        """
        # Act - should not raise exception
        verifier.verify_chunk(valid_chunk_data, valid_checksum)

        # Assert - if we got here, verification succeeded
        assert True  # Explicit pass for clarity

    def test_successful_verification_with_chunk_index(
        self,
        verifier: ChunkVerifier,
        valid_chunk_data: bytes,
        valid_checksum: str,
    ) -> None:
        """Test that chunk_index parameter doesn't affect successful verification.

        Given a chunk with its correct checksum and chunk_index
        When verify_chunk is called
        Then no exception is raised
        """
        # Act - should not raise exception even with chunk_index
        verifier.verify_chunk(valid_chunk_data, valid_checksum, chunk_index=42)

        # Assert
        assert True  # Verification succeeded


class TestChunkVerifierChecksumMismatch:
    """Tests for checksum mismatch detection."""

    def test_checksum_mismatch_raises_exception(self, verifier: ChunkVerifier) -> None:
        """Test that mismatched checksum raises ChecksumMismatchError.

        Given chunk data that doesn't match the expected checksum
        When verify_chunk is called
        Then ChecksumMismatchError is raised with correct details
        """
        # Arrange
        correct_data = b"hello world"
        wrong_data = b"goodbye world"
        expected_checksum = SHA256Hash.from_bytes(correct_data).value

        # Act & Assert
        with pytest.raises(ChecksumMismatchError) as exc_info:
            verifier.verify_chunk(wrong_data, expected_checksum)

        # Verify exception details
        error = exc_info.value
        assert error.expected_checksum == expected_checksum
        assert error.computed_checksum == SHA256Hash.from_bytes(wrong_data).value
        assert "expected" in str(error).lower()
        assert "got" in str(error).lower()

    def test_exception_includes_chunk_index(self, verifier: ChunkVerifier) -> None:
        """Test that ChecksumMismatchError includes chunk_index when provided.

        Given a checksum mismatch with chunk_index parameter
        When ChecksumMismatchError is raised
        Then exception includes chunk_index attribute and in message
        """
        # Arrange
        correct_data = b"hello world"
        wrong_data = b"goodbye world"
        expected_checksum = SHA256Hash.from_bytes(correct_data).value
        chunk_index = 42

        # Act & Assert
        with pytest.raises(ChecksumMismatchError) as exc_info:
            verifier.verify_chunk(wrong_data, expected_checksum, chunk_index=chunk_index)

        # Verify exception details
        error = exc_info.value
        assert error.chunk_index == chunk_index
        assert f"chunk {chunk_index}" in str(error)

    def test_exception_includes_chunk_size(self, verifier: ChunkVerifier) -> None:
        """Test that ChecksumMismatchError includes chunk_size.

        Given a checksum mismatch
        When ChecksumMismatchError is raised
        Then exception includes chunk_size attribute and in message
        """
        # Arrange
        correct_data = b"hello world"
        wrong_data = b"x" * 1024  # 1KB chunk
        expected_checksum = SHA256Hash.from_bytes(correct_data).value

        # Act & Assert
        with pytest.raises(ChecksumMismatchError) as exc_info:
            verifier.verify_chunk(wrong_data, expected_checksum)

        # Verify exception details
        error = exc_info.value
        assert error.chunk_size == 1024
        assert "1024 bytes" in str(error)

    def test_exception_with_both_chunk_index_and_size(self, verifier: ChunkVerifier) -> None:
        """Test that exception includes both chunk_index and chunk_size.

        Given a checksum mismatch with both chunk_index and non-zero size
        When ChecksumMismatchError is raised
        Then exception message includes both details
        """
        # Arrange
        correct_data = b"hello world"
        wrong_data = b"x" * 5242880  # 5MB chunk
        expected_checksum = SHA256Hash.from_bytes(correct_data).value

        # Act & Assert
        with pytest.raises(ChecksumMismatchError) as exc_info:
            verifier.verify_chunk(wrong_data, expected_checksum, chunk_index=7)

        # Verify exception details
        error = exc_info.value
        assert error.chunk_index == 7
        assert error.chunk_size == 5242880
        assert "chunk 7" in str(error)
        assert "5242880 bytes" in str(error)


class TestChunkVerifierInputValidation:
    """Tests for input type validation."""

    def test_data_must_be_bytes(self, verifier: ChunkVerifier) -> None:
        """Test that data parameter must be bytes.

        Given data parameter that is not bytes
        When verify_chunk is called
        Then TypeError is raised
        """
        # Arrange
        invalid_data = "not bytes"  # type: ignore[assignment]
        expected_checksum = "a" * 64

        # Act & Assert
        with pytest.raises(TypeError, match="data must be bytes"):
            verifier.verify_chunk(invalid_data, expected_checksum)  # type: ignore[arg-type]

    def test_expected_checksum_must_be_string(self, verifier: ChunkVerifier) -> None:
        """Test that expected_checksum parameter must be string.

        Given expected_checksum parameter that is not string
        When verify_chunk is called
        Then TypeError is raised
        """
        # Arrange
        valid_data = b"test"
        invalid_checksum = 12345  # type: ignore[assignment]

        # Act & Assert
        with pytest.raises(TypeError, match="expected_checksum must be str"):
            verifier.verify_chunk(valid_data, invalid_checksum)  # type: ignore[arg-type]

    def test_data_cannot_be_none(self, verifier: ChunkVerifier) -> None:
        """Test that data parameter cannot be None.

        Given data parameter is None
        When verify_chunk is called
        Then TypeError is raised
        """
        # Arrange
        expected_checksum = "a" * 64

        # Act & Assert
        with pytest.raises(TypeError):
            verifier.verify_chunk(None, expected_checksum)  # type: ignore[arg-type]


class TestChunkVerifierChecksumFormatValidation:
    """Tests for checksum format validation."""

    def test_invalid_checksum_format_raises_valueerror(self, verifier: ChunkVerifier) -> None:
        """Test that invalid checksum format raises ValueError.

        Given expected_checksum with invalid format
        When verify_chunk is called
        Then ValueError is raised (from SHA256Hash constructor)
        """
        # Arrange
        valid_data = b"test"
        invalid_checksum = "invalid"

        # Act & Assert
        with pytest.raises(ValueError, match="must be 64 chars|must be lowercase hex"):
            verifier.verify_chunk(valid_data, invalid_checksum)

    def test_checksum_wrong_length_raises_valueerror(self, verifier: ChunkVerifier) -> None:
        """Test that checksum with wrong length raises ValueError.

        Given expected_checksum with 63 characters (should be 64)
        When verify_chunk is called
        Then ValueError is raised
        """
        # Arrange
        valid_data = b"test"
        wrong_length_checksum = "a" * 63  # Should be 64

        # Act & Assert
        with pytest.raises(ValueError, match="must be 64 chars"):
            verifier.verify_chunk(valid_data, wrong_length_checksum)

    def test_uppercase_checksum_raises_valueerror(self, verifier: ChunkVerifier) -> None:
        """Test that uppercase checksum raises ValueError.

        Given expected_checksum in uppercase
        When verify_chunk is called
        Then ValueError is raised (checksums must be lowercase)
        """
        # Arrange
        valid_data = b"test"
        uppercase_checksum = "A" * 64

        # Act & Assert
        with pytest.raises(ValueError, match="must be lowercase hex"):
            verifier.verify_chunk(valid_data, uppercase_checksum)


class TestChunkVerifierParameterValidation:
    """Tests for enhanced parameter validation added during code review."""

    def test_negative_chunk_index_raises_valueerror(self, verifier: ChunkVerifier) -> None:
        """Test that negative chunk_index raises ValueError.

        Given chunk_index parameter with negative value
        When verify_chunk is called
        Then ValueError is raised
        """
        # Arrange
        valid_data = b"test"
        valid_checksum = SHA256Hash.from_bytes(valid_data).value

        # Act & Assert
        with pytest.raises(ValueError, match="chunk_index cannot be negative"):
            verifier.verify_chunk(valid_data, valid_checksum, chunk_index=-1)

    def test_chunk_index_wrong_type_raises_typeerror(self, verifier: ChunkVerifier) -> None:
        """Test that non-int chunk_index raises TypeError.

        Given chunk_index parameter that is not int
        When verify_chunk is called
        Then TypeError is raised
        """
        # Arrange
        valid_data = b"test"
        valid_checksum = SHA256Hash.from_bytes(valid_data).value

        # Act & Assert
        with pytest.raises(TypeError, match="chunk_index must be int"):
            verifier.verify_chunk(valid_data, valid_checksum, chunk_index="not an int")  # type: ignore[arg-type]


class TestChunkVerifierExceptionValidation:
    """Tests for ChecksumMismatchError validation added during code review."""

    def test_empty_expected_checksum_raises_valueerror(self) -> None:
        """Test that empty expected_checksum raises ValueError.

        Given empty string for expected_checksum
        When ChecksumMismatchError is instantiated
        Then ValueError is raised
        """
        # Act & Assert
        with pytest.raises(ValueError, match="expected_checksum cannot be empty"):
            ChecksumMismatchError(expected_checksum="", computed_checksum="a" * 64)

    def test_empty_computed_checksum_raises_valueerror(self) -> None:
        """Test that empty computed_checksum raises ValueError.

        Given empty string for computed_checksum
        When ChecksumMismatchError is instantiated
        Then ValueError is raised
        """
        # Act & Assert
        with pytest.raises(ValueError, match="computed_checksum cannot be empty"):
            ChecksumMismatchError(expected_checksum="a" * 64, computed_checksum="")

    def test_negative_chunk_index_in_exception_raises_valueerror(self) -> None:
        """Test that negative chunk_index in exception raises ValueError.

        Given chunk_index parameter with negative value
        When ChecksumMismatchError is instantiated
        Then ValueError is raised
        """
        # Act & Assert
        with pytest.raises(ValueError, match="chunk_index cannot be negative"):
            ChecksumMismatchError(
                expected_checksum="a" * 64, computed_checksum="b" * 64, chunk_index=-1
            )

    def test_negative_chunk_size_in_exception_raises_valueerror(self) -> None:
        """Test that negative chunk_size in exception raises ValueError.

        Given chunk_size parameter with negative value
        When ChecksumMismatchError is instantiated
        Then ValueError is raised
        """
        # Act & Assert
        with pytest.raises(ValueError, match="chunk_size cannot be negative"):
            ChecksumMismatchError(
                expected_checksum="a" * 64, computed_checksum="b" * 64, chunk_size=-100
            )


class TestChunkVerifierEdgeCases:
    """Tests for edge cases."""

    def test_empty_chunk_successful_verification(self, verifier: ChunkVerifier) -> None:
        """Test that empty chunk can be verified successfully.

        Given empty bytes and its correct SHA-256 checksum
        When verify_chunk is called
        Then no exception is raised
        """
        # Arrange
        empty_data = b""
        # SHA-256 of empty string
        expected_checksum = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

        # Act - should not raise exception
        verifier.verify_chunk(empty_data, expected_checksum)

        # Assert
        assert True  # Verification succeeded

    def test_empty_chunk_mismatch_detection(self, verifier: ChunkVerifier) -> None:
        """Test that mismatch detection works with empty chunk.

        Given empty bytes and wrong checksum
        When verify_chunk is called
        Then ChecksumMismatchError is raised
        """
        # Arrange
        empty_data = b""
        wrong_checksum = "a" * 64

        # Act & Assert
        with pytest.raises(ChecksumMismatchError) as exc_info:
            verifier.verify_chunk(empty_data, wrong_checksum)

        # Verify
        error = exc_info.value
        assert error.chunk_size == 0

    def test_large_chunk_successful_verification(self, verifier: ChunkVerifier) -> None:
        """Test that 5MB chunk can be verified successfully.

        Given 5MB chunk and its correct checksum
        When verify_chunk is called
        Then no exception is raised
        """
        # Arrange
        large_chunk = b"x" * (5 * 1024 * 1024)  # 5MB
        expected_checksum = SHA256Hash.from_bytes(large_chunk).value

        # Act - should not raise exception
        verifier.verify_chunk(large_chunk, expected_checksum)

        # Assert
        assert True  # Verification succeeded

    def test_large_chunk_mismatch_detection(self, verifier: ChunkVerifier) -> None:
        """Test that mismatch detection works with 5MB chunk.

        Given 5MB chunk and wrong checksum
        When verify_chunk is called
        Then ChecksumMismatchError is raised with correct size
        """
        # Arrange
        large_chunk = b"x" * (5 * 1024 * 1024)  # 5MB
        wrong_checksum = "a" * 64

        # Act & Assert
        with pytest.raises(ChecksumMismatchError) as exc_info:
            verifier.verify_chunk(large_chunk, wrong_checksum)

        # Verify
        error = exc_info.value
        assert error.chunk_size == 5 * 1024 * 1024


class TestChunkVerifierPerformance:
    """Tests for performance requirements."""

    def test_verification_performance_5mb_chunk(self, verifier: ChunkVerifier) -> None:
        """Test that verification completes in <50ms for 5MB chunks.

        Given a 5MB chunk
        When verify_chunk is called
        Then verification completes in less than 50ms

        This satisfies NFR-P3: per-chunk processing overhead ≤ 100ms
        (50ms for SHA-256 verification + 50ms for Redis state write)
        """
        # Arrange
        chunk_5mb = b"x" * (5 * 1024 * 1024)  # 5MB test data
        expected_checksum = SHA256Hash.from_bytes(chunk_5mb).value

        # Act - measure verification time
        start = time.perf_counter()
        verifier.verify_chunk(chunk_5mb, expected_checksum)
        duration_ms = (time.perf_counter() - start) * 1000

        # Assert - must complete in <50ms
        assert duration_ms < 50, f"Verification took {duration_ms:.2f}ms (limit: 50ms)"

    def test_performance_baseline_1mb_chunk(self, verifier: ChunkVerifier) -> None:
        """Baseline performance test for 1MB chunk.

        This provides a reference point for performance scaling.
        1MB chunk should verify significantly faster than 5MB.
        """
        # Arrange
        chunk_1mb = b"y" * (1 * 1024 * 1024)  # 1MB
        expected_checksum = SHA256Hash.from_bytes(chunk_1mb).value

        # Act - measure verification time
        start = time.perf_counter()
        verifier.verify_chunk(chunk_1mb, expected_checksum)
        duration_ms = (time.perf_counter() - start) * 1000

        # Assert - should be much faster than 5MB limit
        assert duration_ms < 20, f"1MB verification took {duration_ms:.2f}ms (expected <20ms)"


class TestChunkVerifierIdempotency:
    """Tests for idempotent behavior (same inputs always produce same result)."""

    def test_successful_verification_is_idempotent(
        self,
        verifier: ChunkVerifier,
        valid_chunk_data: bytes,
        valid_checksum: str,
    ) -> None:
        """Test that same chunk + checksum can be verified multiple times.

        Given same chunk and checksum
        When verify_chunk is called 3 times in a row
        Then all verifications pass (no state pollution)
        """
        # Act - verify same data 3 times
        verifier.verify_chunk(valid_chunk_data, valid_checksum)
        verifier.verify_chunk(valid_chunk_data, valid_checksum)
        verifier.verify_chunk(valid_chunk_data, valid_checksum)

        # Assert - if we got here, all verifications succeeded
        assert True  # All passes

    def test_mismatch_is_idempotent(self, verifier: ChunkVerifier) -> None:
        """Test that same mismatch raises identical exceptions.

        Given same mismatched chunk and checksum
        When verify_chunk is called multiple times
        Then identical ChecksumMismatchError is raised each time
        """
        # Arrange
        correct_data = b"hello world"
        wrong_data = b"goodbye world"
        expected_checksum = SHA256Hash.from_bytes(correct_data).value
        computed_checksum = SHA256Hash.from_bytes(wrong_data).value

        # Act & Assert - verify 3 times, expect same error each time
        for _ in range(3):
            with pytest.raises(ChecksumMismatchError) as exc_info:
                verifier.verify_chunk(wrong_data, expected_checksum)

            error = exc_info.value
            assert error.expected_checksum == expected_checksum
            assert error.computed_checksum == computed_checksum


class TestChunkVerifierMultipleInstances:
    """Tests for multiple ChunkVerifier instances (stateless verification)."""

    def test_multiple_instances_produce_same_results(self) -> None:
        """Test that different ChunkVerifier instances are stateless.

        Given multiple ChunkVerifier instances
        When they verify the same data
        Then all produce identical results
        """
        # Arrange
        verifier1 = ChunkVerifier()
        verifier2 = ChunkVerifier()
        chunk_data = b"test data"
        expected_checksum = SHA256Hash.from_bytes(chunk_data).value

        # Act - verify with both instances
        verifier1.verify_chunk(chunk_data, expected_checksum)
        verifier2.verify_chunk(chunk_data, expected_checksum)

        # Assert - both succeeded (no exception)
        assert True  # Both verifications passed
