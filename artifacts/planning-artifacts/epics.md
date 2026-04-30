---
stepsCompleted:
    [
        "step-01-validate-prerequisites",
        "step-02-design-epics",
        "step-03-create-stories",
        "step-04-final-validation",
        "step-05-restructure",
    ]
inputDocuments:
    - "artifacts/planning-artifacts/prd.md"
    - "artifacts/planning-artifacts/architecture.md"
    - "artifacts/planning-artifacts/c4-architecture.md"
workflowStatus: restructured
completedAt: "2026-04-30T13:00:20+03:00"
restructuredAt: "2026-04-30T13:32:00+03:00"
restructureReason: "Fixed 2 critical structural issues: (1) Merged Epics 5+7 into single 'File Assembly, Integrity & Pipeline Integration' epic to eliminate forward dependency, (2) Dissolved Epic 8 'Multi-Tenant Isolation' and moved isolation stories into Epics 2, 3, and 5 where they belong - isolation must be built-in from the start. Also added webhook callback stories (PRD MVP requirement) and broke down oversized Story 5.4."
---

# rag-file-uploader - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for rag-file-uploader, decomposing the requirements from the PRD, UX Design if it exists, and Architecture requirements into implementable stories.

**RESTRUCTURING NOTES:**

- ✅ **Fixed Critical Issue #1**: Merged old Epic 5 (File Integrity) + old Epic 7 (Event Publishing) into new Epic 5 to eliminate forward dependency
- ✅ **Fixed Critical Issue #2**: Dissolved old Epic 8 (Isolation) - moved isolation stories into foundational epics (2, 3, 5)
- ✅ **Added Missing Stories**: Webhook callback alternative (Story 5.7) per PRD MVP scope
- ✅ **Fixed Oversized Story**: Broke down old Story 5.4 into 5 focused stories (5.4-5.8)

## Requirements Inventory

### Functional Requirements

**Upload Session Management (FR1-FR9):**

- **FR1**: Workspace owner can initiate a new upload session for a PDF file, receiving a session ID and expiry timestamp
- **FR2**: Workspace owner can upload a file in sequential chunks, each carrying a SHA-256 checksum header
- **FR3**: The system validates the SHA-256 checksum of each chunk independently before committing it
- **FR4**: The system rejects any chunk whose checksum does not match, returning a `460 Checksum Mismatch` error with an actionable message
- **FR5**: Workspace owner can query the current verified byte offset of an active upload session
- **FR6**: Workspace owner can abort an active upload session, triggering cleanup of all associated state
- **FR7**: Workspace owner can list all upload sessions for their active workspace, filterable by status
- **FR8**: Workspace owner can retrieve detailed metadata for a specific upload session (filename, size, status, checksum, timestamps)
- **FR9**: Collaborators with shared file access can retrieve metadata for specifically shared files

**Upload Resumability (FR10-FR13):**

- **FR10**: The system persists upload session state (verified offset, chunk manifest) durably for a minimum of 24 hours
- **FR11**: A client can resume an interrupted upload from the last verified byte offset without re-uploading already-committed chunks
- **FR12**: Upload sessions that exceed the 24-hour TTL expire gracefully, returning `404 Session Not Found` to resumption attempts
- **FR13**: The system supports multi-file batch uploads, processing each file independently through the chunk pipeline

**File Integrity & Validation (FR14-FR18):**

- **FR14**: The system validates that uploaded files do not exceed 1 GB before accepting a session
- **FR15**: The system validates that uploaded files are of type `application/pdf`, rejecting unsupported MIME types with `415 Unsupported Media Type`
- **FR16**: The system detects duplicate files within a tenant workspace using SHA-256 fingerprint matching and returns `409 Duplicate File`
- **FR17**: The system scans assembled files for known malicious payloads before committing to bronze-layer storage
- **FR18**: The system assembles all verified chunks into an immutable, unmodified file on MinIO/S3 bronze-layer storage

**Pipeline Integration (FR19-FR21):**

- **FR19**: The system publishes a `FILE_LOAD_COMPLETED` event upon successful file assembly and storage, carrying: file ID, tenant/workspace ID, S3 path, SHA-256 checksum, file size, and timestamp
- **FR20**: The system retries `FILE_LOAD_COMPLETED` event publication on NATS unavailability before marking the upload as failed
- **FR21**: Downstream services can subscribe to `FILE_LOAD_COMPLETED` events without any coupling to the upload service

**Workspace & Tenant Isolation (FR22-FR26):**

- **FR22**: Each user who creates a workspace becomes its sole owner with full read/write/delete rights
- **FR23**: Workspace owners can grant other users read-only access to specific files within their workspace
- **FR24**: Workspace owners can grant other users read-only access to their entire workspace
- **FR25**: Collaborators cannot upload, modify, or delete files in any workspace — regardless of their access grant level
- **FR26**: The system enforces complete data isolation between workspaces at storage path, session state, deduplication scope, and rate limit boundaries

**Authentication & Authorisation (FR27-FR29):**

- **FR27**: The system validates a JWT on every request, rejecting requests with missing or invalid tokens with `401 Unauthorized`
- **FR28**: The system enforces workspace-role-based access control — collaborator tokens are rejected on write endpoints with `403 Forbidden`
- **FR29**: The system supports workspace-scoped JWT tokens issued by the platform auth service, carrying workspace ID, role, and optionally shared file IDs

**Observability & Operations (FR30-FR33):**

- **FR30**: The system exposes Prometheus metrics: `upload_chunks_total`, `upload_bytes_total`, `chunk_verification_failures_total`, all labelled by workspace
- **FR31**: The system emits structured logs for every upload lifecycle event, including tenant ID, session ID, chunk index, and failure reason where applicable
- **FR32**: Platform operators can determine service health and active upload load without log scraping
- **FR33**: The system exposes an OpenAPI 3.0 specification at `/openapi.json` consumable by the Vue.js frontend without a custom SDK

**Capacity & Availability (FR34-FR35):**

- **FR34**: The system enforces a configurable maximum of concurrent upload sessions per service instance, returning `429 Too Many Requests` when exceeded
- **FR35**: The system is deployable as a Docker container alongside its dependencies (Redis, MinIO, NATS, ClamAV) via a provided Docker Compose configuration

### NonFunctional Requirements

**Performance (NFR-P1 to NFR-P5):**

