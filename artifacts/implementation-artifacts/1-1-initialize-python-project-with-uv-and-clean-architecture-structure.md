# Story 1.1: Initialize Python Project with uv and Clean Architecture Structure

Status: done

## Story

As a **developer**,
I want **the project initialized with uv, Python 3.13, and a complete Clean Architecture directory structure**,
So that **I have a consistent foundation following architectural patterns for all future development**.

## Acceptance Criteria

**Given** a new project directory
**When** the initialization is complete
**Then** the project has a pyproject.toml configured with uv
**And** Python 3.13 is pinned in .python-version
**And** directory structure includes src/domain/, src/application/, src/infrastructure/, src/presentation/
**And** all subdirectories for entities, value_objects, protocols, services, use_cases, dto are created
**And** __init__.py files exist in all package directories

## Tasks / Subtasks

- [x] Initialize uv project with Python 3.13 (AC: pyproject.toml exists)
  - [x] Activate flox environment: `flox activate`
  - [x] Check available tools: `flox list` (uv and python3.13 may be pre-installed)
  - [x] Verify uv is available (check version or install if needed)
  - [x] Run `uv init --python 3.13` in project root
  - [x] Run `uv python pin 3.13` to create .python-version
  - [x] Verify pyproject.toml was created with correct Python version

- [x] Add core dependencies to pyproject.toml (AC: all required packages listed)
  - [x] Add FastAPI framework: `uv add fastapi uvicorn[standard] httpx`
  - [x] Add storage/data integrations: `uv add aioboto3 redis[hiredis] nats-py`
  - [x] Add security/validation: `uv add pyjwt[crypto] python-multipart pydantic-settings`
  - [x] Add utilities: `uv add python-dotenv structlog`
  - [x] Add development dependencies: `uv add --dev pytest pytest-asyncio pytest-cov pytest-mock mypy ruff mkdocs mkdocs-material`
  - [x] Run `uv sync` to create virtual environment and install all dependencies

