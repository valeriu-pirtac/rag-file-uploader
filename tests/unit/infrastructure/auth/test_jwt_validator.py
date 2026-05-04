"""Unit tests for JWT validator."""

import secrets
from datetime import UTC, datetime
from uuid import uuid4

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.domain.exceptions import InvalidTokenError, TokenExpiredError
from src.domain.value_objects.workspace_role import WorkspaceRole
from src.infrastructure.auth.jwt_validator import JWTValidator
from src.infrastructure.config.settings import AppSettings


@pytest.fixture
def rsa_keys():
    """Generate RSA key pair for testing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    return private_key, public_pem


@pytest.fixture
def jwt_validator(rsa_keys):
    """Create JWTValidator with test keys."""
    _, public_key_pem = rsa_keys

    # Create minimal AppSettings with test public key
    settings = AppSettings(
        jwt_public_key=public_key_pem,
        jwt_algorithm="RS256",
        # Required fields for AppSettings
        minio_endpoint="http://localhost:9000",
        s3_bucket_name="test-bucket",
        clamav_host="localhost",
        # Set event_publish_mode to webhook to avoid nats_url requirement
        event_publish_mode="webhook",
        webhook_url="http://localhost:8080/webhook",
        webhook_secret="test-secret",
    )

    return JWTValidator(settings)


@pytest.mark.asyncio
async def test_valid_owner_token_decoded_successfully(jwt_validator, rsa_keys):
    """Test decoding a valid RS256 JWT token for owner role."""
    private_key, _ = rsa_keys

    user_id = uuid4()
    workspace_id = uuid4()

    payload = {
        "user_id": str(user_id),
        "active_workspace_id": str(workspace_id),
        "workspace_role": "owner",
        "exp": int(datetime.now(UTC).timestamp()) + 3600,
    }

    token = pyjwt.encode(payload, private_key, algorithm="RS256")

    # Validate
    claims = await jwt_validator.validate(token)

    assert claims.user_id == user_id
    assert claims.workspace_id == workspace_id
    assert claims.workspace_role == WorkspaceRole.OWNER
    assert claims.shared_file_ids is None


@pytest.mark.asyncio
async def test_valid_collaborator_token_with_shared_files(jwt_validator, rsa_keys):
    """Test decoding JWT for collaborator with shared file IDs."""
    private_key, _ = rsa_keys

    user_id = uuid4()
    workspace_id = uuid4()
    file_id_1 = uuid4()
    file_id_2 = uuid4()

    payload = {
        "user_id": str(user_id),
        "active_workspace_id": str(workspace_id),
        "workspace_role": "collaborator",
        "shared_file_ids": [str(file_id_1), str(file_id_2)],
        "exp": int(datetime.now(UTC).timestamp()) + 3600,
    }

    token = pyjwt.encode(payload, private_key, algorithm="RS256")

    claims = await jwt_validator.validate(token)

    assert claims.user_id == user_id
    assert claims.workspace_id == workspace_id
    assert claims.workspace_role == WorkspaceRole.COLLABORATOR
    assert claims.shared_file_ids == (file_id_1, file_id_2)


@pytest.mark.asyncio
async def test_expired_token_raises_token_expired_error(jwt_validator, rsa_keys):
    """Test that expired tokens raise TokenExpiredError."""
    private_key, _ = rsa_keys

    payload = {
        "user_id": str(uuid4()),
        "active_workspace_id": str(uuid4()),
        "workspace_role": "owner",
        "exp": int(datetime.now(UTC).timestamp()) - 3600,  # Expired 1 hour ago
    }

    token = pyjwt.encode(payload, private_key, algorithm="RS256")

    with pytest.raises(TokenExpiredError, match="JWT token has expired"):
        await jwt_validator.validate(token)


@pytest.mark.asyncio
async def test_invalid_signature_raises_invalid_token_error(jwt_validator, rsa_keys):
    """Test that tokens with invalid signature raise InvalidTokenError."""
    # Generate a different key pair
    wrong_private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    payload = {
        "user_id": str(uuid4()),
        "active_workspace_id": str(uuid4()),
        "workspace_role": "owner",
        "exp": int(datetime.now(UTC).timestamp()) + 3600,
    }

    # Sign with wrong key
    token = pyjwt.encode(payload, wrong_private_key, algorithm="RS256")

    with pytest.raises(InvalidTokenError, match="Invalid JWT token"):
        await jwt_validator.validate(token)


@pytest.mark.asyncio
async def test_malformed_token_raises_invalid_token_error(jwt_validator):
    """Test that malformed tokens raise InvalidTokenError."""
    with pytest.raises(InvalidTokenError):
        await jwt_validator.validate("not.a.valid.token")


@pytest.mark.asyncio
async def test_missing_required_claims_raises_invalid_token_error(jwt_validator, rsa_keys):
    """Test that tokens missing required claims raise InvalidTokenError."""
    private_key, _ = rsa_keys

    # Missing user_id
    payload = {
        "active_workspace_id": str(uuid4()),
        "workspace_role": "owner",
        "exp": int(datetime.now(UTC).timestamp()) + 3600,
    }

    token = pyjwt.encode(payload, private_key, algorithm="RS256")

    with pytest.raises(InvalidTokenError, match="Invalid JWT token"):
        await jwt_validator.validate(token)


@pytest.mark.asyncio
async def test_hs256_token_rejected(jwt_validator):
    """Test that HS256 tokens are rejected (only RS256 allowed)."""
    payload = {
        "user_id": str(uuid4()),
        "active_workspace_id": str(uuid4()),
        "workspace_role": "owner",
        "exp": int(datetime.now(UTC).timestamp()) + 3600,
    }

    # Try to create HS256 token
    token = pyjwt.encode(payload, secrets.token_bytes(32), algorithm="HS256")

    with pytest.raises(InvalidTokenError):
        await jwt_validator.validate(token)


@pytest.mark.asyncio
async def test_active_workspace_id_mapped_to_workspace_id(jwt_validator, rsa_keys):
    """Test that active_workspace_id from JWT is mapped to workspace_id in claims."""
    private_key, _ = rsa_keys

    workspace_id = uuid4()

    payload = {
        "user_id": str(uuid4()),
        "active_workspace_id": str(workspace_id),  # Note: active_workspace_id
        "workspace_role": "owner",
        "exp": int(datetime.now(UTC).timestamp()) + 3600,
    }

    token = pyjwt.encode(payload, private_key, algorithm="RS256")
    claims = await jwt_validator.validate(token)

    # Should be mapped to workspace_id
    assert claims.workspace_id == workspace_id


@pytest.mark.asyncio
async def test_shared_file_ids_converted_to_tuple(jwt_validator, rsa_keys):
    """Test that shared_file_ids list is converted to tuple."""
    private_key, _ = rsa_keys

    file_ids = [uuid4(), uuid4(), uuid4()]

    payload = {
        "user_id": str(uuid4()),
        "active_workspace_id": str(uuid4()),
        "workspace_role": "collaborator",
        "shared_file_ids": [str(fid) for fid in file_ids],
        "exp": int(datetime.now(UTC).timestamp()) + 3600,
    }

    token = pyjwt.encode(payload, private_key, algorithm="RS256")
    claims = await jwt_validator.validate(token)

    # Should be tuple, not list
    assert isinstance(claims.shared_file_ids, tuple)
    assert claims.shared_file_ids == tuple(file_ids)


@pytest.mark.asyncio
async def test_validation_performance_under_30ms(jwt_validator, rsa_keys):
    """Test that JWT validation completes in less than 30ms."""
    import time

    private_key, _ = rsa_keys

    payload = {
        "user_id": str(uuid4()),
        "active_workspace_id": str(uuid4()),
        "workspace_role": "owner",
        "exp": int(datetime.now(UTC).timestamp()) + 3600,
    }

    token = pyjwt.encode(payload, private_key, algorithm="RS256")

    # Measure validation time
    start = time.perf_counter()
    await jwt_validator.validate(token)
    duration_ms = (time.perf_counter() - start) * 1000

    # Should complete in less than 30ms
    assert duration_ms < 30, f"JWT validation took {duration_ms:.2f}ms, expected <30ms"


@pytest.mark.asyncio
async def test_invalid_uuid_format_raises_invalid_token_error(jwt_validator, rsa_keys):
    """Test that invalid UUID formats in claims raise InvalidTokenError."""
    private_key, _ = rsa_keys

    payload = {
        "user_id": "not-a-valid-uuid",
        "active_workspace_id": str(uuid4()),
        "workspace_role": "owner",
        "exp": int(datetime.now(UTC).timestamp()) + 3600,
    }

    token = pyjwt.encode(payload, private_key, algorithm="RS256")

    with pytest.raises(InvalidTokenError, match="Invalid JWT claims"):
        await jwt_validator.validate(token)


@pytest.mark.asyncio
async def test_invalid_workspace_role_raises_invalid_token_error(jwt_validator, rsa_keys):
    """Test that invalid workspace role values raise InvalidTokenError."""
    private_key, _ = rsa_keys

    payload = {
        "user_id": str(uuid4()),
        "active_workspace_id": str(uuid4()),
        "workspace_role": "invalid_role",
        "exp": int(datetime.now(UTC).timestamp()) + 3600,
    }

    token = pyjwt.encode(payload, private_key, algorithm="RS256")

    with pytest.raises(InvalidTokenError, match="Invalid JWT claims"):
        await jwt_validator.validate(token)


@pytest.mark.asyncio
async def test_owner_with_shared_file_ids_raises_error(jwt_validator, rsa_keys):
    """Test that owner role with shared_file_ids raises error during JWTClaims validation."""
    private_key, _ = rsa_keys

    payload = {
        "user_id": str(uuid4()),
        "active_workspace_id": str(uuid4()),
        "workspace_role": "owner",
        "shared_file_ids": [str(uuid4())],  # Owners shouldn't have this
        "exp": int(datetime.now(UTC).timestamp()) + 3600,
    }

    token = pyjwt.encode(payload, private_key, algorithm="RS256")

    # Should raise InvalidTokenError (wraps ValueError from JWTClaims validation)
    with pytest.raises(InvalidTokenError, match="OWNER role cannot have shared_file_ids"):
        await jwt_validator.validate(token)


@pytest.mark.asyncio
async def test_collaborator_without_shared_file_ids_raises_error(jwt_validator, rsa_keys):
    """Test that collaborator role without shared_file_ids raises error."""
    private_key, _ = rsa_keys

    payload = {
        "user_id": str(uuid4()),
        "active_workspace_id": str(uuid4()),
        "workspace_role": "collaborator",
        # Missing shared_file_ids
        "exp": int(datetime.now(UTC).timestamp()) + 3600,
    }

    token = pyjwt.encode(payload, private_key, algorithm="RS256")

    # Should raise InvalidTokenError (wraps ValueError from JWTClaims validation)
    with pytest.raises(InvalidTokenError, match="COLLABORATOR role must have shared_file_ids"):
        await jwt_validator.validate(token)
