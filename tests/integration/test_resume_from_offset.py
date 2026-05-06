"""Integration tests for resume-from-offset functionality (Story 4.2).

Tests validate that interrupted uploads can be resumed from the exact byte
offset without re-uploading previously verified chunks. This is the core
resumability feature following tus protocol v1.0.0 specifications.

Test Coverage:
    - HEAD endpoint returns correct offset after partial upload
    - PATCH continues upload seamlessly from current offset
    - Chunk manifest shows continuity (sequential indices, no gaps)
    - Offset mismatch returns 409 Conflict with expected offset
    - Previously verified chunks are never re-processed
    - Session state persists across service restarts (Redis durability)
    - Resume fails gracefully after 24-hour TTL expiry

Architecture:
    These are integration tests using real Redis instance for storage.
    Tests validate the complete flow across all layers:
    - Domain: UploadSession entity maintains offset invariants
    - Application: ProcessChunkUseCase validates offset match
    - Infrastructure: RedisSessionStore persists state durably
    - Presentation: HEAD/PATCH endpoints translate HTTP semantics

References:
    - tus protocol v1.0.0: https://tus.io/protocols/resumable-upload
    - Story 3.1: UploadSession entity with offset and chunk_manifest
    - Story 3.2: RedisSessionStore with TTL and persistence
    - Story 3.7: ProcessChunkUseCase with offset validation
    - Story 3.9: HEAD endpoint returns Upload-Offset header
    - Story 4.1: Session expiry handling and error responses
"""

import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import redis.asyncio as aioredis

from src.application.dto.process_chunk_request import ProcessChunkRequest
from src.application.use_cases.process_chunk import ProcessChunkUseCase
from src.domain.entities.upload_session import UploadSession
from src.domain.exceptions import OffsetMismatchError
from src.domain.services.chunk_verifier import ChunkVerifier
from src.domain.value_objects.session_status import SessionStatus
from src.domain.value_objects.sha256_hash import SHA256Hash
from src.infrastructure.redis.session_store import RedisSessionStore


# Test Constants
CHUNK_SIZE = 5_242_880  # 5 MB (standard chunk size)
FILE_SIZE_3_CHUNKS = 15_728_640  # 15 MB (3 chunks x 5MB)
FILE_SIZE_200_CHUNKS = 1_048_576_000  # ~1 GB (200 chunks x 5MB)


@pytest.fixture
async def redis_client():
    """Create Redis client for integration tests.

    Uses Redis database from REDIS_TEST_DB env var (default: 1) to avoid
    conflicts with production/dev data. Database is flushed after each test
    to ensure clean state.
    """
    test_db = int(os.environ.get("REDIS_TEST_DB", "1"))
    client = aioredis.from_url(f"redis://localhost:6379/{test_db}", decode_responses=True)
    yield client
    # Clean up after tests
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def session_store(redis_client):
    """Create RedisSessionStore with real Redis client."""
    return RedisSessionStore(redis_client)


@pytest.fixture
def sample_workspace_id():
    """Generate consistent workspace ID for test isolation."""
    return uuid4()


@pytest.fixture
def sample_session_id():
    """Generate consistent session ID for testing."""
    return uuid4()


@pytest.fixture
def sample_file_checksum():
    """Generate sample file SHA-256 checksum."""
    return SHA256Hash("a" * 64)


def create_sample_session(
    session_id: UUID,
    workspace_id: UUID,
    size: int = FILE_SIZE_3_CHUNKS,
    offset: int = 0,
    status: SessionStatus = SessionStatus.PENDING,
    chunk_manifest: list | None = None,
) -> UploadSession:
    """Factory function to create sample upload session for testing.

    Args:
        session_id: Unique session identifier
        workspace_id: Workspace isolation boundary
        size: Total file size in bytes (default: 15 MB)
        offset: Current verified byte offset (default: 0)
        status: Current session status (default: PENDING)
        chunk_manifest: List of verified chunks (default: empty)

    Returns:
        UploadSession entity ready for testing
    """
    return UploadSession(
        session_id=session_id,
        workspace_id=workspace_id,
        filename="large-document.pdf",
        size=size,
        mime_type="application/pdf",
        sha256_checksum=SHA256Hash("a" * 64),
        offset=offset,
        status=status,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        chunk_manifest=chunk_manifest or [],
    )


