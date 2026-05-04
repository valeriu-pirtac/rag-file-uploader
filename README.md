# rag-file-uploader

**Chunked Upload Service for RAG Pipeline**

A FastAPI-based microservice that handles chunked file uploads with resumability, integrity verification, and event-driven pipeline integration. Built with Clean Architecture for the RAG (Retrieval-Augmented Generation) platform.

## Features

- **Chunked Upload Protocol**: tus-protocol-inspired chunked uploads with SHA-256 verification
- **Resumability**: 24-hour session persistence enabling resume-from-offset
- **Multi-Tenant Isolation**: Complete workspace-scoped data separation
- **Event-Driven**: NATS JetStream integration for downstream RAG pipeline
- **Security**: JWT authentication with role-based access control
- **Observability**: Prometheus metrics and structured logging

## Technology Stack

- **Python 3.13** - Latest Python with performance improvements
- **uv** - Fast Rust-based package manager (10-100x faster than pip)
- **FastAPI** - Modern async web framework with automatic OpenAPI generation
- **Clean Architecture** - Domain-driven design with clear dependency flow

## Prerequisites

- **flox** - Development environment manager
- **uv** - Python package manager (available in flox environment)
- **Python 3.13** - (available in flox environment)
- **Docker** - For running external services (Redis, MinIO, NATS, ClamAV)
- **Docker Compose** - For orchestrating multi-container setup

### Port Requirements

⚠️ **Ensure the following ports are available before starting Docker services:**
- **6379** - Redis
- **9000** - MinIO S3 API
- **9001** - MinIO Web Console
- **4222** - NATS Client Connections
- **8222** - NATS HTTP Monitoring
- **3310** - ClamAV TCP Socket

If any ports are already in use, stop the conflicting services or modify the port mappings in `docker/docker-compose.yml`.

## Setup Instructions

### 1. Start External Services with Docker Compose

Before running the application, start all required external services:

```bash
# Navigate to docker directory
cd docker

# Copy environment template (if needed)
cp ../.env.example ../.env

# Start all services in detached mode
docker compose up -d

# Verify all services are healthy (this may take up to 2 minutes for ClamAV)
docker compose ps
```

**Services Started:**
- **Redis** (port 6379) - Session state storage with AOF persistence
- **MinIO** (ports 9000/9001) - S3-compatible object storage
  - API: http://localhost:9000
  - Console: http://localhost:9001 (credentials: minioadmin/minioadmin123)
- **NATS JetStream** (ports 4222/8222) - Event bus for pipeline integration
  - Client: nats://localhost:4222
  - Monitoring: http://localhost:8222
- **ClamAV** (port 3310) - Virus scanning service
  - Note: Takes 60-120 seconds to download virus definitions on first start

#### Verify Service Health

```bash
# Check all services are running and healthy
docker compose ps

# Test Redis connectivity
docker exec rag-uploader-redis redis-cli ping
# Expected: PONG

# Test MinIO health
curl http://localhost:9000/minio/health/live
# Expected: HTTP 200 OK

# Test NATS health
curl http://localhost:8222/healthz
# Expected: HTTP 200 OK

# Test ClamAV connectivity
echo "PING" | nc localhost 3310
# Expected: PONG
```

#### Stop Services

```bash
# Stop all services (preserves data volumes)
docker compose down

# Stop and remove all data volumes (clean slate)
docker compose down -v
```

### 2. Quick Start with Makefile

The project includes a comprehensive Makefile for all common tasks:

```bash
# Show all available commands
make help

# One-command setup: create venv and install dependencies
make setup

# Start development server
make dev

# Run all tests
make test

# Run code quality checks
make check

# Format code
make format
```

### 3. Manual Setup (Alternative)

#### 1. Activate flox environment

```bash
flox activate
```

#### 2. Install dependencies

```bash
uv sync
```

This will:

- Create a virtual environment in `.venv/`
- Install all production and development dependencies
- Generate `uv.lock` for reproducible builds

#### 3. Run development server

```bash
uv run uvicorn src.presentation.main:app --reload
```

The API will be available at http://localhost:8000

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Development Commands

### Using Makefile (Recommended)

```bash
# Setup & Installation
make setup              # Initialize project environment
make install            # Sync dependencies after pyproject.toml changes
make install-dev        # Install with all dev dependencies

# Testing
make test               # Run all tests
make test-unit          # Run unit tests only
make test-integration   # Run integration tests only
make test-e2e           # Run E2E tests only
make test-coverage      # Run tests with coverage report

# Code Quality
make lint               # Run ruff linter
make format             # Format code with ruff
make format-check       # Check formatting without modifying
make type-check         # Run mypy type checker
make check              # Run all checks (format, lint, type)

# Development
make dev                # Start dev server with auto-reload
make dev-debug          # Start dev server with debug logging
make shell              # Start Python shell with project context

# Documentation
make docs               # Build documentation
make docs-serve         # Serve docs at http://127.0.0.1:8000

# Cleanup
make clean              # Remove all build artifacts and venv
make clean-cache        # Remove only cache files

# Utilities
make info               # Display project information
make deps-outdated      # Check for outdated dependencies
make lock               # Regenerate uv.lock file

# CI/CD
make ci                 # Run full CI pipeline
make ci-coverage        # Run CI with coverage report
```

### Manual Commands (Without Makefile)

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src --cov-config=pytest.ini --cov-report=html

# Run specific test file
uv run pytest tests/unit/test_example.py

# Lint and format with ruff
uv run ruff check src/
uv run ruff format src/