- **NFR-P1**: `POST /v1/uploads` (session initiation) responds within **200ms** at p99 under normal load
- **NFR-P2**: `HEAD /v1/uploads/{id}` (offset query) responds within **50ms** at p99 — this is in the hot retry path
- **NFR-P3**: Server-side per-chunk processing overhead (SHA-256 verification + Redis state write) ≤ **100ms** per 5 MB chunk at p99
- **NFR-P4**: Upload throughput is bounded by client network speed, not service processing capacity — the service must not be the bottleneck
- **NFR-P5**: 10 concurrent 500 MB uploads and 50 concurrent 100 MB uploads complete without throughput degradation > 10% compared to single-upload baseline

**Security (NFR-S1 to NFR-S6):**

- **NFR-S1**: All data in transit is encrypted via **TLS 1.2 minimum** on all API endpoints and service-to-service connections (MinIO, Redis, NATS)
- **NFR-S2**: All files at rest on MinIO are encrypted using **AES-256 server-side encryption**
- **NFR-S3**: Upload session IDs are **cryptographically random UUIDs** (v4) — not sequential, not guessable
- **NFR-S4**: JWT validation is enforced on **100% of requests** — no endpoint is accessible without a valid token
- **NFR-S5**: No cross-tenant data is accessible at any layer — storage path namespace, Redis key prefix, and deduplication scope are all isolated per workspace
- **NFR-S6**: No malicious payload is persisted to the bronze layer — ClamAV scanning must complete before `FILE_LOAD_COMPLETED` event is published

**Scalability (NFR-SC1 to NFR-SC4):**

- **NFR-SC1**: The service is **stateless** — all session state is in Redis; adding instances increases concurrent upload capacity linearly without coordination overhead
- **NFR-SC2**: Maximum concurrent sessions scales as `MAX_CONCURRENT_UPLOADS × num_instances`, configurable without code changes
- **NFR-SC3**: Redis and MinIO scale independently of the upload service — no shared in-process state between instances
- **NFR-SC4**: The service handles a **10× increase in concurrent sessions** (via additional instances) with no architectural changes

**Reliability (NFR-R1 to NFR-R5):**

- **NFR-R1**: Upload first-attempt success rate ≥ **90%** under normal operating conditions
- **NFR-R2**: Silent failure rate must be **1%** — any silent failure rate ≥ 1% constitutes a P0 incident
- **NFR-R3**: Upload session state survives **service restarts** — Redis AOF persistence or replication is required; in-flight sessions resume from last verified offset on reconnect
- **NFR-R4**: `FILE_LOAD_COMPLETED` event publication achieves **at-least-once delivery** — failures trigger retry with exponential backoff before the upload is marked `failed`
- **NFR-R5**: ClamAV service unavailability must not silently bypass scanning — the service either waits (with configurable timeout) or returns a clear error; it never skips scanning and proceeds

**Integration (NFR-I1 to NFR-I6):**

- **NFR-I1**: **NATS JetStream**: `FILE_LOAD_COMPLETED` events published to a durable subject; consumers can replay events on reconnect; subject name and schema are stable API contracts
- **NFR-I2**: **MinIO/S3**: All storage operations use the S3-compatible API — no MinIO-specific SDK calls that would prevent migration to AWS S3 or compatible alternatives
- **NFR-I3**: **Redis**: All session state operations use atomic commands (`HSET`, `HINCRBY`, `EXPIRE`) — no Lua scripts or cluster-incompatible patterns
- **NFR-I4**: **ClamAV**: Integration via `clamd` TCP socket — clamd address and port configurable via environment variables
- **NFR-I5**: **Prometheus**: `/metrics` endpoint exposed on a configurable port (default: `9090`); compatible with standard Prometheus scrape config; scrape interval ≤ 15 seconds
- **NFR-I6**: **JWT**: Service accepts RS256 or HS256 signed tokens; public key / secret configurable via environment variables; no hard-coded auth logic

### Additional Requirements

**Starter Template & Project Initialization:**

- Custom FastAPI Clean Architecture setup with Python 3.13 and uv package manager
- Project structure: Domain → Application → Infrastructure → Presentation layers
- Directory structure with clean separation: domain/, application/, infrastructure/, presentation/
- Development tools: pytest + pytest-asyncio, ruff (linting + formatting), mypy (type checking), MkDocs
- Docker Compose configuration with all dependencies: Redis (with AOF persistence), MinIO, NATS JetStream, ClamAV

**Data Architecture Decisions:**

- **Redis Session State Schema**: Single Hash per session with key pattern `session:workspace_{workspace_id}:upload_{upload_id}`
- Hash fields: filename, size, mime_type, sha256_checksum, offset, status, created_at, expires_at, chunk_manifest
- **Chunk Manifest Structure**: Array of chunk indices stored as JSON string
- **Deduplication Storage**: Redis Hash per workspace with key pattern `dedup:workspace_{workspace_id}`

**Authentication & Security Architecture:**

- **JWT Strategy**: RS256 asymmetric public key validation
- **Validation Frequency**: On every PATCH request (per-chunk validation)
- Stub auth service generates RSA key pair for development
- Performance target: JWT validation <30ms to leave 70ms for SHA-256 + Redis

**API & Communication Patterns:**

- **Chunk Upload Protocol**: Strict tus protocol compliance
- Required headers: `Upload-Offset`, `Upload-Length`, `Upload-Checksum: sha256 <hex>`
- Content-type: `application/offset+octet-stream`
- **Error Response Structure**: Enhanced with actionable `details` field including expected/received values, chunk index, documentation URL
- **Rate Limiting**: Redis atomic counter with workspace scoping

**Event Architecture:**

- **Event Naming Convention**: `domain.entity.action` pattern (e.g., `upload.file.load_completed`)
- **Event Payload Schema**: Versioned with `eventVersion`, `eventType`, `payload` fields
- **Dead Letter Queue**: Redis-based DLQ for failed NATS publications with retry logic
- **Webhook Alternative**: Configurable webhook callbacks with HMAC-SHA256 signatures (EVENT_PUBLISH_MODE: "nats" | "webhook")

**Implementation Patterns (All AI Agents Must Follow):**

1. Strict PEP 8 Python naming conventions enforced by ruff/mypy
2. snake_case Redis keys with colon separators
3. camelCase external API JSON via Pydantic alias_generator
4. domain.entity.action event naming
5. Error suffix on exceptions (e.g., `ChecksumMismatchError`)
6. tests/ directory structure mirroring src/
7. .env configuration files with environment prefixes
8. ISO 8601 UTC (Z suffix) for all timestamps
9. Infrastructure exception conversion to domain exceptions at boundaries
10. Log completion/error only on hot path (chunk processing)