- [x] Create Clean Architecture directory structure (AC: all directories exist with __init__.py)
  - [x] Create src/ root directory
  - [x] Create domain layer: src/domain/{entities,value_objects,protocols,services,exceptions.py}
  - [x] Create application layer: src/application/{use_cases,dto,ports}
  - [x] Create infrastructure layer: src/infrastructure/{redis,s3,nats,clamav,auth,config}
  - [x] Create presentation layer: src/presentation/{api/v1/{routers,schemas,dependencies},api/middleware,main.py}
  - [x] Create observability: src/observability/{metrics.py,logging.py}
  - [x] Create tests structure: tests/{unit,integration,e2e}
  - [x] Create docker directory: docker/
  - [x] Create docs directory (if doesn't exist)
  - [x] Add __init__.py to ALL Python package directories (domain, application, infrastructure, presentation, and all subdirectories)

- [x] Create initial README.md with setup instructions (AC: README has clear project setup steps)
  - [x] Document uv installation command
  - [x] Document dependency installation: `uv sync`
  - [x] Document development server command: `uv run uvicorn src.presentation.main:app --reload`
  - [x] Document test command: `uv run pytest`
  - [x] Document code quality commands: `uv run ruff check src/` and `uv run mypy src/`
  - [x] Include project description and purpose (chunked upload service for RAG pipeline)

- [x] Verify structure matches architectural requirements (AC: validation passes)
  - [x] Verify .python-version contains "3.13"
  - [x] Verify pyproject.toml contains all dependencies
  - [x] Verify all required directories exist
  - [x] Verify all __init__.py files exist
  - [x] Verify uv.lock was created during sync
  - [x] Test that `uv run python --version` shows Python 3.13.x

### Review Findings (AI)

**Decision-Needed:**
_(None)_

**Patches Required:**

- [x] [Review][Patch][HIGH] Empty placeholder files prevent basic functionality — FIXED: Added minimal valid Python content with docstrings, base exception classes, and FastAPI app skeleton
- [x] [Review][Patch][MEDIUM] Extraneous root-level main.py file — FIXED: Deleted main.py from project root
- [x] [Review][Patch][LOW] Generic project description in pyproject.toml — FIXED: Updated to "Chunked upload service for RAG pipeline with resumability and integrity verification"

**Deferred:**

- [x] [Review][Defer][LOW] .gitignore patterns for new tools — .gitignore should include .venv/, uv.lock, *.pyc — deferred, pre-existing file outside Story 1.1 scope

## Dev Notes

### Flox Environment Context

**IMPORTANT:** This project uses flox for local development environment management.

**Before any implementation steps:**
1. **Activate flox environment**: `flox activate`
2. **Check installed tools**: `flox list` to see what's already available
3. **Likely pre-installed**: uv and python3.13 may already be in the flox environment

**All commands in this story should be executed within the activated flox environment.**

If uv or Python 3.13 are not in flox:
- Add them to flox: `flox install uv python313`
- Or proceed with manual installation as fallback

### Critical Architectural Context

**This is the foundational story for the entire project.** All subsequent stories depend on this structure being correct and complete.

**Clean Architecture Dependency Flow:**
- **Domain Layer** (pure business logic) → imports NOTHING external
- **Application Layer** (use cases) → imports from Domain only
- **Infrastructure Layer** (external services) → imports from Domain (protocols) and Application
- **Presentation Layer** (FastAPI) → imports from Application (use cases) and Infrastructure (DI setup)

**Why Clean Architecture for this project:**
1. **Testability**: Unit test domain logic without Redis/MinIO/NATS running
2. **Maintainability**: Pure business logic isolated from framework/infrastructure changes
3. **Dependency Inversion**: Infrastructure implements protocols defined in Domain
4. **Proven Pattern**: Netflix Dispatch pattern for multi-domain microservices

### Technology Stack Rationale

**uv Package Manager:**
- **10-100x faster** than pip/poetry for dependency resolution
- Rust-based tool from Astral (same team as Ruff)
- Automatic virtual environment management
- Compatible with standard Python packaging (pyproject.toml)
- Latest stable version as of 2026: use whatever is available

**Python 3.13:**
- Latest performance improvements (PEP 669 low-impact monitoring)
- Improved asyncio performance critical for concurrent chunk uploads
- Better type inference for mypy
- Per architecture decision: Python 3.13 required

**FastAPI:**
- Native async/await support for non-blocking I/O
- Automatic OpenAPI spec generation (FR33 requirement)
- Pydantic integration for request/response validation
- High performance for REST APIs
- Built-in dependency injection for Clean Architecture

### Directory Structure Deep Dive

**src/domain/** (No external dependencies - pure business logic):
```
domain/
├── entities/          # Core business objects (UploadSession, Chunk, FileMetadata)
├── value_objects/     # Immutable values (SHA256Hash, WorkspaceId, ChunkIndex)
├── protocols/         # Interfaces for infrastructure (ISessionStore, IStorageClient, IEventPublisher)
├── services/          # Domain services (ChunkVerificationService, DeduplicationService)
└── exceptions.py      # Domain-specific exceptions (DuplicateFileError, ChecksumMismatchError)
```

**src/application/** (Orchestration layer):
```
application/
├── use_cases/         # Business workflows (InitiateUpload, ProcessChunk, CompleteUpload)
├── dto/               # Data Transfer Objects for cross-layer communication
└── ports/             # Additional application-level interfaces if needed
```

**src/infrastructure/** (External service implementations):
```
infrastructure/
├── redis/             # RedisSessionStore implementing ISessionStore protocol
├── s3/                # S3StorageClient implementing IStorageClient protocol
├── nats/              # NATSEventPublisher implementing IEventPublisher protocol
├── clamav/            # ClamAVScanner implementing IVirusScanner protocol
├── auth/              # JWTValidator + stub auth service
└── config/            # Pydantic Settings for env var management
```

**src/presentation/** (FastAPI HTTP layer):
```
presentation/
├── api/
│   ├── v1/
│   │   ├── routers/         # FastAPI route handlers (uploads.py)
│   │   ├── schemas/         # Pydantic request/response models
│   │   └── dependencies.py  # FastAPI dependency injection setup
│   └── middleware/          # JWT auth middleware, error handlers, CORS
└── main.py                  # FastAPI app initialization and router registration
```

**src/observability/**:
```
observability/
├── metrics.py         # Prometheus metrics setup (upload_chunks_total, etc.)
└── logging.py         # Structured logging with structlog (JSON output)
```

**tests/** (mirrors src/ structure):
```
tests/
├── unit/              # Domain + application logic tests (no external services)
├── integration/       # Infrastructure tests (Redis, S3, NATS integration)
└── e2e/               # Full API flow tests (FastAPI TestClient)
```

### Project Root Files to Create

**Required Files:**
- `.python-version` - Contains "3.13" for uv Python version pinning
- `pyproject.toml` - uv project config with all dependencies
- `uv.lock` - Generated by `uv sync`, do NOT manually edit
- `README.md` - Project setup and development instructions
- `.gitignore` - Ignore .venv/, __pycache__/, *.pyc, .env, uv.lock (debatable), etc.

**NOT Created in This Story (later stories):**
- `ruff.toml` - Story 1.2 (development tools configuration)
- `mypy.ini` - Story 1.2 (type checking configuration)
- `docker-compose.yml` - Story 1.3 (external services setup)
- `.env.example` - Story 1.4 (configuration management)

### Dependencies Reference

**Web Framework & Async:**
- `fastapi` - Modern async web framework
- `uvicorn[standard]` - ASGI server with recommended extras
- `httpx` - Async HTTP client for external API calls

**Storage & Data:**
- `aioboto3` - Async AWS SDK (for MinIO/S3 operations)
- `redis[hiredis]` - Async Redis client with C-based hiredis parser
- `asyncio-nats` - Async NATS client for JetStream events

**Security & Validation:**
- `pyjwt[crypto]` - JWT token validation with RS256 support
- `python-multipart` - Required for FastAPI file uploads
- `pydantic-settings` - Type-safe environment variable management

**Utilities:**
- `python-dotenv` - Load .env files for local development
- `structlog` - Structured logging library for JSON output

**Development Tools:**
- `pytest` - Test framework
- `pytest-asyncio` - Async test support
- `pytest-cov` - Code coverage reporting
- `pytest-mock` - Mocking utilities
- `mypy` - Static type checker
- `ruff` - Fast linter + formatter (replaces black, isort, flake8)
- `mkdocs` + `mkdocs-material` - Documentation generator

### Implementation Commands Sequence

```bash
# Step 0: Activate flox environment and check installed tools
flox activate
flox list  # Check if uv and python3.13 are already available

# Step 1: Verify/install uv (may already be in flox environment)
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh

# Step 2: Initialize project
uv init --python 3.13
uv python pin 3.13

# Step 3: Add dependencies (DO NOT RUN YET - create structure first)
uv add fastapi uvicorn[standard] httpx
uv add aioboto3 redis[hiredis] asyncio-nats
uv add pyjwt[crypto] python-multipart pydantic-settings
uv add python-dotenv structlog
uv add --dev pytest pytest-asyncio pytest-cov pytest-mock mypy ruff mkdocs mkdocs-material

# Step 4: Create directory structure
mkdir -p src/domain/{entities,value_objects,protocols,services}
mkdir -p src/application/{use_cases,dto,ports}
mkdir -p src/infrastructure/{redis,s3,nats,clamav,auth,config}
mkdir -p src/presentation/api/v1/{routers,schemas}
mkdir -p src/presentation/api/middleware
mkdir -p src/observability
mkdir -p tests/{unit,integration,e2e}
mkdir -p docker
mkdir -p docs

# Step 5: Create all __init__.py files
touch src/__init__.py
touch src/domain/__init__.py
touch src/domain/entities/__init__.py
touch src/domain/value_objects/__init__.py
touch src/domain/protocols/__init__.py
touch src/domain/services/__init__.py
touch src/application/__init__.py
touch src/application/use_cases/__init__.py
touch src/application/dto/__init__.py
touch src/application/ports/__init__.py
touch src/infrastructure/__init__.py
touch src/infrastructure/redis/__init__.py
touch src/infrastructure/s3/__init__.py
touch src/infrastructure/nats/__init__.py
touch src/infrastructure/clamav/__init__.py
touch src/infrastructure/auth/__init__.py
touch src/infrastructure/config/__init__.py
touch src/presentation/__init__.py
touch src/presentation/api/__init__.py
touch src/presentation/api/v1/__init__.py
touch src/presentation/api/v1/routers/__init__.py
touch src/presentation/api/v1/schemas/__init__.py
touch src/presentation/api/middleware/__init__.py
touch src/observability/__init__.py
touch tests/__init__.py
touch tests/unit/__init__.py
touch tests/integration/__init__.py
touch tests/e2e/__init__.py

# Step 6: Create exceptions.py placeholder
touch src/domain/exceptions.py

# Step 7: Create main.py placeholder
touch src/presentation/main.py

# Step 8: Create observability files
touch src/observability/metrics.py
touch src/observability/logging.py

# Step 9: Sync dependencies (creates .venv and installs packages)
uv sync

# Step 10: Verify installation
uv run python --version  # Should show Python 3.13.x
```

### Validation Checklist

Before marking this story done, verify:

- [ ] `.python-version` exists and contains "3.13"
- [ ] `pyproject.toml` exists with [project] and [tool.uv] sections
- [ ] All dependencies listed in pyproject.toml under dependencies and dev-dependencies
- [ ] `uv.lock` exists (created by `uv sync`)
- [ ] `.venv/` directory exists (created by `uv sync`)
- [ ] `src/` root directory exists
- [ ] All subdirectories exist: domain, application, infrastructure, presentation, observability
- [ ] All __init__.py files exist in Python packages
- [ ] `tests/` directory with unit/, integration/, e2e/ subdirectories
- [ ] `docker/` directory exists (empty for now)
- [ ] `docs/` directory exists
- [ ] README.md has clear setup instructions
- [ ] `uv run python --version` outputs 3.13.x
- [ ] `uv run python -c "import fastapi; print(fastapi.__version__)"` works without errors

### .gitignore Recommendations

Add to .gitignore (if not already present):
```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python

# Virtual environments
.venv/
venv/
ENV/

# uv
.uv/

# IDE
.vscode/
.idea/
*.swp
*.swo

# Environment
.env
.env.local

# Testing
.pytest_cache/
.coverage
htmlcov/
.tox/

# Build
dist/
build/
*.egg-info/

# Logs
*.log

# OS
.DS_Store
Thumbs.db
```

### Next Stories Dependencies

**Story 1.2** (Development Tools) depends on this structure:
- Will add ruff.toml and mypy.ini
- Will configure pre-commit hooks
- Requires src/ structure to exist

**Story 1.3** (Docker Compose) depends on this foundation:
- Will create docker-compose.yml in docker/
- Will reference Python dependencies from pyproject.toml

**Story 1.4** (Configuration Management) depends on infrastructure/:
- Will create src/infrastructure/config/settings.py
- Will use pydantic-settings dependency we install here

### Project Structure Notes

**Alignment with Clean Architecture:**
- ✅ Dependency flow enforced by folder structure
- ✅ Domain layer has zero external dependencies
- ✅ Protocols defined in domain, implemented in infrastructure
- ✅ Application layer orchestrates use cases, no framework knowledge
- ✅ Presentation layer is pure FastAPI HTTP concerns

**Detected Alignment:**
- Structure matches architecture.md specification exactly (lines 262-307)
- Python 3.13 requirement enforced via .python-version
- uv as package manager per architecture decision
- All dependencies listed match architecture document recommendations

**No Conflicts Detected** - This is a greenfield project initialization

### References

- [Source: artifacts/planning-artifacts/architecture.md#Starter Template Evaluation] - Project initialization approach and directory structure
- [Source: artifacts/planning-artifacts/architecture.md#Project Initialization Command] - Exact uv commands and dependency list
- [Source: artifacts/planning-artifacts/architecture.md#Core Architectural Decisions] - Clean Architecture dependency flow rules
- [Source: artifacts/planning-artifacts/epics.md#Epic 1: Story 1.1] - Acceptance criteria and user story definition
- [Source: artifacts/planning-artifacts/prd.md] - Functional requirements context for why these dependencies are needed

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.5 (claude-sonnet-4.5)

### Debug Log References

N/A - Straightforward project initialization with no errors encountered

### Completion Notes List

- ✅ Successfully initialized uv project with Python 3.13
- ✅ Flox environment provided pre-installed uv (0.11.7) and python3.13 (3.13.12)
- ✅ All 11 production dependencies added successfully
- ✅ All 8 development dependencies added successfully  
- ✅ Note: Used `nats-py` instead of `asyncio-nats` (correct PyPI package name)
- ✅ Complete Clean Architecture directory structure created (28 directories)
- ✅ All 28 __init__.py files created in Python packages
- ✅ Placeholder files created: exceptions.py, main.py, metrics.py, logging.py
- ✅ Comprehensive README.md created with setup instructions and architecture overview
- ✅ All acceptance criteria verified and passing:
  - .python-version contains "3.13"
  - pyproject.toml configured with all dependencies
  - uv.lock generated (343 KB)
  - Complete directory structure matches architecture specification
  - All __init__.py files present
  - `uv run python --version` outputs Python 3.13.12

### Files Created

#### Project Configuration
- `.python-version` - Python 3.13 version pin
- `pyproject.toml` - uv project configuration with all dependencies
- `uv.lock` - Dependency lock file (auto-generated, 343 KB)
- `README.md` - Comprehensive project documentation

#### Directory Structure (src/)
- `src/__init__.py`
- `src/domain/__init__.py`
- `src/domain/entities/__init__.py`
- `src/domain/value_objects/__init__.py`
- `src/domain/protocols/__init__.py`
- `src/domain/services/__init__.py`
- `src/domain/exceptions.py` (placeholder)
- `src/application/__init__.py`
- `src/application/use_cases/__init__.py`
- `src/application/dto/__init__.py`
- `src/application/ports/__init__.py`
- `src/infrastructure/__init__.py`
- `src/infrastructure/redis/__init__.py`
- `src/infrastructure/s3/__init__.py`
- `src/infrastructure/nats/__init__.py`
- `src/infrastructure/clamav/__init__.py`
- `src/infrastructure/auth/__init__.py`
- `src/infrastructure/config/__init__.py`
- `src/presentation/__init__.py`
- `src/presentation/api/__init__.py`
- `src/presentation/api/v1/__init__.py`
- `src/presentation/api/v1/routers/__init__.py`
- `src/presentation/api/v1/schemas/__init__.py`
- `src/presentation/api/middleware/__init__.py`
- `src/presentation/main.py` (placeholder)
- `src/observability/__init__.py`
- `src/observability/metrics.py` (placeholder)
- `src/observability/logging.py` (placeholder)

#### Directory Structure (tests/)
- `tests/__init__.py`
- `tests/unit/__init__.py`
- `tests/integration/__init__.py`
- `tests/e2e/__init__.py`

#### Other Directories
- `docker/` (empty, ready for Story 1.3)

### Implementation Notes

**Flox Integration:**
- Flox environment provided both uv (0.11.7) and Python 3.13.12 pre-installed
- Used `eval "$(flox activate)"` pattern to activate environment in bash sessions
- No additional tool installation was required

**Dependency Note:**
- Changed `asyncio-nats` to `nats-py` - this is the correct package name in PyPI
- All other dependencies installed as specified in the architecture document

**Structure Verification:**
- 28 total directories created
- 28 __init__.py files ensure all directories are proper Python packages
- Structure exactly matches architecture specification from Epic 1, Story 1.1
