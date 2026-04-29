---
stepsCompleted:
    [
        "step-01-init",
        "step-02-discovery",
        "step-02b-vision",
        "step-02c-executive-summary",
        "step-03-success",
        "step-04-journeys",
        "step-05-domain",
        "step-06-innovation",
        "step-07-project-type",
        "step-08-scoping",
        "step-09-functional",
        "step-10-nonfunctional",
        "step-11-polish",
        "step-12-complete",
    ]
workflowStatus: complete
completedAt: "2026-04-28T20:26:18+03:00"
releaseMode: single-release
inputDocuments:
    - "artifacts/planning-artifacts/product-brief-rag-file-uploader.md"
    - "artifacts/planning-artifacts/research/technical-rest-api-rag-chunked-upload-streaming-research-2026-04-27.md"
briefCount: 1
researchCount: 1
brainstormingCount: 0
projectDocsCount: 0
workflowType: "prd"
classification:
    projectType: api_backend
    domain: AI/ML Platform Infrastructure
    complexity: medium-high
    projectContext: greenfield
    platformRole: microservice within a larger platform
    multiTenant: true
    complianceRequirements: none
---

# Product Requirements Document - rag-file-uploader

**Author:** VP
**Date:** 2026-04-28

## Executive Summary

RAG platforms are only as good as the knowledge they ingest — and that knowledge enters through a single critical path: the file upload. When a large PDF silently fails mid-transfer, the knowledge base is incomplete, vector embeddings are corrupted, and AI responses degrade with no visible cause. Users lose trust in the platform before the RAG pipeline ever runs.

**RAG File Uploader** is the ingestion boundary of a larger knowledge platform. It exists to make that trust moment reliable. Users — researchers, analysts, knowledge workers — upload dense PDF documents to power their personal knowledge bases. This service ensures every file lands intact, every time, regardless of network conditions or file size. No silent failures. No starting over. No intervention required.

The service implements a tus-protocol-inspired chunked upload API on FastAPI. Files up to 1 GB are split into independently verified segments, each validated with a SHA-256 checksum before commit. Upload sessions are persisted in Redis with 24-hour TTL, enabling seamless resumability across disconnects and restarts. Assembled files are stored immutably on MinIO/S3 as the bronze-layer source of truth. On completion, a `FILE_LOADED` event is published to NATS — the explicit handoff to downstream RAG pipeline services (chunking, embedding, indexing) without coupling those concerns to the upload path.

The API is consumed directly by a Vue.js frontend — 6 versioned endpoints under `/v1` covering the full upload lifecycle (see **Technical API Specification**). Every request is JWT-gated. Each user operates in an isolated tenant workspace — their knowledge base is theirs alone, enforced at storage path, Redis key prefix, deduplication scope, and rate limit boundaries.

### What Makes This Special

Most upload services stop at storage. This one treats the `FILE_LOADED` event as a first-class output — the handoff to the knowledge pipeline is built in, not bolted on.

The differentiator is **reliability as a product value, not an engineering concern**. SHA-256 verification per chunk means corruption is caught at the boundary — not discovered later when RAG responses degrade. A bad chunk is rejected immediately with `460 Checksum Mismatch`; the client retries only that segment. Upload sessions survive server restarts. Progress is never lost.

The event-driven architecture (`FILE_LOADED` on NATS, bronze-layer immutable storage) is designed from day 1 for expansion beyond PDFs — toward a universal knowledge ingestion hub that accepts all media types without re-engineering the core pipeline contract.

## Project Classification

| Dimension        | Value                                                                                                |
| ---------------- | ---------------------------------------------------------------------------------------------------- |
| **Project Type** | REST API Backend — microservice within a larger knowledge platform                                   |
| **Domain**       | AI/ML Platform Infrastructure                                                                        |
| **Complexity**   | Medium-High — distributed chunked upload protocol, multi-tenant isolation, event-driven architecture |
| **Context**      | Greenfield — new service, no existing codebase                                                       |
| **Multi-Tenant** | Yes — enforced from day 1 at every layer                                                             |
| **Compliance**   | None required for v1                                                                                 |

