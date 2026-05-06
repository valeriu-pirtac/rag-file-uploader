# Story 5.4: Create Event Domain Entities and Schema

Status: done

## Story

As a **developer**,
I want **versioned event schemas for FILE_LOAD_COMPLETED events**,
So that **downstream services have a stable contract for event consumption**.

## Acceptance Criteria

1. **Given** domain layer exists
   **When** event entities are created
   **Then** src/domain/entities/events.py exists with FileLoadCompletedEvent entity

2. **And** event includes fields: event_version ("1.0"), event_type ("FILE_LOAD_COMPLETED"), timestamp (ISO 8601)

3. **And** event payload includes: file_id, workspace_id, s3_path, sha256_checksum, size_bytes, uploaded_at

4. **And** event follows naming convention: upload.file.load_completed (subject name)

5. **And** event schema is documented and considered a stable API contract

6. **And** event serializes to JSON for NATS/webhook publishing

7. **And** src/domain/protocols/event_publisher.py defines IEventPublisher protocol

## Tasks/Subtasks

- [x] Create event domain entity (AC: #1-3, #5-6)
  - [x] Create src/domain/entities/events.py
  - [x] Implement FileLoadCompletedEvent dataclass with validation
  - [x] Add event_version field (string "1.0")
  - [x] Add event_type field (string "FILE_LOAD_COMPLETED")
  - [x] Add timestamp field (datetime, ISO 8601 serialization)
  - [x] Add payload fields: file_id (UUID), workspace_id (UUID)
  - [x] Add payload fields: s3_path (str), sha256_checksum (SHA256Hash)
  - [x] Add payload fields: size_bytes (int), uploaded_at (datetime)
  - [x] Implement to_json() method for serialization
  - [x] Implement to_dict() method for dictionary representation
  - [x] Implement subject_name property returning "upload.file.load_completed"
  - [x] Add comprehensive docstring documenting stable API contract

- [x] Create event publisher protocol (AC: #7)
  - [x] Create src/domain/protocols/event_publisher.py
  - [x] Define IEventPublisher Protocol class
  - [x] Add publish() async method signature
  - [x] Add comprehensive docstring with implementation guidelines
  - [x] Document NATS subject naming convention (AC: #4)
  - [x] Document retry and error handling expectations

- [x] Write comprehensive unit tests
  - [x] Create tests/unit/domain/entities/test_events.py
  - [x] Test FileLoadCompletedEvent creation with valid data
  - [x] Test validation: timezone-aware timestamps required
  - [x] Test validation: file_id and workspace_id must be UUID
  - [x] Test validation: size_bytes must be positive
  - [x] Test validation: s3_path must follow pattern workspace_{id}/{file_id}.pdf
  - [x] Test to_json() serialization produces valid JSON
  - [x] Test to_json() serialization includes all required fields
  - [x] Test to_dict() returns correct dictionary structure
  - [x] Test subject_name property returns "upload.file.load_completed"
  - [x] Test event_version is "1.0"
  - [x] Test event_type is "FILE_LOAD_COMPLETED"
  - [x] Test ISO 8601 timestamp formatting
  - [x] Test SHA256Hash serialization in JSON

- [x] Write protocol validation tests
  - [x] Create tests/unit/domain/protocols/test_event_publisher.py
  - [x] Test IEventPublisher protocol contract
  - [x] Test protocol can be implemented by mock classes
  - [x] Verify publish() method signature matches expectations

- [x] Update domain layer exports
  - [x] Add FileLoadCompletedEvent to src/domain/entities/__init__.py
  - [x] Add IEventPublisher to src/domain/protocols/__init__.py

- [x] Run validation and quality checks
  - [x] Run all unit tests
  - [x] Run ruff linting
  - [x] Run mypy type checking
  - [x] Verify all acceptance criteria met

## Developer Context

### What This Story Is About

Story 5.4 creates **versioned event domain entities and publisher protocol** — the critical contract boundary between the upload service and downstream RAG pipeline services, designed as a stable, evolvable API.

**ARCHITECTURAL POSITION IN EPIC 5:**
This story is the **FOURTH story in Epic 5**, which means:
1. **Story 5.1 (Deduplication)** is complete — deduplication infrastructure exists
2. **Story 5.2 (S3 File Assembly)** is complete — file assembly and storage exists
3. **Story 5.3 (ClamAV Virus Scanner)** is marked optional/deferred — virus scanning not yet implemented
4. This story establishes the **event schema foundation** that Story 5.5 (NATS Publisher) and Story 5.7 (Webhook Publisher) will implement
5. This is a **pure domain story** — no infrastructure implementation, only domain entities and protocols
6. **No API endpoints created** — event publishing is integrated by Story 5.8 (Complete Upload Use Case)

**What This Story ACTUALLY Does:**
This story implements:
1. **FileLoadCompletedEvent entity (domain layer)** — Immutable event representation with versioned schema
2. **IEventPublisher protocol (domain layer)** — Abstract interface for event publishing implementations
3. **Event schema as stable API contract** — Documented, versioned contract for downstream consumers
4. **JSON serialization** — Event converts to JSON for NATS/webhook publishing
5. **NATS subject naming convention** — upload.file.load_completed (dotted hierarchical naming)
6. **Comprehensive unit tests** — Validate event creation, serialization, and protocol contract

**Key Architectural Insights:**

**Event-Driven Architecture Pattern:**
This story implements the **contract boundary** between upload service and RAG pipeline:
```
Upload Service (Producer)          RAG Pipeline (Consumer)
    ↓                                    ↑
FileLoadCompletedEvent (domain)          |
    ↓                                    |
IEventPublisher (protocol)               |
    ↓                                    |
NATS/Webhook (transport)  →  →  →  →  →  |
```

**Event Publication Sequence (Story 5.8 Orchestration):**
```
1. All chunks uploaded and verified (Stories 3.7-3.8)
2. CompleteUploadUseCase triggered (Story 5.8)
3. → Assemble file on S3 (Story 5.2)
4. → Check for duplicates (Story 5.1)
5. → Scan for virus (Story 5.3) — OPTIONAL/DEFERRED
6. → **Create FileLoadCompletedEvent** ← THIS STORY (5.4)
7. → **Publish event via IEventPublisher** ← THIS STORY (5.4 protocol)
8. → Register fingerprint (Story 5.1)
```

**Versioned Event Schema (Critical for Evolution):**
The event uses a **versioned envelope pattern** to enable future schema evolution without breaking consumers:
```json
{
    "event_version": "1.0",
    "event_type": "FILE_LOAD_COMPLETED",
    "timestamp": "2026-05-06T15:30:00Z",
    "payload": {
        "file_id": "123e4567-e89b-12d3-a456-426614174000",
        "workspace_id": "987fcdeb-51a2-43f8-b456-426614174123",
        "s3_path": "s3://rag-uploads/workspace_987fcdeb-51a2-43f8-b456-426614174123/123e4567-e89b-12d3-a456-426614174000.pdf",
        "sha256_checksum": "a" * 64,
        "size_bytes": 1048576,
        "uploaded_at": "2026-05-06T15:25:00Z"
    }
}
```

**Why Versioning Matters:**
- **v1.0 (MVP)**: Base schema with essential fields
- **v1.1 (Future)**: Add optional fields like `original_filename`, `uploaded_by_user_id` without breaking v1.0 consumers
- **v2.0 (Future)**: Breaking changes like renamed fields or restructured payload

**Consumers can handle multiple versions:**
```python
if event["event_version"] == "1.0":
    handle_v1(event["payload"])
elif event["event_version"] == "1.1":
    handle_v1_1(event["payload"])
```

**NATS Subject Naming Convention:**
Subject name: **upload.file.load_completed**

**Rationale for dotted hierarchical naming:**
- Follows NATS best practices for hierarchical subjects
- Enables wildcard subscriptions: `upload.>` (all upload events), `upload.file.>` (all file events)
- Namespace: `upload` (service domain)
- Resource: `file` (resource type)
- Action: `load_completed` (past tense lifecycle event)

**Stable API Contract (Critical):**
This event schema is a **PUBLIC API CONTRACT** between upload service and RAG pipeline:
- **Breaking changes require major version bump** (v2.0)
- **Field removals are breaking changes**
- **Field additions are non-breaking** (consumers ignore unknown fields)
- **Field type changes are breaking changes**
- **Documentation is mandatory** — consumers rely on this contract

**Entity Implementation Pattern:**
```python
# Domain Layer (src/domain/entities/events.py)
from dataclasses import dataclass, asdict
from datetime import datetime
from uuid import UUID
import json

from src.domain.value_objects import SHA256Hash


@dataclass(frozen=True)  # Immutable - events never change
class FileLoadCompletedEvent:
    """FILE_LOAD_COMPLETED event entity (v1.0).
    
    This event is published when a file upload completes successfully
    and the file is ready for downstream RAG pipeline processing.
    
    This is a STABLE API CONTRACT. Any changes to this schema must
    consider backward compatibility and versioning.
    
    Event Lifecycle:
        1. Upload session completes (all chunks verified)
        2. File assembled on S3 (Story 5.2)
        3. Deduplication check passes (Story 5.1)
        4. Virus scan passes (Story 5.3) — optional
        5. Event created with file metadata
        6. Event published to NATS/webhook (Stories 5.5/5.7)
        7. RAG pipeline consumes event and processes file
    
    Schema Version: 1.0
    Subject Name: upload.file.load_completed
    
    Attributes:
        event_version: Schema version string (always "1.0" for v1)
        event_type: Event type identifier (always "FILE_LOAD_COMPLETED")
        timestamp: Event creation timestamp (UTC, ISO 8601)
        file_id: Unique file identifier (UUID v4)
        workspace_id: Workspace owning this file (UUID v4)
        s3_path: Full S3 path to assembled file
        sha256_checksum: Full-file SHA-256 hash (64 hex chars)
        size_bytes: Final file size in bytes
        uploaded_at: Upload completion timestamp (UTC, ISO 8601)
    
    Invariants:
        - event_version is always "1.0"
        - event_type is always "FILE_LOAD_COMPLETED"
        - All timestamps are timezone-aware UTC
        - file_id and workspace_id are valid UUIDs
        - s3_path follows pattern: s3://bucket/workspace_{workspace_id}/{file_id}.pdf
        - sha256_checksum is 64-character hex string
        - size_bytes is positive integer
    
    Serialization:
        - to_json() returns JSON string for NATS/webhook publishing
        - to_dict() returns dictionary for programmatic access
        - Timestamps serialize to ISO 8601 format
        - UUIDs serialize to string format
        - SHA256Hash serializes to hex string
    
    Examples:
        >>> from uuid import uuid4
        >>> from datetime import datetime, timezone
        >>> from src.domain.value_objects import SHA256Hash
        >>>
        >>> # Create event after successful upload
        >>> event = FileLoadCompletedEvent(
        ...     file_id=uuid4(),
        ...     workspace_id=uuid4(),
        ...     s3_path="s3://rag-uploads/workspace_abc123/file_xyz789.pdf",
        ...     sha256_checksum=SHA256Hash("a" * 64),
        ...     size_bytes=1048576,
        ...     uploaded_at=datetime.now(timezone.utc)
        ... )
        >>>
        >>> # Serialize for publishing
        >>> json_str = event.to_json()
        >>> print(json_str)
        {
            "event_version": "1.0",
            "event_type": "FILE_LOAD_COMPLETED",
            "timestamp": "2026-05-06T15:30:00Z",
            "payload": {...}
        }
        >>>
        >>> # Get NATS subject name
        >>> print(event.subject_name)
        "upload.file.load_completed"
    """
    
    # Envelope fields (metadata)
    event_version: str = "1.0"
    event_type: str = "FILE_LOAD_COMPLETED"
    timestamp: datetime = None  # Auto-set in __post_init__ if None
    
    # Payload fields (file metadata)
    file_id: UUID
    workspace_id: UUID
    s3_path: str
    sha256_checksum: SHA256Hash
    size_bytes: int
    uploaded_at: datetime
    
    def __post_init__(self):
        """Validate invariants after initialization."""
        # Auto-set timestamp if not provided
        if self.timestamp is None:
            object.__setattr__(self, 'timestamp', datetime.now(timezone.utc))
        
        # Validate event_version
        if self.event_version != "1.0":
            raise ValueError("event_version must be '1.0' for v1 events")
        
        # Validate event_type
        if self.event_type != "FILE_LOAD_COMPLETED":
            raise ValueError("event_type must be 'FILE_LOAD_COMPLETED'")
        
        # Validate UUIDs
        if not isinstance(self.file_id, UUID):
            raise TypeError("file_id must be UUID")
        if not isinstance(self.workspace_id, UUID):
            raise TypeError("workspace_id must be UUID")
        
        # Validate timestamps are timezone-aware
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        if self.uploaded_at.tzinfo is None:
            raise ValueError("uploaded_at must be timezone-aware")
        
        # Validate size_bytes is positive
        if self.size_bytes <= 0:
            raise ValueError("size_bytes must be positive")
        
        # Validate s3_path pattern (workspace isolation)
        if not self.s3_path.startswith("s3://"):
            raise ValueError("s3_path must start with 's3://'")
        if f"workspace_{self.workspace_id}" not in self.s3_path:
            raise ValueError(
                f"s3_path must contain workspace prefix: workspace_{self.workspace_id}"
            )
    
    @property
    def subject_name(self) -> str:
        """Return NATS subject name for this event.
        
        Subject: upload.file.load_completed
        
        Follows NATS hierarchical naming convention:
        - Namespace: upload (service domain)
        - Resource: file (resource type)
        - Action: load_completed (lifecycle event)
        """
        return "upload.file.load_completed"
    
    def to_dict(self) -> dict:
        """Convert event to dictionary representation.
        
        Returns dictionary with envelope fields and nested payload.
        Timestamps converted to ISO 8601 strings.
        UUIDs converted to string format.
        SHA256Hash converted to hex string.
        """
        return {
            "event_version": self.event_version,
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat(),
            "payload": {
                "file_id": str(self.file_id),
                "workspace_id": str(self.workspace_id),
                "s3_path": self.s3_path,
                "sha256_checksum": str(self.sha256_checksum),
                "size_bytes": self.size_bytes,
                "uploaded_at": self.uploaded_at.isoformat()
            }
        }
    
    def to_json(self) -> str:
        """Serialize event to JSON string for NATS/webhook publishing.
        
        Returns compact JSON (no indentation) with ISO 8601 timestamps.
        """
        return json.dumps(self.to_dict())
```

**Protocol Implementation Pattern:**
```python
# Domain Layer (src/domain/protocols/event_publisher.py)
from typing import Protocol

from src.domain.entities.events import FileLoadCompletedEvent


class IEventPublisher(Protocol):
    """Protocol for event publishing to NATS or webhooks.
    
    Defines the contract for publishing FILE_LOAD_COMPLETED events
    to downstream RAG pipeline consumers. Implementations must handle
    serialization, transport-specific details, and error recovery.
    
    All methods are async to support non-blocking I/O operations with
    external message brokers (NATS JetStream) or HTTP webhooks.
    
    Event Publishing Flow:
        1. CompleteUploadUseCase creates FileLoadCompletedEvent
        2. Use case calls event_publisher.publish(event)
        3. Publisher serializes event to JSON
        4. Publisher sends to NATS subject or webhook URL
        5. Publisher handles retries and errors per NFR-R4
    
    Retry and Error Handling:
        Implementations MUST implement retry logic for transient failures:
        - Quick retries: 3 attempts with exponential backoff (1s, 2s)
        - Dead letter queue: If quick retries fail, push to Redis DLQ
        - Background worker: Retry from DLQ with exponential backoff
        - Max retries: 5-10 attempts before marking as failed
        - At-least-once delivery: Events eventually reach consumers
    
    Error Types:
        - InfrastructureError: NATS connection failure, webhook timeout
        - SerializationError: Event serialization failure (should never happen)
        - ValueError: Invalid event (missing fields, validation failure)
    
    NATS Implementation (Story 5.5):
        - Connect to NATS JetStream server
        - Create/use durable stream for upload events
        - Publish to subject: upload.file.load_completed
        - Wait for JetStream ack to confirm persistence
        - Implement retry logic per architecture.md
    
    Webhook Implementation (Story 5.7):
        - POST event JSON to configured webhook URL
        - Include X-Webhook-Signature header (HMAC-SHA256)
        - Timeout: 10 seconds (configurable)
        - Implement retry logic per architecture.md
    
    Examples:
        >>> # NATS implementation (Story 5.5)
        >>> nats_publisher = NATSEventPublisher(settings)
        >>> await nats_publisher.publish(event)
        >>>
        >>> # Webhook implementation (Story 5.7)
        >>> webhook_publisher = WebhookEventPublisher(settings)
        >>> await webhook_publisher.publish(event)
    """
    
    async def publish(self, event: FileLoadCompletedEvent) -> None:
        """Publish FILE_LOAD_COMPLETED event to downstream consumers.
        
        Args:
            event: FileLoadCompletedEvent to publish
        
        Raises:
            InfrastructureError: If NATS/webhook unavailable after retries
            SerializationError: If event serialization fails
            ValueError: If event validation fails
        
        Implementation Notes:
            - Serialize event using event.to_json()
            - Use event.subject_name for NATS subject
            - Implement retry logic per architecture.md
            - On failure after retries, push to DLQ
            - Log all publish attempts with event metadata
        """
        ...
```

### Why This Is Critical

This story enables:
- **Stable API Contract (FR19)**: Versioned event schema provides stable contract for downstream consumers
- **Event-Driven Architecture**: Decouples upload service from RAG pipeline via events
- **Schema Evolution**: Versioned envelope enables future schema changes without breaking consumers
- **NATS/Webhook Publishing (FR20-FR21)**: Event entities ready for NATS JetStream and webhook publishing
- **At-Least-Once Delivery (NFR-R4)**: Protocol defines retry expectations for reliable delivery
- **Testability**: Pure domain entities enable unit testing without infrastructure dependencies

**User Experience Impact:**
- **Before this story**: No event schema defined → downstream consumers have no contract
- **After this story**: FILE_LOAD_COMPLETED event schema established → downstream RAG pipeline can consume events

**Without this story:**
- **No contract boundary** — upload service and RAG pipeline tightly coupled
- **Failed FR19 requirement** — "publish FILE_LOAD_COMPLETED events to NATS"
- **No schema versioning** — future changes would break downstream consumers
- **No testability** — cannot unit test event creation/serialization

### Relationship to Previous Stories

**Story 3.1 (Upload Session Domain Entities)**: Established domain entity patterns
- Created UploadSession entity with dataclass pattern
- **Story 5.4 follows** same pattern for FileLoadCompletedEvent entity
- Both use frozen=True for immutability (sessions are mutable, events are immutable)

**Story 5.1 (Workspace-Scoped File Deduplication)**: Established workspace isolation
- Created workspace-scoped Redis keys: `dedup:workspace_{workspace_id}`
- **Story 5.4 validates** workspace isolation in s3_path: `workspace_{workspace_id}/{file_id}.pdf`
- Both enforce multi-tenancy isolation at every layer

**Story 5.2 (MinIO/S3 File Assembly)**: Provides file metadata for events
- S3StorageClient assembles file and returns (s3_path, final_size)
- **Story 5.4 event** includes s3_path, size_bytes from assembly result
- Event payload includes all metadata needed by downstream RAG pipeline

**Integration with Future Epic 5 Stories:**

**Story 5.5 (Implement NATS JetStream Publisher)**: Will implement IEventPublisher for NATS
- NATSEventPublisher implements IEventPublisher protocol (THIS STORY)
- Publishes to NATS subject: event.subject_name ("upload.file.load_completed")
- Serializes event using event.to_json() method (THIS STORY)
- **Sequence**: Create event (5.4) → **Publish to NATS (5.5)** → RAG pipeline consumes

**Story 5.6 (Implement Event Retry Logic with DLQ)**: Will implement retry strategy
- Retry logic for failed event publications
- Dead letter queue (DLQ) for prolonged failures
- **Uses IEventPublisher protocol** defined in this story
- Exponential backoff retry per architecture.md

**Story 5.7 (Implement Webhook Callback Alternative)**: Will implement IEventPublisher for webhooks
- WebhookEventPublisher implements IEventPublisher protocol (THIS STORY)
- POSTs event.to_json() to configured webhook URL (THIS STORY)
- Includes X-Webhook-Signature header (HMAC-SHA256)
- **Alternative to NATS** — same event entity, different transport

**Story 5.8 (Orchestrate Complete Upload Use Case)**: Will orchestrate event creation/publishing
- CompleteUploadUseCase coordinates all Epic 5 stories
- **Creates FileLoadCompletedEvent** after successful assembly/scan (THIS STORY)
- **Calls event_publisher.publish(event)** using IEventPublisher (THIS STORY)
- **Sequence**:
  1. Assemble file on S3 (Story 5.2) → returns (s3_path, size_bytes)
  2. Check for duplicate (Story 5.1)
  3. Scan for virus (Story 5.3) — OPTIONAL
  4. **Create FileLoadCompletedEvent** ← THIS STORY (5.4)
  5. **Publish event** ← THIS STORY (5.4 protocol)
  6. Register fingerprint (Story 5.1)

**Story 6.1 (Prometheus Metrics)**: Will track event publishing metrics
- Metric: `events_published_total` (counter, labels: event_type, workspace_id, status)
- Metric: `event_publish_duration_seconds` (histogram, labels: event_type)
- IEventPublisher implementations instrument metrics

**Story 6.2 (Structured Logging)**: Will log event publishing operations
- Log event creation: file_id, workspace_id, s3_path
- Log publish attempts: event_type, subject_name, retry_count
- IEventPublisher implementations add structured logging

### Integration Points

**Depends On (Must Exist):**
- `src/domain/value_objects/sha256_hash.py` (Story 3.1) - SHA256Hash value object for checksum
- `src/domain/exceptions.py` (Story 3.1) - InfrastructureError, SerializationError base classes
- Python standard library: `dataclasses`, `datetime`, `uuid`, `json`

**Used By (Future Stories):**
- **Story 5.5 (NATS JetStream Publisher)**: Implements IEventPublisher for NATS
- **Story 5.6 (Event Retry Logic with DLQ)**: Uses IEventPublisher for retry strategy
- **Story 5.7 (Webhook Callback Alternative)**: Implements IEventPublisher for webhooks
- **Story 5.8 (Complete Upload Use Case)**: Creates FileLoadCompletedEvent and publishes via IEventPublisher
- **Story 6.1 (Prometheus Metrics)**: Instruments event publishing with metrics
- **Story 6.2 (Structured Logging)**: Logs event creation and publishing operations

### Testing Strategy

**Unit Tests (tests/unit/domain/entities/test_events.py):**
- Test FileLoadCompletedEvent creation with all valid fields
- Test validation: timezone-aware timestamps required
- Test validation: UUIDs for file_id and workspace_id
- Test validation: positive size_bytes
- Test validation: s3_path follows workspace isolation pattern
- Test to_dict() returns correct dictionary structure
- Test to_json() produces valid JSON with all fields
- Test subject_name property returns correct NATS subject
- Test event_version is "1.0"
- Test event_type is "FILE_LOAD_COMPLETED"
- Test ISO 8601 timestamp formatting
- Test SHA256Hash serialization in JSON

**Protocol Tests (tests/unit/domain/protocols/test_event_publisher.py):**
- Test IEventPublisher protocol contract
- Test protocol can be satisfied by mock implementations
- Test publish() method signature matches expectations

**Integration Tests (Deferred to Stories 5.5/5.7):**
- End-to-end NATS publishing (Story 5.5)
- End-to-end webhook publishing (Story 5.7)
- Retry and DLQ integration (Story 5.6)

### Architecture Compliance

**Clean Architecture Enforcement:**
- Domain layer defines entities and protocols (THIS STORY)
- Infrastructure layer implements protocols (Stories 5.5, 5.7)
- Application layer orchestrates use cases (Story 5.8)
- NO infrastructure dependencies in domain layer

**Dependency Flow:**
```
Domain Layer (THIS STORY):
├── FileLoadCompletedEvent (entity)
└── IEventPublisher (protocol)

Infrastructure Layer (Stories 5.5, 5.7):
├── NATSEventPublisher (implements IEventPublisher)
└── WebhookEventPublisher (implements IEventPublisher)

Application Layer (Story 5.8):
└── CompleteUploadUseCase (uses IEventPublisher)
```

**Type Safety:**
- All fields fully typed with Python 3.13+ type hints
- Use `mypy --strict` mode for validation
- Pydantic-style validation in `__post_init__`

**Immutability:**
- Events are immutable (`frozen=True`) — once created, never modified
- Events represent historical facts — "file was uploaded at time T"

### Critical Implementation Notes

**DO NOT:**
- ❌ Add infrastructure dependencies (redis, nats, httpx) to domain layer
- ❌ Implement event publishing in this story (that's Stories 5.5, 5.7)
- ❌ Create API endpoints (that's Story 5.8)
- ❌ Add mutable fields to FileLoadCompletedEvent (events are immutable facts)
- ❌ Skip validation in `__post_init__` (prevent invalid events)
- ❌ Use dict instead of dataclass (type safety, IDE support)

**DO:**
- ✅ Use dataclass with `frozen=True` for immutability
- ✅ Validate all fields in `__post_init__`
- ✅ Use existing value objects (SHA256Hash) from domain layer
- ✅ Follow existing entity patterns (UploadSession)
- ✅ Write comprehensive unit tests for all validation paths
- ✅ Document event schema as stable API contract
- ✅ Use Protocol for IEventPublisher (structural subtyping)
- ✅ Add detailed docstrings explaining versioning and evolution

**Event Versioning Best Practices:**
- **event_version field** enables schema evolution
- **v1.0 is immutable** — once published, never change v1.0 fields
- **v1.1 adds optional fields** — consumers ignore unknown fields
- **v2.0 breaks compatibility** — renamed/removed fields require major version
- **Document all versions** — consumers rely on stable contract

**NATS Subject Naming Best Practices:**
- Use **dotted hierarchical naming**: `upload.file.load_completed`
- Enables **wildcard subscriptions**: `upload.>` (all upload events)
- Use **lowercase with underscores**: `load_completed` (not `loadCompleted`)
- Use **past tense**: `load_completed` (not `load_complete` or `loading`)

### Files to Create

```
src/domain/entities/events.py          # FileLoadCompletedEvent entity
src/domain/protocols/event_publisher.py  # IEventPublisher protocol
tests/unit/domain/entities/test_events.py  # Event entity tests
tests/unit/domain/protocols/test_event_publisher.py  # Protocol tests
```

### Files to Update

```
src/domain/entities/__init__.py        # Export FileLoadCompletedEvent
src/domain/protocols/__init__.py       # Export IEventPublisher
```

### References

- [Architecture: Event Publishing & Pipeline Integration](artifacts/planning-artifacts/architecture.md#Event-Publishing--Pipeline-Integration)
- [Architecture: Event Schema Versioning](artifacts/planning-artifacts/architecture.md#Event-Schema-Versioning)
- [Architecture: Data Architecture](artifacts/planning-artifacts/architecture.md#Data-Architecture)
- [Epic 5: File Assembly, Integrity & Pipeline Integration](artifacts/planning-artifacts/epics.md#Epic-5-File-Assembly-Integrity--Pipeline-Integration)
- [Story 5.1: Workspace-Scoped File Deduplication](artifacts/implementation-artifacts/5-1-implement-workspace-scoped-file-deduplication.md)
- [Story 5.2: MinIO/S3 File Assembly with Storage Isolation](artifacts/implementation-artifacts/5-2-implement-minio-s3-file-assembly-with-storage-isolation.md)
- [Story 3.1: Upload Session Domain Entities](artifacts/implementation-artifacts/3-1-create-upload-session-domain-entities-and-value-objects.md)

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.5 (Copilot)

### Debug Log References

None yet.

### Completion Notes List

✅ **Story 5.4 Implementation Complete** (Date: 2026-05-06)

**Implemented Components:**
1. **FileLoadCompletedEvent entity** - Immutable frozen dataclass with comprehensive validation
   - Versioned schema (v1.0) with envelope pattern for future evolution
   - Auto-set timestamp with timezone validation
   - Workspace isolation validation in s3_path
   - JSON serialization via to_json() and to_dict() methods
   - NATS subject name property: "upload.file.load_completed"

2. **IEventPublisher protocol** - Abstract interface for event publishing
   - Protocol-based design (structural subtyping)
   - Async publish() method signature
   - Comprehensive docstring with retry/error handling guidelines
   - Documents NATS and webhook implementation expectations

**Test Coverage:**
- 23 unit tests for FileLoadCompletedEvent (creation, validation, serialization, immutability)
- 4 unit tests for IEventPublisher protocol (contract verification)
- All 444 unit tests pass (no regressions)

**Code Quality:**
- Ruff linting: ✅ All checks passed
- Mypy type checking: ✅ No issues found
- Followed existing patterns from UploadSession and SHA256Hash entities

**Files Modified:**
- Created: src/domain/entities/events.py (210 lines)
- Created: src/domain/protocols/event_publisher.py (95 lines)
- Created: tests/unit/domain/entities/test_events.py (540 lines)
- Created: tests/unit/domain/protocols/test_event_publisher.py (70 lines)
- Updated: src/domain/entities/__init__.py (added FileLoadCompletedEvent export)
- Updated: src/domain/protocols/__init__.py (added IEventPublisher export)

**Acceptance Criteria Verification:**
- ✅ AC#1: FileLoadCompletedEvent entity created in src/domain/entities/events.py
- ✅ AC#2: Event includes event_version ("1.0"), event_type ("FILE_LOAD_COMPLETED"), timestamp (ISO 8601)
- ✅ AC#3: Event payload includes all required fields (file_id, workspace_id, s3_path, sha256_checksum, size_bytes, uploaded_at)
- ✅ AC#4: NATS subject naming convention documented: upload.file.load_completed
- ✅ AC#5: Event schema fully documented as stable API contract with versioning guidance
- ✅ AC#6: Event serializes to JSON via to_json() method
- ✅ AC#7: IEventPublisher protocol defined in src/domain/protocols/event_publisher.py

**Technical Decisions:**
1. Used dataclass(frozen=True) for immutability - events are historical facts
2. Auto-set timestamp in __post_init__ if None for convenience
3. Comprehensive validation in __post_init__ to prevent invalid events
4. Used Protocol for IEventPublisher (structural subtyping, more flexible)
5. Added type hints with Any import for mypy strict mode compliance

**Next Stories:**
- Story 5.5: Implement NATS JetStream publisher (implements IEventPublisher)
- Story 5.7: Implement webhook publisher (implements IEventPublisher)
- Story 5.8: Orchestrate complete upload use case (creates and publishes events)

### File List

Files created:
- src/domain/entities/events.py
- src/domain/protocols/event_publisher.py
- tests/unit/domain/entities/test_events.py
- tests/unit/domain/protocols/test_event_publisher.py

Files modified:
- src/domain/entities/__init__.py
- src/domain/protocols/__init__.py

### Review Findings

**Decision-Needed (2 findings - RESOLVED):**

- [x] [Review][Decision] **file_id not verified in s3_path** — RESOLVED: Add validation to enforce file_id appears in s3_path. Converted to patch finding.

- [x] [Review][Decision] **SHA256Hash string conversion format** — RESOLVED: Add format validation (64-char hex) for defense in depth. Converted to patch finding.

**Patch Findings (13 findings - ALL FIXED):**

- [x] [Review][Patch] **file_id not verified in s3_path** [src/domain/entities/events.py:176-179] — FIXED: Added validation that str(file_id) appears in s3_path to enforce pattern consistency.

- [x] [Review][Patch] **SHA256Hash string format validation** [src/domain/entities/events.py:154-158] — FIXED: Added regex validation that str(sha256_checksum) matches 64-char lowercase hex pattern.

- [x] [Review][Patch] **s3_path workspace isolation validation too weak** [src/domain/entities/events.py:171-174] — FIXED: Changed validation to check for path segment /workspace_{workspace_id}/ instead of substring.

- [x] [Review][Patch] **s3_path is None check missing** [src/domain/entities/events.py:161-162] — FIXED: Added None check before .startswith() with clear ValueError.

- [x] [Review][Patch] **file_id or workspace_id nil UUID check missing** [src/domain/entities/events.py:135-140] — FIXED: Added explicit nil UUID (00000000-0000-0000-0000-000000000000) validation.

- [x] [Review][Patch] **size_bytes exceeds safe JSON integer range** [src/domain/entities/events.py:147-151] — FIXED: Added upper bound check for 2^53-1 (9007199254740991) to prevent precision loss in JavaScript consumers.

- [x] [Review][Patch] **to_json() unhandled exceptions** [src/domain/entities/events.py:242-249] — FIXED: Wrapped json.dumps() in try/except and raise SerializationError on failure.

- [x] [Review][Patch] **Type hint inconsistency for timestamp** [src/domain/entities/events.py:106] — FIXED: Changed from datetime | None to datetime with field(default_factory=lambda: datetime.now(UTC)).

- [x] [Review][Patch] **Frozen dataclass anti-pattern** [src/domain/entities/events.py:106] — FIXED: Removed object.__setattr__() pattern, now using field(default_factory) for clean initialization.

- [x] [Review][Patch] **No temporal consistency validation** [src/domain/entities/events.py:182-185] — FIXED: Added validation that uploaded_at <= timestamp (checked last so other validations fail first).

- [x] [Review][Patch] **Protocol lacks runtime_checkable decorator** [src/domain/protocols/event_publisher.py:14] — FIXED: Added @runtime_checkable decorator to IEventPublisher.

- [x] [Review][Patch] **Missing UTC normalization** [src/domain/entities/events.py:217-218] — FIXED: Added .astimezone(UTC) calls to normalize timestamps before serialization.

- [x] [Review][Patch] **Test gap: s3_path pattern validation** [tests/unit/domain/entities/test_events.py] — FIXED: Added 8 new test cases for malformed paths (embedded workspace_id, missing separators, file_id mismatch, nil UUIDs, size bounds, temporal consistency, SHA256 format).

- [ ] [Review][Patch] **s3_path workspace isolation validation too weak** [src/domain/entities/events.py:149-153] — Validation only checks substring presence (workspace_{workspace_id} anywhere in path), allows malformed paths like s3://bucket/prefix_workspace_abc_suffix/file.pdf. Fix: Change to validate path segment: f"/workspace_{self.workspace_id}/" in self.s3_path. Found by: Blind Hunter + Edge Case Hunter + Acceptance Auditor

- [ ] [Review][Patch] **s3_path is None check missing** [src/domain/entities/events.py:145] — No None check before .startswith() causes AttributeError instead of clear ValueError. Add: if self.s3_path is None: raise ValueError('s3_path cannot be None'). Found by: Edge Case Hunter

- [ ] [Review][Patch] **file_id or workspace_id nil UUID check missing** [src/domain/entities/events.py:131-134] — Nil UUIDs (00000000-0000-0000-0000-000000000000) pass validation but represent invalid business state. Add explicit nil UUID check and raise ValueError. Found by: Edge Case Hunter

- [ ] [Review][Patch] **size_bytes exceeds safe JSON integer range** [src/domain/entities/events.py:141-142] — Values > 2^53-1 (9007199254740991) cause precision loss in JavaScript consumers. Add upper bound check: if self.size_bytes > 9007199254740991: raise ValueError. Found by: Edge Case Hunter

- [ ] [Review][Patch] **to_json() unhandled exceptions** [src/domain/entities/events.py:201] — Generic exceptions instead of domain-specific SerializationError per IEventPublisher contract. Wrap json.dumps() in try/except and raise SerializationError on failure. Found by: Edge Case Hunter

- [ ] [Review][Patch] **Type hint inconsistency for timestamp** [src/domain/entities/events.py:107] — timestamp typed as datetime | None but never None after __post_init__. Change to datetime and use field(default_factory=lambda: datetime.now(UTC)) instead. Found by: Blind Hunter

- [ ] [Review][Patch] **Frozen dataclass anti-pattern** [src/domain/entities/events.py:118-119] — Using object.__setattr__() to mutate frozen dataclass. Use field(default_factory=lambda: datetime.now(UTC)) for cleaner initialization. Found by: Blind Hunter

- [ ] [Review][Patch] **No temporal consistency validation** [src/domain/entities/events.py:__post_init__] — Doesn't validate uploaded_at <= timestamp. Could create events where files are "uploaded" after event creation. Add validation after timestamp is set. Found by: Blind Hunter

- [ ] [Review][Patch] **Protocol lacks runtime_checkable decorator** [src/domain/protocols/event_publisher.py:14] — IEventPublisher cannot be used with isinstance() checks. Add @runtime_checkable decorator. Found by: Blind Hunter

- [ ] [Review][Patch] **Missing UTC normalization** [src/domain/entities/events.py:to_dict] — Accepts any timezone-aware datetime but doesn't normalize to UTC before serialization. Convert timestamps to UTC in isoformat() calls. Found by: Blind Hunter

- [ ] [Review][Patch] **Test gap: s3_path pattern validation** [tests/unit/domain/entities/test_events.py] — Missing edge case tests for malformed workspace prefixes (embedded in longer strings, wrong separators, etc.). Add test cases. Found by: Acceptance Auditor

**Deferred (3 findings):**

- [x] [Review][Defer] **Missing event deduplication field** — No event_id for at-least-once delivery deduplication. Deferred: Story 5.6 (Event Retry Logic) will handle deduplication strategy, not in scope for basic event schema.

- [x] [Review][Defer] **Hardcoded subject name prevents environment routing** — Cannot distinguish dev/staging/prod environments. Deferred: Environment-specific routing not a requirement; NATS configuration (Story 5.5) handles environment separation, not event schema.

- [x] [Review][Defer] **Overly strict version validation** — Rejects "1.1" but docs mention v1.1 evolution. Deferred: v1.1 doesn't exist yet, validation can be updated when needed (YAGNI principle).
