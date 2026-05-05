"""Redis implementation of rate limiter protocol.

This module implements the IRateLimiter protocol using Redis atomic integer
operations (INCR/DECR) for per-workspace concurrent upload rate limiting.

Key Features:
    - Workspace-scoped isolation via key patterns
    - Atomic counter operations (INCR/DECR/GET/SET)
    - Configurable concurrent upload limits
    - Defensive programming (negative counter handling)
    - Comprehensive error handling and logging

Storage Format:
    - Data Structure: Redis Hash (field: active_uploads)
    - Key Pattern: ratelimit:workspace_{workspace_id}
    - Field: active_uploads
    - Operations: HINCRBY (atomic increment), HGET (query), HSET (reset)
    - No TTL: Counter persists for workspace lifetime

Rate Limiting Logic:
    - check_and_increment: HGET current count, if < limit then HINCRBY, else raise error
    - decrement: HINCRBY with -1 atomically
    - get_current_count: HGET counter value, return 0 if not exists
    - reset: HSET counter to 0 (admin operation)

Atomicity:
    - HINCRBY is atomic (single Redis command)
    - No race condition with proper implementation
    - HGET+HINCRBY still has race window, but HINCRBY itself is atomic

Integration Points:
    - Story 2.3: Uses rate_limit_key() from key_builder for workspace isolation
    - Story 1.4: Uses MAX_CONCURRENT_UPLOADS from AppSettings
    - Story 3.4: Used by InitiateUploadUseCase to enforce rate limits
    - Story 3.7+: Decrements counter when uploads complete/abort

Examples:
    >>> import redis.asyncio as aioredis
    >>> from uuid import uuid4
    >>> from src.infrastructure.config.settings import AppSettings
    >>>
    >>> # Initialize Redis client and rate limiter
    >>> redis_client = aioredis.from_url("redis://localhost:6379")
    >>> settings = AppSettings(max_concurrent_uploads=10)
    >>> rate_limiter = RedisRateLimiter(redis_client, settings)
    >>>
    >>> workspace_id = uuid4()
    >>>
    >>> # Check and increment (succeeds if below limit)
    >>> await rate_limiter.check_and_increment(workspace_id)  # Count: 1
    >>> await rate_limiter.check_and_increment(workspace_id)  # Count: 2
    >>>
    >>> # Get current count
    >>> count = await rate_limiter.get_current_count(workspace_id)
    >>> print(f"Active uploads: {count}")  # Active uploads: 2
    >>>
    >>> # Decrement when upload completes
    >>> await rate_limiter.decrement(workspace_id)  # Count: 1
    >>>
    >>> # Reset counter (admin operation)
    >>> await rate_limiter.reset(workspace_id)  # Count: 0
"""

import logging
from uuid import UUID

import redis.asyncio as aioredis
import redis.exceptions

from src.domain.exceptions import InfrastructureError, RateLimitExceededError
from src.infrastructure.config.settings import AppSettings
from src.infrastructure.redis.key_builder import rate_limit_field, rate_limit_key


logger = logging.getLogger(__name__)


