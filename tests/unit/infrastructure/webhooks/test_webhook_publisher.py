"""Unit tests for WebhookEventPublisher.

Tests webhook event publishing with mocked httpx client to verify:
- HMAC-SHA256 signature generation
- HTTP request headers and payload
- Timeout handling
- HTTP error responses
- Network errors
- Event serialization
- Structured logging
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import httpx
import pytest

from src.domain.entities.events import FileLoadCompletedEvent
from src.domain.exceptions import InfrastructureError
from src.domain.value_objects.sha256_hash import SHA256Hash


# Module under test will be imported after implementation
# from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher


@pytest.fixture
def webhook_url() -> str:
    """Webhook URL fixture."""
    return "https://example.com/webhooks/file-load-completed"


@pytest.fixture
def webhook_secret() -> str:
    """Webhook secret fixture."""
    return "test-webhook-secret-key-12345"


@pytest.fixture
def webhook_timeout() -> int:
    """Webhook timeout fixture."""
    return 10


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


@pytest.fixture
def expected_signature(webhook_secret: str, sample_event: FileLoadCompletedEvent) -> str:
    """Expected HMAC-SHA256 signature for sample event."""
    payload_json = sample_event.to_json()
    return hmac.new(
        key=webhook_secret.encode("utf-8"),
        msg=payload_json.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


class TestWebhookEventPublisherInit:
    """Test WebhookEventPublisher initialization."""

    def test_init_stores_configuration(
        self, webhook_url: str, webhook_secret: str, webhook_timeout: int
    ) -> None:
        """Test that __init__ stores webhook configuration."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        with patch("src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient"):
            publisher = WebhookEventPublisher(
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
                webhook_timeout=webhook_timeout,
            )

            assert publisher._webhook_url == webhook_url
            assert publisher._webhook_secret == webhook_secret
            assert publisher._timeout == webhook_timeout

    def test_init_default_timeout(self, webhook_url: str, webhook_secret: str) -> None:
        """Test that __init__ uses default timeout when not specified."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        with patch("src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient"):
            publisher = WebhookEventPublisher(
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
            )

            assert publisher._timeout == 10

    def test_init_validates_empty_url(self, webhook_secret: str) -> None:
        """Test that __init__ raises ValueError for empty webhook_url."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        with pytest.raises(ValueError, match="webhook_url cannot be empty"):
            WebhookEventPublisher(webhook_url="", webhook_secret=webhook_secret)

    def test_init_validates_empty_secret(self, webhook_url: str) -> None:
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        with pytest.raises(ValueError, match="webhook_secret cannot be empty"):
            WebhookEventPublisher(webhook_url=webhook_url, webhook_secret="")

    def test_init_validates_whitespace_only_url(self, webhook_secret: str) -> None:
        """Test that __init__ raises ValueError for whitespace-only webhook_url."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        with pytest.raises(ValueError, match="webhook_url cannot be empty"):
            WebhookEventPublisher(webhook_url="   ", webhook_secret=webhook_secret)

    def test_init_validates_whitespace_only_secret(self, webhook_url: str) -> None:
        """Test that __init__ raises ValueError for whitespace-only webhook_secret."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        with pytest.raises(ValueError, match="webhook_secret cannot be empty"):
            WebhookEventPublisher(webhook_url=webhook_url, webhook_secret="\t")

    def test_init_validates_invalid_url_format(self, webhook_secret: str) -> None:
        """Test that __init__ raises ValueError for invalid URL format."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        with pytest.raises(ValueError, match="Invalid webhook URL format"):
            WebhookEventPublisher(webhook_url="not a url", webhook_secret=webhook_secret)

    def test_init_validates_zero_timeout(self, webhook_url: str, webhook_secret: str) -> None:
        """Test that __init__ raises ValueError for zero timeout."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        with pytest.raises(ValueError, match="webhook_timeout must be positive"):
            WebhookEventPublisher(
                webhook_url=webhook_url, webhook_secret=webhook_secret, webhook_timeout=0
            )

    def test_init_validates_negative_timeout(self, webhook_url: str, webhook_secret: str) -> None:
        """Test that __init__ raises ValueError for negative timeout."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        with pytest.raises(ValueError, match="webhook_timeout must be positive"):
            WebhookEventPublisher(
                webhook_url=webhook_url, webhook_secret=webhook_secret, webhook_timeout=-1
            )


class TestSignatureGeneration:
    """Test HMAC-SHA256 signature generation."""

    def test_generate_signature_correctness(
        self, webhook_secret: str, sample_event: FileLoadCompletedEvent, expected_signature: str
    ) -> None:
        """Test that signature generation produces correct HMAC-SHA256 hash."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        with patch("src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient"):
            publisher = WebhookEventPublisher(
                webhook_url="https://example.com/webhook",
                webhook_secret=webhook_secret,
            )

            payload_json = sample_event.to_json()
            signature = publisher._generate_signature(payload_json)

            assert signature == expected_signature
            assert len(signature) == 64  # 256 bits = 64 hex chars

    def test_generate_signature_deterministic(
        self, webhook_url: str, webhook_secret: str, sample_event: FileLoadCompletedEvent
    ) -> None:
        """Test that signature generation is deterministic."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        with patch("src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient"):
            publisher = WebhookEventPublisher(
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
            )

            payload_json = sample_event.to_json()
            signature1 = publisher._generate_signature(payload_json)
            signature2 = publisher._generate_signature(payload_json)

            assert signature1 == signature2

    def test_generate_signature_different_secrets(
        self, webhook_url: str, sample_event: FileLoadCompletedEvent
    ) -> None:
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        with patch("src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient"):
            publisher1 = WebhookEventPublisher(webhook_url=webhook_url, webhook_secret="secret1")
            publisher2 = WebhookEventPublisher(webhook_url=webhook_url, webhook_secret="secret2")

            payload_json = sample_event.to_json()
            signature1 = publisher1._generate_signature(payload_json)
            signature2 = publisher2._generate_signature(payload_json)

            assert signature1 != signature2


class TestWebhookPublish:
    """Test webhook event publishing."""

    @pytest.mark.asyncio
    async def test_publish_success(
        self,
        webhook_url: str,
        webhook_secret: str,
        sample_event: FileLoadCompletedEvent,
        expected_signature: str,
    ) -> None:
        """Test successful webhook publish with correct headers and payload."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        # Mock httpx.Response
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()

        # Mock httpx.AsyncClient
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        # Patch AsyncClient constructor
        with patch(
            "src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient",
            return_value=mock_client,
        ):
            publisher = WebhookEventPublisher(
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
            )
            await publisher.publish(sample_event)

        # Verify POST request was made
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
        assert headers["X-Webhook-Signature"] == f"sha256={expected_signature}"
        assert headers["X-Event-Type"] == "FILE_LOAD_COMPLETED"
        assert headers["X-Idempotency-Key"] == str(sample_event.file_id)

        # Verify raise_for_status was called
        mock_response.raise_for_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_timeout_error(
        self, webhook_url: str, webhook_secret: str, sample_event: FileLoadCompletedEvent
    ) -> None:
        """Test that timeout errors raise InfrastructureError."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        # Mock timeout exception
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Request timeout"))
        mock_client.aclose = AsyncMock()

        with patch(
            "src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient",
            return_value=mock_client,
        ):
            publisher = WebhookEventPublisher(
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
                webhook_timeout=1,
            )
            with pytest.raises(InfrastructureError, match="Webhook timeout"):
                await publisher.publish(sample_event)

    @pytest.mark.asyncio
    async def test_publish_http_4xx_error(
        self, webhook_url: str, webhook_secret: str, sample_event: FileLoadCompletedEvent
    ) -> None:
        """Test that 4xx HTTP errors raise InfrastructureError."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        # Mock 401 response
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "401 Unauthorized", request=Mock(), response=mock_response
            )
        )

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
            with pytest.raises(InfrastructureError, match="Webhook HTTP error 401"):
                await publisher.publish(sample_event)

    @pytest.mark.asyncio
    async def test_publish_http_5xx_error(
        self, webhook_url: str, webhook_secret: str, sample_event: FileLoadCompletedEvent
    ) -> None:
        """Test that 5xx HTTP errors raise InfrastructureError."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        # Mock 503 response
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

        with patch(
            "src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient",
            return_value=mock_client,
        ):
            publisher = WebhookEventPublisher(
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
            )
            with pytest.raises(InfrastructureError, match="Webhook HTTP error 503"):
                await publisher.publish(sample_event)

    @pytest.mark.asyncio
    async def test_publish_connection_error(
        self, webhook_url: str, webhook_secret: str, sample_event: FileLoadCompletedEvent
    ) -> None:
        """Test that network errors raise InfrastructureError."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        # Mock connection error
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.aclose = AsyncMock()

        with patch(
            "src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient",
            return_value=mock_client,
        ):
            publisher = WebhookEventPublisher(
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
            )
            with pytest.raises(InfrastructureError, match="Webhook publish failed"):
                await publisher.publish(sample_event)

    @pytest.mark.asyncio
    async def test_publish_logs_attempt(
        self,
        webhook_url: str,
        webhook_secret: str,
        sample_event: FileLoadCompletedEvent,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that publish logs webhook attempt with event metadata."""
        import logging

        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        # Set log level to capture INFO logs
        caplog.set_level(logging.INFO)

        # Mock successful response
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

        # Verify structured logging
        log_messages = [record.message for record in caplog.records]
        assert any("Publishing event via webhook" in msg for msg in log_messages), (
            f"Log messages: {log_messages}"
        )
        assert any("Webhook publish successful" in msg for msg in log_messages), (
            f"Log messages: {log_messages}"
        )

    @pytest.mark.asyncio
    async def test_publish_logs_failure(
        self,
        webhook_url: str,
        webhook_secret: str,
        sample_event: FileLoadCompletedEvent,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that publish logs webhook failure with error details."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        # Mock timeout exception
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Request timeout"))
        mock_client.aclose = AsyncMock()

        with patch(
            "src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient",
            return_value=mock_client,
        ):
            publisher = WebhookEventPublisher(
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
            )
            with pytest.raises(InfrastructureError):
                await publisher.publish(sample_event)

        # Verify error logging
        assert any("Webhook publish failed" in record.message for record in caplog.records)


class TestProtocolCompliance:
    """Test IEventPublisher protocol compliance."""

    def test_implements_ievent_publisher(self, webhook_url: str, webhook_secret: str) -> None:
        """Test that WebhookEventPublisher implements IEventPublisher protocol."""
        from src.domain.protocols.event_publisher import IEventPublisher
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        with patch("src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient"):
            publisher = WebhookEventPublisher(
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
            )

            assert isinstance(publisher, IEventPublisher)

    def test_has_publish_method(self, webhook_url: str, webhook_secret: str) -> None:
        """Test that WebhookEventPublisher has publish() method."""
        from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher

        with patch("src.infrastructure.webhooks.webhook_publisher.httpx.AsyncClient"):
            publisher = WebhookEventPublisher(
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
            )

            assert hasattr(publisher, "publish")
            assert callable(publisher.publish)
