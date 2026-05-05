"""Unit tests for uploads router POST /v1/uploads endpoint.

This module tests the initiate_upload endpoint with mocked dependencies,
verifying request/response handling, error cases, and integration with
authentication and authorization.

Test Coverage:
    - Happy path: Valid request returns 201 with correct response schema
    - JWT validation: Missing/invalid JWT returns 401
    - RBAC enforcement: COLLABORATOR role returns 403
    - Rate limiting: Rate limit exceeded returns 429 with details
    - File size validation: File > 1 GB returns 413
    - MIME type validation: Non-PDF returns 415
    - Pydantic validation: Invalid request body returns 422
    - Infrastructure errors: Redis failure returns 503
    - camelCase conversion: Request/response use camelCase JSON fields

Integration Points:
    - Story 3.4: Mocks InitiateUploadUseCase
    - Story 2.2: Tests JWT authentication dependency
    - Story 2.4: Tests RBAC authorization dependency
    - Story 3.1: Tests response schema with UploadSession data

Architecture:
    - Fast unit tests with no external dependencies
    - Mocks all use cases and infrastructure
    - TestClient for HTTP testing without network
    - Fixtures for reusable test data
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.dto.upload_response import InitiateUploadResponse as InitiateUploadResponseDTO
from src.application.use_cases.initiate_upload import InitiateUploadUseCase
from src.domain.exceptions import (
    FileSizeLimitExceededError,
    InfrastructureError,
    RateLimitExceededError,
    UnsupportedMediaTypeError,
)
from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.workspace_role import WorkspaceRole
from src.presentation.api.v1.routers import uploads


# Test Fixtures


@pytest.fixture
def mock_use_case() -> AsyncMock:
    """Create mock InitiateUploadUseCase for testing."""
    return AsyncMock(spec=InitiateUploadUseCase)


@pytest.fixture
def mock_current_user_owner() -> JWTClaims:
    """Create mock authenticated OWNER user."""
    return JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    )


@pytest.fixture
def mock_current_user_collaborator() -> JWTClaims:
    """Create mock authenticated COLLABORATOR user."""
    return JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.COLLABORATOR,
        shared_file_ids=(uuid4(),),
        exp=int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    )


@pytest.fixture
def valid_request_body() -> dict[str, Any]:
    """Create valid request body with camelCase fields."""
    return {
        "filename": "document.pdf",
        "size": 1048576,  # 1 MB
        "mimeType": "application/pdf",
        "sha256Checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }


@pytest.fixture
def app(mock_use_case: AsyncMock, mock_current_user_owner: JWTClaims) -> FastAPI:
    """Create FastAPI test app with mocked dependencies."""
    test_app = FastAPI()
    test_app.include_router(uploads.router)

    # Override dependencies with mocks
    async def override_get_use_case() -> InitiateUploadUseCase:
        return mock_use_case

    # Mock Redis client to avoid settings requirement
    def override_get_redis_client() -> MagicMock:
        return MagicMock()

    # Mock require_role to return the mock user
    from src.domain.value_objects.workspace_role import WorkspaceRole
    from src.infrastructure.auth.rbac_middleware import require_role
    from src.presentation.api.middleware.auth import get_current_user

    async def override_require_role() -> JWTClaims:
        return mock_current_user_owner

    async def override_get_current_user() -> JWTClaims:
        return mock_current_user_owner

    # Override all dependencies to avoid real Redis/settings/auth
    test_app.dependency_overrides[uploads.get_initiate_upload_use_case] = override_get_use_case
    test_app.dependency_overrides[uploads.get_redis_client] = override_get_redis_client
    test_app.dependency_overrides[require_role(WorkspaceRole.OWNER)] = override_require_role
    test_app.dependency_overrides[get_current_user] = override_get_current_user

    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create FastAPI test client."""
    return TestClient(app)


# Happy Path Tests


def test_initiate_upload_success(
    client: TestClient,
    mock_use_case: AsyncMock,
    mock_current_user_owner: JWTClaims,
    valid_request_body: dict[str, Any],
) -> None:
    """Test happy path: valid request returns 201 with correct response.

    Validates:
        - 201 Created status code
        - Response contains uploadId (camelCase), offset, expiresAt
        - Use case executed with correct DTO
        - workspace_id extracted from JWT claims
    """
    # Mock use case response
    session_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=24)
    mock_use_case.execute.return_value = InitiateUploadResponseDTO(
        session_id=session_id,
        offset=0,
        expires_at=expires_at,
    )

    # Make request
    response = client.post(
        "/v1/uploads",
        json=valid_request_body,
        headers={"Authorization": "Bearer valid-token"},
    )

    # Assertions
    assert response.status_code == 201
    response_data = response.json()
    assert "uploadId" in response_data  # camelCase
    assert "offset" in response_data
    assert "expiresAt" in response_data
    assert response_data["offset"] == 0
    assert UUID(response_data["uploadId"]) == session_id
    assert "upload_id" not in response_data  # snake_case not present
    mock_use_case.execute.assert_called_once()


