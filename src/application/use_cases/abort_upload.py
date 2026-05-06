"""Use case for aborting active upload sessions.

This module implements the AbortUploadUseCase, which orchestrates the
complete abort flow including session validation, status update, deletion,
and rate limit counter decrement.
"""

from uuid import UUID

from src.domain.exceptions import (
    InfrastructureError,
    SessionNotFoundError,
    WorkspaceMismatchError,
)
from src.domain.protocols.rate_limiter import IRateLimiter
from src.domain.protocols.session_store import ISessionStore
from src.domain.value_objects.session_status import SessionStatus


class AbortUploadUseCase:
    """Use case for aborting active upload sessions.

    This use case orchestrates the complete abort flow:
    1. Validate session exists and belongs to workspace
    2. Update status to ABORTED (audit trail before deletion)
    3. Delete session from Redis (cleanup all state)
    4. Decrement rate limit counter (free up workspace capacity)

    Business Rules:
        - Session MUST exist to be aborted (404 if not found)
        - Session MUST belong to requesting workspace (403 if mismatch)
        - Status set to ABORTED before deletion (enables logging)
        - Rate limit counter MUST be decremented (prevent leaks)
        - Delete operation is idempotent (safe to call multiple times)

    Security:
        - Workspace ownership validated (session.workspace_id vs JWT)
        - Only OWNER role can abort (enforced by endpoint RBAC)
        - No cross-workspace session access possible

    Counter Management:
        - Rate limit counter incremented on session creation (Story 3.4)
        - Counter decremented here on explicit abort
        - Future: Counter also decremented on complete/fail (Story 5.8)
        - Critical: Missing decrements cause permanent rate limit hits

    Integration Points:
        - Story 3.2: Uses ISessionStore for get, update, delete operations
        - Story 3.3: Uses IRateLimiter for counter decrement
        - Story 3.1: Uses SessionStatus.ABORTED for status transition
        - Story 2.4: Called after RBAC middleware validates OWNER role

    Attributes:
        _session_store: Session store protocol implementation
        _rate_limiter: Rate limiter protocol implementation

    Examples:
        >>> # Create use case with dependencies
        >>> use_case = AbortUploadUseCase(
        ...     session_store=redis_session_store,
        ...     rate_limiter=redis_rate_limiter
        ... )
        >>>
        >>> # Abort upload session
        >>> await use_case.execute(
        ...     workspace_id=uuid4(),
        ...     session_id=uuid4()
        ... )
        >>> # Session deleted, counter decremented, returns None
    """

    def __init__(
        self,
        session_store: ISessionStore,
        rate_limiter: IRateLimiter,
    ) -> None:
        """Initialize the use case with protocol dependencies.

        Args:
            session_store: Session store protocol implementation for retrieving,
                updating, and deleting upload session state
            rate_limiter: Rate limiter protocol implementation for decrementing
                workspace concurrent upload counter
        """
        self._session_store = session_store
        self._rate_limiter = rate_limiter

    async def execute(self, workspace_id: UUID, session_id: UUID) -> None:
        """Execute the abort upload use case.

        Orchestrates the complete abort flow:
        1. Retrieve session from Redis
        2. Validate session exists and belongs to workspace
        3. Update status to ABORTED (audit trail)
        4. Delete session from Redis (cleanup)
        5. Decrement rate limit counter (free capacity)

        Args:
            workspace_id: Workspace UUID from JWT claims (for validation)
            session_id: Upload session UUID from path parameter

        Raises:
            SessionNotFoundError: If session doesn't exist or expired.
                Endpoint converts to 404 Session Not Found.
            WorkspaceMismatchError: If session belongs to different workspace.
                Endpoint converts to 403 Forbidden (security violation).
            InfrastructureError: If Redis connection fails.
                Endpoint converts to 503 Service Unavailable.

        Returns:
            None: 204 No Content has no response body

        Flow Details:
            1. session = await session_store.get_session(workspace_id, session_id)
               - Returns None if session doesn't exist or expired (Redis TTL)
               - Raises InfrastructureError if Redis connection fails

            2. if session is None: raise SessionNotFoundError
               - Session never existed or already expired (24h TTL)
               - Endpoint converts to 404 with helpful error message

            3. if session.workspace_id != workspace_id: raise WorkspaceMismatchError
               - Session belongs to different workspace (security check)
               - Endpoint converts to 403 Forbidden (access denied)
               - This should NEVER happen if JWT validation is correct
               - Include this check as defense-in-depth

            4. session.status = SessionStatus.ABORTED
               await session_store.update_session(session)
               - Update status BEFORE deletion (audit trail)
               - Enables structured logging to capture abort event
               - If update_session fails, session remains IN_PROGRESS (safe)

            5. await session_store.delete_session(workspace_id, session_id)
               - Delete session from Redis (cleanup all state)
               - Idempotent operation (safe to call multiple times)
               - If this fails, session still marked ABORTED (partial cleanup)

            6. await rate_limiter.decrement(workspace_id)
               - Free up rate limit slot for workspace
               - CRITICAL: Missing this causes permanent rate limit hits
               - If this fails, counter leaks (operational issue, not user-facing)

        Error Recovery:
            - If steps 4-6 fail, session may be partially cleaned up
            - Session marked ABORTED → future attempts to use it fail
            - Rate limit counter leak → operators manually reset via admin API
            - Redis TTL eventually cleans up orphaned sessions (24h)

        Examples:
            >>> # Success case
            >>> await use_case.execute(workspace_id, session_id)
            # Session deleted, counter decremented, returns None
            >>>
            >>> # Session not found
            >>> await use_case.execute(workspace_id, uuid4())
            # Raises SessionNotFoundError → 404 Session Not Found
            >>>
            >>> # Workspace mismatch (should never happen with correct JWT)
            >>> await use_case.execute(wrong_workspace_id, session_id)
            # Raises WorkspaceMismatchError → 403 Forbidden
        """
        # Step 0: Validate input parameters
        if workspace_id is None or session_id is None:
            raise ValueError("workspace_id and session_id must not be None")

        # Step 1: Retrieve session from Redis
        session = await self._session_store.get_session(workspace_id, session_id)

        # Step 2: Validate session exists
        if session is None:
            raise SessionNotFoundError(f"Upload session {session_id} not found or expired")

        # Step 2b: Check if session is already in terminal state (idempotency + race prevention)
        # If already ABORTED/COMPLETE/FAILED, treat as not found to prevent double decrement
        if session.status in (SessionStatus.ABORTED, SessionStatus.COMPLETE, SessionStatus.FAILED):
            raise SessionNotFoundError(f"Upload session {session_id} not found or expired")

        # Step 3: Validate session belongs to workspace (defense-in-depth)
        if session.workspace_id != workspace_id:
            raise WorkspaceMismatchError(
                resource_id=session_id,
                resource_type="upload_session",
                expected_workspace_id=workspace_id,
                actual_workspace_id=session.workspace_id,
            )

        # Step 4: Update status to ABORTED (audit trail before deletion)
        # Note: Mutating session in-place is acceptable here as we immediately persist
        session.status = SessionStatus.ABORTED
        await self._session_store.update_session(session)

        # Step 5: Delete session from Redis (cleanup all state)
        await self._session_store.delete_session(workspace_id, session_id)

        # Step 6: Decrement rate limit counter (free up workspace capacity)
        # Partial failure handling: If decrement fails, session is already deleted
        # Counter leak is logged at infrastructure layer; Epic 6 metrics will track
        try:
            await self._rate_limiter.decrement(workspace_id)
        except InfrastructureError:
            # Session deleted successfully but counter decrement failed
            # This creates a counter leak (workspace loses one upload slot)
            # Infrastructure layer logs error; operators monitor via metrics (Epic 6)
            # Don't re-raise - partial success is acceptable (session cleanup succeeded)
            pass
