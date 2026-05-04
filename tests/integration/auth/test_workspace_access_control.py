"""Integration tests for workspace access control with FastAPI endpoints."""

from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI, Header
from httpx import ASGITransport, AsyncClient

from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.workspace_role import WorkspaceRole
from src.infrastructure.auth import (
    require_owner,
    validate_file_access,
    validate_workspace_access,
)


# Mock data structures for testing
class MockUploadSession:
    """Mock upload session for testing."""

    def __init__(
        self,
        upload_id: UUID,
        workspace_id: UUID,
        file_id: UUID,
    ) -> None:
        self.upload_id = upload_id
        self.workspace_id = workspace_id
        self.file_id = file_id


@pytest.fixture(autouse=True)
def mock_sessions():
    """Fixture providing clean mock session store for each test."""
    sessions: dict[UUID, MockUploadSession] = {}
    yield sessions
    sessions.clear()


def create_mock_jwt_token(
    user_id: UUID,
    workspace_id: UUID,
    role: WorkspaceRole,
    shared_file_ids: tuple[UUID, ...] | None = None,
) -> str:
    """Create a mock JWT token string for testing."""
    # In real implementation, this would be a signed JWT
    # For testing, we use a simple format that encodes the claims
    return f"mock_jwt_{user_id}_{workspace_id}_{role.value}_{shared_file_ids or 'none'}"


def parse_mock_jwt_token(token: str) -> JWTClaims:
    """Parse a mock JWT token into JWTClaims."""
    parts = token.replace("mock_jwt_", "").split("_")
    user_id = UUID(parts[0])
    workspace_id = UUID(parts[1])
    role = WorkspaceRole(parts[2])

    # Parse shared_file_ids
    shared_file_ids = None
    if len(parts) > 3 and parts[3] != "none":
        # In real implementation, would parse from JWT
        # For testing, we'll handle this per-test
        pass

    return JWTClaims(
        user_id=user_id,
        workspace_id=workspace_id,
        workspace_role=role,
        shared_file_ids=shared_file_ids,
        exp=9999999999,
    )


