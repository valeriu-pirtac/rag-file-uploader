"""Unit tests for SHA256Hash value object."""

import hashlib

import pytest

from src.domain.value_objects.sha256_hash import SHA256Hash


class TestSHA256Hash:
    """Test suite for SHA256Hash value object."""

    def test_creation_with_valid_hash(self) -> None:
        """Test that a valid 64-character hex string is accepted."""
        valid_hash = "a" * 64
        sha_hash = SHA256Hash(valid_hash)
        assert sha_hash.value == valid_hash

    def test_validation_rejects_wrong_length(self) -> None:
        """Test that hashes with incorrect length are rejected."""
        # Too short
        with pytest.raises(ValueError, match="SHA-256 hash must be 64 chars"):
            SHA256Hash("abc123")

        # Too long
        with pytest.raises(ValueError, match="SHA-256 hash must be 64 chars"):
            SHA256Hash("a" * 65)

        # Empty string
        with pytest.raises(ValueError, match="SHA-256 hash must be 64 chars"):
            SHA256Hash("")

    def test_validation_rejects_non_hex_characters(self) -> None:
        """Test that non-hexadecimal characters are rejected."""
        invalid_hash = "g" * 64  # 'g' is not a hex character
        with pytest.raises(ValueError, match="SHA-256 hash must be lowercase hex"):
            SHA256Hash(invalid_hash)

        invalid_hash = "z" * 64
        with pytest.raises(ValueError, match="SHA-256 hash must be lowercase hex"):
            SHA256Hash(invalid_hash)

        invalid_hash = "!" * 64
        with pytest.raises(ValueError, match="SHA-256 hash must be lowercase hex"):
            SHA256Hash(invalid_hash)

    def test_validation_rejects_uppercase_hex(self) -> None:
        """Test that uppercase hex characters are rejected (must be lowercase)."""
        uppercase_hash = "A" * 64
        with pytest.raises(ValueError, match="SHA-256 hash must be lowercase hex"):
            SHA256Hash(uppercase_hash)

        mixed_case_hash = "Aa" * 32
        with pytest.raises(ValueError, match="SHA-256 hash must be lowercase hex"):
            SHA256Hash(mixed_case_hash)

    def test_from_bytes_computes_correct_hash(self) -> None:
        """Test that from_bytes() computes the correct hash for known test data."""
        test_data = b"hello world"
        expected_hash = hashlib.sha256(test_data).hexdigest()

        sha_hash = SHA256Hash.from_bytes(test_data)

        assert sha_hash.value == expected_hash
        assert len(sha_hash.value) == 64
        assert sha_hash.value.islower()

    def test_from_bytes_matches_expected_value(self) -> None:
        """Test that from_bytes() produces the expected hash for a known input."""
        test_data = b"hello world"
        # Expected SHA-256 hash of "hello world"
        expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

        sha_hash = SHA256Hash.from_bytes(test_data)

        assert sha_hash.value == expected

    def test_immutability(self) -> None:
        """Test that SHA256Hash is immutable (frozen dataclass)."""
        sha_hash = SHA256Hash("a" * 64)

        with pytest.raises(AttributeError):
            sha_hash.value = "b" * 64  # type: ignore[misc]

    def test_equality_comparison(self) -> None:
        """Test that equality comparison works correctly."""
        hash1 = SHA256Hash("a" * 64)
        hash2 = SHA256Hash("a" * 64)
        hash3 = SHA256Hash("b" * 64)

        assert hash1 == hash2
        assert hash1 != hash3
        assert hash2 != hash3

    def test_hashable_for_dict_keys(self) -> None:
        """Test that SHA256Hash can be used as dictionary keys."""
        hash1 = SHA256Hash("a" * 64)
        hash2 = SHA256Hash("b" * 64)

        hash_dict = {
            hash1: "file1",
            hash2: "file2",
        }

        assert hash_dict[hash1] == "file1"
        assert hash_dict[hash2] == "file2"
        assert len(hash_dict) == 2

    def test_str_representation(self) -> None:
        """Test that __str__ returns the hash value."""
        hash_value = "a" * 64
        sha_hash = SHA256Hash(hash_value)

        assert str(sha_hash) == hash_value

    def test_repr_representation(self) -> None:
        """Test that __repr__ provides useful debugging information."""
        hash_value = "a" * 64
        sha_hash = SHA256Hash(hash_value)

        repr_str = repr(sha_hash)
        assert "SHA256Hash" in repr_str
        assert hash_value in repr_str

    def test_accepts_all_valid_hex_characters(self) -> None:
        """Test that all valid lowercase hex characters (0-9, a-f) are accepted."""
        valid_chars = "0123456789abcdef"
        # Create a 64-char hash using all valid chars (repeated to reach 64)
        valid_hash = (valid_chars * 4)[:64]

        sha_hash = SHA256Hash(valid_hash)

        assert sha_hash.value == valid_hash
        assert len(sha_hash.value) == 64
