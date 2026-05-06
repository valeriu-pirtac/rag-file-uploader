"""Webhook infrastructure module.

This module provides webhook-based event publishing as an alternative to NATS
for downstream RAG pipeline integration.
"""

from __future__ import annotations

from src.infrastructure.webhooks.webhook_publisher import WebhookEventPublisher


__all__ = ["WebhookEventPublisher"]