# Type checking with mypy
uv run mypy src/
```

## Project Structure

```
rag-file-uploader/
├── src/
│   ├── domain/                      # Pure business logic, no dependencies
│   │   ├── entities/                # Domain entities (UploadSession, Chunk, etc.)
│   │   ├── value_objects/           # Value objects (SHA256Hash, WorkspaceId, etc.)
│   │   ├── protocols/               # Interfaces for infrastructure
│   │   ├── services/                # Domain services
│   │   └── exceptions.py            # Domain exceptions
│   ├── application/                 # Use cases orchestration
│   │   ├── use_cases/               # Business workflows
│   │   ├── dto/                     # Data Transfer Objects
│   │   └── ports/                   # Application-level interfaces
│   ├── infrastructure/              # External service implementations
│   │   ├── redis/                   # Redis session store
│   │   ├── s3/                      # MinIO/S3 storage client
│   │   ├── nats/                    # NATS event publisher
│   │   ├── clamav/                  # ClamAV scanner client
│   │   ├── auth/                    # JWT validation middleware
│   │   └── config/                  # Configuration management
│   ├── presentation/                # FastAPI HTTP layer
│   │   ├── api/v1/                  # API v1 endpoints
│   │   └── main.py                  # FastAPI app initialization
│   └── observability/               # Metrics and logging
├── tests/
│   ├── unit/                        # Unit tests (domain + application)
│   ├── integration/                 # Integration tests (infrastructure)
│   └── e2e/                         # End-to-end API tests
├── docker/                          # Docker Compose and Dockerfile
├── docs/                            # Project documentation
├── .python-version                  # Python 3.13
├── pyproject.toml                   # uv project configuration
└── uv.lock                          # Dependency lock file
```

## Code Quality Standards

This project enforces strict code quality standards to ensure consistency, maintainability, and type safety across the codebase.

### Tools Overview

- **ruff** - Fast all-in-one Python linter and formatter (replaces black, isort, flake8, pylint)
- **mypy** - Static type checker with strict mode enabled
- **pytest** - Test discovery and execution framework with asyncio support

### Configuration Files

- `ruff.toml` - Linting and formatting rules (PEP 8, import sorting, line length 100)
- `mypy.ini` - Type checking with strict mode and Python 3.13 target
- `pytest.ini` - Test discovery patterns and asyncio configuration

### Running Quality Checks

#### Run all checks
```bash
make check              # Runs format-check, lint, and type-check
```

#### Individual checks
```bash
make lint               # Linting with ruff
make format             # Format code with ruff (modifies files)
make format-check       # Check formatting without modifying
make type-check         # Type checking with mypy
```

#### Manual commands
```bash
# Linting
uv run ruff check src/ tests/

# Formatting
uv run ruff format src/ tests/

# Type checking
uv run mypy src/
```

### Testing

Tests are organized into three categories:

- **Unit tests** (`tests/unit/`) - Domain and application layer tests with no external dependencies
- **Integration tests** (`tests/integration/`) - Tests for infrastructure implementations (Redis, S3, etc.)
- **E2E tests** (`tests/e2e/`) - Full API flow tests using FastAPI TestClient

#### Running tests
```bash
make test               # Run all tests
make test-unit          # Run unit tests only
make test-integration   # Run integration tests only
make test-e2e           # Run E2E tests only
make test-coverage      # Run with coverage report (target: ≥80% domain, ≥70% app)
```

#### Manual commands
```bash
# Run all tests
uv run pytest tests/

# Run with coverage
uv run pytest tests/ --cov=src --cov-config=pytest.ini --cov-report=html

# Run specific test category
uv run pytest tests/unit -v
uv run pytest tests/integration -v
uv run pytest tests/e2e -v
```

### Code Style Guidelines

- **Line length**: 100 characters (enforced by ruff)
- **Naming conventions**: snake_case for functions/variables, PascalCase for classes and exceptions
- **Imports**: Organized per isort (standard library → third-party → local)
- **Type annotations**: Strictly required on all function signatures (enforced by mypy)
- **Async consistency**: All service methods use `async def`, all calls are `await`-ed

### Pre-commit Workflow

Before committing code:

1. Format: `make format`
2. Lint: `make lint`
3. Type check: `make type-check`
4. Test: `make test`

Or use `make check` to run all checks in sequence.

## Architecture

This project follows **Clean Architecture** principles:

- **Domain Layer** - Pure business logic with zero external dependencies
- **Application Layer** - Use case orchestration, depends on Domain only
- **Infrastructure Layer** - External service implementations via Domain protocols
- **Presentation Layer** - FastAPI routes, depends on Application use cases

**Dependency Flow**: Presentation → Application → Domain ← Infrastructure (via Protocols)

## Development Workflow

1. **Create feature branch** from `main`
2. **Implement changes** following Clean Architecture patterns
3. **Write tests** for new functionality (TDD recommended)
4. **Run quality checks**: `ruff`, `mypy`, `pytest`
5. **Submit PR** for code review

## External Dependencies

All external services are managed via Docker Compose (see `docker/docker-compose.yml`):

- **Redis 7** - Upload session state persistence with AOF durability
- **MinIO** - S3-compatible bronze-layer file storage with workspace isolation
- **NATS JetStream** - Event publishing for downstream RAG pipeline services
- **ClamAV** - Real-time virus scanning with automatic definition updates

**Environment Configuration:**
- Copy `.env.example` to `.env` and customize as needed
- Default credentials are provided for local development
- Production deployments should use secure credential management

## License

See [LICENSE](LICENSE) for details.

## Contributing

This project is part of the RAG platform development.
