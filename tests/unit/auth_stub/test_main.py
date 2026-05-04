"""Tests for FastAPI endpoints in stub auth service.

Test coverage:
- POST /generate-token for owner role
- POST /generate-token for collaborator role with shared files
- POST /generate-token validation errors (invalid role, missing fields)
- GET /.well-known/jwks.json returns valid JWKS
- GET /health check endpoint
- Token signature verification
- Token expiry validation (1 hour)
"""

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

import docker.auth_stub.main as main


# Add docker/auth-stub to Python path for imports
auth_stub_path = Path(__file__).parent.parent.parent.parent / "docker" / "auth_stub"
sys.path.insert(0, str(auth_stub_path))

# Import after path setup
try:
    from docker.auth_stub.keys import RSAKeyManager
except ImportError:
    pytest.skip("main.py not yet implemented", allow_module_level=True)


@pytest.fixture(autouse=True)
def setup_key_manager(tmp_path, monkeypatch):
    """Initialize key manager for tests.

    Uses temporary directory for test isolation. Key manager is initialized
    before each test and cleaned up after.
    """

    # Create and initialize key manager in temp directory
    test_key_manager = RSAKeyManager(keys_dir=tmp_path / "keys")
    test_key_manager.initialize()

    # Monkeypatch the global key_manager in main module
    monkeypatch.setattr(main, "key_manager", test_key_manager)

    return test_key_manager


@pytest.mark.asyncio
async def test_generate_token_owner(setup_key_manager):
    """Test token generation for owner role.

    RED PHASE: This test should fail until main.py implements POST /generate-token.
    """
    user_id = uuid4()
    workspace_id = uuid4()

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/generate-token",
            json={
                "user_id": str(user_id),
                "workspace_id": str(workspace_id),
                "workspace_role": "owner",
            },
        )

    # Verify response structure
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "Bearer"
    assert data["expires_in"] == 3600

    # Verify token is valid JWT
    token = data["access_token"]
    decoded = jwt.decode(
        token,
        setup_key_manager.get_public_key(),
        algorithms=["RS256"],
    )

    # Verify claims
    assert decoded["user_id"] == str(user_id)
    assert decoded["active_workspace_id"] == str(workspace_id)
    assert decoded["workspace_role"] == "owner"
    assert "shared_file_ids" not in decoded or decoded["shared_file_ids"] is None
    assert "exp" in decoded
    assert "iat" in decoded


@pytest.mark.asyncio
async def test_generate_token_collaborator_with_shared_files(setup_key_manager):
    """Test token generation for collaborator with shared files.

    RED PHASE: This test should fail until shared_file_ids handling is implemented.
    """
    user_id = uuid4()
    workspace_id = uuid4()
    file_ids = [uuid4(), uuid4(), uuid4()]

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/generate-token",
            json={
                "user_id": str(user_id),
                "workspace_id": str(workspace_id),
                "workspace_role": "collaborator",
                "shared_file_ids": [str(fid) for fid in file_ids],
            },
        )

    assert response.status_code == 200
    data = response.json()
    token = data["access_token"]

    decoded = jwt.decode(
        token,
        setup_key_manager.get_public_key(),
        algorithms=["RS256"],
    )

    assert decoded["workspace_role"] == "collaborator"
    assert "shared_file_ids" in decoded
    assert len(decoded["shared_file_ids"]) == 3
    assert all(fid in decoded["shared_file_ids"] for fid in [str(f) for f in file_ids])


@pytest.mark.asyncio
async def test_generate_token_invalid_role():
    """Test token generation with invalid workspace_role.

    RED PHASE: This test should fail until validation is implemented.
    """
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/generate-token",
            json={
                "user_id": str(uuid4()),
                "workspace_id": str(uuid4()),
                "workspace_role": "admin",  # Invalid role
            },
        )

    # Should return 422 Unprocessable Entity for validation error
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_generate_token_missing_required_fields():
    """Test token generation with missing required fields.

    RED PHASE: This test should fail until validation is implemented.
    """
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        # Missing workspace_role
        response = await client.post(
            "/generate-token",
            json={
                "user_id": str(uuid4()),
                "workspace_id": str(uuid4()),
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_token_expiry_is_one_hour(setup_key_manager):
    """Test generated token has 1 hour expiry.

    RED PHASE: This test should fail until expiry logic is correct.
    """
    before_time = datetime.now(UTC)

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/generate-token",
            json={
                "user_id": str(uuid4()),
                "workspace_id": str(uuid4()),
                "workspace_role": "owner",
            },
        )

    token = response.json()["access_token"]
    decoded = jwt.decode(
        token,
        setup_key_manager.get_public_key(),
        algorithms=["RS256"],
    )

    # Verify expiry is ~1 hour from now (allow 30 second tolerance for CI stability)
    exp_time = datetime.fromtimestamp(decoded["exp"], tz=UTC)
    expected_exp = before_time.timestamp() + 3600
    assert abs(exp_time.timestamp() - expected_exp) < 30


@pytest.mark.asyncio
async def test_get_jwks(setup_key_manager):
    """Test JWKS endpoint returns valid format.

    RED PHASE: This test should fail until GET /.well-known/jwks.json is implemented.
    """
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/.well-known/jwks.json")

    assert response.status_code == 200
    data = response.json()

    # Verify JWKS structure
    assert "keys" in data
    assert len(data["keys"]) == 1

    key = data["keys"][0]
    assert key["kty"] == "RSA"
    assert key["use"] == "sig"
    assert key["alg"] == "RS256"
    assert key["kid"] == "stub-auth-key-1"
    assert "n" in key
    assert "e" in key


@pytest.mark.asyncio
async def test_health_check():
    """Test health check endpoint.

    RED PHASE: This test should fail until GET /health is implemented.
    """
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "stub-auth"


@pytest.mark.asyncio
async def test_token_signature_verification(setup_key_manager):
    """Test generated tokens have valid RS256 signatures.

    RED PHASE: This test should fail until token signing is correct.
    """
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/generate-token",
            json={
                "user_id": str(uuid4()),
                "workspace_id": str(uuid4()),
                "workspace_role": "owner",
            },
        )

    token = response.json()["access_token"]

    # Verify token can be decoded and verified with public key
    try:
        jwt.decode(
            token,
            setup_key_manager.get_public_key(),
            algorithms=["RS256"],
        )
    except jwt.InvalidTokenError:
        pytest.fail("Token signature verification failed")


@pytest.mark.asyncio
async def test_collaborator_without_shared_files(setup_key_manager):
    """Test collaborator token generation without shared_file_ids.

    Collaborators can have null shared_file_ids initially.
    """
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post(
            "/generate-token",
            json={
                "user_id": str(uuid4()),
                "workspace_id": str(uuid4()),
                "workspace_role": "collaborator",
            },
        )

    assert response.status_code == 200
    token = response.json()["access_token"]

    decoded = jwt.decode(
        token,
        setup_key_manager.get_public_key(),
        algorithms=["RS256"],
    )

    assert decoded["workspace_role"] == "collaborator"
    # shared_file_ids may be absent or null
    assert "shared_file_ids" not in decoded or decoded["shared_file_ids"] is None
