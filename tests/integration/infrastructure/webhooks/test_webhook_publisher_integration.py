"""Integration tests for WebhookEventPublisher.

Tests webhook publisher integration with EventPublisherWithRetry wrapper
and validation of retry + DLQ behavior as specified in Story 5.6.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import httpx
import pytest
from redis import asyncio as aioredis

from src.domain.entities.events import FileLoadCompletedEvent
from src.domain.exceptions import InfrastructureError
from src.domain.value_objects.sha256_hash import SHA256Hash
from src.infrastructure.nats.event_publisher_with_retry import EventPublisherWithRetry
from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher


@pytest.fixture
def webhook_url() -> str:
    """Webhook URL fixture."""
    return "https://example.com/webhooks/file-load-completed"


@pytest.fixture
def webhook_secret() -> str:
    """Webhook secret fixture."""
    return "integration-test-secret"


@pytest.fixture
def sample_event() -> FileLoadCompletedEvent:
    """Sample FileLoadCompletedEvent fixture."""
    return FileLoadCompletedEvent(
        file_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
        workspace_id=UUID("660f9511-f3ac-52e5-b827-557766551111"),
        s3_path="s3://uploads/workspace_660f9511-f3ac-52e5-b827-557766551111/550e8400-e29b-41d4-a716-446655440000.pdf",
        sha256_checksum=SHA256Hash("a" * 64),
        size_bytes=1048576,
        uploaded_at=datetime(2026, 5, 6, 10, 22, 30, tzinfo=UTC),
    )


@pytest.mark.integration
class TestWebhookEventPublisherIntegration:
    """Integration tests for WebhookEventPublisher with EventPublisherWithRetry."""

    @pytest.mark.asyncio
    async def test_webhook_publisher_integrates_with_retry_wrapper(
        self,
        webhook_url: str,
        webhook_secret: str,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test that WebhookEventPublisher works with EventPublisherWithRetry wrapper."""
        # Mock Redis client
        mock_redis = AsyncMock(spec=aioredis.Redis)
        mock_redis.rpush = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)

        # Mock successful HTTP response
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        # Create webhook publisher with patch
        with patch(
            "src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient",
            return_value=mock_client,
        ):
            webhook_publisher = WebhookEventPublisher(
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
            )

            # Wrap with retry logic
            publisher_with_retry = EventPublisherWithRetry(
                publisher=webhook_publisher,
                redis_client=mock_redis,
                max_retry_attempts=5,
            )

            # Publish event
            await publisher_with_retry.publish(sample_event)

        # Verify webhook was called
        mock_client.post.assert_called_once()

        # Verify no DLQ entry (success case)
        mock_redis.rpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_webhook_failure_triggers_retry_logic(
        self,
        webhook_url: str,
        webhook_secret: str,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test that webhook failures trigger retry logic in wrapper."""
        # Mock Redis client
        mock_redis = AsyncMock(spec=aioredis.Redis)
        mock_redis.rpush = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)

        # Mock failing HTTP response (503 Service Unavailable)
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 503
        mock_response.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "503 Service Unavailable", request=Mock(), response=mock_response
            )
        )

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        # Create webhook publisher with patch
        with patch(
            "src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient",
            return_value=mock_client,
        ):
            webhook_publisher = WebhookEventPublisher(
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
            )

            # Wrap with retry logic
            publisher_with_retry = EventPublisherWithRetry(
                publisher=webhook_publisher,
                redis_client=mock_redis,
                max_retry_attempts=5,
            )

            # Publish event (should retry and eventually fail)
            with pytest.raises(InfrastructureError):
                await publisher_with_retry.publish(sample_event)

        # Verify multiple retry attempts were made (5 attempts)
        assert mock_client.post.call_count == 5

        # Verify DLQ entry was created after max retries
        mock_redis.rpush.assert_called_once()
        mock_redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_timeout_triggers_retry_and_dlq(
        self,
        webhook_url: str,
        webhook_secret: str,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test that webhook timeouts trigger retry logic and DLQ fallback."""
        # Mock Redis client
        mock_redis = AsyncMock(spec=aioredis.Redis)
        mock_redis.rpush = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)

        # Mock timeout exception
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Request timeout"))
        mock_client.aclose = AsyncMock()

        # Create webhook publisher with patch
        with patch(
            "src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient",
            return_value=mock_client,
        ):
            webhook_publisher = WebhookEventPublisher(
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
                webhook_timeout=1,
            )

            # Wrap with retry logic
            publisher_with_retry = EventPublisherWithRetry(
                publisher=webhook_publisher,
                redis_client=mock_redis,
                max_retry_attempts=3,  # Fewer retries for timeout test
            )

            # Publish event (should retry and eventually fail)
            with pytest.raises(InfrastructureError, match="Webhook timeout"):
                await publisher_with_retry.publish(sample_event)

        # Verify retry attempts were made (3 attempts)
        assert mock_client.post.call_count == 3

        # Verify DLQ entry was created after max retries
        mock_redis.rpush.assert_called_once()
        mock_redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_signature_generation_correctness(
        self,
        webhook_url: str,
        webhook_secret: str,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test that webhook signature generation produces correct HMAC-SHA256."""
        with patch("src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient"):
            publisher = WebhookEventPublisher(
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
            )

            payload_json = sample_event.to_json()
            signature = publisher._generate_signature(payload_json)

            # Verify signature manually
            expected_signature = hmac.new(
                key=webhook_secret.encode("utf-8"),
                msg=payload_json.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).hexdigest()

            assert signature == expected_signature
            assert len(signature) == 64  # 256 bits = 64 hex chars

    @pytest.mark.asyncio
    async def test_webhook_request_headers_and_payload(
        self,
        webhook_url: str,
        webhook_secret: str,
        sample_event: FileLoadCompletedEvent,
    ) -> None:
        """Test that webhook request includes correct headers and payload."""
        # Mock successful HTTP response
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        with patch(
            "src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient",
            return_value=mock_client,
        ):
            publisher = WebhookEventPublisher(
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
            )
            await publisher.publish(sample_event)

        # Verify POST request
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args

        # Verify URL
        assert call_args.args[0] == webhook_url

        # Verify payload
        payload_json = sample_event.to_json()
        assert call_args.kwargs["content"] == payload_json

        # Verify headers
        headers = call_args.kwargs["headers"]
        assert headers["Content-Type"] == "application/json"
        assert headers["X-Event-Type"] == "FILE_LOAD_COMPLETED"
        assert headers["X-Idempotency-Key"] == str(sample_event.file_id)
        assert "X-Webhook-Signature" in headers
        assert headers["X-Webhook-Signature"].startswith("sha256=")

        # Verify signature in header
        signature_hex = headers["X-Webhook-Signature"].replace("sha256=", "")
        expected_sig = hmac.new(
            key=webhook_secret.encode("utf-8"),
            msg=payload_json.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        assert signature_hex == expected_sig
