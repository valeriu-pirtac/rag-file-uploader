"""SHA-256 hash value object for checksum validation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class SHA256Hash:
    """SHA-256 checksum value object with validation.

    This immutable value object represents a SHA-256 hash checksum. It enforces
    validation rules to ensure the hash is always in the correct format (64
    lowercase hexadecimal characters).

    SHA-256 hashes are used throughout the system for:
    - File content deduplication (identifying identical files)
    - Chunk integrity verification (ensuring chunks are not corrupted)
    - Data integrity validation (detecting tampering or corruption)

    Attributes:
        value: Lowercase hexadecimal string, exactly 64 characters
               (256 bits / 8 bits per hex char = 64 characters)

    Raises:
        ValueError: If hash is not exactly 64 characters or contains non-hex characters

    Examples:
        >>> # Create from existing hash string
        >>> hash1 = SHA256Hash("b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9")
        >>> print(hash1.value)
        b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9

        >>> # Compute hash from bytes
        >>> hash2 = SHA256Hash.from_bytes(b"hello world")
        >>> print(hash2.value)
        b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9

        >>> # Use as dict key (hashable)
        >>> file_map = {hash1: "file1.pdf", hash2: "file2.pdf"}
    """

    value: str

    def __post_init__(self) -> None:
        """Validate that the hash is exactly 64 lowercase hexadecimal characters.

        Raises:
            TypeError: If value is None or not a string
            ValueError: If hash length is not 64 or contains invalid characters
        """
        if self.value is None:
            raise TypeError("SHA-256 hash cannot be None")
        if not isinstance(self.value, str):
            raise TypeError("SHA-256 hash must be a string")
        if len(self.value) != 64:
            raise ValueError(f"SHA-256 hash must be 64 chars, got {len(self.value)}")

        if not all(c in "0123456789abcdef" for c in self.value):
            raise ValueError("SHA-256 hash must be lowercase hex")

    @classmethod
    def from_bytes(cls, data: bytes) -> SHA256Hash:
        """Compute SHA-256 hash from bytes.

        This factory method computes the SHA-256 hash of the provided bytes
        and returns a new SHA256Hash instance.

        Args:
            data: Raw bytes to hash

        Returns:
            SHA256Hash instance with computed hash value

        Raises:
            TypeError: If data is None or not bytes

        Examples:
            >>> hash_obj = SHA256Hash.from_bytes(b"hello world")
            >>> print(hash_obj.value)
            b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9
        """
        if data is None:
            raise TypeError("data cannot be None")
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        digest = hashlib.sha256(data).hexdigest()
        return cls(digest)

    def __str__(self) -> str:
        """Return the hash value as a string.

        Returns:
            64-character lowercase hex string
        """
        return self.value

    def __repr__(self) -> str:
        """Return detailed representation for debugging.

        Returns:
            String representation showing class and hash value
        """
        return f"SHA256Hash(value='{self.value}')"

    def __eq__(self, other: object) -> bool:
        """Compare two SHA256Hash instances for equality.

        Args:
            other: Another SHA256Hash instance to compare

        Returns:
            True if both hashes have the same value, False otherwise
        """
        if not isinstance(other, SHA256Hash):
            return NotImplemented
        return self.value == other.value

    def __hash__(self) -> int:
        """Return hash for use as dictionary key or in sets.

        Returns:
            Hash of the value string
        """
        return hash(self.value)