**Storage & File Assembly:**

- MinIO/S3 multipart upload for large file assembly
- Immutable bronze-layer storage with workspace-scoped paths
- Server-side AES-256 encryption at rest
- Lifecycle policies for cleanup of incomplete multipart uploads

**Observability Infrastructure:**

- Prometheus metrics with workspace labels
- Structured logging with structlog (JSON format with tenant_id, session_id, request_id context)
- OpenAPI 3.0 automatic spec generation at `/docs` and `/openapi.json`
- Health check endpoint for service status monitoring

### UX Design Requirements

(No UX Design document provided)

### FR Coverage Map

**Epic 1 (Project Foundation):** FR35 (partial - Docker deployment setup)
**Epic 2 (Authentication & Isolation):** FR27, FR28, FR29, FR22, FR23, FR24, FR25, FR26 (partial)
**Epic 3 (Chunked Upload):** FR1, FR2, FR3, FR4, FR5, FR6, FR14, FR15, FR34 (rate limiting)
**Epic 4 (Resumability):** FR10, FR11, FR12, FR13
**Epic 5 (File Assembly & Pipeline):** FR16, FR17, FR18, FR19, FR20, FR21, FR26 (storage isolation)
**Epic 6 (Observability):** FR30, FR31, FR32, FR33
**Epic 7 (Metadata Management):** FR7, FR8, FR9

All 35 FRs covered across 7 epics (restructured from 9).

## Epic List

### Epic 1: Project Foundation & Infrastructure Setup

Development environment is ready, and all external services (Redis, MinIO, NATS, ClamAV) are operational and accessible via Docker Compose.
**FRs covered:** FR35 (partial - Docker setup)

### Epic 2: Authentication, Authorization & Workspace Isolation

Workspace owners and collaborators can authenticate via JWT tokens, and the system enforces role-based access control with complete workspace isolation built-in from the start.
**FRs covered:** FR27, FR28, FR29, FR22, FR23, FR24, FR25, FR26 (partial - RBAC & session isolation)

### Epic 3: Chunked Upload Session Lifecycle

Workspace owners can initiate upload sessions, upload files in verified chunks with SHA-256 checksums, query upload progress, and abort sessions - with rate limiting and workspace isolation enforced.
**FRs covered:** FR1, FR2, FR3, FR4, FR5, FR6, FR14, FR15, FR34
**NFRs addressed:** NFR-P1, NFR-P2, NFR-P3, NFR-S3, NFR-S4

### Epic 4: Upload Resumability & Session Persistence

Users can resume interrupted uploads from the exact byte offset within 24 hours, and the system handles multi-file batch uploads independently.
**FRs covered:** FR10, FR11, FR12, FR13
**NFRs addressed:** NFR-R3, NFR-SC1

### Epic 5: File Assembly, Integrity & Pipeline Integration

When all chunks are verified, the system assembles the complete file, validates integrity, scans for malware, stores immutably on S3 with workspace isolation, and publishes FILE_LOAD_COMPLETED events (NATS or webhook) to downstream RAG pipeline.
**FRs covered:** FR16, FR17, FR18, FR19, FR20, FR21, FR26 (storage isolation)
**NFRs addressed:** NFR-S6, NFR-R5, NFR-R4, NFR-I1, NFR-S2, NFR-S5 (storage isolation)

### Epic 6: Observability, Metrics & Operations

Platform operators can monitor service health, diagnose upload failures, and access detailed metrics without SSH access or log scraping.
**FRs covered:** FR30, FR31, FR32, FR33
**NFRs addressed:** NFR-I5

### Epic 7: Upload Metadata & Session Management

Workspace owners can list all their upload sessions, retrieve detailed session metadata, and collaborators can access metadata for shared files.
**FRs covered:** FR7, FR8, FR9

## Epic 1: Project Foundation & Infrastructure Setup

Development environment is ready, and all external services (Redis, MinIO, NATS, ClamAV) are operational and accessible via Docker Compose.

### Story 1.1: Initialize Python Project with uv and Clean Architecture Structure

As a **developer**,
I want **the project initialized with uv, Python 3.13, and a complete Clean Architecture directory structure**,
So that **I have a consistent foundation following architectural patterns for all future development**.

**Acceptance Criteria:**

**Given** a new project directory
**When** the initialization is complete
**Then** the project has a pyproject.toml configured with uv
**And** Python 3.13 is pinned in .python-version
**And** directory structure includes src/domain/, src/application/, src/infrastructure/, src/presentation/
**And** all subdirectories for entities, value_objects, protocols, services, use_cases, dto are created
**And** **init**.py files exist in all package directories

### Story 1.2: Configure Development Tools and Code Quality Standards

As a **developer**,
I want **development tools (pytest, ruff, mypy, MkDocs) configured with project standards**,
So that **code quality is enforced automatically and testing infrastructure is ready**.

**Acceptance Criteria:**

**Given** the project structure exists
**When** development tools are configured
**Then** pyproject.toml includes pytest, pytest-asyncio, ruff, mypy, mkdocs dependencies
**And** ruff.toml exists with PEP 8 enforcement rules
**And** mypy.ini exists with strict type checking configuration
**And** tests/ directory structure mirrors src/ structure
**And** running `uv run ruff check src/` executes without errors on empty structure
**And** running `uv run mypy src/` executes without errors on empty structure

### Story 1.3: Set Up Docker Compose with All External Services

As a **developer**,
I want **Docker Compose configured with Redis, MinIO, NATS JetStream, and ClamAV**,
So that **all external dependencies are available locally for development and testing**.

**Acceptance Criteria:**

**Given** the project has docker/ directory
**When** Docker Compose is started
**Then** docker-compose.yml defines services: redis, minio, nats, clamav
**And** Redis is configured with AOF persistence enabled
**And** MinIO is accessible on port 9000 with access/secret keys via environment variables
**And** NATS JetStream is enabled and accessible on port 4222
**And** ClamAV clamd is accessible on TCP port 3310
**And** all services start successfully with `docker compose up -d`
**And** health checks pass for all services within 30 seconds

### Story 1.4: Create Base Configuration Management with Pydantic Settings

As a **developer**,
I want **centralized configuration management using Pydantic Settings**,
So that **all environment variables are validated, typed, and documented in one place**.

**Acceptance Criteria:**

