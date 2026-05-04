"""Integration tests for RBAC middleware with FastAPI endpoints.

These tests verify end-to-end role-based access control enforcement
with FastAPI TestClient using real JWT tokens and dependency overrides.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.domain.value_objects.jwt_claims import JWTClaims
from src.infrastructure.auth.rbac_middleware import require_owner
from src.presentation.api.middleware.auth import get_current_user


# Test fixtures


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
def test_app(rsa_keys, monkeypatch):
    """Create test FastAPI app with RBAC-protected endpoints."""
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

    # Create test app with protected endpoints
    app = FastAPI()

    @app.post("/test-write")
    async def test_write_endpoint(
        current_user: Annotated[JWTClaims, Depends(require_owner())],
    ) -> dict:
        """Write endpoint requiring OWNER role."""
        return {
            "status": "success",
            "workspace_id": str(current_user.workspace_id),
            "role": current_user.workspace_role.value,
        }

    @app.get("/test-read")
    async def test_read_endpoint(
        current_user: Annotated[JWTClaims, Depends(get_current_user)],
    ) -> dict:
        """Read endpoint requiring any authenticated user."""
        return {
            "status": "success",
            "workspace_id": str(current_user.workspace_id),
            "role": current_user.workspace_role.value,
        }

    @app.patch("/test-update")
    async def test_update_endpoint(
        current_user: Annotated[JWTClaims, Depends(require_owner())],
    ) -> dict:
        """Update endpoint requiring OWNER role."""
        return {"status": "updated"}

    @app.delete("/test-delete")
    async def test_delete_endpoint(
        current_user: Annotated[JWTClaims, Depends(require_owner())],
    ) -> dict:
        """Delete endpoint requiring OWNER role."""
        return {"status": "deleted"}

    return app


@pytest.fixture
def client(test_app):
    """Create TestClient with test app."""
    return TestClient(test_app)


def generate_token(
    private_key, workspace_role: str = "owner", expired: bool = False, **kwargs
) -> str:
    """Generate a JWT token for testing.

    Args:
        private_key: RSA private key for signing
        workspace_role: Role to include in token (owner or collaborator)
        expired: Whether to create an expired token
        **kwargs: Additional claims (user_id, workspace_id, shared_file_ids)

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


# Integration Tests - Write endpoints with OWNER role


def test_write_endpoint_with_owner_token_succeeds(rsa_keys, client):
    """Test POST endpoint with OWNER token succeeds."""
    private_key, _ = rsa_keys
    token = generate_token(private_key, workspace_role="owner")

    response = client.post(
        "/test-write",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["role"] == "owner"


def test_update_endpoint_with_owner_token_succeeds(rsa_keys, client):
    """Test PATCH endpoint with OWNER token succeeds."""
    private_key, _ = rsa_keys
    token = generate_token(private_key, workspace_role="owner")

    response = client.patch(
        "/test-update",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "updated"


def test_delete_endpoint_with_owner_token_succeeds(rsa_keys, client):
    """Test DELETE endpoint with OWNER token succeeds."""
    private_key, _ = rsa_keys
    token = generate_token(private_key, workspace_role="owner")

    response = client.delete(
        "/test-delete",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"


# Integration Tests - Write endpoints with COLLABORATOR role (should fail)


def test_write_endpoint_with_collaborator_token_returns_403(rsa_keys, client):
    """Test POST endpoint with COLLABORATOR token returns 403."""
    private_key, _ = rsa_keys
    token = generate_token(private_key, workspace_role="collaborator")

    response = client.post(
        "/test-write",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    data = response.json()
    assert "detail" in data
    assert data["detail"]["required_role"] == "owner"


def test_update_endpoint_with_collaborator_token_returns_403(rsa_keys, client):
    """Test PATCH endpoint with COLLABORATOR token returns 403."""
    private_key, _ = rsa_keys
    token = generate_token(private_key, workspace_role="collaborator")

    response = client.patch(
        "/test-update",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_delete_endpoint_with_collaborator_token_returns_403(rsa_keys, client):
    """Test DELETE endpoint with COLLABORATOR token returns 403."""
    private_key, _ = rsa_keys
    token = generate_token(private_key, workspace_role="collaborator")

    response = client.delete(
        "/test-delete",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


# Integration Tests - Read endpoints (both roles should succeed)


def test_read_endpoint_with_owner_token_succeeds(rsa_keys, client):
    """Test GET endpoint with OWNER token succeeds."""
    private_key, _ = rsa_keys
    token = generate_token(private_key, workspace_role="owner")

    response = client.get(
        "/test-read",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["role"] == "owner"


def test_read_endpoint_with_collaborator_token_succeeds(rsa_keys, client):
    """Test GET endpoint with COLLABORATOR token succeeds."""
    private_key, _ = rsa_keys
    token = generate_token(private_key, workspace_role="collaborator")

    response = client.get(
        "/test-read",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["role"] == "collaborator"


# Integration Tests - RBAC runs after JWT validation


def test_rbac_returns_401_for_invalid_token(client):
    """Test RBAC returns 401 for invalid token (JWT validation fails first)."""
    response = client.post(
        "/test-write",
        headers={"Authorization": "Bearer invalid-token"},
    )

    # Should get 401 from JWT validation, not 403 from RBAC
    assert response.status_code == 401


def test_rbac_returns_401_for_expired_token(rsa_keys, client):
    """Test RBAC returns 401 for expired token (JWT validation fails first)."""
    private_key, _ = rsa_keys
    token = generate_token(private_key, workspace_role="owner", expired=True)

    response = client.post(
        "/test-write",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Should get 401 from JWT validation (expired), not 403 from RBAC
    assert response.status_code == 401


def test_rbac_returns_401_for_missing_token(client):
    """Test RBAC returns 401 for missing Authorization header."""
    response = client.post("/test-write")

    # Should get 401 from JWT validation (missing header)
    assert response.status_code == 401


def test_rbac_returns_403_only_after_valid_jwt(rsa_keys, client):
    """Test RBAC returns 403 only when JWT is valid but role is insufficient."""
    private_key, _ = rsa_keys

    # First verify JWT validation passes with valid collaborator token
    token = generate_token(private_key, workspace_role="collaborator")

    # Read endpoint should succeed (proves JWT is valid)
    read_response = client.get(
        "/test-read",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert read_response.status_code == 200

    # Write endpoint should fail with 403 (JWT valid, role insufficient)
    write_response = client.post(
        "/test-write",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert write_response.status_code == 403
    assert write_response.json()["detail"]["required_role"] == "owner"


# Integration Tests - Error message format


def test_error_message_includes_workspace_owner_role(rsa_keys, client):
    """Test error message format includes required role."""
    private_key, _ = rsa_keys
    token = generate_token(private_key, workspace_role="collaborator")

    response = client.post(
        "/test-write",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    data = response.json()
    assert "Insufficient permissions - owner role required" == data["detail"]["detail"]


def test_error_response_structure(rsa_keys, client):
    """Test error response has correct structure with required fields."""
    private_key, _ = rsa_keys
    token = generate_token(private_key, workspace_role="collaborator")

    response = client.post(
        "/test-write",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    data = response.json()

    # Verify structure (no user_role field for security)
    assert "detail" in data
    assert isinstance(data["detail"], dict)
    assert "detail" in data["detail"]
    assert "required_role" in data["detail"]
    assert "user_role" not in data["detail"]
