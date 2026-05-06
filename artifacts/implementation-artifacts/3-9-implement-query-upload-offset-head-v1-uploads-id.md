# Story 3.9: Implement Query Upload Offset (HEAD /v1/uploads/{id})

Status: done

## Story

As a **workspace owner**,
I want **to query the current verified byte offset of my upload**,
So that **I can resume uploads from the correct position**.

## Acceptance Criteria

1. **Given** session store exists
   **When** offset query is implemented
   **Then** HEAD /v1/uploads/{id} endpoint exists in uploads router

2. **And** endpoint retrieves session from Redis

3. **And** response returns 200 OK with Upload-Offset header

4. **And** response includes Upload-Length header (total file size)

5. **And** expired sessions return 404 Session Not Found

6. **And** endpoint allows both OWNER and COLLABORATOR (read operation)

7. **And** endpoint responds in <50ms at p99 (NFR-P2 - hot retry path)

## Developer Context

### What This Story Is About

Story 3.9 implements the **HEAD /v1/uploads/{id} API endpoint** — the lightweight read-only endpoint for querying upload progress. This is THE critical endpoint that enables upload resumability.

This story is **PURELY PRESENTATION LAYER** work:
- Maps HTTP HEAD request to session store retrieval
- Retrieves session from Redis via ISessionStore
- Returns HTTP 200 OK with Upload-Offset and Upload-Length headers
- No request body, no response body (HEAD semantics)
- Enforces authentication (JWT) but allows both OWNER and COLLABORATOR roles (read operation)
- Extremely lightweight - just Redis lookup and header response

**Critical Architecture Rule:** This endpoint does NOT need a use case. It's a simple read operation that retrieves session and returns headers. No business logic, no orchestration, no state changes.

### Why This Is EXTREMELY Critical

This story enables:
- **Upload Resumability (FR11)**: THE core resumability mechanism - client must query offset before resuming
- **Client Recovery**: After disconnect, client calls HEAD to determine where to resume
- **Offset Verification**: Client can verify server state matches expectation before sending next chunk
- **tus Protocol Compliance**: HEAD offset query is a core tus v1.0.0 protocol operation

**Performance Critical - NFR-P2:**
- **Target: <50ms at p99** (compared to <200ms for POST, <100ms for PATCH)
- **Why so fast?** This is in the hot retry path - clients call this BEFORE every resume attempt
- **Impact:** Slow HEAD responses block resumability and frustrate users waiting to resume uploads

**Without this story:**
- **No upload resumability** - clients cannot determine where to resume from
- **Story 3.8 (PATCH endpoint) is unusable** - clients have no way to know current offset
- **Upload reliability drops to zero** - any disconnect = complete restart
- **Integration testing blocked** - cannot test resume-from-offset flows

### Relationship to Previous Stories

**Story 3.8 (PATCH /v1/uploads/{id})**: The write endpoint this HEAD endpoint complements
- PATCH uploads chunks and updates session offset
- HEAD queries current offset before PATCH resume
- Typical flow: **Disconnect → HEAD query offset → PATCH resume from offset**
- Error handling pattern: 409 Offset Mismatch suggests "Query HEAD /v1/uploads/{id} to get current offset"

**Story 3.5 (POST /v1/uploads Endpoint)**: Established the FastAPI router pattern
- Dependency injection for dependencies (via Depends())
- Error handling pattern (try/except with HTTPException)
- Structured logging with context variables (bind_contextvars)
- Authentication via JWT (Depends(get_current_user) or Depends(require_role()))
- Structured error responses with error code, message, details
- This story follows the SAME PATTERN but simpler (no use case, just session store)

**Story 3.2 (Session Store)**: Provides session persistence
- This endpoint calls ISessionStore.get_session() directly
- No use case needed - simple read operation
- Session store returns UploadSession entity with offset and size fields

**Story 2.4 (RBAC Middleware)**: Provides role-based authorization
- HEAD is a **read operation** - both OWNER and COLLABORATOR allowed
- Use `Depends(get_current_user)` NOT `Depends(require_role(WorkspaceRole.OWNER))`
- This is different from POST/PATCH (write operations - OWNER only)

**Story 2.2 (JWT Validation)**: Provides authentication
- JWT validation runs for all endpoints (including HEAD)
- Returns 401 Unauthorized for missing/invalid tokens

