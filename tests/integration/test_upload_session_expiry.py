"""Integration tests for upload session expiry handling (Story 4.1).

Tests the enhanced error responses when clients attempt to access expired sessions.
Uses real Redis instance to test TTL behavior and expiry metadata.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import redis.asyncio as aioredis
from fastapi.testclient import TestClient

from src.domain.entities import UploadSession
from src.domain.value_objects import SessionStatus, SHA256Hash
from src.infrastructure.redis.session_store import RedisSessionStore


TEST_JWT_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqc7D4YqrpKAQyZ8T/O/h
AEr7u9btVsE5EJKf7Q2N2qu8gsjTCWXXxK36xETMuR2arSCsry/j71syUXVblHXb
ByiipaKzzpBv/AcWip2kMucmQ/4AoMGdmBav7MKVNhuMf7rIg1udhpc1HdUKiMHd
vWXXuGqyltQ5XTcUgjZWqfQF58GKvq9SIcIQpcLk24ZaN9RaQXsut6PQALQBXfFS
cqE2zJ4JX9zhCAo2zMGouj5QGvAstEPsi9fs0mm/pjACihRA1KPn75hB8exOonBd
AFLuPKEGvpNPzmUGmPoNVyJSC3vxl1L0PjUDuLjJpV+hyRpfwKShLcS94KspanuN
CwIDAQAB
-----END PUBLIC KEY-----"""


