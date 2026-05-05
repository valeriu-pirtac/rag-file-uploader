"""Rate limiter protocol for per-workspace upload rate limiting.

This module defines the IRateLimiter protocol, which specifies the contract
for enforcing concurrent upload limits per workspace. Implementations must
provide atomic counter operations with workspace isolation.

Protocol Contract:
    - All methods are async (Redis/storage operations are I/O bound)
    - Rate limits MUST be isolated by workspace_id (FR26, NFR-S5)
    - check_and_increment MUST be atomic (check + increment together)
    - Counter MUST be decremented when uploads complete/abort
    - Counter persists for workspace lifetime (no TTL)

Error Handling:
    - RateLimitExceededError: Raised when workspace reaches concurrent limit
    - InfrastructureError: Raised for storage system failures (Redis connection, etc.)

Atomicity:
    - check_and_increment performs atomic check+increment operation
    - Race conditions possible with GET+INCR pattern (acceptable for v1)
    - Future improvement: Use Lua script or Redis transactions (WATCH/MULTI/EXEC)

Implementation Notes:
    - Redis implementation: src/application/services/rate_limiter.py
    - Counter key pattern: ratelimit:workspace_{workspace_id}:active_uploads
    - Default limit: MAX_CONCURRENT_UPLOADS = 10 per workspace

Examples:
    >>> from uuid import uuid4
    >>>
    >>> workspace_id = uuid4()
    >>>
    >>> # Check and increment (succeeds if below limit)
    >>> await rate_limiter.check_and_increment(workspace_id)
    >>>
    >>> # Decrement when upload completes
    >>> await rate_limiter.decrement(workspace_id)
    >>>
    >>> # Get current active uploads count
    >>> count = await rate_limiter.get_current_count(workspace_id)
    >>> print(f"Active uploads: {count}")
    >>>
    >>> # Reset counter (admin/testing operation)
    >>> await rate_limiter.reset(workspace_id)
"""

from typing import Protocol
from uuid import UUID


class IRateLimiter(Protocol):
    """Protocol for per-workspace upload rate limiting.

    Enforces maximum concurrent uploads per workspace using atomic counter
    operations. Each workspace has independent rate limit (default: 10).

    Workspace Isolation:
        Rate limits are scoped to workspace_id. Workspace A reaching its
        limit does NOT affect Workspace B (security requirement FR26).

    Counter Lifecycle:
        - Increment: On upload session creation (POST /v1/uploads)
        - Decrement: On session completion, failure, or abort
        - No TTL: Counter persists for workspace lifetime
        - Cleanup: On workspace deletion (future story)

    Atomicity Considerations:
        - check_and_increment should be atomic but may use GET+INCR
        - Race condition: Two requests might both pass check (limit+1 uploads)
        - Impact: Minor (1 extra upload beyond limit, acceptable for v1)
        - Future: Use Lua script or Redis transactions for true atomicity

    Monitoring:
        - get_current_count enables Prometheus metrics tracking
        - Alert if counter diverges from actual session count (leak detection)
    """

    async def check_and_increment(self, workspace_id: UUID) -> None:
        """Check rate limit and atomically increment counter if allowed.

        Verifies workspace has not exceeded MAX_CONCURRENT_UPLOADS limit.
        If below limit, increments counter atomically. If at/above limit,
        raises RateLimitExceededError without incrementing.

        IMPORTANT: This operation should be atomic but may use GET+INCR
        pattern which has race condition. Two concurrent requests might both
        pass check, resulting in limit+1 uploads. This is acceptable for v1.

        Args:
            workspace_id: Workspace UUID for rate limit scope

        Raises:
            RateLimitExceededError: If workspace has reached or exceeded
                max_concurrent_uploads limit. Includes current count, limit,
                and suggested retry_after_seconds in exception attributes.
            InfrastructureError: If storage system fails (Redis connection
                error, timeout, etc.).

        Usage:
            >>> # Before creating upload session
            >>> await rate_limiter.check_and_increment(workspace_id)
            >>> # If no exception, proceed with session creation
        """
        ...

    async def decrement(self, workspace_id: UUID) -> None:
        """Decrement active upload counter for workspace.

        Called when upload completes, fails, or is aborted to free up
        capacity for new uploads. Decrements counter atomically using
        Redis DECR command.

        Defensive: If counter becomes negative (shouldn't happen), logs
        warning and resets to 0. This handles edge cases like:
        - Decrement called on non-existent key (DECR returns -1)
        - Multiple decrements for same session (bug)
        - Manual counter manipulation

        Args:
            workspace_id: Workspace UUID for rate limit scope

        Raises:
            InfrastructureError: If storage system fails (Redis connection
                error, timeout, etc.).

        Usage:
            >>> # After upload completes/aborts
            >>> await rate_limiter.decrement(workspace_id)
        """
        ...

    async def get_current_count(self, workspace_id: UUID) -> int:
        """Get current number of active uploads for workspace.

        Returns the current value of the rate limit counter. Used for
        monitoring, metrics, and debugging. Does not modify counter.

        Args:
            workspace_id: Workspace UUID for rate limit scope

        Returns:
            Current number of active uploads (0 if counter doesn't exist)

        Raises:
            InfrastructureError: If storage system fails (Redis connection
                error, timeout, etc.).

        Usage:
            >>> count = await rate_limiter.get_current_count(workspace_id)
            >>> logger.info("Active uploads", workspace_id=workspace_id, count=count)
        """
        ...

    async def reset(self, workspace_id: UUID) -> None:
        """Reset rate limit counter to zero for workspace.

        Administrative operation to manually reset counter. Used for:
        - Testing and development
        - Recovery from counter leak (missed decrements)
        - Manual intervention by operators

        Args:
            workspace_id: Workspace UUID for rate limit scope

        Raises:
            InfrastructureError: If storage system fails (Redis connection
                error, timeout, etc.).

        Usage:
            >>> # Admin operation - reset workspace counter
            >>> await rate_limiter.reset(workspace_id)
            >>> logger.info("Rate limit counter reset", workspace_id=workspace_id)
        """
        ...
