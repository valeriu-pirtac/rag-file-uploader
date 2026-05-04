# Story 2.3: Implement Workspace-Scoped Redis Key Prefixing (Isolation)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **developer**,
I want **all Redis keys scoped to workspace_id from the start**,
So that **session state, deduplication, and rate limits are completely isolated by design**.

## Acceptance Criteria

1. **Given** workspace isolation requirements
   **When** Redis key helper is implemented
   **Then** src/infrastructure/redis/key_builder.py exists with workspace-scoped key functions

2. **And** session keys: `session:workspace_{workspace_id}:document_{document_id}`

3. **And** dedup keys: `dedup:workspace_{workspace_id}`

4. **And** rate limit keys: `ratelimit:workspace_{workspace_id}:active_uploads`

5. **And** all key builder functions validate workspace_id is present

6. **And** key patterns follow snake_case with colon separators (implementation pattern #2)

7. **And** no Redis key can be created without workspace scope

8. **And** satisfies FR26 (isolation at session state layer) and NFR-S5

## Tasks / Subtasks

- [x] Create domain validation for WorkspaceId (AC: #5, #7)
  - [x] Evaluate if workspace_id validation belongs in domain layer or key_builder
  - [x] If domain layer: Create src/domain/value_objects/workspace_id.py (lightweight UUID wrapper)
  - [x] If infrastructure: Add validation directly in key_builder functions
  - [x] Ensure workspace_id cannot be None/empty before key creation
  - [x] Raise appropriate error if workspace_id is invalid

- [x] Create Redis key builder infrastructure component (AC: #1, #2, #3, #4, #5, #6, #7)
  - [x] Create src/infrastructure/redis/key_builder.py
  - [x] Implement session_key(workspace_id: UUID, document_id: UUID) -> str
    - Pattern: `session:workspace_{workspace_id}:document_{document_id}`
    - Validate both workspace_id and document_id are present
    - Return formatted key string
  - [x] Implement dedup_key(workspace_id: UUID) -> str
    - Pattern: `dedup:workspace_{workspace_id}`
    - Validate workspace_id is present
    - Return formatted key string
  - [x] Implement rate_limit_key(workspace_id: UUID) -> str
    - Pattern: `ratelimit:workspace_{workspace_id}:active_uploads`
    - Validate workspace_id is present
    - Return formatted key string
  - [x] Ensure all functions use snake_case with colon separators (Implementation Pattern #2)
  - [x] Add type hints for all functions (mypy compliance)
  - [x] Add docstrings with examples for each function

- [x] Create key builder validation logic (AC: #5, #7)
  - [x] Create _validate_workspace_id() private helper function
  - [x] Check workspace_id is not None
  - [x] Check workspace_id is valid UUID
  - [x] Raise ValueError with clear message if invalid
  - [x] Use this validation in all key builder functions
  - [x] Add _validate_document_id() for session keys

- [x] Create comprehensive unit tests (testing standard)
  - [x] Create tests/unit/infrastructure/redis/__init__.py
  - [x] Create tests/unit/infrastructure/redis/test_key_builder.py
    - [x] Test session_key() generates correct pattern
    - [x] Test session_key() with valid UUIDs
    - [x] Test session_key() raises error on None workspace_id
    - [x] Test session_key() raises error on None document_id
    - [x] Test dedup_key() generates correct pattern
    - [x] Test dedup_key() with valid UUID
    - [x] Test dedup_key() raises error on None workspace_id
    - [x] Test rate_limit_key() generates correct pattern
    - [x] Test rate_limit_key() with valid UUID
    - [x] Test rate_limit_key() raises error on None workspace_id
    - [x] Test all keys use snake_case with colons
    - [x] Test workspace isolation: same document_id, different workspaces produce different keys
    - [x] Test key uniqueness within workspace

- [x] Update Redis module __init__.py for clean imports (code organization)
  - [x] Update src/infrastructure/redis/__init__.py
  - [x] Export key_builder functions for easy import
  - [x] Add module docstring explaining Redis isolation strategy

- [x] Document key patterns in code (developer guidance)
  - [x] Add comprehensive module docstring in key_builder.py
  - [x] Document all three key patterns with examples
  - [x] Explain workspace isolation guarantees
  - [x] Reference FR26 and NFR-S5 requirements
  - [x] Add usage examples in docstring

### Review Findings

Code review completed: 2026-05-04

**Decision Needed:**
- [x] [Review][Decision][RESOLVED] Out-of-scope JWT error handling changes included — DECISION: Removed from commit to keep Story 2.3 scope clean. JWT improvements should be tracked separately.

**Patch:**
- [x] [Review][Patch] NIL UUID accepted as valid identifier [key_builder.py:35-65] — FIXED: Added validation to reject NIL UUID (00000000-0000-0000-0000-000000000000) in both _validate_workspace_id and _validate_document_id functions.
- [x] [Review][Patch] Missing TypeError tests for string UUIDs [test_key_builder.py] — FIXED: Added tests verifying session_key("uuid-string", ...) raises TypeError for all three key functions.
- [x] [Review][Patch] No TTL documentation in key builder functions [key_builder.py] — FIXED: Added TTL notes to all three function docstrings clarifying caller responsibility.

**Deferred:**
- [x] [Review][Defer] Workspace and document ID can be identical [key_builder.py:71] — deferred, pre-existing — No validation preventing `session_key(same_uuid, same_uuid)`. While technically valid (UUIDs are unique), this likely indicates caller bug. Defer as this is a calling code validation concern, not key builder responsibility.
- [x] [Review][Defer] UUID subclass validation gap [key_builder.py:45] — deferred, pre-existing — `isinstance(workspace_id, UUID)` accepts subclasses with overridden `__str__()`. If custom UUID subclass changes formatting, key patterns could break. Defer as this is theoretical - no UUID subclasses exist in project, and consumers control their UUID types.
- [x] [Review][Defer] Key collision risk with future features [key_builder.py] — deferred, pre-existing — Simple prefixes (`session:`, `dedup:`, `ratelimit:`) have no namespace governance. Future features could cause collisions. Defer as this is architectural concern for future stories, not actionable in current scope.
- [x] [Review][Defer] UUID case variation in logging vs keys [main.py:63-66, key_builder.py:77] — deferred, pre-existing — Theoretical issue if custom UUID subclass overrides `__str__()` to uppercase - logs wouldn't match Redis keys. Defer as no such subclasses exist and Python UUID standard guarantees lowercase.

## Dev Notes

### Architecture Requirements

**Multi-Tenant Isolation from Day 1:**

This story is **foundational for the entire application's security model**. From the architecture document:

> "Workspace isolation enforced at every layer (storage paths, Redis keys, deduplication scope, rate limits) — no retrofitting required"

**Critical Pattern:** Every Redis key MUST be scoped to workspace_id. This prevents cross-tenant data leakage and enforces the security boundary defined in FR26:

> "FR26: The system enforces complete data isolation between workspaces at storage path, session state, deduplication scope, and rate limit boundaries"

**Why This Matters:**

- **Session State Isolation**: Two workspaces with same document_id will have completely separate session state
- **Deduplication Scope**: SHA-256 fingerprints are checked only within workspace (workspace A can upload same file as workspace B)
- **Rate Limiting**: Each workspace has independent rate limit counters (workspace A hitting limit doesn't affect workspace B)

**Clean Architecture Boundaries:**

This is an **infrastructure** component that will be used by:
- Session Store (Story 3.2) - will use `session_key()` for all Redis operations
- Deduplication Service (future story) - will use `dedup_key()` for fingerprint lookups
- Rate Limiter (Story 3.3) - will use `rate_limit_key()` for counter operations

The key builder has **zero dependencies** on domain logic - it's a pure infrastructure utility.

### Technical Stack & Patterns

**Python Environment:**
- Python 3.13 with uv package manager
- Type hints required on all functions (mypy --strict enforcement)
- Use UUID type from uuid module (not strings)
- Follow existing project patterns from Stories 2.1 and 2.2

**Redis Key Pattern (Implementation Pattern #2):**

From architecture document:
```
Pattern: category:scope:resource_{id}:attribute
Examples:
  session:workspace_{workspace_id}:document_{document_id}
  dedup:workspace_{workspace_id}
  ratelimit:workspace_{workspace_id}:active_uploads
```

**Key Pattern Rules:**
1. **snake_case** for all components (not camelCase, not kebab-case)
2. **Colon separators** between segments (standard Redis convention)
3. **Curly braces** for variable placeholders (e.g., `{workspace_id}`)
4. **UUID formatting**: Use standard UUID string representation (lowercase, with hyphens)

**Example Implementation Pattern:**

```python
from uuid import UUID

def session_key(workspace_id: UUID, document_id: UUID) -> str:
    """Generate workspace-scoped session key for upload session.
    
    Args:
        workspace_id: Workspace UUID for isolation boundary
        document_id: Document UUID
        
    Returns:
        Redis key string: session:workspace_{workspace_id}:document_{document_id}
        
    Raises:
        ValueError: If workspace_id or document_id is None
        
    Examples:
        >>> from uuid import UUID
        >>> ws = UUID('12345678-1234-5678-1234-567812345678')
        >>> doc = UUID('87654321-8765-4321-8765-432187654321')
        >>> session_key(ws, doc)
        'session:workspace_12345678-1234-5678-1234-567812345678:document_87654321-8765-4321-8765-432187654321'
    """
    if workspace_id is None:
        raise ValueError("workspace_id cannot be None")
    if document_id is None:
        raise ValueError("document_id cannot be None")
    return f"session:workspace_{workspace_id}:document_{document_id}"
```

**Validation Strategy:**

The acceptance criteria require validation that workspace_id is present (AC #5, #7). Two options:

1. **Option A - Infrastructure Validation**: Validate in key_builder functions directly (simpler, faster)
2. **Option B - Domain Value Object**: Create WorkspaceId value object (more DDD-pure, reusable)

**RECOMMENDATION:** Option A (infrastructure validation) for this story:
- Faster implementation
- Clear error messages at point of use
- No domain layer changes needed
- Validation happens where it matters (key creation)
- Can refactor to value object later if needed elsewhere

If you choose Option B, follow the pattern from JWTClaims (Story 2.1):
```python
# src/domain/value_objects/workspace_id.py
from dataclasses import dataclass
from uuid import UUID

@dataclass(frozen=True)
class WorkspaceId:
    """Value object for workspace identifier with validation."""
    value: UUID
    
    def __post_init__(self) -> None:
        if not isinstance(self.value, UUID):
            raise TypeError("workspace_id must be a UUID")
```

### Previous Story Intelligence

**From Story 2.2 (JWT Validation Middleware):**

**Pattern Established:**
- All infrastructure components are in `src/infrastructure/<service>/`
- Type hints on all functions (enforced by mypy)
- Comprehensive docstrings with examples
- Unit tests in `tests/unit/infrastructure/<service>/`
- Clean imports via `__init__.py` exports

**Code Organization Pattern:**
```python
# src/infrastructure/auth/__init__.py
"""Authentication infrastructure - JWT validation."""

from src.infrastructure.auth.jwt_validator import JWTValidator

__all__ = ["JWTValidator"]
```

**Testing Pattern from Story 2.2:**
- One test file per implementation file
- Test happy paths with valid inputs
- Test error cases (None, invalid types)
- Test boundary conditions
- Use pytest parametrize for multiple test cases
- Clear test names: `test_<function>_<scenario>`

**From Story 2.1 (Domain Entities):**

**Value Object Pattern:**
- Frozen dataclasses for immutability
- Validation in `__post_init__`
- Clear error messages with TypeError/ValueError
- Type hints for all attributes

**Latest Git Intelligence (Last 10 Commits):**

Recent commits show the established workflow:
```
966e8b2 - Merge PR #17 US#2.2 (JWT Validation)
04b2bff - US#2.2 Implementation
1753541 - Merge PR #16 US#2.1 (Domain Entities)
322242b - US#2.1 Implementation
```

**Pattern Observed:** Each story is implemented on a branch, then merged via PR. Code reviews are thorough (see deferred-work.md files).

### Implementation Patterns to Follow

**1. File Organization:**
```
src/infrastructure/redis/
├── __init__.py          # Clean exports, module docstring
└── key_builder.py       # Key generation functions
```

**2. Function Signature Pattern:**
```python
def function_name(required_param: Type, optional_param: Type | None = None) -> ReturnType:
    """Single-line summary.
    
    Detailed explanation if needed. Reference FRs/NFRs if applicable.
    
    Args:
        required_param: Description of parameter
        optional_param: Description of optional parameter
        
    Returns:
        Description of return value with example
        
    Raises:
        ExceptionType: When and why this is raised
        
    Examples:
        >>> example usage
        'expected output'
    """
```

**3. Validation Pattern:**
```python
def _validate_workspace_id(workspace_id: UUID | None) -> None:
    """Validate workspace_id is present and valid UUID.
    
    Args:
        workspace_id: Workspace UUID to validate
        
    Raises:
        ValueError: If workspace_id is None or invalid
    """
    if workspace_id is None:
        raise ValueError("workspace_id cannot be None - required for isolation")
    if not isinstance(workspace_id, UUID):
        raise TypeError(f"workspace_id must be UUID, got {type(workspace_id).__name__}")
```

**4. Testing Pattern:**
```python
import pytest
from uuid import UUID, uuid4
from src.infrastructure.redis.key_builder import session_key

def test_session_key_generates_correct_pattern():
    """Test session_key generates workspace-scoped key pattern."""
    ws_id = UUID('12345678-1234-5678-1234-567812345678')
    doc_id = UUID('87654321-8765-4321-8765-432187654321')
    
    key = session_key(ws_id, doc_id)
    
    assert key == f"session:workspace_{ws_id}:document_{doc_id}"
    assert key.startswith("session:workspace_")
    assert f":document_{doc_id}" in key

def test_session_key_raises_error_on_none_workspace_id():
    """Test session_key raises ValueError when workspace_id is None."""
    doc_id = uuid4()
    
    with pytest.raises(ValueError, match="workspace_id cannot be None"):
        session_key(None, doc_id)

@pytest.mark.parametrize("workspace_id,document_id", [
    (uuid4(), uuid4()),
    (uuid4(), uuid4()),
    (uuid4(), uuid4()),
])
def test_session_key_uniqueness(workspace_id, document_id):
    """Test each workspace+document combination produces unique key."""
    key = session_key(workspace_id, document_id)
    assert workspace_id in key
    assert document_id in key
```

### Redis Context from Architecture

**From Architecture Decision Document:**

**Session State Schema (AC #2):**
```
Key: session:workspace_{workspace_id}:document_{document_id}
Type: Redis Hash
Fields: filename, size, mime_type, sha256_checksum, offset, status, created_at, expires_at, chunk_manifest
TTL: 86400 seconds (24 hours)
```

This key pattern will be used by Story 3.2 (Session Store) for all HSET, HGET, HGETALL operations.

**Deduplication Storage (AC #3):**
```
Key: dedup:workspace_{workspace_id}
Type: Redis Hash
Field: {sha256_checksum} → JSON {file_id, s3_path, size, uploaded_at}
```

This enables O(1) duplicate detection within workspace boundary using HEXISTS/HGET.

**Rate Limiting (AC #4):**
```
Key: ratelimit:workspace_{workspace_id}:active_uploads
Type: Redis String (counter)
Operations: INCR (on upload start), DECR (on complete/abort)
```

Used by Story 3.3 to enforce MAX_CONCURRENT_UPLOADS per workspace (default: 10).

**Why These Patterns Matter:**

1. **Consistent Prefixing**: All keys start with category (session, dedup, ratelimit)
2. **Workspace Scoping**: All keys include `workspace_{workspace_id}` segment
3. **Resource Identification**: Session keys include `document_{document_id}`, dedup keys use hash fields
4. **Future-Proof**: Pattern allows adding new categories without conflicts (e.g., `cache:workspace_{id}:*`)

### Performance Considerations

**NFR-S5 (Security Requirement):**
> "Multi-tenant isolation: Upload session state, deduplication fingerprints, and rate limit counters must be workspace-scoped at the Redis key level"

**Key Generation Performance:**
- String formatting with f-strings is O(n) where n is string length
- UUID string conversion is O(1)
- Total key generation time: <1μs (microsecond)
- No performance concern for this implementation

**Redis Key Length:**
- Example session key: `session:workspace_12345678-1234-5678-1234-567812345678:document_87654321-8765-4321-8765-432187654321`
- Length: ~95 characters
- Redis key length limit: 512 MB (practically unlimited)
- Our keys: Well under 1 KB, no concern

### Error Handling Requirements

**Validation Errors:**

Based on AC #5 and #7 (validate workspace_id is present, no key without workspace scope):

```python
# Required error cases to handle:
1. workspace_id is None → ValueError("workspace_id cannot be None - required for isolation")
2. document_id is None (session_key only) → ValueError("document_id cannot be None")
3. workspace_id wrong type → TypeError("workspace_id must be UUID, got <type>")
```

**Why These Errors:**
- **ValueError**: For logical errors (None values, business rule violations)
- **TypeError**: For type mismatches (passing string instead of UUID)
- Clear messages help developers debug integration issues quickly

### Integration Points

**This key_builder.py will be imported by:**

1. **Story 3.2 - Redis Session Store** (next story):
   ```python
   from src.infrastructure.redis.key_builder import session_key
   
   class RedisSessionStore:
       async def create_session(self, session: UploadSession) -> None:
           key = session_key(session.workspace_id, session.document_id)
           await self.redis.hset(key, mapping=session.to_dict())
           await self.redis.expire(key, 86400)
   ```

2. **Story 3.3 - Rate Limiter**:
   ```python
   from src.infrastructure.redis.key_builder import rate_limit_key
   
   async def check_rate_limit(workspace_id: UUID) -> bool:
       key = rate_limit_key(workspace_id)
       count = await redis.incr(key)
       return count <= MAX_CONCURRENT_UPLOADS
   ```

3. **Future Deduplication Service**:
   ```python
   from src.infrastructure.redis.key_builder import dedup_key
   
   async def check_duplicate(workspace_id: UUID, sha256: str) -> bool:
       key = dedup_key(workspace_id)
       return await redis.hexists(key, sha256)
   ```

**Critical:** These functions must be reliable and correct - errors here will cause:
- Session state corruption (wrong key = lost upload progress)
- Security violations (missing workspace scope = data leakage)
- Rate limit bypasses (wrong counter key = limit not enforced)

### Testing Strategy

**Unit Test Coverage Requirements:**

1. **Happy Path Tests** (valid inputs, correct output):
   - All three functions with valid UUIDs
   - Verify exact key pattern format
   - Verify workspace_id and upload_id appear in result

2. **Error Case Tests** (invalid inputs, proper errors):
   - None workspace_id for all functions
   - None document_id for session_key
   - Wrong types (string instead of UUID)

3. **Isolation Tests** (security validation):
   - Same document_id in different workspaces produces different keys
   - Keys contain full workspace_id (no truncation)
   - No collision possible between workspaces

4. **Pattern Compliance Tests** (implementation standards):
   - snake_case verification (no camelCase, no kebab-case)
   - Colon separators (not dashes, not underscores)
   - UUID format (lowercase with hyphens)

**Test File Structure:**
```python
# tests/unit/infrastructure/redis/test_key_builder.py

import pytest
from uuid import UUID, uuid4
from src.infrastructure.redis.key_builder import (
    session_key,
    dedup_key,
    rate_limit_key,
)

class TestSessionKey:
    """Tests for session_key() function."""
    
    def test_generates_correct_pattern(self):
        """Test session_key follows pattern: session:workspace_{id}:document_{id}"""
        ...
    
    def test_validates_workspace_id_not_none(self):
        """Test session_key raises ValueError when workspace_id is None."""
        ...
    
    def test_validates_document_id_not_none(self):
        """Test session_key raises ValueError when document_id is None."""
        ...
    
    def test_workspace_isolation(self):
        """Test same document_id in different workspaces produces different keys."""
        ...

class TestDedupKey:
    """Tests for dedup_key() function."""
    ...

class TestRateLimitKey:
    """Tests for rate_limit_key() function."""
    ...
```

### Definition of Done

Before marking this story complete, verify:

- ✅ All three key functions implemented (session, dedup, rate_limit)
- ✅ All functions validate workspace_id is not None
- ✅ All keys follow snake_case with colon separators
- ✅ All keys include workspace_{workspace_id} segment
- ✅ Type hints on all functions
- ✅ Docstrings with examples on all functions
- ✅ Unit tests achieve >95% coverage
- ✅ All tests passing (pytest)
- ✅ Type checking passing (mypy)
- ✅ Linting passing (ruff)
- ✅ Module exports configured in __init__.py
- ✅ No existing functionality broken

### Known Considerations from Previous Reviews

**From Story 2.2 Deferred Work:**

No directly applicable items - Story 2.2 was about JWT validation. However, learned that:
- Reviews focus on security and validation
- Type safety is critical (mypy enforcement)
- Clear error messages expected
- Performance considerations noted when relevant

**From Story 2.1 Deferred Work:**

> "Avoid awkward manual UUID generation - Standard pattern for DDD when reconstructing from DB, default factories are often omitted."

This suggests: Don't over-engineer UUID handling. Using UUID type directly (not wrapped in value object) is acceptable for infrastructure utilities.

### Reference Documentation

**Functional Requirements:**
- FR26: Complete data isolation between workspaces at session state, deduplication scope, and rate limit boundaries

**Non-Functional Requirements:**
- NFR-S5: Multi-tenant isolation enforced at Redis key level

**Architecture Patterns:**
- Implementation Pattern #2: Redis Key Naming (section in architecture.md)

**Related Stories:**
- Story 2.1: Domain entities (Workspace, JWTClaims) - provides workspace_id type context
- Story 2.2: JWT validation - provides workspace_id from authenticated requests
- Story 3.2: Redis Session Store (NEXT) - primary consumer of session_key()
- Story 3.3: Rate Limiting (SOON) - primary consumer of rate_limit_key()

### Project Context Reference

For complete project setup, dependencies, and architectural decisions, see:
- Root README.md (project overview, setup instructions)
- Architecture document: `artifacts/planning-artifacts/architecture.md`
- PRD document: `artifacts/planning-artifacts/prd.md`
- Epic breakdown: `artifacts/planning-artifacts/epics.md`

## Story Completion Status

**Status:** ready-for-dev

**Context Analysis Completed:** ✅
- All planning artifacts analyzed
- Architecture patterns extracted
- Previous stories reviewed for established patterns
- Integration points identified
- Testing strategy defined

**Developer has everything needed for flawless implementation:**
- ✅ Clear acceptance criteria with specific key patterns
- ✅ Detailed implementation patterns from previous stories
- ✅ Redis architecture decisions documented
- ✅ Testing requirements and examples provided
- ✅ Error handling specifications defined
- ✅ Integration points with future stories explained
- ✅ Definition of done checklist included

**Next Step:** Run `dev-story` workflow to implement this story.

## Dev Agent Record

### Implementation Plan

**Technical Approach:**
Implemented Option A (infrastructure validation) as recommended in Dev Notes:
- Validation performed directly in key_builder functions (simpler, faster)
- No domain value object created for WorkspaceId
- Clear error messages at point of use
- Consistent with existing UUID usage patterns in the codebase

**Implementation Strategy:**
1. RED Phase: Created comprehensive unit tests (22 test cases) covering all acceptance criteria
2. GREEN Phase: Implemented key_builder.py with three key functions and validation
3. REFACTOR Phase: Updated module exports, ran type checking and linting

**Key Decisions:**
- Used infrastructure validation (_validate_workspace_id, _validate_document_id) over domain value objects
- Followed Implementation Pattern #2: snake_case with colon separators
- All UUIDs formatted as lowercase with hyphens (standard representation)
- Comprehensive docstrings with examples and FR/NFR references

### Completion Notes

✅ **All Tasks Complete:**
- Created src/infrastructure/redis/key_builder.py with 3 key generation functions
- Implemented validation logic (_validate_workspace_id, _validate_document_id)
- Created 22 comprehensive unit tests (100% coverage)
- Updated src/infrastructure/redis/__init__.py with clean exports
- All tests pass (106/106 unit tests including existing tests)
- Type checking passes (mypy --strict)
- Linting passes (ruff)
- No regressions detected

**Security Validation:**
- ✅ All keys require workspace_id (FR26 compliance)
- ✅ Workspace isolation verified (same document_id, different workspaces = different keys)
- ✅ No key can be created without workspace scope (NFR-S5 compliance)
- ✅ Validation raises clear errors for None/invalid values

**Pattern Compliance:**
- ✅ snake_case with colon separators (Implementation Pattern #2)
- ✅ UUID format: lowercase with hyphens
- ✅ Type hints on all functions (mypy compliance)
- ✅ Comprehensive docstrings with examples

**Integration Readiness:**
- ✅ Functions exported via __all__ in __init__.py
- ✅ Ready for Story 3.2 (Redis Session Store) to use session_key()
- ✅ Ready for Story 3.3 (Rate Limiter) to use rate_limit_key()
- ✅ Ready for future Deduplication Service to use dedup_key()

### File List

**Files Created:**
- src/infrastructure/redis/key_builder.py
- tests/unit/infrastructure/redis/__init__.py
- tests/unit/infrastructure/redis/test_key_builder.py

**Files Updated:**
- src/infrastructure/redis/__init__.py (added key_builder exports and updated docstring)

## Change Log

**Date:** 2026-05-04

**Summary:** Implemented workspace-scoped Redis key prefixing for multi-tenant isolation with comprehensive validation and test coverage.

**Changes:**
1. Created Redis key builder infrastructure component (src/infrastructure/redis/key_builder.py)
2. Implemented three key generation functions:
   - session_key(workspace_id, document_id) → session:workspace_{id}:document_{id}
   - dedup_key(workspace_id) → dedup:workspace_{id}
   - rate_limit_key(workspace_id) → ratelimit:workspace_{id}:active_uploads
3. Implemented validation helpers (_validate_workspace_id, _validate_document_id)
4. Created 22 comprehensive unit tests covering all acceptance criteria
5. Updated Redis module __init__.py with clean exports
6. All code passes mypy type checking and ruff linting
7. Zero regressions: All 106 unit tests pass
8. Foundational security component for workspace isolation (FR26, NFR-S5)

**Acceptance Criteria Status:**
- ✅ AC #1: src/infrastructure/redis/key_builder.py exists with workspace-scoped functions
- ✅ AC #2: Session keys follow pattern: session:workspace_{workspace_id}:document_{document_id}
- ✅ AC #3: Dedup keys follow pattern: dedup:workspace_{workspace_id}
- ✅ AC #4: Rate limit keys follow pattern: ratelimit:workspace_{workspace_id}:active_uploads
- ✅ AC #5: All key builder functions validate workspace_id is present
- ✅ AC #6: Key patterns use snake_case with colon separators
- ✅ AC #7: No Redis key can be created without workspace scope
- ✅ AC #8: Satisfies FR26 (isolation at session state layer) and NFR-S5