**Given** infrastructure layer exists
**When** configuration is implemented
**Then** src/infrastructure/config/settings.py exists with AppSettings class
**And** settings inherit from pydantic_settings.BaseSettings
**And** configuration includes: REDIS_URL, MINIO_ENDPOINT, NATS_URL, CLAMAV_HOST, CLAMAV_PORT, JWT_PUBLIC_KEY, MAX_CONCURRENT_UPLOADS
**And** all settings have type annotations and default values where appropriate
**And** settings load from .env file and environment variables
**And** missing required settings raise clear validation errors on startup
**And** settings are instantiated once as singleton pattern

## Epic 2: Authentication, Authorization & Workspace Isolation

Workspace owners and collaborators can authenticate via JWT tokens, and the system enforces role-based access control with complete workspace isolation built-in from the start.

### Story 2.1: Create Domain Entities for Workspace and User Roles

As a **developer**,
I want **domain entities that represent workspace ownership and collaboration roles**,
So that **authorization logic is clear and type-safe throughout the application**.

**Acceptance Criteria:**

**Given** domain layer exists
**When** workspace entities are created
**Then** src/domain/entities/workspace.py exists with Workspace entity
**And** src/domain/value_objects/workspace_role.py defines WorkspaceRole enum (OWNER, COLLABORATOR)
**And** Workspace entity includes: workspace_id, owner_user_id, created_at
**And** src/domain/value_objects/jwt_claims.py defines JWTClaims value object
**And** JWTClaims includes: user_id, workspace_id, workspace_role, shared_file_ids (optional list)
**And** all entities follow immutability pattern where applicable

### Story 2.2: Implement JWT Validation Middleware

As a **developer**,
I want **JWT validation enforced on every API request**,
So that **no endpoint is accessible without valid authentication**.

**Acceptance Criteria:**

**Given** infrastructure layer exists
**When** JWT middleware is implemented
**Then** src/infrastructure/auth/jwt_validator.py implements JWT validation
**And** validator supports RS256 asymmetric key validation
**And** validator loads public key from config (environment variable)
**And** validator extracts JWTClaims from token payload
**And** invalid/expired tokens raise AuthenticationError (401)
**And** middleware is registered globally in FastAPI app
**And** all /v1/uploads/\* endpoints require valid JWT
**And** JWT validation completes in <30ms (NFR requirement)
**And** satisfies FR27 (100% JWT validation)

### Story 2.3: Implement Workspace-Scoped Redis Key Prefixing (Isolation)

As a **developer**,
I want **all Redis keys scoped to workspace_id from the start**,
So that **session state, deduplication, and rate limits are completely isolated by design**.

**Acceptance Criteria:**