def test_initiate_upload_camelcase_conversion(
    client: TestClient,
    mock_use_case: AsyncMock,
    valid_request_body: dict[str, Any],
) -> None:
    """Test camelCase conversion in request/response.

    Validates:
        - Request accepts camelCase fields (mimeType, sha256Checksum)
        - Response uses camelCase fields (uploadId, expiresAt)
        - Internal Python code uses snake_case
    """
    # Mock use case response
    session_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=24)
    mock_use_case.execute.return_value = InitiateUploadResponseDTO(
        session_id=session_id,
        offset=0,
        expires_at=expires_at,
    )

    # Make request with camelCase
    response = client.post(
        "/v1/uploads",
        json=valid_request_body,
        headers={"Authorization": "Bearer valid-token"},
    )

    # Verify response uses camelCase
    assert response.status_code == 201
    response_data = response.json()
    assert "uploadId" in response_data
    assert "expiresAt" in response_data
    assert "upload_id" not in response_data
    assert "expires_at" not in response_data


# Authentication Tests


def test_initiate_upload_missing_authorization_header(
    client: TestClient,
    valid_request_body: dict[str, Any],
) -> None:
    """Test missing Authorization header returns 401.

    Validates:
        - 401 Unauthorized status code
        - Error message indicates missing header
    """
    # Create app without auth override (will require real auth)
    test_app = FastAPI()
    test_app.include_router(uploads.router)
    test_client = TestClient(test_app)

    # Make request without Authorization header
    response = test_client.post("/v1/uploads", json=valid_request_body)

    # Assertions
    assert response.status_code == 401


# Authorization Tests


def test_initiate_upload_collaborator_forbidden(
    mock_use_case: AsyncMock,
    mock_current_user_collaborator: JWTClaims,
    valid_request_body: dict[str, Any],
) -> None:
    """Test COLLABORATOR role returns 403 Forbidden.

    Validates:
        - 403 Forbidden status code
        - Error message indicates OWNER role required
        - Use case not executed (failed at RBAC check)
    """
    # Create app with COLLABORATOR user
    test_app = FastAPI()
    test_app.include_router(uploads.router)

    from src.domain.value_objects.workspace_role import WorkspaceRole
    from src.infrastructure.auth.rbac_middleware import require_role
    from src.presentation.api.middleware.auth import get_current_user

    async def override_require_role_owner() -> JWTClaims:
        # Simulate RBAC middleware behavior for COLLABORATOR
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail={"detail": "Insufficient permissions - owner role required"},
        )

    async def override_get_current_user() -> JWTClaims:
        return mock_current_user_collaborator

    def override_get_redis_client() -> MagicMock:
        return MagicMock()

    test_app.dependency_overrides[require_role(WorkspaceRole.OWNER)] = override_require_role_owner
    test_app.dependency_overrides[get_current_user] = override_get_current_user
    test_app.dependency_overrides[uploads.get_redis_client] = override_get_redis_client
    test_app.dependency_overrides[uploads.get_initiate_upload_use_case] = lambda: mock_use_case

    test_client = TestClient(test_app)

    # Make request
    response = test_client.post(
        "/v1/uploads",
        json=valid_request_body,
        headers={"Authorization": "Bearer collaborator-token"},
    )

    # Assertions
    assert response.status_code == 403
    mock_use_case.execute.assert_not_called()


# Rate Limiting Tests


def test_initiate_upload_rate_limit_exceeded(
    client: TestClient,
    mock_use_case: AsyncMock,
    valid_request_body: dict[str, Any],
) -> None:
    """Test rate limit exceeded returns 429 with details.

    Validates:
        - 429 Too Many Requests status code
        - Response includes current_uploads, limit, retry_after_seconds
        - Retry-After header present
        - Error response follows standard format
    """
    # Mock use case to raise RateLimitExceededError
    workspace_id = uuid4()
    mock_use_case.execute.side_effect = RateLimitExceededError(
        workspace_id=str(workspace_id),
        current_count=10,
        limit=10,
        retry_after_seconds=60,
    )

    # Make request
    response = client.post(
        "/v1/uploads",
        json=valid_request_body,
        headers={"Authorization": "Bearer valid-token"},
    )

    # Assertions
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert response.headers["Retry-After"] == "60"

    response_data = response.json()
    assert "error" in response_data["detail"]
    assert response_data["detail"]["error"] == "RATE_LIMIT_EXCEEDED"
    assert "details" in response_data["detail"]
    assert response_data["detail"]["details"]["current_uploads"] == 10
    assert response_data["detail"]["details"]["limit"] == 10
    assert response_data["detail"]["details"]["retry_after_seconds"] == 60


