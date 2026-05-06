"""NATS JetStream implementation of event publisher protocol.

This module implements IEventPublisher using NATS JetStream for durable
at-least-once event delivery to downstream RAG pipeline consumers.
"""

from __future__ import annotations

import logging

import nats
from nats.aio.client import Client as NATSClient
from nats.js import JetStreamContext
from nats.js.api import DiscardPolicy, RetentionPolicy, StorageType, StreamConfig

from src.domain.entities.events import FileLoadCompletedEvent
from src.domain.exceptions import InfrastructureError, SerializationError


logger = logging.getLogger(__name__)


class NATSEventPublisher:
    """NATS JetStream implementation of event publisher protocol.

    Publishes FILE_LOAD_COMPLETED events to NATS JetStream with durable
    storage and at-least-once delivery guarantees. Creates JetStream stream
    on first publish if not exists.

    Architecture Position:
        - Implements IEventPublisher protocol (Story 5.4)
        - Used by CompleteUploadUseCase (Story 5.8)
        - Publishes to subject: upload.file.load_completed
        - Durable stream: UPLOAD_EVENTS (7-day retention)

    Connection Lifecycle:
        1. __init__: Store configuration (nats_url, subject)
        2. connect(): Establish NATS connection + JetStream context
        3. _ensure_stream(): Create stream if not exists
        4. publish(): Publish event, wait for PubAck
        5. disconnect(): Graceful shutdown

    Error Handling:
        - NATS connection failures → InfrastructureError
        - NATS timeout → InfrastructureError
        - Serialization failures → SerializationError
        - All errors logged with event metadata

    Configuration (from AppSettings):
        - nats_url: NATS server URL (e.g., "nats://localhost:4222")
        - nats_subject: Subject name (default: "upload.file.load.completed")
        - stream_name: JetStream stream name (default: "UPLOAD_EVENTS")
        - connection_timeout: Connection timeout in seconds (default: 5)
        - max_reconnect_attempts: Max reconnection attempts (default: 3)

    Examples:
        >>> from src.infrastructure.config import get_settings
        >>> from src.domain.entities.events import FileLoadCompletedEvent
        >>>
        >>> # Initialize publisher
        >>> settings = get_settings()
        >>> publisher = NATSEventPublisher(
        ...     nats_url=settings.nats_url,
        ...     nats_subject=settings.nats_subject,
        ...     stream_name=settings.nats_stream_name,
        ...     connection_timeout=settings.nats_connection_timeout,
        ...     max_reconnect_attempts=settings.nats_max_reconnect_attempts
        ... )
        >>>
        >>> # Connect to NATS
        >>> await publisher.connect()
        >>>
        >>> # Publish event
        >>> event = FileLoadCompletedEvent(...)
        >>> await publisher.publish(event)
        >>>
        >>> # Graceful shutdown
        >>> await publisher.disconnect()

    JetStream Stream Configuration:
        - Name: UPLOAD_EVENTS
        - Subjects: ["upload.file.load_completed"]
        - Retention: LIMITS (keep until max_age)
        - Max Age: 7 days (604,800 seconds)
        - Storage: FILE (persist to disk)
        - Discard: OLD (FIFO when full)

    NFR Compliance:
        - NFR-R4: At-least-once delivery via JetStream PubAck
        - NFR-I1: Durable subjects, consumer replay capability
        - NFR-R5: Connection errors do not silently fail

    Integration Points:
        - Story 5.4: Uses FileLoadCompletedEvent.to_json() for serialization
        - Story 5.4: Uses FileLoadCompletedEvent.subject_name for NATS subject
        - Story 5.6: Retry logic wrapper (not in this story)
        - Story 5.8: CompleteUploadUseCase calls publish() method
    """

    def __init__(
        self,
        nats_url: str,
        nats_subject: str,
        stream_name: str = "UPLOAD_EVENTS",
        connection_timeout: int = 5,
        max_reconnect_attempts: int = 3,
    ) -> None:
        """Initialize NATS event publisher with configuration.

        Args:
            nats_url: NATS server URL (e.g., "nats://localhost:4222")
            nats_subject: NATS subject for events (e.g., "upload.file.load_completed")
            stream_name: JetStream stream name (default: "UPLOAD_EVENTS")
            connection_timeout: Connection timeout in seconds (default: 5)
            max_reconnect_attempts: Max reconnection attempts (default: 3)

        Raises:
            ValueError: If nats_url or nats_subject is empty

        Note:
            Connection is not established in __init__. Call connect() explicitly.
        """
        if not nats_url or not nats_url.strip():
            raise ValueError("nats_url cannot be empty")
        if not nats_subject or not nats_subject.strip():
            raise ValueError("nats_subject cannot be empty")
        if not stream_name or not stream_name.strip():
            raise ValueError("stream_name cannot be empty")

        self._nats_url = nats_url
        self._nats_subject = nats_subject
        self._stream_name = stream_name
        self._connection_timeout = connection_timeout
        self._max_reconnect_attempts = max_reconnect_attempts

        self._client: NATSClient | None = None
        self._js: JetStreamContext | None = None
        self._connected = False

        logger.info(
            "NATSEventPublisher initialized",
            extra={
                "nats_url": nats_url,
                "subject": nats_subject,
                "stream": stream_name,
            },
        )

    async def connect(self) -> None:
        """Establish connection to NATS JetStream.

        Creates NATS client connection and JetStream context.
        Ensures durable stream exists with proper configuration.

        Raises:
            InfrastructureError: If NATS connection fails

        Note:
            This method is idempotent - calling multiple times is safe.
            If already connected, returns immediately.
        """
        if self._connected:
            logger.debug("Already connected to NATS, skipping connection")
            return

        try:
            # Connect to NATS server
            logger.info("Connecting to NATS", extra={"nats_url": self._nats_url})

            self._client = await nats.connect(
                servers=[self._nats_url],
                connect_timeout=self._connection_timeout,
                max_reconnect_attempts=self._max_reconnect_attempts,
                # Connection name for monitoring
                name="rag-file-uploader",
            )

            try:
                # Get JetStream context
                self._js = self._client.jetstream()

                # Ensure stream exists
                await self._ensure_stream()

                self._connected = True
                logger.info("Successfully connected to NATS JetStream")

            except Exception:
                # Cleanup client connection on partial failure
                if self._client:
                    await self._client.close()
                    self._client = None
                raise

        except Exception as e:
            logger.error(
                "Failed to connect to NATS",
                extra={"nats_url": self._nats_url, "error": str(e)},
                exc_info=True,
            )
            raise InfrastructureError(f"Failed to connect to NATS at {self._nats_url}: {e}") from e

    async def _ensure_stream(self) -> None:
        """Ensure JetStream stream exists with proper configuration.

        Creates stream if not exists. If stream exists, verifies configuration
        matches expected settings. Idempotent - safe to call multiple times.

        Stream Configuration:
            - Name: UPLOAD_EVENTS
            - Subjects: ["upload.file.load_completed"]
            - Retention: LIMITS (keep until max_age)
            - Max Age: 7 days (604,800 seconds)
            - Storage: FILE (persist to disk)
            - Discard: OLD (FIFO when full)

        Raises:
            InfrastructureError: If stream creation fails
        """
        if not self._js:
            raise InfrastructureError("JetStream context not initialized")

        try:
            # Check if stream exists
            try:
                existing_stream = await self._js.stream_info(self._stream_name)
                # Validate stream subjects match expected configuration
                stream_subjects = existing_stream.config.subjects or []
                if self._nats_subject not in stream_subjects:
                    logger.warning(
                        "Stream subject mismatch detected",
                        extra={
                            "stream": self._stream_name,
                            "expected_subject": self._nats_subject,
                            "actual_subjects": stream_subjects,
                        },
                    )
                logger.debug(
                    "JetStream stream already exists",
                    extra={
                        "stream": self._stream_name,
                        "subjects": existing_stream.config.subjects,
                    },
                )
                return
            except nats.js.errors.NotFoundError:
                # Stream does not exist, create it
                logger.info(
                    "Creating JetStream stream",
                    extra={"stream": self._stream_name, "subject": self._nats_subject},
                )

                stream_config = StreamConfig(
                    name=self._stream_name,
                    subjects=[self._nats_subject],
                    retention=RetentionPolicy.LIMITS,
                    max_age=604_800_000_000_000,  # 7 days in nanoseconds
                    storage=StorageType.FILE,
                    discard=DiscardPolicy.OLD,
                )

                await self._js.add_stream(config=stream_config)

                logger.info(
                    "Successfully created JetStream stream",
                    extra={"stream": self._stream_name, "subject": self._nats_subject},
                )

        except nats.js.errors.NotFoundError:
            # Expected error handled above
            pass
        except Exception as e:
            logger.error(
                "Failed to ensure JetStream stream exists",
                extra={"stream": self._stream_name, "error": str(e)},
                exc_info=True,
            )
            raise InfrastructureError(
                f"Failed to create JetStream stream {self._stream_name}: {e}"
            ) from e

    async def publish(self, event: FileLoadCompletedEvent) -> bool:
        """Publish FILE_LOAD_COMPLETED event to NATS JetStream.

        Implements IEventPublisher.publish() protocol method.
        Serializes event to JSON and publishes to JetStream subject.
        Waits for PubAck to confirm message persistence.

        Args:
            event: FileLoadCompletedEvent to publish

        Returns:
            True if event was successfully published and acknowledged

        Raises:
            InfrastructureError: If NATS unavailable or publish fails
            SerializationError: If event serialization fails

        Implementation Notes:
            - Uses event.to_json() for serialization (Story 5.4)
            - Uses event.subject_name for NATS subject (Story 5.4)
            - Waits for JetStream PubAck (at-least-once delivery)
            - Logs all publish attempts with event metadata

        NFR Compliance:
            - NFR-R4: At-least-once delivery via PubAck
            - NFR-I1: Stable subject/schema contracts
        """
        if not self._connected or not self._js or not self._client:
            raise InfrastructureError("Not connected to NATS. Call connect() first.")

        try:
            # Serialize event using domain entity method
            event_json = event.to_json()

            # Get subject from event (Story 5.4)
            subject = event.subject_name

            logger.info(
                "Publishing event to NATS",
                extra={
                    "subject": subject,
                    "file_id": str(event.file_id),
                    "workspace_id": str(event.workspace_id),
                    "event_version": event.event_version,
                },
            )

            # Publish to JetStream and wait for ack (with timeout)
            ack = await self._js.publish(
                subject=subject,
                payload=event_json.encode("utf-8"),
                timeout=self._connection_timeout,
            )

            logger.info(
                "Event published successfully",
                extra={
                    "subject": subject,
                    "file_id": str(event.file_id),
                    "workspace_id": str(event.workspace_id),
                    "stream": ack.stream,
                    "sequence": ack.seq,
                },
            )
            return True

        except SerializationError:
            # Serialization error from event.to_json() - re-raise as-is
            logger.error(
                "Event serialization failed",
                extra={
                    "file_id": str(event.file_id),
                    "workspace_id": str(event.workspace_id),
                },
                exc_info=True,
            )
            raise

        except Exception as e:
            logger.error(
                "Failed to publish event to NATS",
                extra={
                    "subject": self._nats_subject,
                    "file_id": str(event.file_id),
                    "workspace_id": str(event.workspace_id),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise InfrastructureError(f"Failed to publish event to NATS: {e}") from e

    async def disconnect(self) -> None:
        """Gracefully disconnect from NATS.

        Closes NATS client connection and cleans up resources.
        Safe to call multiple times (idempotent).

        Note:
            Should be called during application shutdown to ensure
            all pending messages are flushed before exit.
        """
        if not self._connected:
            logger.debug("Not connected to NATS, skipping disconnect")
            return

        try:
            if self._client:
                logger.info("Disconnecting from NATS")
                await self._client.drain()
                await self._client.close()

                self._client = None
                self._js = None
                self._connected = False

                logger.info("Successfully disconnected from NATS")

        except Exception as e:
            logger.error("Error during NATS disconnect", extra={"error": str(e)}, exc_info=True)
            # Don't raise - best effort cleanup during shutdown
