"""Tests for RSA key generation and management.

Test coverage:
- RSA key pair generation (2048-bit, RS256)
- Key persistence to disk (PEM format)
- Key reuse across instances (no regeneration)
- JWKS format conversion (RFC 7517)
"""

import sys
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa


# Add docker/auth-stub to Python path for imports
auth_stub_path = Path(__file__).parent.parent.parent.parent / "docker" / "auth_stub"
sys.path.insert(0, str(auth_stub_path))

# Import will be available after implementing keys.py
try:
    from docker.auth_stub.keys import RSAKeyManager
except ImportError:
    pytest.skip("RSAKeyManager not yet implemented", allow_module_level=True)


def test_rsa_key_generation():
    """Test RSA key pair generation with correct parameters.

    RED PHASE: This test should fail until keys.py is implemented.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        key_manager = RSAKeyManager(keys_dir=Path(tmpdir))
        key_manager.initialize()

        # Verify keys were generated
        private_key = key_manager.get_private_key()
        public_key = key_manager.get_public_key()

        assert private_key is not None
        assert public_key is not None

        # Verify key type and parameters
        assert isinstance(private_key, rsa.RSAPrivateKey)
        assert private_key.key_size == 2048
        assert public_key.key_size == 2048

        # Verify key files exist
        assert (Path(tmpdir) / "private.pem").exists()
        assert (Path(tmpdir) / "public.pem").exists()


def test_rsa_key_persistence():
    """Test RSA key pair is reused across instances (no regeneration).

    RED PHASE: This test should fail until keys.py properly loads existing keys.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Generate keys in first instance
        key_manager1 = RSAKeyManager(keys_dir=Path(tmpdir))
        key_manager1.initialize()
        public_key1_pem = key_manager1.get_public_key_pem()

        # Load existing keys in second instance
        key_manager2 = RSAKeyManager(keys_dir=Path(tmpdir))
        key_manager2.initialize()
        public_key2_pem = key_manager2.get_public_key_pem()

        # Verify keys are identical (no regeneration)
        assert public_key1_pem == public_key2_pem


def test_get_public_key_pem_format():
    """Test public key is returned in PEM format.

    RED PHASE: This test should fail until get_public_key_pem() is implemented.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        key_manager = RSAKeyManager(keys_dir=Path(tmpdir))
        key_manager.initialize()

        pem_str = key_manager.get_public_key_pem()

        # Verify PEM format
        assert pem_str.startswith("-----BEGIN PUBLIC KEY-----")
        assert pem_str.strip().endswith("-----END PUBLIC KEY-----")
        assert isinstance(pem_str, str)


def test_get_public_key_jwks_format():
    """Test JWKS format conversion (RFC 7517).

    RED PHASE: This test should fail until get_public_key_jwks() is implemented.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        key_manager = RSAKeyManager(keys_dir=Path(tmpdir))
        key_manager.initialize()

        jwks = key_manager.get_public_key_jwks()

        # Verify JWKS structure
        assert "keys" in jwks
        assert isinstance(jwks["keys"], list)
        assert len(jwks["keys"]) == 1

        key = jwks["keys"][0]
        assert key["kty"] == "RSA"
        assert key["use"] == "sig"
        assert key["alg"] == "RS256"
        assert key["kid"] == "stub-auth-key-1"
        assert "n" in key  # Modulus (base64url encoded)
        assert "e" in key  # Exponent (base64url encoded)

        # Verify base64url encoding (no padding)
        assert "=" not in key["n"]
        assert "=" not in key["e"]


def test_keys_not_initialized_error():
    """Test accessing keys before initialization raises error.

    RED PHASE: This test should fail until proper initialization checks exist.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        key_manager = RSAKeyManager(keys_dir=Path(tmpdir))

        # Should raise error before initialize() is called
        with pytest.raises(RuntimeError, match="Keys not initialized"):
            key_manager.get_private_key()

        with pytest.raises(RuntimeError, match="Keys not initialized"):
            key_manager.get_public_key()


def test_keys_directory_creation():
    """Test keys directory is created if it doesn't exist.

    RED PHASE: This test should fail until directory creation logic exists.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        keys_path = Path(tmpdir) / "nested" / "keys"

        # Directory doesn't exist yet
        assert not keys_path.exists()

        key_manager = RSAKeyManager(keys_dir=keys_path)
        key_manager.initialize()

        # Directory should be created
        assert keys_path.exists()
        assert keys_path.is_dir()

        # Keys should be generated in the new directory
        assert (keys_path / "private.pem").exists()
        assert (keys_path / "public.pem").exists()