class RedisRateLimiter:
    """Redis implementation of rate limiter protocol.

    Enforces per-workspace concurrent upload limits using Redis atomic
    integer operations (INCR/DECR). Rate limiting is workspace-scoped -
    each workspace has independent counter and limit.

    Key Pattern (from key_builder.py):
        ratelimit:workspace_{workspace_id} (hash key)
        Field: active_uploads

    Counter Management:
        - Increment: On upload session creation (POST /v1/uploads)
        - Decrement: On session completion, failure, or abort
        - No TTL: Counter persists for workspace lifetime
        - Cleanup: On workspace deletion (future story)

    Atomicity:
        - check_and_increment uses HGET+HINCRBY (HINCRBY is atomic)
        - HGET+check+HINCRBY still has race window between check and increment
        - HINCRBY itself guarantees atomic increment
        - Improved over GET+INCR but not fully atomic without Lua script

    Error Handling:
        - Redis connection errors: log and raise InfrastructureError
        - Limit exceeded: raise RateLimitExceededError with retry_after
        - Negative counter: log warning, reset to 0 (defensive programming)

    Monitoring:
        - get_current_count enables Prometheus metrics
        - Alert if counter diverges significantly from actual sessions

    Examples:
        >>> redis_client = aioredis.from_url("redis://localhost:6379")
        >>> settings = AppSettings(max_concurrent_uploads=10)
        >>> limiter = RedisRateLimiter(redis_client, settings)
        >>> await limiter.check_and_increment(workspace_id)
    """

    def __init__(self, redis_client: aioredis.Redis, settings: AppSettings) -> None:
        """Initialize Redis rate limiter.

        Args:
            redis_client: Configured aioredis.Redis client instance.
                Must support async operations and be properly connected.
            settings: Application settings with max_concurrent_uploads configured.

        Raises:
            ValueError: If redis_client is None or max_concurrent_uploads <= 0
        """
        if redis_client is None:
            raise ValueError("redis_client cannot be None")
        if settings.max_concurrent_uploads <= 0:
            raise ValueError("max_concurrent_uploads must be positive")

        self._redis = redis_client
        self._max_concurrent = settings.max_concurrent_uploads
        self._field = rate_limit_field()

    async def check_and_increment(self, workspace_id: UUID) -> None:
        """Check rate limit and atomically increment counter if allowed.

        Verifies workspace has not exceeded max_concurrent_uploads limit.
        If below limit, increments counter atomically. If at/above limit,
        raises RateLimitExceededError without incrementing.

        IMPORTANT: This operation uses GET+INCR which is NOT atomic.
        Race condition: Two concurrent requests might both pass check,
        resulting in limit+1 uploads. This is acceptable for v1.

        Args:
            workspace_id: Workspace UUID for rate limit scope

        Raises:
            RateLimitExceededError: If workspace has reached or exceeded
                max_concurrent_uploads limit. Includes current count, limit,
                and suggested retry_after_seconds in exception attributes.
            InfrastructureError: If Redis operation fails (connection error,
                timeout, etc.).
        """
        key = rate_limit_key(workspace_id)

        try:
            # HGET current count (None if field doesn't exist)
            current_bytes = await self._redis.hget(key, self._field)  # type: ignore[misc]
            current = 0 if current_bytes is None else int(current_bytes)

            logger.debug(
                "Rate limit check",
                extra={
                    "workspace_id": str(workspace_id),
                    "current_count": current,
                    "limit": self._max_concurrent,
                },
            )

            # Check if limit exceeded
            if current >= self._max_concurrent:
                logger.warning(
                    "Rate limit exceeded",
                    extra={
                        "workspace_id": str(workspace_id),
                        "current_count": current,
                        "limit": self._max_concurrent,
                    },
                )
                raise RateLimitExceededError(
                    workspace_id=str(workspace_id),
                    current_count=current,
                    limit=self._max_concurrent,
                    retry_after_seconds=60,
                )

            # Increment counter atomically using HINCRBY
            new_count = await self._redis.hincrby(key, self._field, 1)  # type: ignore[misc]

            logger.info(
                "Rate limit counter incremented",
                extra={
                    "workspace_id": str(workspace_id),
                    "old_count": current,
                    "new_count": new_count,
                    "limit": self._max_concurrent,
                },
            )

        except RateLimitExceededError:
            # Re-raise rate limit errors unchanged
            raise
        except redis.exceptions.RedisError as e:
            logger.error(
                "Redis operation failed in check_and_increment",
                extra={
                    "workspace_id": str(workspace_id),
                    "key": key,
                    "error": str(e),
                },
            )
            raise InfrastructureError(f"Rate limiter unavailable: {e}") from e
        except ValueError as e:
            # ValueError when parsing counter (e.g., Redis contains "not_a_number")
            logger.error(
                "Counter value parsing failed - corrupted data in Redis",
                extra={
                    "workspace_id": str(workspace_id),
                    "key": key,
                    "value": current_bytes,
                    "error": str(e),
                },
            )
            raise InfrastructureError(f"Rate limiter counter corrupted: {e}") from e

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
            InfrastructureError: If Redis operation fails (connection error,
                timeout, etc.).
        """
        key = rate_limit_key(workspace_id)

        try:
            # Decrement counter atomically using HINCRBY with -1
            new_count = await self._redis.hincrby(key, self._field, -1)  # type: ignore[misc]

            # Defensive: Handle negative counter
            if new_count < 0:
                logger.warning(
                    "Rate limit counter negative, resetting to 0",
                    extra={
                        "workspace_id": str(workspace_id),
                        "count": new_count,
                        "key": key,
                    },
                )
                await self._redis.hset(key, self._field, "0")  # type: ignore[misc]
                new_count = 0

            logger.info(
                "Rate limit counter decremented",
                extra={
                    "workspace_id": str(workspace_id),
                    "new_count": new_count,
                },
            )

        except redis.exceptions.RedisError as e:
            logger.error(
                "Redis operation failed in decrement",
                extra={
                    "workspace_id": str(workspace_id),
                    "key": key,
                    "error": str(e),
                },
            )
            raise InfrastructureError(f"Rate limiter unavailable: {e}") from e

    async def get_current_count(self, workspace_id: UUID) -> int:
        """Get current number of active uploads for workspace.

        Returns the current value of the rate limit counter. Used for
        monitoring, metrics, and debugging. Does not modify counter.

        Args:
            workspace_id: Workspace UUID for rate limit scope

        Returns:
            Current number of active uploads (0 if counter doesn't exist)

        Raises:
            InfrastructureError: If Redis operation fails (connection error,
                timeout, etc.).
        """
        key = rate_limit_key(workspace_id)

        try:
            # HGET counter value (None if field doesn't exist)
            count_bytes = await self._redis.hget(key, self._field)  # type: ignore[misc]
            count = 0 if count_bytes is None else int(count_bytes)

            # Defensive: Handle negative counter
            if count < 0:
                logger.warning(
                    "Rate limit counter corrupted (negative), resetting to 0",
                    extra={
                        "workspace_id": str(workspace_id),
                        "count": count,
                    },
                )
                await self._redis.hset(key, self._field, "0")  # type: ignore[misc]
                return 0

            logger.debug(
                "Rate limit counter queried",
                extra={
                    "workspace_id": str(workspace_id),
                    "count": count,
                },
            )

            return count

        except redis.exceptions.RedisError as e:
            logger.error(
                "Redis operation failed in get_current_count",
                extra={
                    "workspace_id": str(workspace_id),
                    "key": key,
                    "error": str(e),
                },
            )
            raise InfrastructureError(f"Rate limiter unavailable: {e}") from e
        except ValueError as e:
            # ValueError when parsing counter (e.g., Redis contains "not_a_number")
            logger.error(
                "Counter value parsing failed - corrupted data in Redis",
                extra={
                    "workspace_id": str(workspace_id),
                    "key": key,
                    "value": count_bytes,
                    "error": str(e),
                },
            )
            raise InfrastructureError(f"Rate limiter counter corrupted: {e}") from e

    async def reset(self, workspace_id: UUID) -> None:
        """Reset rate limit counter to zero for workspace.

        Administrative operation to manually reset counter. Used for:
        - Testing and development
        - Recovery from counter leak (missed decrements)
        - Manual intervention by operators

        Args:
            workspace_id: Workspace UUID for rate limit scope

        Raises:
            InfrastructureError: If Redis operation fails (connection error,
                timeout, etc.).
        """
        key = rate_limit_key(workspace_id)

        try:
            # Set counter to 0 using HSET
            await self._redis.hset(key, self._field, "0")  # type: ignore[misc]

            logger.info(
                "Rate limit counter reset",
                extra={
                    "workspace_id": str(workspace_id),
                },
            )

        except redis.exceptions.RedisError as e:
            logger.error(
                "Redis operation failed in reset",
                extra={
                    "workspace_id": str(workspace_id),
                    "key": key,
                    "error": str(e),
                },
            )
            raise InfrastructureError(f"Rate limiter unavailable: {e}") from e
