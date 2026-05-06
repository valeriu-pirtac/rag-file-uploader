"""Webhook implementation of event publisher protocol.

This module implements IEventPublisher using HTTP webhooks with HMAC-SHA256
signatures for secure event delivery to downstream RAG pipeline consumers.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from types import TracebackType

import httpx

from src.domain.entities.events import FileLoadCompletedEvent
from src.domain.exceptions import InfrastructureError


logger = logging.getLogger(__name__)


class WebhookEventPublisher:
    """Webhook implementation of event publisher protocol.

    Publishes FILE_LOAD_COMPLETED events via HTTP POST to configured webhook
    URL with HMAC-SHA256 signature for authentication and integrity verification.

    Architecture Position:
        - Implements IEventPublisher protocol (Story 5.4)
        - Alternative to NATSEventPublisher (Story 5.5)
        - Wrapped by EventPublisherWithRetry (Story 5.6)
        - Used by CompleteUploadUseCase (Story 5.8)

    Security:
        - HMAC-SHA256 signature prevents tampering
        - Signature sent in X-Webhook-Signature header
        - Receiver verifies signature using shared secret
        - HTTPS recommended for production (not enforced in MVP)

    Error Handling:
        - HTTP timeouts → InfrastructureError
        - HTTP 4xx/5xx responses → InfrastructureError
        - Network errors → InfrastructureError
        - Retry logic delegated to EventPublisherWithRetry wrapper

    Configuration (from AppSettings):
        - webhook_url: Full webhook URL (e.g., "https://example.com/webhook")
        - webhook_secret: Shared secret for HMAC signature
        - webhook_timeout: Request timeout in seconds (default: 10)

    Request Format:
        POST {webhook_url}
        Content-Type: application/json
        X-Webhook-Signature: sha256={hex_signature}
        X-Event-Type: FILE_LOAD_COMPLETED
        X-Idempotency-Key: {file_id}

        {
            "eventVersion": "1.0",
            "eventType": "FILE_LOAD_COMPLETED",
            "timestamp": "2026-05-06T10:23:45.123456Z",
            "payload": {
                "file_id": "550e8400-e29b-41d4-a716-446655440000",
                "workspace_id": "660f9511-f3ac-52e5-b827-557766551111",
                "s3_path": "workspace_660f9511.../file.pdf",
                "sha256_checksum": "a7f3c9b2...",
                "size_bytes": 1048576,
                "uploaded_at": "2026-05-06T10:22:30.000000Z"
            }
        }

    Idempotency:
        - X-Idempotency-Key header contains file_id (UUID)
        - Receivers can use this to deduplicate retry attempts
        - Same file_id = same event (idempotent processing)
        - Delivery guarantee: at-least-once with idempotency support

    Signature Verification (Receiver Side):
        ```python
        import hmac
        import hashlib

        def verify_signature(payload: str, signature: str, secret: str) -> bool:
            expected = hmac.new(
                key=secret.encode('utf-8'),
                msg=payload.encode('utf-8'),
                digestmod=hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected, signature)

        # In webhook handler
        raw_body = await request.body()
        payload_json = raw_body.decode('utf-8')
        signature = request.headers['X-Webhook-Signature'].replace('sha256=', '')

        if not verify_signature(payload_json, signature, webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid signature")

        # Note: verify_signature uses hmac.compare_digest() to prevent timing attacks
        ```

    Examples:
        >>> from src.infrastructure.config.settings import get_settings
        >>> from src.domain.entities.events import FileLoadCompletedEvent
        >>>
        >>> # Initialize publisher
        >>> settings = get_settings()
        >>> publisher = WebhookEventPublisher(
        ...     webhook_url=settings.webhook_url,
        ...     webhook_secret=settings.webhook_secret.get_secret_value(),
        ...     webhook_timeout=settings.webhook_timeout
        ... )
        >>>
        >>> # Publish event (single attempt - no retry logic here)
        >>> event = FileLoadCompletedEvent(...)
        >>> await publisher.publish(event)
        >>>
        >>> # Wrap with retry logic (Story 5.8)
        >>> from src.infrastructure.nats.event_publisher_with_retry import EventPublisherWithRetry
        >>> publisher_with_retry = EventPublisherWithRetry(
        ...     publisher=publisher,
        ...     redis_client=redis_client,
        ...     max_retry_attempts=5
        ... )
        >>> await publisher_with_retry.publish(event)

    NFR Compliance:
        - NFR-R4: Publishes events for downstream RAG pipeline integration
        - NFR-R5: All failures raise InfrastructureError (no silent failures)
        - NFR-I1: Webhook alternative when NATS unavailable

    Integration Points:
        - Story 5.4: Uses FileLoadCompletedEvent.to_json() for serialization
        - Story 5.4: Implements IEventPublisher protocol
        - Story 5.6: Wrapped by EventPublisherWithRetry for retry logic
        - Story 5.8: CompleteUploadUseCase calls publish() method
    """

    def __init__(
        self,
        webhook_url: str,
        webhook_secret: str,
        webhook_timeout: int = 10,
    ) -> None:
        """Initialize webhook event publisher with configuration.

        Args:
            webhook_url: Full webhook URL (must be HTTPS in production)
            webhook_secret: Shared secret for HMAC-SHA256 signature
            webhook_timeout: HTTP request timeout in seconds (default: 10)

        Raises:
            ValueError: If webhook_url or webhook_secret is empty

        Note:
            No connection is established in __init__. HTTP requests are made
            on-demand during publish() calls using httpx.AsyncClient.
        """
        if not webhook_url or not webhook_url.strip():
            raise ValueError("webhook_url cannot be empty")
        if not webhook_secret or not webhook_secret.strip():
            raise ValueError("webhook_secret cannot be empty")
        if webhook_timeout <= 0:
            raise ValueError("webhook_timeout must be positive")

        # Validate URL format
        from urllib.parse import urlparse

        parsed = urlparse(webhook_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid webhook URL format: {webhook_url}")

        self._webhook_url = webhook_url
        self._webhook_secret = webhook_secret
        self._timeout = webhook_timeout
        self._client = httpx.AsyncClient(timeout=webhook_timeout)

        logger.info(
            "WebhookEventPublisher initialized",
            extra={
                "webhook_url": webhook_url,
                "timeout": webhook_timeout,
            },
        )

    async def __aenter__(self) -> WebhookEventPublisher:
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit - close HTTP client."""
        await self._client.aclose()

    async def close(self) -> None:
        """Close the HTTP client connection pool."""
        await self._client.aclose()

    async def publish(self, event: FileLoadCompletedEvent) -> None:
        """Publish FILE_LOAD_COMPLETED event via webhook.

        Makes single HTTP POST request to configured webhook URL with
        HMAC-SHA256 signed payload. Does NOT implement retry logic -
        retries are handled by EventPublisherWithRetry wrapper.

        Args:
            event: FileLoadCompletedEvent to publish

        Raises:
            InfrastructureError: On any webhook failure (timeout, HTTP error,
                network error). Caller (EventPublisherWithRetry) handles retry.

        Implementation Notes:
            - Uses httpx.AsyncClient for async HTTP requests
            - Computes HMAC-SHA256 signature from event JSON
            - Sets headers: Content-Type, X-Webhook-Signature, X-Event-Type, X-Idempotency-Key
            - X-Idempotency-Key = file_id for duplicate detection by receivers
            - Waits for HTTP response and validates status code
            - Logs all attempts with structured metadata
            - Does NOT retry on failure - raises InfrastructureError
        """
        # Serialize event with error handling
        try:
            payload_json = event.to_json()
        except Exception as e:
            raise InfrastructureError(f"Event serialization failed: {e}") from e

        # Validate payload is not empty
        if not payload_json or not payload_json.strip():
            raise InfrastructureError("Event serialization produced empty payload")

        signature = self._generate_signature(payload_json)

        logger.info(
            "Publishing event via webhook",
            extra={
                "file_id": str(event.file_id),
                "workspace_id": str(event.workspace_id),
                "webhook_url": self._webhook_url,
                "event_type": event.event_type,
                "event_version": event.event_version,
            },
        )

        try:
            response = await self._client.post(
                self._webhook_url,
                content=payload_json,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": f"sha256={signature}",
                    "X-Event-Type": event.event_type,
                    "X-Idempotency-Key": str(event.file_id),
                },
            )
            response.raise_for_status()

            logger.info(
                "Webhook publish successful",
                extra={
                    "file_id": str(event.file_id),
                    "workspace_id": str(event.workspace_id),
                    "webhook_url": self._webhook_url,
                    "status_code": response.status_code,
                },
            )

        except httpx.TimeoutException as e:
            logger.error(
                "Webhook publish failed",
                extra={
                    "file_id": str(event.file_id),
                    "workspace_id": str(event.workspace_id),
                    "webhook_url": self._webhook_url,
                    "error": "timeout",
                    "timeout_seconds": self._timeout,
                },
                exc_info=True,
            )
            raise InfrastructureError(f"Webhook timeout: {e}") from e

        except httpx.HTTPStatusError as e:
            logger.error(
                "Webhook publish failed",
                extra={
                    "file_id": str(event.file_id),
                    "workspace_id": str(event.workspace_id),
                    "webhook_url": self._webhook_url,
                    "error": "http_status_error",
                    "status_code": e.response.status_code,
                    "response_body": e.response.text if e.response else None,
                },
                exc_info=True,
            )
            raise InfrastructureError(f"Webhook HTTP error {e.response.status_code}: {e}") from e

        except Exception as e:
            logger.error(
                "Webhook publish failed",
                extra={
                    "file_id": str(event.file_id),
                    "workspace_id": str(event.workspace_id),
                    "webhook_url": self._webhook_url,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise InfrastructureError(f"Webhook publish failed: {e}") from e

    def _generate_signature(self, payload_json: str) -> str:
        """Generate HMAC-SHA256 signature for webhook request.

        Computes HMAC-SHA256 hash of payload JSON using webhook secret.
        Signature is sent in X-Webhook-Signature header for receiver
        to verify authenticity and integrity.

        Args:
            payload_json: Complete JSON request body (from event.to_json())

        Returns:
            Hex-encoded HMAC-SHA256 signature (64 characters)

        Algorithm:
            HMAC-SHA256(key=webhook_secret, message=payload_json)

        Example:
            >>> publisher = WebhookEventPublisher(
            ...     webhook_url="https://example.com/webhook",
            ...     webhook_secret="my-secret-key"
            ... )
            >>> payload = '{"event_version":"1.0","event_type":"FILE_LOAD_COMPLETED",...}'
            >>> signature = publisher._generate_signature(payload)
            >>> len(signature)
            64
            >>> signature
            'a7f3c9b2d8e1f6a4c2b9d7e5f3a1c8b6d4e2f0a8c6b4d2e0f8a6c4b2d0e8f6a4'
        """
        return hmac.new(
            key=self._webhook_secret.encode("utf-8"),
            msg=payload_json.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