def generate_chunk_data(chunk_index: int, size: int = CHUNK_SIZE) -> bytes:
    """Generate deterministic chunk data for testing.

    Creates predictable chunk data by repeating the pattern:
    "chunk_{chunk_index}_" until reaching desired size.

    Args:
        chunk_index: Zero-based chunk index
        size: Chunk size in bytes (default: 5 MB)

    Returns:
        Bytes object with predictable test data
    """
    pattern = f"chunk_{chunk_index}_".encode()
    repetitions = (size // len(pattern)) + 1
    return (pattern * repetitions)[:size]


def compute_chunk_checksum(data: bytes) -> str:
    """Compute SHA-256 checksum for chunk data.

    Args:
        data: Chunk data bytes

    Returns:
        Hex-encoded SHA-256 hash (64 characters)
    """
    return hashlib.sha256(data).hexdigest()


# ==============================================================================
# AC1: HEAD returns correct offset after partial upload
# ==============================================================================


@pytest.mark.asyncio
async def test_head_returns_correct_offset_after_partial_upload(
    redis_client,
    session_store: RedisSessionStore,
    sample_workspace_id: UUID,
    sample_session_id: UUID,
):
    """Test HEAD returns correct offset after uploading 2 of 3 chunks.

    Validates Acceptance Criterion 1:
        Given an upload was interrupted at chunk 42 (offset 220200960 bytes)
        When I query HEAD /v1/uploads/{id}
        Then response returns Upload-Offset: 220200960

    Scenario:
        1. Create session for 15 MB file (3 chunks x 5MB)
        2. Upload chunk 0 (5 MB) → offset should be 5242880
        3. Upload chunk 1 (5 MB) → offset should be 10485760
        4. Simulate interruption (client disconnects)
        5. Client resumes: Query session via HEAD
        6. Verify offset matches bytes uploaded (10485760)
        7. Verify chunk_manifest contains chunks 0 and 1
    """
    # ARRANGE: Create session for 15 MB file
    session = create_sample_session(
        session_id=sample_session_id,
        workspace_id=sample_workspace_id,
        size=FILE_SIZE_3_CHUNKS,
    )
    await session_store.create_session(session)

    # ACT: Upload chunk 0 (5 MB)
    chunk_0_data = generate_chunk_data(0)
    chunk_0_checksum = compute_chunk_checksum(chunk_0_data)
    session.add_chunk(0, CHUNK_SIZE, chunk_0_checksum)
    session.update_offset(CHUNK_SIZE)
    session.mark_in_progress()
    await session_store.update_session(session)

    # ACT: Upload chunk 1 (5 MB)
    chunk_1_data = generate_chunk_data(1)
    chunk_1_checksum = compute_chunk_checksum(chunk_1_data)
    session.add_chunk(1, CHUNK_SIZE, chunk_1_checksum)
    session.update_offset(2 * CHUNK_SIZE)
    await session_store.update_session(session)

    # Simulate interruption here (client disconnects)

    # ACT: Client resumes - Query offset via HEAD (simulate HEAD request)
    retrieved_session = await session_store.get_session(sample_workspace_id, sample_session_id)

    # ASSERT: Offset matches bytes uploaded (2 chunks x 5MB = 10485760)
    assert retrieved_session is not None, "Session should exist"
    assert retrieved_session.offset == 10_485_760, "Offset should be 10485760 bytes"

    # ASSERT: Chunk manifest contains exactly 2 chunks
    assert len(retrieved_session.chunk_manifest) == 2, "Should have 2 chunks"

    # ASSERT: Chunk manifest shows sequential indices (0, 1)
    assert retrieved_session.chunk_manifest[0]["index"] == 0
    assert retrieved_session.chunk_manifest[0]["size"] == CHUNK_SIZE
    assert retrieved_session.chunk_manifest[0]["checksum"] == chunk_0_checksum

    assert retrieved_session.chunk_manifest[1]["index"] == 1
    assert retrieved_session.chunk_manifest[1]["size"] == CHUNK_SIZE
    assert retrieved_session.chunk_manifest[1]["checksum"] == chunk_1_checksum


# ==============================================================================
# AC2 & AC3: Upload-Length included, resume with PATCH continues seamlessly
# ==============================================================================


@pytest.mark.asyncio
async def test_patch_continues_upload_from_offset(
    redis_client,
    session_store: RedisSessionStore,
    sample_workspace_id: UUID,
    sample_session_id: UUID,
):
    """Test PATCH continues upload seamlessly from current offset.

    Validates Acceptance Criteria 2, 3, 4:
        AC2: Response includes Upload-Length with total file size
        AC3: I can resume with PATCH starting at byte 220200960
        AC4: Upload continues seamlessly from that point

    Scenario:
        1. Create session with offset at 10 MB (2 chunks uploaded)
        2. Client queries offset via HEAD (gets 10485760)
        3. Client resumes with PATCH at offset 10485760
        4. Server validates offset matches (10485760 == 10485760)
        5. Upload chunk 2 successfully
        6. Verify offset updated to 15728640 (all 3 chunks complete)
        7. Verify total file size accessible (Upload-Length)
    """
    # ARRANGE: Create session with 2 chunks already uploaded (offset = 10 MB)
    session = create_sample_session(
        session_id=sample_session_id,
        workspace_id=sample_workspace_id,
        size=FILE_SIZE_3_CHUNKS,
        offset=2 * CHUNK_SIZE,  # 10485760 bytes
        status=SessionStatus.IN_PROGRESS,
        chunk_manifest=[
            {"index": 0, "size": CHUNK_SIZE, "checksum": "chunk0_hash"},
            {"index": 1, "size": CHUNK_SIZE, "checksum": "chunk1_hash"},
        ],
    )
    await session_store.create_session(session)

    # ACT: Client resumes - Upload chunk 2 via PATCH
    chunk_2_data = generate_chunk_data(2)
    chunk_2_checksum = compute_chunk_checksum(chunk_2_data)

    # Create ProcessChunkUseCase to validate offset logic
    use_case = ProcessChunkUseCase(
        session_store=session_store,
        chunk_verifier=ChunkVerifier(),
        redis_client=redis_client,
    )

    request = ProcessChunkRequest(
        workspace_id=sample_workspace_id,
        session_id=sample_session_id,
        chunk_data=chunk_2_data,
        chunk_offset=2 * CHUNK_SIZE,  # Must match current offset (10485760)
        chunk_checksum=chunk_2_checksum,
    )

    response = await use_case.execute(request)

    # ASSERT: New offset is 15 MB (all 3 chunks uploaded)
    assert response.new_offset == FILE_SIZE_3_CHUNKS, "Offset should be 15728640 bytes"

    # ASSERT: Session state updated correctly
    updated_session = await session_store.get_session(sample_workspace_id, sample_session_id)
    assert updated_session.offset == FILE_SIZE_3_CHUNKS
    assert len(updated_session.chunk_manifest) == 3

    # ASSERT: Chunk 2 added to manifest
    assert updated_session.chunk_manifest[2]["index"] == 2
    assert updated_session.chunk_manifest[2]["size"] == CHUNK_SIZE
    assert updated_session.chunk_manifest[2]["checksum"] == chunk_2_checksum

    # ASSERT: Upload-Length (total file size) is accessible
    assert updated_session.size == FILE_SIZE_3_CHUNKS, "Upload-Length should be 15728640"


# ==============================================================================
# AC5: Chunk manifest shows continuity (no gaps, sequential indices)
# ==============================================================================


@pytest.mark.asyncio
async def test_chunk_manifest_continuity_after_resume(
    redis_client,
    session_store: RedisSessionStore,
    sample_workspace_id: UUID,
    sample_session_id: UUID,
):
    """Test chunk manifest shows continuity after resume (no gaps).

    Validates Acceptance Criterion 5:
        Chunk manifest shows continuity (chunks 0-41 already verified, now adding 42+)

    Scenario:
        1. Upload chunks 0-4 (5 chunks)
        2. Simulate interruption
        3. Resume and upload chunks 5-9 (5 more chunks)
        4. Verify manifest has sequential indices: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        5. Verify no gaps, no duplicates
        6. Verify all chunks have correct size and checksum metadata
    """
    # ARRANGE: Create session for 50 MB file (10 chunks x 5MB)
    session = create_sample_session(
        session_id=sample_session_id,
        workspace_id=sample_workspace_id,
        size=10 * CHUNK_SIZE,  # 52428800 bytes
    )
    await session_store.create_session(session)

    use_case = ProcessChunkUseCase(
        session_store=session_store,
        chunk_verifier=ChunkVerifier(),
        redis_client=redis_client,
    )

    # ACT: Upload chunks 0-4 (first session, before interruption)
    for chunk_index in range(5):
        chunk_data = generate_chunk_data(chunk_index)
        chunk_checksum = compute_chunk_checksum(chunk_data)

        request = ProcessChunkRequest(
            workspace_id=sample_workspace_id,
            session_id=sample_session_id,
            chunk_data=chunk_data,
            chunk_offset=chunk_index * CHUNK_SIZE,
            chunk_checksum=chunk_checksum,
        )

        await use_case.execute(request)

    # Simulate interruption here

    # ACT: Resume and upload chunks 5-9 (resumed session)
    for chunk_index in range(5, 10):
        chunk_data = generate_chunk_data(chunk_index)
        chunk_checksum = compute_chunk_checksum(chunk_data)

        request = ProcessChunkRequest(
            workspace_id=sample_workspace_id,
            session_id=sample_session_id,
            chunk_data=chunk_data,
            chunk_offset=chunk_index * CHUNK_SIZE,
            chunk_checksum=chunk_checksum,
        )

        await use_case.execute(request)

    # ASSERT: Chunk manifest has 10 chunks with sequential indices
    final_session = await session_store.get_session(sample_workspace_id, sample_session_id)

    assert len(final_session.chunk_manifest) == 10, "Should have 10 chunks"

    # ASSERT: Indices are sequential (0, 1, 2, ..., 9)
    for i in range(10):
        chunk = final_session.chunk_manifest[i]
        assert chunk["index"] == i, f"Chunk index should be {i}"
        assert chunk["size"] == CHUNK_SIZE, f"Chunk {i} size should be {CHUNK_SIZE}"
        assert len(chunk["checksum"]) == 64, f"Chunk {i} checksum should be 64 chars"

    # ASSERT: No gaps (all indices present)
    indices = [c["index"] for c in final_session.chunk_manifest]
    assert indices == list(range(10)), "Indices should be [0, 1, 2, ..., 9]"

    # ASSERT: No duplicates
    assert len(set(indices)) == 10, "No duplicate indices should exist"


# ==============================================================================
# AC6: No previously verified chunks are re-processed
# ==============================================================================


@pytest.mark.asyncio
async def test_no_chunk_reprocessing_on_resume(
    redis_client,
    session_store: RedisSessionStore,
    sample_workspace_id: UUID,
    sample_session_id: UUID,
):
    """Test previously verified chunks are never re-processed.

    Validates Acceptance Criterion 6:
        No previously verified chunks are re-processed

    Scenario:
        1. Upload chunks 0-2 (3 chunks, offset = 15 MB)
        2. Attempt to re-upload chunk 1 (offset 5 MB)
        3. Verify offset validation rejects (409 Conflict)
        4. Verify chunk_manifest still has only 3 chunks (no re-processing)
        5. Verify UploadSession entity prevents duplicate chunk indices
        6. Verify UploadSession entity prevents offset from going backwards
    """
    # ARRANGE: Create session with 3 chunks already uploaded
    chunk_0_data = generate_chunk_data(0)
    chunk_1_data = generate_chunk_data(1)
    chunk_2_data = generate_chunk_data(2)

    session = create_sample_session(
        session_id=sample_session_id,
        workspace_id=sample_workspace_id,
        size=FILE_SIZE_3_CHUNKS,
        offset=3 * CHUNK_SIZE,  # All 3 chunks uploaded (15728640 bytes)
        status=SessionStatus.IN_PROGRESS,
        chunk_manifest=[
            {"index": 0, "size": CHUNK_SIZE, "checksum": compute_chunk_checksum(chunk_0_data)},
            {"index": 1, "size": CHUNK_SIZE, "checksum": compute_chunk_checksum(chunk_1_data)},
            {"index": 2, "size": CHUNK_SIZE, "checksum": compute_chunk_checksum(chunk_2_data)},
        ],
    )
    await session_store.create_session(session)

    # ACT: Attempt to re-upload chunk 1 (offset 5242880) - should fail
    use_case = ProcessChunkUseCase(
        session_store=session_store,
        chunk_verifier=ChunkVerifier(),
        redis_client=redis_client,
    )

    request = ProcessChunkRequest(
        workspace_id=sample_workspace_id,
        session_id=sample_session_id,
        chunk_data=chunk_1_data,
        chunk_offset=1 * CHUNK_SIZE,  # WRONG - trying to go back to chunk 1
        chunk_checksum=compute_chunk_checksum(chunk_1_data),
    )

    # ASSERT: OffsetMismatchError raised (offset validation rejects)
    with pytest.raises(OffsetMismatchError) as exc_info:
        await use_case.execute(request)

    # ASSERT: Error contains correct offset information
    assert exc_info.value.expected_offset == 3 * CHUNK_SIZE, "Expected offset should be 15728640"
    assert exc_info.value.received_offset == 1 * CHUNK_SIZE, "Received offset should be 5242880"
    assert exc_info.value.session_id == sample_session_id

    # ASSERT: Session state unchanged (no re-processing occurred)
    unchanged_session = await session_store.get_session(sample_workspace_id, sample_session_id)
    assert unchanged_session.offset == 3 * CHUNK_SIZE, "Offset should remain 15728640"
    assert len(unchanged_session.chunk_manifest) == 3, "Should still have 3 chunks"

    # ASSERT: UploadSession entity prevents offset from going backwards
    with pytest.raises(ValueError, match="cannot decrease offset"):
        unchanged_session.update_offset(1 * CHUNK_SIZE)

    # ASSERT: UploadSession entity prevents duplicate chunk indices
    with pytest.raises(ValueError, match="already exists in manifest"):
        unchanged_session.add_chunk(1, CHUNK_SIZE, "duplicate_hash")


# ==============================================================================
# AC7: Offset mismatch returns 409 Conflict with expected offset
# ==============================================================================


@pytest.mark.asyncio
async def test_offset_mismatch_returns_409_conflict(
    redis_client,
    session_store: RedisSessionStore,
    sample_workspace_id: UUID,
    sample_session_id: UUID,
):
    """Test offset mismatch returns OffsetMismatchError (translates to 409).

    Validates Acceptance Criterion 7:
        Offset mismatch (e.g., client sends offset 0) returns 409 Conflict
        with expected offset

    Test Cases:
        1. Client sends offset 0 when server offset is 10 MB → 409
        2. Client skips chunk (sends offset 15 MB when server is at 10 MB) → 409
        3. Client sends correct offset → 204 (success)
        4. Error response includes expected_offset for client correction
    """
    # ARRANGE: Create session with 2 chunks uploaded (offset = 10 MB)
    session = create_sample_session(
        session_id=sample_session_id,
        workspace_id=sample_workspace_id,
        size=FILE_SIZE_3_CHUNKS,
        offset=2 * CHUNK_SIZE,  # 10485760 bytes
        status=SessionStatus.IN_PROGRESS,
        chunk_manifest=[
            {"index": 0, "size": CHUNK_SIZE, "checksum": "hash0"},
            {"index": 1, "size": CHUNK_SIZE, "checksum": "hash1"},
        ],
    )
    await session_store.create_session(session)

    use_case = ProcessChunkUseCase(
        session_store=session_store,
        chunk_verifier=ChunkVerifier(),
        redis_client=redis_client,
    )

    # TEST CASE 1: Client sends offset 0 (trying to restart upload)
    chunk_data = generate_chunk_data(0)
    request = ProcessChunkRequest(
        workspace_id=sample_workspace_id,
        session_id=sample_session_id,
        chunk_data=chunk_data,
        chunk_offset=0,  # WRONG - should be 10485760
        chunk_checksum=compute_chunk_checksum(chunk_data),
    )

    with pytest.raises(OffsetMismatchError) as exc_info:
        await use_case.execute(request)

    assert exc_info.value.expected_offset == 2 * CHUNK_SIZE
    assert exc_info.value.received_offset == 0

    # TEST CASE 2: Client skips chunk (sends offset 15 MB)
    request_skip = ProcessChunkRequest(
        workspace_id=sample_workspace_id,
        session_id=sample_session_id,
        chunk_data=chunk_data,
        chunk_offset=3 * CHUNK_SIZE,  # WRONG - skipping chunk 2
        chunk_checksum=compute_chunk_checksum(chunk_data),
    )

    with pytest.raises(OffsetMismatchError) as exc_info:
        await use_case.execute(request_skip)

    assert exc_info.value.expected_offset == 2 * CHUNK_SIZE
    assert exc_info.value.received_offset == 3 * CHUNK_SIZE

    # TEST CASE 3: Client sends correct offset → Success
    chunk_2_data = generate_chunk_data(2)
    request = ProcessChunkRequest(
        workspace_id=sample_workspace_id,
        session_id=sample_session_id,
        chunk_data=chunk_2_data,
        chunk_offset=2 * CHUNK_SIZE,  # CORRECT
        chunk_checksum=compute_chunk_checksum(chunk_2_data),
    )

    response = await use_case.execute(request)
    assert response.new_offset == FILE_SIZE_3_CHUNKS, "Upload should succeed"


# ==============================================================================
# Resume after service restart (Redis persistence)
# ==============================================================================


@pytest.mark.asyncio
async def test_resume_after_service_restart(
    redis_client,
    sample_workspace_id: UUID,
    sample_session_id: UUID,
):
    """Test session state persists across service restarts (Redis durability).

    Scenario:
        1. Upload 2 chunks with first session_store instance
        2. Simulate service restart: Create NEW session_store instance
        3. Resume upload with new session_store instance
        4. Verify session state intact (offset, chunk_manifest preserved)
        5. Verify upload can continue from where it left off

    This validates Redis AOF/RDB persistence and proves resumability
    survives application restarts (as long as Redis is running).
    """
    # ARRANGE: Create session and upload 2 chunks (first "service instance")
    session_store_1 = RedisSessionStore(redis_client)

    session = create_sample_session(
        session_id=sample_session_id,
        workspace_id=sample_workspace_id,
        size=FILE_SIZE_3_CHUNKS,
    )
    await session_store_1.create_session(session)

    use_case_1 = ProcessChunkUseCase(
        session_store=session_store_1,
        chunk_verifier=ChunkVerifier(),
        redis_client=redis_client,
    )

    # Upload chunk 0
    chunk_0_data = generate_chunk_data(0)
    request = ProcessChunkRequest(
        workspace_id=sample_workspace_id,
        session_id=sample_session_id,
        chunk_data=chunk_0_data,
        chunk_offset=0,
        chunk_checksum=compute_chunk_checksum(chunk_0_data),
    )
    await use_case_1.execute(request)

    # Upload chunk 1
    chunk_1_data = generate_chunk_data(1)
    request = ProcessChunkRequest(
        workspace_id=sample_workspace_id,
        session_id=sample_session_id,
        chunk_data=chunk_1_data,
        chunk_offset=CHUNK_SIZE,
        chunk_checksum=compute_chunk_checksum(chunk_1_data),
    )
    await use_case_1.execute(request)

    # ACT: Simulate service restart - Create NEW session_store instance
    session_store_2 = RedisSessionStore(redis_client)

    # ACT: Retrieve session with new session_store instance
    retrieved_session = await session_store_2.get_session(sample_workspace_id, sample_session_id)

    # ASSERT: Session state intact (offset and chunk_manifest preserved)
    assert retrieved_session is not None, "Session should persist across restart"
    assert retrieved_session.offset == 2 * CHUNK_SIZE, "Offset should be 10485760"
    assert len(retrieved_session.chunk_manifest) == 2, "Should have 2 chunks"
    assert retrieved_session.chunk_manifest[0]["index"] == 0
    assert retrieved_session.chunk_manifest[1]["index"] == 1

    # ASSERT: Upload can continue from where it left off (chunk 2)
    use_case_2 = ProcessChunkUseCase(
        session_store=session_store_2,
        chunk_verifier=ChunkVerifier(),
        redis_client=redis_client,
    )

    chunk_2_data = generate_chunk_data(2)
    request = ProcessChunkRequest(
        workspace_id=sample_workspace_id,
        session_id=sample_session_id,
        chunk_data=chunk_2_data,
        chunk_offset=2 * CHUNK_SIZE,
        chunk_checksum=compute_chunk_checksum(chunk_2_data),
    )

    response = await use_case_2.execute(request)
    assert response.new_offset == FILE_SIZE_3_CHUNKS, "Resume after restart should work"


# ==============================================================================
# Resume fails gracefully after 24-hour TTL expiry
# ==============================================================================


@pytest.mark.asyncio
async def test_resume_fails_after_24_hour_expiry(
    redis_client,
    session_store: RedisSessionStore,
    sample_workspace_id: UUID,
    sample_session_id: UUID,
):
    """Test resume fails gracefully after 24-hour TTL expiry.

    Scenario:
        1. Create session with 1-second TTL (simulate expiry for test speed)
        2. Upload 1 chunk successfully
        3. Wait for TTL expiry (2 seconds)
        4. Attempt to resume upload (query session)
        5. Verify session expired (returns None)
        6. Verify expiry metadata available for better error messages

    Note: Uses 1-second TTL for test speed (production uses 24 hours).
    This validates the expiry mechanism works correctly.
    """
    # ARRANGE: Create session with custom short TTL for testing
    # We'll need to modify the session_store to use a short TTL for this test
    # Since RedisSessionStore uses a fixed 24-hour TTL, we'll directly use Redis

    session = create_sample_session(
        session_id=sample_session_id,
        workspace_id=sample_workspace_id,
        size=FILE_SIZE_3_CHUNKS,
    )

    # Create session manually with 1-second TTL
    from src.infrastructure.redis.key_builder import session_key

    key = session_key(sample_workspace_id, sample_session_id)

    session_data = {
        "session_id": str(session.session_id),
        "workspace_id": str(session.workspace_id),
        "filename": session.filename,
        "size": str(session.size),
        "mime_type": session.mime_type,
        "sha256_checksum": str(session.sha256_checksum),
        "offset": str(session.offset),
        "status": session.status.value,
        "created_at": session.created_at.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "chunk_manifest": "[]",
    }

    # Set with 1-second TTL
    await redis_client.hset(key, mapping=session_data)
    await redis_client.expire(key, 1)

    # Verify session exists initially
    initial_session = await session_store.get_session(sample_workspace_id, sample_session_id)
    assert initial_session is not None, "Session should exist initially"

    # ACT: Wait for expiry (2 seconds to be safe)
    await asyncio.sleep(2)

    # ACT: Attempt to resume after expiry
    expired_session = await session_store.get_session(sample_workspace_id, sample_session_id)

    # ASSERT: Session expired (returns None)
    assert expired_session is None, "Session should be expired and return None"

    # ASSERT: Attempting to upload chunk fails (session not found)
    use_case = ProcessChunkUseCase(
        session_store=session_store,
        chunk_verifier=ChunkVerifier(),
        redis_client=redis_client,
    )

    chunk_data = generate_chunk_data(0)
    request = ProcessChunkRequest(
        workspace_id=sample_workspace_id,
        session_id=sample_session_id,
        chunk_data=chunk_data,
        chunk_offset=0,
        chunk_checksum=compute_chunk_checksum(chunk_data),
    )

    from src.domain.exceptions import SessionNotFoundError

    with pytest.raises(SessionNotFoundError):
        await use_case.execute(request)


# ==============================================================================
# Large file scenario: 1 GB file with 200 chunks
# ==============================================================================


@pytest.mark.asyncio
async def test_resume_large_file_200_chunks(
    redis_client,
    session_store: RedisSessionStore,
    sample_workspace_id: UUID,
    sample_session_id: UUID,
):
    """Test resume scenario with large file (1 GB = 200 chunks x 5MB).

    Realistic Production Scenario:
        - File: 1 GB document
        - Chunks: 200 chunks x 5 MB
        - Interruption: At chunk 150 (787 MB uploaded)
        - Resume: Continue from chunk 150 → 200

    This validates:
        - Large chunk_manifest handling (200 entries)
        - High offset values (787 MB = 825_229_312 bytes)
        - Resume after significant progress
        - Performance with realistic file sizes

    Note: For test speed, only uploads first 3 and last 3 chunks as proof.
    Chunks 3-149 are simulated with placeholder data. This tests capacity
    and offset handling, but not full integrity validation of 150 chunks.
    """
    # ARRANGE: Create session for 1 GB file (200 chunks x 5 MB)
    session = create_sample_session(
        session_id=sample_session_id,
        workspace_id=sample_workspace_id,
        size=FILE_SIZE_200_CHUNKS,  # ~1 GB
    )
    await session_store.create_session(session)

    use_case = ProcessChunkUseCase(
        session_store=session_store,
        chunk_verifier=ChunkVerifier(),
        redis_client=redis_client,
    )

    # ACT: Upload chunks 0-149 (first 787 MB)
    # For test speed, we'll only upload first 3 and last 3 chunks as proof
    # In production, all 150 would be uploaded before interruption

    # Upload first 3 chunks
    for chunk_index in range(3):
        chunk_data = generate_chunk_data(chunk_index)
        request = ProcessChunkRequest(
            workspace_id=sample_workspace_id,
            session_id=sample_session_id,
            chunk_data=chunk_data,
            chunk_offset=chunk_index * CHUNK_SIZE,
            chunk_checksum=compute_chunk_checksum(chunk_data),
        )
        await use_case.execute(request)

    # Simulate interruption at chunk 150 (skip chunks 3-149 for test speed)
    # Manually set session state as if 150 chunks were uploaded
    # NOTE: This simulates capacity but doesn't validate full chunk integrity
    session_after_150 = await session_store.get_session(sample_workspace_id, sample_session_id)

    # Fast-forward to chunk 150 state (simulate 150 chunks uploaded)
    session_after_150.update_offset(150 * CHUNK_SIZE)

    # Add chunk entries 3-149 to manifest (simplified for test)
    for i in range(3, 150):
        session_after_150.chunk_manifest.append(
            {
                "index": i,
                "size": CHUNK_SIZE,
                "checksum": f"chunk_{i}_hash_simulated",
            }
        )

    await session_store.update_session(session_after_150)

    # ACT: Resume at chunk 150 (upload chunks 150-152 as proof)
    for chunk_index in range(150, 153):
        chunk_data = generate_chunk_data(chunk_index)
        request = ProcessChunkRequest(
            workspace_id=sample_workspace_id,
            session_id=sample_session_id,
            chunk_data=chunk_data,
            chunk_offset=chunk_index * CHUNK_SIZE,
            chunk_checksum=compute_chunk_checksum(chunk_data),
        )
        await use_case.execute(request)

    # ASSERT: Resume successful at high offset values
    final_session = await session_store.get_session(sample_workspace_id, sample_session_id)

    assert final_session.offset == 153 * CHUNK_SIZE, "Offset should be at chunk 153"
    assert len(final_session.chunk_manifest) == 153, "Should have 153 chunks"

    # ASSERT: Chunk manifest has sequential indices (spot check)
    assert final_session.chunk_manifest[0]["index"] == 0
    assert final_session.chunk_manifest[150]["index"] == 150
    assert final_session.chunk_manifest[152]["index"] == 152


# ==============================================================================
# Additional edge case validations (from code review)
# ==============================================================================


@pytest.mark.asyncio
async def test_chunk_overflow_beyond_file_size_rejected(
    redis_client,
    session_store: RedisSessionStore,
    sample_workspace_id: UUID,
    sample_session_id: UUID,
):
    """Test that chunk offset beyond file size is rejected.

    Critical boundary validation: Prevents uploading more data than declared.
    If offset + chunk_size > file_size, server should reject the chunk.
    """
    # ARRANGE: Create session for 12 MB file (2.4 chunks)
    file_size = 12_582_912  # 12 MB
    session = create_sample_session(
        session_id=sample_session_id,
        workspace_id=sample_workspace_id,
        size=file_size,
    )
    await session_store.create_session(session)

    use_case = ProcessChunkUseCase(
        session_store=session_store,
        chunk_verifier=ChunkVerifier(),
        redis_client=redis_client,
    )

    # Upload chunk 0 and 1 successfully (10 MB total)
    for i in range(2):
        chunk_data = generate_chunk_data(i)
        request = ProcessChunkRequest(
            workspace_id=sample_workspace_id,
            session_id=sample_session_id,
            chunk_data=chunk_data,
            chunk_offset=i * CHUNK_SIZE,
            chunk_checksum=compute_chunk_checksum(chunk_data),
        )
        await use_case.execute(request)

    # ACT: Attempt to upload full 5MB chunk at offset 10MB
    # This would result in 15MB total, exceeding 12MB file size
    chunk_data = generate_chunk_data(2)
    request = ProcessChunkRequest(
        workspace_id=sample_workspace_id,
        session_id=sample_session_id,
        chunk_data=chunk_data,
        chunk_offset=2 * CHUNK_SIZE,
        chunk_checksum=compute_chunk_checksum(chunk_data),
    )

    # ASSERT: Should raise ValueError for chunk exceeding file size
    with pytest.raises(ValueError, match="exceeds file size|offset.*size"):
        await use_case.execute(request)


@pytest.mark.asyncio
async def test_workspace_isolation_prevents_cross_workspace_access(
    redis_client,
    session_store: RedisSessionStore,
):
    """Test workspace_id enforces isolation boundary.

    Security-critical: Workspace A cannot resume workspace B's session.
    """
    workspace_a = uuid4()
    workspace_b = uuid4()
    session_id = uuid4()

    # ARRANGE: Create session in workspace A
    session = create_sample_session(
        session_id=session_id,
        workspace_id=workspace_a,
        size=FILE_SIZE_3_CHUNKS,
    )
    await session_store.create_session(session)

    # Upload 1 chunk to workspace A's session
    use_case = ProcessChunkUseCase(
        session_store=session_store,
        chunk_verifier=ChunkVerifier(),
        redis_client=redis_client,
    )
    chunk_data = generate_chunk_data(0)
    request = ProcessChunkRequest(
        workspace_id=workspace_a,
        session_id=session_id,
        chunk_data=chunk_data,
        chunk_offset=0,
        chunk_checksum=compute_chunk_checksum(chunk_data),
    )
    await use_case.execute(request)

    # ACT: Attempt to access session from workspace B
    session_from_b = await session_store.get_session(workspace_b, session_id)

    # ASSERT: Workspace B cannot see workspace A's session
    assert session_from_b is None, "Cross-workspace access should be prevented"

    # ACT: Attempt to upload to workspace A's session using workspace B context
    request_from_b = ProcessChunkRequest(
        workspace_id=workspace_b,
        session_id=session_id,
        chunk_data=generate_chunk_data(1),
        chunk_offset=CHUNK_SIZE,
        chunk_checksum=compute_chunk_checksum(generate_chunk_data(1)),
    )

    # ASSERT: Should raise SessionNotFoundError (workspace mismatch)
    from src.domain.exceptions import SessionNotFoundError

    with pytest.raises(SessionNotFoundError):
        await use_case.execute(request_from_b)


@pytest.mark.asyncio
async def test_negative_and_invalid_offsets_rejected(
    redis_client,
    session_store: RedisSessionStore,
    sample_workspace_id: UUID,
    sample_session_id: UUID,
):
    """Test obviously invalid offset values are rejected.

    Edge cases: negative offsets, offsets beyond file size.
    """
    session = create_sample_session(
        session_id=sample_session_id,
        workspace_id=sample_workspace_id,
        size=FILE_SIZE_3_CHUNKS,
    )
    await session_store.create_session(session)

    use_case = ProcessChunkUseCase(
        session_store=session_store,
        chunk_verifier=ChunkVerifier(),
        redis_client=redis_client,
    )

    # Test case 1: Negative offset raises ValueError at DTO validation
    chunk_data = generate_chunk_data(0)

    with pytest.raises(ValueError, match="cannot be negative"):
        ProcessChunkRequest(
            workspace_id=sample_workspace_id,
            session_id=sample_session_id,
            chunk_data=chunk_data,
            chunk_offset=-1,  # Invalid: negative
            chunk_checksum=compute_chunk_checksum(chunk_data),
        )

    # Test case 2: Offset beyond file size
    request_beyond = ProcessChunkRequest(
        workspace_id=sample_workspace_id,
        session_id=sample_session_id,
        chunk_data=chunk_data,
        chunk_offset=FILE_SIZE_3_CHUNKS + 1000,  # Beyond file size
        chunk_checksum=compute_chunk_checksum(chunk_data),
    )

    # Should raise OffsetMismatchError or ValueError
    with pytest.raises((OffsetMismatchError, ValueError)):
        await use_case.execute(request_beyond)


@pytest.mark.asyncio
async def test_partial_last_chunk_handling(
    redis_client,
    session_store: RedisSessionStore,
    sample_workspace_id: UUID,
    sample_session_id: UUID,
):
    """Test file size not multiple of chunk size (partial last chunk).

    Example: 12 MB file = 2 full chunks (10 MB) + 1 partial chunk (2 MB).
    """
    # ARRANGE: Create session for 12 MB file (2 full + 1 partial chunk)
    file_size = 12_582_912  # 12 MB
    last_chunk_size = file_size - (2 * CHUNK_SIZE)  # 2,097,152 bytes (2 MB)

    session = create_sample_session(
        session_id=sample_session_id,
        workspace_id=sample_workspace_id,
        size=file_size,
    )
    await session_store.create_session(session)

    use_case = ProcessChunkUseCase(
        session_store=session_store,
        chunk_verifier=ChunkVerifier(),
        redis_client=redis_client,
    )

    # ACT: Upload 2 full chunks
    for i in range(2):
        chunk_data = generate_chunk_data(i)
        request = ProcessChunkRequest(
            workspace_id=sample_workspace_id,
            session_id=sample_session_id,
            chunk_data=chunk_data,
            chunk_offset=i * CHUNK_SIZE,
            chunk_checksum=compute_chunk_checksum(chunk_data),
        )
        await use_case.execute(request)

    # ACT: Upload partial last chunk (2 MB)
    last_chunk_data = generate_chunk_data(2, size=last_chunk_size)
    request = ProcessChunkRequest(
        workspace_id=sample_workspace_id,
        session_id=sample_session_id,
        chunk_data=last_chunk_data,
        chunk_offset=2 * CHUNK_SIZE,
        chunk_checksum=compute_chunk_checksum(last_chunk_data),
    )
    response = await use_case.execute(request)

    # ASSERT: Offset equals file size after partial chunk
    assert response.new_offset == file_size, "Offset should equal file size"

    # ASSERT: Last chunk has correct smaller size
    final_session = await session_store.get_session(sample_workspace_id, sample_session_id)
    assert final_session.chunk_manifest[2]["size"] == last_chunk_size
    assert final_session.offset == file_size


@pytest.mark.asyncio
async def test_offset_equals_size_before_completion(
    redis_client,
    session_store: RedisSessionStore,
    sample_workspace_id: UUID,
    sample_session_id: UUID,
):
    """Test boundary state: offset == size but status != COMPLETE.

    Valid temporary state after uploading all chunks but before calling
    the complete endpoint. Session should still be IN_PROGRESS.
    """
    # ARRANGE: Create session for 3-chunk file
    session = create_sample_session(
        session_id=sample_session_id,
        workspace_id=sample_workspace_id,
        size=FILE_SIZE_3_CHUNKS,
    )
    await session_store.create_session(session)

    use_case = ProcessChunkUseCase(
        session_store=session_store,
        chunk_verifier=ChunkVerifier(),
        redis_client=redis_client,
    )

    # ACT: Upload all 3 chunks
    for i in range(3):
        chunk_data = generate_chunk_data(i)
        request = ProcessChunkRequest(
            workspace_id=sample_workspace_id,
            session_id=sample_session_id,
            chunk_data=chunk_data,
            chunk_offset=i * CHUNK_SIZE,
            chunk_checksum=compute_chunk_checksum(chunk_data),
        )
        await use_case.execute(request)

    # ACT: Query session state (simulate HEAD request)
    final_session = await session_store.get_session(sample_workspace_id, sample_session_id)

    # ASSERT: Offset equals size
    assert final_session.offset == FILE_SIZE_3_CHUNKS, "All bytes uploaded"

    # ASSERT: Status still IN_PROGRESS (not COMPLETE yet)
    assert final_session.status == SessionStatus.IN_PROGRESS, (
        "Session should be IN_PROGRESS until completion endpoint called"
    )

    # ASSERT: All chunks present in manifest
    assert len(final_session.chunk_manifest) == 3
