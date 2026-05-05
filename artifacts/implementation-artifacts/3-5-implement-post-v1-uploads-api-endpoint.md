# Story 3.5: Implement POST /v1/uploads API Endpoint

Status: done

## Story

As a **workspace owner**,
I want **a REST API endpoint to initiate upload sessions**,
So that **I can start uploading files via HTTP**.

## Acceptance Criteria

1. **Given** use case exists
   **When** API endpoint is implemented
   **Then** src/presentation/api/v1/routers/uploads.py contains POST /v1/uploads endpoint

2. **And** src/presentation/api/v1/schemas/upload_schemas.py defines InitiateUploadRequest with fields: filename, size, mime_type, sha256_checksum

3. **And** response schema includes: uploadId (camelCase), offset, expiresAt (ISO 8601)

4. **And** endpoint requires valid JWT (401 if missing/invalid)

5. **And** endpoint requires workspace_role == OWNER (403 for collaborators)

6. **And** endpoint injects workspace_id from JWT claims

7. **And** 429 response includes current active upload count in details

8. **And** error responses follow standard format with error code, message, details

9. **And** endpoint is documented in OpenAPI spec

## Tasks / Subtasks

- [x] Create Pydantic Request/Response Schemas (AC: #2, #3)
  - [x] Review architecture.md for Pydantic patterns with camelCase conversion
  - [x] Review Epic 3 requirements for data structure
  - [x] Create src/presentation/api/v1/schemas/upload_schemas.py
  - [x] Define BaseAPISchema base class with ConfigDict:
    - alias_generator=to_camel (converts snake_case to camelCase)
    - populate_by_name=True (allows both formats)
    - Example: upload_id field → "uploadId" in JSON
  - [x] Define InitiateUploadRequest schema (Pydantic BaseModel):
    - filename: str (original filename for display)
    - size: int (file size in bytes, must be > 0 and ≤ 1GB)
    - mime_type: str (must be "application/pdf")
    - sha256_checksum: str (64-char hex string, full file checksum for deduplication)
    - Add Field validators for each field with clear error messages
  - [x] Define InitiateUploadResponse schema:
    - upload_id: UUID (session identifier, becomes "uploadId" in JSON)
    - offset: int (always 0 for new session)
    - expires_at: datetime (24 hours from creation, ISO 8601 UTC, becomes "expiresAt" in JSON)
    - Add ConfigDict with json_encoders for datetime → ISO 8601 with Z suffix
  - [x] Add comprehensive docstrings with examples
  - [x] Add type hints throughout

- [x] Create FastAPI Router with POST /v1/uploads endpoint (AC: #1, #4, #5, #6)
  - [x] Review main.py to understand existing FastAPI app structure
  - [x] Review auth middleware patterns (get_current_user, require_role)
  - [x] Create src/presentation/api/v1/routers/uploads.py
  - [x] Import required dependencies:
    - FastAPI router, APIRouter, HTTPException
    - Depends for dependency injection
    - JWTClaims from domain.value_objects
    - WorkspaceRole from domain.value_objects
    - get_current_user, require_role from auth middleware
    - InitiateUploadUseCase from application.use_cases
    - InitiateUploadRequest, InitiateUploadResponse from schemas
    - InitiateUploadRequest (DTO), InitiateUploadResponse (DTO) from application.dto
  - [x] Create APIRouter instance with prefix="/v1" and tags=["uploads"]
  - [x] Implement POST /v1/uploads endpoint:
    - Path: ""  (full path will be /v1/uploads after router inclusion)
    - Dependency: current_user via require_role(WorkspaceRole.OWNER) (AC: #4, #5)
    - Request body: InitiateUploadRequest (Pydantic schema)
    - Response: InitiateUploadResponse (Pydantic schema)
    - Status code: 201 Created (indicates new resource created)
  - [x] Map Pydantic schema to DTO:
    - Extract workspace_id from current_user.workspace_id (AC: #6)
    - Create InitiateUploadRequest DTO with workspace_id + schema fields
  - [x] Call use case and handle response:
    - Instantiate InitiateUploadUseCase with injected dependencies
    - Execute use_case.execute(dto_request)
    - Map DTO response to Pydantic response schema
    - Return response with 201 status
  - [x] Add comprehensive docstring with OpenAPI metadata:
    - Summary: "Initiate chunked upload session"
    - Description: "Creates new upload session for workspace owner. Returns session ID and expiry timestamp for resumable chunked upload."
    - Response examples: Success 201, Error 401/403/413/415/429
  - [x] Add type hints throughout

- [x] Implement Error Response Handling (AC: #7, #8)
  - [x] Review architecture.md for error response structure
  - [x] Create error response handler for domain exceptions:
    - RateLimitExceededError → 429 Too Many Requests with Retry-After header
    - FileSizeLimitExceededError → 413 Payload Too Large
    - UnsupportedMediaTypeError → 415 Unsupported Media Type
    - InfrastructureError → 503 Service Unavailable
    - AuthenticationError → 401 Unauthorized (already handled by middleware)
  - [x] Add error response with structured details (AC: #7):
    - For 429: Include current active upload count, retry_after_seconds, limit
    - For 413: Include max_file_size, received_size
    - For 415: Include allowed_mime_types, received_mime_type
    - For 503: Include retry guidance message
  - [x] Add try/except block in endpoint to catch and transform domain exceptions
  - [x] Ensure all error responses follow standard format (AC: #8):
    - error: ERROR_CODE (uppercase snake case)
    - message: Human-readable description
    - details: Additional context dictionary
    - request_id: Optional request correlation ID

- [x] Integrate Router into Main Application (AC: #9)
  - [x] Open src/presentation/main.py
  - [x] Import uploads router
  - [x] Include router in app: app.include_router(uploads.router)
  - [x] Verify OpenAPI spec generation includes new endpoint
  - [x] Test /docs endpoint shows POST /v1/uploads with correct schemas

- [x] Create Dependency Injection Setup
  - [x] Review existing dependency injection patterns in the codebase
  - [x] Create dependency provider for InitiateUploadUseCase:
    - Function that instantiates use case with injected dependencies
    - Dependencies: IRateLimiter, ISessionStore (from infrastructure implementations)
  - [x] Add dependency to router endpoint via Depends()
  - [x] Ensure dependencies are singletons for performance (use lru_cache or FastAPI Depends caching)

- [x] Create Comprehensive Unit Tests (AC: #1-#9)
  - [x] Create tests/unit/presentation/api/v1/routers/test_uploads.py
  - [x] Setup test fixtures:
    - mock_use_case: Mock InitiateUploadUseCase
    - mock_current_user: JWTClaims with OWNER role
    - test_client: FastAPI TestClient with router
    - valid_request: InitiateUploadRequest with valid data
  - [x] Test happy path (AC: #1, #2, #3, #6):
    - POST /v1/uploads with valid request body
    - Verify 201 Created status
    - Verify response contains uploadId (camelCase), offset (0), expiresAt (ISO 8601)
    - Verify use_case.execute called with correct DTO
    - Verify workspace_id extracted from JWT claims
  - [x] Test JWT validation (AC: #4):
    - POST without Authorization header → 401 Unauthorized
    - POST with invalid JWT → 401 Unauthorized
    - POST with expired JWT → 401 Unauthorized
  - [x] Test RBAC enforcement (AC: #5):
    - POST with COLLABORATOR role → 403 Forbidden
    - Verify error message indicates OWNER role required
  - [x] Test validation errors:
    - Invalid filename → 422 Unprocessable Entity
    - Invalid size (0 or negative) → 422 Unprocessable Entity
    - Invalid mime_type → 422 Unprocessable Entity
    - Invalid sha256_checksum (not 64 hex chars) → 422 Unprocessable Entity
  - [x] Test rate limit exceeded (AC: #7):
    - Mock use_case to raise RateLimitExceededError
    - Verify 429 Too Many Requests
    - Verify response includes current active upload count, retry_after, limit
  - [x] Test file size limit exceeded:
    - Mock use_case to raise FileSizeLimitExceededError
    - Verify 413 Payload Too Large
    - Verify error message includes max size and received size
  - [x] Test unsupported MIME type:
    - Mock use_case to raise UnsupportedMediaTypeError
    - Verify 415 Unsupported Media Type
    - Verify error message includes allowed types
  - [x] Test infrastructure failure:
    - Mock use_case to raise InfrastructureError
    - Verify 503 Service Unavailable
    - Verify error message includes retry guidance
  - [x] Test camelCase conversion (AC: #3):
    - Verify request with camelCase fields (uploadId, mimeType) is accepted
    - Verify response uses camelCase (uploadId, expiresAt) not snake_case
  - [x] Test OpenAPI documentation (AC: #9):
    - Verify /openapi.json includes POST /v1/uploads
    - Verify request/response schemas documented
    - Verify security requirements documented (JWT)

- [x] Create Integration Tests
  - [x] Create tests/integration/api/test_initiate_upload_endpoint.py
  - [x] Test full integration with real dependencies (Redis, use case)
  - [x] Setup test fixtures:
    - redis_client: Real Redis connection to test database
    - test_app: FastAPI app with real dependencies
    - jwt_token: Valid JWT for OWNER user
  - [x] Test happy path end-to-end:
    - POST /v1/uploads with valid JWT and request
    - Verify 201 Created
    - Verify session created in Redis with correct TTL
    - Verify rate limit counter incremented
    - Verify response matches expected schema
  - [x] Test rate limiting integration:
    - Create MAX_CONCURRENT_UPLOADS sessions
    - Verify next POST returns 429
    - Verify rate limit counter accurate
  - [x] Test JWT validation integration:
    - POST with real JWT from stub auth service
    - Verify successful authentication
  - [x] Cleanup:
    - Delete test sessions from Redis
    - Reset rate limit counters

- [x] Code Quality Checks (development standards)
  - [x] Run: flox activate -- ruff check src/presentation/api/v1/
  - [x] Run: flox activate -- ruff format src/presentation/api/v1/
  - [x] Run: flox activate -- mypy src/presentation/api/v1/ --strict
  - [x] Verify PEP 8 compliance
  - [x] Verify all public APIs have comprehensive docstrings
  - [x] Verify no unused imports or variables
  - [x] Run unit tests: flox activate -- pytest tests/unit/presentation/api/v1/ -v
  - [x] Run integration tests: flox activate -- pytest tests/integration/api/ -v

- [x] Documentation Updates
  - [x] Add inline documentation for endpoint handler
  - [x] Document error handling strategy
  - [x] Document camelCase conversion mechanism
  - [x] Add usage examples in docstrings

### Review Findings

**Code review completed on 2026-05-05**

**Patch findings (actionable):**
- [x] [Review][Patch] JWT validation path check has off-by-one edge case [src/presentation/main.py:44] — FIXED: Added exact `/v1` path check to middleware
- [x] [Review][Patch] Error response structure lacks shared model [src/presentation/api/v1/routers/uploads.py] — FIXED: Created ErrorResponse Pydantic schema
- [x] [Review][Patch] Structured logging lacks context binding [src/presentation/api/v1/routers/uploads.py] — FIXED: Added structlog.contextvars.bind_contextvars for automatic context binding
- [x] [Review][Patch] Request body logging may expose sensitive metadata [src/presentation/api/v1/routers/uploads.py:initiate_upload] — FIXED: Sanitized filename in logs (shows only extension)

**Deferred findings (pre-existing or out of scope):**
- [x] [Review][Defer] Redis client singleton lacks connection lifecycle management [src/presentation/api/v1/routers/uploads.py:get_redis_client] — deferred, pre-existing (Epic 6: operations)
- [x] [Review][Defer] Middleware suppresses type checking with type: ignore [src/presentation/main.py:jwt_validation_middleware] — deferred, pre-existing pattern
- [x] [Review][Defer] DTO mapping layer adds redundant transformation [src/presentation/api/v1/routers/uploads.py:initiate_upload] — deferred, architectural decision from Story 3.4
- [x] [Review][Defer] JWT claims lack workspace existence validation [Authentication flow] — deferred, pre-existing authentication design
- [x] [Review][Defer] Application startup/shutdown events not implemented [src/presentation/main.py] — deferred, Epic 6 scope
- [x] [Review][Defer] Rate limiting occurs after authentication overhead [Architecture decision] — deferred, requires JWT claims for workspace-scoped limiting
- [x] [Review][Defer] Settings retrieved via scattered function calls [src/presentation/api/v1/routers/uploads.py] — deferred, standard FastAPI pattern
- [x] [Review][Defer] Redis operations lack timeout configuration [Infrastructure layer] — deferred, Epic 6 scope

**Review summary:** 0 decision-needed, 4 patch, 8 deferred, 3 dismissed

## File List

**Files Created:**
- src/presentation/api/v1/schemas/upload_schemas.py
- src/presentation/api/v1/routers/uploads.py
- tests/unit/presentation/api/v1/routers/test_uploads.py
- tests/integration/api/test_initiate_upload_endpoint.py
- tests/unit/presentation/api/v1/__init__.py
- tests/unit/presentation/api/v1/routers/__init__.py
- tests/integration/api/__init__.py

**Files Modified:**
- src/presentation/main.py
- artifacts/implementation-artifacts/3-5-implement-post-v1-uploads-api-endpoint.md
- artifacts/implementation-artifacts/sprint-status.yaml

## Change Log

**2026-05-05** - Code Review Fixes Applied
- Fixed JWT validation middleware edge case: exact `/v1` path now requires authentication
- Created ErrorResponse Pydantic schema for consistent error response structure
- Implemented structured logging context binding using structlog.contextvars
- Sanitized filename in logs to prevent PII exposure (shows only file extension)
- All code quality checks passing (ruff, mypy --strict)
- All tests passing (374 passed, 3 skipped)
- Story marked as "done" in sprint status

**2026-05-05** - Story 3.5 Implementation Completed
- Created POST /v1/uploads API endpoint with comprehensive error handling
- Implemented Pydantic request/response schemas with camelCase conversion
- Added dependency injection for use case, session store, and rate limiter
- Created 16 unit tests (100% passing) and 8 integration tests
- Integrated router into main FastAPI application
- All code quality checks passing (ruff, mypy --strict)
- Story marked as "review" in sprint status

## Dev Notes

### Story Context and Purpose

**What This Story Is About:**

Story 3.5 implements the **POST /v1/uploads API endpoint** — the REST API presentation layer for initiating chunked upload sessions. This is the HTTP interface that workspace owners use to start file uploads, mapping between external camelCase JSON and internal domain models.

**Why This Is Critical:**

This story enables:
- **External API contract** - First user-facing endpoint for upload functionality
- **Authentication & authorization enforcement** - JWT validation + RBAC for workspace owners only
- **Clean Architecture boundary** - Maps between HTTP (Pydantic schemas) and application layer (DTOs)
- **OpenAPI documentation** - Auto-generated API docs for Vue.js frontend integration

**Relationship to Previous Stories:**

- **Story 3.4 (Initiate Upload Use Case)**: This story calls the use case implemented in 3.4
- **Story 3.3 (Rate Limiting)**: Use case handles rate limiting; this story returns 429 responses
- **Story 3.2 (Session Store)**: Use case persists sessions; this story doesn't interact with Redis directly
- **Story 3.1 (Domain Entities)**: Use case creates entities; this story only deals with HTTP layer
- **Story 2.2 (JWT Validation)**: This story uses JWT middleware for authentication
- **Story 2.4 (RBAC)**: This story uses require_role dependency for OWNER-only access

**Integration Points:**

- **Frontend (Vue.js)**: Calls POST /v1/uploads with JSON body (camelCase)
- **Authentication**: JWT middleware validates token before endpoint handler
- **Authorization**: RBAC middleware enforces OWNER role requirement
- **Use Case Layer**: Calls InitiateUploadUseCase.execute() with DTO
- **Next Story 3.6**: Chunk SHA-256 verification service (used by future PATCH endpoint)
- **Future Story 3.8**: PATCH /v1/uploads/{id} endpoint for chunk upload

**What Already Exists (DO NOT RECREATE):**

✅ **InitiateUploadUseCase** - src/application/use_cases/initiate_upload.py (Story 3.4)
✅ **InitiateUploadRequest DTO** - src/application/dto/upload_request.py (Story 3.4)
✅ **InitiateUploadResponse DTO** - src/application/dto/upload_response.py (Story 3.4)
✅ **JWT middleware** - src/presentation/api/middleware/auth.py (Story 2.2)
✅ **RBAC middleware** - src/infrastructure/auth/rbac_middleware.py (Story 2.4)
✅ **get_current_user dependency** - src/presentation/api/middleware/auth.py (Story 2.2)
✅ **require_role dependency** - src/infrastructure/auth/rbac_middleware.py (Story 2.4)
✅ **Domain entities** - src/domain/entities/upload_session.py (Story 3.1)
✅ **Value objects** - src/domain/value_objects/ (Stories 2.1, 3.1)
✅ **Domain exceptions** - src/domain/exceptions.py (Stories 2.1, 3.1)
✅ **FastAPI app** - src/presentation/main.py (Story 1.1)

**What We Need to Create:**

🔨 **Pydantic Schemas** - src/presentation/api/v1/schemas/upload_schemas.py (NEW)
🔨 **Uploads Router** - src/presentation/api/v1/routers/uploads.py (NEW)
🔨 **Error Response Handling** - In router endpoint (NEW)
🔨 **Dependency Injection Setup** - For use case (NEW)
🔨 **Comprehensive Unit Tests** - tests/unit/presentation/api/v1/routers/test_uploads.py (NEW)
🔨 **Integration Tests** - tests/integration/api/test_initiate_upload_endpoint.py (NEW)

### Architecture Requirements

**API Endpoint Pattern from [architecture.md](../planning-artifacts/architecture.md#api-communication-patterns):**

> **Presentation Layer** (FastAPI routers) depends on Application layer use cases, not directly on Infrastructure. The presentation layer maps between external API conventions (camelCase JSON) and internal domain models (snake_case Python).

**Clean Architecture Flow for This Story:**

```
HTTP Request (camelCase JSON)
  ↓
FastAPI Endpoint (src/presentation/api/v1/routers/uploads.py)
  ↓
Pydantic Schema Validation (InitiateUploadRequest)
  ↓
Map to Application DTO (InitiateUploadRequest DTO)
  ↓
Use Case Execution (InitiateUploadUseCase.execute())
  ↓
Application DTO Response (InitiateUploadResponse DTO)
  ↓
Map to Pydantic Schema (InitiateUploadResponse)
  ↓
HTTP Response (camelCase JSON)
```

**Pydantic Schema Pattern from [architecture.md](../planning-artifacts/architecture.md#api-json-field-naming):**

> External API uses camelCase (Vue.js friendly), internal Python uses snake_case. Pydantic's `alias_generator=to_camel` handles automatic conversion.

**Pydantic Configuration Pattern:**

```python
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

class BaseAPISchema(BaseModel):
    """Base schema for all API request/response models.
    
    Automatically converts snake_case Python fields to camelCase JSON fields.
    """
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,  # Allows both snake_case and camelCase in input
        json_encoders={
            datetime: lambda v: v.isoformat().replace("+00:00", "Z")
        }
    )

class InitiateUploadRequest(BaseAPISchema):
    """Request schema for POST /v1/uploads endpoint."""
    filename: str = Field(..., description="Original filename", min_length=1, max_length=255)
    size: int = Field(..., description="File size in bytes", gt=0, le=1073741824)
    mime_type: str = Field(..., description="MIME type", pattern="^application/pdf$")
    sha256_checksum: str = Field(..., description="SHA-256 checksum", pattern="^[a-f0-9]{64}$")
    # JSON: {"filename": "...", "size": 1024, "mimeType": "...", "sha256Checksum": "..."}
```

**FastAPI Router Pattern from [architecture.md](../planning-artifacts/architecture.md#presentation-layer):**

> FastAPI routers live in src/presentation/api/v1/routers/, one router per resource domain. Each router defines endpoints, dependencies, and response models.

**Router Structure Pattern:**

```python
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.workspace_role import WorkspaceRole
from src.infrastructure.auth.rbac_middleware import require_role
from src.application.use_cases.initiate_upload import InitiateUploadUseCase
from src.presentation.api.v1.schemas.upload_schemas import (
    InitiateUploadRequest,
    InitiateUploadResponse
)

router = APIRouter(prefix="/v1", tags=["uploads"])

@router.post(
    "/uploads",
    status_code=status.HTTP_201_CREATED,
    response_model=InitiateUploadResponse,
    summary="Initiate chunked upload session",
    description="Creates new upload session for workspace owner",
)
async def initiate_upload(
    request: InitiateUploadRequest,
    current_user: Annotated[JWTClaims, Depends(require_role(WorkspaceRole.OWNER))],
    use_case: Annotated[InitiateUploadUseCase, Depends(get_initiate_upload_use_case)],
) -> InitiateUploadResponse:
    """Initiate new chunked upload session.
    
    Requires OWNER role. Returns session ID and expiry timestamp.
    """
    # Map Pydantic schema to application DTO
    dto_request = InitiateUploadRequest(  # Application DTO, not Pydantic schema
        workspace_id=current_user.workspace_id,
        filename=request.filename,
        size=request.size,
        mime_type=request.mime_type,
        sha256_checksum=request.sha256_checksum
    )
    
    # Execute use case
    try:
        dto_response = await use_case.execute(dto_request)
    except RateLimitExceededError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "RATE_LIMIT_EXCEEDED",
                "message": str(e),
                "details": {
                    "current_uploads": e.current_count,
                    "limit": e.limit,
                    "retry_after_seconds": 60
                }
            }
        )
    # ... handle other exceptions ...
    
    # Map DTO response to Pydantic schema
    return InitiateUploadResponse(
        upload_id=dto_response.session_id,
        offset=dto_response.offset,
        expires_at=dto_response.expires_at
    )
```

**Dependency Injection Pattern:**

From [architecture.md](../planning-artifacts/architecture.md#dependency-injection):

> Use FastAPI's Depends() for dependency injection. Create provider functions that instantiate use cases with infrastructure dependencies.

**Dependency Provider Pattern:**

```python
from functools import lru_cache
from fastapi import Depends
from src.application.use_cases.initiate_upload import InitiateUploadUseCase
from src.infrastructure.redis.session_store import get_session_store
from src.application.services.rate_limiter import get_rate_limiter

@lru_cache(maxsize=1)
def get_initiate_upload_use_case(
    session_store: Annotated[ISessionStore, Depends(get_session_store)],
    rate_limiter: Annotated[IRateLimiter, Depends(get_rate_limiter)],
) -> InitiateUploadUseCase:
    """Provide InitiateUploadUseCase with injected dependencies."""
    return InitiateUploadUseCase(
        session_store=session_store,
        rate_limiter=rate_limiter
    )
```

**Error Response Pattern from [architecture.md](../planning-artifacts/architecture.md#error-response-structure):**

> Error responses include structured details for debugging. Use consistent format across all endpoints.

**Error Response Structure:**

```python
{
    "error": "ERROR_CODE",  # Uppercase snake case
    "message": "Human-readable description",
    "details": {
        # Additional context specific to error type
        "field": "value"
    }
}
```

**HTTP Status Codes for This Endpoint:**

- **201 Created**: Session successfully created
- **401 Unauthorized**: Missing or invalid JWT
- **403 Forbidden**: COLLABORATOR role (requires OWNER)
- **413 Payload Too Large**: File size > 1 GB
- **415 Unsupported Media Type**: MIME type not "application/pdf"
- **422 Unprocessable Entity**: Invalid request body (Pydantic validation)
- **429 Too Many Requests**: Rate limit exceeded
- **503 Service Unavailable**: Redis/infrastructure failure

### Previous Story Intelligence (Story 3.4)

**Key Learnings from Story 3.4 (Initiate Upload Use Case):**

1. **Use Case Orchestration Pattern:**
   - Use case validates input FIRST (fail fast)
   - Use case checks rate limit BEFORE creating session (prevent wasted work)
   - Use case creates session with 24-hour TTL
   - Use case returns DTO response (not domain entity)

2. **DTO vs Pydantic Schema Separation:**
   - Application layer has DTOs (InitiateUploadRequest/Response in src/application/dto/)
   - Presentation layer has Pydantic schemas (will be created in this story)
   - Endpoint maps between Pydantic schema and DTO
   - This separation allows domain to evolve independently of API contract

3. **Error Handling Strategy:**
   - Domain exceptions raised by use case
   - API layer catches and converts to HTTP responses
   - Rate limit cleanup handled by use case (not API layer)

4. **Validation Order:**
   ```python
   # Story 3.4 use case order (THIS IS THE CONTRACT):
   1. Validate filename, checksum format (fail fast before rate limit)
   2. Check rate limit (increment counter)
   3. Validate file size and MIME type
   4. Create session in Redis
   5. If session creation fails, counter cleanup happens in use case
   ```

5. **Performance Budget (NFR-P1):**
   - Total endpoint response time: <200ms at p99
   - Use case execution: <40ms (measured in Story 3.4)
   - Leaves 160ms for HTTP processing, JWT validation, serialization

**Dev Notes from Story 3.4:**

> Use case depends on protocols (IRateLimiter, ISessionStore), not concrete implementations. This enables dependency injection via FastAPI Depends().

**Implications for Story 3.5:**

- Create dependency provider that injects Redis implementations
- Map Pydantic schema fields to DTO fields (workspace_id from JWT)
- Handle domain exceptions in endpoint, convert to HTTP status codes
- Test both Pydantic validation errors (422) and domain exception errors (413, 415, 429, 503)

### Authentication & Authorization Flow

**JWT Validation Middleware (Already Exists):**

From src/presentation/api/middleware/auth.py:

```python
async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> JWTClaims:
    """Extract and validate JWT from Authorization header."""
    # Validates Authorization header exists
    # Validates Bearer token format
    # Validates token size (prevent DoS)
    # Validates JWT signature and expiry
    # Returns JWTClaims with user_id, workspace_id, workspace_role
    # Raises HTTPException 401 on failure
```

**RBAC Middleware (Already Exists):**

From src/infrastructure/auth/rbac_middleware.py:

```python
def require_role(required_role: WorkspaceRole) -> Callable[..., Awaitable[JWTClaims]]:
    """Create FastAPI dependency that enforces workspace role requirement."""
    async def check_role(
        current_user: Annotated[JWTClaims, Depends(get_current_user)],
    ) -> JWTClaims:
        # Validates current_user.workspace_role == required_role
        # Returns current_user if authorized
        # Raises HTTPException 403 if role doesn't match
```

**Usage in This Story:**

```python
@router.post("/uploads")
async def initiate_upload(
    request: InitiateUploadRequest,
    current_user: Annotated[JWTClaims, Depends(require_role(WorkspaceRole.OWNER))],
    # ↑ This dependency chain ensures:
    # 1. JWT is validated (401 if invalid)
    # 2. Role is OWNER (403 if COLLABORATOR)
    # 3. current_user contains workspace_id for use case
) -> InitiateUploadResponse:
    workspace_id = current_user.workspace_id  # Extract from JWT claims
    # ... proceed with use case execution ...
```

**Dependency Chain:**

```
require_role(WorkspaceRole.OWNER)
  ↓ depends on
get_current_user
  ↓ validates
Authorization: Bearer <token>
  ↓ returns
JWTClaims(user_id, workspace_id, workspace_role, shared_file_ids)
```

**Error Scenarios:**

- Missing Authorization header → 401 from get_current_user
- Invalid JWT signature → 401 from get_current_user
- Expired JWT → 401 from get_current_user
- COLLABORATOR role → 403 from require_role
- Infrastructure error during validation → 401 from get_current_user

### Testing Strategy

**Unit Tests (Fast, No External Dependencies):**

```python
# tests/unit/presentation/api/v1/routers/test_uploads.py

@pytest.fixture
def mock_use_case():
    """Mock InitiateUploadUseCase for testing endpoint logic."""
    return AsyncMock(spec=InitiateUploadUseCase)

@pytest.fixture
def mock_current_user():
    """Mock authenticated OWNER user."""
    return JWTClaims(
        user_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None
    )

async def test_initiate_upload_success(test_client, mock_use_case, mock_current_user):
    """Test happy path: valid request returns 201 with session details."""
    # Mock use case response
    mock_use_case.execute.return_value = InitiateUploadResponse(
        session_id=uuid4(),
        offset=0,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
    )
    
    # Make request
    response = test_client.post(
        "/v1/uploads",
        json={
            "filename": "document.pdf",
            "size": 1048576,
            "mimeType": "application/pdf",  # camelCase in request
            "sha256Checksum": "a" * 64
        },
        headers={"Authorization": "Bearer valid-token"}
    )
    
    # Assertions
    assert response.status_code == 201
    assert "uploadId" in response.json()  # camelCase in response
    assert response.json()["offset"] == 0
    assert "expiresAt" in response.json()
    mock_use_case.execute.assert_called_once()

async def test_initiate_upload_collaborator_forbidden(test_client):
    """Test RBAC: COLLABORATOR role returns 403."""
    # Override dependency to return COLLABORATOR user
    response = test_client.post(
        "/v1/uploads",
        json={"filename": "doc.pdf", "size": 1024, "mimeType": "application/pdf", "sha256Checksum": "a"*64},
        headers={"Authorization": "Bearer collaborator-token"}
    )
    
    assert response.status_code == 403
    assert "OWNER role required" in response.json()["detail"]
```

**Integration Tests (With Real Dependencies):**

```python
# tests/integration/api/test_initiate_upload_endpoint.py

async def test_initiate_upload_integration(test_app, redis_client, jwt_token):
    """Test full flow: request → use case → Redis → response."""
    # Make request with real JWT
    response = await test_app.post(
        "/v1/uploads",
        json={
            "filename": "test.pdf",
            "size": 1024,
            "mimeType": "application/pdf",
            "sha256Checksum": "a" * 64
        },
        headers={"Authorization": f"Bearer {jwt_token}"}
    )
    
    # Verify response
    assert response.status_code == 201
    upload_id = response.json()["uploadId"]
    
    # Verify session created in Redis
    session_key = f"session:workspace_{workspace_id}:upload_{upload_id}"
    session_data = await redis_client.hgetall(session_key)
    assert session_data is not None
    assert session_data["filename"] == "test.pdf"
    
    # Verify TTL set to 24 hours
    ttl = await redis_client.ttl(session_key)
    assert 86000 < ttl <= 86400  # ~24 hours
    
    # Cleanup
    await redis_client.delete(session_key)
```

### File Mapping

**Files Being Created (NEW):**

```
src/presentation/api/v1/
├── schemas/
│   └── upload_schemas.py          # NEW - Pydantic request/response schemas
└── routers/
    └── uploads.py                 # NEW - FastAPI router with POST endpoint

tests/unit/presentation/api/v1/
└── routers/
    └── test_uploads.py            # NEW - Unit tests for endpoint

tests/integration/api/
└── test_initiate_upload_endpoint.py  # NEW - Integration tests
```

**Files Being Modified (UPDATE):**

```
src/presentation/main.py           # UPDATE - Include uploads router
```

**Files Being Read/Used (REFERENCE ONLY):**

```
src/application/use_cases/initiate_upload.py          # USE - Call execute()
src/application/dto/upload_request.py                 # USE - Map from Pydantic schema
src/application/dto/upload_response.py                # USE - Map to Pydantic schema
src/presentation/api/middleware/auth.py               # USE - get_current_user dependency
src/infrastructure/auth/rbac_middleware.py            # USE - require_role dependency
src/domain/value_objects/jwt_claims.py                # USE - Type for current_user
src/domain/value_objects/workspace_role.py            # USE - WorkspaceRole.OWNER
src/domain/exceptions.py                              # USE - Exception handling
```

### Implementation Checklist

**Pre-Implementation Verification:**

- [ ] Read Story 3.4 implementation artifacts completely
- [ ] Understand DTO vs Pydantic schema separation
- [ ] Review existing auth middleware (get_current_user, require_role)
- [ ] Review architecture.md for camelCase conversion pattern
- [ ] Review main.py to understand app structure
- [ ] Identify all domain exceptions that need HTTP status mappings

**Implementation Order (DO NOT SKIP STEPS):**

1. **Create Pydantic Schemas First**
   - Define BaseAPISchema with camelCase config
   - Define InitiateUploadRequest with Field validators
   - Define InitiateUploadResponse with datetime encoding
   - Test schemas independently (unit tests for serialization)

2. **Create Router with POST Endpoint**
   - Import all dependencies (use case, auth, schemas, DTOs)
   - Define POST /uploads handler signature
   - Add require_role(WorkspaceRole.OWNER) dependency
   - Implement mapping: Pydantic schema → DTO
   - Call use_case.execute()
   - Implement error handling with try/except
   - Implement mapping: DTO → Pydantic schema
   - Add comprehensive docstring for OpenAPI

3. **Create Dependency Injection Provider**
   - Create provider function for InitiateUploadUseCase
   - Inject IRateLimiter and ISessionStore
   - Use @lru_cache for singleton behavior
   - Add to router endpoint via Depends()

4. **Integrate Router into Main App**
   - Import uploads router in main.py
   - Add app.include_router(uploads.router)
   - Verify /docs shows new endpoint

5. **Create Comprehensive Tests**
   - Unit tests: Mock use case, test all error scenarios
   - Integration tests: Real Redis, real use case execution
   - Test camelCase conversion both directions
   - Test all HTTP status codes (201, 401, 403, 413, 415, 422, 429, 503)

6. **Run Quality Checks**
   - ruff check + format
   - mypy --strict
   - pytest with coverage
   - Verify OpenAPI spec generation

### Success Criteria

**Definition of Done:**

- [ ] POST /v1/uploads endpoint returns 201 with uploadId, offset, expiresAt
- [ ] Endpoint requires OWNER role (403 for COLLABORATOR)
- [ ] Endpoint validates JWT (401 for invalid/missing)
- [ ] Endpoint handles all domain exceptions with appropriate HTTP status codes
- [ ] Request/response use camelCase (uploadId, not upload_id)
- [ ] All unit tests pass with >90% coverage
- [ ] Integration tests pass with real Redis
- [ ] OpenAPI spec includes new endpoint with correct schemas
- [ ] Code passes ruff, mypy, and all quality checks
- [ ] Error responses include structured details (e.g., rate limit count)

**Non-Goals (Out of Scope):**

- ❌ Implementing PATCH /v1/uploads/{id} (Story 3.8)
- ❌ Implementing chunk SHA-256 verification (Story 3.6)
- ❌ Modifying use case logic (Story 3.4 is complete)
- ❌ Adding new middleware (auth already exists)
- ❌ Modifying domain entities or value objects

### Completion Notes

**Implementation Date:** 2026-05-05

**Actual Changes Made:**

Files Created:
- `src/presentation/api/v1/schemas/upload_schemas.py` - Pydantic request/response schemas with camelCase conversion
  - BaseAPISchema with to_camel alias generator
  - InitiateUploadRequest with Field validators
  - InitiateUploadResponse with field_serializer for ISO 8601 datetime
- `src/presentation/api/v1/routers/uploads.py` - FastAPI router with POST /v1/uploads endpoint
  - Complete error handling for all domain exceptions
  - Dependency injection for Redis client, session store, rate limiter, use case
  - Comprehensive OpenAPI documentation with response examples
- `tests/unit/presentation/api/v1/routers/test_uploads.py` - 16 comprehensive unit tests
  - Tests for happy path, authentication, authorization, validation, error handling
  - Tests for camelCase conversion
  - All tests passing
- `tests/integration/api/test_initiate_upload_endpoint.py` - Integration tests with real Redis
  - Tests for full flow, rate limiting, workspace isolation, data integrity

Files Modified:
- `src/presentation/main.py` - Included uploads router, removed placeholder endpoint

**Deviations from Plan:**

Minor deviations:
1. Used Pydantic's `field_serializer` instead of deprecated `json_encoders` for datetime formatting
2. Changed HTTP status code from `HTTP_413_REQUEST_ENTITY_TOO_LARGE` to `HTTP_413_CONTENT_TOO_LARGE` (deprecated warning fix)
3. Added JWTClaims `exp` field to test fixtures (required by domain object)

All deviations were to address deprecation warnings and align with current Pydantic best practices.

**Integration Points Verified:**

✅ Story 3.4 - InitiateUploadUseCase integration tested
✅ Story 3.3 - Rate limiting with RedisRateLimiter working correctly
✅ Story 3.2 - Session persistence via RedisSessionStore verified
✅ Story 3.1 - Domain entities correctly used
✅ Story 2.2 - JWT authentication middleware dependency
✅ Story 2.4 - RBAC middleware (require_role) enforcing OWNER-only access

**Known Issues / Follow-up Work:**

None. All acceptance criteria satisfied. All tests passing.

**Performance Metrics:**

Unit tests: 16 tests passed in 0.59s (all mocked dependencies)
Type checking: mypy --strict passes with no issues
Code formatting: ruff format applied successfully
Linting: ruff check passes with no issues

**Test Coverage:**

Unit tests cover:
- Happy path (201 Created)
- Authentication (401 Unauthorized)
- Authorization (403 Forbidden for COLLABORATOR)
- Rate limiting (429 Too Many Requests)
- File size validation (413 Payload Too Large)
- MIME type validation (415 Unsupported Media Type)
- Pydantic validation (422 Unprocessable Entity)
- Infrastructure errors (503 Service Unavailable)
- camelCase conversion (request/response)
- Workspace ID extraction from JWT claims
- ISO 8601 datetime formatting with Z suffix

Integration tests cover:
- Full request → Redis → response flow
- Rate limit counter management
- Workspace isolation
- Session TTL verification
- Data integrity round-trip
- Infrastructure failure handling

**Review Notes:**

Ready for code review. All acceptance criteria met. No known issues or technical debt.
