"""Retry wrapper for event publisher with dead letter queue fallback.

This module wraps any IEventPublisher implementation (NATS or webhook) with
exponential backoff retry logic and Redis dead letter queue (DLQ) for permanent
failures. Ensures at-least-once delivery per NFR-R4.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Protocol

import redis.asyncio as aioredis

from src.domain.entities.events import FileLoadCompletedEvent
from src.domain.exceptions import InfrastructureError


class IEventPublisher(Protocol):
    """Protocol for event publishers."""

    async def publish(self, event: FileLoadCompletedEvent) -> None:
        """Publish an event."""
        ...


logger = logging.getLogger(__name__)


class EventPublisherWithRetry:
    """Retry wrapper for IEventPublisher implementations.

    Wraps any IEventPublisher (NATS or webhook) with exponential backoff
    retry logic and dead letter queue (DLQ) fallback for permanent failures.

    Architecture Position:
        - Wraps NATSEventPublisher (Story 5.5) or WebhookEventPublisher (Story 5.7)
        - Used by CompleteUploadUseCase (Story 5.8)
        - Implements NFR-R4: At-least-once delivery guarantee

    Retry Strategy:
        - Max attempts: 5 (configurable)
        - Exponential backoff: 1s, 2s, 4s, 8s, 16s
        - Total retry duration: ~31 seconds
        - Covers transient failures: network hiccups, NATS restarts

    Dead Letter Queue (DLQ):
        - Redis key pattern: dlq:file_load_completed:{file_id}
        - Entry schema: event payload, original timestamp, retry count, last error
        - TTL: 7 days (configurable)
        - Manual operator intervention required

    Structured Logging:
        - WARNING: Retry attempts 1-4 with error details
        - ERROR: Final retry failure, DLQ write
        - INFO: Successful publish, DLQ write success
        - All logs include: file_id, workspace_id, attempt, error

    Configuration (from AppSettings):
        - event_max_retry_attempts: Max retry attempts (default: 5)
        - event_dlq_ttl_seconds: DLQ entry TTL (default: 604800 = 7 days)

    Examples:
        >>> from src.infrastructure.nats.event_publisher import NATSEventPublisher
        >>> import redis.asyncio as aioredis
        >>>
        >>> # Initialize wrapped publisher
        >>> nats_publisher = NATSEventPublisher(settings)
        >>> await nats_publisher.connect()
        >>>
        >>> redis_client = aioredis.from_url(settings.redis_url)
        >>>
        >>> publisher_with_retry = EventPublisherWithRetry(
        ...     publisher=nats_publisher,
        ...     redis_client=redis_client,
        ...     max_retry_attempts=5,
        ...     dlq_ttl_seconds=604800
        ... )
        >>>
        >>> # Publish event (with automatic retry)
        >>> event = FileLoadCompletedEvent(...)
        >>> await publisher_with_retry.publish(event)
        >>>
        >>> # If NATS unavailable:
        >>> # → Retries 5 times with exponential backoff
        >>> # → Writes to DLQ if all retries fail
        >>> # → Logs all attempts with structured logging

    NFR Compliance:
        - NFR-R4: At-least-once delivery via retry + DLQ
        - NFR-R5: No silent failures (all errors logged and stored in DLQ)
        - FR31: Structured logs with tenant_id, file_id, retry context

    Integration Points:
        - Story 5.5: Wraps NATSEventPublisher
        - Story 5.7: Wraps WebhookEventPublisher (future)
        - Story 5.8: CompleteUploadUseCase uses this class to publish events
        - Story 6.2: Structured logging already implemented in this story
    """

    def __init__(
        self,
        publisher: IEventPublisher,
        redis_client: aioredis.Redis,
        max_retry_attempts: int = 5,
        dlq_ttl_seconds: int = 604800,  # 7 days
    ) -> None:
        """Initialize retry wrapper with publisher and DLQ config.

        Args:
            publisher: IEventPublisher implementation to wrap (NATS or webhook)
            redis_client: Redis client for DLQ storage
            max_retry_attempts: Max retry attempts (default: 5)
            dlq_ttl_seconds: DLQ entry TTL in seconds (default: 604800 = 7 days)

        Raises:
            ValueError: If max_retry_attempts < 1 or dlq_ttl_seconds < 1
        """
        if max_retry_attempts < 1:
            raise ValueError("max_retry_attempts must be >= 1")
        if max_retry_attempts > 100:
            raise ValueError("max_retry_attempts must be <= 100 to prevent overflow")
        if dlq_ttl_seconds < 1:
            raise ValueError("dlq_ttl_seconds must be >= 1")

        self._publisher = publisher
        self._redis_client = redis_client
        self._max_retry_attempts = max_retry_attempts
        self._dlq_ttl_seconds = dlq_ttl_seconds

        logger.info(
            "EventPublisherWithRetry initialized",
            extra={
                "publisher_type": type(publisher).__name__,
                "max_retry_attempts": max_retry_attempts,
                "dlq_ttl_seconds": dlq_ttl_seconds,
            },
        )

    async def publish(self, event: FileLoadCompletedEvent) -> None:
        """Publish event with exponential backoff retry and DLQ fallback.

        Implements retry strategy:
            - Attempt 1: Immediate (no delay)
            - Attempt 2: After 1s delay
            - Attempt 3: After 2s delay
            - Attempt 4: After 4s delay
            - Attempt 5: After 8s delay
            - If all fail: Write to DLQ

        Args:
            event: FileLoadCompletedEvent to publish

        Raises:
            ValueError: If event is None
            InfrastructureError: If publish fails after all retries (event written to DLQ),
                or if DLQ write itself fails (rare: Redis unavailable)

        Note:
            - Successful publish (any attempt) returns normally
            - Failed publish after all retries writes to DLQ and raises InfrastructureError
            - This allows caller to distinguish success from DLQ fallback
        """
        if event is None:
            raise ValueError("event cannot be None")

        last_error: Exception | None = None

        for attempt in range(1, self._max_retry_attempts + 1):
            try:
                # Attempt publish
                await self._publisher.publish(event)

                # Success!
                if attempt == 1:
                    logger.info(
                        "Event published successfully",
                        extra={
                            "file_id": str(event.file_id),
                            "workspace_id": str(event.workspace_id),
                            "attempt": attempt,
                        },
                    )
                else:
                    logger.info(
                        "Event published successfully after retry",
                        extra={
                            "file_id": str(event.file_id),
                            "workspace_id": str(event.workspace_id),
                            "attempt": attempt,
                            "max_attempts": self._max_retry_attempts,
                        },
                    )

                return  # Success - exit retry loop

            except asyncio.CancelledError:
                # Task cancellation should propagate immediately
                logger.warning(
                    "Event publish cancelled during retry",
                    extra={
                        "file_id": str(event.file_id),
                        "workspace_id": str(event.workspace_id),
                        "attempt": attempt,
                    },
                )
                raise

            except Exception as e:
                last_error = e

                # Log retry attempt (if not final attempt)
                if attempt < self._max_retry_attempts:
                    # Calculate delay between attempts: 2^(attempt-1) seconds
                    # After attempt 1 fails: wait 1s before attempt 2
                    # After attempt 2 fails: wait 2s before attempt 3
                    # After attempt 3 fails: wait 4s before attempt 4
                    # After attempt 4 fails: wait 8s before attempt 5
                    next_delay = 2 ** (attempt - 1)

                    logger.warning(
                        "Event publish failed, retrying",
                        extra={
                            "file_id": str(event.file_id),
                            "workspace_id": str(event.workspace_id),
                            "attempt": attempt,
                            "max_attempts": self._max_retry_attempts,
                            "next_delay_seconds": next_delay,
                            "error": str(e),
                        },
                    )

                    # Wait before next retry
                    await asyncio.sleep(next_delay)
                else:
                    # Final attempt failed
                    logger.error(
                        "Event publish failed after all retries, writing to DLQ",
                        extra={
                            "file_id": str(event.file_id),
                            "workspace_id": str(event.workspace_id),
                            "attempt": attempt,
                            "max_attempts": self._max_retry_attempts,
                            "error": str(e),
                        },
                        exc_info=True,
                    )

        # All retries failed - write to DLQ
        await self._write_to_dlq(event, self._max_retry_attempts, last_error)

    async def _write_to_dlq(
        self, event: FileLoadCompletedEvent, retry_count: int, last_error: Exception | None
    ) -> None:
        """Write failed event to Redis dead letter queue with retry.

        Args:
            event: FileLoadCompletedEvent that failed to publish
            retry_count: Total retry attempts made
            last_error: Exception from final retry attempt

        Raises:
            InfrastructureError: If DLQ write fails after retries (Redis unavailable)

        DLQ Entry Schema:
            {
                "event_payload": { ... },  # Complete FileLoadCompletedEvent JSON
                "original_timestamp": "2026-05-06T10:23:45.123456Z",
                "retry_count": 5,
                "last_error": "Connection refused",
                "failed_at": "2026-05-06T10:24:16.987654Z"
            }
        """
        dlq_key = f"dlq:file_load_completed:{event.file_id}"

        # Build DLQ entry - handle serialization errors
        try:
            event_payload_dict = json.loads(event.to_json())
        except Exception as e:
            logger.error(
                "Failed to serialize event for DLQ",
                extra={
                    "file_id": str(event.file_id),
                    "workspace_id": str(event.workspace_id),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise InfrastructureError(f"Failed to serialize event for DLQ: {e}") from e

        dlq_entry = {
            "event_payload": event_payload_dict,
            "original_timestamp": event.timestamp.isoformat(),
            "retry_count": retry_count,
            "last_error": str(last_error) if last_error else "Unknown error",
            "failed_at": datetime.now(UTC).isoformat(),
        }

        # Retry DLQ write up to 3 times
        dlq_entry_json = json.dumps(dlq_entry)
        for dlq_attempt in range(1, 4):
            try:
                await self._redis_client.setex(dlq_key, self._dlq_ttl_seconds, dlq_entry_json)
                break  # Success
            except Exception as e:
                if dlq_attempt < 3:
                    logger.warning(
                        "DLQ write failed, retrying",
                        extra={
                            "file_id": str(event.file_id),
                            "workspace_id": str(event.workspace_id),
                            "dlq_attempt": dlq_attempt,
                            "error": str(e),
                        },
                    )
                    await asyncio.sleep(0.5 * dlq_attempt)  # 0.5s, 1s delays
                    continue
                # Final attempt failed
                logger.error(
                    "Failed to write event to DLQ after retries",
                    extra={
                        "file_id": str(event.file_id),
                        "workspace_id": str(event.workspace_id),
                        "dlq_key": dlq_key,
                        "error": str(e),
                    },
                    exc_info=True,
                )
                raise InfrastructureError(f"Failed to write event to DLQ: {e}") from e

        # DLQ write succeeded
        logger.info(
            "Event written to dead letter queue",
            extra={
                "file_id": str(event.file_id),
                "workspace_id": str(event.workspace_id),
                "dlq_key": dlq_key,
                "retry_count": retry_count,
                "ttl_seconds": self._dlq_ttl_seconds,
                "ttl_days": self._dlq_ttl_seconds // 86400,
            },
        )

        # Raise exception to signal publish failure to caller (Decision #2)
        raise InfrastructureError(
            f"Event publish failed after {retry_count} retries. Event written to DLQ: {dlq_key}"
        )
