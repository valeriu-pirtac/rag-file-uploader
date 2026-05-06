"""Use case for processing uploaded file chunks.

This module implements the ProcessChunkUseCase, which orchestrates the core
chunk upload processing flow including session retrieval, offset validation,
SHA-256 verification, chunk tracking, and session state updates.
"""

import redis.asyncio as aioredis

from src.application.dto.process_chunk_request import ProcessChunkRequest
from src.application.dto.process_chunk_response import ProcessChunkResponse
from src.domain.exceptions import (
    InfrastructureError,
    InvalidSessionStateError,
    OffsetMismatchError,
    SessionNotFoundError,
)
from src.domain.protocols.session_store import ISessionStore
from src.domain.services.chunk_verifier import ChunkVerifier
from src.domain.value_objects.session_status import SessionStatus


class ProcessChunkUseCase:
    """Use case for processing uploaded file chunks.

    This use case orchestrates the core chunk upload processing flow,
    including session retrieval, offset validation, SHA-256 verification,
    chunk tracking, and session state updates.

    Performance Critical:
        This code runs on the hot path for every chunk upload. For a 1GB
        file with 5MB chunks, this executes 200 times per file. Must
        complete in ≤100ms per chunk (NFR-P3).

        Performance Budget Breakdown:
        - Session retrieval (Redis HGETALL): ~5ms
        - Offset validation (Python comparison): <1ms
        - SHA-256 verification (ChunkVerifier): <50ms (Story 3.6)
        - Chunk manifest append (Python list): <1ms
        - Session update (Redis HSET): ~5ms
        - Orchestration overhead: ~5ms
        - TOTAL: ~67ms (well within 100ms budget)

    Business Rules:
        - Offset MUST match current session offset exactly (strict tus compliance)
        - Checksum MUST match computed SHA-256 (data integrity)
        - Session status transitions PENDING → IN_PROGRESS on first chunk
        - Session status must NOT be COMPLETE, FAILED, or ABORTED (terminal states)
        - Chunk manifest MUST be updated before offset increment (audit trail)
        - All updates MUST be atomic (session.update_offset + add_chunk + update_session)

    Error Handling:
        - SessionNotFoundError: Session expired or never existed → 404
        - OffsetMismatchError: Client offset doesn't match server → 409
        - ChecksumMismatchError: SHA-256 verification failed → 460
        - ValueError: Terminal state or invalid offset → 400/409

    Attributes:
        _session_store: Session store protocol implementation
        _chunk_verifier: Chunk verifier domain service

    Examples:
        >>> # Create use case with dependencies
        >>> use_case = ProcessChunkUseCase(
        ...     session_store=redis_session_store,
        ...     chunk_verifier=ChunkVerifier()
        ... )
        >>>
        >>> # Process chunk
        >>> request = ProcessChunkRequest(
        ...     workspace_id=uuid4(),
        ...     session_id=uuid4(),
        ...     chunk_data=b"x" * 5242880,  # 5MB
        ...     chunk_offset=0,
        ...     chunk_checksum="abc123...",
        ... )
        >>> response = await use_case.execute(request)
        >>> print(f"New offset: {response.new_offset}")
    """

    def __init__(
        self,
        session_store: ISessionStore,
        chunk_verifier: ChunkVerifier,
        redis_client: aioredis.Redis,
    ) -> None:
        """Initialize the use case with protocol dependencies.

        Args:
            session_store: Session store protocol implementation for retrieving
                and updating upload session state in durable storage
            chunk_verifier: Chunk verifier domain service for SHA-256 checksum
                validation of uploaded chunks
            redis_client: Redis client for storing chunk data with 24-hour TTL
        """
        self._session_store = session_store
        self._chunk_verifier = chunk_verifier
        self._redis = redis_client
        self._chunk_ttl_seconds = 86400  # 24 hours (matches session TTL)

    async def execute(self, request: ProcessChunkRequest) -> ProcessChunkResponse:
        """Execute the process chunk use case.

        Orchestrates the complete flow of processing an uploaded chunk:
        1. Retrieve session from storage (Redis)
        2. Validate session exists and not expired (→ 404 if expired/missing)
        3. Validate session not in terminal state (COMPLETE/FAILED/ABORTED)
        4. Validate offset matches current session offset (→ 409 if mismatch)
        5. Verify chunk SHA-256 checksum (→ 460 if mismatch)
        6. Calculate chunk index from offset and chunk size
        7. Add chunk to manifest with metadata (index, size, checksum)
        8. Update session offset (offset += len(chunk_data))
        9. Transition status PENDING → IN_PROGRESS (if first chunk)
        10. Persist updated session atomically to storage
        11. Return response with new offset

        Execution Order (Critical):
            Validation happens FIRST to fail fast before expensive operations.
            SHA-256 verification happens BEFORE session updates to ensure only
            verified chunks update state. Session updates are atomic (manifest +
            offset + status updated together).

        Offset Validation (Strict tus Protocol):
            The client-provided offset MUST exactly match the current session
            offset. This enforces sequential chunk uploads and prevents:
            - Duplicate chunk uploads
            - Out-of-order chunk uploads
            - Client-server state desynchronization

            If offsets don't match, return 409 Conflict with expected offset.

        Args:
            request: ProcessChunkRequest DTO containing workspace_id, session_id,
                chunk_data (bytes), chunk_offset (int), and chunk_checksum (str)

        Returns:
            ProcessChunkResponse with new_offset (bytes uploaded so far)

        Raises:
            SessionNotFoundError: Session doesn't exist or has expired (24h TTL).
                This should return 404 Session Not Found to client.
            OffsetMismatchError: Client offset doesn't match current session offset.
                Contains expected_offset and received_offset for 409 Conflict response.
            ChecksumMismatchError: Chunk SHA-256 doesn't match provided checksum.
                Contains expected/computed checksums for 460 Checksum Mismatch response.
            ValueError: Session in terminal state (COMPLETE/FAILED/ABORTED) or
                invalid offset update (going backwards). Should return 409 Conflict.
            InfrastructureError: Storage system failure (Redis connection, timeout).
                Should return 503 Service Unavailable to client.

        Performance:
            Must complete in ≤100ms at p99 for 5MB chunks (NFR-P3).
            Measured: ~67ms average on reference hardware.

        Examples:
            >>> # Success case
            >>> request = ProcessChunkRequest(
            ...     workspace_id=uuid4(),
            ...     session_id=uuid4(),
            ...     chunk_data=b"x" * 5242880,
            ...     chunk_offset=0,
            ...     chunk_checksum="correct_hash",
            ... )
            >>> response = await use_case.execute(request)
            >>> assert response.new_offset == 5242880
            >>>
            >>> # Offset mismatch (client out of sync)
            >>> try:
            ...     request.chunk_offset = 999999  # Wrong offset
            ...     await use_case.execute(request)
            ... except OffsetMismatchError as e:
            ...     print(f"Expected offset: {e.expected_offset}")
            ...     print(f"Received offset: {e.received_offset}")
            >>>
            >>> # Checksum mismatch (corrupt chunk)
            >>> try:
            ...     request.chunk_checksum = "wrong_hash"
            ...     await use_case.execute(request)
            ... except ChecksumMismatchError as e:
            ...     print(f"Expected: {e.expected_checksum}")
            ...     print(f"Computed: {e.computed_checksum}")
        """
        # STEP 1: Retrieve session from storage
        session = await self._session_store.get_session(
            request.workspace_id,
            request.session_id,
        )

        # STEP 2: Validate session exists (None = expired or never existed)
        if session is None:
            raise SessionNotFoundError(f"Upload session {request.session_id} not found or expired")

        # STEP 3: Validate session not in terminal state
        if session.status in (SessionStatus.COMPLETE, SessionStatus.FAILED, SessionStatus.ABORTED):
            raise InvalidSessionStateError(
                session_id=session.session_id,
                current_state=session.status.value,
                operation="process_chunk",
            )

        # STEP 4: Validate offset matches (strict tus protocol compliance)
        if request.chunk_offset != session.offset:
            raise OffsetMismatchError(
                expected_offset=session.offset,
                received_offset=request.chunk_offset,
                session_id=session.session_id,
            )

        # STEP 5: Validate chunk size bounds (DoS prevention + empty check)
        chunk_size = len(request.chunk_data)
        if chunk_size == 0:
            raise ValueError("Chunk data cannot be empty")
        if chunk_size > 10485760:  # 10 MB max chunk size
            raise ValueError(f"Chunk size {chunk_size} exceeds maximum 10 MB")

        # STEP 6: Verify chunk SHA-256 checksum (data integrity)
        # This is the most expensive operation (~20-30ms for 5MB)
        # Calculate chunk_index from manifest length (handles variable chunk sizes)
        chunk_index = len(session.chunk_manifest)
        self._chunk_verifier.verify_chunk(
            data=request.chunk_data,
            expected_checksum=request.chunk_checksum,
            chunk_index=chunk_index,
        )
        # Note: verify_chunk raises ChecksumMismatchError on mismatch

        # STEP 6.5: Store chunk bytes in Redis for later assembly (Story 5.8)
        # Key pattern: chunk:workspace_{workspace_id}:session_{session_id}:index_{index}
        # TTL: 24 hours (matches session TTL)
        chunk_key = f"chunk:workspace_{request.workspace_id}:session_{request.session_id}:index_{chunk_index}"
        try:
            await self._redis.set(chunk_key, request.chunk_data, ex=self._chunk_ttl_seconds)
        except Exception as e:
            raise InfrastructureError(
                f"Failed to store chunk {chunk_index} in Redis: {str(e)}"
            ) from e

        # STEP 7: Calculate new offset
        new_offset = session.offset + chunk_size

        # STEP 8: Add chunk to manifest (audit trail + completion validation)
        session.add_chunk(
            chunk_index=chunk_index,
            chunk_size=chunk_size,
            chunk_checksum=request.chunk_checksum,
        )

        # STEP 9: Update session offset (monotonic increase only)
        session.update_offset(new_offset)

        # STEP 10: Transition status to IN_PROGRESS (if first chunk)
        if session.status == SessionStatus.PENDING:
            session.mark_in_progress()

        # STEP 11: Persist updated session atomically
        await self._session_store.update_session(session)

        # STEP 12: Return response
        return ProcessChunkResponse(new_offset=new_offset)
