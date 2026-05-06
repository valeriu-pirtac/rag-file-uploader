"""HTTP-level integration tests for resume functionality (Story 4.2 AC validation).

These tests validate the HTTP presentation layer for resume-from-offset:
- AC1: HEAD endpoint returns Upload-Offset header
- AC2: HEAD/PATCH responses include Upload-Length header
- AC7: PATCH endpoint returns 409 Conflict with error details on offset mismatch

Complements test_resume_from_offset.py which tests domain/application layers.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import redis.asyncio as aioredis
from fastapi.testclient import TestClient

from src.domain.entities import UploadSession
from src.domain.value_objects import SessionStatus, SHA256Hash


TEST_JWT_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqc7D4YqrpKAQyZ8T/O/h
AEr7u9btVsE5EJKf7Q2N2qu8gsjTCWXXxK36xETMuR2arSCsry/j71syUXVblHXb
ByiipaKzzpBv/AcWip2kMucmQ/4AoMGdmBav7MKVNhuMf7rIg1udhpc1HdUKiMHd
vWXXuGqyltQ5XTcUgjZWqfQF58GKvq9SIcIQpcLk24ZaN9RaQXsut6PQALQBXfFS
cqE2zJ4JX9zhCAo2zMGouj5QGvAstEPsi9fs0mm/pjACihRA1KPn75hB8exOonBd
AFLuPKEGvpNPzmUGmPoNVyJSC3vxl1L0PjUDuLjJpV+hyRpfwKShLcS94KspanuN
CwIDAQAB
-----END PUBLIC KEY-----"""

CHUNK_SIZE = 5_242_880  # 5 MB


