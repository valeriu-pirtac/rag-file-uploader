# Story 3.1: Create Upload Session Domain Entities and Value Objects

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **developer**,
I want **domain entities for upload sessions, chunks, and related value objects**,
So that **business logic is independent of infrastructure**.

## Acceptance Criteria

1. **Given** the domain layer exists
   **When** upload session entities are created
   **Then** src/domain/entities/upload_session.py exists with UploadSession entity

2. **And** UploadSession includes: session_id, workspace_id, filename, size, mime_type, sha256_checksum, offset, status, created_at, expires_at, chunk_manifest

3. **And** src/domain/value_objects/session_status.py exists with SessionStatus enum (PENDING, IN_PROGRESS, COMPLETE, FAILED, ABORTED)

4. **And** src/domain/value_objects/sha256_hash.py exists with SHA256Hash value object for checksum validation

5. **And** src/domain/exceptions.py includes ChecksumMismatchError, SessionNotFoundError, FileSizeLimitExceededError, UnsupportedMediaTypeError

6. **And** all entities follow Clean Architecture principles with no infrastructure dependencies

## Tasks / Subtasks

- [x] Design upload session domain model (AC: #1, #2, #6)
  - [x] Review Epic 3 requirements for complete upload session lifecycle
  - [x] Review architecture.md for domain entity patterns and requirements
  - [x] Review existing domain entities (workspace.py) for consistency patterns
  - [x] Review existing value objects (workspace_role.py, jwt_claims.py) for patterns
  - [x] Define UploadSession entity attributes with proper types
  - [x] Define status lifecycle transitions (PENDING → IN_PROGRESS → COMPLETE/FAILED/ABORTED)
  - [x] Determine chunk_manifest structure (list of chunk metadata)
  - [x] Document entity relationships and dependencies

- [x] Create SessionStatus value object (AC: #3)
  - [x] Create src/domain/value_objects/session_status.py
  - [x] Implement SessionStatus as StrEnum (consistent with WorkspaceRole pattern)
  - [x] Define states: PENDING, IN_PROGRESS, COMPLETE, FAILED, ABORTED
  - [x] Add comprehensive docstrings explaining each status
  - [x] Document valid state transitions
  - [x] Add type hints throughout
  - [x] Add __init__.py exports if needed

- [x] Create SHA256Hash value object (AC: #4)
  - [x] Create src/domain/value_objects/sha256_hash.py
  - [x] Implement SHA256Hash as immutable value object (@dataclass(frozen=True))
  - [x] Store hash as lowercase hex string (64 characters)
  - [x] Implement validation in __post_init__: must be exactly 64 hex chars
  - [x] Implement from_bytes(data: bytes) classmethod for computing hash
  - [x] Implement __str__ and __repr__ for debugging
  - [x] Implement __eq__ and __hash__ for comparison and dict keys
  - [x] Use hashlib.sha256() for computation (standard library)
  - [x] Add comprehensive docstrings and type hints
  - [x] Add __init__.py exports if needed

- [x] Create UploadSession domain entity (AC: #1, #2, #6)
  - [x] Create src/domain/entities/upload_session.py
  - [x] Implement UploadSession as @dataclass(frozen=False) (mutable for offset updates)
  - [x] Define attributes:
    - session_id: UUID (unique identifier, UUID v4)
    - workspace_id: UUID (from Workspace entity - isolation boundary)
    - filename: str (original filename for display)
    - size: int (total file size in bytes, validated ≤ 1 GB)
    - mime_type: str (must be "application/pdf" per FR15)
    - sha256_checksum: SHA256Hash (final file checksum for deduplication)
    - offset: int (current verified byte offset, starts at 0)
    - status: SessionStatus (lifecycle status, starts at PENDING)
    - created_at: datetime (UTC timezone-aware)
    - expires_at: datetime (UTC timezone-aware, 24 hours after creation)
    - chunk_manifest: list[dict[str, Any]] (list of verified chunks with index, size, checksum)
  - [x] Implement __post_init__ validation:
    - session_id and workspace_id must be UUID instances
    - size must be > 0 and ≤ 1_073_741_824 (1 GB, FR14)
    - mime_type must be "application/pdf" (FR15)
    - offset must be ≥ 0 and ≤ size
    - created_at and expires_at must be timezone-aware UTC
    - expires_at must be after created_at
    - chunk_manifest must be a list
  - [x] Implement domain methods:
    - add_chunk(chunk_index: int, chunk_size: int, chunk_checksum: str) -> None
    - update_offset(new_offset: int) -> None (validates new_offset ≤ size)
    - mark_in_progress() -> None (status transition)
    - mark_complete() -> None (status transition, offset must equal size)
    - mark_failed() -> None (status transition)
    - mark_aborted() -> None (status transition)
    - is_expired(current_time: datetime) -> bool (checks if past expires_at)
    - is_complete() -> bool (offset == size and status == COMPLETE)
  - [x] Add comprehensive docstrings explaining business logic
  - [x] Follow patterns from workspace.py (frozen dataclass, validation)
  - [x] Add __init__.py exports if needed

- [x] Update domain exceptions (AC: #5)
  - [x] Open src/domain/exceptions.py (already exists from Story 2.1)
  - [x] Verify ChecksumMismatchError exists (already added from previous stories)
  - [x] Verify UploadSessionNotFoundError exists (might be named SessionNotFoundError)
  - [x] Add FileSizeLimitExceededError if missing:
    - Inherit from DomainException
    - Accept file_size and max_size parameters
    - Include both sizes in error message
  - [x] Add UnsupportedMediaTypeError if missing:
    - Inherit from DomainException
    - Accept provided_mime_type and allowed_mime_types parameters
    - Include clear error message
  - [x] Ensure all exceptions follow naming pattern: {Error}Error
  - [x] Add comprehensive docstrings
  - [x] Add type hints for exception parameters

- [x] Create comprehensive unit tests (AC: #6, testing standards)
  - [x] Create tests/unit/domain/value_objects/test_session_status.py
    - Test all status enum values exist
    - Test status string representations
    - Test comparison operations
  - [x] Create tests/unit/domain/value_objects/test_sha256_hash.py
    - Test creation with valid 64-char hex string
    - Test validation rejects invalid lengths
    - Test validation rejects non-hex characters
    - Test from_bytes() classmethod with known test data
    - Test immutability (frozen dataclass)
    - Test equality comparison
    - Test hash() for dict key usage
    - Test __str__ and __repr__
  - [x] Create tests/unit/domain/entities/test_upload_session.py
    - Test creation with valid attributes
    - Test validation: size > 1 GB raises FileSizeLimitExceededError
    - Test validation: mime_type != "application/pdf" raises UnsupportedMediaTypeError
    - Test validation: offset > size raises ValueError
    - Test validation: created_at/expires_at must be timezone-aware
    - Test validation: expires_at must be after created_at
    - Test add_chunk() appends to chunk_manifest correctly
    - Test update_offset() updates offset and validates ≤ size
    - Test status transitions: mark_in_progress(), mark_complete(), etc.
    - Test is_expired() with current_time before/after expires_at
    - Test is_complete() returns True when offset == size and status == COMPLETE
    - Test mark_complete() validates offset == size before transitioning
  - [x] Run tests: pytest tests/unit/domain/ -v
  - [x] Verify all tests pass
  - [x] Verify test coverage ≥ 90% for new modules

- [x] Code quality checks (development standards)
  - [x] Run: ruff check src/domain/entities/upload_session.py src/domain/value_objects/session_status.py src/domain/value_objects/sha256_hash.py
  - [x] Run: ruff format src/domain/ (auto-fix formatting)
  - [x] Run: mypy src/domain/ --strict (ensure no type errors)
  - [x] Verify PEP 8 compliance (snake_case, proper imports)
  - [x] Verify all public APIs have comprehensive docstrings
  - [x] Verify no unused imports or variables
  - [x] Run full test suite: pytest (ensure no regressions)

- [x] Documentation updates
  - [x] Add inline documentation for all domain methods
  - [x] Document status lifecycle in SessionStatus docstring
  - [x] Document SHA256Hash validation rules in docstring
  - [x] Add usage examples in module docstrings if helpful

### Review Findings

**Code review completed: 2026-05-05**

- [x] [Review][Decision] Entity mutability architectural choice — Decision: Keep `frozen=False`, document that direct field mutation bypasses validation. Comment added to class attributes.
- [x] [Review][Decision] Missing required domain exceptions — Decision: ChecksumMismatchError and SessionNotFoundError already exist in exceptions.py (added in Story 2.1). AC #5 satisfied.
- [x] [Review][Patch] Status transitions not enforced — Added validation in mark_in_progress() and mark_complete() to prevent transitions from terminal states [src/domain/entities/upload_session.py:185-242]
- [x] [Review][Patch] chunk_manifest structure never validated — Added validation in __post_init__ to check all dicts contain required keys [src/domain/entities/upload_session.py:139-149]
- [x] [Review][Patch] update_offset allows non-monotonic updates — Added check: new_offset must be >= current offset [src/domain/entities/upload_session.py:164-183]
- [x] [Review][Patch] Filename has zero validation — Added validation: non-empty, no path separators, no null bytes, max 255 chars [src/domain/entities/upload_session.py:115-125]
- [x] [Review][Patch] Missing __init__.py exports — Added UploadSession, SessionStatus, SHA256Hash exports [src/domain/entities/__init__.py, src/domain/value_objects/__init__.py]
- [x] [Review][Patch] Inconsistent datetime patterns in tests — Standardized to `datetime.now(timezone.utc)` [tests/unit/domain/entities/test_upload_session.py:29]
- [x] [Review][Patch] add_chunk() missing parameter validation — Added validation: chunk_index >= 0, chunk_size > 0, checksum non-empty, no duplicates [src/domain/entities/upload_session.py:142-168]
- [x] [Review][Patch] update_offset() missing negative check — Added check: new_offset must be >= 0 [src/domain/entities/upload_session.py:178-179]
- [x] [Review][Patch] is_expired() missing timezone validation — Added check: current_time must be timezone-aware [src/domain/entities/upload_session.py:267-268]
- [x] [Review][Patch] SHA256Hash missing None and type checks — Added validation: value cannot be None and must be string [src/domain/value_objects/sha256_hash.py:48-51]
- [x] [Review][Patch] SHA256Hash.from_bytes() missing validation — Added validation: data cannot be None and must be bytes [src/domain/value_objects/sha256_hash.py:79-82]
- [x] [Review][Defer] chunk_manifest mutable externally — Mutable list allows external code to bypass add_chunk() via direct manipulation — deferred, related to frozen=False decision
- [x] [Review][Defer] Business constants hardcoded in entity — MAX_FILE_SIZE_BYTES and ALLOWED_MIME_TYPES should be configurable — deferred, architectural decision for future configuration story
- [x] [Review][Defer] Type annotation maximally vague — chunk_manifest type `list[dict[str, Any]]` should be TypedDict or proper ChunkMetadata value object — deferred, requires new value object creation
- [x] [Review][Defer] No chunk_manifest memory protection — No limit on number of chunks that can be added — deferred, not in acceptance criteria
- [x] [Review][Defer] SessionStatus transitions not documented on enum — Transition rules only in entity docstring, not on enum itself — deferred, documentation enhancement
- [x] [Review][Defer] Test coverage gaps for non-standard inputs — No tests for non-UUID types, non-SHA256Hash types, concurrent modifications — deferred, comprehensive coverage acceptable for story scope
- [x] [Review][Defer] duplicate chunk_index handling unclear — No guard against duplicate chunk indices in manifest — deferred, business logic decision needed (NOW FIXED: validation added in add_chunk)

## Dev Notes

### Story Context and Purpose

**What This Story Is About:**

Story 3.1 creates the **foundational domain model for chunked file uploads**. This is the first story in Epic 3 (Chunked Upload Session Lifecycle) and establishes the core business entities that all subsequent upload stories will depend on.

**Why This Is Critical:**

This story defines the domain language and business rules for:
- Upload session lifecycle (PENDING → IN_PROGRESS → COMPLETE/FAILED/ABORTED)
- Chunk tracking and manifest management
- File validation rules (size limits, MIME type enforcement)
- SHA-256 checksum verification for data integrity

Following Clean Architecture principles, these domain entities are **pure business logic** with zero infrastructure dependencies. This enables:
- Unit testing without Redis, MinIO, or NATS
- Clear separation between business rules and infrastructure
- Easy refactoring of infrastructure without touching business logic

**Relationship to Previous Stories:**

- **Story 2.1**: Created Workspace entity and WorkspaceRole enum - we follow the same patterns for immutability and validation
- **Stories 2.2-2.6**: Built authentication and authorization infrastructure - UploadSession includes workspace_id for isolation
- **Epic 1**: Established project structure and tooling - we follow the same quality standards (ruff, mypy, pytest)

**What Already Exists (DO NOT RECREATE):**

✅ **Domain layer structure** - src/domain/ with entities/, value_objects/, exceptions.py (Story 2.1)
✅ **Workspace entity** - src/domain/entities/workspace.py (Story 2.1)
✅ **WorkspaceRole enum** - src/domain/value_objects/workspace_role.py (Story 2.1)
✅ **JWTClaims value object** - src/domain/value_objects/jwt_claims.py (Story 2.1)
✅ **Base domain exceptions** - DomainException, ChecksumMismatchError, UploadSessionNotFoundError (Story 2.1)
✅ **Testing infrastructure** - pytest configured with fixtures in tests/conftest.py (Story 1.2)
✅ **Code quality tools** - ruff, mypy configured in pyproject.toml (Story 1.2)

**What We Need to Create:**

🔨 **SessionStatus value object** - Enum for upload session lifecycle states
🔨 **SHA256Hash value object** - Immutable checksum with validation and computation
🔨 **UploadSession entity** - Core domain entity with business logic
🔨 **Additional domain exceptions** - FileSizeLimitExceededError, UnsupportedMediaTypeError
🔨 **Comprehensive unit tests** - Test all validation rules and business logic

### Architecture Requirements

**Clean Architecture Principles from [architecture.md](../../artifacts/planning-artifacts/architecture.md):**

> **Architecture Pattern**: Clean Architecture with Dependency Flow: Presentation → Application → Domain ← Infrastructure (via Protocols)

**Domain Layer Requirements:**

1. **Zero Infrastructure Dependencies** - No imports from infrastructure/, presentation/, or application/
2. **Immutability Where Appropriate** - Value objects are frozen; entities may be mutable for business logic
3. **Explicit Validation** - Validate invariants in __post_init__ or factory methods
4. **Rich Domain Methods** - Business logic lives in entities/services, not use cases

**Naming Conventions from [architecture.md#conventions](../../artifacts/planning-artifacts/architecture.md#conventions):**

```python
# PEP 8 naming (already established in workspace.py)
DEFAULT_CHUNK_SIZE = 5242880  # Constants: SCREAMING_SNAKE_CASE
class UploadSession:              # Classes: PascalCase
    def mark_complete(self) -> None:  # Methods: snake_case
        self.status = SessionStatus.COMPLETE  # Instance variables: snake_case
```

**Type Hints Required:**

- All function signatures must include type hints
- Use `from __future__ import annotations` for forward references
- Follow patterns from workspace.py for consistency

**Exception Hierarchy from [architecture.md#conventions](../../artifacts/planning-artifacts/architecture.md#conventions):**

```python
DomainException (base)  # Already exists
├── ChecksumMismatchError  # Already exists
├── UploadSessionNotFoundError  # Already exists (SessionNotFoundError)
├── FileSizeLimitExceededError  # NEW - add in this story
└── UnsupportedMediaTypeError  # NEW - add in this story
```

### Domain Model Design

**UploadSession Entity Specification:**

Based on Epic 3 requirements and architecture analysis, the UploadSession entity must:

1. **Track Session Identity and Ownership:**
   - `session_id: UUID` - Unique identifier (UUID v4 per NFR-S3)
   - `workspace_id: UUID` - Isolation boundary (FR22-FR26)

2. **Store File Metadata:**
   - `filename: str` - Original filename for display/debugging
   - `size: int` - Total file size in bytes (validated ≤ 1 GB per FR14)
   - `mime_type: str` - Must be "application/pdf" (validated per FR15)
   - `sha256_checksum: SHA256Hash` - Final file checksum for deduplication (FR16)

3. **Track Upload Progress:**
   - `offset: int` - Current verified byte offset (starts at 0, updated per chunk)
   - `chunk_manifest: list[dict]` - List of verified chunks with metadata
     - Each entry: `{"index": int, "size": int, "checksum": str}`
     - Enables resume validation and debugging

4. **Manage Lifecycle:**
   - `status: SessionStatus` - Current lifecycle state
   - `created_at: datetime` - Session creation timestamp (UTC)
   - `expires_at: datetime` - Session expiry timestamp (24 hours per FR10)

**Business Rules (Enforced in Entity):**

- ✅ File size must be ≤ 1 GB (raises FileSizeLimitExceededError)
- ✅ MIME type must be "application/pdf" (raises UnsupportedMediaTypeError)
- ✅ Offset must always be ≥ 0 and ≤ size
- ✅ Status transitions must follow valid lifecycle paths
- ✅ mark_complete() requires offset == size
- ✅ All timestamps must be timezone-aware UTC

**SHA256Hash Value Object Specification:**

Immutable value object for SHA-256 checksums:

```python
@dataclass(frozen=True)
class SHA256Hash:
    """SHA-256 checksum value object with validation.
    
    Attributes:
        value: Lowercase hex string, exactly 64 characters
    """
    value: str
    
    def __post_init__(self) -> None:
        # Validate: exactly 64 hex chars, lowercase
        if len(self.value) != 64:
            raise ValueError(f"SHA-256 hash must be 64 chars, got {len(self.value)}")
        if not all(c in '0123456789abcdef' for c in self.value):
            raise ValueError("SHA-256 hash must be lowercase hex")
    
    @classmethod
    def from_bytes(cls, data: bytes) -> "SHA256Hash":
        """Compute SHA-256 hash from bytes."""
        import hashlib
        digest = hashlib.sha256(data).hexdigest()
        return cls(digest)
```

**SessionStatus Enum Specification:**

```python
class SessionStatus(StrEnum):
    """Upload session lifecycle status.
    
    Valid transitions:
    - PENDING → IN_PROGRESS (first chunk received)
    - IN_PROGRESS → COMPLETE (all chunks verified, offset == size)
    - IN_PROGRESS → FAILED (verification error, storage error)
    - IN_PROGRESS → ABORTED (user cancellation)
    - Any state → ABORTED (explicit abort)
    """
    PENDING = "pending"          # Session created, no chunks received
    IN_PROGRESS = "in_progress"  # Chunks being uploaded
    COMPLETE = "complete"        # All chunks verified, file assembled
    FAILED = "failed"            # Error during upload/assembly
    ABORTED = "aborted"          # User-initiated cancellation
```

### Patterns from Previous Stories

**From Story 2.1 (workspace.py):**

✅ **Use @dataclass(frozen=True) for immutable entities:**
```python
from dataclasses import dataclass
from uuid import UUID

@dataclass(frozen=True)
class Workspace:
    workspace_id: UUID
    owner_user_id: UUID
    created_at: datetime
```

❗ **For UploadSession, use frozen=False** because offset and status are mutable:
```python
@dataclass(frozen=False)  # Mutable for business logic
class UploadSession:
    # ... attributes ...
    offset: int  # Updated via update_offset()
    status: SessionStatus  # Updated via mark_*() methods
```

✅ **Validate invariants in __post_init__:**
```python
def __post_init__(self) -> None:
    if not isinstance(self.workspace_id, UUID):
        raise TypeError("workspace_id must be a UUID")
    if self.created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
```

✅ **Use StrEnum for enums (from workspace_role.py):**
```python
from enum import StrEnum

class WorkspaceRole(StrEnum):
    OWNER = "owner"
    COLLABORATOR = "collaborator"
```

**From Story 2.6 (auth stub tests):**

✅ **Test validation exhaustively:**
- Test valid cases
- Test each validation rule with invalid input
- Test boundary conditions (e.g., size = 1 GB exactly)
- Test state transitions and business logic

✅ **Use descriptive test names:**
```python
def test_upload_session_rejects_file_size_exceeding_1gb():
    # Arrange
    size = 1_073_741_825  # 1 GB + 1 byte
    # Act & Assert
    with pytest.raises(FileSizeLimitExceededError):
        UploadSession(size=size, ...)
```

### Testing Requirements

**Test Coverage Standards from [architecture.md](../../artifacts/planning-artifacts/architecture.md):**

- Unit tests for all domain entities and value objects
- Test all validation rules with valid and invalid inputs
- Test all business logic methods (status transitions, chunk tracking)
- Test boundary conditions (size limits, offset limits)
- Minimum 90% code coverage for domain layer

**Test Organization:**

```
tests/unit/domain/
├── entities/
│   └── test_upload_session.py  # UploadSession entity tests
└── value_objects/
    ├── test_session_status.py   # SessionStatus enum tests
    └── test_sha256_hash.py      # SHA256Hash value object tests
```

**Key Test Cases for UploadSession:**

1. **Creation and Validation:**
   - ✅ Valid session creation with all required attributes
   - ❌ Size > 1 GB raises FileSizeLimitExceededError
   - ❌ mime_type != "application/pdf" raises UnsupportedMediaTypeError
   - ❌ offset > size raises ValueError
   - ❌ Non-timezone-aware datetime raises ValueError
   - ❌ expires_at before created_at raises ValueError

2. **Business Logic:**
   - ✅ add_chunk() appends to chunk_manifest correctly
   - ✅ update_offset() updates offset when valid
   - ❌ update_offset() raises error when new_offset > size
   - ✅ Status transitions work correctly (mark_in_progress, mark_complete, etc.)
   - ❌ mark_complete() fails when offset < size
   - ✅ is_expired() returns correct boolean based on current_time
   - ✅ is_complete() returns True only when offset == size and status == COMPLETE

**Key Test Cases for SHA256Hash:**

1. **Validation:**
   - ✅ Valid 64-char hex string accepted
   - ❌ Wrong length rejected
   - ❌ Non-hex characters rejected
   - ❌ Uppercase letters rejected (must be lowercase)

2. **Computation:**
   - ✅ from_bytes() computes correct hash for known test data
   - ✅ Computed hash matches expected value

3. **Value Object Behavior:**
   - ✅ Immutability (frozen dataclass)
   - ✅ Equality comparison works correctly
   - ✅ Hashable (can be used as dict key)

### File Structure Impact

**Files to Create:**

```
src/domain/
├── entities/
│   └── upload_session.py          # NEW
├── value_objects/
│   ├── session_status.py          # NEW
│   └── sha256_hash.py             # NEW
└── exceptions.py                  # UPDATE (add 2 new exceptions)

tests/unit/domain/
├── entities/
│   └── test_upload_session.py     # NEW
└── value_objects/
    ├── test_session_status.py     # NEW
    └── test_sha256_hash.py        # NEW
```

**Files to Update:**

- `src/domain/exceptions.py` - Add FileSizeLimitExceededError and UnsupportedMediaTypeError
- `src/domain/entities/__init__.py` - Export UploadSession (if using __all__)
- `src/domain/value_objects/__init__.py` - Export SessionStatus, SHA256Hash (if using __all__)

**Files NOT to Touch:**

- ❌ Any infrastructure layer files (Redis, S3, NATS, ClamAV)
- ❌ Any application layer files (use cases, DTOs)
- ❌ Any presentation layer files (API endpoints, schemas)
- ❌ Existing domain entities (workspace.py) - no changes needed

### Critical Implementation Notes

**⚠️ Common Pitfalls to Avoid:**

1. **DO NOT add infrastructure dependencies** - No Redis, S3, NATS imports in domain layer
2. **DO NOT implement persistence** - That's Story 3.2 (Redis session store)
3. **DO NOT create API schemas** - That's Story 3.5 (API endpoints)
4. **DO NOT implement chunk verification logic** - That's Story 3.6 (domain service)
5. **DO NOT make UploadSession frozen** - It needs mutable offset and status

**✅ Must-Do Checklist:**

- ✅ All attributes have type hints
- ✅ All validation happens in __post_init__
- ✅ All business logic methods have docstrings
- ✅ All exceptions inherit from DomainException
- ✅ All timestamps are timezone-aware UTC
- ✅ All tests pass with ≥90% coverage
- ✅ Mypy --strict passes with no errors
- ✅ Ruff check passes with no violations

**🔍 Quality Gates:**

Before marking this story complete:
1. Run: `pytest tests/unit/domain/ -v --cov=src/domain --cov-report=term-missing`
2. Verify: Coverage ≥ 90%
3. Run: `mypy src/domain/ --strict`
4. Verify: No type errors
5. Run: `ruff check src/domain/`
6. Verify: No linting violations
7. Run full suite: `pytest`
8. Verify: No regressions in existing tests

### Integration with Future Stories

**Story 3.2 (Redis Session Store) will:**
- Implement ISessionStore protocol using UploadSession entity
- Serialize/deserialize UploadSession to/from Redis Hash
- Convert chunk_manifest list to/from JSON

**Story 3.4 (Initiate Upload Use Case) will:**
- Create UploadSession instances with initial values
- Validate file size and MIME type (using entity validation)
- Set status to PENDING

**Story 3.7 (Process Chunk Use Case) will:**
- Call update_offset() and add_chunk() methods
- Transition status to IN_PROGRESS
- Use is_expired() to check session validity

**Story 5.8 (Complete Upload Use Case) will:**
- Call mark_complete() when all chunks verified
- Use sha256_checksum for deduplication (FR16)
- Check is_complete() before publishing events

### References

**Source Documents:**

- [Epic 3 Requirements](../../artifacts/planning-artifacts/epics.md#epic-3-chunked-upload-session-lifecycle) - Complete epic scope and story list
- [Story 3.1 Specification](../../artifacts/planning-artifacts/epics.md#story-31-create-upload-session-domain-entities-and-value-objects) - Detailed acceptance criteria
- [Architecture - Domain Model](../../artifacts/planning-artifacts/architecture.md#project-structure--boundaries) - Clean Architecture structure
- [Architecture - Naming Conventions](../../artifacts/planning-artifacts/architecture.md#conventions) - Code standards and patterns
- [PRD - Functional Requirements](../../artifacts/planning-artifacts/prd.md) - FR1-FR35 business requirements

**Existing Code to Reference:**

- [src/domain/entities/workspace.py](../../src/domain/entities/workspace.py) - Pattern for frozen dataclass entity with validation
- [src/domain/value_objects/workspace_role.py](../../src/domain/value_objects/workspace_role.py) - Pattern for StrEnum value objects
- [src/domain/exceptions.py](../../src/domain/exceptions.py) - Existing exception hierarchy

**Previous Stories:**

- [Story 2.1: Create Domain Entities](../../artifacts/implementation-artifacts/2-1-create-domain-entities-for-workspace-and-user-roles.md) - Workspace entity patterns
- [Story 1.2: Configure Development Tools](../../artifacts/implementation-artifacts/1-2-configure-development-tools-and-code-quality-standards.md) - Tooling configuration

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.5 (Copilot)

### Debug Log References

No issues encountered during implementation. All tasks completed using red-green-refactor TDD cycle.

### Completion Notes List

**Implementation Summary:**

✅ Successfully created all upload session domain entities and value objects following Clean Architecture principles and TDD methodology

**What Was Implemented:**

1. **SessionStatus Value Object** (src/domain/value_objects/session_status.py)
   - StrEnum with 5 lifecycle states: PENDING, IN_PROGRESS, COMPLETE, FAILED, ABORTED
   - Comprehensive docstrings documenting valid state transitions
   - 5 passing unit tests

2. **SHA256Hash Value Object** (src/domain/value_objects/sha256_hash.py)
   - Immutable frozen dataclass with validation
   - 64-character lowercase hex string validation
   - from_bytes() factory method for hash computation
   - Full support for equality, hashing, and string representations
   - 12 passing unit tests with 96% coverage

3. **UploadSession Entity** (src/domain/entities/upload_session.py)
   - Mutable dataclass (frozen=False) for business logic operations
   - 11 attributes including session_id, workspace_id, size, status, chunk_manifest
   - Comprehensive __post_init__ validation:
     - File size ≤ 1 GB (raises FileSizeLimitExceededError)
     - MIME type must be "application/pdf" (raises UnsupportedMediaTypeError)
     - Offset validation, timezone-aware timestamps
   - 8 business logic methods: add_chunk(), update_offset(), mark_*(), is_expired(), is_complete()
   - 28 passing unit tests with 97% coverage

4. **Domain Exceptions** (src/domain/exceptions.py)
   - Added FileSizeLimitExceededError with file_size and max_size attributes
   - Added UnsupportedMediaTypeError with provided_mime_type and allowed_mime_types attributes
   - Both exceptions inherit from DomainException with clear error messages

**Testing Results:**

- **Total Tests**: 246 tests pass (85 domain tests + 161 existing tests)
- **Domain Coverage**: 98% overall
- **No Regressions**: All existing tests from previous stories pass
- **TDD Approach**: All tests written before implementation (red-green-refactor)

**Code Quality:**

- ✅ Ruff check: All checks passed
- ✅ Ruff format: 3 files reformatted (import sorting)
- ✅ Mypy --strict: No type errors
- ✅ PEP 8 compliant: snake_case, proper docstrings, type hints throughout
- ✅ Zero infrastructure dependencies in domain layer

**Architecture Compliance:**

- Followed Clean Architecture principles: domain layer has no dependencies on infrastructure, application, or presentation layers
- Consistent with existing patterns from workspace.py and workspace_role.py
- Used @dataclass for entities and value objects
- Implemented validation in __post_init__
- StrEnum for status enum (matching WorkspaceRole pattern)

### File List

**Created Files:**

- src/domain/entities/upload_session.py
- src/domain/value_objects/session_status.py
- src/domain/value_objects/sha256_hash.py
- tests/unit/domain/entities/test_upload_session.py
- tests/unit/domain/value_objects/test_session_status.py
- tests/unit/domain/value_objects/test_sha256_hash.py

**Modified Files:**

- src/domain/exceptions.py (added 2 new exception classes)

### Change Log

**Date: 2026-05-05**

**Story 3.1: Create Upload Session Domain Entities and Value Objects - COMPLETE**

Created foundational domain model for chunked file uploads following Clean Architecture principles and TDD methodology:

- Implemented SessionStatus value object (StrEnum) with 5 lifecycle states
- Implemented SHA256Hash value object (immutable, frozen dataclass) with validation and from_bytes() factory method
- Implemented UploadSession entity (mutable dataclass) with comprehensive validation and 8 business logic methods
- Added FileSizeLimitExceededError and UnsupportedMediaTypeError to domain exceptions
- Created 45 comprehensive unit tests (5 + 12 + 28) with red-green-refactor TDD approach
- Achieved 98% test coverage across domain layer
- All 246 tests pass with zero regressions
- Code quality: ruff, mypy --strict, PEP 8 compliant
- Zero infrastructure dependencies in domain layer (Clean Architecture compliance)

**Files Created:** 6 new files (3 source + 3 test)
**Files Modified:** 1 file (domain exceptions)
**Tests Added:** 45 new tests
**Test Results:** 246/246 passing
