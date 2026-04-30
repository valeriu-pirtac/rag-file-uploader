"""NATS JetStream integration - Event publishing.

Implements IEventPublisher protocol using nats-py for:
- FILE_LOAD_COMPLETED event publishing
- At-least-once delivery with retry logic
- Durable subject configuration
"""
