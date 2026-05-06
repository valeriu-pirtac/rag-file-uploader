"""Event publisher protocol for FILE_LOAD_COMPLETED events.

This module defines the abstract interface for publishing events to
downstream RAG pipeline consumers via NATS or webhooks.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.domain.entities.events import FileLoadCompletedEvent


@runtime_checkable
class IEventPublisher(Protocol):
    """Protocol for event publishing to NATS or webhooks.

    Defines the contract for publishing FILE_LOAD_COMPLETED events
    to downstream RAG pipeline consumers. Implementations must handle
    serialization, transport-specific details, and error recovery.

    All methods are async to support non-blocking I/O operations with
    external message brokers (NATS JetStream) or HTTP webhooks.

    Event Publishing Flow:
        1. CompleteUploadUseCase creates FileLoadCompletedEvent
        2. Use case calls event_publisher.publish(event)
        3. Publisher serializes event to JSON
        4. Publisher sends to NATS subject or webhook URL
        5. Publisher handles retries and errors per NFR-R4

    Retry and Error Handling:
        Implementations MUST implement retry logic for transient failures:
        - Quick retries: 3 attempts with exponential backoff (1s, 2s)
        - Dead letter queue: If quick retries fail, push to Redis DLQ
        - Background worker: Retry from DLQ with exponential backoff
        - Max retries: 5-10 attempts before marking as failed
        - At-least-once delivery: Events eventually reach consumers

    Error Types:
        - InfrastructureError: NATS connection failure, webhook timeout
        - SerializationError: Event serialization failure (should never happen)
        - ValueError: Invalid event (missing fields, validation failure)

    NATS Implementation (Story 5.5):
        - Connect to NATS JetStream server
        - Create/use durable stream for upload events
        - Publish to subject: upload.file.load_completed
        - Wait for JetStream ack to confirm persistence
        - Implement retry logic per architecture.md

    Webhook Implementation (Story 5.7):
        - POST event JSON to configured webhook URL
        - Include X-Webhook-Signature header (HMAC-SHA256)
        - Timeout: 10 seconds (configurable)
        - Implement retry logic per architecture.md

    Examples:
        >>> # NATS implementation (Story 5.5)
        >>> nats_publisher = NATSEventPublisher(settings)
        >>> await nats_publisher.publish(event)
        >>>
        >>> # Webhook implementation (Story 5.7)
        >>> webhook_publisher = WebhookEventPublisher(settings)
        >>> await webhook_publisher.publish(event)
    """

    async def publish(self, event: FileLoadCompletedEvent) -> None:
        """Publish FILE_LOAD_COMPLETED event to downstream consumers.

        Args:
            event: FileLoadCompletedEvent to publish

        Raises:
            InfrastructureError: If NATS/webhook unavailable after retries
            SerializationError: If event serialization fails
            ValueError: If event validation fails

        Implementation Notes:
            - Serialize event using event.to_json()
            - Use event.subject_name for NATS subject
            - Implement retry logic per architecture.md
            - On failure after retries, push to DLQ
            - Log all publish attempts with event metadata
        """
        ...