@pytest.fixture
async def redis_client():
    """Create Redis client for integration tests."""
    import os

    test_db = int(os.environ.get("REDIS_TEST_DB", "1"))
    client = aioredis.from_url(f"redis://localhost:6379/{test_db}", decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
def test_environment(monkeypatch):
    """Set up test environment variables."""
    import os

    test_db = int(os.environ.get("REDIS_TEST_DB", "1"))
    monkeypatch.setenv("REDIS_URL", f"redis://localhost:6379/{test_db}")
    monkeypatch.setenv("JWT_PUBLIC_KEY", TEST_JWT_PUBLIC_KEY)
    monkeypatch.setenv("JWT_ALGORITHM", "RS256")
    monkeypatch.setenv("MINIO_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("S3_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("CLAMAV_HOST", "localhost")
    monkeypatch.setenv("EVENT_PUBLISH_MODE", "webhook")
    monkeypatch.setenv("WEBHOOK_URL", "http://localhost:8080/webhook")
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("MAX_CONCURRENT_UPLOADS", "10")

    from src.infrastructure.config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def mock_current_user():
    """Create mock authenticated OWNER user."""
    from src.domain.value_objects.jwt_claims import JWTClaims
    from src.domain.value_objects.workspace_role import WorkspaceRole

    return JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    )


@pytest.fixture
def test_app(test_environment, mock_current_user):
    """Create FastAPI test app with mocked auth."""
    from fastapi import FastAPI

    from src.domain.value_objects.workspace_role import WorkspaceRole
    from src.infrastructure.auth.rbac_middleware import require_role
    from src.presentation.api.middleware.auth import get_current_user
    from src.presentation.api.v1.routers import uploads

    app = FastAPI()
    app.include_router(uploads.router)

    uploads.get_redis_client.cache_clear()

    def override_get_redis_client():
        from src.infrastructure.config.settings import get_settings

        settings = get_settings()
        return aioredis.from_url(settings.redis_url, decode_responses=True)

    async def override_get_current_user():
        return mock_current_user

    async def override_require_role_owner():
        return mock_current_user

    app.dependency_overrides[uploads.get_redis_client] = override_get_redis_client
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[require_role(WorkspaceRole.OWNER)] = override_require_role_owner

    return app


@pytest.fixture
def test_client(test_app):
    """Create FastAPI test client."""
    return TestClient(test_app)


@pytest.fixture
def auth_headers():
    """Create authentication headers."""
    return {
        "Authorization": "Bearer test-token",
    }


def create_test_session(workspace_id, session_id, offset=0, size=15_728_640):
    """Helper to create test upload session."""
    return UploadSession(
        session_id=session_id,
        workspace_id=workspace_id,
        filename="test-file.pdf",
        size=size,
        mime_type="application/pdf",
        sha256_checksum=SHA256Hash("a" * 64),
        offset=offset,
        status=SessionStatus.IN_PROGRESS,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        chunk_manifest=[],
    )


async def store_session_in_redis(redis_client, session):
    """Helper to manually store session in Redis."""
    from src.infrastructure.redis.key_builder import session_key

    key = session_key(session.workspace_id, session.session_id)
    session_data = {
        "session_id": str(session.session_id),
        "workspace_id": str(session.workspace_id),
        "filename": session.filename,
        "size": str(session.size),
        "mime_type": session.mime_type,
        "sha256_checksum": str(session.sha256_checksum),
        "offset": str(session.offset),
        "status": session.status.value,
        "created_at": session.created_at.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "chunk_manifest": "[]",
    }
    await redis_client.hset(key, mapping=session_data)
    await redis_client.expire(key, 86400)  # 24 hours


# ==============================================================================
# AC1: HEAD returns Upload-Offset header
# ==============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
class TestResumeHTTPEndpoints:
    """HTTP-level integration tests for resume functionality."""

    async def test_head_returns_upload_offset_header(
        self,
        test_client: TestClient,
        redis_client,
        mock_current_user,
        auth_headers,
    ):
        """Test HEAD /v1/uploads/{id} returns Upload-Offset header (AC1).

        Validates that HEAD endpoint includes Upload-Offset header in response,
        not just the domain entity field.
        """
        # ARRANGE: Create session with 2 chunks uploaded (10 MB offset)
        workspace_id = mock_current_user.workspace_id
        session_id = uuid4()
        offset = 2 * CHUNK_SIZE  # 10,485,760 bytes

        session = create_test_session(workspace_id, session_id, offset=offset)

        # Store in Redis
        await store_session_in_redis(redis_client, session)

        # ACT: Call HEAD endpoint
        response = test_client.head(
            f"/v1/uploads/{session_id}",
            headers=auth_headers,
        )

        # ASSERT: Response successful
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        # ASSERT: Upload-Offset header present and correct (AC1)
        assert "upload-offset" in response.headers, "Upload-Offset header missing"
        assert response.headers["upload-offset"] == str(offset), (
            f"Expected offset {offset}, got {response.headers['upload-offset']}"
        )

    # ==============================================================================
    # AC2: Response includes Upload-Length header
    # ==============================================================================

    async def test_head_returns_upload_length_header(
        self,
        test_client: TestClient,
        redis_client,
        mock_current_user,
        auth_headers,
    ):
        """Test HEAD /v1/uploads/{id} returns Upload-Length header (AC2).

        Validates that HEAD response includes total file size in Upload-Length header.
        """
        # ARRANGE: Create session with known file size
        workspace_id = mock_current_user.workspace_id
        session_id = uuid4()
        file_size = 15_728_640  # 15 MB

        session = create_test_session(workspace_id, session_id, size=file_size, offset=0)
        await store_session_in_redis(redis_client, session)

        # ACT: Call HEAD endpoint
        response = test_client.head(
            f"/v1/uploads/{session_id}",
            headers=auth_headers,
        )

        # ASSERT: Upload-Length header present and correct (AC2)
        assert "upload-length" in response.headers, "Upload-Length header missing"
        assert response.headers["upload-length"] == str(file_size), (
            f"Expected size {file_size}, got {response.headers['upload-length']}"
        )

    # ==============================================================================
    # AC7: Offset mismatch returns 409 Conflict with error details
    # ==============================================================================

    async def test_patch_returns_409_on_offset_mismatch(
        self,
        test_client: TestClient,
        redis_client,
        mock_current_user,
        auth_headers,
    ):
        """Test PATCH returns 409 Conflict on offset mismatch (AC7).

        Validates that PATCH with wrong offset returns HTTP 409 status code
        with structured error response containing expected/received offsets.
        """
        # ARRANGE: Create session with offset at 10 MB (2 chunks uploaded)
        workspace_id = mock_current_user.workspace_id
        session_id = uuid4()
        current_offset = 2 * CHUNK_SIZE  # 10,485,760 bytes

        session = create_test_session(workspace_id, session_id, offset=current_offset)
        await store_session_in_redis(redis_client, session)

        # Prepare chunk data
        chunk_data = b"x" * CHUNK_SIZE
        chunk_checksum = hashlib.sha256(chunk_data).hexdigest()

        # ACT: Send PATCH with wrong offset (0 instead of 10 MB)
        response = test_client.patch(
            f"/v1/uploads/{session_id}",
            headers={
                **auth_headers,
                "Content-Type": "application/offset+octet-stream",
                "Upload-Offset": "0",  # WRONG - should be current_offset
                "Upload-Length": str(session.size),
                "Upload-Checksum": f"sha256 {chunk_checksum}",
            },
            content=chunk_data,
        )

        # ASSERT: HTTP 409 Conflict returned (AC7)
        assert response.status_code == 409, f"Expected 409 Conflict, got {response.status_code}"

        # ASSERT: Error response body structure (AC7)
        error_data = response.json()
        assert "detail" in error_data, "Detail missing from response"
        detail = error_data["detail"]
        assert "error" in detail, "Error code missing from detail"
        assert detail["error"] == "OFFSET_MISMATCH", "Wrong error code"

        # ASSERT: Error details include expected and received offsets (AC7)
        assert "details" in detail, "Error details missing"
        details = detail["details"]
        assert "expected_offset" in details, "Expected offset missing from details"
        assert "received_offset" in details, "Received offset missing from details"
        assert details["expected_offset"] == current_offset
        assert details["received_offset"] == 0

    async def test_patch_succeeds_with_matching_offset(
        self,
        test_client: TestClient,
        redis_client,
        mock_current_user,
        auth_headers,
    ):
        """Test PATCH succeeds when offset matches (complementary to AC7).

        Validates that correct offset results in 204 No Content, not 409.
        """
        # ARRANGE: Create session with offset at 10 MB
        workspace_id = mock_current_user.workspace_id
        session_id = uuid4()
        current_offset = 2 * CHUNK_SIZE

        session = create_test_session(workspace_id, session_id, offset=current_offset)
        await store_session_in_redis(redis_client, session)

        # Prepare chunk data
        chunk_data = b"x" * CHUNK_SIZE
        chunk_checksum = hashlib.sha256(chunk_data).hexdigest()

        # ACT: Send PATCH with CORRECT offset
        response = test_client.patch(
            f"/v1/uploads/{session_id}",
            headers={
                **auth_headers,
                "Content-Type": "application/offset+octet-stream",
                "Upload-Offset": str(current_offset),  # CORRECT
                "Upload-Length": str(session.size),
                "Upload-Checksum": f"sha256 {chunk_checksum}",
            },
            content=chunk_data,
        )

        # ASSERT: Success response (not 409)
        assert response.status_code == 204, f"Expected 204, got {response.status_code}"

        # ASSERT: New offset returned in header
        assert "upload-offset" in response.headers
        new_offset = int(response.headers["upload-offset"])
        assert new_offset == current_offset + CHUNK_SIZE