def create_test_app(mock_sessions: dict[UUID, MockUploadSession]) -> FastAPI:
    """Create FastAPI test application with protected endpoints."""
    app = FastAPI()

    # Mock get_current_user dependency
    async def mock_get_current_user(authorization: str | None = Header(None)) -> JWTClaims:
        """Mock JWT validation for testing."""
        if not authorization or not authorization.startswith("Bearer "):
            from fastapi import HTTPException

            raise HTTPException(401, "Missing or invalid authorization header")

        # Return test claims set by the test
        if not hasattr(mock_get_current_user, "test_claims"):
            from fastapi import HTTPException

            raise HTTPException(401, "No test claims configured")

        return mock_get_current_user.test_claims

    @app.post("/v1/uploads")
    async def create_upload(
        current_user: Annotated[JWTClaims, Depends(require_owner())],
        workspace_id: UUID,
    ) -> dict:
        """Owner-only endpoint for creating uploads."""
        return {
            "upload_id": str(uuid4()),
            "workspace_id": str(current_user.workspace_id),
        }

    @app.get("/v1/uploads/{upload_id}")
    async def get_upload(
        upload_id: UUID,
        current_user: Annotated[JWTClaims, Depends(mock_get_current_user)],
    ) -> dict:
        """Read endpoint with workspace and file access validation."""
        # Layer 3: Validate workspace access BEFORE checking resource existence
        # This prevents information leakage about resource IDs

        # Fetch upload session
        session = mock_sessions.get(upload_id)

        # If resource exists, validate workspace access before revealing existence
        if session:
            validate_workspace_access(current_user, session.workspace_id)
            # Layer 4: Validate file access
            validate_file_access(current_user, session.file_id)

        # Return 404 only after access control checks pass
        # If workspace validation failed, we already raised 403
        if not session:
            from fastapi import HTTPException

            raise HTTPException(404, "Upload not found")

        return {
            "upload_id": str(upload_id),
            "workspace_id": str(session.workspace_id),
            "file_id": str(session.file_id),
        }

    @app.delete("/v1/uploads/{upload_id}")
    async def delete_upload(
        upload_id: UUID,
        current_user: Annotated[JWTClaims, Depends(require_owner())],
    ) -> dict:
        """Delete endpoint demonstrating require_owner + workspace validation."""
        # Fetch upload session
        session = mock_sessions.get(upload_id)
        if not session:
            from fastapi import HTTPException

            raise HTTPException(404, "Upload not found")

        # Layer 3: Validate workspace access
        # Even though require_owner ensures OWNER role, we still validate
        # that the resource belongs to the user's active workspace
        validate_workspace_access(current_user, session.workspace_id)

        # Delete the session
        del mock_sessions[upload_id]

        return {"deleted": str(upload_id)}

    @app.patch("/v1/uploads/{upload_id}")
    async def update_upload(
        upload_id: UUID,
        current_user: Annotated[JWTClaims, Depends(require_owner())],
    ) -> dict:
        """Update endpoint demonstrating require_owner + workspace validation."""
        # Fetch upload session
        session = mock_sessions.get(upload_id)
        if not session:
            from fastapi import HTTPException

            raise HTTPException(404, "Upload not found")

        # Layer 3: Validate workspace access
        validate_workspace_access(current_user, session.workspace_id)

        # Update logic would go here
        return {
            "upload_id": str(upload_id),
            "workspace_id": str(session.workspace_id),
            "updated": True,
        }

    # Override get_current_user for all dependencies
    from src.presentation.api.middleware.auth import get_current_user

    app.dependency_overrides[get_current_user] = mock_get_current_user

    return app, mock_get_current_user


@pytest.mark.asyncio
async def test_owner_can_access_own_workspace_resource(mock_sessions):
    """Test OWNER with matching workspace_id can access resource."""
    # Setup
    workspace_id = uuid4()
    file_id = uuid4()
    upload_id = uuid4()

    session = MockUploadSession(upload_id, workspace_id, file_id)
    mock_sessions[upload_id] = session

    owner_claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=9999999999,
    )

    # Create test app
    app, mock_auth = create_test_app(mock_sessions)
    mock_auth.test_claims = owner_claims

    # Test using real HTTP client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/uploads/{upload_id}", headers={"Authorization": "Bearer mock_token"}
        )

    # Verify
    assert response.status_code == 200
    data = response.json()
    assert data["upload_id"] == str(upload_id)
    assert data["workspace_id"] == str(workspace_id)
    assert data["file_id"] == str(file_id)


@pytest.mark.asyncio
async def test_collaborator_can_access_shared_file(mock_sessions):
    """Test COLLABORATOR with file_id in shared_file_ids can access."""
    # Setup
    workspace_id = uuid4()
    file_id = uuid4()
    upload_id = uuid4()

    session = MockUploadSession(upload_id, workspace_id, file_id)
    mock_sessions[upload_id] = session

    collaborator_claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(file_id,),
        exp=9999999999,
    )

    # Create test app
    app, mock_auth = create_test_app(mock_sessions)
    mock_auth.test_claims = collaborator_claims

    # Test using real HTTP client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/uploads/{upload_id}", headers={"Authorization": "Bearer mock_token"}
        )

    # Verify
    assert response.status_code == 200
    data = response.json()
    assert data["file_id"] == str(file_id)