# Validation Tests


def test_initiate_upload_file_size_exceeded(
    client: TestClient,
    mock_use_case: AsyncMock,
    valid_request_body: dict[str, Any],
) -> None:
    """Test file size > 1 GB returns 413 Payload Too Large.

    Validates:
        - 413 Request Entity Too Large status code
        - Response includes file_size and max_size
        - Error response follows standard format
    """
    # Mock use case to raise FileSizeLimitExceededError
    mock_use_case.execute.side_effect = FileSizeLimitExceededError(
        file_size=1073741825,  # 1 GB + 1 byte
        max_size=1073741824,  # 1 GB
    )

    # Make request
    response = client.post(
        "/v1/uploads",
        json=valid_request_body,
        headers={"Authorization": "Bearer valid-token"},
    )

    # Assertions
    assert response.status_code == 413
    response_data = response.json()
    assert response_data["detail"]["error"] == "FILE_SIZE_LIMIT_EXCEEDED"
    assert response_data["detail"]["details"]["file_size"] == 1073741825
    assert response_data["detail"]["details"]["max_size"] == 1073741824


def test_initiate_upload_unsupported_media_type(
    client: TestClient,
    mock_use_case: AsyncMock,
    valid_request_body: dict[str, Any],
) -> None:
    """Test unsupported MIME type returns 415 Unsupported Media Type.

    Validates:
        - 415 Unsupported Media Type status code
        - Response includes provided_mime_type and allowed_mime_types
        - Error response follows standard format
    """
    # Mock use case to raise UnsupportedMediaTypeError
    mock_use_case.execute.side_effect = UnsupportedMediaTypeError(
        provided_mime_type="application/msword",
        allowed_mime_types=["application/pdf"],
    )

    # Make request
    response = client.post(
        "/v1/uploads",
        json=valid_request_body,
        headers={"Authorization": "Bearer valid-token"},
    )

    # Assertions
    assert response.status_code == 415
    response_data = response.json()
    assert response_data["detail"]["error"] == "UNSUPPORTED_MEDIA_TYPE"
    assert response_data["detail"]["details"]["provided_mime_type"] == "application/msword"
    assert response_data["detail"]["details"]["allowed_mime_types"] == ["application/pdf"]


def test_initiate_upload_invalid_filename_too_long(
    client: TestClient,
    valid_request_body: dict[str, Any],
) -> None:
    """Test filename > 255 characters returns 422 Unprocessable Entity.

    Validates:
        - 422 Unprocessable Entity status code
        - Pydantic validation error in response
    """
    # Request with filename > 255 characters
    invalid_request = {**valid_request_body, "filename": "a" * 256}

    # Make request
    response = client.post(
        "/v1/uploads",
        json=invalid_request,
        headers={"Authorization": "Bearer valid-token"},
    )

    # Assertions
    assert response.status_code == 422
    response_data = response.json()
    assert "detail" in response_data


def test_initiate_upload_invalid_size_negative(
    client: TestClient,
    valid_request_body: dict[str, Any],
) -> None:
    """Test negative file size returns 422 Unprocessable Entity.

    Validates:
        - 422 Unprocessable Entity status code
        - Pydantic validation error for size field
    """
    # Request with negative size
    invalid_request = {**valid_request_body, "size": -1}

    # Make request
    response = client.post(
        "/v1/uploads",
        json=invalid_request,
        headers={"Authorization": "Bearer valid-token"},
    )

    # Assertions
    assert response.status_code == 422
    response_data = response.json()
    assert "detail" in response_data


def test_initiate_upload_invalid_size_exceeds_limit(
    client: TestClient,
    valid_request_body: dict[str, Any],
) -> None:
    """Test file size > 1 GB in Pydantic validation returns 422.

    Validates:
        - 422 Unprocessable Entity status code (caught by Pydantic before use case)
        - Validation error for size field
    """
    # Request with size > 1 GB
    invalid_request = {**valid_request_body, "size": 1073741825}  # 1 GB + 1 byte

    # Make request
    response = client.post(
        "/v1/uploads",
        json=invalid_request,
        headers={"Authorization": "Bearer valid-token"},
    )

    # Assertions
    assert response.status_code == 422
    response_data = response.json()
    assert "detail" in response_data


