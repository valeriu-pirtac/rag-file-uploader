"""Application configuration management with Pydantic Settings.

This module provides centralized, type-safe configuration management for all
external service dependencies and application settings. Configuration is loaded
from environment variables and .env files with validation at startup.
"""

import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Application configuration with validation.

    All settings are loaded from environment variables or .env file.
    Required fields will raise ValidationError on startup if missing.

    Attributes:
        Application Settings:
            max_file_size: Maximum file size in bytes (default: 500 MB, max: 1 GB)
            max_chunk_size: Maximum chunk size in bytes (default: 100 MB)
            max_concurrent_uploads: Maximum concurrent uploads per workspace (default: 10, max: 10)
            chunk_size: Chunk size for resumable uploads in bytes (default: 25 MB)
            session_ttl_hours: Upload session TTL in hours (default: 24)
            allowed_mime_types: List of allowed MIME types (default: ["application/pdf"])

        Redis Configuration:
            redis_url: Redis connection URL (default: "redis://localhost:6379/0")

        MinIO/S3 Storage Configuration:
            minio_endpoint: MinIO service endpoint (REQUIRED)
            minio_root_user: MinIO root username (default: "admin")
            minio_root_password: MinIO root password (default: "admin")
            s3_bucket_name: S3 bucket name for file storage (REQUIRED)
            s3_use_ssl: Use SSL for S3 connections (default: False)
            s3_region: S3 region (default: "eu-west-2")

        NATS Configuration:
            nats_url: NATS server URL (required if event_publish_mode == "nats")
            nats_subject: NATS subject for events (default: "file.load.completed")
            event_publish_mode: Event publish mode - "nats" or "webhook" (default: "nats")

        ClamAV Configuration:
            clamav_host: ClamAV clamd service host (REQUIRED)
            clamav_port: ClamAV clamd service port (default: 3310)
            clamav_timeout: ClamAV scan timeout in seconds (default: 30)

        JWT Configuration:
            jwt_public_key: RSA public key for JWT validation (REQUIRED, PEM format)
            jwt_algorithm: JWT signing algorithm (default: "RS256")

        Webhook Configuration:
            webhook_url: Webhook URL for events (required if event_publish_mode == "webhook")
            webhook_secret: Webhook secret for HMAC (required if event_publish_mode == "webhook")
            webhook_timeout: Webhook request timeout in seconds (default: 10)

        Observability Configuration:
            log_level: Logging level (default: "INFO")
            log_format: Log format - "json" or "console" (default: "json")
            metrics_enabled: Enable Prometheus metrics (default: True)

        Server Configuration:
            host: Server bind host (default: "0.0.0.0")
            port: Server bind port (default: 8000)
            workers: Number of worker processes (default: 1)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore unknown environment variables
    )

    # Application Settings
    max_file_size: int = Field(
        default=524_288_000,
        gt=0,
        le=1_073_741_824,
        description="Maximum file size in bytes (500 MB, max 1 GB)",
    )
    max_chunk_size: int = Field(
        default=104_857_600, gt=0, description="Maximum chunk size in bytes (100 MB)"
    )
    max_concurrent_uploads: int = Field(
        default=10, gt=0, le=10, description="Maximum concurrent uploads per workspace"
    )
    chunk_size: int = Field(
        default=26_214_400, gt=0, description="Chunk size for resumable uploads (25 MB)"
    )
    session_ttl_hours: int = Field(default=24, gt=0, description="Upload session TTL in hours")
    allowed_mime_types: list[str] = Field(
        default=["application/pdf"], min_length=1, description="Allowed MIME types for upload"
    )

    # Redis Configuration
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")

    # MinIO/S3 Storage Configuration
    minio_endpoint: str = Field(..., min_length=1, description="MinIO service endpoint (REQUIRED)")
    minio_root_user: str = Field(default="admin", min_length=1, description="MinIO root username")
    minio_root_password: SecretStr = Field(
        default=SecretStr("admin"), description="MinIO root password"
    )
    s3_bucket_name: str = Field(
        ..., min_length=3, description="S3 bucket name for file storage (REQUIRED)"
    )
    s3_use_ssl: bool = Field(default=False, description="Use SSL for S3 connections")
    s3_region: str = Field(default="eu-west-2", description="S3 region")
    s3_server_side_encryption: bool = Field(
        default=True,
        description="Enable server-side encryption (AES256) for S3 objects (requires KMS configuration for MinIO)",
    )

    # NATS Configuration
    nats_url: str | None = Field(
        default=None, description="NATS server URL (required if event_publish_mode == 'nats')"
    )
    nats_subject: str = Field(
        default="file.load.completed", description="NATS subject for file load events"
    )
    event_publish_mode: Literal["nats", "webhook"] = Field(
        default="nats", description="Event publish mode"
    )

    # ClamAV Configuration
    clamav_host: str = Field(..., min_length=1, description="ClamAV clamd service host (REQUIRED)")
    clamav_port: int = Field(default=3310, ge=1, le=65535, description="ClamAV clamd service port")
    clamav_timeout: int = Field(default=30, gt=0, description="ClamAV scan timeout in seconds")

    # JWT Configuration
    jwt_public_key: str = Field(
        ..., description="RSA public key for JWT validation (REQUIRED, PEM format)"
    )
    jwt_algorithm: str = Field(default="RS256", description="JWT signing algorithm")

    # Webhook Configuration (alternative to NATS)
    webhook_url: str | None = Field(
        default=None, description="Webhook URL (required if event_publish_mode == 'webhook')"
    )
    webhook_secret: SecretStr | None = Field(
        default=None, description="Webhook secret (required if event_publish_mode == 'webhook')"
    )
    webhook_timeout: int = Field(default=10, gt=0, description="Webhook request timeout in seconds")

    # Observability Configuration
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: Literal["json", "console"] = Field(default="json", description="Log format")
    metrics_enabled: bool = Field(default=True, description="Enable Prometheus metrics")

    # Server Configuration
    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8000, ge=1, le=65535, description="Server bind port")
    workers: int = Field(default=1, gt=0, description="Number of worker processes")

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, v: str) -> str:
        """Validate Redis URL scheme.

        Args:
            v: Redis URL to validate

        Returns:
            Validated Redis URL

        Raises:
            ValueError: If URL doesn't use redis:// or rediss:// scheme
        """
        if not v.startswith(("redis://", "rediss://")):
            raise ValueError("Redis URL must start with redis:// or rediss://")
        return v

    @field_validator("minio_root_password")
    @classmethod
    def validate_minio_password(cls, v: SecretStr) -> SecretStr:
        """Validate MinIO password is not empty.

        Args:
            v: MinIO password to validate

        Returns:
            Validated password

        Raises:
            ValueError: If password is empty
        """
        if len(v.get_secret_value()) == 0:
            raise ValueError("MinIO root password cannot be empty")
        return v

    @field_validator("s3_bucket_name")
    @classmethod
    def validate_s3_bucket_name(cls, v: str) -> str:
        """Validate S3 bucket name follows naming rules.

        Args:
            v: Bucket name to validate

        Returns:
            Validated bucket name

        Raises:
            ValueError: If bucket name violates S3 naming rules
        """
        if not (3 <= len(v) <= 63):
            raise ValueError("S3 bucket name must be between 3 and 63 characters")
        if not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", v):
            raise ValueError(
                "S3 bucket name must be lowercase alphanumeric with hyphens, "
                "starting and ending with alphanumeric"
            )
        if "--" in v or ".-" in v or "-." in v:
            raise ValueError("S3 bucket name cannot contain consecutive special characters")
        return v

    @field_validator("nats_url")
    @classmethod
    def validate_nats_url(cls, v: str | None) -> str | None:
        """Validate NATS URL scheme.

        Args:
            v: NATS URL to validate

        Returns:
            Validated NATS URL

        Raises:
            ValueError: If URL doesn't use nats:// or tls:// scheme
        """
        if v is not None and not v.startswith(("nats://", "tls://")):
            raise ValueError("NATS URL must start with nats:// or tls://")
        return v

    @field_validator("nats_subject")
    @classmethod
    def validate_nats_subject(cls, v: str) -> str:
        """Validate NATS subject format.

        Args:
            v: NATS subject to validate

        Returns:
            Validated subject

        Raises:
            ValueError: If subject contains invalid characters
        """
        if not re.match(r"^[a-zA-Z0-9._-]+$", v):
            raise ValueError(
                "NATS subject can only contain alphanumeric, dots, underscores, and hyphens"
            )
        if " " in v:
            raise ValueError("NATS subject cannot contain spaces")
        return v

    @field_validator("jwt_public_key")
    @classmethod
    def validate_jwt_public_key(cls, v: str) -> str:
        """Validate JWT public key is in PEM format.

        Args:
            v: Public key to validate

        Returns:
            Validated public key

        Raises:
            ValueError: If key is not valid PEM format
        """
        try:
            from cryptography.hazmat.primitives import serialization

            # Handle escaped newlines from .env files
            key_content = v.replace("\\n", "\n")
            serialization.load_pem_public_key(key_content.encode())
            return key_content  # Return with actual newlines
        except Exception as e:
            raise ValueError(f"Invalid PEM format for JWT public key: {e}") from e

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is a valid Python logging level.

        Args:
            v: Log level to validate

        Returns:
            Validated log level (uppercase)

        Raises:
            ValueError: If log level is invalid
        """
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"Log level must be one of: {', '.join(valid_levels)}")
        return v_upper

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: str | None) -> str | None:
        """Ensure webhook URLs use HTTPS in production (except localhost).

        Args:
            v: Webhook URL to validate

        Returns:
            Validated webhook URL

        Raises:
            ValueError: If webhook URL doesn't use HTTPS (except localhost)
        """
        if v is not None and not v.startswith(("http://localhost", "http://127.0.0.1", "https://")):
            raise ValueError("Webhook URL must use HTTPS (except localhost)")
        return v

    @model_validator(mode="after")
    def validate_event_mode_requirements(self) -> "AppSettings":
        """Validate conditional requirements based on event_publish_mode.

        NATS mode requires: nats_url
        Webhook mode requires: webhook_url, webhook_secret (non-empty)
        Also validates chunk_size <= max_chunk_size

        Returns:
            Validated AppSettings instance

        Raises:
            ValueError: If required fields for the selected event mode are missing or invalid
        """
        # Validate chunk size constraints
        if self.chunk_size > self.max_chunk_size:
            raise ValueError(
                f"chunk_size ({self.chunk_size}) cannot exceed max_chunk_size ({self.max_chunk_size})"
            )

        # Validate event mode requirements
        if self.event_publish_mode == "nats" and not self.nats_url:
            raise ValueError("NATS_URL is required when EVENT_PUBLISH_MODE is 'nats'")

        if self.event_publish_mode == "webhook":
            if not self.webhook_url:
                raise ValueError("WEBHOOK_URL is required when EVENT_PUBLISH_MODE is 'webhook'")
            if not self.webhook_secret:
                raise ValueError("WEBHOOK_SECRET is required when EVENT_PUBLISH_MODE is 'webhook'")
            # Validate webhook_secret is not empty
            if len(self.webhook_secret.get_secret_value()) == 0:
                raise ValueError(
                    "WEBHOOK_SECRET cannot be empty when EVENT_PUBLISH_MODE is 'webhook'"
                )

        return self


@lru_cache
def get_settings() -> AppSettings:
    """Get singleton settings instance.

    Uses functools.lru_cache to ensure settings are loaded only once
    and the same instance is returned on subsequent calls.

    Returns:
        Singleton AppSettings instance

    Raises:
        ValidationError: If required settings are missing or invalid
    """
    return AppSettings()  # type: ignore[call-arg]  # Pydantic loads from env