**Story 3.1 (Domain Entities)**: Created UploadSession entity
- UploadSession includes: session_id, workspace_id, filename, size, offset, status, etc.
- HEAD endpoint returns offset (current verified position) and size (total file size)

### Integration Points

**Depends On (Must Exist):**
- `src/domain/protocols/session_store.py` (Story 3.2) - ISessionStore protocol
- `src/infrastructure/redis/session_store.py` (Story 3.2) - RedisSessionStore implementation
- `src/domain/entities/upload_session.py` (Story 3.1) - UploadSession entity
- `src/domain/exceptions.py` (Story 3.1) - SessionNotFoundError
- `src/infrastructure/auth/jwt_validator.py` (Story 2.2) - get_current_user dependency
- `src/domain/value_objects/jwt_claims.py` (Story 2.2) - JWTClaims
- `src/presentation/api/v1/routers/uploads.py` (Story 3.5) - Existing router with get_session_store dependency

**Used By (Current and Future Stories):**
- **Story 3.8 (PATCH Endpoint - Already Implemented)**: Error messages suggest calling HEAD to get current offset
- **Client Resume Flow**: After disconnect, client calls HEAD before resuming PATCH
- **Story 4.2 (Resume-from-Offset Logic)**: Will use HEAD to query offset before resuming
- **Integration Tests (Epic 6)**: End-to-end tests will use HEAD to verify offset after each PATCH
- **Vue.js Frontend**: Primary consumer - queries offset before resuming interrupted uploads

