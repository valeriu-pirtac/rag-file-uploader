"""Integration tests for chunked upload flow.

This module tests the end-to-end upload flow with real infrastructure
dependencies (Redis for session storage). Tests verify that POST and PATCH
endpoints work together correctly.

Test Coverage:
    - Complete multi-chunk upload flow (POST → PATCH → PATCH)
    - Offset mismatch handling with real session store
    - Checksum verification with real ChunkVerifier

Integration Points:
    - Story 3.5: POST /v1/uploads endpoint
    - Story 3.8: PATCH /v1/uploads/{id} endpoint
    - Story 3.2: Redis session store
    - Story 3.7: ProcessChunkUseCase
    - Story 3.6: ChunkVerifier

Requirements:
    - Running Redis instance (docker-compose up -d redis)

Architecture:
    - Integration tests with real Redis container
    - TestClient for HTTP testing
    - Fixtures for test data and infrastructure setup
"""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.workspace_role import WorkspaceRole
from src.presentation.api.v1.routers import uploads


# Redis connection URL for integration tests (use DB 1 for tests)
REDIS_TEST_URL = "redis://localhost:6379/1"

# Test RSA public key for JWT validation (required by AppSettings)
TEST_JWT_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqc7D4YqrpKAQyZ8T/O/h
AEr7u9btVsE5EJKf7Q2N2qu8gsjTCWXXxK36xETMuR2arSCsry/j71syUXVblHXb
ByiipaKzzpBv/AcWip2kMucmQ/4AoMGdmBav7MKVNhuMf7rIg1udhpc1HdUKiMHd
vWXXuGqyltQ5XTcUgjZWqfQF58GKvq9SIcIQpcLk24ZaN9RaQXsut6PQALQBXfFS
cqE2zJ4JX9zhCAo2zMGouj5QGvAstEPsi9fs0mm/pjACihRA1KPn75hB8exOonBd
AFLuPKEGvpNPzmUGmPoNVyJSC3vxl1L0PjUDuLjJpV+hyRpfwKShLcS94KspanuN
CwIDAQAB
-----END PUBLIC KEY-----"""


# Test Fixtures


@pytest.fixture
def test_environment(monkeypatch):
    """Set up test environment variables for AppSettings."""
    monkeypatch.setenv("REDIS_URL", REDIS_TEST_URL)
    monkeypatch.setenv("JWT_PUBLIC_KEY", TEST_JWT_PUBLIC_KEY)
    monkeypatch.setenv("JWT_ALGORITHM", "RS256")
    monkeypatch.setenv("MINIO_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("S3_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("CLAMAV_HOST", "localhost")
    monkeypatch.setenv("EVENT_PUBLISH_MODE", "webhook")
    monkeypatch.setenv("WEBHOOK_URL", "http://localhost:8080/webhook")
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("MAX_CONCURRENT_UPLOADS", "10")

    # Clear lru_cache to force reload with new env vars
    from src.infrastructure.config.settings import get_settings
    from src.presentation.api.middleware.auth import get_jwt_validator

    get_settings.cache_clear()
    get_jwt_validator.cache_clear()

    yield

    # Cleanup cache after test
    get_settings.cache_clear()
    get_jwt_validator.cache_clear()


@pytest.fixture
def mock_current_user() -> JWTClaims:
    """Create mock authenticated OWNER user for testing."""
    return JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    )


@pytest.fixture
def test_app(test_environment, mock_current_user: JWTClaims) -> FastAPI:
    """Create FastAPI test app with real dependencies and mocked auth.

    Uses real Redis-backed session store and rate limiter,
    but mocks JWT authentication for testing.
    """
    app = FastAPI()
    app.include_router(uploads.router)

    # Clear Redis client cache to avoid event loop issues
    uploads.get_redis_client.cache_clear()

    # Override Redis client to create fresh instances (no caching in tests)
    def override_get_redis_client() -> aioredis.Redis:
        from src.infrastructure.config.settings import get_settings

        settings = get_settings()
        return aioredis.from_url(settings.redis_url, decode_responses=True)

    # Mock JWT authentication (bypass real JWT validation)
    from src.infrastructure.auth.rbac_middleware import require_role
    from src.presentation.api.middleware.auth import get_current_user

    async def override_get_current_user() -> JWTClaims:
        return mock_current_user

    async def override_require_role_owner() -> JWTClaims:
        return mock_current_user

    app.dependency_overrides[uploads.get_redis_client] = override_get_redis_client
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[require_role(WorkspaceRole.OWNER)] = override_require_role_owner

    return app


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    """Create FastAPI test client with real dependencies."""
    return TestClient(test_app)


@pytest.fixture
def chunk_size() -> int:
    """Standard chunk size for testing (5MB)."""
    return 5242880


@pytest.fixture
def first_chunk_data(chunk_size: int) -> bytes:
    """Create first chunk data (5MB of 'a' bytes)."""
    return b"a" * chunk_size


@pytest.fixture
def second_chunk_data(chunk_size: int) -> bytes:
    """Create second chunk data (5MB of 'b' bytes)."""
    return b"b" * chunk_size


@pytest.fixture
def first_chunk_checksum(first_chunk_data: bytes) -> str:
    """Compute SHA-256 checksum for first chunk."""
    return hashlib.sha256(first_chunk_data).hexdigest()


@pytest.fixture
def second_chunk_checksum(second_chunk_data: bytes) -> str:
    """Compute SHA-256 checksum for second chunk."""
    return hashlib.sha256(second_chunk_data).hexdigest()


# Integration Tests


@pytest.mark.integration
def test_complete_two_chunk_upload_flow(
    client: TestClient,
    chunk_size: int,
    first_chunk_data: bytes,
    second_chunk_data: bytes,
    first_chunk_checksum: str,
    second_chunk_checksum: str,
) -> None:
    """Test complete upload flow: POST → PATCH → PATCH.

    Validates:
        - Session creation via POST returns valid uploadId
        - First PATCH uploads chunk at offset 0
        - Upload-Offset header returns new offset (5MB)
        - Second PATCH uploads chunk at offset 5MB
        - Upload-Offset header returns final offset (10MB)
        - Session state persists between requests

    This test uses real Redis for session storage to verify end-to-end
    integration of presentation, application, and infrastructure layers.
    """
    total_size = chunk_size * 2  # 10MB total

    # STEP 1: Create upload session via POST /v1/uploads
    initiate_request = {
        "filename": "test-document.pdf",
        "size": total_size,
        "mimeType": "application/pdf",
        "sha256Checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }

    response = client.post(
        "/v1/uploads",
        json=initiate_request,
        headers={"Authorization": "Bearer valid-owner-token"},
    )

    assert response.status_code == 201
    response_data = response.json()
    upload_id = response_data["uploadId"]
    assert "offset" in response_data
    assert response_data["offset"] == 0
    assert "expiresAt" in response_data

    # Validate uploadId is valid UUID
    UUID(upload_id)

    # STEP 2: Upload first chunk at offset 0
    first_chunk_headers = {
        "Authorization": "Bearer valid-owner-token",
        "Upload-Offset": "0",
        "Upload-Length": str(total_size),
        "Upload-Checksum": f"sha256 {first_chunk_checksum}",
        "Content-Type": "application/offset+octet-stream",
    }

    response = client.patch(
        f"/v1/uploads/{upload_id}",
        headers=first_chunk_headers,
        content=first_chunk_data,
    )

    assert response.status_code == 204
    assert response.content == b""  # No Content
    assert "Upload-Offset" in response.headers
    assert response.headers["Upload-Offset"] == str(chunk_size)

    # STEP 3: Upload second chunk at offset 5MB
    second_chunk_headers = {
        "Authorization": "Bearer valid-owner-token",
        "Upload-Offset": str(chunk_size),
        "Upload-Length": str(total_size),
        "Upload-Checksum": f"sha256 {second_chunk_checksum}",
        "Content-Type": "application/offset+octet-stream",
    }

    response = client.patch(
        f"/v1/uploads/{upload_id}",
        headers=second_chunk_headers,
        content=second_chunk_data,
    )

    assert response.status_code == 204
    assert response.content == b""  # No Content
    assert "Upload-Offset" in response.headers
    assert response.headers["Upload-Offset"] == str(total_size)


@pytest.mark.integration
def test_offset_mismatch_with_real_session_store(
    client: TestClient,
    chunk_size: int,
    first_chunk_data: bytes,
    second_chunk_data: bytes,
    first_chunk_checksum: str,
    second_chunk_checksum: str,
) -> None:
    """Test offset mismatch handling with real session store.

    Validates:
        - Client can create session
        - Client can upload first chunk successfully
        - Attempting to upload chunk 0 again (wrong offset) returns 409
        - 409 response includes expected and received offsets
        - Error message is actionable

    This test verifies that the server correctly detects offset mismatches
    when client state is out of sync with server state.
    """
    total_size = chunk_size * 2

    # STEP 1: Create session
    initiate_request = {
        "filename": "test-document.pdf",
        "size": total_size,
        "mimeType": "application/pdf",
        "sha256Checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }

    response = client.post(
        "/v1/uploads",
        json=initiate_request,
        headers={"Authorization": "Bearer valid-owner-token"},
    )

    assert response.status_code == 201
    upload_id = response.json()["uploadId"]

    # STEP 2: Upload first chunk successfully
    first_chunk_headers = {
        "Authorization": "Bearer valid-owner-token",
        "Upload-Offset": "0",
        "Upload-Length": str(total_size),
        "Upload-Checksum": f"sha256 {first_chunk_checksum}",
        "Content-Type": "application/offset+octet-stream",
    }

    response = client.patch(
        f"/v1/uploads/{upload_id}",
        headers=first_chunk_headers,
        content=first_chunk_data,
    )

    assert response.status_code == 204
    assert response.headers["Upload-Offset"] == str(chunk_size)

    # STEP 3: Attempt to upload chunk at wrong offset (offset 0 again)
    # Server expects offset 5MB, but client provides offset 0
    wrong_offset_headers = {
        "Authorization": "Bearer valid-owner-token",
        "Upload-Offset": "0",  # Wrong - should be chunk_size
        "Upload-Length": str(total_size),
        "Upload-Checksum": f"sha256 {first_chunk_checksum}",
        "Content-Type": "application/offset+octet-stream",
    }

    response = client.patch(
        f"/v1/uploads/{upload_id}",
        headers=wrong_offset_headers,
        content=first_chunk_data,
    )

    # Verify 409 Conflict response
    assert response.status_code == 409
    response_data = response.json()
    assert response_data["detail"]["error"] == "OFFSET_MISMATCH"
    assert "message" in response_data["detail"]
    assert response_data["detail"]["details"]["expected_offset"] == chunk_size
    assert response_data["detail"]["details"]["received_offset"] == 0
    assert "suggestion" in response_data["detail"]["details"]

    # STEP 4: Verify that correct offset still works
    # Client should query HEAD to get offset, but we'll use the known offset
    correct_headers = {
        "Authorization": "Bearer valid-owner-token",
        "Upload-Offset": str(chunk_size),  # Correct offset
        "Upload-Length": str(total_size),
        "Upload-Checksum": f"sha256 {second_chunk_checksum}",
        "Content-Type": "application/offset+octet-stream",
    }

    response = client.patch(
        f"/v1/uploads/{upload_id}",
        headers=correct_headers,
        content=second_chunk_data,
    )

    assert response.status_code == 204
    assert response.headers["Upload-Offset"] == str(total_size)


@pytest.mark.integration
def test_checksum_verification_with_real_verifier(
    client: TestClient,
    chunk_size: int,
    first_chunk_data: bytes,
) -> None:
    """Test checksum verification with real ChunkVerifier.

    Validates:
        - Client can create session
        - Providing wrong checksum returns 460 Checksum Mismatch
        - 460 response includes both checksums
        - Error message is actionable

    This test verifies that ChunkVerifier correctly detects corrupted chunks.
    """
    total_size = chunk_size

    # STEP 1: Create session
    initiate_request = {
        "filename": "test-document.pdf",
        "size": total_size,
        "mimeType": "application/pdf",
        "sha256Checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }

    response = client.post(
        "/v1/uploads",
        json=initiate_request,
        headers={"Authorization": "Bearer valid-owner-token"},
    )

    assert response.status_code == 201
    upload_id = response.json()["uploadId"]

    # STEP 2: Upload chunk with WRONG checksum
    wrong_checksum = "0" * 64  # Obviously wrong checksum
    wrong_checksum_headers = {
        "Authorization": "Bearer valid-owner-token",
        "Upload-Offset": "0",
        "Upload-Length": str(total_size),
        "Upload-Checksum": f"sha256 {wrong_checksum}",
        "Content-Type": "application/offset+octet-stream",
    }

    response = client.patch(
        f"/v1/uploads/{upload_id}",
        headers=wrong_checksum_headers,
        content=first_chunk_data,
    )

    # Verify 460 Checksum Mismatch response
    assert response.status_code == 460
    response_data = response.json()
    assert response_data["detail"]["error"] == "CHECKSUM_MISMATCH"
    assert "message" in response_data["detail"]
    assert response_data["detail"]["details"]["expected_checksum"] == wrong_checksum
    assert "computed_checksum" in response_data["detail"]["details"]
    assert response_data["detail"]["details"]["computed_checksum"] != wrong_checksum
    assert "suggestion" in response_data["detail"]["details"]
