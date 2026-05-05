"""Session store protocol for upload session persistence.

This module defines the ISessionStore protocol, which specifies the contract
for persisting and retrieving upload session state. Implementations must
provide durable storage with workspace isolation and TTL management.

Protocol Contract:
    - All methods are async (storage operations are I/O bound)
    - Sessions MUST be isolated by workspace_id (security requirement FR26)
    - create_session MUST set 24-hour TTL (per FR10)
    - get_session returns None for non-existent sessions (no exception)
    - update_session raises SessionNotFoundError if session doesn't exist
    - delete_session is idempotent (no error if session doesn't exist)

Error Handling:
    - SessionNotFoundError: Raised when update targets non-existent session
    - InfrastructureError: Raised for storage system failures (connection, timeout)
    - SerializationError: Raised for data corruption or invalid format

TTL Requirements:
    - Sessions expire 24 hours after creation (86400 seconds)
    - TTL is set atomically during create_session
    - update_session MUST NOT reset TTL (preserve original expiry time)

Implementation Notes:
    - Implementations are typically in src/infrastructure/
    - Redis implementation: src/infrastructure/redis/session_store.py
    - Use dependency injection to swap implementations (testing, different backends)

Examples:
    >>> from uuid import uuid4
    >>> from datetime import datetime, timedelta, timezone
    >>>
    >>> # Create and store a session
    >>> session = UploadSession(
    ...     session_id=uuid4(),
    ...     workspace_id=uuid4(),
    ...     filename="doc.pdf",
    ...     size=1024,
    ...     mime_type="application/pdf",
    ...     sha256_checksum=SHA256Hash("a" * 64),
    ...     offset=0,
    ...     status=SessionStatus.PENDING,
    ...     created_at=datetime.now(timezone.utc),
    ...     expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    ...     chunk_manifest=[]
    ... )
    >>>
    >>> # Store session (sets 24-hour TTL)
    >>> await session_store.create_session(session)
    >>>
    >>> # Retrieve session
    >>> retrieved = await session_store.get_session(
    ...     session.workspace_id,
    ...     session.session_id
    ... )
    >>> assert retrieved is not None
    >>>
    >>> # Update session progress
    >>> retrieved.offset = 512
    >>> await session_store.update_session(retrieved)
    >>>
    >>> # Delete session
    >>> await session_store.delete_session(
    ...     session.workspace_id,
    ...     session.session_id
    ... )
"""

from typing import Protocol
from uuid import UUID

from src.domain.entities import UploadSession


