"""Integration tests for JWT authentication middleware.

These tests verify end-to-end JWT authentication with FastAPI TestClient
using real RSA keys and actual JWT token generation.
"""

from datetime import UTC, datetime
from uuid import uuid4

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient


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
def app_with_auth(rsa_keys, monkeypatch):
    """Create FastAPI app with authentication configured."""
    _, public_key_pem = rsa_keys

    # Set environment variables for AppSettings
    monkeypatch.setenv("JWT_PUBLIC_KEY", public_key_pem)
    monkeypatch.setenv("JWT_ALGORITHM", "RS256")
    monkeypatch.setenv("MINIO_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("S3_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("CLAMAV_HOST", "localhost")
    monkeypatch.setenv("EVENT_PUBLISH_MODE", "webhook")
    monkeypatch.setenv("WEBHOOK_URL", "http://localhost:8080/webhook")
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret")

    # Clear the lru_cache for get_settings and get_jwt_validator
    from src.infrastructure.config.settings import get_settings
    from src.presentation.api.middleware.auth import get_jwt_validator

    get_settings.cache_clear()
    get_jwt_validator.cache_clear()

    # Import app after clearing cache and setting env vars
    from src.presentation.main import app

    return app


@pytest.fixture
def client(app_with_auth):
    """Create TestClient with configured app."""
    return TestClient(app_with_auth)


def generate_token(private_key, workspace_role="owner", expired=False, **kwargs):
    """Generate a JWT token for testing.

    Args:
        private_key: RSA private key for signing
        workspace_role: Role to include in token
        expired: Whether to create an expired token
        **kwargs: Additional claims to include

    Returns:
        str: Encoded JWT token
    """
    user_id = kwargs.get("user_id", str(uuid4()))
    workspace_id = kwargs.get("workspace_id", str(uuid4()))

    exp_timestamp = (
        int(datetime.now(UTC).timestamp()) - 3600
        if expired
        else int(datetime.now(UTC).timestamp()) + 3600
    )

    payload = {
        "user_id": user_id,
        "active_workspace_id": workspace_id,
        "workspace_role": workspace_role,
        "exp": exp_timestamp,
    }

    if workspace_role == "collaborator":
        payload["shared_file_ids"] = kwargs.get("shared_file_ids", [str(uuid4())])

    return pyjwt.encode(payload, private_key, algorithm="RS256")


def test_health_endpoint_is_public(client):
    """Test that health endpoints don't require authentication."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_root_endpoint_is_public(client):
    """Test that root endpoint doesn't require authentication."""
    response = client.get("/")
    assert response.status_code == 200
    assert "service" in response.json()


def test_protected_endpoint_requires_authentication(client):
    """Test that protected endpoints require valid JWT."""
    # Try to access protected endpoint without token
    response = client.get("/v1/uploads")

    assert response.status_code == 401
    assert "Missing" in response.json()["detail"]


def test_protected_endpoint_with_valid_token(client, rsa_keys):
    """Test that valid token allows access to protected endpoints."""
    private_key, _ = rsa_keys

    token = generate_token(private_key, workspace_role="owner")

    response = client.get(
        "/v1/uploads",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Should not return 401 (authentication successful)
    # May return 404 or other code if endpoint not fully implemented
    assert response.status_code != 401


def test_protected_endpoint_with_expired_token(client, rsa_keys):
    """Test that expired token returns 401."""
    private_key, _ = rsa_keys

    token = generate_token(private_key, expired=True)

    response = client.get(
        "/v1/uploads",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication failed"


def test_protected_endpoint_with_invalid_signature(client, rsa_keys):
    """Test that token with invalid signature returns 401."""
    # Generate a different key pair
    wrong_private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    token = generate_token(wrong_private_key)

    response = client.get(
        "/v1/uploads",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication failed"


def test_protected_endpoint_with_malformed_token(client):
    """Test that malformed token returns 401."""
    response = client.get(
        "/v1/uploads",
        headers={"Authorization": "Bearer invalid.token.here"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication failed"


def test_protected_endpoint_without_bearer_prefix(client, rsa_keys):
    """Test that token without Bearer prefix returns 401."""
    private_key, _ = rsa_keys

    token = generate_token(private_key)

    response = client.get(
        "/v1/uploads",
        headers={"Authorization": token},  # Missing "Bearer " prefix
    )

    assert response.status_code == 401
    assert isinstance(response.json()["detail"], str)


def test_error_response_format_matches_spec(client):
    """Test that 401 error responses match FastAPI standard format."""
    response = client.get("/v1/uploads")

    assert response.status_code == 401

    # FastAPI standard format: {"detail": "error message"}
    error_data = response.json()
    assert "detail" in error_data
    assert isinstance(error_data["detail"], str)


def test_collaborator_token_with_shared_files(client, rsa_keys):
    """Test authentication with collaborator role and shared files."""
    private_key, _ = rsa_keys

    file_ids = [str(uuid4()), str(uuid4())]
    token = generate_token(
        private_key,
        workspace_role="collaborator",
        shared_file_ids=file_ids,
    )

    response = client.get(
        "/v1/uploads",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Should not return 401 (authentication successful)
    assert response.status_code != 401


def test_owner_token_without_shared_files(client, rsa_keys):
    """Test authentication with owner role (no shared files)."""
    private_key, _ = rsa_keys

    token = generate_token(private_key, workspace_role="owner")

    response = client.get(
        "/v1/uploads",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Should not return 401 (authentication successful)
    assert response.status_code != 401
