# Story 1.2: Configure Development Tools and Code Quality Standards

Status: done

## Story

As a **developer**,
I want **development tools (pytest, ruff, mypy, MkDocs) configured with project standards**,
So that **code quality is enforced automatically and testing infrastructure is ready**.

## Acceptance Criteria

1. **pyproject.toml dependencies** — `pyproject.toml` includes pytest, pytest-asyncio, pytest-cov, pytest-mock, ruff, mypy, and mkdocs dependency groups (ALREADY DONE in Story 1.1)

2. **Ruff linting configuration** — `ruff.toml` exists with PEP 8 enforcement rules and executes without errors on empty src/ structure when running `uv run ruff check src/`

3. **Mypy strict type checking** — `mypy.ini` exists with strict type checking configuration and executes without errors on empty src/ structure when running `uv run mypy src/`

4. **Test directory structure** — `tests/` directory structure mirrors `src/` structure (unit/, integration/, e2e/ with __init__.py files)

5. **Ruff check passes** — Running `uv run ruff check src/` executes without errors on the clean src/ architecture structure

6. **Mypy check passes** — Running `uv run mypy src/` executes without errors on the clean src/ architecture structure

## Tasks / Subtasks

- [x] Create ruff.toml configuration file (AC: #2)
  - [x] Define linter rules: PEP 8 compliance with ruff built-in rules
  - [x] Configure import sorting (isort compatibility)
  - [x] Exclude patterns: __pycache__, .venv, .git, tests/__pycache__
  - [x] Line length: 100 characters (standard for FastAPI projects)
  - [x] Indentation: 4 spaces
  - [x] Set formatter defaults (quote style, trailing commas, etc.)
  - [x] Verify ruff.toml is valid TOML and loads without errors

- [x] Create mypy.ini configuration file (AC: #3)
  - [x] Set strict mode: strict = True
  - [x] Configure Python version: python_version = 3.13
  - [x] Exclude patterns for third-party and infrastructure modules
  - [x] Enable all strict options (warn_unused_configs, warn_redundant_casts, warn_unused_ignores, etc.)
  - [x] Set ignore_missing_imports = False (enforce type stubs)
  - [x] Verify mypy.ini is valid and loads without errors

- [x] Create tests/ subdirectories matching src/ structure (AC: #4)
  - [x] Create tests/unit/ directory (for domain + application layer tests)
  - [x] Create tests/integration/ directory (for infrastructure implementations)
  - [x] Create tests/e2e/ directory (for full API flow tests)
  - [x] Add __init__.py to tests/, tests/unit/, tests/integration/, tests/e2e/
  - [x] Verify directory structure matches src/ organization

- [x] Create pytest.ini configuration file
  - [x] Configure test discovery patterns: test files matching test_*.py or *_test.py
  - [x] Configure asyncio mode for pytest-asyncio: asyncio_mode = auto
  - [x] Set test directory: testpaths = ["tests"]
  - [x] Set minimum Python version: minversion = 7.0
  - [x] Add markers for test categorization: @pytest.mark.unit, @pytest.mark.integration, @pytest.mark.e2e
  - [x] Configure coverage settings for pytest-cov

- [x] Validate ruff configuration against clean src/ architecture (AC: #5)
  - [x] Run `uv run ruff check src/` command
  - [x] Verify no linting errors are reported
  - [x] Fix any configuration issues if ruff reports problems
  - [x] Test ruff format (read-only) with `uv run ruff format --check src/`

- [x] Validate mypy configuration against clean src/ architecture (AC: #6)
  - [x] Run `uv run mypy src/` command
  - [x] Verify no type checking errors are reported
  - [x] Document any necessary type: ignore comments if needed
  - [x] Verify all imports and protocols are properly typed

- [x] Update README.md with code quality instructions (AC: #2, #3, #6)
  - [x] Add "Code Quality" section documenting ruff, mypy, and pytest commands
  - [x] Include example: `make check` to run all quality checks
  - [x] Include example: `make lint`, `make type-check`, `make test`
  - [x] Document expected behavior: tools should run without errors

- [x] Verify Makefile targets work correctly (AC: all)
  - [x] Test `make lint` → runs ruff check
  - [x] Test `make format` → runs ruff format
  - [x] Test `make type-check` → runs mypy
  - [x] Test `make test` → runs pytest
  - [x] Test `make test-coverage` → runs pytest with coverage
  - [x] Test `make check` → runs all quality checks in sequence

### Review Findings

- [x] [Review][Patch] `make test` and `make test-coverage` fail because pytest collects zero tests, despite the Makefile verification tasks being checked. Evidence: `make test` exits with pytest code 5 (`collected 0 items`), and `make test-coverage` also exits 5 with no data collected. Add at least one real/smoke test or otherwise make the configured test targets succeed. [Makefile:69] — Resolved by adding a unit smoke test for domain exceptions.
- [x] [Review][Patch] Coverage settings are placed in `pytest.ini`, but `coverage.py` does not read that file as its config source. Evidence: `coverage debug config` attempts `.coveragerc`, `setup.cfg`, `tox.ini`, and `pyproject.toml`, reads `pyproject.toml`, and shows `config_file: None` for the new coverage settings. Move coverage config to `.coveragerc` or `[tool.coverage.*]` in `pyproject.toml`, or pass `--cov-config=pytest.ini`. [pytest.ini:23] — Resolved by keeping coverage configuration in `pytest.ini` and passing `--cov-config=pytest.ini` for coverage runs.
- [x] [Review][Dismiss] The implementation modifies `src/` even though the story explicitly says Story 1.2 should not modify application code. Evidence: diff changes `src/domain/exceptions.py`, `src/observability/logging.py`, `src/observability/metrics.py`, and `src/presentation/main.py`; story Dev Notes say "NO changes to: `src/` directory". Revert these source changes or adjust the tooling config so Story 1.2 can pass without touching application code. [src/domain/exceptions.py:7] — Skipped per user direction; source typing-related changes are intentionally retained.
- [x] [Review][Patch] `DomainException` was renamed to `DomainError` without a compatibility alias, which can break existing imports/catches from the branch baseline. Evidence: `origin/dev` exported `DomainException`; this diff removes it. If the rename is kept, add a compatibility alias or update all consumers and document the intentional API change. [src/domain/exceptions.py:7] — Resolved by reverting the rename and retaining `DomainException`.
- [x] [Review][Patch] The checked task "Verify directory structure matches src organization" is not satisfied by the diff. Evidence: current tracked test structure only has `tests/unit`, `tests/integration`, and `tests/e2e` package roots; it does not include the nested `tests/unit/domain`, `tests/unit/application`, `tests/integration/infrastructure`, or `tests/e2e/api` layout described in the story's Testing Standards. Add the missing package directories/files or correct the story task if the flatter layout is intentional. [tests] — Resolved by adding the nested test package directories.
- [x] [Review][Patch] `mypy.ini` marks the "Exclude patterns" subtask complete but does not define an explicit `exclude` setting. Evidence: the new config has `strict`, `python_version`, `namespace_packages`, and per-module sections only. Add the intended exclude pattern(s) for generated/cache/build paths and any story-approved third-party/infrastructure exclusions, or uncheck/correct the task. [mypy.ini:1] — Resolved by adding explicit generated/cache/build exclusions.

## Dev Notes

### Architecture Patterns and Constraints

**Clean Architecture Enforcement Rules:**
- Domain layer imports NOTHING from application, infrastructure, or presentation — keep pure business logic
- Application layer imports from domain only — orchestration layer
- Infrastructure layer imports from domain (protocols) and application (use case interfaces)
- Presentation layer imports from application (use cases) and infrastructure (dependency injection)

**Code Quality Standards (from architecture.md):**

1. **Strict PEP 8 Enforcement**: Python naming conventions enforced by ruff with snake_case for functions/variables, PascalCase for classes
2. **Type Safety**: mypy strict mode prevents interface mismatches and type-related bugs before runtime
3. **Testing**: pytest + pytest-asyncio for async test support; tests/ directory mirrors src/ organization
4. **Async Consistency**: All service methods use `async def`, all calls are `await`-ed, no blocking I/O in async routes
5. **No Framework Dependencies in Domain**: Domain layer must import NOTHING from FastAPI, Redis, S3, NATS, or any external library

**Development Workflow Integration (from Makefile and architecture.md):**

The project uses a comprehensive Makefile for all development tasks:
- `make setup` — initialize environment
- `make lint` — run ruff linter
- `make format` — format code with ruff
- `make type-check` — run mypy
- `make check` — run all quality checks (format, lint, type)
- `make test` — run all tests
- `make test-coverage` — run tests with coverage report

### Source Tree Components to Touch

**Configuration files to create:**
- `/home/dev/projects/rag-file-uploader/ruff.toml` — Linting + formatting config
- `/home/dev/projects/rag-file-uploader/mypy.ini` — Type checking config
- `/home/dev/projects/rag-file-uploader/pytest.ini` — Test discovery + asyncio config (OPTIONAL: pytest also reads from pyproject.toml)

**Directories to create/verify:**
- `tests/` — Main test directory (already exists from Story 1.1)
- `tests/unit/` — Unit tests for domain + application layer
- `tests/integration/` — Infrastructure implementation tests
- `tests/e2e/` — Full API flow end-to-end tests

**Files to update:**
- `README.md` — Add code quality section with tool usage examples

**NO changes to:**
- `src/` directory — Story 1.2 does not modify application code, only adds tool configuration
- `pyproject.toml` — Dependencies already added in Story 1.1 (pytest, ruff, mypy, mkdocs)
- `.python-version` — Already set to 3.13 in Story 1.1
- Existing `__init__.py` files — Keep as-is from Story 1.1

### Testing Standards

**Framework & Structure:**
- `pytest` — Test discovery and execution framework
- `pytest-asyncio` — Async test support with `@pytest.mark.asyncio` decorator
- `pytest-mock` — Mocking infrastructure dependencies (Redis, S3, NATS, ClamAV)
- `pytest-cov` — Code coverage reporting with target of 80%+ for domain/application layers

**Test Organization (mirrors src/ structure):**
```
tests/
├── __init__.py
├── unit/              # No external service dependencies
│   ├── __init__.py
│   ├── domain/        # Domain entity and service tests
│   └── application/   # Use case tests with mocked infrastructure
├── integration/       # Real Redis, S3, NATS, ClamAV connections
│   ├── __init__.py
│   ├── infrastructure/
│   └── conftest.py    # Pytest fixtures for external services
└── e2e/              # Full API flow tests with FastAPI TestClient
    ├── __init__.py
    ├── api/
    └── conftest.py   # Fixtures for complete app setup
```

**Pytest Configuration (pytest.ini or pyproject.toml [tool.pytest]):**
- `asyncio_mode = auto` — Auto-detect asyncio for async tests
- `testpaths = ["tests"]` — Only discover tests in tests/ directory
- `python_files = ["test_*.py", "*_test.py"]` — Test file naming convention
- Markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`

**Coverage Expectations:**
- Run: `uv run pytest --cov=src --cov-config=pytest.ini --cov-report=html --cov-report=term-missing`
- Target: ≥80% coverage for domain layer, ≥70% for application layer
- Exclude from coverage: infrastructure adapters (external services are hard to test), presentation layer (FastAPI handles most validation)

### Code Style & Linting

**Ruff Configuration (ruff.toml) — PEP 8 Enforcement:**

Key settings:
- **Line length**: 100 characters (FastAPI convention, balances readability and conciseness)
- **Indentation**: 4 spaces (PEP 8 standard)
- **Quote style**: double quotes (industry convention)
- **Trailing commas**: multiline (improves diffs)
- **Include patterns**: `["*.py", "*.pyi"]`
- **Exclude patterns**: `["__pycache__", ".venv", ".git", "node_modules", "dist", "build"]`
- **Lint rules** (ruff built-in):
  - `E` — pycodestyle (PEP 8 enforcement): E101-E902 errors
  - `W` — pycodestyle warnings: W191, W292, W293
  - `F` — Pyflakes (undefined names, unused imports): F401, F841, etc.
  - `I` — isort (import sorting)
  - `N` — pep8-naming (PEP 8 naming conventions)
  - `UP` — pyupgrade (Python version idioms)
  - `B` — flake8-bugbear (common bugs)
  - `C4` — flake8-comprehensions (comprehension style)
  - `T10` — flake8-debugger (no print debugging in production)
  - `PT` — flake8-pytest-style (pytest best practices)

**Mypy Configuration (mypy.ini) — Type Safety with Strict Mode:**

Key settings:
- **strict = True** — Enables all strict type checking options:
  - `warn_unused_configs = True` — Warn if mypy config sections are unused
  - `warn_redundant_casts = True` — Flag unnecessary type casts
  - `warn_unused_ignores = True` — Flag unnecessary `# type: ignore` comments
  - `warn_return_any = True` — Flag functions returning Any when specific type is expected
  - `warn_untyped_defs = True` — Require type annotations on all function definitions
  - `check_untyped_defs = True` — Type-check untyped function bodies
  - `disallow_untyped_defs = True` — Error on untyped function definitions
  - `disallow_incomplete_defs = True` — Error on incomplete type signatures
  - `disallow_untyped_calls = True` — Error when calling untyped functions from typed code
  - `no_implicit_optional = True` — Disallow Optional[] syntax sugar
  - `no_implicit_reexport = True` — Explicit re-exports required
  - `strict_equality = True` — Stricter equality checking
  - `strict_optional = True` — None is not compatible with non-optional types
- **python_version = 3.13** — Target Python version for type checking
- **namespace_packages = True** — Support PEP 420 namespace packages
- **plugins** — Type stubs for FastAPI, pydantic, etc.

**Enforcing Standards:**
- Pre-commit hooks (Story 1.2 creates configs, Story TBD will implement git hooks)
- Makefile targets: `make lint`, `make format`, `make type-check`
- CI/CD pipeline: GitHub Actions will run `make check` before allowing merge

### Tools and Frameworks

**Package Manager & Environment:**
- `uv` — Ultra-fast Python package manager (10-100x faster than pip/poetry)
- Dependency groups in pyproject.toml: main dependencies + [dependency-groups] dev section
- Virtual environment: Managed automatically by uv, located in .venv/

**Core Dependencies (already added in Story 1.1):**
- Web framework: `fastapi>=0.136.1`, `uvicorn[standard]>=0.46.0`, `httpx>=0.28.1`
- Data & Storage: `aioboto3>=15.5.0`, `redis[hiredis]>=7.4.0`, `nats-py>=2.14.0`
- Security & Validation: `pyjwt[crypto]>=2.12.1`, `pydantic-settings>=2.14.0`, `python-multipart>=0.0.27`
- Utilities: `python-dotenv>=1.2.2`, `structlog>=25.5.0`

**Development Tools (Story 1.2 configures these):**
- **Testing**: `pytest>=9.0.3`, `pytest-asyncio>=1.3.0`, `pytest-cov>=7.1.0`, `pytest-mock>=3.15.1`
- **Linting & Formatting**: `ruff>=0.15.12` (replaces black, isort, flake8, pylint in one tool)
- **Type Checking**: `mypy>=1.20.2` (static type analysis)
- **Documentation**: `mkdocs>=1.6.1`, `mkdocs-material>=9.7.6`

**Command Execution Pattern:**
- All commands run through `uv run <tool>` to ensure consistency across environments
- Flox environment activation (already set up): `flox activate` — provides isolated dev environment
- Makefile provides convenient shortcuts: `make <target>`

### Dependencies & Context

**Story 1.1 Foundation (already completed):**

Story 1.1 "Initialize Python Project with uv and Clean Architecture Structure" established:
- `pyproject.toml` with Python 3.13 and all core + dev dependencies
- `.python-version` file pinning Python 3.13
- Complete Clean Architecture directory structure:
  - `src/domain/`, `src/application/`, `src/infrastructure/`, `src/presentation/`
  - All required subdirectories: entities/, value_objects/, protocols/, services/, use_cases/, etc.
  - All `__init__.py` files present for package discovery
- `tests/` root directory with unit/, integration/, e2e/ subdirectories
- `README.md` with project description and basic setup
- `Makefile` with development targets
- Virtual environment created and dependencies locked via `uv sync`

**Story 1.2 Builds On Story 1.1:**
- Adds configuration files (ruff.toml, mypy.ini, pytest.ini) for consistent tooling across team
- Tools are already installed as dev dependencies — Story 1.2 just configures them
- Tests are now discoverable and configured
- Linting and type checking are now standardized

**Sequencing Note:**
- Story 1.2 must complete before Story 1.3 (Docker Compose) to ensure all developers can validate code locally
- Subsequent stories (2.1+) will rely on these standards being in place

**Files Already Committed in Story 1.1 (do NOT modify):**
- `pyproject.toml` — dependency groups already include pytest, ruff, mypy, mkdocs
- `uv.lock` — generated lockfile, do not manually edit
- `.python-version` — contains "3.13"
- `README.md` — basic setup info, Story 1.2 will ADD code quality section
- `src/` directory tree with all Clean Architecture structure
- `tests/` directory with unit/, integration/, e2e/ subdirectories
- `Makefile` — already has targets for lint, format, type-check, test

**Commands from Story 1.1 (already working):**
- `uv sync` — Sync dependencies and create virtual environment
- `uv run pytest` — Run tests (will discover tests/unit/, tests/integration/, tests/e2e/)
- `uv run ruff check src/` — Will run once ruff.toml is created
- `uv run mypy src/` — Will run once mypy.ini is created

### References

**Architecture Document (planning-artifacts/architecture.md):**
- Lines 172-185: "FastAPI Project Architecture" — Development tools section
- Lines 315-353: "Testing Framework & Development Workflow" — Tool usage patterns
- Lines 325-349: "Code Quality & Development Workflow" — Ruff/mypy/pytest specifics
- Lines 367-385: "Implementation Notes & Async consistency" — Clean Architecture enforcement

**Epics Document (planning-artifacts/epics.md):**
- Lines 282-297: "Story 1.2: Configure Development Tools and Code Quality Standards" — Full story requirements
- Acceptance criteria explicitly require ruff.toml and mypy.ini

**Story 1.1 (implementation-artifacts/1-1-initialize-python-project-with-uv-and-clean-architecture-structure.md):**
- "Review Findings (AI)" section — Lessons learned from Story 1.1 implementation
- "Dependencies Reference" section (lines 210-238) — All tools are already added to pyproject.toml
- Establishes directory structure and Clean Architecture patterns that Story 1.2 leverages

**Makefile (project root):**
- Targets: lint, format, type-check, check, test, test-coverage (all pre-configured in Story 1.1)
- Story 1.2 enables these targets by creating configuration files

**Clean Architecture Pattern References:**
- Domain layer isolation: No external imports (FastAPI, Redis, S3, etc.)
- Protocol-based infrastructure: Interfaces defined in domain/, implementations in infrastructure/
- Dependency inversion: Application depends on domain protocols, not infrastructure implementations

**Python Version & PEP 8:**
- Python 3.13: Latest version with improved asyncio performance (critical for concurrent chunk uploads)
- PEP 8: Standard Python naming conventions (snake_case, PascalCase for classes)
- PEP 420: Namespace packages (supported via mypy configuration)

**Testing Best Practices:**
- pytest-asyncio for async test support (required for all async application code)
- pytest-mock for infrastructure mocking (domain logic tested without Redis/S3 running)
- pytest-cov for coverage reporting (target: ≥80% domain layer, ≥70% application layer)
- Test organization mirrors source code organization (unit/, integration/, e2e/)

**Type Safety:**
- mypy strict mode catches type errors before runtime
- Mypy --strict option enables all strict checks (warn_untyped_defs, disallow_incomplete_defs, etc.)
- Type annotations on all function signatures (no implicit Any)
- Protocol classes in domain/ for infrastructure interfaces

**Performance & Consistency:**
- ruff: 10-100x faster than black + isort + flake8 + pylint (Rust implementation)
- Single tool for linting + formatting reduces tool chaining complexity
- Configuration files committed to repo ensure consistency across team members and CI/CD pipeline
