"""Redis implementation of session store protocol.

This module implements the ISessionStore protocol using Redis as the storage
backend. Sessions are stored as Redis Hashes with 24-hour TTL for automatic
cleanup.

Key Features:
    - Workspace-scoped isolation via key patterns
    - 24-hour automatic expiry (TTL management)
    - Atomic operations (HSET, HGETALL, EXISTS, DEL)
    - JSON serialization for complex fields (chunk_manifest)
    - Comprehensive error handling and logging

Storage Format:
    - Data Structure: Redis Hash
    - Key Pattern: session:workspace_{workspace_id}:upload_{session_id}
    - Hash Fields: session_id, workspace_id, filename, size, mime_type,
      sha256_checksum, offset, status, created_at, expires_at, chunk_manifest

Integration Points:
    - Story 2.3: Uses session_key() from key_builder for workspace isolation
    - Story 3.1: Stores/retrieves UploadSession domain entities
    - Story 3.3: Enables rate limiting via session counting
    - Story 3.4+: Used by upload session use cases

Examples:
    >>> import redis.asyncio as aioredis
    >>> from uuid import uuid4
    >>> from datetime import datetime, timedelta, timezone
    >>>
    >>> # Initialize Redis client and session store
    >>> redis_client = aioredis.from_url("redis://localhost:6379")
    >>> session_store = RedisSessionStore(redis_client)
    >>>
    >>> # Create session
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
    >>> await session_store.create_session(session)
    >>>
    >>> # Retrieve and update session
    >>> retrieved = await session_store.get_session(
    ...     session.workspace_id,
    ...     session.session_id
    ... )
    >>> if retrieved is not None:
    ...     retrieved.offset = 512
    ...     await session_store.update_session(retrieved)
    >>>
    >>> # Delete session
    >>> await session_store.delete_session(
    ...     session.workspace_id,
    ...     session.session_id
    ... )
"""

import json
import logging
from datetime import datetime
from uuid import UUID

import redis.asyncio as aioredis
import redis.exceptions

from src.domain.entities import UploadSession
from src.domain.exceptions import (
    InfrastructureError,
    SerializationError,
    SessionNotFoundError,
)
from src.domain.protocols.session_store import ExpiryMetadata
from src.domain.value_objects import SessionStatus, SHA256Hash
from src.infrastructure.redis.key_builder import session_key


logger = logging.getLogger(__name__)


