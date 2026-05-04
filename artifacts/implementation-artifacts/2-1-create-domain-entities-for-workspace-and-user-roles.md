# Story 2.1: Create Domain Entities for Workspace and User Roles

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **developer**,
I want **domain entities that represent workspace ownership and collaboration roles**,
So that **authorization logic is clear and type-safe throughout the application**.

## Acceptance Criteria

1. **Given** domain layer exists
   **When** workspace entities are created
   **Then** src/domain/entities/workspace.py exists with Workspace entity

2. **And** src/domain/value_objects/workspace_role.py defines WorkspaceRole enum (OWNER, COLLABORATOR)

3. **And** Workspace entity includes: workspace_id, owner_user_id, created_at

4. **And** src/domain/value_objects/jwt_claims.py defines JWTClaims value object

5. **And** JWTClaims includes: user_id, workspace_id (active_workspace_id from JWT), workspace_role, shared_file_ids (optional list of UUIDs)

6. **And** all entities follow immutability pattern where applicable

## Tasks / Subtasks

- [x] Create WorkspaceRole enum value object (AC: #2)
  - [x] Create src/domain/value_objects/workspace_role.py
  - [x] Define WorkspaceRole enum with OWNER and COLLABORATOR values
  - [x] Follow PEP 8 naming conventions (UPPER_CASE enum values)
  - [x] Add type hints and docstrings

- [x] Create Workspace entity (AC: #1, #3, #6)
  - [x] Create src/domain/entities/workspace.py
  - [x] Define Workspace entity with workspace_id, owner_user_id, created_at fields
  - [x] Use Python dataclass with frozen=True for immutability
  - [x] Add UUID type hints for IDs (use standard library uuid.UUID)
  - [x] Add datetime type hints with timezone.utc for created_at
  - [x] Include comprehensive docstrings explaining purpose and fields

- [x] Create JWTClaims value object (AC: #4, #5, #6)
  - [x] Create src/domain/value_objects/jwt_claims.py
  - [x] Define JWTClaims with: user_id, workspace_id, workspace_role, shared_file_ids, exp
  - [x] Use Python dataclass with frozen=True for immutability
  - [x] Map workspace_id to active_workspace_id from JWT token
  - [x] shared_file_ids should be Optional[list[str]] (can be None for owners)
  - [x] exp should be int (Unix timestamp)
  - [x] Add validation method to check if token is expired
  - [x] Add method to check if user has access to specific file_id

- [x] Update domain __init__ exports (maintainability)
  - [x] Export Workspace from src/domain/entities/__init__.py
  - [x] Export WorkspaceRole and JWTClaims from src/domain/value_objects/__init__.py
  - [x] Ensure clean imports for use in other layers

- [x] Create comprehensive unit tests (testing standard)
  - [x] Create tests/unit/domain/entities/test_workspace.py
    - [x] Test Workspace creation with valid data
    - [x] Test immutability (frozen dataclass)
    - [x] Test field types and validation
  - [x] Create tests/unit/domain/value_objects/test_workspace_role.py
    - [x] Test enum values (OWNER, COLLABORATOR)
    - [x] Test enum comparison and equality
  - [x] Create tests/unit/domain/value_objects/test_jwt_claims.py
    - [x] Test JWTClaims creation with all fields
    - [x] Test JWTClaims with None shared_file_ids (owner scenario)
    - [x] Test is_expired() method with past and future timestamps
    - [x] Test has_access_to_file() method for owner and collaborator scenarios
    - [x] Test immutability

## Dev Notes

### Architecture Requirements

**Clean Architecture Pattern:**
This story creates the foundational domain entities for authentication and workspace isolation. These entities live in the Domain layer which has ZERO external dependencies - pure Python only. All other layers (Application, Infrastructure, Presentation) will depend on these domain entities.

**Dependency Flow:**
```
Domain Layer (this story) ← Application Layer ← Infrastructure Layer
                         ← Presentation Layer
```

**Multi-Tenancy Foundation:**
These entities are critical for enforcing workspace isolation (FR22-FR26). Every future component that touches workspaces or user roles will depend on these foundational types. The WorkspaceRole enum and JWTClaims will be used by:
- JWT validation middleware (Story 2.2)
- RBAC middleware (Story 2.4)
- All upload endpoints (Stories 3.4, 3.5, 3.7, 3.8, etc.)
- Access control rules (Story 2.5)

### Technical Stack & Patterns

**Python Environment:**
- Python 3.13 (project uses uv package manager)
- Standard library only for domain layer (no external dependencies)
- Type hints required on all functions and class attributes (mypy enforcement)

**Immutability Pattern:**
Use Python dataclasses with `frozen=True` to enforce immutability:
```python
from dataclasses import dataclass
from typing import Optional
from datetime import datetime
from uuid import UUID

@dataclass(frozen=True)
class Workspace:
    """Domain entity representing a workspace with ownership."""
    workspace_id: UUID
    owner_user_id: UUID
    created_at: datetime
```

**Enum Pattern:**
Use Python's enum.Enum for WorkspaceRole:
```python
from enum import Enum

class WorkspaceRole(str, Enum):
    """Workspace role determining user permissions."""
    OWNER = "owner"
    COLLABORATOR = "collaborator"
```

**Naming Conventions (Implementation Pattern #1 - PEP 8):**
- Module names: `snake_case.py` (workspace_role.py, jwt_claims.py)
- Class names: `PascalCase` (WorkspaceRole, JWTClaims, Workspace)
- Enum values: `UPPER_CASE` (OWNER, COLLABORATOR)
- Method names: `snake_case()` (is_expired(), has_access_to_file())
- All code must pass `ruff check` and `mypy` validation

**Datetime Pattern (Implementation Pattern #8):**
- All datetime fields use timezone-aware datetime with UTC
- Use `datetime.now(timezone.utc)` for current time
- Store as datetime objects, convert to ISO 8601 with Z suffix only at API boundary

### JWT Claims Mapping

**From PRD Authentication Model:**
JWT tokens issued by platform auth service contain these claims:
```json
{
    "user_id": "uuid",
    "active_workspace_id": "uuid",
    "workspace_role": "owner | collaborator",
    "shared_file_ids": ["uuid"],
    "exp": 1234567890
}
```

**Domain Model Mapping:**
- `user_id` → JWTClaims.user_id (UUID)
- `active_workspace_id` → JWTClaims.workspace_id (UUID) - note the field rename for internal consistency
- `workspace_role` → JWTClaims.workspace_role (WorkspaceRole enum)
- `shared_file_ids` → JWTClaims.shared_file_ids (Optional[list[UUID]])
- `exp` → JWTClaims.exp (int, Unix timestamp)

**Helper Methods Required:**
```python
def is_expired(self) -> bool:
    """Check if the JWT token has expired based on exp claim."""
    from datetime import datetime, timezone
    current_timestamp = int(datetime.now(timezone.utc).timestamp())
    return current_timestamp > self.exp

def has_access_to_file(self, file_id: UUID) -> bool:
    """Check if user has access to specific file.
    
    Owners have access to all files in their workspace.
    Collaborators only have access to files in shared_file_ids.
    """
    if self.workspace_role == WorkspaceRole.OWNER:
        return True
    return self.shared_file_ids is not None and file_id in self.shared_file_ids
```

### File Structure Requirements

**Files to Create:**
```
src/domain/
├── entities/
│   ├── __init__.py          # Export Workspace
│   └── workspace.py         # NEW: Workspace entity
└── value_objects/
    ├── __init__.py          # Export WorkspaceRole, JWTClaims
    ├── workspace_role.py    # NEW: WorkspaceRole enum
    └── jwt_claims.py        # NEW: JWTClaims value object

tests/unit/domain/
├── entities/
│   ├── __init__.py
│   └── test_workspace.py    # NEW: Workspace tests
└── value_objects/
    ├── __init__.py
    ├── test_workspace_role.py  # NEW: WorkspaceRole tests
    └── test_jwt_claims.py      # NEW: JWTClaims tests
```

### Testing Requirements

**Testing Framework:** pytest + pytest-asyncio (already configured in project)

**Test Coverage Standards:**
- All domain entities and value objects must have unit tests
- Aim for 100% code coverage on domain layer (it's pure logic, fully testable)
- Tests must be in tests/unit/domain/ mirroring src/domain/ structure
- Use descriptive test names: `test_workspace_creation_with_valid_data()`

**Test Patterns:**
```python
# Example test structure
import pytest
from uuid import UUID, uuid4
from datetime import datetime, timezone
from src.domain.entities.workspace import Workspace

def test_workspace_creation_with_valid_data():
    """Test creating a workspace with all required fields."""
    workspace_id = uuid4()
    owner_id = uuid4()
    created_at = datetime.now(timezone.utc)
    
    workspace = Workspace(
        workspace_id=workspace_id,
        owner_user_id=owner_id,
        created_at=created_at
    )
    
    assert workspace.workspace_id == workspace_id
    assert workspace.owner_user_id == owner_id
    assert workspace.created_at == created_at

def test_workspace_immutability():
    """Test that Workspace is immutable (frozen dataclass)."""
    workspace = Workspace(
        workspace_id=uuid4(),
        owner_user_id=uuid4(),
        created_at=datetime.now(timezone.utc)
    )
    
    with pytest.raises(AttributeError):
        workspace.workspace_id = uuid4()  # Should fail - frozen
```

### Previous Story Learnings (Epic 1)

**From Story 1.4 (Configuration Management):**
- Successfully used Pydantic Settings for configuration with type safety
- Environment variables validated at startup with clear error messages
- Singleton pattern used for settings access via @lru_cache
- All sensitive fields protected with SecretStr

**Patterns to Apply:**
- Type safety is critical - use type hints everywhere
- Clear validation errors at initialization time
- Comprehensive docstrings for all classes and methods
- Follow existing project patterns (Clean Architecture structure already established)

**Existing Project Structure:**
```
src/
├── domain/
│   ├── __init__.py          ✓ Exists
│   ├── entities/
│   │   └── __init__.py      ✓ Exists (empty, ready for Workspace)
│   ├── value_objects/
│   │   └── __init__.py      ✓ Exists (empty, ready for WorkspaceRole, JWTClaims)
│   ├── exceptions.py        ✓ Exists (has DomainException base class)
│   ├── protocols/           ✓ Exists (for Story 2.3+)
│   └── services/            ✓ Exists (for Story 2.3+)
```

### Critical Implementation Notes

**⚠️ MUST FOLLOW:**

1. **Zero External Dependencies**: Domain layer uses ONLY Python standard library. No FastAPI, no Pydantic, no Redis, no external imports.

2. **Type Hints Required**: Every class attribute, function parameter, and return type must have type hints. This is enforced by mypy.

3. **Immutability Where Applicable**: Value objects and entities that don't change state should use `frozen=True` dataclasses.

4. **UUID vs String**: Use `uuid.UUID` type for all ID fields, not strings. This provides type safety and catches UUID format errors early.

5. **Workspace Role Values**: Use lowercase string values ("owner", "collaborator") to match JWT token format from auth service.

6. **shared_file_ids Handling**: This field is Optional. Owners may have None (access all files). Collaborators should have a list (even if empty).

7. **Timezone Awareness**: Always use `datetime.now(timezone.utc)` for datetime objects. Never use naive datetime objects.

8. **Testing First**: Consider writing tests first or alongside implementation to ensure all edge cases are covered.

### Success Criteria

**This story is complete when:**
- ✓ All three files created (workspace.py, workspace_role.py, jwt_claims.py)
- ✓ All entities follow immutability pattern (frozen dataclasses)
- ✓ All type hints are present and pass mypy validation
- ✓ All code passes ruff linting
- ✓ Comprehensive unit tests written with >95% coverage
- ✓ All tests pass
- ✓ Domain layer still has zero external dependencies
- ✓ Exports added to __init__.py files for clean imports

### References

- [Source: artifacts/planning-artifacts/epics.md - Epic 2, Story 2.1]
- [Source: artifacts/planning-artifacts/prd.md - Authentication Model section]
- [Source: artifacts/planning-artifacts/architecture.md - Implementation Patterns #1, #8]
- [Source: artifacts/planning-artifacts/architecture.md - Clean Architecture structure]
- [Source: artifacts/implementation-artifacts/1-4-create-base-configuration-management-with-pydantic-settings.md - Previous story patterns]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.5 (GitHub Copilot)

### Debug Log References

N/A - No debugging required. Implementation was straightforward following Clean Architecture patterns.

### Completion Notes List

**Implementation Summary:**
- Created three foundational domain entities/value objects for workspace isolation and authentication
- All entities follow immutability pattern using frozen dataclasses
- Zero external dependencies - pure Python standard library only
- Modern Python 3.13 features used: `enum.StrEnum` instead of `(str, Enum)`, `datetime.UTC` instead of `timezone.utc`, `X | None` instead of `Optional[X]`

**Key Technical Decisions:**
1. Used `enum.StrEnum` (Python 3.11+) for WorkspaceRole instead of inheriting from both str and Enum
2. JWTClaims.shared_file_ids is `list[UUID] | None` to support both owner (None = all access) and collaborator (list = specific files) scenarios
3. Added helper methods `is_expired()` and `has_access_to_file()` to JWTClaims for reusable authorization logic
4. All datetime fields use timezone-aware UTC timestamps per project standards

**Test Coverage:**
- Created 27 unit tests covering all domain entities and value objects
- Tests cover: creation, immutability, type validation, equality, edge cases, authorization logic
- All tests pass with 100% code coverage for new domain entities
- Full test suite: 50 tests pass (27 new + 23 existing from previous stories)

**Code Quality:**
- All code passes ruff linting checks
- All code passes mypy type checking (strict mode)
- Follows PEP 8 naming conventions and project coding standards

**Acceptance Criteria Validation:**
- ✓ AC1: Workspace entity created with workspace_id, owner_user_id, created_at
- ✓ AC2: WorkspaceRole enum defined with OWNER and COLLABORATOR
- ✓ AC3: All fields properly typed with UUID and datetime
- ✓ AC4: JWTClaims value object created
- ✓ AC5: JWTClaims includes user_id, workspace_id, workspace_role, shared_file_ids (optional), exp
- ✓ AC6: All entities follow immutability pattern (frozen=True)

### File List

**Created Files:**
- src/domain/entities/workspace.py
- src/domain/value_objects/workspace_role.py
- src/domain/value_objects/jwt_claims.py
- tests/unit/domain/entities/__init__.py
- tests/unit/domain/entities/test_workspace.py
- tests/unit/domain/value_objects/__init__.py
- tests/unit/domain/value_objects/test_workspace_role.py
- tests/unit/domain/value_objects/test_jwt_claims.py

**Modified Files:**
- src/domain/entities/__init__.py (added Workspace export)
- src/domain/value_objects/__init__.py (added WorkspaceRole and JWTClaims exports)

## Change Log

- **2026-05-04**: Created domain entities for workspace ownership and user roles (Story 2.1 complete)
  - Implemented WorkspaceRole enum with OWNER and COLLABORATOR values
  - Implemented Workspace entity with workspace_id, owner_user_id, created_at fields
  - Implemented JWTClaims value object with authorization helper methods
  - Added comprehensive unit tests (27 tests) with 100% coverage
  - All code passes linting and type checking validations


### Review Findings

- [x] [Review][Decision] Spec contradiction for shared_file_ids type (UUID vs str) — Updated spec to clarify UUID type
- [x] [Review][Decision] Enforce state consistency in JWTClaims — Added validation in __post_init__
- [x] [Review][Patch] Fake Immutability with Mutable Collections in JWTClaims.shared_file_ids [src/domain/value_objects/jwt_claims.py:37] — Changed list to tuple
- [x] [Review][Patch] Hidden Time Coupling in JWTClaims.is_expired() [src/domain/value_objects/jwt_claims.py:46] — Added current_timestamp parameter
- [x] [Review][Patch] test_is_expired_at_exact_expiration tests type bool instead of exact return value [tests/unit/domain/value_objects/test_jwt_claims.py] — Fixed to assert exact values
- [x] [Review][Patch] Add __post_init__ validation for Workspace and JWTClaims (e.g. UUID, datetime timezone validation) [src/domain/entities/workspace.py, src/domain/value_objects/jwt_claims.py] — Added validation
- [x] [Review][Patch] StrEnum deviates from explicit Enum pattern spec [src/domain/value_objects/workspace_role.py:3-6] — Reverted to str, Enum
- [x] [Review][Patch] Use FrozenInstanceError for mutability assertions [tests/unit/domain/entities/test_workspace.py, tests/unit/domain/value_objects/test_jwt_claims.py] — Fixed assertions
- [x] [Review][Defer] Add standard JWT claims (iat, nbf, iss, aud) [src/domain/value_objects/jwt_claims.py] — deferred, feature expansion not required by current AC
- [x] [Review][Defer] Avoid awkward manual UUID generation [src/domain/entities/workspace.py] — deferred, standard pattern for DDD when un-persisting from DB
