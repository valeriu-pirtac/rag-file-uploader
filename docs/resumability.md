# Upload Resumability Guide

## Overview

This service implements **resumable uploads** following the [tus protocol v1.0.0](https://tus.io/protocols/resumable-upload) specification. This allows clients to resume interrupted uploads from the exact byte offset without re-uploading previously verified chunks.

## Why Resumability Matters

**User Experience Benefits:**
- **Network Resilience**: Uploads survive network interruptions, browser closes, and system restarts
- **Time Savings**: Resume from where you left off, not from the beginning
- **Cost Efficiency**: No need to re-upload gigabytes of data after minor interruptions
- **Mobile Friendly**: Essential for uploads on unstable mobile networks

**Technical Benefits:**
- **Bandwidth Optimization**: Only upload new data, not previously verified chunks
- **Server Efficiency**: Stateless resume via session ID (no server-side session memory)
- **Data Integrity**: Each chunk independently verified via SHA-256 before state updates
- **Fault Tolerance**: Session state persists in Redis across service restarts

## How Resume Works

### Standard Upload Flow

```
1. Client: POST /v1/uploads
   → Create session (session_id returned)

2. Client: PATCH /v1/uploads/{id} + chunk 0 (5 MB)
   → Server verifies SHA-256, updates offset to 5 MB

3. Client: PATCH /v1/uploads/{id} + chunk 1 (5 MB)
   → Server verifies SHA-256, updates offset to 10 MB

4. ... (continue until all chunks uploaded)

5. Client: POST /v1/uploads/{id}/complete
   → Server assembles file, publishes event, marks complete
```

### Resume After Interruption

```
1. Client uploads chunks 0-41 successfully
   → Session offset: 220,200,960 bytes (42 chunks × 5 MB)

2. ⚡ Network interruption (browser close, connection drop, etc.)

3. Client resumes:
   a. HEAD /v1/uploads/{id}
      → Response: Upload-Offset: 220200960
      → Response: Upload-Length: 1073741824 (total size)

   b. Client calculates next chunk: offset ÷ chunk_size = 42

   c. PATCH /v1/uploads/{id} + chunk 42 (5 MB)
      → Request: Upload-Offset: 220200960 (MUST match server)
      → Server validates offset, verifies chunk, updates to 225,443,840

   d. Continue uploading chunks 43-199 until complete
```

## API Usage

### Query Current Offset (HEAD)

**Request:**
```http
HEAD /v1/uploads/{session_id} HTTP/1.1
Host: api.example.com
Authorization: Bearer <jwt_token>
```

**Response:**
```http
HTTP/1.1 204 No Content
Upload-Offset: 220200960
Upload-Length: 1073741824
Upload-Expires: Wed, 25 Jun 2025 18:00:00 GMT
Cache-Control: no-store
```

**Response Headers:**
- `Upload-Offset`: Current verified byte offset (how much uploaded)
- `Upload-Length`: Total file size in bytes
- `Upload-Expires`: When session expires (24 hours after creation)

### Resume Upload (PATCH)

**Request:**
```http
PATCH /v1/uploads/{session_id} HTTP/1.1
Host: api.example.com
Authorization: Bearer <jwt_token>
Content-Type: application/offset+octet-stream
Upload-Offset: 220200960
Upload-Checksum: sha256 a948904f2f0f479b8f8197694b30184b0d2ed1c1cd2a1ec0fb85d299a192a447
Content-Length: 5242880

<5 MB binary chunk data>
```

**Critical Request Headers:**
- `Upload-Offset`: **MUST** match current session offset exactly
- `Upload-Checksum`: SHA-256 hash of chunk data (for integrity)
- `Content-Length`: Chunk size in bytes (≤10 MB)

**Success Response:**
```http
HTTP/1.1 204 No Content
Upload-Offset: 225443840
```

**Updated offset returned** (220200960 + 5242880 = 225443840)

## Error Scenarios

### Offset Mismatch (409 Conflict)

**Scenario:** Client sends wrong offset (out of sync with server)

**Request:**
```http
PATCH /v1/uploads/{session_id}
Upload-Offset: 0
```

**Response:**
```http
HTTP/1.1 409 Conflict
Content-Type: application/json

{
  "error": "OFFSET_MISMATCH",
  "message": "Upload offset mismatch: expected 220200960, received 0",
  "details": {
    "expected_offset": 220200960,
    "received_offset": 0,
    "suggestion": "Query HEAD /v1/uploads/{id} to get current offset before retrying"
  }
}
```

**Client Action:** Query HEAD to get correct offset, then retry

### Session Expired (404 Not Found)

**Scenario:** Attempting to resume after 24-hour TTL expiry

**Response:**
```http
HTTP/1.1 404 Not Found
Content-Type: application/json

{
  "error": "SESSION_EXPIRED",
  "message": "Session expired at 2025-06-24T18:00:00Z (24 hours after creation)",
  "details": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "created_at": "2025-06-23T18:00:00Z",
    "expires_at": "2025-06-24T18:00:00Z",
    "suggestion": "Create a new upload session with POST /v1/uploads"
  }
}
```

**Client Action:** Start fresh upload with new session

## Client Implementation Guide

### Pseudocode

```typescript
async function uploadFileWithResume(file: File, sessionId?: string) {
  const CHUNK_SIZE = 5 * 1024 * 1024; // 5 MB
  const MAX_RETRIES = 5; // Maximum retry attempts per chunk
  let retryDelay = 1000; // Initial retry delay: 1 second
  
  // Step 1: Create or resume session
  if (!sessionId) {
    // Create new session
    const response = await fetch('/v1/uploads', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${jwt}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        filename: file.name,
        size: file.size,
        mime_type: file.type,
        sha256_checksum: await computeFileSHA256(file)
      })
    });
    sessionId = response.json().session_id;
  }
  
  // Step 2: Query current offset (resume point)
  const headResponse = await fetch(`/v1/uploads/${sessionId}`, {
    method: 'HEAD',
    headers: { 'Authorization': `Bearer ${jwt}` }
  });
  
  const currentOffset = parseInt(headResponse.headers.get('Upload-Offset'));
  const totalSize = parseInt(headResponse.headers.get('Upload-Length'));
  
  console.log(`Resuming from ${currentOffset} / ${totalSize} bytes`);
  
  // Step 3: Upload remaining chunks
  let offset = currentOffset;
  let retryCount = 0;
  
  while (offset < file.size) {
    const chunkEnd = Math.min(offset + CHUNK_SIZE, file.size);
    const chunk = file.slice(offset, chunkEnd);
    const chunkChecksum = await computeChunkSHA256(chunk);
    
    try {
      const response = await fetch(`/v1/uploads/${sessionId}`, {
        method: 'PATCH',
        headers: {
          'Authorization': `Bearer ${jwt}`,
          'Content-Type': 'application/offset+octet-stream',
          'Upload-Offset': offset.toString(),
          'Upload-Checksum': `sha256 ${chunkChecksum}`,
          'Content-Length': chunk.size.toString()
        },
        body: chunk
      });
      
      if (response.status === 409) {
        // Offset mismatch - re-query and retry
        const error = await response.json();
        offset = error.details.expected_offset;
        retryCount++;
        if (retryCount >= MAX_RETRIES) {
          throw new Error(`Max retries exceeded for offset ${offset}`);
        }
        await sleep(retryDelay);
        continue; // Retry with correct offset
      }
      
      if (response.status === 429) {
        // Rate limited - exponential backoff
        retryCount++;
        if (retryCount >= MAX_RETRIES) {
          throw new Error('Rate limit exceeded - max retries reached');
        }
        await sleep(retryDelay);
        retryDelay = Math.min(retryDelay * 2, 32000); // Cap at 32 seconds
        continue;
      }
      
      // Success - update offset from response
      offset = parseInt(response.headers.get('Upload-Offset'));
      retryCount = 0; // Reset retry counter on success
      retryDelay = 1000; // Reset delay
      
      // Update progress UI
      updateProgress(offset, totalSize);
      
    } catch (error) {
      // Network error - retry with exponential backoff
      retryCount++;
      if (retryCount >= MAX_RETRIES) {
        throw new Error(`Network error: ${error.message}`);
      }
      await sleep(retryDelay);
      retryDelay = Math.min(retryDelay * 2, 32000); // Cap at 32 seconds
      continue;
    }
  }
  
  // Step 4: Mark upload complete
  await fetch(`/v1/uploads/${sessionId}/complete`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${jwt}` }
  });
  
  console.log('Upload complete!');
}

