# Story 2.5: Implement Workspace Access Control Rules

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **workspace owner**,
I want **full control over my workspace with strict collaborator restrictions**,
So that **my data remains secure and collaborators have read-only access only**.

## Acceptance Criteria

1. **Given** workspace with owner and collaborators
   **When** access control is enforced
   **Then** workspace owner (workspace_role == OWNER in JWT) has full CRUD rights

2. **And** owner can initiate uploads (POST), upload chunks (PATCH), abort (DELETE), list (GET), retrieve (GET)

3. **And** collaborators (workspace_role == COLLABORATOR) have read-only access

4. **And** collaborators can only access files in shared_file_ids JWT claim

5. **And** collaborators attempting POST/PATCH/DELETE receive 403 Forbidden

6. **And** collaborators accessing non-shared files receive 403 Forbidden

7. **And** workspace_id in JWT must match resource workspace_id (403 otherwise)

8. **And** access control validated on every endpoint via RBAC middleware

9. **And** satisfies FR22-FR26 (workspace isolation and role enforcement)

## Tasks / Subtasks

- [x] Design workspace access control architecture (AC: #7, #8)
  - [x] Review existing RBAC middleware from Story 2.4
  - [x] Review JWTClaims.has_access_to_file() method from Story 2.1
  - [x] Identify what new components are needed vs leveraging existing ones
  - [x] Decision: Create workspace validation helpers vs endpoint-level checks
  - [x] Decision: File access control helper pattern (decorator, dependency, or helper function)
  - [x] Document integration with existing auth stack

- [x] Create workspace ID validation infrastructure (AC: #7)
  - [x] Create src/infrastructure/auth/workspace_validator.py
  - [x] Implement validate_workspace_access() function
    - Signature: `validate_workspace_access(current_user: JWTClaims, resource_workspace_id: UUID) -> None`
    - Validates current_user.workspace_id == resource_workspace_id
    - Raises HTTPException 403 if workspace IDs don't match
    - Logs workspace access violations with user_id, claimed_workspace_id, resource_workspace_id
  - [x] Add comprehensive docstring explaining use cases
  - [x] Add type hints for mypy compliance

- [x] Create file access control infrastructure (AC: #4, #6)
  - [x] Create src/infrastructure/auth/file_access_validator.py
  - [x] Implement validate_file_access() function
    - Signature: `validate_file_access(current_user: JWTClaims, file_id: UUID) -> None`
    - Leverages current_user.has_access_to_file(file_id) method
    - OWNER role: Always passes (full workspace access)
    - COLLABORATOR role: Validates file_id in shared_file_ids, raises 403 if not
    - Raises HTTPException 403 with clear message for unauthorized access
    - Logs file access violations with user_id, workspace_id, file_id, role
  - [x] Add comprehensive docstring with usage examples
  - [x] Add type hints for mypy compliance

- [x] Create FastAPI dependency wrappers for easy endpoint integration (AC: #8)
  - [x] Design decision: Use helper functions instead of dependencies for better flexibility
  - [x] Helper functions can be called conditionally inside handlers (better than dependencies)
  - [x] Pattern documented in module docstrings with usage examples
  - [x] Validation functions integrate seamlessly with existing get_current_user dependency

- [x] Update auth module exports (AC: #8)
  - [x] Update src/infrastructure/auth/__init__.py
  - [x] Export workspace_validator, file_access_validator components
  - [x] Export validate_workspace_access, validate_file_access functions
  - [x] Update module docstring with complete access control overview
  - [x] Document the full auth stack: JWT → RBAC → Workspace → File Access

- [x] Create comprehensive unit tests (testing standard)
  - [x] Create tests/unit/infrastructure/auth/test_workspace_validator.py
    - [x] Test validate_workspace_access allows matching workspace IDs
    - [x] Test validate_workspace_access rejects mismatched workspace IDs with 403
    - [x] Test error response includes workspace IDs for debugging
    - [x] Test logging on validation failure
    - [x] Test None/invalid UUID handling
  - [x] Create tests/unit/infrastructure/auth/test_file_access_validator.py
    - [x] Test OWNER role always passes file access validation
    - [x] Test COLLABORATOR with file_id in shared_file_ids passes
    - [x] Test COLLABORATOR without file_id in shared_file_ids receives 403
    - [x] Test COLLABORATOR with None shared_file_ids receives 403
    - [x] Test error response format and content
    - [x] Test logging on access denial
  - [x] Use pytest fixtures for JWTClaims with different scenarios
  - [x] Verify all tests pass with uv run pytest

- [x] Create integration tests with composed dependencies (AC: #8)
  - [x] Create tests/integration/auth/test_workspace_access_control.py
  - [x] Test endpoint with require_owner() + workspace validation
  - [x] Test endpoint with get_current_user + file access validation
  - [x] Test OWNER accessing any file in workspace succeeds
  - [x] Test COLLABORATOR accessing shared file succeeds
  - [x] Test COLLABORATOR accessing non-shared file receives 403
  - [x] Test user accessing different workspace receives 403
  - [x] Verify proper error ordering: 401 (auth) → 403 (role) → 403 (workspace/file)
  - [x] Use httpx AsyncClient for endpoint testing

- [x] Document access control patterns and best practices (developer guidance)
  - [x] Add comprehensive module docstrings with architecture overview
  - [x] Document the complete auth stack layers:
    ```
    Layer 1: JWT Validation (get_current_user) - 401 Unauthorized
    Layer 2: RBAC (require_owner/require_role) - 403 Forbidden (role)
    Layer 3: Workspace Validation - 403 Forbidden (workspace)
    Layer 4: File Access Validation - 403 Forbidden (file access)
    ```
  - [x] Provide endpoint patterns for common scenarios:
    - Write operations: require_owner() + workspace validation
    - Read operations: get_current_user + file access validation
    - List operations: get_current_user + filter by workspace_id
  - [x] Document error response hierarchy and meanings
  - [x] Reference FR22-FR26 requirements
  - [x] Add troubleshooting section

- [x] Code quality checks (development standards)
  - [x] Run uv run ruff check src/infrastructure/auth/
  - [x] Run uv run ruff format src/infrastructure/auth/
  - [x] Run uv run mypy src/infrastructure/auth/
  - [x] Verify no type errors or linting issues
  - [x] Run full test suite: uv run pytest
  - [x] Verify 100% test coverage for new code

## Dev Notes

### Story Context and Purpose

**What This Story Is About:**

Story 2.5 implements **workspace-level and file-level access control** on top of the existing RBAC foundation (Story 2.4). While RBAC handles role enforcement (OWNER vs COLLABORATOR), this story adds **resource-level authorization**:

1. **Workspace Validation**: Ensures users can only access resources in their active workspace
2. **File Access Control**: Ensures collaborators can only access files explicitly shared with them

**Why This Is Critical:**

This is the final piece of the multi-tenant isolation puzzle. Without these controls:
- Users could access resources in other workspaces by guessing IDs (FR26 violation)
- Collaborators could see all files in a workspace instead of only shared files (FR23 violation)

**Relationship to Previous Stories:**

- **Story 2.1**: Created JWTClaims with `has_access_to_file()` method - we leverage this!
- **Story 2.2**: Created JWT validation (Layer 1 auth)
- **Story 2.3**: Created workspace-scoped Redis keys (data isolation)
- **Story 2.4**: Created RBAC middleware (Layer 2 auth)
- **Story 2.5** (this story): Creates workspace/file validation (Layer 3/4 auth)

**What Already Exists (DO NOT RECREATE):**

✅ **JWTClaims.has_access_to_file()** - Domain method that checks file access
✅ **require_owner()** - RBAC dependency for owner-only operations
✅ **require_role()** - Generic RBAC dependency
✅ **get_current_user** - JWT validation dependency

**What We Need to Create:**

🔨 **workspace_validator** - Validates JWT workspace_id matches resource workspace_id
🔨 **file_access_validator** - Validates collaborator file access using has_access_to_file()
🔨 **FastAPI dependencies** - Composable dependencies for endpoint protection

### Architecture Requirements

**Four-Layer Security Model:**

From the architecture document, access control operates in layers:

```
Request → Layer 1: JWT Validation (get_current_user)
         ↓ 401 if token invalid/expired
         → Layer 2: RBAC (require_owner/require_role)
         ↓ 403 if wrong role
         → Layer 3: Workspace Validation (validate_workspace_access)
         ↓ 403 if wrong workspace
         → Layer 4: File Access Validation (validate_file_access)
         ↓ 403 if file not shared
         → Endpoint Handler
```

**Error Response Priority:**

1. **401 Unauthorized**: JWT validation failed (Layer 1)
2. **403 Forbidden (role)**: User role insufficient (Layer 2)
3. **403 Forbidden (workspace)**: Workspace mismatch (Layer 3)
4. **403 Forbidden (file access)**: File not accessible (Layer 4)

This ordering is important for security - never reveal resource existence to unauthorized users.

**FR Requirements Mapping:**

- **FR22**: Workspace owner has full CRUD rights → Handled by RBAC (Story 2.4)
- **FR23**: Owners grant read-only access to specific files → Implemented via shared_file_ids validation
- **FR24**: Owners grant read-only access to entire workspace → Handled by workspace_id validation
- **FR25**: Collaborators cannot modify files → Handled by RBAC (Story 2.4)
- **FR26**: Complete workspace isolation → This story enforces workspace_id matching

**Critical Pattern: Defense in Depth**

Each layer adds protection:
- JWT validation prevents unauthenticated access
- RBAC prevents role escalation attacks
- Workspace validation prevents cross-tenant access
- File validation prevents unauthorized file access within workspace

**ALL LAYERS MUST BE ENFORCED** for complete security. Skipping any layer creates vulnerabilities.

### Technical Stack & Patterns

**FastAPI Dependency Composition Pattern:**

From Story 2.4, we established the dependency pattern. This story extends it:

```python
# Layer 1: JWT Validation (from Story 2.2)
async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> JWTClaims:
    # Validates JWT, returns JWTClaims or raises 401
    ...

# Layer 2: RBAC (from Story 2.4)
def require_owner() -> Callable:
    async def check_role(
        current_user: Annotated[JWTClaims, Depends(get_current_user)],
    ) -> JWTClaims:
        # Validates role, returns JWTClaims or raises 403
        ...
    return check_role

# Layer 3: Workspace Validation (this story)
def validate_workspace_access(
    current_user: JWTClaims,
    resource_workspace_id: UUID,
) -> None:
    """Validate user's workspace matches resource workspace.
    
    Args:
        current_user: Authenticated user from JWT
        resource_workspace_id: Workspace ID of the resource being accessed
        
    Raises:
        HTTPException: 403 if workspace IDs don't match
    """
    if current_user.workspace_id != resource_workspace_id:
        log.warning(
            "workspace_access_denied",
            user_id=str(current_user.user_id),
            user_workspace_id=str(current_user.workspace_id),
            resource_workspace_id=str(resource_workspace_id),
        )
        raise HTTPException(
            status_code=403,
            detail={
                "detail": "Access denied - resource belongs to different workspace",
                "error": "WORKSPACE_MISMATCH",
            },
        )

# Layer 4: File Access Validation (this story)
def validate_file_access(
    current_user: JWTClaims,
    file_id: UUID,
) -> None:
    """Validate user has access to specific file.
    
    OWNER role: Always has access to all files in workspace
    COLLABORATOR role: Only has access to files in shared_file_ids
    
    Args:
        current_user: Authenticated user from JWT
        file_id: File ID being accessed
        
    Raises:
        HTTPException: 403 if user doesn't have access to file
    """
    if not current_user.has_access_to_file(file_id):
        log.warning(
            "file_access_denied",
            user_id=str(current_user.user_id),
            workspace_id=str(current_user.workspace_id),
            file_id=str(file_id),
            role=current_user.workspace_role.value,
        )
        raise HTTPException(
            status_code=403,
            detail={
                "detail": "Access denied - file not accessible to user",
                "error": "FILE_ACCESS_DENIED",
            },
        )
```

**Endpoint Usage Patterns:**

```python
# Pattern 1: Write operation (owner-only, workspace-scoped)
@router.post("/v1/uploads")
async def create_upload(
    current_user: Annotated[JWTClaims, Depends(require_owner())],
    request: UploadRequest,
) -> UploadResponse:
    # RBAC already validated OWNER role
    # Workspace validation implicit (creating in user's workspace)
    workspace_id = current_user.workspace_id
    ...

# Pattern 2: Read operation on specific resource (file-level access control)
@router.get("/v1/uploads/{upload_id}")
async def get_upload(
    upload_id: UUID,
    current_user: Annotated[JWTClaims, Depends(get_current_user)],
) -> UploadResponse:
    # Any authenticated user can call this endpoint
    # Must validate workspace and file access inside handler
    
    # Fetch upload session from Redis
    session = await session_store.get_session(upload_id)
    if not session:
        raise HTTPException(404, "Upload session not found")
    
    # Layer 3: Validate workspace access
    validate_workspace_access(current_user, session.workspace_id)
    
    # Layer 4: Validate file access
    # Note: validates all roles (OWNER auto-passes, COLLABORATOR checks shared_file_ids)
    validate_file_access(current_user, session.file_id)
    
    return session

# Pattern 3: List operation (filtered by workspace)
@router.get("/v1/uploads")
async def list_uploads(
    current_user: Annotated[JWTClaims, Depends(get_current_user)],
) -> list[UploadResponse]:
    # Fetch all uploads for user's workspace
    workspace_id = current_user.workspace_id
    uploads = await session_store.list_sessions(workspace_id)
    
    # Filter by file access for collaborators
    if current_user.workspace_role == WorkspaceRole.COLLABORATOR:
        uploads = [u for u in uploads if current_user.has_access_to_file(u.file_id)]
    
    return uploads
```

**Key Design Decision: Helper Functions vs Dependencies**

For this story, use **helper functions** (not dependencies) for validation:

**Why Helper Functions:**
- More flexible - can be called inside endpoint logic
- Better for conditional validation (e.g., only for collaborators)
- Easier to compose with different control flows
- Matches FastAPI HTTPException pattern

**Why Not Dependencies:**
- Dependencies must execute before handler (less flexible)
- Hard to conditionally apply (e.g., collaborator-only checks)
- Requires path parameters to be in dependency signature

**The Pattern:**
```python
# Helper function (preferred)
def validate_file_access(current_user: JWTClaims, file_id: UUID) -> None:
    if not current_user.has_access_to_file(file_id):
        raise HTTPException(403, "File access denied")

# Called in handler where needed
@router.get("/uploads/{id}")
async def get_upload(
    id: UUID,
    user: Annotated[JWTClaims, Depends(get_current_user)],
):
    session = await get_session(id)
    validate_workspace_access(user, session.workspace_id)  # Flexible placement
    validate_file_access(user, session.file_id)
    return session
```

### Previous Story Intelligence

**From Story 2.4 (RBAC Middleware):**

**Key Learnings:**

1. **Error Response Structure**: Use flat dict with `detail` and error-specific fields
   ```python
   {"detail": "...", "required_role": "owner"}
   ```

2. **Logging Strategy**:
   - Failures at WARNING level with full context
   - Success at DEBUG level to avoid log flooding
   - Always include: user_id, workspace_id, reason

3. **Defensive Checks**: Validate None values before operations
   ```python
   if current_user is None:
       raise HTTPException(401, "Invalid authentication - no user claims")
   ```

4. **Type Safety**: Full type hints for mypy --strict compliance

5. **Module Organization**:
   - One file per major component
   - Clean __init__.py exports
   - Comprehensive docstrings with usage examples

**Review Feedback Applied:**

- ✅ Flattened error response structure
- ✅ Moved success logging to DEBUG level
- ✅ Added runtime type validation
- ✅ Wrapped logging in try/except
- ✅ Clear error messages without security leaks

**Testing Pattern Established:**

```python
# Unit test structure
def test_validation_success():
    # Test happy path
    ...

def test_validation_failure_returns_403():
    # Test authorization failure
    ...

def test_error_response_format():
    # Verify error response structure
    ...

def test_logging_on_failure():
    # Verify logging behavior
    ...

# Integration test structure
async def test_endpoint_with_valid_access():
    # Test full endpoint with valid auth
    ...

async def test_endpoint_with_invalid_access_returns_403():
    # Test full endpoint with invalid auth
    ...
```

**From Story 2.3 (Redis Key Prefixing):**

**Key Insight**: Workspace isolation is enforced at EVERY layer:
- Domain entities include workspace_id
- Redis keys are prefixed with workspace_id
- This story adds: HTTP endpoint validation of workspace_id

**Pattern Consistency**: All workspace validation should follow the same principle - workspace_id must match at every layer.

**From Story 2.2 (JWT Validation):**

**Auth Stack Integration**: New components must integrate seamlessly with existing auth stack:
- Use `get_current_user` as foundation
- Return or raise - no side effects
- Clear error messages with HTTP status codes

**From Story 2.1 (Domain Entities):**

**Critical Discovery**: `JWTClaims.has_access_to_file()` already exists!

```python
def has_access_to_file(self, file_id: UUID) -> bool:
    """Check if user has access to a specific file.
    
    Owners have access to all files in their workspace.
    Collaborators only have access to files in shared_file_ids list.
    """
    if self.workspace_role == WorkspaceRole.OWNER:
        return True
    return self.shared_file_ids is not None and file_id in self.shared_file_ids
```

**DO NOT RECREATE THIS LOGIC** - Call this method from file_access_validator!

### File Structure Requirements

**Location Decisions:**

Following Clean Architecture from previous stories:

```
src/infrastructure/auth/
├── __init__.py                    # Module exports (update in this story)
├── jwt_validator.py               # Story 2.2 - JWT validation
├── rbac_middleware.py             # Story 2.4 - RBAC enforcement
├── workspace_validator.py         # NEW in this story - Workspace validation
└── file_access_validator.py       # NEW in this story - File access validation

tests/unit/infrastructure/auth/
├── __init__.py
├── test_jwt_validator.py          # Story 2.2
├── test_rbac_middleware.py        # Story 2.4
├── test_workspace_validator.py    # NEW in this story
└── test_file_access_validator.py  # NEW in this story

tests/integration/
├── test_rbac_integration.py       # Story 2.4
└── test_workspace_access_control.py  # NEW in this story
```

**Why Infrastructure Layer:**

- These are FastAPI-specific implementations
- They integrate with HTTP concerns (HTTPException, path parameters)
- They depend on framework features
- Domain layer stays pure (JWTClaims.has_access_to_file is domain logic)

**Import Structure:**

```python
# workspace_validator.py
from uuid import UUID
import structlog
from fastapi import HTTPException
from src.domain.value_objects.jwt_claims import JWTClaims

# file_access_validator.py
from uuid import UUID
import structlog
from fastapi import HTTPException
from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.workspace_role import WorkspaceRole
```

### Testing Requirements

**Test Coverage Requirements:**

From previous stories, we maintain 100% test coverage for new code.

**Unit Test Structure:**

```python
# tests/unit/infrastructure/auth/test_workspace_validator.py
import pytest
from uuid import UUID, uuid4
from src.infrastructure.auth.workspace_validator import validate_workspace_access
from src.domain.value_objects.jwt_claims import JWTClaims
from src.domain.value_objects.workspace_role import WorkspaceRole

def test_validate_workspace_access_allows_matching_workspace():
    """Test workspace validation passes when IDs match."""
    workspace_id = uuid4()
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=workspace_id,
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=9999999999,
    )
    
    # Should not raise
    validate_workspace_access(claims, workspace_id)

def test_validate_workspace_access_rejects_different_workspace():
    """Test workspace validation raises 403 when IDs don't match."""
    user_workspace = uuid4()
    resource_workspace = uuid4()
    claims = JWTClaims(
        user_id=uuid4(),
        workspace_id=user_workspace,
        workspace_role=WorkspaceRole.OWNER,
        shared_file_ids=None,
        exp=9999999999,
    )
    
    with pytest.raises(HTTPException) as exc_info:
        validate_workspace_access(claims, resource_workspace)
    
    assert exc_info.value.status_code == 403
    assert "workspace" in exc_info.value.detail["detail"].lower()

# Similar structure for test_file_access_validator.py
```

**Integration Test Structure:**

```python
# tests/integration/test_workspace_access_control.py
import pytest
from httpx import AsyncClient
from uuid import uuid4

@pytest.mark.asyncio
async def test_owner_can_access_own_workspace_resource():
    """Test owner with matching workspace_id can access resource."""
    # Create test app with protected endpoint
    # Generate JWT with workspace_id
    # Call endpoint
    # Assert 200 OK
    ...

@pytest.mark.asyncio
async def test_user_cannot_access_different_workspace_resource():
    """Test user with different workspace_id receives 403."""
    # Create test app with protected endpoint
    # Generate JWT with workspace_id A
    # Try to access resource in workspace_id B
    # Assert 403 Forbidden
    ...

@pytest.mark.asyncio
async def test_collaborator_can_access_shared_file():
    """Test collaborator with file_id in shared_file_ids can access."""
    ...

@pytest.mark.asyncio
async def test_collaborator_cannot_access_non_shared_file():
    """Test collaborator without file_id in shared_file_ids receives 403."""
    ...
```

**Testing Standard from Previous Stories:**

- Use pytest fixtures for reusable test data
- Use parametrize for multiple scenarios
- Test happy path and all error cases
- Verify error response structure
- Verify logging behavior
- Run with: `uv run pytest -v`

### Security Considerations

**Critical Security Principle: Fail Closed**

From the architecture:
> "Zero-trust model — every request validated"

All validation functions must **raise exceptions on failure**, not return booleans. This ensures:
- No forgotten checks (exception bubbles up)
- Clear error handling (403 Forbidden)
- No accidental bypasses

**Why Not Return Boolean:**

```python
# BAD - easy to forget check
if not validate_access(user, file):  # If developer forgets this check?
    raise HTTPException(403)

# GOOD - impossible to bypass
validate_access(user, file)  # Raises HTTPException automatically
```

**Security by Default:**

- COLLABORATOR role: Deny by default, allow only shared files
- Workspace validation: Deny by default, allow only matching workspace
- Never leak information: Don't reveal resource existence in error messages

**Logging for Security Audits:**

From NFR requirements, all access control failures must be logged:

```python
log.warning(
    "workspace_access_denied",
    user_id=str(current_user.user_id),
    user_workspace_id=str(current_user.workspace_id),
    resource_workspace_id=str(resource_workspace_id),
    timestamp=datetime.now(UTC).isoformat(),
)
```

This enables:
- Security incident investigation
- Access pattern analysis
- Compliance auditing

### References

**Source Documents:**

- [Epic 2](../../artifacts/planning-artifacts/epics.md#epic-2-authentication-authorization--workspace-isolation) - Complete epic context and all stories
- [Architecture Document](../../artifacts/planning-artifacts/architecture.md) - Four-layer security model and access control patterns
- [PRD](../../artifacts/planning-artifacts/prd.md) - FR22-FR26 workspace isolation requirements

**Related Stories:**

- [Story 2.1](./2-1-create-domain-entities-for-workspace-and-user-roles.md) - JWTClaims with has_access_to_file()
- [Story 2.2](./2-2-implement-jwt-validation-middleware.md) - JWT validation (Layer 1)
- [Story 2.3](./2-3-implement-workspace-scoped-redis-key-prefixing-isolation.md) - Redis workspace isolation
- [Story 2.4](./2-4-implement-rbac-middleware-for-workspace-roles.md) - RBAC (Layer 2)

**Key Architecture Sections:**

- [Authentication & Security Strategy](../../artifacts/planning-artifacts/architecture.md#authentication--security) - JWT validation and RBAC patterns
- [Multi-Tenancy & Workspace Isolation](../../artifacts/planning-artifacts/architecture.md#cross-cutting-concerns-identified) - Complete isolation requirements

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.5 (copilot)

### Debug Log References

- Story status: ready-for-dev → in-progress
- Sprint status updated: 2026-05-04T20:06:00Z

### Implementation Plan

**Architecture Design Decisions:**

1. **Component Integration**: Leveraging existing infrastructure from Stories 2.1-2.4
   - Story 2.1: JWTClaims.has_access_to_file() domain method (reuse, don't recreate)
   - Story 2.2: get_current_user JWT validation dependency
   - Story 2.4: RBAC middleware pattern for dependencies

2. **Validation Pattern**: Helper functions (not dependencies)
   - More flexible than dependencies - can be called conditionally inside handlers
   - Better for file-level checks (only needed for collaborators)
   - Consistent with HTTPException pattern from RBAC
   - Signature: `validate_*(claims: JWTClaims, resource_id: UUID) -> None`

3. **Four-Layer Security Model** (from architecture):
   ```
   Layer 1: JWT Validation (get_current_user) → 401 Unauthorized
   Layer 2: RBAC (require_owner/require_role) → 403 Forbidden (role)
   Layer 3: Workspace Validation → 403 Forbidden (workspace)
   Layer 4: File Access Validation → 403 Forbidden (file access)
   ```

4. **Error Response Structure**: Following Story 2.4 pattern
   - Flat dict: `{"detail": "...", "error": "ERROR_CODE"}`
   - No security leaks in error messages
   - Clear error codes for client handling

5. **Logging Strategy**: Following Story 2.4 pattern
   - Failures at WARNING level with full context
   - Include: user_id, workspace_id, resource details
   - No success logging to avoid log flooding

6. **Module Organization**:
   - workspace_validator.py: Workspace ID matching validation
   - file_access_validator.py: File access control using has_access_to_file()
   - Update __init__.py with new exports

### Completion Notes List

- [x] Design task: Architecture decisions documented above
- [x] Workspace validator implemented with comprehensive tests (7 tests)
- [x] File access validator implemented with comprehensive tests (11 tests)
- [x] Integration tests created (8 tests covering all scenarios)
- [x] Auth module exports updated with complete documentation
- [x] All code quality checks pass (ruff, mypy)
- [x] Full test suite passes: 183 tests, no regressions
- [x] Story implementation complete and ready for review

### File List

New files created:
- src/infrastructure/auth/workspace_validator.py
- src/infrastructure/auth/file_access_validator.py
- tests/unit/infrastructure/auth/test_workspace_validator.py
- tests/unit/infrastructure/auth/test_file_access_validator.py
- tests/integration/auth/test_workspace_access_control.py

Modified files:
- src/infrastructure/auth/__init__.py

### Review Findings

#### Patches Applied ✅

- [x] [Review][Patch] Refactor integration tests to use httpx AsyncClient — **FIXED**. Tests now make real HTTP requests through AsyncClient to validate complete dependency chain: HTTP request → JWT extraction → dependency resolution → handlers → HTTP response. [tests/integration/auth/test_workspace_access_control.py]

- [x] [Review][Patch] Add update/delete endpoints demonstrating workspace validation pattern — **FIXED**. Added DELETE and PATCH endpoints that demonstrate `require_owner()` + `validate_workspace_access()` composition. Tests verify cross-workspace access is blocked. [tests/integration/auth/test_workspace_access_control.py]

- [x] [Review][Patch] 404 returned before workspace validation leaks resource existence — **FIXED**. Refactored GET endpoint to validate workspace access before checking resource existence. Returns 403 for unauthorized access, preventing resource ID enumeration. [tests/integration/auth/test_workspace_access_control.py:84-86]

- [x] [Review][Patch] Inconsistent file access validation pattern in documentation — **FIXED**. Removed conditional check from documentation, now shows unconditional validation pattern that works for all roles. [artifacts/implementation-artifacts/2-5-implement-workspace-access-control-rules.md:305]

- [x] [Review][Patch] No defensive error handling around logging operations — **FIXED**. Wrapped all `log.warning()` calls in try/except blocks to prevent denial of service if logging fails. [src/infrastructure/auth/workspace_validator.py:92-98, file_access_validator.py:105-111]

- [x] [Review][Patch] Missing None validation for resource IDs — **FIXED**. Added None checks for `resource_workspace_id` and `file_id` parameters with appropriate 400 Bad Request errors. [src/infrastructure/auth/workspace_validator.py:91, file_access_validator.py:103]

- [x] [Review][Patch] Test cleanup is fragile with module-level mutable state — **FIXED**. Converted MOCK_SESSIONS to pytest fixture with autouse cleanup. All tests now have isolated, reliable test data. [tests/integration/auth/test_workspace_access_control.py:34]

#### Deferred

- [x] [Review][Defer] No integration test for owner write operations — `create_upload` endpoint has no test validating owner write operations through full auth stack. **Deferred**: No upload endpoints exist yet to test POST/PATCH/DELETE. Will be covered when upload API is implemented. [tests/integration/auth/test_workspace_access_control.py]

- [x] [Review][Defer] Usage examples in docstrings are not tested — Module docstrings show example code that's never validated. Examples could be wrong or outdated. **Deferred**: Doctest or example validation is not in scope for this story. Consider for future quality improvement. [src/infrastructure/auth/__init__.py, workspace_validator.py, file_access_validator.py]

- [x] [Review][Defer] No performance consideration for large shared_file_ids — COLLABORATOR validation uses `in` operator on tuple - O(n) lookup. With large lists (1000+ files), performance could degrade. **Deferred**: Performance optimization not required for initial implementation. Premature optimization until proven bottleneck. [src/infrastructure/auth/file_access_validator.py]

- [x] [Review][Defer] No rate limiting or DOS protection — Validators make no attempt to prevent brute-force enumeration attacks. **Deferred**: Rate limiting is infrastructure/middleware concern, not access control validation concern. Should be handled at API gateway or FastAPI middleware layer. [src/infrastructure/auth/workspace_validator.py, file_access_validator.py]