def test_initiate_upload_invalid_mime_type(
    client: TestClient,
    valid_request_body: dict[str, Any],
) -> None:
    """Test invalid MIME type returns 422 Unprocessable Entity.

    Validates:
        - 422 Unprocessable Entity status code
        - Pydantic validation error for mime_type field
    """
    # Request with invalid MIME type
    invalid_request = {**valid_request_body, "mimeType": "application/msword"}

    # Make request
    response = client.post(
        "/v1/uploads",
        json=invalid_request,
        headers={"Authorization": "Bearer valid-token"},
    )

    # Assertions
    assert response.status_code == 422
    response_data = response.json()
    assert "detail" in response_data


def test_initiate_upload_invalid_checksum_format(
    client: TestClient,
    valid_request_body: dict[str, Any],
) -> None:
    """Test invalid SHA-256 checksum format returns 422.

    Validates:
        - 422 Unprocessable Entity status code
        - Pydantic validation error for sha256_checksum field
    """
    # Request with invalid checksum (not 64 hex chars)
    invalid_request = {**valid_request_body, "sha256Checksum": "INVALID"}

    # Make request
    response = client.post(
        "/v1/uploads",
        json=invalid_request,
        headers={"Authorization": "Bearer valid-token"},
    )

    # Assertions
    assert response.status_code == 422
    response_data = response.json()
    assert "detail" in response_data


def test_initiate_upload_missing_required_fields(
    client: TestClient,
) -> None:
    """Test missing required fields returns 422 Unprocessable Entity.

    Validates:
        - 422 Unprocessable Entity status code
        - Validation errors for missing fields
    """
    # Request with missing fields
    invalid_request = {"filename": "document.pdf"}

    # Make request
    response = client.post(
        "/v1/uploads",
        json=invalid_request,
        headers={"Authorization": "Bearer valid-token"},
    )

    # Assertions
    assert response.status_code == 422
    response_data = response.json()
    assert "detail" in response_data


# Infrastructure Error Tests


def test_initiate_upload_infrastructure_error(
    client: TestClient,
    mock_use_case: AsyncMock,
    valid_request_body: dict[str, Any],
) -> None:
    """Test infrastructure failure returns 503 Service Unavailable.

    Validates:
        - 503 Service Unavailable status code
        - Response includes retry guidance
        - Error response follows standard format
    """
    # Mock use case to raise InfrastructureError
    mock_use_case.execute.side_effect = InfrastructureError("Redis connection timeout")

    # Make request
    response = client.post(
        "/v1/uploads",
        json=valid_request_body,
        headers={"Authorization": "Bearer valid-token"},
    )

    # Assertions
    assert response.status_code == 503
    response_data = response.json()
    assert response_data["detail"]["error"] == "INFRASTRUCTURE_ERROR"
    assert "retry_guidance" in response_data["detail"]["details"]


# Edge Case Tests


def test_initiate_upload_workspace_id_from_jwt_claims(
    client: TestClient,
    mock_use_case: AsyncMock,
    mock_current_user_owner: JWTClaims,
    valid_request_body: dict[str, Any],
) -> None:
    """Test workspace_id extracted from JWT claims.

    Validates:
        - workspace_id passed to use case matches JWT claims
        - workspace_id NOT in request body (security)
    """
    # Mock use case response
    session_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=24)
    mock_use_case.execute.return_value = InitiateUploadResponseDTO(
        session_id=session_id,
        offset=0,
        expires_at=expires_at,
    )

    # Make request (no workspace_id in body)
    response = client.post(
        "/v1/uploads",
        json=valid_request_body,
        headers={"Authorization": "Bearer valid-token"},
    )

    # Verify use case called with workspace_id from JWT
    assert response.status_code == 201
    mock_use_case.execute.assert_called_once()
    call_args = mock_use_case.execute.call_args[0][0]
    assert call_args.workspace_id == mock_current_user_owner.workspace_id


def test_initiate_upload_response_iso8601_datetime(
    client: TestClient,
    mock_use_case: AsyncMock,
    valid_request_body: dict[str, Any],
) -> None:
    """Test expiresAt is ISO 8601 format with Z suffix.

    Validates:
        - expiresAt is ISO 8601 string
        - Timezone indicator is Z (UTC)
        - Format: YYYY-MM-DDTHH:MM:SS.ffffffZ
    """
    # Mock use case response
    session_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=24)
    mock_use_case.execute.return_value = InitiateUploadResponseDTO(
        session_id=session_id,
        offset=0,
        expires_at=expires_at,
    )

    # Make request
    response = client.post(
        "/v1/uploads",
        json=valid_request_body,
        headers={"Authorization": "Bearer valid-token"},
    )

    # Verify datetime format
    assert response.status_code == 201
    response_data = response.json()
    expires_at_str = response_data["expiresAt"]
    assert expires_at_str.endswith("Z")
    assert "T" in expires_at_str
    # Verify parseable as ISO 8601
    datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