// Helper: Compute SHA-256 of entire file
// WARNING: For large files (>100MB), this blocks the UI thread.
// Consider using Web Worker or streaming hash for production.
async function computeFileSHA256(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const hash = await crypto.subtle.digest('SHA-256', buffer);
  return Array.from(new Uint8Array(hash))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
}

// Helper: Compute SHA-256 of chunk
async function computeChunkSHA256(blob: Blob): Promise<string> {
  const buffer = await blob.arrayBuffer();
  const hash = await crypto.subtle.digest('SHA-256', buffer);
  return Array.from(new Uint8Array(hash))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
}
```

### Error Handling Best Practices

1. **Always query HEAD before resuming** - Never assume offset is 0
2. **Handle 409 Conflict gracefully** - Re-query and retry with correct offset
3. **Implement exponential backoff** - For network errors (500, 503)
4. **Respect session expiry** - Start fresh after 24 hours
5. **Validate checksums client-side** - Catch corruption before upload
6. **Store session ID persistently** - In localStorage or IndexedDB for browser restarts

## Server-Side Architecture

### Session State Storage

Sessions are stored in Redis with 24-hour TTL:

```
Key: session:workspace_{workspace_id}:upload_{session_id}
Type: Redis Hash

Fields:
  - session_id: UUID
  - workspace_id: UUID (multi-tenancy isolation)
  - filename: string
  - size: int (total bytes)
  - mime_type: string
  - sha256_checksum: string (file hash for deduplication)
  - offset: int (current verified byte offset)
  - status: PENDING | IN_PROGRESS | COMPLETE | FAILED | ABORTED
  - created_at: ISO 8601 timestamp
  - expires_at: ISO 8601 timestamp (created_at + 24 hours)
  - chunk_manifest: JSON array of verified chunks
    [
      {"index": 0, "size": 5242880, "checksum": "abc123..."},
      {"index": 1, "size": 5242880, "checksum": "def456..."},
      ...
    ]