class RedisSessionStore:
    """Redis implementation of session store protocol.

    Stores upload sessions as Redis Hashes with 24-hour TTL.
    All operations are atomic using native Redis commands (no Lua).

    Key Pattern (from key_builder.py):
        session:workspace_{workspace_id}:upload_{session_id}

    Hash Fields:
        - session_id: UUID string
        - workspace_id: UUID string
        - filename: original filename
        - size: total file size (bytes)
        - mime_type: file MIME type
        - sha256_checksum: SHA-256 hash string
        - offset: current verified offset (bytes)
        - status: SessionStatus enum value
        - created_at: ISO 8601 timestamp with timezone
        - expires_at: ISO 8601 timestamp with timezone
        - chunk_manifest: JSON array of chunk metadata

    TTL Management:
        Sessions automatically expire 24 hours after creation.
        TTL is set atomically during create_session via EXPIRE command.

    Error Handling:
        - Redis connection errors: log and raise InfrastructureError
        - Not found: return None (get_session) or raise SessionNotFoundError (update)
        - Deserialization errors: log and raise SerializationError

    Thread Safety:
        This class is thread-safe when used with asyncio (async/await).
        The underlying aioredis client manages connection pooling and
        concurrent access safely.

    Examples:
        >>> redis_client = aioredis.from_url("redis://localhost:6379")
        >>> store = RedisSessionStore(redis_client)
        >>> await store.create_session(session)
    """

    def __init__(self, redis_client: aioredis.Redis) -> None:
        """Initialize Redis session store.

        Args:
            redis_client: Configured aioredis.Redis client instance.
                Must support async operations and be properly connected.
        """
        self._redis = redis_client
        self._ttl_seconds = 86400  # 24 hours per FR10

    async def create_session(self, session: UploadSession) -> None:
        """Create a new upload session with 24-hour TTL.

        Stores the session state in Redis as a Hash with automatic expiry
        after 24 hours. All fields are serialized appropriately for storage.

        Also creates expiry metadata with 7-day TTL to support enhanced error
        responses when clients attempt to access expired sessions.

        Args:
            session: UploadSession entity to persist.

        Raises:
            InfrastructureError: If Redis operation fails (connection error, timeout).
            SerializationError: If session data cannot be serialized.
        """
        key = session_key(session.workspace_id, session.session_id)
        expiry_metadata_key = f"session:expiry:{session.session_id}"

        try:
            # Serialize UploadSession to Redis Hash format
            data = self._serialize_session(session)

            # Prepare expiry metadata for graceful error handling
            # This allows us to distinguish expired sessions from never-existed for 7 days
            expiry_metadata = {
                "session_id": str(session.session_id),
                "workspace_id": str(session.workspace_id),
                "expires_at": session.expires_at.isoformat(),
                "filename": session.filename,
            }

            # Store all fields and set TTL atomically using pipeline
            # Pipeline ensures both HSET and EXPIRE execute together,
            # preventing session from persisting without TTL if process crashes
            pipeline = self._redis.pipeline()

            # Store session with 24-hour TTL
            pipeline.hset(key, mapping=data)
            pipeline.expire(key, self._ttl_seconds)

            # Store expiry metadata with 7-day TTL (604800 seconds)
            # This enables enhanced error responses for up to 7 days after expiry
            pipeline.hset(expiry_metadata_key, mapping=expiry_metadata)
            pipeline.expire(expiry_metadata_key, 604800)

            await pipeline.execute()

            logger.info(
                "Session created",
                extra={
                    "workspace_id": str(session.workspace_id),
                    "session_id": str(session.session_id),
                    "ttl_seconds": self._ttl_seconds,
                    "expiry_metadata_ttl": 604800,
                },
            )

        except redis.exceptions.RedisError as e:
            logger.error(
                "Redis operation failed during create_session",
                extra={
                    "workspace_id": str(session.workspace_id),
                    "session_id": str(session.session_id),
                    "error": str(e),
                },
            )
            raise InfrastructureError(f"Failed to create session: {e}") from e

        except (TypeError, ValueError) as e:
            logger.error(
                "Serialization failed during create_session",
                extra={
                    "workspace_id": str(session.workspace_id),
                    "session_id": str(session.session_id),
                    "error": str(e),
                },
            )
            raise SerializationError(f"Failed to serialize session: {e}") from e

    async def get_session(
        self,
        workspace_id: UUID,
        session_id: UUID,
    ) -> UploadSession | None:
        """Retrieve an upload session by workspace and session ID.

        Args:
            workspace_id: Workspace UUID for isolation boundary.
            session_id: Session UUID to retrieve.

        Returns:
            UploadSession entity if found, None if not found or expired.

        Raises:
            InfrastructureError: If Redis operation fails.
            SerializationError: If stored data is corrupted or invalid.
        """
        key = session_key(workspace_id, session_id)

        try:
            # Retrieve all hash fields
            raw_data = await self._redis.hgetall(key)  # type: ignore[misc]

            # Empty dict means key doesn't exist or expired
            if not raw_data:
                logger.debug(
                    "Session not found",
                    extra={
                        "workspace_id": str(workspace_id),
                        "session_id": str(session_id),
                    },
                )
                return None

            # Decode bytes to strings (Redis returns bytes)
            data = {
                k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                for k, v in raw_data.items()
            }

            # Deserialize to UploadSession
            session = self._deserialize_session(data)

            logger.debug(
                "Session retrieved",
                extra={
                    "workspace_id": str(workspace_id),
                    "session_id": str(session_id),
                    "offset": session.offset,
                    "status": session.status.value,
                },
            )

            return session

        except redis.exceptions.RedisError as e:
            logger.error(
                "Redis operation failed during get_session",
                extra={
                    "workspace_id": str(workspace_id),
                    "session_id": str(session_id),
                    "error": str(e),
                },
            )
            raise InfrastructureError(f"Failed to retrieve session: {e}") from e

        except (KeyError, ValueError, json.JSONDecodeError) as e:
            logger.error(
                "Deserialization failed during get_session",
                extra={
                    "workspace_id": str(workspace_id),
                    "session_id": str(session_id),
                    "error": str(e),
                },
            )
            raise SerializationError(f"Invalid session data: {e}") from e

    async def get_session_with_expiry_info(
        self,
        workspace_id: UUID,
        session_id: UUID,
    ) -> tuple[UploadSession | None, ExpiryMetadata | None]:
        """Retrieve session with expiry metadata for enhanced error responses.

        This method supports graceful session expiry handling by distinguishing
        between sessions that expired recently (within 7 days) vs sessions that
        never existed or expired long ago.

        Args:
            workspace_id: Workspace UUID for isolation boundary.
            session_id: Session UUID to retrieve.

        Returns:
            Tuple of (session, expiry_metadata):
            - (session, None): Session exists and is active
            - (None, metadata): Session expired within last 7 days, metadata available
            - (None, None): Session never existed or expired >7 days ago

        Raises:
            InfrastructureError: If Redis operation fails.
            SerializationError: If stored data is corrupted.

        Examples:
            >>> # Active session
            >>> session, metadata = await store.get_session_with_expiry_info(ws_id, sess_id)
            >>> if session is not None:
            ...     # Session is active, use it normally
            ...     print(f"Offset: {session.offset}")
            >>>
            >>> # Expired session
            >>> session, metadata = await store.get_session_with_expiry_info(ws_id, sess_id)
            >>> if session is None and metadata is not None:
            ...     # Session expired, return SESSION_EXPIRED error with metadata
            ...     expired_at = metadata["expired_at"]
            ...     print(f"Session expired at {expired_at}")
            >>>
            >>> # Never existed
            >>> session, metadata = await store.get_session_with_expiry_info(ws_id, sess_id)
            >>> if session is None and metadata is None:
            ...     # Session never existed, return SESSION_NOT_FOUND error
            ...     print("Session not found")
        """
        key = session_key(workspace_id, session_id)
        expiry_metadata_key = f"session:expiry:{session_id}"

        try:
            # Try to get session first
            raw_session_data = await self._redis.hgetall(key)  # type: ignore[misc]

            if raw_session_data:
                # Session exists and is active
                data = {
                    k.decode() if isinstance(k, bytes) else k: v.decode()
                    if isinstance(v, bytes)
                    else v
                    for k, v in raw_session_data.items()
                }
                session = self._deserialize_session(data)

                logger.debug(
                    "Session retrieved (active)",
                    extra={
                        "workspace_id": str(workspace_id),
                        "session_id": str(session_id),
                        "offset": session.offset,
                    },
                )

                return (session, None)

            # Session not found - check if expired (expiry metadata exists)
            raw_expiry_data = await self._redis.hgetall(expiry_metadata_key)  # type: ignore[misc]

            if raw_expiry_data:
                # Session expired, metadata available
                # Decode bytes to strings for all fields
                decoded_data = {
                    k.decode() if isinstance(k, bytes) else k: v.decode()
                    if isinstance(v, bytes)
                    else v
                    for k, v in raw_expiry_data.items()
                }

                # Construct typed metadata dict with explicit keys
                expiry_metadata: ExpiryMetadata = {
                    "session_id": decoded_data.get("session_id", ""),
                    "workspace_id": decoded_data.get("workspace_id", ""),
                    "expires_at": decoded_data.get("expires_at", ""),
                    "filename": decoded_data.get("filename", ""),
                }

                # Validate workspace isolation - metadata workspace_id must match request
                metadata_workspace_id = expiry_metadata.get("workspace_id")
                if metadata_workspace_id != str(workspace_id):
                    logger.warning(
                        "Workspace isolation violation - expiry metadata workspace mismatch",
                        extra={
                            "request_workspace_id": str(workspace_id),
                            "metadata_workspace_id": metadata_workspace_id,
                            "session_id": str(session_id),
                        },
                    )
                    # Treat as not found to prevent cross-workspace data leakage
                    return (None, None)

                logger.debug(
                    "Session expired (metadata available)",
                    extra={
                        "workspace_id": str(workspace_id),
                        "session_id": str(session_id),
                        "expired_at": expiry_metadata.get("expires_at"),
                    },
                )

                return (None, expiry_metadata)

            # Session never existed or expired >7 days ago
            logger.debug(
                "Session not found (never existed or expired >7 days ago)",
                extra={
                    "workspace_id": str(workspace_id),
                    "session_id": str(session_id),
                },
            )

            return (None, None)

        except redis.exceptions.RedisError as e:
            logger.error(
                "Redis operation failed during get_session_with_expiry_info",
                extra={
                    "workspace_id": str(workspace_id),
                    "session_id": str(session_id),
                    "error": str(e),
                },
            )
            raise InfrastructureError(f"Failed to retrieve session with expiry info: {e}") from e

        except (KeyError, ValueError, json.JSONDecodeError) as e:
            logger.error(
                "Deserialization failed during get_session_with_expiry_info",
                extra={
                    "workspace_id": str(workspace_id),
                    "session_id": str(session_id),
                    "error": str(e),
                },
            )
            raise SerializationError(f"Invalid session or expiry data: {e}") from e

    async def update_session(self, session: UploadSession) -> None:
        """Update an existing upload session.

        Updates all fields of the session. TTL is NOT reset (preserves
        original expiry time).

        Args:
            session: UploadSession entity with updated fields.

        Raises:
            SessionNotFoundError: If session doesn't exist or has expired.
            InfrastructureError: If Redis operation fails.
            SerializationError: If session data cannot be serialized.
        """
        key = session_key(session.workspace_id, session.session_id)

        try:
            # Check if session exists and has valid TTL
            # TTL returns: >0 if key exists with TTL, -2 if key doesn't exist,
            # -1 if key exists without expiry (shouldn't happen, but handle it)
            ttl = await self._redis.ttl(key)
            if ttl == -2:
                raise SessionNotFoundError(
                    f"Session not found: workspace_id={session.workspace_id}, "
                    f"session_id={session.session_id}"
                )
            if ttl == -1:
                # Key exists but has no TTL (data corruption or race condition)
                # Log error and proceed with update, but flag as anomaly
                logger.error(
                    "Session exists without TTL (data corruption)",
                    extra={
                        "workspace_id": str(session.workspace_id),
                        "session_id": str(session.session_id),
                    },
                )

            # Serialize UploadSession to Redis Hash format
            data = self._serialize_session(session)

            # Update all fields atomically (preserves TTL)
            # HSET on existing key preserves the existing TTL
            await self._redis.hset(key, mapping=data)  # type: ignore[misc]

            logger.info(
                "Session updated",
                extra={
                    "workspace_id": str(session.workspace_id),
                    "session_id": str(session.session_id),
                    "offset": session.offset,
                    "status": session.status.value,
                },
            )

        except SessionNotFoundError:
            # Re-raise domain exception as-is
            raise

        except redis.exceptions.RedisError as e:
            logger.error(
                "Redis operation failed during update_session",
                extra={
                    "workspace_id": str(session.workspace_id),
                    "session_id": str(session.session_id),
                    "error": str(e),
                },
            )
            raise InfrastructureError(f"Failed to update session: {e}") from e

        except (TypeError, ValueError) as e:
            logger.error(
                "Serialization failed during update_session",
                extra={
                    "workspace_id": str(session.workspace_id),
                    "session_id": str(session.session_id),
                    "error": str(e),
                },
            )
            raise SerializationError(f"Failed to serialize session: {e}") from e

    async def delete_session(
        self,
        workspace_id: UUID,
        session_id: UUID,
    ) -> None:
        """Delete an upload session from storage.

        This operation is idempotent - deleting a non-existent session does
        not raise an exception. Also removes expiry metadata to prevent
        confusion when user explicitly aborts a session.

        Args:
            workspace_id: Workspace UUID for isolation boundary.
            session_id: Session UUID to delete.

        Raises:
            InfrastructureError: If Redis operation fails.
        """
        key = session_key(workspace_id, session_id)
        expiry_metadata_key = f"session:expiry:{session_id}"

        try:
            # Delete both session and expiry metadata keys
            deleted_count = await self._redis.delete(key, expiry_metadata_key)

            if deleted_count == 0:
                logger.warning(
                    "Session delete attempted but key didn't exist (idempotent)",
                    extra={
                        "workspace_id": str(workspace_id),
                        "session_id": str(session_id),
                    },
                )
            else:
                logger.info(
                    "Session deleted (including expiry metadata)",
                    extra={
                        "workspace_id": str(workspace_id),
                        "session_id": str(session_id),
                        "keys_deleted": deleted_count,
                    },
                )

        except redis.exceptions.RedisError as e:
            logger.error(
                "Redis operation failed during delete_session",
                extra={
                    "workspace_id": str(workspace_id),
                    "session_id": str(session_id),
                    "error": str(e),
                },
            )
            raise InfrastructureError(f"Failed to delete session: {e}") from e

    def _serialize_session(self, session: UploadSession) -> dict[str, str]:
        """Serialize UploadSession to Redis Hash format.

        All values are converted to strings since Redis Hashes store
        string values.

        Args:
            session: UploadSession entity to serialize.

        Returns:
            Dictionary mapping field names to string values.

        Raises:
            TypeError: If serialization fails.
            ValueError: If data cannot be serialized.
        """
        return {
            "session_id": str(session.session_id),
            "workspace_id": str(session.workspace_id),
            "filename": session.filename,
            "size": str(session.size),
            "mime_type": session.mime_type,
            "sha256_checksum": session.sha256_checksum.value,
            "offset": str(session.offset),
            "status": session.status.value,
            "created_at": session.created_at.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "chunk_manifest": json.dumps(session.chunk_manifest),
        }

    def _deserialize_session(self, data: dict[str, str]) -> UploadSession:
        """Deserialize Redis Hash data to UploadSession entity.

        Args:
            data: Dictionary of field names to string values.

        Returns:
            Reconstructed UploadSession entity.

        Raises:
            KeyError: If required field is missing.
            ValueError: If field value is invalid (bad UUID, datetime, etc).
            json.JSONDecodeError: If chunk_manifest JSON is invalid.
            SerializationError: If chunk_manifest is not a list.
        """
        # Parse and validate chunk_manifest
        chunk_manifest_raw = json.loads(data["chunk_manifest"])
        if not isinstance(chunk_manifest_raw, list):
            raise SerializationError(
                f"chunk_manifest must be a list, got {type(chunk_manifest_raw).__name__}"
            )

        return UploadSession(
            session_id=UUID(data["session_id"]),
            workspace_id=UUID(data["workspace_id"]),
            filename=data["filename"],
            size=int(data["size"]),
            mime_type=data["mime_type"],
            sha256_checksum=SHA256Hash(data["sha256_checksum"]),
            offset=int(data["offset"]),
            status=SessionStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            chunk_manifest=chunk_manifest_raw,
        )