**Given** workspace isolation requirements
**When** Redis key helper is implemented
**Then** src/infrastructure/redis/key*builder.py exists with workspace-scoped key functions
**And** session keys: `session:workspace*{workspace*id}:upload*{upload*id}`**And** dedup keys:`dedup:workspace*{workspace*id}`**And** rate limit keys:`ratelimit:workspace*{workspace_id}:active_uploads`
**And** all key builder functions validate workspace_id is present
**And** key patterns follow snake_case with colon separators (implementation pattern #2)
**And** no Redis key can be created without workspace scope
**And** satisfies FR26 (isolation at session state layer) and NFR-S5

### Story 2.4: Implement RBAC Middleware for Workspace Roles

As a **developer**,
I want **role-based access control enforced at the middleware level**,
So that **collaborators cannot perform write operations**.

**Acceptance Criteria:**

**Given** JWT middleware extracts workspace_role
**When** RBAC middleware is implemented
**Then** src/infrastructure/auth/rbac_middleware.py implements role checking
**And** middleware decorator @require_role(WorkspaceRole.OWNER) exists
**And** OWNER role allows: POST, PATCH, DELETE operations
**And** COLLABORATOR role allows: GET, HEAD operations only
**And** write endpoints (POST, PATCH, DELETE) return 403 Forbidden for COLLABORATOR
**And** error message: "Write operations require workspace owner role"
**And** RBAC checks execute after JWT validation
**And** satisfies FR28 (role-based access control)

### Story 2.5: Implement Workspace Access Control Rules

As a **workspace owner**,
I want **full control over my workspace with strict collaborator restrictions**,
So that **my data remains secure and collaborators have read-only access only**.

**Acceptance Criteria:**

**Given** workspace with owner and collaborators
**When** access control is enforced
**Then** workspace owner (workspace_role == OWNER in JWT) has full CRUD rights
**And** owner can initiate uploads (POST), upload chunks (PATCH), abort (DELETE), list (GET), retrieve (GET)
**And** collaborators (workspace_role == COLLABORATOR) have read-only access
**And** collaborators can only access files in shared_file_ids JWT claim
**And** collaborators attempting POST/PATCH/DELETE receive 403 Forbidden
**And** collaborators accessing non-shared files receive 403 Forbidden
**And** workspace_id in JWT must match resource workspace_id (403 otherwise)
**And** access control validated on every endpoint via RBAC middleware
**And** satisfies FR22-FR26 (workspace isolation and role enforcement)

### Story 2.6: Create Stub Auth Service for Development

As a **developer**,
I want **a stub authentication service that generates valid JWT tokens for local testing**,
So that **I can test all auth flows without external dependencies**.

**Acceptance Criteria:**

**Given** Docker Compose environment
**When** stub auth service is created
**Then** docker/auth-stub/ contains a simple FastAPI service
**And** service generates RSA key pair on startup
**And** service exposes POST /generate-token endpoint
**And** endpoint accepts: user_id, workspace_id, workspace_role, shared_file_ids (optional)
**And** endpoint returns valid RS256-signed JWT
**And** JWT includes exp claim (1 hour expiry)
**And** public key is accessible at GET /.well-known/jwks.json
**And** upload service configured to use stub's public key in development
**And** stub service added to docker-compose.yml

## Epic 3: Chunked Upload Session Lifecycle

Workspace owners can initiate upload sessions, upload files in verified chunks with SHA-256 checksums, query upload progress, and abort sessions - with rate limiting and workspace isolation enforced.

### Story 3.1: Create Upload Session Domain Entities and Value Objects

As a **developer**,
I want **domain entities for upload sessions, chunks, and related value objects**,
So that **business logic is independent of infrastructure**.

**Acceptance Criteria:**

**Given** the domain layer exists
**When** upload session entities are created
**Then** src/domain/entities/upload_session.py exists with UploadSession entity
**And** UploadSession includes: session_id, workspace_id, filename, size, mime_type, sha256_checksum, offset, status, created_at, expires_at, chunk_manifest
**And** src/domain/value_objects/session_status.py exists with SessionStatus enum (PENDING, IN_PROGRESS, COMPLETE, FAILED, ABORTED)
**And** src/domain/value_objects/sha256_hash.py exists with SHA256Hash value object for checksum validation
**And** src/domain/exceptions.py includes ChecksumMismatchError, SessionNotFoundError, FileSizeLimitExceededError, UnsupportedMediaTypeError
**And** all entities follow Clean Architecture principles with no infrastructure dependencies

### Story 3.2: Implement Redis Session Store Infrastructure

As a **developer**,
I want **Redis-backed session storage implementing the ISessionStore protocol**,
So that **upload sessions persist durably with 24-hour TTL**.

**Acceptance Criteria:**

**Given** infrastructure layer exists
**When** Redis session store is implemented
**Then** src/domain/protocols/session*store.py defines ISessionStore protocol with methods: create_session, get_session, update_offset, delete_session
**And** src/infrastructure/redis/session_store.py implements RedisSessionStore
**And** session keys follow pattern: session:workspace*{workspace*id}:upload*{upload_id}
**And** sessions stored as Redis Hash with all UploadSession fields
**And** chunk_manifest stored as JSON string within hash
**And** EXPIRE set to 86400 seconds (24 hours) on session creation
**And** all operations use atomic Redis commands (HSET, HGET, HGETALL, DEL)
**And** RedisSessionStore handles connection errors and converts to domain exceptions

### Story 3.3: Implement Per-Workspace Rate Limiting

As a **platform operator**,
I want **concurrent upload limits enforced per workspace from the start**,
So that **one workspace cannot monopolize service resources**.

**Acceptance Criteria:**

**Given** MAX*CONCURRENT_UPLOADS configured (e.g., 10)
**When** rate limiting is implemented
**Then** src/application/services/rate_limiter.py implements workspace-scoped rate limiting
**And** rate limit uses Redis counter: ratelimit:workspace*{workspace_id}:active_uploads
**And** counter incremented atomically via HINCRBY on session creation
**And** if counter >= MAX_CONCURRENT_UPLOADS, raises RateLimitExceededError
**And** counter decremented when session completes, fails, or is aborted
**And** expired sessions automatically decrement counter via TTL callback
**And** rate limiting is workspace-scoped (workspace A hitting limit doesn't affect workspace B)
**And** satisfies FR34 (configurable concurrent session limits)

### Story 3.4: Create Initiate Upload Session Use Case (POST /v1/uploads)

As a **workspace owner**,
I want **to initiate a new upload session for a PDF file**,
So that **I receive a session ID and can begin uploading chunks**.

**Acceptance Criteria:**

**Given** authentication and rate limiting are configured
**When** initiate upload use case is implemented
**Then** src/application/use_cases/initiate_upload.py exists
**And** use case checks workspace rate limit first (429 if exceeded)
**And** use case validates file size ≤ 1 GB (FR14)
**And** use case validates mime_type == "application/pdf" (FR15)
**And** use case generates UUID v4 session_id (NFR-S3)
**And** use case creates session in Redis with 24-hour TTL
**And** use case increments rate limit counter
**And** use case returns: session_id, offset (0), expires_at timestamp
**And** file size > 1 GB returns 413 Payload Too Large
**And** non-PDF mime type returns 415 Unsupported Media Type
**And** rate limit exceeded returns 429 Too Many Requests with Retry-After header
**And** POST endpoint responds in <200ms at p99 (NFR-P1)

### Story 3.5: Implement POST /v1/uploads API Endpoint

As a **workspace owner**,
I want **a REST API endpoint to initiate upload sessions**,
So that **I can start uploading files via HTTP**.

**Acceptance Criteria:**

**Given** use case exists
**When** API endpoint is implemented
**Then** src/presentation/api/v1/routers/uploads.py contains POST /v1/uploads endpoint
**And** src/presentation/api/v1/schemas/upload_schemas.py defines InitiateUploadRequest with fields: filename, size, mime_type, sha256_checksum
**And** response schema includes: uploadId (camelCase), offset, expiresAt (ISO 8601)
**And** endpoint requires valid JWT (401 if missing/invalid)
**And** endpoint requires workspace_role == OWNER (403 for collaborators)
**And** endpoint injects workspace_id from JWT claims
**And** 429 response includes current active upload count in details
**And** error responses follow standard format with error code, message, details
**And** endpoint is documented in OpenAPI spec

### Story 3.6: Implement Chunk SHA-256 Verification Service

As a **developer**,
I want **a domain service that verifies chunk SHA-256 checksums**,
So that **corrupted chunks are rejected immediately**.

**Acceptance Criteria:**

**Given** domain services layer exists
**When** verification service is implemented
**Then** src/domain/services/chunk_verifier.py exists
**And** service provides verify_chunk(data: bytes, expected_checksum: str) method
**And** service computes SHA-256 hash of chunk data
**And** service compares computed hash with expected checksum
**And** mismatches raise ChecksumMismatchError with both hashes included
**And** verification completes in <50ms for 5MB chunk (allows 100ms total with Redis write)

### Story 3.7: Create Process Chunk Use Case (PATCH /v1/uploads/{id})

As a **workspace owner**,
I want **to upload file chunks with SHA-256 verification**,
So that **data integrity is guaranteed during upload**.

**Acceptance Criteria:**

**Given** session store and chunk verifier exist
**When** process chunk use case is implemented
**Then** src/application/use_cases/process_chunk.py exists
**And** use case retrieves session from Redis
**And** use case validates Upload-Offset header matches current session offset (409 Conflict if mismatch)
**And** use case verifies chunk SHA-256 checksum (460 Checksum Mismatch if invalid)
**And** use case updates session offset atomically in Redis
**And** use case appends chunk index to chunk_manifest
**And** use case updates session status to IN_PROGRESS
**And** expired sessions return 404 Session Not Found
**And** total per-chunk processing ≤ 100ms (NFR-P3)

### Story 3.8: Implement PATCH /v1/uploads/{id} API Endpoint

As a **workspace owner**,
I want **a REST API endpoint to upload chunks with strict tus protocol compliance**,
So that **I can upload large files reliably**.

**Acceptance Criteria:**

**Given** process chunk use case exists
**When** API endpoint is implemented
**Then** PATCH /v1/uploads/{id} endpoint exists in uploads router
**And** endpoint requires headers: Upload-Offset, Upload-Length, Upload-Checksum (sha256 base64)
**And** endpoint requires Content-Type: application/offset+octet-stream
**And** endpoint streams chunk data asynchronously (no blocking I/O)
**And** success returns 204 No Content with Upload-Offset header showing new offset
**And** offset mismatch returns 409 Conflict with expected/received offsets in details
**And** checksum mismatch returns 460 Checksum Mismatch with both checksums in details
**And** endpoint enforces workspace ownership (JWT validation + RBAC)

### Story 3.9: Implement Query Upload Offset (HEAD /v1/uploads/{id})

As a **workspace owner**,
I want **to query the current verified byte offset of my upload**,
So that **I can resume uploads from the correct position**.

**Acceptance Criteria:**

**Given** session store exists
**When** offset query is implemented
**Then** HEAD /v1/uploads/{id} endpoint exists in uploads router
**And** endpoint retrieves session from Redis
**And** response returns 200 OK with Upload-Offset header
**And** response includes Upload-Length header (total file size)
**And** expired sessions return 404 Session Not Found
**And** endpoint allows both OWNER and COLLABORATOR (read operation)
**And** endpoint responds in <50ms at p99 (NFR-P2 - hot retry path)

### Story 3.10: Implement Abort Upload Session (DELETE /v1/uploads/{id})

As a **workspace owner**,
I want **to abort an active upload session**,
So that **I can cancel unwanted uploads and clean up resources**.

**Acceptance Criteria:**

**Given** session store exists
**When** abort session use case and endpoint are implemented
**Then** src/application/use_cases/abort_upload.py exists
**And** DELETE /v1/uploads/{id} endpoint exists in uploads router
**And** use case deletes session from Redis (removes all state)
**And** use case updates session status to ABORTED before deletion
**And** use case decrements workspace rate limit counter
**And** success returns 204 No Content
**And** non-existent sessions return 404 Session Not Found
**And** endpoint requires workspace_role == OWNER (write operation)
**And** all associated temporary data is cleaned up

## Epic 4: Upload Resumability & Session Persistence

Users can resume interrupted uploads from the exact byte offset within 24 hours, and the system handles multi-file batch uploads independently.

### Story 4.1: Implement Session TTL and Expiry Handling

As a **workspace owner**,
I want **upload sessions to expire gracefully after 24 hours**,
So that **I receive clear feedback when attempting to resume expired sessions**.

**Acceptance Criteria:**

**Given** a session was created 24+ hours ago
**When** I attempt to resume the upload (HEAD or PATCH request)
**Then** the system returns 404 Session Not Found
**And** error response includes "session_expired" error code
**And** error details include original expiry timestamp
**And** error message suggests starting a new upload session
**And** Redis automatically removes expired sessions via TTL
**And** no manual cleanup is required for expired sessions

### Story 4.2: Implement Resume-from-Offset Logic

As a **workspace owner**,
I want **to resume interrupted uploads from the exact byte offset**,
So that **I don't need to re-upload already verified chunks**.

**Acceptance Criteria:**

**Given** an upload was interrupted at chunk 42 (offset 220200960 bytes)
**When** I query HEAD /v1/uploads/{id}
**Then** response returns Upload-Offset: 220200960
**And** response includes Upload-Length with total file size
**And** I can resume with PATCH starting at byte 220200960
**When** I send PATCH with matching offset
**Then** upload continues seamlessly from that point
**And** chunk manifest shows continuity (chunks 0-41 already verified, now adding 42+)
**And** no previously verified chunks are re-processed
**And** offset mismatch (e.g., client sends offset 0) returns 409 Conflict with expected offset

### Story 4.3: Add Multi-File Batch Upload Support

As a **workspace owner**,
I want **to upload multiple files concurrently as independent sessions**,
So that **batch uploads complete efficiently without blocking each other**.

**Acceptance Criteria:**

**Given** I initiate 5 upload sessions simultaneously
**When** each session is created via POST /v1/uploads
**Then** each receives a unique session_id
**And** sessions are independent with separate Redis keys
**And** chunk processing for file 1 does not block file 2
**And** each session tracks its own offset and chunk_manifest
**And** completing one session does not affect others
**And** sessions can be queried independently via HEAD
**And** all sessions respect the per-workspace concurrent upload limit
**And** rate limiting applies across all sessions for the workspace

## Epic 5: File Assembly, Integrity & Pipeline Integration

When all chunks are verified, the system assembles the complete file, validates integrity, scans for malware, stores immutably on S3 with workspace isolation, and publishes FILE_LOAD_COMPLETED events (NATS or webhook) to downstream RAG pipeline - ensuring every file is safe, complete, and ready for processing.

### Story 5.1: Implement Workspace-Scoped File Deduplication

As a **workspace owner**,
I want **the system to detect when I'm uploading a duplicate file**,
So that **I don't waste time and storage on files I already have**.

**Acceptance Criteria:**

**Given** a file with SHA-256 hash "abc123..." already exists in my workspace
**When** I initiate a new upload with the same SHA-256 checksum
**Then** the system returns 409 Duplicate File
**And** error response includes existing file*id and s3_path
**And** error response includes original upload timestamp
**And** deduplication check occurs after successful file assembly (not at session initiation)
**And** deduplication is scoped to workspace only (same file in different workspace is allowed)
**And** Redis hash key follows pattern: dedup:workspace*{workspace_id}
**And** successful uploads register their SHA-256 in the dedup hash
**And** dedup entry includes: file_id, s3_path, size, uploaded_at (JSON)

### Story 5.2: Implement MinIO/S3 File Assembly with Storage Isolation

As a **developer**,
I want **verified chunks assembled into a complete file and stored immutably on S3 with workspace path isolation**,
So that **files are available for downstream RAG processing and no workspace can access another's files**.

**Acceptance Criteria:**

**Given** all chunks are verified and in Redis chunk*manifest
**When** file assembly is triggered
**Then** src/infrastructure/s3/storage_client.py implements IStorageClient protocol
**And** storage client uses aioboto3 for async S3 operations
**And** file assembly uses S3 multipart upload API
**And** S3 key follows pattern: workspace*{workspace_id}/{file_id}.pdf (WORKSPACE ISOLATION)
**And** storage client validates workspace_id matches JWT claim before any operation
**And** cross-workspace access attempts are rejected with 403 Forbidden
**And** server-side encryption (AES-256) is enabled (NFR-S2)
**And** assembled file SHA-256 is validated against session checksum
**And** checksum mismatch during assembly raises IntegrityError
**And** successful storage returns s3_path and final file size
**And** storage operations use S3-compatible API only (no MinIO-specific calls, NFR-I2)
**And** incomplete multipart uploads have lifecycle policy cleanup
**And** storage isolation satisfies NFR-S5 (no cross-tenant data access)

### Story 5.3: Integrate ClamAV Virus Scanner

As a **platform operator**,
I want **all uploaded files scanned for malicious payloads**,
So that **no viruses reach the bronze-layer storage**.

**Acceptance Criteria:**

**Given** file assembly is complete
**When** virus scanning is triggered
**Then** src/infrastructure/clamav/scanner.py implements IClamAVScanner protocol
**And** scanner connects to clamd via TCP socket (host/port from config)
**And** scanner sends assembled file for scanning
**And** clean files return scan_result: "OK"
**And** infected files raise MaliciousFileDetectedError
**And** ClamAV unavailability does NOT silently proceed (NFR-R5)
**And** scanner timeout (configurable, default 30s) returns clear error
**And** scan happens BEFORE FILE_LOAD_COMPLETED event publication
**And** infected files are not stored on S3
**And** session status is updated to FAILED for infected files

### Story 5.4: Create Event Domain Entities and Schema

As a **developer**,
I want **versioned event schemas for FILE_LOAD_COMPLETED events**,
So that **downstream services have a stable contract for event consumption**.

**Acceptance Criteria:**

**Given** domain layer exists
**When** event entities are created
**Then** src/domain/entities/events.py exists with FileLoadCompletedEvent entity
**And** event includes fields: event_version ("1.0"), event_type ("FILE_LOAD_COMPLETED"), timestamp (ISO 8601)
**And** event payload includes: file_id, workspace_id, s3_path, sha256_checksum, size_bytes, uploaded_at
**And** event follows naming convention: upload.file.load_completed (subject name)
**And** event schema is documented and considered a stable API contract
**And** event serializes to JSON for NATS/webhook publishing
**And** src/domain/protocols/event_publisher.py defines IEventPublisher protocol

### Story 5.5: Implement NATS JetStream Publisher

As a **developer**,
I want **async event publishing to NATS JetStream with durable subjects**,
So that **events are reliably delivered to downstream consumers**.

**Acceptance Criteria:**

**Given** infrastructure layer exists
**When** NATS publisher is implemented
**Then** src/infrastructure/nats/event_publisher.py implements IEventPublisher protocol
**And** publisher connects to NATS JetStream (server URL from config)
**And** publisher creates/uses durable stream for upload events
**And** subject name: upload.file.load_completed
**And** publisher uses async NATS client (asyncio-nats library)
**And** publish method is async and returns success/failure
**And** JetStream ack confirms message persistence
**And** NATS connection errors raise InfrastructureError
**And** publisher supports graceful shutdown and connection cleanup

### Story 5.6: Implement Event Retry Logic with Dead Letter Queue

As a **platform operator**,
I want **failed event publications retried with exponential backoff**,
So that **temporary NATS/webhook outages don't cause silent failures**.

**Acceptance Criteria:**

**Given** NATS/webhook is temporarily unavailable
**When** event publication fails
**Then** system retries with exponential backoff (1s, 2s, 4s, 8s, 16s)
**And** max retry attempts: 5
**And** after max retries, event is written to Redis dead letter queue (DLQ)
**And** DLQ key pattern: dlq:file_load_completed:{file_id}
**And** DLQ entry includes: event payload, original timestamp, retry count, last_error
**And** DLQ entries have 7-day TTL for manual intervention
**And** failed publications do NOT mark upload as complete (status remains IN_PROGRESS)
**And** retry logic implements NFR-R4 (at-least-once delivery)
**And** structured logs record all retry attempts with file_id and error details

### Story 5.7: Implement Webhook Callback Alternative

As a **platform integrator**,
I want **optional webhook callbacks as an alternative to NATS events**,
So that **I can receive upload completion notifications without NATS infrastructure**.

**Acceptance Criteria:**

**Given** webhook mode is configured
**When** upload completes successfully
**Then** system sends POST request to configured WEBHOOK_URL
**And** webhook payload includes: eventType ("FILE_LOAD_COMPLETED"), eventVersion ("1.0"), file_id, workspace_id, s3_path, sha256_checksum, size_bytes, uploaded_at
**And** webhook request includes X-Webhook-Signature header with HMAC-SHA256 signature
**And** signature computed from: HMAC(WEBHOOK_SECRET, request_body)
**And** config supports: EVENT_PUBLISH_MODE ("nats" | "webhook"), WEBHOOK_URL, WEBHOOK_SECRET
**And** webhook failures use same retry + DLQ strategy as NATS
**And** webhook timeout: 10 seconds (configurable)
**And** webhook implementation in src/infrastructure/webhooks/webhook_publisher.py
**And** webhook publisher implements IEventPublisher protocol
**And** satisfies PRD MVP requirement for webhook alternative

### Story 5.8: Orchestrate Complete Upload Use Case

As a **workspace owner**,
I want **my upload to complete automatically when all chunks are received**,
So that **the file is assembled, scanned, stored, and ready for processing**.

**Acceptance Criteria:**

**Given** all chunks have been uploaded and verified
**When** the final chunk is processed
**Then** src/application/use_cases/complete_upload.py exists
**And** use case validates chunk_manifest completeness (all indices 0 to N-1 present)
**And** use case triggers file assembly on S3 with workspace isolation (Story 5.2)
**And** use case validates full-file SHA-256 matches session checksum
**And** use case triggers ClamAV virus scan (Story 5.3)
**And** use case checks for duplicates (Story 5.1) - 409 if duplicate found
**And** use case triggers event publication (NATS or webhook per Story 5.5/5.7)
**And** use case updates session status to COMPLETE only after successful event publish
**And** use case decrements workspace rate limit counter
**And** use case returns file_id, s3_path, final size
**And** any failure during completion updates status to FAILED with error details
**And** completion is atomic (all-or-nothing per NFR-R2)
**And** deduplication registration happens AFTER successful completion

## Epic 6: Observability, Metrics & Operations

Platform operators can monitor service health, diagnose upload failures, and access detailed metrics without SSH access or log scraping.

### Story 6.1: Implement Prometheus Metrics Endpoint

As a **platform operator**,
I want **Prometheus metrics exposed for all upload operations**,
So that **I can monitor service health and performance in real-time**.

**Acceptance Criteria:**

**Given** observability infrastructure exists
**When** metrics endpoint is implemented
**Then** /metrics endpoint is exposed on configurable port (default 9090)
**And** src/observability/metrics.py implements Prometheus metrics
**And** metric: upload_chunks_total (counter, labels: workspace_id, status)
**And** metric: upload_bytes_total (counter, labels: workspace_id)
**And** metric: chunk_verification_failures_total (counter, labels: workspace_id, failure_reason)
**And** metric: upload_sessions_active (gauge, labels: workspace_id)
**And** metric: upload_completion_time_seconds (histogram, labels: workspace_id)
**And** all metrics include workspace_id label (per FR30)
**And** /metrics endpoint is compatible with Prometheus scrape config (NFR-I5)
**And** scrape interval target: ≤ 15 seconds
**And** metrics do not include PII or sensitive file content

### Story 6.2: Implement Structured Logging with Context

As a **platform operator**,
I want **structured JSON logs with contextual information**,
So that **I can diagnose failures without SSH access to containers**.

**Acceptance Criteria:**

**Given** logging infrastructure exists
**When** structured logging is implemented
**Then** src/observability/logging.py configures structlog
**And** all logs output as JSON format
**And** log context includes: tenant_id (workspace_id), session_id, request_id, chunk_index (where applicable)
**And** upload lifecycle events logged: session_created, chunk_received, chunk_verified, chunk_failed, session_completed, session_failed, session_aborted
**And** error logs include failure_reason and stack traces
**And** log levels: INFO for success paths, WARN for retries, ERROR for failures
**And** hot path (chunk processing) logs completion or error only (implementation pattern #10)
**And** request_id propagated through entire request lifecycle
**And** logs satisfy FR31 (structured logs for every lifecycle event)

### Story 6.3: Implement Health Check and Status Endpoints

As a **platform operator**,
I want **health check endpoints that validate all dependencies**,
So that **orchestration systems can detect service degradation automatically**.

**Acceptance Criteria:**

**Given** service is running
**When** health check is implemented
**Then** GET /health endpoint returns 200 OK if service is healthy
**And** health check validates: Redis connectivity, MinIO/S3 connectivity, NATS connectivity, ClamAV connectivity
**And** any dependency failure returns 503 Service Unavailable with details
**And** response includes: status (healthy/degraded/unhealthy), dependencies (list with status per dependency)
**And** GET /status endpoint returns service metrics: active_uploads_count, capacity_remaining, uptime_seconds
**And** /status does NOT require authentication (public monitoring endpoint)
**And** health checks run async and timeout after 5 seconds per dependency
**And** satisfies FR32 (determine service health without log scraping)

### Story 6.4: Generate OpenAPI 3.0 Specification

As a **frontend developer**,
I want **a complete OpenAPI 3.0 specification for the upload API**,
So that **I can consume the API without needing a custom SDK**.

**Acceptance Criteria:**

**Given** all API endpoints are implemented
**When** FastAPI application is running
**Then** GET /openapi.json returns complete OpenAPI 3.0 spec
**And** spec includes all /v1/uploads endpoints with request/response schemas
**And** schemas use camelCase field names (matching API responses)
**And** spec documents all error responses (401, 403, 404, 409, 413, 415, 429, 460, 503)
**And** spec includes authentication requirement (JWT Bearer token)
**And** GET /docs provides interactive Swagger UI documentation
**And** GET /redoc provides ReDoc alternative documentation
**And** spec is consumable by Vue.js frontend without custom SDK (FR33)
**And** all endpoints have clear descriptions and examples

## Epic 7: Upload Metadata & Session Management

Workspace owners can list all their upload sessions, retrieve detailed session metadata, and collaborators can access metadata for shared files.

### Story 7.1: Implement List Upload Sessions (GET /v1/uploads)

As a **workspace owner**,
I want **to see all my upload sessions with filtering by status**,
So that **I can monitor upload progress and history**.

**Acceptance Criteria:**

**Given** I have multiple upload sessions in my workspace
**When** I call GET /v1/uploads
**Then** response includes all sessions for my workspace (from JWT workspace_id)
**And** each session includes: uploadId, filename, size, status, offset, createdAt, expiresAt
**And** query parameter ?status=in_progress filters to only IN_PROGRESS sessions
**And** supported status filters: pending, in_progress, complete, failed, aborted
**And** sessions are sorted by createdAt (newest first)
**And** pagination is supported with ?page and ?limit query parameters
**And** response includes total count of sessions
**And** endpoint allows both OWNER and COLLABORATOR roles (read operation)
**And** collaborators only see sessions for files in their shared_file_ids
**And** empty workspace returns 200 with empty sessions array

### Story 7.2: Implement Get Session Metadata (GET /v1/uploads/{id})

As a **workspace owner**,
I want **detailed metadata for a specific upload session**,
So that **I can inspect progress, timestamps, and any errors**.

**Acceptance Criteria:**

**Given** a session exists in my workspace
**When** I call GET /v1/uploads/{id}
**Then** response includes complete session details
**And** response fields: uploadId, workspaceId, filename, size, mimeType, sha256Checksum, offset, status, createdAt, expiresAt, completedAt (if complete)
**And** response includes upload progress percentage: (offset / size) \* 100
**And** response includes chunk count: verified chunks vs total expected
**And** failed sessions include errorCode and errorMessage fields
**And** endpoint validates workspace ownership (403 if different workspace)
**And** collaborators can access if file_id in their shared_file_ids
**And** non-existent session returns 404 Session Not Found
**And** response follows camelCase JSON convention via Pydantic

### Story 7.3: Implement Collaborator Shared File Access

As a **collaborator**,
I want **read-only access to metadata for files shared with me**,
So that **I can view upload status without being able to modify anything**.

**Acceptance Criteria:**

**Given** I am a collaborator with shared_file_ids in my JWT
**When** I call GET /v1/uploads (list)
**Then** I only see sessions where file_id is in my shared_file_ids array
**And** I cannot see other workspace sessions
**When** I call GET /v1/uploads/{id} (retrieve)
**Then** I can access metadata if file_id is in shared_file_ids
**And** I receive 403 Forbidden if file_id is not in shared list
**When** I attempt write operations (POST, PATCH, DELETE)
**Then** I receive 403 Forbidden with message "Write operations require workspace owner role"
**And** my read access does not grant any upload, modify, or delete capabilities
**And** shared_file_ids claim is validated on every request