```

### Chunk Manifest

The `chunk_manifest` provides:
- **Resume validation**: Verify chunk continuity (no gaps, sequential indices)
- **Audit trail**: Track which chunks uploaded and when
- **Deduplication**: Prevent re-processing of verified chunks
- **Completion check**: Ensure all chunks present before marking complete

### Offset Validation Logic

```python
# From ProcessChunkUseCase.execute()
if request.chunk_offset != session.offset:
    raise OffsetMismatchError(
        expected_offset=session.offset,
        received_offset=request.chunk_offset,
        session_id=session.session_id,
    )
```

**Why strict validation:**
- **Prevents duplicates**: Client can't re-upload chunk 0 after chunk 10
- **Prevents gaps**: Client can't skip from chunk 5 to chunk 10
- **Enforces synchronization**: Client and server must agree on state
### Rate Limiting

- **Concurrent uploads**: Up to 10 per workspace (configurable)
- **429 Too Many Requests**: Returned when limit exceeded
- **Retry strategy**: Exponential backoff with 32-second cap
- **Time window**: Per-workspace concurrent sessions (not per-second rate)

**Client handling**: See pseudocode example above for 429 retry logic with exponential backoff.
## Performance Characteristics

### Latency

- **HEAD query**: <50ms (NFR-P2) - Redis HGETALL is fast
- **PATCH processing**: <100ms per 5MB chunk (NFR-P3)
  - Session retrieval: ~5ms
  - SHA-256 verification: ~50ms (hardware-accelerated)
  - Session update: ~5ms

### Throughput

- **Concurrent uploads**: Up to 10 per workspace (configurable rate limit)
- **Chunk size**: 5 MB standard, 10 MB maximum
- **File size**: Up to 1 GB (enforced limit)

### Durability

- **Redis persistence**: AOF (Append-Only File) + RDB snapshots
- **Session survives**: Service restarts, Redis failovers (with replication)
- **Session expires**: After 24 hours (automatic cleanup)

## Security Considerations

### Authentication

- **JWT required**: All requests require valid JWT token
- **Workspace isolation**: Cannot resume session from different workspace
- **Role-based access**: OWNER or COLLABORATOR role required

### Data Integrity

- **SHA-256 verification**: Every chunk verified before updating state
- **Checksum header**: `Upload-Checksum` header mandatory (enforced)
- **Offset validation**: Strict offset matching prevents data corruption

### Attack Prevention

- **Rate limiting**: 10 concurrent uploads per workspace (DoS prevention)
- **Size limits**: 1 GB file max, 10 MB chunk max (resource exhaustion)
- **TTL enforcement**: 24-hour session expiry (storage management)

## Testing

Comprehensive integration tests validate all resume scenarios:

- ✅ HEAD returns correct offset after partial upload
- ✅ PATCH continues upload seamlessly from current offset
- ✅ Chunk manifest shows continuity (sequential indices, no gaps)
- ✅ Offset mismatch returns 409 Conflict with expected offset
- ✅ Previously verified chunks are never re-processed
- ✅ Session state persists across service restarts
- ✅ Resume fails gracefully after 24-hour expiry
- ✅ Large file scenario (1 GB = 200 chunks)

**Run tests:**
```bash
uv run pytest tests/integration/test_resume_from_offset.py -v
```

## Troubleshooting

### Common Issues

**Q: Upload keeps returning 409 Conflict**  
A: Client offset out of sync. Query HEAD to get current offset before retrying.

**Q: Session expired but upload wasn't finished**  
A: 24-hour TTL exceeded. Start fresh upload with new session.

**Q: Chunk verification fails (460 Checksum Mismatch)**  
A: Network corruption or client checksum error. Re-upload the failed chunk.

**Q: Resume after browser restart not working**  
A: Session ID not persisted. Store session_id in localStorage or IndexedDB.

## References

- [tus Protocol v1.0.0 Specification](https://tus.io/protocols/resumable-upload)
- [RFC 7231 - HTTP/1.1 Semantics (409 Conflict)](https://tools.ietf.org/html/rfc7231#section-6.5.8)
- [Story 4.1 - Session TTL and Expiry Handling](../artifacts/implementation-artifacts/4-1-implement-session-ttl-and-expiry-handling.md)
- [Story 4.2 - Implement Resume-from-Offset Logic](../artifacts/implementation-artifacts/4-2-implement-resume-from-offset-logic.md)

---

**Last Updated:** 2026-05-06  
**Version:** 1.0  
**Authors:** Development Team