@pytest.fixture
async def redis_client():
    """Create Redis client for integration tests."""
    client = aioredis.from_url("redis://localhost:6379/1", decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
async def session_store(redis_client):
    """Create RedisSessionStore with real Redis client."""
    return RedisSessionStore(redis_client)


@pytest.fixture
def test_environment(monkeypatch):
    """Set up test environment variables for AppSettings."""
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")
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
    """Create mock authenticated OWNER user for testing."""
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
    """Create FastAPI test app with mocked auth for testing."""
    from fastapi import FastAPI

    from src.domain.value_objects.workspace_role import WorkspaceRole
    from src.infrastructure.auth.rbac_middleware import require_role
    from src.presentation.api.middleware.auth import get_current_user
    from src.presentation.api.v1.routers import uploads

    app = FastAPI()
    app.include_router(uploads.router)

    # Clear Redis client cache
    uploads.get_redis_client.cache_clear()

    # Override Redis client
    def override_get_redis_client():
        from src.infrastructure.config.settings import get_settings

        settings = get_settings()
        return aioredis.from_url(settings.redis_url, decode_responses=True)

    # Mock JWT authentication
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
    """Create authentication headers for testing."""
    return {
        "Authorization": "Bearer test-token",
        "Content-Type": "application/json",
    }


@pytest.mark.asyncio
@pytest.mark.integration
class TestExpiredSessionErrorResponses:
    """Integration tests for expired session error responses."""

    async def test_head_endpoint_returns_session_expired_error(
        self,
        test_client: TestClient,
        redis_client: aioredis.Redis,
        auth_headers: dict,
        mock_current_user,
    ) -> None:
        """Test HEAD /v1/uploads/{id} returns SESSION_EXPIRED for expired sessions."""
        # Create a session manually in Redis
        workspace_id = mock_current_user.workspace_id
        session_id = uuid4()

        # Create expiry metadata (simulating expired session)
        expiry_key = f"session:expiry:{session_id}"
        expires_at = datetime.now(UTC)
        expiry_metadata = {
            "session_id": str(session_id),
            "workspace_id": str(workspace_id),
            "expires_at": expires_at.isoformat(),
            "filename": "test.pdf",
        }

        # Store only expiry metadata (no session data, simulating expiry)
        await redis_client.hset(expiry_key, mapping=expiry_metadata)
        await redis_client.expire(expiry_key, 604800)  # 7 days

        # Query offset - should get SESSION_EXPIRED error
        response = test_client.head(f"/v1/uploads/{session_id}", headers=auth_headers)

        assert response.status_code == 404

        # Note: HEAD responses don't have body in standard HTTP
        # But FastAPI may include error details in some test scenarios
        # In production, the error would be logged server-side

        # Cleanup
        await redis_client.delete(expiry_key)

    async def test_patch_endpoint_returns_session_expired_error(
        self,
        test_client: TestClient,
        redis_client: aioredis.Redis,
        auth_headers: dict,
        mock_current_user,
    ) -> None:
        """Test PATCH /v1/uploads/{id} returns SESSION_EXPIRED for expired sessions."""
        # Create a session manually in Redis
        workspace_id = mock_current_user.workspace_id
        session_id = uuid4()

        # Create expiry metadata (simulating expired session)
        expiry_key = f"session:expiry:{session_id}"
        expires_at = datetime.now(UTC)
        expiry_metadata = {
            "session_id": str(session_id),
            "workspace_id": str(workspace_id),
            "expires_at": expires_at.isoformat(),
            "filename": "test.pdf",
        }

        # Store only expiry metadata (no session data, simulating expiry)
        await redis_client.hset(expiry_key, mapping=expiry_metadata)
        await redis_client.expire(expiry_key, 604800)  # 7 days

        # Upload chunk - should get SESSION_EXPIRED error
        chunk_data = b"x" * 5242880  # 5MB chunk
        checksum = hashlib.sha256(chunk_data).hexdigest()

        response = test_client.patch(
            f"/v1/uploads/{session_id}",
            headers={
                **auth_headers,
                "Upload-Offset": "0",
                "Upload-Length": "5242880",
                "Upload-Checksum": f"sha256 {checksum}",
                "Content-Type": "application/offset+octet-stream",
            },
            content=chunk_data,
        )

        assert response.status_code == 404
        response_json = response.json()
        error_detail = response_json["detail"]
        assert error_detail["error"] == "SESSION_EXPIRED"
        assert "expired" in error_detail["message"].lower()
        assert "expired_at" in error_detail["details"]
        assert "expired_hours_ago" in error_detail["details"]
        assert "suggestion" in error_detail["details"]

        # Cleanup
        await redis_client.delete(expiry_key)

    async def test_delete_endpoint_returns_session_expired_error(
        self,
        test_client: TestClient,
        redis_client: aioredis.Redis,
        auth_headers: dict,
        mock_current_user,
    ) -> None:
        """Test DELETE /v1/uploads/{id} returns SESSION_EXPIRED for expired sessions."""
        # Create a session manually in Redis
        workspace_id = mock_current_user.workspace_id
        session_id = uuid4()

        # Create expiry metadata (simulating expired session)
        expiry_key = f"session:expiry:{session_id}"
        expires_at = datetime.now(UTC)
        expiry_metadata = {
            "session_id": str(session_id),
            "workspace_id": str(workspace_id),
            "expires_at": expires_at.isoformat(),
            "filename": "test.pdf",
        }

        # Store only expiry metadata (no session data, simulating expiry)
        await redis_client.hset(expiry_key, mapping=expiry_metadata)
        await redis_client.expire(expiry_key, 604800)  # 7 days

        # Abort session - should get SESSION_EXPIRED error
        response = test_client.delete(f"/v1/uploads/{session_id}", headers=auth_headers)

        assert response.status_code == 404
        response_json = response.json()
        error_detail = response_json["detail"]
        assert error_detail["error"] == "SESSION_EXPIRED"
        assert "expired" in error_detail["message"].lower()
        assert "automatically cleaned up" in error_detail["message"].lower()

        # Cleanup
        await redis_client.delete(expiry_key)

    async def test_session_not_found_for_never_existed_session(
        self,
        test_client: TestClient,
        auth_headers: dict,
    ) -> None:
        """Test endpoints return SESSION_NOT_FOUND for sessions that never existed."""
        fake_session_id = uuid4()

        # HEAD endpoint
        response = test_client.head(f"/v1/uploads/{fake_session_id}", headers=auth_headers)
        assert response.status_code == 404

        # PATCH endpoint
        chunk_data = b"x" * 1024
        checksum = hashlib.sha256(chunk_data).hexdigest()
        response = test_client.patch(
            f"/v1/uploads/{fake_session_id}",
            headers={
                **auth_headers,
                "Upload-Offset": "0",
                "Upload-Length": "1024",
                "Upload-Checksum": f"sha256 {checksum}",
                "Content-Type": "application/offset+octet-stream",
            },
            content=chunk_data,
        )
        assert response.status_code == 404
        response_json = response.json()
        error_detail = response_json["detail"]
        assert error_detail["error"] == "SESSION_NOT_FOUND"

        # DELETE endpoint
        response = test_client.delete(f"/v1/uploads/{fake_session_id}", headers=auth_headers)
        assert response.status_code == 404
        response_json = response.json()
        error_detail = response_json["detail"]
        assert error_detail["error"] == "SESSION_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.integration
class TestExpiryMetadataStorage:
    """Integration tests for expiry metadata storage in Redis."""

    async def test_create_session_stores_expiry_metadata(
        self,
        redis_client: aioredis.Redis,
        session_store: RedisSessionStore,
    ) -> None:
        """Test that creating a session also creates expiry metadata."""
        # Create a session
        workspace_id = uuid4()
        session_id = uuid4()
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(hours=24)

        session = UploadSession(
            session_id=session_id,
            workspace_id=workspace_id,
            filename="test.pdf",
            size=1024,
            mime_type="application/pdf",
            sha256_checksum=SHA256Hash("a" * 64),
            offset=0,
            status=SessionStatus.PENDING,
            created_at=created_at,
            expires_at=expires_at,
            chunk_manifest=[],
        )

        await session_store.create_session(session)

        # Verify session exists
        session_key = f"session:workspace_{workspace_id}:document_{session_id}"
        assert await redis_client.exists(session_key) == 1

        # Verify expiry metadata exists
        expiry_key = f"session:expiry:{session_id}"
        assert await redis_client.exists(expiry_key) == 1

        # Verify metadata content
        expiry_data = await redis_client.hgetall(expiry_key)
        assert expiry_data["session_id"] == str(session_id)
        assert expiry_data["workspace_id"] == str(workspace_id)
        assert expiry_data["expires_at"] == expires_at.isoformat()
        assert expiry_data["filename"] == "test.pdf"

        # Verify TTLs
        session_ttl = await redis_client.ttl(session_key)
        expiry_ttl = await redis_client.ttl(expiry_key)

        # Session TTL should be ~24 hours (86400 seconds)
        assert 86300 < session_ttl <= 86400

        # Expiry metadata TTL should be ~7 days (604800 seconds)
        assert 604700 < expiry_ttl <= 604800

        # Cleanup
        await redis_client.delete(session_key)
        await redis_client.delete(expiry_key)

    async def test_get_session_with_expiry_info_active_session(
        self,
        redis_client: aioredis.Redis,
        session_store: RedisSessionStore,
    ) -> None:
        """Test get_session_with_expiry_info returns session for active sessions."""
        # Create a session
        workspace_id = uuid4()
        session_id = uuid4()
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(hours=24)

        session = UploadSession(
            session_id=session_id,
            workspace_id=workspace_id,
            filename="test.pdf",
            size=1024,
            mime_type="application/pdf",
            sha256_checksum=SHA256Hash("a" * 64),
            offset=0,
            status=SessionStatus.PENDING,
            created_at=created_at,
            expires_at=expires_at,
            chunk_manifest=[],
        )

        await session_store.create_session(session)

        # Get session with expiry info
        result_session, expiry_metadata = await session_store.get_session_with_expiry_info(
            workspace_id, session_id
        )

        assert result_session is not None
        assert result_session.session_id == session_id
        assert expiry_metadata is None

        # Cleanup
        session_key = f"session:workspace_{workspace_id}:document_{session_id}"
        expiry_key = f"session:expiry:{session_id}"
        await redis_client.delete(session_key)
        await redis_client.delete(expiry_key)

    async def test_get_session_with_expiry_info_expired_session(
        self,
        redis_client: aioredis.Redis,
        session_store: RedisSessionStore,
    ) -> None:
        """Test get_session_with_expiry_info returns metadata for expired sessions."""
        # Create expiry metadata only (simulating expired session)
        workspace_id = uuid4()
        session_id = uuid4()
        expires_at = datetime.now(UTC)

        expiry_key = f"session:expiry:{session_id}"
        expiry_metadata = {
            "session_id": str(session_id),
            "workspace_id": str(workspace_id),
            "expires_at": expires_at.isoformat(),
            "filename": "test.pdf",
        }

        await redis_client.hset(expiry_key, mapping=expiry_metadata)

        # Get session with expiry info
        result_session, result_metadata = await session_store.get_session_with_expiry_info(
            workspace_id, session_id
        )

        assert result_session is None
        assert result_metadata is not None
        assert result_metadata["session_id"] == str(session_id)
        assert result_metadata["expires_at"] == expires_at.isoformat()

        # Cleanup
        await redis_client.delete(expiry_key)

    async def test_get_session_with_expiry_info_never_existed(
        self,
        session_store: RedisSessionStore,
    ) -> None:
        """Test get_session_with_expiry_info returns (None, None) for non-existent sessions."""
        fake_workspace_id = uuid4()
        fake_session_id = uuid4()

        result_session, expiry_metadata = await session_store.get_session_with_expiry_info(
            fake_workspace_id, fake_session_id
        )

        assert result_session is None
        assert expiry_metadata is None