## Success Criteria

### User Success

- **Upload completion rate**: ≥ 90% of uploads complete on first attempt without user-visible interruption
- **Resumability**: If a session is interrupted (network drop, browser close, client crash), the upload resumes from the exact byte offset within a 24-hour window — no re-upload of already-verified chunks
- **Silent recovery**: The Vue.js frontend auto-retries failed chunks transparently; users are never asked to restart an upload that can be resumed
- **Zero ambiguity**: Every upload either completes verifiably (confirmed SHA-256 checksum, `FILE_LOADED` event fired) or returns a clear, actionable error — no silent partial successes

### Business Success

- **Demo milestone gate**: The service is production-ready and integrated into the broader platform demo — reliable ingest is the prerequisite for showcasing any downstream RAG capability
- **Zero silent failure tolerance**: Any silent failure rate ≥ 1% is treated as a P0 incident requiring immediate remediation; 5% silent failure is platform-breaking

### Technical Success

- **Concurrency**: 10 concurrent 500 MB uploads and 50 concurrent 100 MB uploads complete without data loss or corruption
- **Integrity**: Per-chunk SHA-256 verification catches 100% of corrupted segments before storage commit; corrupt chunks return `460 Checksum Mismatch` and are retried at chunk level only
- **Performance**: Server-side per-chunk processing overhead (SHA-256 verification + Redis session state write) ≤ 100ms per 5 MB chunk; upload throughput is bounded by client network speed, not service capacity
- **Security**: JWT validation rejects 100% of unauthenticated requests; ClamAV virus scanning blocks known malicious payloads before bronze layer write
- **Tenant isolation**: No cross-tenant data access at any layer — storage path, Redis key prefix, deduplication scope, and rate limits are all tenant-scoped
- **Observability**: Prometheus metrics exposed — `upload_chunks_total`, `upload_bytes_total`, `chunk_verification_failures_total`; service health queryable without log scraping

### Measurable Outcomes

| Outcome                            | Target   | Threshold                    |
| ---------------------------------- | -------- | ---------------------------- |
| Upload first-attempt success rate  | ≥ 90%    | < 85% triggers investigation |
| Silent failure rate                | 0%       | ≥ 1% = P0 incident           |
| Chunk integrity catch rate         | 100%     | Any miss = critical defect   |
| Unauthenticated request rejection  | 100%     | Any miss = security incident |
| Per-chunk processing overhead      | ≤ 100ms  | > 500ms = performance defect |
| Upload session resumability window | 24 hours | < 1 hour = unacceptable      |

## Product Scope

### MVP — Minimum Viable Product

The demo milestone gate. Everything here must work to unblock downstream platform capabilities:

- PDF file uploads up to 1 GB per file
- Chunked, resumable upload with per-chunk SHA-256 integrity verification
- MinIO/S3 bronze-layer immutable storage (raw files, unmodified)
- `FILE_LOADED` event publication via NATS (file ID, tenant ID, S3 path, checksum, size, timestamp)
- Upload session state in Redis with 24-hour TTL and atomic chunk tracking
- File deduplication within tenant workspace (SHA-256 fingerprint match)
- ClamAV virus scanning before bronze layer write
- Multi-file batch uploads (sequenced individually through chunk pipeline)
- JWT authentication with per-tenant workspace isolation at every layer
- REST API versioned at `/v1`, consumable by Vue.js frontend without custom SDK
- Prometheus observability — three core metrics minimum
- Docker containerised, deployable as part of the broader platform

### Growth Features (Post-MVP)

Features that make the service competitive and operationally robust:

- Additional file types (DOCX, TXT, Markdown — expand ahead of audio/video)
- Configurable chunk size per upload session (client hint, server-bounded)
- Per-tenant upload rate limiting and quota enforcement
- Admin API for upload session inspection and manual abort
- Webhook callbacks as an alternative to NATS event (for platform integrators who can't consume NATS directly)
- Enhanced error telemetry — per-tenant failure rates exposed via Prometheus

### Vision (Future)

The universal knowledge ingestion hub:

- All media types — audio, video, images, structured data (CSV, JSON)
- Format-aware pre-processing hooks per media type (e.g., audio transcription trigger, image OCR trigger) — delivered as pluggable pipeline steps, not hardcoded logic
- Rich `FILE_LOADED` event envelope carrying format metadata, extracted structure hints, and tenant lineage — enabling intelligent multi-modal RAG pipelines
- Global deduplication across a shared knowledge graph (cross-tenant, opt-in)
- Presigned upload URLs for direct-to-storage flows where the API service is not in the hot path

## User Journeys

### Journey 1: Dr. Elena — Knowledge Worker & Workspace Owner (Happy Path)

Dr. Elena is a legal researcher building a personal knowledge base to power her AI assistant. She has 40+ dense case law PDFs totalling over 3 GB, accumulated over a decade of research. Before this platform, she'd tried three times to upload a 650 MB landmark ruling to a competitor tool — each attempt timed out past the 80% mark, silently, with no way to resume.

She opens the platform, creates her workspace. At that moment, she becomes the owner and administrator — the workspace is hers alone, isolated from every other user's data. She selects her first file: a 700 MB PDF corpus. The Vue.js frontend splits it into chunks and begins uploading. A progress bar advances steadily. She doesn't know — or need to know — that behind this bar, each chunk is being SHA-256 verified, committed to Redis, and streamed to MinIO. She starts preparing her next file.

Upload completes. The service assembles the multipart file on MinIO, writes it to the bronze layer, and fires a `FILE_LOADED` event to NATS. The downstream RAG pipeline picks it up — chunking, embedding, indexing. Minutes later, Elena asks her knowledge base a question about a ruling from 1994. The answer is accurate. The citation is correct. She uploads the remaining 39 files without a second thought.

**This journey reveals requirements for:** workspace creation with owner role assignment, JWT-scoped upload authorization (owner-only), chunked upload pipeline, MinIO bronze-layer write, `FILE_LOADED` event publication, Prometheus progress observability.

---

### Journey 2: Marcus — Knowledge Worker / Workspace Owner (Interrupted Upload — Edge Case)

Marcus is a financial analyst building a knowledge base from quarterly earnings PDFs. He's mid-upload on a 900 MB archive — 67% through — when his laptop loses WiFi and switches to mobile hotspot. The connection drops entirely for 8 seconds.

The Vue.js frontend detects the interruption. It doesn't show an error. It silently queries `HEAD /v1/uploads/{id}` to retrieve the last verified offset — chunk 134 of 200. It resumes PATCH requests from exactly that byte offset. Marcus glances at his screen 15 seconds later. The progress bar is still moving. He never knew anything went wrong.

Later that evening, Marcus closes his laptop mid-upload — 43% through a different file — and forgets about it. The next morning he opens the platform. The upload session is still alive in Redis (24-hour TTL). The frontend queries the offset, resumes automatically on page load. The file completes while Marcus drinks his coffee.

**This journey reveals requirements for:** `HEAD /v1/uploads/{id}` offset query, Vue.js silent auto-retry on interruption, Redis session persistence with 24-hour TTL, resume-from-offset PATCH behaviour, graceful session expiry handling (what happens at hour 25).

---

### Journey 3: Elena Shares a File — Workspace Owner & Collaborator Access

Elena wants to share a single ruling — a 45 MB PDF she uploaded last week — with her colleague Priya, a paralegal who needs to reference it. She grants Priya read access to that specific file through the platform. Priya receives a link.

Priya authenticates with her own JWT. Her token carries her user ID and a grant record linking her to that specific file in Elena's workspace. She can open and read the document. She cannot see Elena's other files. She cannot upload anything. When Priya attempts to navigate to Elena's workspace root, the service returns `403 Forbidden` — the JWT grant is scoped to one file, not the workspace.

Elena later decides to share her entire workspace with a trusted research partner. She grants workspace-level read access. The partner can now browse all of Elena's files — but still cannot upload, delete, or modify anything. The upload endpoints reject their JWT: `403 Forbidden — insufficient role`.

**This journey reveals requirements for:** file-level and workspace-level access grant model in JWT claims, upload endpoint role enforcement (owner-only write), read endpoint scoped authorization, cross-tenant isolation guarantees, `403` vs `401` error semantics.

---

### Journey 4: Platform Operator — Investigating a Spike in Chunk Failures

The ops team's Grafana dashboard shows `chunk_verification_failures_total` spiking — 47 failures in 20 minutes, all from the same tenant workspace. This is unusual. Normal baseline is near zero.

The operator queries Prometheus. The spike correlates with a single upload session — a 1.2 GB file uploaded by a specific user. The failures are all `460 Checksum Mismatch` responses. No data was written to MinIO for any failed chunk — the integrity gate held. The service did not silently accept corrupt data.

The operator checks structured logs. The pattern reveals the client is a non-browser integration that is computing SHA-256 checksums incorrectly — sending the checksum of the raw file chunk before base64 encoding, but the service expects the checksum of the encoded form. The user's upload is failing, but the platform is not degraded — other uploads are completing normally.

The operator opens a support ticket, contacts the user, and shares the correct checksum computation spec from the API documentation. The user fixes their client. The next upload completes without a single failure.

**This journey reveals requirements for:** `chunk_verification_failures_total` Prometheus metric with tenant label, structured log fields (tenant ID, session ID, chunk index, failure reason), `460 Checksum Mismatch` error response with actionable message, operational runbook linkage in API error docs.

---

### Journey Requirements Summary

| Capability Area                                                | Revealed By   |
| -------------------------------------------------------------- | ------------- |
| Workspace creation + owner role assignment                     | Journey 1     |
| JWT-scoped upload authorization (owner-only write)             | Journeys 1, 3 |
| Chunked upload pipeline with SHA-256 per-chunk verification    | Journeys 1, 2 |
| MinIO bronze-layer write + `FILE_LOADED` NATS event            | Journey 1     |
| `HEAD` offset query + Vue.js silent auto-retry                 | Journey 2     |
| Redis session persistence (24h TTL) + resume-from-offset       | Journey 2     |
| Session expiry handling at TTL boundary                        | Journey 2     |
| File-level and workspace-level read access grants in JWT       | Journey 3     |
| `403 Forbidden` enforcement on upload endpoints for non-owners | Journey 3     |
| Cross-tenant isolation guarantees                              | Journey 3     |
| `chunk_verification_failures_total` metric with tenant label   | Journey 4     |
| Structured logs with tenant ID, session ID, failure reason     | Journey 4     |
| `460 Checksum Mismatch` with actionable error message          | Journey 4     |

## Technical API Specification

### Overview

RAG File Uploader is a REST API microservice — no UI, no SDK — consumed directly by an internal Vue.js frontend. The API follows tus-protocol-inspired semantics with versioned endpoints under `/v1`. All endpoints are stateless from the client's perspective; all session state is server-side in Redis.

### Endpoint Specification

| Method   | Endpoint           | Description                                                          | Auth                                     |
| -------- | ------------------ | -------------------------------------------------------------------- | ---------------------------------------- |
| `POST`   | `/v1/uploads`      | Initiate upload session; returns upload ID and expiry                | Owner                                    |
| `PATCH`  | `/v1/uploads/{id}` | Upload a chunk at offset; validates SHA-256 per chunk                | Owner                                    |
| `HEAD`   | `/v1/uploads/{id}` | Query current verified offset; enables resumability                  | Owner                                    |
| `DELETE` | `/v1/uploads/{id}` | Abort session and clean up Redis state                               | Owner                                    |
| `GET`    | `/v1/uploads`      | List upload sessions for active workspace (filterable by status)     | Owner                                    |
| `GET`    | `/v1/uploads/{id}` | Fetch session metadata: filename, size, status, checksum, timestamps | Owner / Collaborator (shared files only) |

**Skipped for v1:** download endpoints, file management endpoints (separate service concern).

### Authentication Model

- **Token issuer**: Platform-dedicated auth service — the upload service validates tokens, does not issue them
- **Approach**: Workspace-scoped JWT — the platform auth service issues tokens scoped to a single active workspace. Switching workspace requires a new token from the auth service. The upload service validates independently: no extra DB lookup, no stale authorization risk, manageable JWT size.
- **JWT claims**:
    ```json
    {
        "user_id": "uuid",
        "active_workspace_id": "uuid",
        "workspace_role": "owner | collaborator",
        "shared_file_ids": ["uuid"],
        "exp": 1234567890
    }
    ```
- **Upload authorization**: Only `workspace_role: owner` tokens may call `POST`, `PATCH`, `DELETE` endpoints — `403 Forbidden` for collaborators
- **Read authorization**: `GET` endpoints validate that `active_workspace_id` matches the resource workspace; collaborators may access `GET /v1/uploads/{id}` only for file IDs present in their `shared_file_ids` claim

### Data Schemas

**Initiate Upload — Request** (`POST /v1/uploads`):

```json
{
    "filename": "string",
    "size": "integer (bytes)",
    "mime_type": "application/pdf",
    "sha256_checksum": "string (full-file SHA-256, hex-encoded)"
}
```

**Initiate Upload — Response** (`201 Created`):

```json
{
    "upload_id": "uuid",
    "workspace_id": "uuid",
    "offset": 0,
    "expires_at": "ISO-8601 timestamp",
    "status": "pending"
}
```

**Chunk Upload — Request** (`PATCH /v1/uploads/{id}`):

- Body: raw binary chunk (`Content-Type: application/offset+octet-stream`)
- Headers: `Upload-Offset`, `Upload-Length`, `Upload-Checksum: sha256 <hex>`

**Chunk Upload — Response** (`204 No Content`):

- Header: `Upload-Offset: <new_verified_offset>`

**Session Metadata — Response** (`GET /v1/uploads/{id}`):

```json
{
    "upload_id": "uuid",
    "workspace_id": "uuid",
    "filename": "string",
    "size": "integer",
    "mime_type": "string",
    "status": "pending | in_progress | complete | failed | aborted",
    "offset": "integer",
    "sha256_checksum": "string",
    "created_at": "ISO-8601",
    "expires_at": "ISO-8601",
    "completed_at": "ISO-8601 | null"
}
```

**Session List — Response** (`GET /v1/uploads`):

```json
{
  "items": [{ "...session metadata..." }],
  "total": "integer",
  "page": "integer",
  "page_size": "integer"
}
```

### Error Codes

All error responses follow the standard schema:

```json
{
    "error": "CHECKSUM_MISMATCH",
    "code": 460,
    "message": "Chunk SHA-256 checksum does not match Upload-Checksum header value",
    "request_id": "uuid"
}
```

| Status | Error Code               | Trigger                                                |
| ------ | ------------------------ | ------------------------------------------------------ |
| `400`  | `INVALID_REQUEST`        | Malformed body, missing required fields                |
| `401`  | `UNAUTHORIZED`           | Missing or invalid JWT                                 |
| `403`  | `FORBIDDEN`              | Collaborator attempting write operation                |
| `404`  | `SESSION_NOT_FOUND`      | Upload ID does not exist or has expired                |
| `409`  | `DUPLICATE_FILE`         | SHA-256 fingerprint matches existing file in workspace |
| `413`  | `FILE_TOO_LARGE`         | File exceeds 1 GB limit                                |
| `415`  | `UNSUPPORTED_MEDIA_TYPE` | Non-PDF MIME type                                      |
| `460`  | `CHECKSUM_MISMATCH`      | Per-chunk SHA-256 verification failure                 |
| `507`  | `STORAGE_UNAVAILABLE`    | MinIO/S3 write failure                                 |

### Rate Limits

**v1 — Capacity-based only (no subscription enforcement):**

- Max concurrent upload sessions per service instance: **10** (at 500 MB each = 5 GB in-flight per instance)
- Total concurrent capacity: `10 × num_running_instances` (configurable via `MAX_CONCURRENT_UPLOADS` env var)
- Enforced via Redis atomic counter per workspace; sessions exceeding capacity receive `429 Too Many Requests`

**Guest users — Configurable rate limit:**

- Default: 1 file per day
- Configurable via env vars: `GUEST_RATE_LIMIT_COUNT=1`, `GUEST_RATE_LIMIT_WINDOW=day|week|month`
- Tracked per `user_id` in Redis with TTL matching the configured window

**Post-v1:** Subscription tier-based limits enforced per tenant — to be designed when subscription model is defined.

### API Documentation

- OpenAPI 3.0 spec auto-generated by FastAPI at `/docs` (Swagger UI) and `/openapi.json`
- Consumable by Vue.js frontend without custom SDK
- All `460 Checksum Mismatch` responses include a link to checksum computation guide in the API docs

## Project Scoping

### Strategy & Philosophy

**Approach:** Single v1 release — build the complete MVP scope, ship it as the demo milestone gate, then plan post-v1 evolution separately. No phased milestones within v1.

**Release goal:** A production-ready, demo-ready file ingestion microservice that earns user trust from the first upload. Every capability in the MVP scope ships together — partial delivery would leave the platform without a reliable ingest boundary.

**Resource requirements:** Backend engineer(s) with FastAPI + async Python proficiency; Redis, MinIO, NATS operational experience; DevOps for Docker + Prometheus setup; internal Vue.js team for frontend integration.

### Complete Feature Set

All capabilities as defined in **Product Scope — MVP**. The four user journeys fully covered: happy-path upload (J1), interrupted-upload recovery (J2), workspace sharing (J3), and operator failure investigation (J4).

### Risk Mitigation Strategy

**Technical Risks:**

| Risk                                                    | Likelihood | Impact | Mitigation                                                                                                                 |
| ------------------------------------------------------- | ---------- | ------ | -------------------------------------------------------------------------------------------------------------------------- |
| ClamAV scanning latency on large files (1 GB scan time) | Medium     | Medium | Run ClamAV async — scan after bronze layer write, block `FILE_LOADED` event until scan clears; configurable scan timeout   |
| NATS unavailable when upload completes                  | Medium     | High   | Dead letter queue in Redis for failed event publications; retry with exponential backoff before marking upload `failed`    |
| Redis restart loses in-flight upload sessions           | Low        | High   | Enable Redis AOF persistence or replication; 24h TTL means sessions are recoverable on restart                             |
| MinIO multipart partial commits                         | Low        | Medium | Lifecycle policy on MinIO to abort incomplete multipart uploads after 48h; service-side abort on `DELETE /v1/uploads/{id}` |

**Market Risks:**

- **Risk**: Demo showcases upload reliability but downstream RAG pipeline isn't ready — perceived value is low
- **Mitigation**: `FILE_LOADED` event contract is the interface boundary; the upload service is independently demonstrable with a stub consumer that logs received events

**Resource Risks:**

- **Risk**: ClamAV + NATS + MinIO + Redis = 4 external service dependencies to stand up
- **Mitigation**: Docker Compose file ships with the service, providing all dependencies pre-configured for local and demo environments; nice-to-have items (deduplication, virus scanning) can be feature-flagged if ClamAV setup blocks demo timeline

## Functional Requirements

### Upload Session Management

- **FR1**: Workspace owner can initiate a new upload session for a PDF file, receiving a session ID and expiry timestamp
- **FR2**: Workspace owner can upload a file in sequential chunks, each carrying a SHA-256 checksum header
- **FR3**: The system validates the SHA-256 checksum of each chunk independently before committing it
- **FR4**: The system rejects any chunk whose checksum does not match, returning a `460 Checksum Mismatch` error with an actionable message
- **FR5**: Workspace owner can query the current verified byte offset of an active upload session
- **FR6**: Workspace owner can abort an active upload session, triggering cleanup of all associated state
- **FR7**: Workspace owner can list all upload sessions for their active workspace, filterable by status
- **FR8**: Workspace owner can retrieve detailed metadata for a specific upload session (filename, size, status, checksum, timestamps)
- **FR9**: Collaborators with shared file access can retrieve metadata for specifically shared files

### Upload Resumability

- **FR10**: The system persists upload session state (verified offset, chunk manifest) durably for a minimum of 24 hours
- **FR11**: A client can resume an interrupted upload from the last verified byte offset without re-uploading already-committed chunks
- **FR12**: Upload sessions that exceed the 24-hour TTL expire gracefully, returning `404 Session Not Found` to resumption attempts
- **FR13**: The system supports multi-file batch uploads, processing each file independently through the chunk pipeline

### File Integrity & Validation

- **FR14**: The system validates that uploaded files do not exceed 1 GB before accepting a session
- **FR15**: The system validates that uploaded files are of type `application/pdf`, rejecting unsupported MIME types with `415 Unsupported Media Type`
- **FR16**: The system detects duplicate files within a tenant workspace using SHA-256 fingerprint matching and returns `409 Duplicate File`
- **FR17**: The system scans assembled files for known malicious payloads before committing to bronze-layer storage
- **FR18**: The system assembles all verified chunks into an immutable, unmodified file on MinIO/S3 bronze-layer storage

### Pipeline Integration

- **FR19**: The system publishes a `FILE_LOADED` event upon successful file assembly and storage, carrying: file ID, tenant/workspace ID, S3 path, SHA-256 checksum, file size, and timestamp
- **FR20**: The system retries `FILE_LOADED` event publication on NATS unavailability before marking the upload as failed
- **FR21**: Downstream services can subscribe to `FILE_LOADED` events without any coupling to the upload service

### Workspace & Tenant Isolation

- **FR22**: Each user who creates a workspace becomes its sole owner with full read/write/delete rights
- **FR23**: Workspace owners can grant other users read-only access to specific files within their workspace
- **FR24**: Workspace owners can grant other users read-only access to their entire workspace
- **FR25**: Collaborators cannot upload, modify, or delete files in any workspace — regardless of their access grant level
- **FR26**: The system enforces complete data isolation between workspaces at storage path, session state, deduplication scope, and rate limit boundaries

### Authentication & Authorisation

- **FR27**: The system validates a JWT on every request, rejecting requests with missing or invalid tokens with `401 Unauthorized`
- **FR28**: The system enforces workspace-role-based access control — collaborator tokens are rejected on write endpoints with `403 Forbidden`
- **FR29**: The system supports workspace-scoped JWT tokens issued by the platform auth service, carrying workspace ID, role, and optionally shared file IDs

### Guest User Controls

- **FR30**: Guest users are subject to a configurable upload rate limit (count and time window) enforced independently per user
- **FR31**: Platform operators can configure the guest rate limit window (day / week / month) and maximum file count via environment variables

### Observability & Operations

- **FR32**: The system exposes Prometheus metrics: `upload_chunks_total`, `upload_bytes_total`, `chunk_verification_failures_total`, all labelled by workspace
- **FR33**: The system emits structured logs for every upload lifecycle event, including tenant ID, session ID, chunk index, and failure reason where applicable
- **FR34**: Platform operators can determine service health and active upload load without log scraping
- **FR35**: The system exposes an OpenAPI 3.0 specification at `/openapi.json` consumable by the Vue.js frontend without a custom SDK

### Capacity & Availability

- **FR36**: The system enforces a configurable maximum of concurrent upload sessions per service instance, returning `429 Too Many Requests` when exceeded
- **FR37**: The system is deployable as a Docker container alongside its dependencies (Redis, MinIO, NATS, ClamAV) via a provided Docker Compose configuration

## Non-Functional Requirements

### Performance

- **NFR-P1**: `POST /v1/uploads` (session initiation) responds within **200ms** at p99 under normal load
- **NFR-P2**: `HEAD /v1/uploads/{id}` (offset query) responds within **50ms** at p99 — this is in the hot retry path
- **NFR-P3**: Server-side per-chunk processing overhead (SHA-256 verification + Redis state write) ≤ **100ms** per 5 MB chunk at p99
- **NFR-P4**: Upload throughput is bounded by client network speed, not service processing capacity — the service must not be the bottleneck
- **NFR-P5**: 10 concurrent 500 MB uploads and 50 concurrent 100 MB uploads complete without throughput degradation > 10% compared to single-upload baseline

### Security

- **NFR-S1**: All data in transit is encrypted via **TLS 1.2 minimum** on all API endpoints and service-to-service connections (MinIO, Redis, NATS)
- **NFR-S2**: All files at rest on MinIO are encrypted using **AES-256 server-side encryption**
- **NFR-S3**: Upload session IDs are **cryptographically random UUIDs** (v4) — not sequential, not guessable
- **NFR-S4**: JWT validation is enforced on **100% of requests** — no endpoint is accessible without a valid token
- **NFR-S5**: No cross-tenant data is accessible at any layer — storage path namespace, Redis key prefix, and deduplication scope are all isolated per workspace
- **NFR-S6**: No malicious payload is persisted to the bronze layer — ClamAV scanning must complete before `FILE_LOADED` event is published

### Scalability

- **NFR-SC1**: The service is **stateless** — all session state is in Redis; adding instances increases concurrent upload capacity linearly without coordination overhead
- **NFR-SC2**: Maximum concurrent sessions scales as `MAX_CONCURRENT_UPLOADS × num_instances`, configurable without code changes
- **NFR-SC3**: Redis and MinIO scale independently of the upload service — no shared in-process state between instances
- **NFR-SC4**: The service handles a **10× increase in concurrent sessions** (via additional instances) with no architectural changes

### Reliability

- **NFR-R1**: Upload first-attempt success rate ≥ **90%** under normal operating conditions
- **NFR-R2**: Silent failure rate must be **0%** — any silent failure rate ≥ 1% constitutes a P0 incident
- **NFR-R3**: Upload session state survives **service restarts** — Redis AOF persistence or replication is required; in-flight sessions resume from last verified offset on reconnect
- **NFR-R4**: `FILE_LOADED` event publication achieves **at-least-once delivery** — failures trigger retry with exponential backoff before the upload is marked `failed`
- **NFR-R5**: ClamAV service unavailability must not silently bypass scanning — the service either waits (with configurable timeout) or returns a clear error; it never skips scanning and proceeds

### Integration

- **NFR-I1**: **NATS JetStream**: `FILE_LOADED` events published to a durable subject; consumers can replay events on reconnect; subject name and schema are stable API contracts
- **NFR-I2**: **MinIO/S3**: All storage operations use the S3-compatible API — no MinIO-specific SDK calls that would prevent migration to AWS S3 or compatible alternatives
- **NFR-I3**: **Redis**: All session state operations use atomic commands (`HSET`, `HINCRBY`, `EXPIRE`) — no Lua scripts or cluster-incompatible patterns
- **NFR-I4**: **ClamAV**: Integration via `clamd` TCP socket — clamd address and port configurable via environment variables
- **NFR-I5**: **Prometheus**: `/metrics` endpoint exposed on a configurable port (default: `9090`); compatible with standard Prometheus scrape config; scrape interval ≤ 15 seconds
- **NFR-I6**: **JWT**: Service accepts RS256 or HS256 signed tokens; public key / secret configurable via environment variables; no hard-coded auth logic