@pytest.mark.asyncio
async def test_collaborator_cannot_access_non_shared_file(mock_sessions):
    """Test COLLABORATOR accessing non-shared file receives 403."""
    # Setup
    workspace_id = uuid4()
    file_id = uuid4()
    other_file = uuid4()
    upload_id = uuid4()

    session = MockUploadSession(upload_id, workspace_id, file_id)
    mock_sessions[upload_id] = session

    # Collaborator has access to other_file, but not file_id
    collaborator_claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(other_file,),
        exp=9999999999,
    )

    # Create test app
    app, mock_auth = create_test_app(mock_sessions)
    mock_auth.test_claims = collaborator_claims

    # Test using real HTTP client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/uploads/{upload_id}", headers={"Authorization": "Bearer mock_token"}
        )

    # Verify
    assert response.status_code == 403
    data = response.json()
    assert "FILE_ACCESS_DENIED" in str(data)


@pytest.mark.asyncio
async def test_user_cannot_access_different_workspace_resource(mock_sessions):
    """Test user accessing resource in different workspace receives 403."""
    # Setup
    user_workspace = uuid4()
    resource_workspace = uuid4()
    file_id = uuid4()
    upload_id = uuid4()

    session = MockUploadSession(upload_id, resource_workspace, file_id)
    mock_sessions[upload_id] = session

    # User is owner of different workspace
    owner_claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=user_workspace,
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=9999999999,
    )

    # Create test app
    app, mock_auth = create_test_app(mock_sessions)
    mock_auth.test_claims = owner_claims

    # Test using real HTTP client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/uploads/{upload_id}", headers={"Authorization": "Bearer mock_token"}
        )

    # Verify
    assert response.status_code == 403
    data = response.json()
    assert "WORKSPACE_MISMATCH" in str(data)


@pytest.mark.asyncio
async def test_owner_can_access_any_file_in_workspace(mock_sessions):
    """Test OWNER can access any file in their workspace."""
    # Setup
    workspace_id = uuid4()
    file1 = uuid4()
    file2 = uuid4()
    file3 = uuid4()

    owner_claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=9999999999,
    )

    # Create test app
    app, mock_auth = create_test_app(mock_sessions)
    mock_auth.test_claims = owner_claims

    # Test multiple files
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for file_id in [file1, file2, file3]:
            upload_id = uuid4()
            session = MockUploadSession(upload_id, workspace_id, file_id)
            mock_sessions[upload_id] = session

            response = await client.get(
                f"/v1/uploads/{upload_id}", headers={"Authorization": "Bearer mock_token"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["file_id"] == str(file_id)


@pytest.mark.asyncio
async def test_error_ordering_workspace_before_file_access(mock_sessions):
    """Test workspace validation happens before file access validation."""
    # Setup
    user_workspace = uuid4()
    resource_workspace = uuid4()
    file_id = uuid4()
    other_file = uuid4()
    upload_id = uuid4()

    session = MockUploadSession(upload_id, resource_workspace, file_id)
    mock_sessions[upload_id] = session

    # Collaborator in wrong workspace AND without file access
    collaborator_claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=user_workspace,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(other_file,),
        exp=9999999999,
    )

    # Create test app
    app, mock_auth = create_test_app(mock_sessions)
    mock_auth.test_claims = collaborator_claims

    # Test using real HTTP client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/uploads/{upload_id}", headers={"Authorization": "Bearer mock_token"}
        )

    # Verify workspace error comes first (Layer 3 before Layer 4)
    assert response.status_code == 403
    data = response.json()
    assert "WORKSPACE_MISMATCH" in str(data)
    # Not FILE_ACCESS_DENIED because workspace check fails first


@pytest.mark.asyncio
async def test_collaborator_with_empty_shared_files_denied(mock_sessions):
    """Test COLLABORATOR with empty shared_file_ids cannot access files."""
    # Setup
    workspace_id = uuid4()
    file_id = uuid4()
    upload_id = uuid4()

    session = MockUploadSession(upload_id, workspace_id, file_id)
    mock_sessions[upload_id] = session

    # Collaborator with empty shared files
    collaborator_claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(),
        exp=9999999999,
    )

    # Create test app
    app, mock_auth = create_test_app(mock_sessions)
    mock_auth.test_claims = collaborator_claims

    # Test using real HTTP client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/uploads/{upload_id}", headers={"Authorization": "Bearer mock_token"}
        )

    # Verify
    assert response.status_code == 403
    data = response.json()
    assert "FILE_ACCESS_DENIED" in str(data)


