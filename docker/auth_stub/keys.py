"""RSA key generation and management for JWT signing.

This module provides RSA key pair generation, persistence, and JWKS format
conversion for the stub authentication service.

DEVELOPMENT ONLY - DO NOT USE IN PRODUCTION
"""

import base64
from pathlib import Path
from typing import Any

import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey


log = structlog.get_logger(__name__)


class RSAKeyManager:
    """Manages RSA key pair for JWT signing.

    Keys are persisted to disk and reused across restarts. If keys don't exist,
    new ones are generated automatically.

    This implementation uses 2048-bit RSA keys with RS256 algorithm, matching
    the JWT validation requirements in the main upload service.

    Attributes:
        keys_dir: Directory path for storing key files
        private_key_path: Path to private key PEM file
        public_key_path: Path to public key PEM file
        _private_key: Cached RSA private key instance
        _public_key: Cached RSA public key instance
    """

    def __init__(self, keys_dir: Path = Path("/app/keys")) -> None:
        """Initialize key manager with storage directory.

        Args:
            keys_dir: Directory path for storing keys (default: /app/keys)
        """
        self.keys_dir = keys_dir
        self.private_key_path = self.keys_dir / "private.pem"
        self.public_key_path = self.keys_dir / "public.pem"

        self._private_key: RSAPrivateKey | None = None
        self._public_key: RSAPublicKey | None = None

    def initialize(self) -> None:
        """Load or generate RSA key pair.

        If both private.pem and public.pem exist, they are loaded. Otherwise,
        a new RSA key pair is generated and saved to disk.

        Creates the keys directory if it doesn't exist.
        """
        # Create keys directory if needed
        self.keys_dir.mkdir(parents=True, exist_ok=True)

        # Load existing keys or generate new ones
        if self.private_key_path.exists() and self.public_key_path.exists():
            log.info("rsa_keys_loading", path=str(self.keys_dir))
            try:
                self._load_keys()
                # Validate loaded keys are a matching pair
                self._validate_key_pair()
            except Exception as e:
                log.warning(
                    "rsa_keys_load_failed",
                    error=str(e),
                    action="regenerating",
                )
                # Clean up corrupted/mismatched keys and regenerate
                if self.private_key_path.exists():
                    self.private_key_path.unlink()
                if self.public_key_path.exists():
                    self.public_key_path.unlink()
                self._generate_keys()
        else:
            # Partial state - clean up and regenerate
            if self.private_key_path.exists():
                log.warning("partial_key_state", file="private.pem", action="cleanup")
                self.private_key_path.unlink()
            if self.public_key_path.exists():
                log.warning("partial_key_state", file="public.pem", action="cleanup")
                self.public_key_path.unlink()
            log.info("rsa_keys_generating", path=str(self.keys_dir))
            self._generate_keys()

    def _generate_keys(self) -> None:
        """Generate new RSA key pair and save to disk.

        Generates a 2048-bit RSA key pair using public_exponent=65537 (standard).
        Keys are saved in PEM format without encryption (development only).
        """
        # Generate 2048-bit RSA key (standard security for development)
        self._private_key = rsa.generate_private_key(
            public_exponent=65537,  # Standard RSA exponent
            key_size=2048,  # 2048-bit key for good security/performance balance
        )
        self._public_key = self._private_key.public_key()

        # Save private key to disk (PEM format, no encryption)
        private_pem = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),  # No password for dev
        )
        self.private_key_path.write_bytes(private_pem)
        # Set restrictive permissions on private key (read/write owner only)
        import os

        os.chmod(self.private_key_path, 0o600)

        # Save public key to disk (PEM format)
        public_pem = self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.public_key_path.write_bytes(public_pem)

        log.info("rsa_keys_generated", private_key=str(self.private_key_path))

    def _load_keys(self) -> None:
        """Load existing RSA key pair from disk.

        Loads private and public keys from PEM files. Keys are cached for
        performance to avoid repeated file I/O and parsing.
        """
        # Load private key
        private_pem = self.private_key_path.read_bytes()
        loaded_private_key = serialization.load_pem_private_key(
            private_pem,
            password=None,  # No password protection for development keys
        )
        # Ensure loaded key is RSA type
        if not isinstance(loaded_private_key, RSAPrivateKey):
            raise TypeError(f"Expected RSA private key, got {type(loaded_private_key)}")
        self._private_key = loaded_private_key

        # Load public key
        public_pem = self.public_key_path.read_bytes()
        loaded_public_key = serialization.load_pem_public_key(public_pem)
        # Ensure loaded key is RSA type
        if not isinstance(loaded_public_key, RSAPublicKey):
            raise TypeError(f"Expected RSA public key, got {type(loaded_public_key)}")
        self._public_key = loaded_public_key

        log.info("rsa_keys_loaded", private_key=str(self.private_key_path))

    def _validate_key_pair(self) -> None:
        """Validate that loaded private and public keys form a matching pair.

        Performs a sign-verify test to ensure keys are cryptographically compatible.

        Raises:
            ValueError: If keys do not form a valid pair
        """
        import jwt

        # Ensure keys are initialized before validation
        if self._private_key is None or self._public_key is None:
            raise ValueError("Keys must be initialized before validation")

        # Sign a test token with private key
        test_claims = {"test": "validation", "exp": 9999999999}
        try:
            test_token = jwt.encode(test_claims, self._private_key, algorithm="RS256")
            # Verify with public key
            jwt.decode(test_token, self._public_key, algorithms=["RS256"])
        except Exception as e:
            raise ValueError(f"Key pair validation failed: {str(e)}") from e

    def get_private_key(self) -> RSAPrivateKey:
        """Get private key for signing JWT tokens.

        Returns:
            RSA private key instance for token signing

        Raises:
            RuntimeError: If keys not initialized (call initialize() first)
        """
        if self._private_key is None:
            raise RuntimeError("Keys not initialized - call initialize() first")
        return self._private_key

    def get_public_key(self) -> RSAPublicKey:
        """Get public key for token verification.

        Returns:
            RSA public key instance for token verification

        Raises:
            RuntimeError: If keys not initialized (call initialize() first)
        """
        if self._public_key is None:
            raise RuntimeError("Keys not initialized - call initialize() first")
        return self._public_key

    def get_public_key_pem(self) -> str:
        """Get public key in PEM format as string.

        This format is suitable for configuration in the main upload service
        JWT_PUBLIC_KEY environment variable.

        Returns:
            Public key in PEM format (UTF-8 string)

        Raises:
            RuntimeError: If keys not initialized
        """
        public_key = self.get_public_key()

        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return public_pem.decode("utf-8")

    def get_public_key_jwks(self) -> dict[str, Any]:
        """Get public key in JWKS format (RFC 7517).

        Converts the RSA public key to JSON Web Key Set (JWKS) format for
        the /.well-known/jwks.json endpoint.

        Returns:
            JWKS dictionary with RSA public key parameters

        Raises:
            RuntimeError: If keys not initialized
            TypeError: If public key is not RSA type
        """
        public_key = self.get_public_key()

        # Verify key is RSA type
        if not isinstance(public_key, RSAPublicKey):
            raise TypeError("Public key must be RSA key")

        # Extract RSA public numbers (modulus and exponent)
        numbers = public_key.public_numbers()

        # Convert integers to base64url format (RFC 7517)
        def int_to_base64url(n: int) -> str:
            """Convert integer to base64url encoding without padding."""
            # Calculate byte length needed
            byte_length = (n.bit_length() + 7) // 8
            # Convert to big-endian bytes
            n_bytes = n.to_bytes(byte_length, byteorder="big")
            # Base64url encode and remove padding
            return base64.urlsafe_b64encode(n_bytes).decode("utf-8").rstrip("=")

        # Build JWKS structure (RFC 7517)
        return {
            "keys": [
                {
                    "kty": "RSA",  # Key type
                    "use": "sig",  # Usage: signature
                    "alg": "RS256",  # Algorithm
                    "kid": "stub-auth-key-1",  # Key ID
                    "n": int_to_base64url(numbers.n),  # Modulus
                    "e": int_to_base64url(numbers.e),  # Exponent
                }
            ]
        }