**Sequence Diagram (This Story's Role):**
```
Vue.js Client (after disconnect)
    ↓
    HEAD /v1/uploads/{id} (Story 3.9)
    ↓
    JWT Validation (Story 2.2)
    ↓
    get_session_store() → ISessionStore.get_session() (Story 3.2)
    ↓
    Redis lookup: session:workspace_{workspace_id}:upload_{upload_id}
    ↓
    Return UploadSession entity (Story 3.1)
    ↓
    HTTP 200 OK with Upload-Offset: {offset}, Upload-Length: {size}
    ↓
    Client now knows: "Resume from byte {offset}"
    ↓
    Client calls PATCH /v1/uploads/{id} with Upload-Offset: {offset}
```

## Technical Requirements

### FastAPI HEAD Endpoint Pattern

**Location:** `src/presentation/api/v1/routers/uploads.py` (ADD to existing file)

**Purpose:** Lightweight HTTP endpoint for querying current upload progress - enables resumability

**HEAD Semantics:**
- **No request body** (HTTP HEAD method never has body)
- **No response body** (HTTP HEAD returns same headers as GET but no body)
- **Headers only** - Upload-Offset and Upload-Length in response headers
- **Same authentication as GET** (both OWNER and COLLABORATOR allowed for read operations)

**Response Headers:**
- `Upload-Offset` (int): Current verified byte offset (where next chunk should start)
- `Upload-Length` (int): Total file size in bytes (from session initialization)

**Response:**
- Success: 200 OK with Upload-Offset and Upload-Length headers, empty body
- Errors: Structured JSON with error code, message, details (same pattern as other endpoints)

### Endpoint Implementation Structure

```python
# ADD to src/presentation/api/v1/routers/uploads.py
# Location: After PATCH endpoint (around line 900)

@router.head(
    "/uploads/{upload_id}",
    status_code=status.HTTP_200_OK,
    summary="Query current upload offset for resumability",
    description=(
        "Returns current verified byte offset in Upload-Offset header. "
        "Client calls this before resuming to determine where to continue. "
        "Critical performance target: <50ms p99 (hot retry path). "
        "Allows both OWNER and COLLABORATOR roles (read operation)."
    ),
    responses={
        200: {
            "description": "Session found - offset returned in headers",
            "headers": {
                "Upload-Offset": {
                    "description": "Current verified byte offset (start position for next chunk)",
                    "schema": {"type": "integer"},
                    "example": 5242880
                },
                "Upload-Length": {
                    "description": "Total file size in bytes (from session initiation)",
                    "schema": {"type": "integer"},
                    "example": 10485760
                },
            },
        },
        401: {
            "description": "Authentication failed (missing/invalid/expired JWT)",
            "content": {"application/json": {"example": {"detail": "Authentication failed"}}},
        },
        404: {
            "description": "Session not found or expired (24h TTL)",
            "content": {
                "application/json": {
                    "example": {
                        "error": "SESSION_NOT_FOUND",
                        "message": "Upload session 550e8400-e29b-41d4-a716-446655440000 not found or expired",
                        "details": {
                            "session_id": "550e8400-e29b-41d4-a716-446655440000",
                            "suggestion": "Start a new upload session via POST /v1/uploads",
                        },
                    }
                }
            },
        },
        503: {
            "description": "Service unavailable (infrastructure failure)",
            "content": {
                "application/json": {
                    "example": {
                        "error": "INFRASTRUCTURE_ERROR",
                        "message": "Storage system temporarily unavailable. Please retry.",
                        "details": {"retry_guidance": "Retry after a few seconds"},
                    }
                }
            },
        },
    },
)
async def query_upload_offset(
    upload_id: UUID,
    current_user: Annotated[JWTClaims, Depends(get_current_user)],
    session_store: Annotated[ISessionStore, Depends(get_session_store)],
) -> Response:
    """Query current upload offset for resumability.

    Returns current verified byte offset and total file size in response headers.
    This is THE critical endpoint for upload resumability - client must call this
    before resuming to determine where to continue from.

    Authentication & Authorization:
        - Requires valid JWT in Authorization header (Bearer token)
        - Allows both OWNER and COLLABORATOR roles (read operation)
        - workspace_id extracted from JWT claims

    Request:
        - No request body (HEAD method)
        - No query parameters
        - Path parameter: upload_id (UUID)

    Response Headers (Success):
        - Upload-Offset: Current verified byte offset (start position for next chunk)
        - Upload-Length: Total file size in bytes (from session initiation)

    Response Body:
        - Empty (HEAD method returns headers only, no body)

    Error Handling:
        - 401: Authentication failed (missing/invalid/expired JWT)
        - 404: Session not found or expired (24h TTL)
        - 503: Infrastructure failure (Redis connection error)

    Performance (Critical - NFR-P2):
        - Target: <50ms at p99 (hot retry path)
        - This is faster than POST (<200ms) and PATCH (<100ms)
        - Why so fast? Clients call this BEFORE every resume attempt
        - Implementation: Single Redis lookup, no business logic

    tus Protocol Compliance:
        - HEAD offset query is core tus v1.0.0 protocol operation
        - Upload-Offset header indicates where client should resume
        - Upload-Length header provides total size for validation

    Args:
        upload_id: Upload session UUID from path parameter
        current_user: JWT claims from authentication (contains workspace_id)
        session_store: Injected session store for Redis operations

    Returns:
        Response: 200 OK with Upload-Offset and Upload-Length headers, empty body

    Raises:
        HTTPException: 401/404/503 with structured error details

    Examples:
        >>> # Success case - query offset after uploading first chunk
        >>> HEAD /v1/uploads/550e8400-e29b-41d4-a716-446655440000
        >>> Authorization: Bearer <token>
        >>>
        >>> # Response 200 OK
        >>> Upload-Offset: 5242880
        >>> Upload-Length: 10485760
        >>> (empty body)
        >>>
        >>> # Client interprets: "I've uploaded 5MB of 10MB total. Resume from byte 5242880."
        >>>
        >>> # Session not found (expired or never existed)
        >>> HEAD /v1/uploads/550e8400-e29b-41d4-a716-446655440000
        >>> Authorization: Bearer <token>
        >>>
        >>> # Response 404 Not Found
        >>> {
        ...     "error": "SESSION_NOT_FOUND",
        ...     "message": "Upload session 550e8400-e29b-41d4-a716-446655440000 not found or expired",
        ...     "details": {
        ...         "session_id": "550e8400-e29b-41d4-a716-446655440000",
        ...         "suggestion": "Start a new upload session via POST /v1/uploads"
        ...     }
        ... }
    """
    # Bind user context for structured logging
    bind_contextvars(
        user_id=str(current_user.user_id),
        workspace_id=str(current_user.workspace_id),
        session_id=str(upload_id),
    )

    log.info(
        "query_upload_offset_request",
        session_id=str(upload_id),
    )

    try:
        # Retrieve session from Redis
        session = await session_store.get_session(
            workspace_id=current_user.workspace_id,
            session_id=upload_id,
        )

        log.info(
            "query_upload_offset_success",
            session_id=str(upload_id),
            offset=session.offset,
            size=session.size,
            status=session.status.value,
        )

        clear_contextvars()

        # Return 200 OK with Upload-Offset and Upload-Length headers, empty body
        return Response(
            status_code=status.HTTP_200_OK,
            headers={
                "Upload-Offset": str(session.offset),
                "Upload-Length": str(session.size),
            },
        )

    except SessionNotFoundError as e:
        # 404 Session Not Found - expired or never existed
        log.warning(
            "query_upload_offset_session_not_found",
            session_id=str(upload_id),
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "SESSION_NOT_FOUND",
                "message": str(e),
                "details": {
                    "session_id": str(upload_id),
                    "suggestion": "Start a new upload session via POST /v1/uploads",
                },
            },
        ) from e

    except InfrastructureError as e:
        # 503 Service Unavailable - Redis connection failure
        log.error(
            "query_upload_offset_infrastructure_error",
            error=str(e),
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "INFRASTRUCTURE_ERROR",
                "message": str(e),
                "details": {
                    "retry_guidance": "Retry after a few seconds",
                },
            },
        ) from e

    except Exception as e:
        # 500 Internal Server Error - unexpected error
        log.error(
            "query_upload_offset_unexpected_error",
            error=str(e),
            error_type=type(e).__name__,
        )
        clear_contextvars()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": {"error_type": type(e).__name__},
            },
        ) from e
```

### Architecture Compliance

**Clean Architecture Layer: Presentation (FastAPI)**

**What Presentation Layer Is:**
- HTTP request/response mapping (HEAD request → session store → HTTP headers)
- FastAPI route handlers, dependencies, middleware
- HTTP status codes, headers, error responses
- Authentication enforcement (JWT validation)

**What Presentation Layer Is NOT:**
- Business logic (no business logic needed for this simple read operation)
- Session store implementation (that's in infrastructure layer)
- Session entity definition (that's in domain layer)

**Why No Use Case?**
- This is a simple read operation - retrieve session, return headers
- No orchestration needed, no business rules, no state changes
- Use cases are for complex operations with multiple steps or business logic
- HEAD endpoint calls session_store.get_session() directly (Clean Architecture allows this for simple reads)

### Imports Required

**Add to existing imports in uploads.py:**
```python
# Already imported from previous stories:
from uuid import UUID
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Response, status
from structlog.contextvars import bind_contextvars, clear_contextvars
from src.domain.exceptions import SessionNotFoundError, InfrastructureError
from src.domain.protocols.session_store import ISessionStore
from src.domain.value_objects.jwt_claims import JWTClaims
from src.infrastructure.auth.jwt_validator import get_current_user

# No new imports needed - all dependencies already exist!
```

**Note:** Use `Depends(get_current_user)` NOT `Depends(require_role(WorkspaceRole.OWNER))` because HEAD is a read operation that allows both OWNER and COLLABORATOR roles.

### Performance Requirements

**Critical Performance Target (NFR-P2):**
- **HEAD /v1/uploads/{id} responds within 50ms at p99**
- **Why so fast?** This is in the hot retry path - clients call this before every resume attempt
- **Comparison:** POST <200ms (session creation), PATCH <100ms (chunk processing), HEAD <50ms (offset query)

**Performance Budget Breakdown:**
```
JWT validation:                      ~10ms (already optimized in Story 2.2)
Session store lookup (Redis):        ~5-10ms (single HGETALL operation)
Response header creation:            ~1ms
--------------------------------------------------
TOTAL:                               ~15-20ms (well within 50ms budget)
```

**Performance Optimization Strategies:**
- Single Redis lookup (HGETALL session:{workspace_id}:{session_id})
- No business logic execution
- No file I/O, no external service calls
- Async Redis operations (no blocking)
- Minimal logging (one log entry on success, one on error)

## Library/Framework Requirements

### FastAPI

**Already in project** (from Story 1.2, 3.5, 3.8)

**Required imports:**
- `fastapi.Response` - for 200 OK with custom headers
- `fastapi.Depends` - for dependency injection
- `fastapi.HTTPException` - for error responses
- `fastapi.status` - for HTTP status code constants

### Python Standard Library

**uuid:**
- `UUID` type for upload_id path parameter (already imported)

**typing:**
- `Annotated` for FastAPI dependency injection type hints (already imported)

### Existing Project Components

**Domain Layer (Story 3.1, 3.2):**
- `SessionNotFoundError` exception - raised when session doesn't exist
- `InfrastructureError` exception - raised on Redis connection failure
- `ISessionStore` protocol with `get_session()` method
- `UploadSession` entity with offset and size fields

**Infrastructure Layer (Story 2.2, 3.2):**
- `get_current_user` dependency for JWT authentication (allows both OWNER and COLLABORATOR)
- `RedisSessionStore` implementation of ISessionStore
- Existing `get_session_store()` dependency provider

### No New Dependencies Required

This story uses only existing components - no new libraries or dependencies needed.

## File Structure Requirements

### Modified Files

**File:** `src/presentation/api/v1/routers/uploads.py`

**Change:** Add HEAD /v1/uploads/{id} endpoint

**Location:** Add after the PATCH /v1/uploads/{id} endpoint (around line 900)

**Pattern:** Follow same pattern as existing endpoints:
1. Route decorator with full OpenAPI documentation
2. Async endpoint function with authentication
3. Structured logging with context variables
4. Session store retrieval
5. Error handling with try/except blocks
6. Structured error responses with error code, message, details
7. Clear context variables before return/raise

### No New Files Required

This story only modifies the existing uploads router - no new files needed.

## Testing Requirements

### Unit Tests Required

**File:** `tests/unit/presentation/api/v1/routers/test_uploads.py` (ADD to existing file)

**Test coverage for HEAD endpoint:**

1. **Test happy path (successful offset query):**
   - Mock session_store.get_session() to return session with offset=5242880, size=10485760
   - Send HEAD with valid token (OWNER role)
   - Assert 200 OK response
   - Assert Upload-Offset header = "5242880"
   - Assert Upload-Length header = "10485760"
   - Assert response body is empty (HEAD semantics)
   - Assert session_store.get_session() called once with correct parameters

2. **Test authentication required (401):**
   - Send HEAD without Authorization header
   - Assert 401 Unauthorized response

3. **Test allows OWNER role:**
   - Send HEAD with OWNER token
   - Assert 200 OK response (not 403)

4. **Test allows COLLABORATOR role (read operation):**
   - Send HEAD with COLLABORATOR token
   - Assert 200 OK response (not 403)
   - Verify read operations allow both roles

5. **Test session not found (404):**
   - Mock session_store.get_session() to raise SessionNotFoundError
   - Assert 404 response with SESSION_NOT_FOUND error code
   - Assert details include session_id and suggestion

6. **Test expired session (404):**
   - Mock session_store.get_session() to raise SessionNotFoundError
   - Assert 404 response
   - Assert error message indicates session not found or expired

7. **Test infrastructure error (503):**
   - Mock session_store.get_session() to raise InfrastructureError
   - Assert 503 response with INFRASTRUCTURE_ERROR error code

8. **Test offset=0 (no chunks uploaded yet):**
   - Mock session with offset=0, size=10485760
   - Assert Upload-Offset header = "0"
   - Verify client can query offset before uploading any chunks

9. **Test full upload (offset = size):**
   - Mock session with offset=10485760, size=10485760
   - Assert Upload-Offset header = "10485760"
   - Assert Upload-Length header = "10485760"
   - Verify endpoint works even after upload complete

10. **Test response has no body (HEAD semantics):**
    - Send HEAD request
    - Assert response body is empty or None
    - Verify HEAD method compliance

### Integration Tests Required

**File:** `tests/integration/api/test_upload_flow.py` (ADD to existing tests)

**Test coverage for resume-from-offset flow:**

1. **Test complete resume flow (POST → PATCH → HEAD → PATCH):**
   - POST /v1/uploads to create session
   - PATCH /v1/uploads/{id} to upload first chunk (offset 0)
   - HEAD /v1/uploads/{id} to query offset
   - Verify Upload-Offset = 5242880
   - PATCH /v1/uploads/{id} to upload second chunk (offset 5242880)
   - Verify seamless resume from queried offset

2. **Test HEAD before any chunks uploaded:**
   - POST /v1/uploads to create session
   - HEAD /v1/uploads/{id} immediately
   - Verify Upload-Offset = 0
   - Verify Upload-Length = total file size from POST

3. **Test HEAD after disconnect simulation:**
   - POST /v1/uploads
   - PATCH first chunk
   - PATCH second chunk
   - Simulate disconnect (close connection)
   - HEAD to query current state
   - Verify offset reflects last successful chunk
   - Resume with PATCH from queried offset

4. **Test HEAD after session expiry:**
   - Create session with very short TTL (test mode)
   - Wait for expiry
   - HEAD /v1/uploads/{id}
   - Assert 404 Session Not Found

### Test Fixtures

```python
import pytest
from fastapi.testclient import TestClient
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from src.domain.entities.upload_session import UploadSession
from src.domain.value_objects.session_status import SessionStatus


@pytest.fixture
def mock_session_with_offset() -> UploadSession:
    """Create mock session with offset at 5MB (first chunk uploaded)."""
    return UploadSession(
        session_id=uuid4(),
        workspace_id=uuid4(),
        filename="test.pdf",
        size=10485760,  # 10MB total
        mime_type="application/pdf",
        sha256_checksum="a" * 64,
        offset=5242880,  # 5MB uploaded
        status=SessionStatus.IN_PROGRESS,
        chunk_manifest=[0],  # First chunk uploaded
        created_at="2026-05-05T12:00:00Z",
        expires_at="2026-05-06T12:00:00Z",
    )


@pytest.fixture
def mock_session_store_with_session(mock_session_with_offset: UploadSession) -> AsyncMock:
    """Mock session store that returns session."""
    mock_store = AsyncMock()
    mock_store.get_session.return_value = mock_session_with_offset
    return mock_store
```

### Testing Pattern (from Previous Stories)

**Example test structure:**
```python
@pytest.mark.asyncio
async def test_successful_offset_query(
    client: TestClient,
    mock_session_with_offset: UploadSession,
    mock_session_store_with_session: AsyncMock,
) -> None:
    """Test that valid offset query returns 200 with offset/length headers."""
    # Arrange
    upload_id = mock_session_with_offset.session_id
    
    # Act
    response = client.head(
        f"/v1/uploads/{upload_id}",
        headers={"Authorization": "Bearer valid-token"}
    )
    
    # Assert
    assert response.status_code == 200
    assert response.headers["Upload-Offset"] == "5242880"
    assert response.headers["Upload-Length"] == "10485760"
    assert response.content == b""  # HEAD has no body
    mock_session_store_with_session.get_session.assert_called_once()
```

## Previous Story Intelligence

### Story 3.8 Learnings (PATCH Endpoint)

**Pattern Established:**
- Dependency injection via `Depends()` for session store
- Structured logging with `bind_contextvars()` at start, `clear_contextvars()` at end
- Authentication via JWT (Depends)
- Error handling with try/except blocks for each domain exception
- Structured error responses: `{"error": "CODE", "message": "...", "details": {...}}`
- FastAPI OpenAPI documentation with detailed examples for each status code

**Critical Patterns to Follow:**
- Inject workspace_id from JWT claims (current_user.workspace_id)
- Log structured events: "operation_event_type" with context fields
- Clear context variables before ALL returns and raises
- Include actionable suggestions in error details

**Differences for HEAD:**
- **No use case needed** - direct session store access is fine for simple reads
- **Both roles allowed** - use `Depends(get_current_user)` not `Depends(require_role(WorkspaceRole.OWNER))`
- **No request body, no response body** - HEAD semantics
- **Faster performance target** - <50ms vs <100ms for PATCH

### Story 3.5 Learnings (POST Endpoint)

**Pattern Established:**
- Same patterns as Story 3.8 but for session creation
- Detailed OpenAPI documentation with examples
- Comprehensive error handling
- Performance logging with timing metrics

**Critical Patterns to Follow:**
- Same structured error response format
- Same logging patterns
- Same context variable cleanup

### Story 3.2 Learnings (Session Store)

**Session Store Interface:**
- `get_session(workspace_id: UUID, session_id: UUID) -> UploadSession`
- Raises `SessionNotFoundError` if session doesn't exist or expired
- Raises `InfrastructureError` on Redis connection failure
- Returns UploadSession entity with all fields including offset and size

**Performance:**
- Single Redis HGETALL operation
- Fast enough for <50ms target
- No optimization needed for this story

### Architecture Learning (NFR-P2)

**Why HEAD Must Be So Fast (<50ms):**
- Clients call HEAD before EVERY resume attempt
- Network latency + HEAD latency = total resume delay
- Slow HEAD = frustrated users waiting to resume
- This is the hot path for reliability - must be instant

**Performance Budget:**
- JWT validation: ~10ms (already optimized)
- Redis lookup: ~5-10ms (single operation)
- Response: ~1ms
- **Total: ~15-20ms** (2.5x faster than target, good margin)

## Git Intelligence Summary

**Recent Commit Patterns (Epic 3 Stories):**

**Story 3.8 (PATCH Endpoint):** Created chunked upload endpoint
- File: `src/presentation/api/v1/routers/uploads.py`
- Pattern: Full endpoint with use case, structured errors, OpenAPI docs
- Testing: Unit tests with mocked use case, integration tests with Redis

**Story 3.5 (POST Endpoint):** Created session initiation endpoint
- File: `src/presentation/api/v1/routers/uploads.py`
- Pattern: Dependency injection, error handling, logging
- Testing: Comprehensive unit and integration tests

**Story 3.2 (Session Store):** Created Redis session persistence
- File: `src/infrastructure/redis/session_store.py`
- Pattern: Protocol implementation with error conversion
- Testing: Integration tests with real Redis

**Key Insights for Story 3.9:**
1. **Simplest endpoint yet** - no use case, no complex logic, just Redis lookup
2. **Follow exact same patterns** as Story 3.5 and 3.8 for consistency
3. **Performance critical** - this is the hot path for resumability
4. **Both roles allowed** - different from POST/PATCH (OWNER only)

## Project Context Reference

**From project structure analysis:**
- Project uses Clean Architecture with clear layer separation
- FastAPI for presentation layer (async/await throughout)
- Redis for session state (already configured and working)
- JWT authentication (already implemented and working)
- Structured logging with structlog (already configured)
- Test infrastructure in place (pytest, fixtures, mocks)

**Code Quality Standards:**
- Type hints on all functions
- Docstrings with Args, Returns, Raises, Examples
- Error handling with specific exception types
- Structured logging with context
- Unit tests for all functions
- Integration tests for end-to-end flows

**Architecture Decisions:**
- Presentation layer can call session store directly for simple reads (no use case needed)
- Both OWNER and COLLABORATOR roles allowed for read operations
- HEAD endpoints return headers only, no body
- Performance targets must be met (NFR-P2: <50ms p99)

---

**Status**: ready-for-dev  
**Created**: 2026-05-05  
**Epic**: 3 (Chunked Upload Session Lifecycle)  
**Story ID**: 3.9  
**Complexity**: Low (simple read operation, no business logic)  
**Estimated Effort**: 2-3 hours (endpoint + tests)  

**Notes:**
- This is the SIMPLEST endpoint in Epic 3 - just Redis lookup and header response
- Performance critical (<50ms) but easy to achieve with single Redis operation
- Enables upload resumability - critical for user experience
- Must support both OWNER and COLLABORATOR roles (read operation)
- Follow exact same patterns as Story 3.5 and 3.8 for consistency

---

## Review Findings

### Decision Needed

- [x] [Review][Decision] Session status not validated for terminated sessions — **RESOLVED:** Return 410 Gone for terminated sessions (COMPLETE, ABORTED, FAILED)

### Patches Required

- [x] [Review][Patch] Missing RBAC authorization check violates AC6 [src/presentation/api/v1/routers/uploads.py:1165] — **FIXED:** Added `@require_role([WorkspaceRole.OWNER, WorkspaceRole.COLLABORATOR])` decorator

- [x] [Review][Patch] No timeout on async Redis operation blocks performance target [src/presentation/api/v1/routers/uploads.py:1259] — **FIXED:** Added `asyncio.wait_for(..., timeout=5.0)` wrapper

- [x] [Review][Patch] Offset and size values not validated before response [src/presentation/api/v1/routers/uploads.py:1332-1337] — **FIXED:** Validates `session.offset >= 0 and session.offset <= session.size`

- [x] [Review][Patch] Missing Cache-Control headers enable stale offset caching [src/presentation/api/v1/routers/uploads.py:1332] — **FIXED:** Added `Cache-Control: no-store, no-cache, must-revalidate`

- [x] [Review][Patch] Scattered clear_contextvars() creates maintenance burden [src/presentation/api/v1/routers/uploads.py:1253-1309] — **FIXED:** Refactored to `try/finally` pattern with single cleanup point

### Deferred Issues

- [x] [Review][Defer] Missing rate limiting for hot retry path — deferred, infrastructure concern outside story scope (Epic-level)

- [x] [Review][Defer] No performance metrics collection for <50ms p99 target — deferred, Epic 6 Observability scope

- [x] [Review][Defer] Missing request correlation ID in logs — deferred, logging infrastructure enhancement outside story scope

- [x] [Review][Defer] Logging user_id/workspace_id may violate privacy regulations — deferred, org-wide compliance concern

- [x] [Review][Defer] No ETag or Last-Modified headers — deferred, optimization beyond MVP scope
