"""Redis key builder for workspace-scoped isolation.

Implements workspace-scoped key generation for multi-tenant isolation (FR26, NFR-S5).
All Redis keys are scoped to workspace_id to prevent cross-tenant data leakage.

Key Patterns (Implementation Pattern #2):
- Session:    session:workspace_{workspace_id}:document_{document_id}
- Dedup:      dedup:workspace_{workspace_id}
- Rate Limit: ratelimit:workspace_{workspace_id}:active_uploads

Security Guarantee:
No Redis key can be created without workspace scope. All functions validate
workspace_id is present before generating keys.

Integration Points:
- Story 3.2: Redis Session Store will use session_key()
- Story 3.3: Rate Limiter will use rate_limit_key()
- Future: Deduplication Service will use dedup_key()

Examples:
    >>> from uuid import UUID
    >>> ws = UUID('12345678-1234-5678-1234-567812345678')
    >>> doc = UUID('87654321-8765-4321-8765-432187654321')
    >>> session_key(ws, doc)
    'session:workspace_12345678-1234-5678-1234-567812345678:document_87654321-8765-4321-8765-432187654321'
    >>> dedup_key(ws)
    'dedup:workspace_12345678-1234-5678-1234-567812345678'
    >>> rate_limit_key(ws)
    'ratelimit:workspace_12345678-1234-5678-1234-567812345678:active_uploads'
"""

from uuid import UUID


def _validate_workspace_id(workspace_id: UUID | None) -> None:
    """Validate workspace_id is present and valid UUID.

    Args:
        workspace_id: Workspace UUID to validate

    Raises:
        ValueError: If workspace_id is None (isolation requirement violated)
        ValueError: If workspace_id is NIL UUID (00000000-0000-0000-0000-000000000000)
        TypeError: If workspace_id is not a UUID
    """
    if workspace_id is None:
        raise ValueError("workspace_id cannot be None - required for isolation")
    if not isinstance(workspace_id, UUID):
        raise TypeError(f"workspace_id must be UUID, got {type(workspace_id).__name__}")
    if workspace_id.int == 0:
        raise ValueError("NIL UUID not allowed for workspace_id")


def _validate_document_id(document_id: UUID | None) -> None:
    """Validate document_id is present and valid UUID.

    Args:
        document_id: Document UUID to validate

    Raises:
        ValueError: If document_id is None
        ValueError: If document_id is NIL UUID (00000000-0000-0000-0000-000000000000)
        TypeError: If document_id is not a UUID
    """
    if document_id is None:
        raise ValueError("document_id cannot be None")
    if not isinstance(document_id, UUID):
        raise TypeError(f"document_id must be UUID, got {type(document_id).__name__}")
    if document_id.int == 0:
        raise ValueError("NIL UUID not allowed for document_id")


def session_key(workspace_id: UUID, document_id: UUID) -> str:
    """Generate workspace-scoped session key for upload session.

    Session keys isolate upload state by workspace and document. Two workspaces
    with the same document_id will have completely separate session state.

    Pattern: session:workspace_{workspace_id}:document_{document_id}

    Args:
        workspace_id: Workspace UUID for isolation boundary (FR26)
        document_id: Document UUID for session identification

    Returns:
        Redis key string with workspace and document identifiers

    Raises:
        ValueError: If workspace_id or document_id is None or NIL UUID
        TypeError: If workspace_id or document_id is not a UUID

    TTL:
        Caller must set TTL (typically 86400 seconds / 24 hours).
        Keys without TTL will persist indefinitely causing memory leaks.

    Examples:
        >>> from uuid import UUID
        >>> ws = UUID('12345678-1234-5678-1234-567812345678')
        >>> doc = UUID('87654321-8765-4321-8765-432187654321')
        >>> session_key(ws, doc)
        'session:workspace_12345678-1234-5678-1234-567812345678:document_87654321-8765-4321-8765-432187654321'

    References:
        - FR26: Complete data isolation between workspaces
        - NFR-S5: Multi-tenant isolation at Redis key level
        - Story 3.2: Redis Session Store (primary consumer)
    """
    _validate_workspace_id(workspace_id)
    _validate_document_id(document_id)
    return f"session:workspace_{workspace_id}:document_{document_id}"


def dedup_key(workspace_id: UUID) -> str:
    """Generate workspace-scoped deduplication key.

    Dedup keys scope SHA-256 fingerprint lookups to workspace. Two workspaces
    can upload the same file independently without triggering deduplication.

    Pattern: dedup:workspace_{workspace_id}

    Args:
        workspace_id: Workspace UUID for isolation boundary (FR26)

    Returns:
        Redis key string for deduplication hash storage

    Raises:
        ValueError: If workspace_id is None or NIL UUID
        TypeError: If workspace_id is not a UUID

    TTL:
        No TTL required - deduplication hashes persist for workspace lifetime.
        Cleanup handled by workspace deletion operations.

    Examples:
        >>> from uuid import UUID
        >>> ws = UUID('12345678-1234-5678-1234-567812345678')
        >>> dedup_key(ws)
        'dedup:workspace_12345678-1234-5678-1234-567812345678'

    Storage Schema:
        Type: Redis Hash
        Field: {sha256_checksum}
        Value: JSON {file_id, s3_path, size, uploaded_at}
        Operations: HEXISTS (check), HGET (retrieve), HSET (store)

    References:
        - FR26: Deduplication scope within workspace boundary
        - NFR-S5: Multi-tenant isolation
        - Future Story: Deduplication Service (primary consumer)
    """
    _validate_workspace_id(workspace_id)
    return f"dedup:workspace_{workspace_id}"


def rate_limit_key(workspace_id: UUID) -> str:
    """Generate workspace-scoped rate limit counter key.

    Rate limit keys track concurrent upload count per workspace. Each workspace
    has independent rate limits (default: 10 concurrent uploads).

    Pattern: ratelimit:workspace_{workspace_id}:active_uploads

    Args:
        workspace_id: Workspace UUID for isolation boundary (FR26)

    Returns:
        Redis key string for rate limit counter storage

    Raises:
        ValueError: If workspace_id is None or NIL UUID
        TypeError: If workspace_id is not a UUID

    TTL:
        No TTL required - counter persists for workspace lifetime.
        Counter is incremented/decremented as uploads start/complete.

    Examples:
        >>> from uuid import UUID
        >>> ws = UUID('12345678-1234-5678-1234-567812345678')
        >>> rate_limit_key(ws)
        'ratelimit:workspace_12345678-1234-5678-1234-567812345678:active_uploads'

    Storage Schema:
        Type: Redis String (integer counter)
        Operations: INCR (on upload start), DECR (on complete/abort)
        Limit: MAX_CONCURRENT_UPLOADS per workspace (default: 10)

    References:
        - FR26: Rate limits enforced per workspace
        - NFR-S5: Multi-tenant isolation
        - Story 3.3: Rate Limiter (primary consumer)
    """
    _validate_workspace_id(workspace_id)
    return f"ratelimit:workspace_{workspace_id}:active_uploads"