class ISessionStore(Protocol):
    """Protocol for upload session persistence.

    Defines the contract for storing, retrieving, updating, and deleting
    upload session state. Implementations must provide workspace-scoped
    isolation, TTL management, and atomic operations.

    All methods are async to support non-blocking I/O operations with
    external storage systems (Redis, databases, etc.).

    Workspace Isolation:
        Every session is scoped to a workspace_id. Implementations MUST
        ensure sessions from different workspaces cannot access or
        interfere with each other (security requirement FR26).

    TTL Management:
        Sessions MUST expire 24 hours after creation (FR10). The TTL is
        set during create_session and MUST NOT be reset by update_session.
        Expired sessions are automatically removed by the storage system.

    Atomicity:
        Each method operates atomically. For example, update_session either
        updates all fields or fails entirely (no partial updates).

    Thread Safety:
        Implementations MUST be thread-safe and support concurrent access
        from multiple async tasks or processes.
    """

    async def create_session(self, session: UploadSession) -> None:
        """Create a new upload session with 24-hour TTL.

        Stores the session state in durable storage with automatic expiry
        after 24 hours (86400 seconds). The TTL is set atomically to prevent
        sessions from persisting indefinitely.

        Args:
            session: UploadSession entity to persist. Must have all required
                fields populated (session_id, workspace_id, filename, etc.).

        Raises:
            InfrastructureError: If storage system fails (connection error,
                timeout, disk full, etc.).
            SerializationError: If session data cannot be serialized to
                storage format.

        TTL Behavior:
            - TTL is set to 86400 seconds (24 hours) from now
            - After 24 hours, the session is automatically deleted
            - Calling create_session for existing session overwrites it
              and resets TTL (avoid this - use update_session instead)

        Notes:
            - This method does NOT validate session data (validation is
              domain layer responsibility)
            - session_id uniqueness is NOT enforced (caller must ensure
              uniqueness)
            - Workspace isolation is enforced via storage key patterns

        Examples:
            >>> session = UploadSession(...)
            >>> await session_store.create_session(session)
            # Session stored with 24-hour expiry
        """
        ...

    async def get_session(
        self,
        workspace_id: UUID,
        session_id: UUID,
    ) -> UploadSession | None:
        """Retrieve an upload session by workspace and session ID.

        Fetches the session state from storage. Returns None if the session
        doesn't exist or has expired (no exception raised for not found).

        Args:
            workspace_id: Workspace UUID for isolation boundary (required).
            session_id: Session UUID to retrieve (required).

        Returns:
            UploadSession entity if found, None if not found or expired.

        Raises:
            InfrastructureError: If storage system fails (connection error,
                timeout, etc.).
            SerializationError: If stored data is corrupted or cannot be
                deserialized into UploadSession.

        Workspace Isolation:
            Only sessions belonging to the specified workspace_id can be
            retrieved. Sessions from other workspaces with the same
            session_id are completely isolated (security requirement FR26).

        Expiry Handling:
            If the session has expired (TTL reached), the storage system
            automatically removes it and this method returns None. No
            explicit expiry check is needed.

        Examples:
            >>> # Retrieve existing session
            >>> session = await session_store.get_session(workspace_id, session_id)
            >>> if session is not None:
            ...     print(f"Offset: {session.offset}")
            >>>
            >>> # Non-existent session returns None
            >>> missing = await session_store.get_session(workspace_id, uuid4())
            >>> assert missing is None
        """
        ...

    async def update_session(self, session: UploadSession) -> None:
        """Update an existing upload session.

        Updates all fields of the session in storage. This is used to persist
        progress updates (offset changes, status transitions, chunk manifest
        additions) after each chunk upload.

        Args:
            session: UploadSession entity with updated fields. Must contain
                the same session_id and workspace_id as the original session.

        Raises:
            SessionNotFoundError: If the session doesn't exist or has expired.
                This indicates a logic error (trying to update non-existent
                session) or the session expired during processing.
            InfrastructureError: If storage system fails (connection error,
                timeout, etc.).
            SerializationError: If session data cannot be serialized.

        TTL Behavior:
            - The existing TTL is PRESERVED (not reset)
            - Session will still expire at the original expiry time
            - If you need to extend TTL, delete and recreate the session
              (typically not needed - 24 hours is sufficient)

        Atomicity:
            All fields are updated atomically. Either the entire update
            succeeds or the session remains unchanged (no partial updates).

        Examples:
            >>> # Update session after chunk upload
            >>> session = await session_store.get_session(workspace_id, session_id)
            >>> if session is not None:
            ...     session.offset += chunk_size
            ...     session.chunk_manifest.append(chunk_metadata)
            ...     await session_store.update_session(session)
            >>>
            >>> # Raises SessionNotFoundError if session expired
            >>> try:
            ...     await session_store.update_session(session)
            ... except SessionNotFoundError:
            ...     print("Session expired or doesn't exist")
        """
        ...

    async def delete_session(
        self,
        workspace_id: UUID,
        session_id: UUID,
    ) -> None:
        """Delete an upload session from storage.

        Removes the session permanently. This is used when a user explicitly
        aborts an upload or after successful completion (cleanup).

        Args:
            workspace_id: Workspace UUID for isolation boundary (required).
            session_id: Session UUID to delete (required).

        Raises:
            InfrastructureError: If storage system fails (connection error,
                timeout, etc.).

        Idempotency:
            This method is idempotent. Deleting a non-existent or already
            deleted session does NOT raise an exception. This simplifies
            cleanup logic and prevents errors in retry scenarios.

        Workspace Isolation:
            Only the session belonging to the specified workspace_id is
            deleted. Sessions from other workspaces with the same session_id
            are unaffected (security requirement FR26).

        Examples:
            >>> # Delete session after abort
            >>> await session_store.delete_session(workspace_id, session_id)
            >>>
            >>> # Deleting again is safe (idempotent)
            >>> await session_store.delete_session(workspace_id, session_id)
            # No exception raised
        """
        ...
