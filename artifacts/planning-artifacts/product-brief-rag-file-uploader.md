---
title: "Product Brief: rag-file-uploader"
status: "complete"
created: "2026-04-27"
updated: "2026-04-27"
inputs:
  - "bmad/output/planning-artifacts/research/technical-rest-api-rag-chunked-upload-streaming-research-2026-04-27.md"
  - "User discovery session with VP, 2026-04-27"
---

# Product Brief: RAG File Uploader

## Executive Summary

RAG platforms are only as good as the knowledge they ingest. When a 600 MB PDF silently fails mid-upload, the knowledge base is incomplete — and the AI answers users receive are wrong in ways no one can easily detect. This is the silent killer of production RAG deployments.

**RAG File Uploader** is a dedicated ingestion microservice that solves large-file reliability at the boundary of the data pipeline. It accepts PDF documents up to 1 GB from end users, transfers them via fault-tolerant chunked uploads with per-segment integrity verification, stores them immutably on MinIO/S3 as the bronze-layer source of truth, and fires a `FILE_LOADED` event to trigger all downstream processing — chunking, embedding, indexing — without coupling any of those concerns to the upload path.

Built as a standalone REST API consumed by a Vue.js frontend, it gives knowledge workers a professional-grade upload experience with deduplication, virus scanning, and multi-file batch support — the kind of reliability that transforms a RAG prototype into a production-grade knowledge platform.

---

## The Problem

Large-file uploads over HTTP are inherently unreliable. A single network hiccup at byte 480 MB of a 500 MB file means starting over. For end users building personal or team knowledge bases from dense technical PDFs, legal corpora, or research archives, this isn't a minor inconvenience — it's a workflow blocker.

The consequences compound silently downstream. A partial or corrupted upload that makes it through produces broken vector embeddings. RAG responses degrade with no obvious cause — the system appears to work, but the knowledge is wrong. By the time the problem is detected, the cost is a full re-ingest cycle and lost user trust.

Current workarounds are painful:
- **Direct S3 uploads** lack progress tracking, resumability, and integrity guarantees for end users
- **Generic file upload libraries** are not designed for the RAG pipeline contract (bronze storage + event trigger)
- **Chunked upload bolt-ons** are typically ad hoc, with no per-chunk verification or session recovery

The gap is a purpose-built service that treats large-file reliability as a first-class concern — not an afterthought.

---

## The Solution

RAG File Uploader is a FastAPI microservice that implements a tus-protocol-inspired chunked upload API. Uploads are broken into independently verified segments. Each chunk is validated with a SHA-256 checksum before being committed. Redis tracks the upload session state — which chunks arrived, which failed, what offset to resume from — with atomic operations and 24-hour TTL expiry.

When all chunks arrive and verify, the service assembles the file via MinIO's native multipart API and persists it to the S3 bronze layer — the raw, immutable source of truth. It then publishes a `FILE_LOADED` event — carrying file ID, tenant ID, S3 path, SHA-256 checksum, file size, and timestamp — to a NATS-compatible message broker (event bus selection in evaluation; NATS JetStream is the leading candidate for its open-source, low-latency, durable messaging model). Downstream RAG pipeline services subscribe to this event to begin processing.

The REST API is clean and consumed directly by a Vue.js frontend:
- `POST /uploads` — initiate session, receive upload ID
- `PATCH /uploads/{id}` — stream a chunk with checksum header
- `HEAD /uploads/{id}` — query current offset (enables resumability)
- `DELETE /uploads/{id}` — abort and clean up

JWT validation gates every request, and each user operates within an isolated tenant workspace — their knowledge base is theirs alone.

---

## What Makes This Different

**Purpose-built for the RAG pipeline contract.** Generic upload services stop at storage. RAG File Uploader treats the `FILE_LOADED` event as a first-class output — the handoff to embedding, chunking, and indexing is built in, not bolted on.

**Bronze layer as source of truth.** Files land on MinIO/S3 in their original, unmodified form before any processing occurs. This enables full re-processing pipelines without re-upload, complete audit trails, and recovery from any downstream failure — the raw file is always there, always intact.

**Chunk-level integrity, not hope.** SHA-256 verification per chunk means corruption is caught at the boundary — not discovered later when RAG responses degrade. A bad chunk is rejected immediately with a `460 Checksum Mismatch` response; the client retries only that segment.

**Resumability as a design principle.** Upload sessions survive client disconnects, server restarts, and transient failures. Users don't lose progress on large files.

---

## Who This Serves

**Primary: Knowledge Workers Building Personal Knowledge Bases**
End users — researchers, analysts, legal professionals, students — who upload dense PDF documents to fuel their personal RAG assistant. They need confidence that a 700 MB research archive lands intact, without babysitting the upload or starting over after a dropped connection.

**Secondary: Frontend Developers & Platform Integrators**
Vue.js frontend teams that consume the REST API. They need a clean, well-documented API contract, predictable error responses, and no surprises in the upload lifecycle.

---

## Success Criteria

**Reliability (v1 gate):**
- 10 concurrent 500 MB PDF uploads complete without data loss or corruption
- 50 concurrent 100 MB PDF uploads complete without data loss or corruption
- Zero silent failures — every upload either succeeds verifiably or returns a clear, actionable error

**Integrity:**
- Per-chunk SHA-256 verification catches 100% of corrupted segments before storage commit
- Deduplication prevents redundant storage of identical files within a tenant workspace

**Security:**
- JWT validation rejects 100% of unauthenticated requests
- Virus scanning blocks known malicious payloads before bronze layer write

**Developer Experience:**
- REST API documented and consumable by the Vue.js frontend without custom SDK
- Prometheus metrics exposed for `upload_chunks_total`, `upload_bytes_total`, `chunk_verification_failures_total`

---

## Scope

**In scope for v1:**
- PDF file type (up to 1 GB per file)
- Chunked, resumable upload with per-chunk SHA-256 verification
- MinIO/S3 bronze layer persistence
- `FILE_LOADED` event publication via NATS
- File deduplication (within tenant workspace)
- Virus scanning before storage commit
- Multi-file batch uploads (up to N files per request, sequenced individually through the chunk pipeline)
- JWT-based auth with per-tenant workspace isolation
- REST API versioned at `/v1` (consumed by Vue.js frontend)
- Upload session resumability window: 24 hours (documented API contract)
- Prometheus observability

**Explicitly out of scope for v1:**
- Audio and video file types
- Document pre-processing or transformation (that's downstream)
- End-user facing UI (owned by the Vue.js frontend service)
- Full-text search or indexing (downstream RAG pipeline concern)

---

## Vision

RAG File Uploader begins as the PDF ingestion boundary of one RAG platform. Within 2–3 years, it evolves into a **universal knowledge ingestion hub**: accepting all media types — audio, video, images, structured data — with format-aware pre-processing hooks, intelligent deduplication across a global knowledge graph, and an extensible pipeline contract that any downstream processing service can subscribe to.

The bronze layer becomes a durable, queryable archive. The `FILE_LOADED` event becomes a rich envelope carrying format metadata, extracted structure hints, and tenant lineage — enabling a new class of intelligent, multi-modal RAG pipelines that process what they receive rather than assuming everything is a PDF.