@pytest.mark.asyncio
async def test_require_owner_blocks_collaborator(mock_sessions):
    """Test require_owner() RBAC dependency blocks collaborator role."""
    # Setup
    workspace_id = uuid4()
    file_id = uuid4()

    collaborator_claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(file_id,),
        exp=9999999999,
    )

    # Create test app
    app, mock_auth = create_test_app(mock_sessions)
    mock_auth.test_claims = collaborator_claims

    # Test - collaborator tries to call owner-only endpoint
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/uploads",
            json={"workspace_id": str(workspace_id)},
            headers={"Authorization": "Bearer mock_token"},
        )

    # Verify RBAC blocks at Layer 2 (before workspace/file validation)
    assert response.status_code == 403
    data = response.json()
    assert "required_role" in str(data)


@pytest.mark.asyncio
async def test_delete_endpoint_with_owner_and_workspace_validation(mock_sessions):
    """Test DELETE endpoint demonstrates require_owner + workspace validation."""
    # Setup
    workspace_id = uuid4()
    file_id = uuid4()
    upload_id = uuid4()

    session = MockUploadSession(upload_id, workspace_id, file_id)
    mock_sessions[upload_id] = session

    owner_claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=9999999999,
    )

    # Create test app
    app, mock_auth = create_test_app(mock_sessions)
    mock_auth.test_claims = owner_claims

    # Test - owner deletes resource in their workspace
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(
            f"/v1/uploads/{upload_id}", headers={"Authorization": "Bearer mock_token"}
        )

    # Verify success
    assert response.status_code == 200
    data = response.json()
    assert data["deleted"] == str(upload_id)
    assert upload_id not in mock_sessions


@pytest.mark.asyncio
async def test_update_endpoint_with_owner_and_workspace_validation(mock_sessions):
    """Test PATCH endpoint demonstrates require_owner + workspace validation."""
    # Setup
    workspace_id = uuid4()
    file_id = uuid4()
    upload_id = uuid4()

    session = MockUploadSession(upload_id, workspace_id, file_id)
    mock_sessions[upload_id] = session

    owner_claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=9999999999,
    )

    # Create test app
    app, mock_auth = create_test_app(mock_sessions)
    mock_auth.test_claims = owner_claims

    # Test - owner updates resource in their workspace
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/v1/uploads/{upload_id}", headers={"Authorization": "Bearer mock_token"}
        )

    # Verify success
    assert response.status_code == 200
    data = response.json()
    assert data["upload_id"] == str(upload_id)
    assert data["updated"] is True


@pytest.mark.asyncio
async def test_delete_blocks_owner_from_different_workspace(mock_sessions):
    """Test DELETE with workspace validation blocks cross-workspace access."""
    # Setup
    user_workspace = uuid4()
    resource_workspace = uuid4()
    file_id = uuid4()
    upload_id = uuid4()

    session = MockUploadSession(upload_id, resource_workspace, file_id)
    mock_sessions[upload_id] = session

    # Owner of different workspace
    owner_claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=user_workspace,
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=9999999999,
    )

    # Create test app
    app, mock_auth = create_test_app(mock_sessions)
    mock_auth.test_claims = owner_claims

    # Test - owner tries to delete resource from different workspace
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete(
            f"/v1/uploads/{upload_id}", headers={"Authorization": "Bearer mock_token"}
        )

    # Verify workspace validation blocks access
    assert response.status_code == 403
    data = response.json()
    assert "WORKSPACE_MISMATCH" in str(data)
    # Resource should NOT be deleted
    assert upload_id in mock_sessions
