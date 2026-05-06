"""Use case for orchestrating complete upload flow.

This module implements the CompleteUploadUseCase, which orchestrates the final
upload completion flow including file assembly, deduplication, event publication,
and session lifecycle management.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
import structlog

from src.application.dto.complete_upload_request import CompleteUploadRequest
from src.application.dto.complete_upload_response import CompleteUploadResponse
from src.domain.entities.events import FileLoadCompletedEvent
from src.domain.entities.upload_session import UploadSession
from src.domain.exceptions import (
    DuplicateFileError,
    InfrastructureError,
    IntegrityError,
    InvalidSessionStateError,
    SessionNotFoundError,
    WorkspaceMismatchError,
)
from src.domain.protocols.deduplication_store import FileMetadata, IDeduplicationStore
from src.domain.protocols.event_publisher import IEventPublisher
from src.domain.protocols.rate_limiter import IRateLimiter
from src.domain.protocols.session_store import ISessionStore
from src.domain.protocols.storage_client import IStorageClient
from src.domain.value_objects import SessionStatus


logger = structlog.get_logger(__name__)


class CompleteUploadUseCase:
    """Use case for orchestrating complete upload flow.

    This is the final orchestration step that brings together all Epic 5
    capabilities: file assembly, deduplication, event publishing, and
    session lifecycle completion.

    Orchestration Flow:
        1. Retrieve and validate session
        2. Validate chunk manifest completeness (all indices 0 to N-1 present)
        3. Retrieve chunk data from Redis
        4. Assemble file on S3 with SHA-256 validation (Story 5.2)
        5. Check for duplicates (Story 5.1) - 409 if found
        6. Skip virus scan (Story 5.3 deferred - TODO placeholder)
        7. Publish event to NATS/webhook with retry (Stories 5.5, 5.6, 5.7)
        8. Mark session COMPLETE (only after successful event publish)
        9. Decrement rate limit counter
        10. Register deduplication fingerprint
        11. Cleanup chunk data from Redis
        12. Return response with file_id, s3_path, size_bytes

    Business Rules:
        - Session MUST be IN_PROGRESS (404 if not found, 400 if wrong state)
        - Workspace_id MUST match session.workspace_id (403 if mismatch)
        - Chunk manifest MUST be complete (no gaps, no duplicates)
        - Offset MUST equal size (all bytes uploaded)
        - Session marked COMPLETE only AFTER successful event publish
        - Rate limit counter decremented AFTER session COMPLETE
        - Dedup registration happens AFTER session COMPLETE

    Error Handling:
        - Any failure before event publish → mark session FAILED
        - Event publish failure → mark session FAILED (do NOT mark COMPLETE)
        - Rate limit decrement failure → log error but don't fail (already COMPLETE)
        - Dedup registration failure → log error but don't fail (already COMPLETE)
        - Chunk cleanup failure → log error but don't fail (TTL will expire)

    Atomicity (NFR-R2):
        - File successfully assembled + event published = committed
        - Session COMPLETE = file ready for downstream processing
        - Counter/fingerprint failures are operational issues (logged, not fatal)

    Attributes:
        _session_store: Session store protocol implementation
        _storage_client: Storage client protocol implementation
        _dedup_store: Deduplication store protocol implementation
        _event_publisher: Event publisher protocol implementation (NATS or webhook)
        _rate_limiter: Rate limiter protocol implementation
        _redis: Redis client for retrieving chunk data

    Examples:
        >>> use_case = CompleteUploadUseCase(
        ...     session_store=redis_session_store,
        ...     storage_client=s3_storage_client,
        ...     dedup_store=redis_dedup_store,
        ...     event_publisher=nats_event_publisher_with_retry,
        ...     rate_limiter=redis_rate_limiter,
        ...     redis_client=redis_client
        ... )
        >>>
        >>> request = CompleteUploadRequest(
        ...     workspace_id=uuid4(),
        ...     session_id=uuid4()
        ... )
        >>> response = await use_case.execute(request)
        >>> print(f"File ID: {response.file_id}")
        >>> print(f"S3 Path: {response.s3_path}")
        >>> print(f"Size: {response.size_bytes}")
    """

    def __init__(
        self,
        session_store: ISessionStore,
        storage_client: IStorageClient,
        dedup_store: IDeduplicationStore,
        event_publisher: IEventPublisher,
        rate_limiter: IRateLimiter,
        redis_client: aioredis.Redis,
    ) -> None:
        """Initialize the use case with protocol dependencies.

        Args:
            session_store: Session store protocol implementation
            storage_client: Storage client protocol implementation (MinIO/S3)
            dedup_store: Deduplication store protocol implementation
            event_publisher: Event publisher protocol implementation (NATS or webhook)
            rate_limiter: Rate limiter protocol implementation
            redis_client: Redis client for retrieving chunk data
        """
        self._session_store = session_store
        self._storage_client = storage_client
        self._dedup_store = dedup_store
        self._event_publisher = event_publisher
        self._rate_limiter = rate_limiter
        self._redis = redis_client

    async def execute(self, request: CompleteUploadRequest) -> CompleteUploadResponse:
        """Execute the complete upload use case.

        Orchestrates the complete flow of file assembly, validation, event
        publication, and session completion.

        Args:
            request: CompleteUploadRequest with workspace_id and session_id

        Returns:
            CompleteUploadResponse with file_id, s3_path, and size_bytes

        Raises:
            SessionNotFoundError: Session doesn't exist or expired (404)
            WorkspaceMismatchError: Session belongs to different workspace (403)
            InvalidSessionStateError: Session not in correct state (400/409)
            IntegrityError: File assembly checksum validation failed (500)
            DuplicateFileError: File already exists in workspace (409)
            InfrastructureError: Storage, event, or Redis failure (503)
        """
        workspace_id = request.workspace_id
        session_id = request.session_id

        logger.info(
            "complete_upload_started",
            workspace_id=str(workspace_id),
            session_id=str(session_id),
        )

        try:
            # STEP 1: Retrieve and validate session
            session = await self._session_store.get_session(workspace_id, session_id)

            if session is None:
                logger.error(
                    "complete_upload_session_not_found",
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                )
                raise SessionNotFoundError(f"Upload session {session_id} not found or expired")

            # Validate workspace ownership
            if session.workspace_id != workspace_id:
                logger.error(
                    "complete_upload_workspace_mismatch",
                    workspace_id=str(workspace_id),
                    session_workspace_id=str(session.workspace_id),
                    session_id=str(session_id),
                )
                raise WorkspaceMismatchError(
                    resource_id=session_id,
                    resource_type="upload_session",
                    expected_workspace_id=workspace_id,
                    actual_workspace_id=session.workspace_id,
                )

            # Validate session state
            if session.status != SessionStatus.IN_PROGRESS:
                logger.error(
                    "complete_upload_invalid_state",
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                    current_status=session.status.value,
                )
                raise InvalidSessionStateError(
                    session_id=session_id,
                    current_state=session.status.value,
                    operation="complete_upload",
                )

            # STEP 2: Validate chunk manifest completeness
            self._validate_chunk_manifest(session)

            # Validate offset == size (belt-and-suspenders)
            if session.offset != session.size:
                logger.error(
                    "complete_upload_offset_mismatch",
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                    offset=session.offset,
                    size=session.size,
                )
                raise InvalidSessionStateError(
                    session_id=session_id,
                    current_state=f"offset={session.offset}, size={session.size}",
                    operation="complete_upload",
                )

            # STEP 3: Retrieve chunk data from Redis
            chunks = await self._retrieve_chunks(workspace_id, session_id, session.chunk_manifest)

            logger.info(
                "chunks_retrieved",
                workspace_id=str(workspace_id),
                session_id=str(session_id),
                chunk_count=len(chunks),
                total_size=sum(len(c) for c in chunks),
            )

            # STEP 4: Assemble file on S3 with SHA-256 validation
            file_id = session_id  # Use session_id as file_id
            s3_path, final_size = await self._storage_client.assemble_file(
                workspace_id=workspace_id,
                file_id=file_id,
                chunk_data=chunks,
                expected_checksum=session.sha256_checksum,
            )

            logger.info(
                "file_assembled",
                workspace_id=str(workspace_id),
                session_id=str(session_id),
                file_id=str(file_id),
                s3_path=s3_path,
                size_bytes=final_size,
            )

            # STEP 5: Check for duplicates
            duplicate_metadata = await self._dedup_store.check_duplicate(
                workspace_id, session.sha256_checksum
            )

            if duplicate_metadata is not None:
                logger.warning(
                    "duplicate_file_detected",
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                    sha256=str(session.sha256_checksum),
                    existing_file_id=str(duplicate_metadata.file_id),
                )
                # Mark session FAILED before raising (audit trail)
                session.mark_failed()
                await self._session_store.update_session(session)

                raise DuplicateFileError(
                    sha256_checksum=session.sha256_checksum,
                    existing_file_id=duplicate_metadata.file_id,
                    existing_s3_path=duplicate_metadata.s3_path,
                    uploaded_at=duplicate_metadata.uploaded_at,
                )

            # STEP 6: Skip virus scan (Story 5.3 deferred)
            # TODO: Story 5.3 - ClamAV virus scan integration (optional/deferred)
            # When Story 5.3 is implemented, insert virus scan here:
            # scan_result = await self._virus_scanner.scan_file(s3_path)
            # if not scan_result.clean:
            #     session.mark_failed()
            #     await self._session_store.update_session(session)
            #     raise VirusDetectedError(...)

            logger.info(
                "virus_scan_skipped",
                workspace_id=str(workspace_id),
                session_id=str(session_id),
                note="Story 5.3 deferred - virus scan not implemented in MVP",
            )

            # STEP 7: Publish event (NATS or webhook with retry)
            event = FileLoadCompletedEvent(
                file_id=file_id,
                workspace_id=workspace_id,
                s3_path=s3_path,
                sha256_checksum=session.sha256_checksum,
                size_bytes=final_size,
                uploaded_at=datetime.now(UTC),
            )

            try:
                await self._event_publisher.publish(event)
                logger.info(
                    "event_published",
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                    file_id=str(file_id),
                    event_type=event.event_type,
                )
            except InfrastructureError as e:
                # Event went to DLQ after max retries
                logger.error(
                    "event_publish_failed_after_retries",
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                    file_id=str(file_id),
                    error=str(e),
                )
                # Mark session FAILED - file not ready for downstream
                session.mark_failed()
                await self._session_store.update_session(session)
                raise  # Re-raise to caller (endpoint returns 503)

            # STEP 8: Mark session COMPLETE (only after successful event publish)
            session.mark_complete()
            await self._session_store.update_session(session)

            logger.info(
                "session_marked_complete",
                workspace_id=str(workspace_id),
                session_id=str(session_id),
                file_id=str(file_id),
            )

            # STEP 9: Decrement rate limit counter
            # If this fails, log error but don't fail completion (already committed)
            try:
                await self._rate_limiter.decrement(workspace_id)
                logger.info(
                    "rate_limit_decremented",
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                )
            except InfrastructureError as e:
                logger.error(
                    "rate_limit_decrement_failed",
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                    error=str(e),
                )
                # Don't re-raise - session already COMPLETE, file already published

            # STEP 10: Register deduplication fingerprint
            # If this fails, log error but don't fail completion
            try:
                metadata = FileMetadata(
                    file_id=file_id,
                    s3_path=s3_path,
                    size=final_size,
                    uploaded_at=datetime.now(UTC),
                )
                await self._dedup_store.register_file(
                    workspace_id, session.sha256_checksum, metadata
                )
                logger.info(
                    "dedup_fingerprint_registered",
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                    file_id=str(file_id),
                    sha256=str(session.sha256_checksum),
                )
            except (InfrastructureError, Exception) as e:
                logger.error(
                    "dedup_registration_failed",
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                    file_id=str(file_id),
                    error=str(e),
                )
                # Don't re-raise - session already COMPLETE

            # STEP 11: Cleanup chunk data from Redis
            # If this fails, log error but don't fail - TTL will clean up eventually
            try:
                await self._cleanup_chunks(workspace_id, session_id, session.chunk_manifest)
                logger.info(
                    "chunks_cleaned_up",
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                    chunk_count=len(session.chunk_manifest),
                )
            except Exception as e:
                logger.error(
                    "chunk_cleanup_failed",
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                    error=str(e),
                )
                # Don't re-raise - chunks have 24h TTL, will auto-expire

            # STEP 12: Return response
            logger.info(
                "complete_upload_success",
                workspace_id=str(workspace_id),
                session_id=str(session_id),
                file_id=str(file_id),
                s3_path=s3_path,
                size_bytes=final_size,
            )

            return CompleteUploadResponse(
                file_id=file_id,
                s3_path=s3_path,
                size_bytes=final_size,
            )

        except (SessionNotFoundError, WorkspaceMismatchError, InvalidSessionStateError):
            # Re-raise domain exceptions without wrapping
            raise
        except DuplicateFileError:
            # Already handled (session marked FAILED), re-raise for 409 response
            raise
        except (IntegrityError, InfrastructureError) as e:
            # Infrastructure or integrity errors - mark session FAILED if not already
            try:
                if session is not None:
                    session.mark_failed()
                    await self._session_store.update_session(session)
                logger.error(
                    "complete_upload_failed",
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                    error_type=type(e).__name__,
                    error=str(e),
                )
            except Exception as update_error:
                logger.error(
                    "failed_to_mark_session_failed",
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                    original_error=str(e),
                    update_error=str(update_error),
                )
            raise
        except Exception as e:
            # Unexpected errors - mark session FAILED and log
            logger.error(
                "complete_upload_unexpected_error",
                workspace_id=str(workspace_id),
                session_id=str(session_id),
                error_type=type(e).__name__,
                error=str(e),
            )
            try:
                if session is not None:
                    session.mark_failed()
                    await self._session_store.update_session(session)
            except Exception:
                pass  # Best effort
            raise

    def _validate_chunk_manifest(self, session: UploadSession) -> None:
        """Validate chunk manifest is complete (all indices 0 to N-1 present).

        Args:
            session: UploadSession entity

        Raises:
            InvalidSessionStateError: If manifest is incomplete or has gaps
        """
        manifest = session.chunk_manifest

        if not manifest:
            raise InvalidSessionStateError(
                session_id=session.session_id,
                current_state="chunk_manifest is empty",
                operation="validate_completeness",
            )

        # Extract all chunk indices
        indices = {chunk["index"] for chunk in manifest}

        # Check for sequential indices from 0 to N-1
        expected_indices = set(range(len(manifest)))

        if indices != expected_indices:
            missing = expected_indices - indices
            extra = indices - expected_indices
            raise InvalidSessionStateError(
                session_id=session.session_id,
                current_state=f"chunk_manifest incomplete: missing={missing}, extra={extra}",
                operation="validate_completeness",
            )

        # Validate total size matches expected (belt-and-suspenders)
        total_size = sum(chunk["size"] for chunk in manifest)
        if total_size != session.size:
            raise InvalidSessionStateError(
                session_id=session.session_id,
                current_state=f"chunk_manifest size mismatch: {total_size} != {session.size}",
                operation="validate_completeness",
            )

    async def _retrieve_chunks(
        self, workspace_id: UUID, session_id: UUID, manifest: list[dict[str, Any]]
    ) -> list[bytes]:
        """Retrieve chunk bytes from Redis in index order.

        Args:
            workspace_id: Workspace UUID
            session_id: Session UUID
            manifest: Chunk manifest from session

        Returns:
            List of chunk bytes in index order

        Raises:
            InvalidSessionStateError: If chunk not found in Redis
            InfrastructureError: If Redis operation fails
        """
        chunks = []
        for chunk_meta in sorted(manifest, key=lambda c: c["index"]):
            chunk_key = (
                f"chunk:workspace_{workspace_id}:session_{session_id}:index_{chunk_meta['index']}"
            )
            try:
                chunk_data = await self._redis.get(chunk_key)
                if chunk_data is None:
                    raise InvalidSessionStateError(
                        session_id=session_id,
                        current_state=f"chunk {chunk_meta['index']} not found in Redis",
                        operation="retrieve_chunks",
                    )
                chunks.append(chunk_data)
            except Exception as e:
                if isinstance(e, InvalidSessionStateError):
                    raise
                raise InfrastructureError(
                    f"Failed to retrieve chunk {chunk_meta['index']} from Redis: {str(e)}"
                ) from e

        return chunks

    async def _cleanup_chunks(
        self, workspace_id: UUID, session_id: UUID, manifest: list[dict[str, Any]]
    ) -> None:
        """Delete chunk data from Redis after successful assembly.

        Args:
            workspace_id: Workspace UUID
            session_id: Session UUID
            manifest: Chunk manifest from session

        Raises:
            Exception: If Redis operation fails (logged, not fatal)
        """
        for chunk_meta in manifest:
            chunk_key = (
                f"chunk:workspace_{workspace_id}:session_{session_id}:index_{chunk_meta['index']}"
            )
            try:
                await self._redis.delete(chunk_key)
            except Exception as e:
                # Log but continue - other chunks should still be cleaned up
                logger.warning(
                    "chunk_delete_failed",
                    workspace_id=str(workspace_id),
                    session_id=str(session_id),
                    chunk_index=chunk_meta["index"],
                    error=str(e),
                )
