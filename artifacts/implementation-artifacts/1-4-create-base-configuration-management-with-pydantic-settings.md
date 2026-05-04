# Story 1.4: Create Base Configuration Management with Pydantic Settings

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **developer**,
I want **centralized configuration management using Pydantic Settings**,
So that **all environment variables are validated, typed, and documented in one place**.

## Acceptance Criteria

1. **Given** infrastructure layer exists
   **When** configuration is implemented
   **Then** src/infrastructure/config/settings.py exists with AppSettings class

2. **And** settings inherit from pydantic_settings.BaseSettings

3. **And** configuration includes: REDIS_URL, MINIO_ENDPOINT, NATS_URL, CLAMAV_HOST, CLAMAV_PORT, JWT_PUBLIC_KEY, MAX_CONCURRENT_UPLOADS

4. **And** all settings have type annotations and default values where appropriate

5. **And** settings load from .env file and environment variables

6. **And** missing required settings raise clear validation errors on startup

7. **And** settings are instantiated once as singleton pattern

## Tasks / Subtasks

- [x] Create AppSettings class in src/infrastructure/config/settings.py (AC: #1, #2)
  - [x] Import BaseSettings from pydantic_settings
  - [x] Configure model_config with env_file=".env", case_sensitive=False
  - [x] Define all configuration fields with proper types and defaults
  - [x] Add SecretStr for sensitive credentials

- [x] Implement core application settings (AC: #3, #4)
  - [x] MAX_FILE_SIZE: int = 1_073_741_824 (1 GB)
  - [x] MAX_CONCURRENT_UPLOADS: int = 10
  - [x] CHUNK_SIZE: int = 26_214_400 (25 MB)
  - [x] SESSION_TTL_HOURS: int = 24
  - [x] ALLOWED_MIME_TYPES: list[str] = ["application/pdf"]

- [x] Implement Redis configuration (AC: #3, #4)
  - [x] REDIS_URL: str with default "redis://localhost:6379/0"

- [x] Implement MinIO/S3 configuration (AC: #3, #4)
  - [x] MINIO_ENDPOINT: str (required)
  - [x] MINIO_ROOT_USER: str = "minioadmin"
  - [x] MINIO_ROOT_PASSWORD: SecretStr = "minioadmin123"
  - [x] S3_BUCKET_NAME: str (required)
  - [x] S3_USE_SSL: bool = True
  - [x] S3_REGION: str = "us-east-1"

- [x] Implement NATS configuration (AC: #3, #4)
  - [x] NATS_URL: str (required for nats mode)
  - [x] NATS_SUBJECT: str = "file.load.completed"
  - [x] EVENT_PUBLISH_MODE: Literal["nats", "webhook"] = "nats"

- [x] Implement ClamAV configuration (AC: #3, #4, #5)
  - [x] CLAMAV_HOST: str (required)
  - [x] CLAMAV_PORT: int = 3310
  - [x] CLAMAV_TIMEOUT: int = 30

- [x] Implement JWT configuration (AC: #3, #4)
  - [x] JWT_PUBLIC_KEY: str (required)
  - [x] JWT_ALGORITHM: str = "RS256"

- [x] Implement webhook configuration (optional alternative to NATS)
  - [x] WEBHOOK_URL: str (required if webhook mode)
  - [x] WEBHOOK_SECRET: SecretStr (required if webhook mode)
  - [x] WEBHOOK_TIMEOUT: int = 10

- [x] Implement observability configuration
  - [x] LOG_LEVEL: str = "INFO"
  - [x] LOG_FORMAT: str = "json"
  - [x] METRICS_ENABLED: bool = True

- [x] Implement server configuration
  - [x] HOST: str = "0.0.0.0"
  - [x] PORT: int = 8000
  - [x] WORKERS: int = 1

- [x] Add Pydantic validators for complex validation (AC: #4, #6)
  - [x] @field_validator for webhook_url to enforce HTTPS in production
  - [x] @model_validator to check conditional requirements (webhook vs nats)
  - [x] Validators for positive integers (max_file_size, chunk_size, etc.)

- [x] Implement singleton pattern (AC: #7)
  - [x] Create get_settings() function with @lru_cache
  - [x] Return single instance of AppSettings

- [x] Update .env.example with new configuration fields (AC: #5)
  - [x] Add all new settings with descriptions
  - [x] Document required vs optional settings
  - [x] Add value examples and format guidance

- [x] Create unit tests for settings (testing standard)
  - [x] Test default values load correctly
  - [x] Test required fields raise validation errors when missing
  - [x] Test validators work correctly
  - [x] Test SecretStr fields are protected
  - [x] Test singleton pattern returns same instance

- [x] Create integration test for settings loading
  - [x] Test loading from .env file
  - [x] Test environment variable overrides
  - [x] Test validation errors on startup

## Dev Notes

### Architecture Requirements

**FR35 (partial)**: Configuration management for all external service dependencies.

**Configuration Philosophy from Architecture:**
- Type-safe configuration using Pydantic Settings for validation at startup
- Environment-based configuration with .env files for development
- Clear validation errors that fail fast on startup if misconfigured
- Singleton pattern for efficient configuration access throughout application
- Secrets protected with SecretStr to prevent accidental logging/exposure

**External Service Dependencies:**

This story creates the configuration layer for all external services established in Story 1.3:

1. **Redis** - Upload session state store
   - Connection: REDIS_URL
   - Purpose: Session persistence with 24-hour TTL, atomic operations

2. **MinIO/S3** - Bronze-layer file storage
   - Connection: MINIO_ENDPOINT, credentials
   - Purpose: Immutable file storage with workspace isolation

3. **NATS JetStream** - Event bus for FILE_LOAD_COMPLETED events
   - Connection: NATS_URL
   - Purpose: Durable event publishing to downstream services

4. **ClamAV** - Virus scanning service
   - Connection: CLAMAV_HOST:CLAMAV_PORT
   - Purpose: Malware detection before file completion

5. **JWT Authentication** - Token validation
   - Connection: JWT_PUBLIC_KEY
   - Purpose: RS256 asymmetric signature verification

### Critical Configuration Details

**MUST HAVE Settings (Required, no defaults):**
- `MINIO_ENDPOINT` - MinIO service endpoint (e.g., "minio:9000")
- `S3_BUCKET_NAME` - Bucket for file storage
- `CLAMAV_HOST` - ClamAV service host
- `JWT_PUBLIC_KEY` - RSA public key in PEM format for token validation

**CONDITIONAL Requirements:**
- If `EVENT_PUBLISH_MODE="nats"` → `NATS_URL` is required
- If `EVENT_PUBLISH_MODE="webhook"` → `WEBHOOK_URL` and `WEBHOOK_SECRET` are required

**Application Settings with Defaults:**
- `MAX_FILE_SIZE`: 1_073_741_824 (1 GB) - Enforces FR14
- `MAX_CONCURRENT_UPLOADS`: 10 - Enforces FR34 rate limiting
- `CHUNK_SIZE`: 26_214_400 (25 MB) - Optimal chunk size per NFR-P3
- `SESSION_TTL_HOURS`: 24 - Enforces FR10 session persistence
- `ALLOWED_MIME_TYPES`: ["application/pdf"] - Enforces FR15

**Security-Sensitive Settings:**
Use `SecretStr` type for:
- `MINIO_ROOT_PASSWORD`
- `WEBHOOK_SECRET`
- Any S3 secret keys (for AWS S3 vs MinIO)

### Configuration Structure

**Settings Class Structure:**
```python
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal

class AppSettings(BaseSettings):
    """Application configuration with validation."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"  # Ignore unknown env vars
    )
    
    # Application Settings
    max_file_size: int = Field(default=1_073_741_824, gt=0)
    max_concurrent_uploads: int = Field(default=10, gt=0)
    chunk_size: int = Field(default=26_214_400, gt=0)
    session_ttl_hours: int = Field(default=24, gt=0)
    allowed_mime_types: list[str] = Field(default=["application/pdf"])
    
    # Redis Configuration
    redis_url: str = "redis://localhost:6379/0"
    
    # MinIO/S3 Configuration
    minio_endpoint: str  # REQUIRED
    minio_root_user: str = "minioadmin"
    minio_root_password: SecretStr = SecretStr("minioadmin123")
    s3_bucket_name: str  # REQUIRED
    s3_use_ssl: bool = True
    s3_region: str = "us-east-1"
    
    # NATS Configuration
    nats_url: str | None = None  # Required if event_publish_mode == "nats"
    nats_subject: str = "file.load.completed"
    event_publish_mode: Literal["nats", "webhook"] = "nats"
    
    # ClamAV Configuration
    clamav_host: str  # REQUIRED
    clamav_port: int = 3310
    clamav_timeout: int = 30
    
    # JWT Configuration
    jwt_public_key: str  # REQUIRED - PEM format RSA public key
    jwt_algorithm: str = "RS256"
    
    # Webhook Configuration (alternative to NATS)
    webhook_url: str | None = None  # Required if event_publish_mode == "webhook"
    webhook_secret: SecretStr | None = None  # Required if event_publish_mode == "webhook"
    webhook_timeout: int = 10
    
    # Observability Configuration
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    metrics_enabled: bool = True
    
    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    
    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: str | None, info) -> str | None:
        """Ensure webhook URLs use HTTPS in production."""
        if v is not None and not v.startswith(("http://localhost", "http://127.0.0.1", "https://")):
            raise ValueError("Webhook URL must use HTTPS (except localhost)")
        return v
    
    @model_validator(mode="after")
    def validate_event_mode_requirements(self) -> "AppSettings":
        """Validate conditional requirements based on event_publish_mode."""
        if self.event_publish_mode == "nats" and not self.nats_url:
            raise ValueError("NATS_URL is required when EVENT_PUBLISH_MODE is 'nats'")
        if self.event_publish_mode == "webhook":
            if not self.webhook_url:
                raise ValueError("WEBHOOK_URL is required when EVENT_PUBLISH_MODE is 'webhook'")
            if not self.webhook_secret:
                raise ValueError("WEBHOOK_SECRET is required when EVENT_PUBLISH_MODE is 'webhook'")
        return self

# Singleton pattern
from functools import lru_cache

@lru_cache
def get_settings() -> AppSettings:
    """Get singleton settings instance."""
    return AppSettings()
```

### Previous Story Learnings

**From Story 1.1 (Project Initialization):**
- Clean Architecture structure established: src/infrastructure/config/ exists
- All __init__.py files already created
- Python 3.13 and uv package manager in use

**From Story 1.2 (Development Tools):**
- pytest, mypy, ruff already configured
- pydantic-settings>=2.14.0 already in pyproject.toml dependencies
- Test structure mirrors src/ structure → tests/unit/infrastructure/config/
- Type checking enforced by mypy → all settings must have type annotations
- Code quality enforced by ruff → follow PEP 8 conventions

**From Story 1.3 (Docker Compose):**
- .env.example already exists with basic configuration
- External services running: Redis (6379), MinIO (9000), NATS (4222), ClamAV (3310)
- Environment variables already documented: MINIO_ROOT_USER, MINIO_ROOT_PASSWORD, REDIS_URL, NATS_URL, CLAMAV_HOST, CLAMAV_PORT, MAX_CONCURRENT_UPLOADS
- Need to EXTEND .env.example (not replace) to preserve Story 1.3's work

**Key Pattern Established:**
- Environment variables use UPPER_SNAKE_CASE
- Pydantic settings use snake_case (auto-converted by BaseSettings)
- Secrets stored in .env (gitignored), examples in .env.example (committed)
- Clear documentation in .env.example for each variable

### Project Structure Alignment

**File Locations (Clean Architecture):**
- Settings implementation: `src/infrastructure/config/settings.py`
- Settings export: Update `src/infrastructure/config/__init__.py` to export AppSettings and get_settings
- Tests: `tests/unit/infrastructure/config/test_settings.py`
- Integration tests: `tests/integration/infrastructure/test_config_loading.py`
- Configuration file: `.env.example` (update existing file)

**No Conflicts:**
- infrastructure/config/ directory exists with __init__.py
- No existing settings.py file
- .env.example exists and should be extended, not replaced

### Testing Approach

**Unit Tests (tests/unit/infrastructure/config/test_settings.py):**
```python
from src.infrastructure.config.settings import AppSettings, get_settings
import pytest

def test_settings_with_defaults():
    """Test settings load with default values."""
    # Use monkeypatch to set required fields
    settings = AppSettings(
        minio_endpoint="minio:9000",
        s3_bucket_name="test-bucket",
        clamav_host="clamav",
        jwt_public_key="test-key"
    )
    assert settings.max_file_size == 1_073_741_824
    assert settings.chunk_size == 26_214_400
    assert settings.redis_url == "redis://localhost:6379/0"

def test_settings_required_fields_missing():
    """Test that missing required fields raise validation error."""
    with pytest.raises(ValidationError) as exc:
        AppSettings()
    # Check that minio_endpoint, s3_bucket_name, clamav_host, jwt_public_key are in error

def test_settings_validates_positive_integers():
    """Test that size/count fields must be positive."""
    with pytest.raises(ValidationError):
        AppSettings(
            max_file_size=-1,  # Invalid
            minio_endpoint="minio:9000",
            s3_bucket_name="test",
            clamav_host="clamav",
            jwt_public_key="key"
        )

def test_settings_validates_nats_requirements():
    """Test conditional validation for NATS mode."""
    with pytest.raises(ValidationError) as exc:
        AppSettings(
            event_publish_mode="nats",
            nats_url=None,  # Required but missing
            minio_endpoint="minio:9000",
            s3_bucket_name="test",
            clamav_host="clamav",
            jwt_public_key="key"
        )
    assert "NATS_URL is required" in str(exc.value)

def test_settings_validates_webhook_requirements():
    """Test conditional validation for webhook mode."""
    with pytest.raises(ValidationError):
        AppSettings(
            event_publish_mode="webhook",
            webhook_url=None,  # Required but missing
            minio_endpoint="minio:9000",
            s3_bucket_name="test",
            clamav_host="clamav",
            jwt_public_key="key"
        )

def test_settings_webhook_url_enforces_https():
    """Test webhook URL validation requires HTTPS."""
    with pytest.raises(ValidationError) as exc:
        AppSettings(
            event_publish_mode="webhook",
            webhook_url="http://example.com/webhook",  # HTTP not allowed
            webhook_secret="secret",
            minio_endpoint="minio:9000",
            s3_bucket_name="test",
            clamav_host="clamav",
            jwt_public_key="key"
        )
    assert "must use HTTPS" in str(exc.value)

def test_settings_secret_str_not_exposed():
    """Test that SecretStr fields don't expose values."""
    settings = AppSettings(
        minio_root_password="secret123",
        minio_endpoint="minio:9000",
        s3_bucket_name="test",
        clamav_host="clamav",
        jwt_public_key="key"
    )
    assert "secret123" not in str(settings)
    assert "secret123" not in repr(settings)
    assert settings.minio_root_password.get_secret_value() == "secret123"

def test_singleton_pattern():
    """Test get_settings returns same instance."""
    settings1 = get_settings()
    settings2 = get_settings()
    assert settings1 is settings2
```

**Integration Test (tests/integration/infrastructure/test_config_loading.py):**
```python
from src.infrastructure.config.settings import get_settings
import os
import pytest

def test_load_from_env_file(tmp_path):
    """Test settings load from .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text("""
MINIO_ENDPOINT=minio:9000
S3_BUCKET_NAME=test-bucket
CLAMAV_HOST=clamav
JWT_PUBLIC_KEY=test-public-key
MAX_CONCURRENT_UPLOADS=20
    """)
    
    # Clear cache and reload with new env file
    get_settings.cache_clear()
    settings = get_settings()
    
    assert settings.max_concurrent_uploads == 20

def test_environment_variables_override():
    """Test environment variables override .env file."""
    os.environ["MAX_CONCURRENT_UPLOADS"] = "50"
    get_settings.cache_clear()
    
    settings = get_settings()
    assert settings.max_concurrent_uploads == 50
    
    del os.environ["MAX_CONCURRENT_UPLOADS"]
```

### .env.example Extensions

**Add to existing .env.example file (preserve existing content from Story 1.3):**

```env
# ================================================
# Application Configuration
# ================================================

# File Upload Limits
# Maximum file size in bytes (default: 1 GB)
MAX_FILE_SIZE=1_073_741_824

# Chunk size for uploads in bytes (default: 25 MB)
CHUNK_SIZE=26_214_400

# Session expiry in hours (default: 24 hours per API contract)
SESSION_TTL_HOURS=24

# Allowed MIME types (comma-separated, default: application/pdf)
ALLOWED_MIME_TYPES=application/pdf

# ================================================
# MinIO/S3 Storage Configuration (REQUIRED)
# ================================================

# MinIO endpoint (required for local development)
MINIO_ENDPOINT=minio:9000

# S3 bucket name for file storage (required)
S3_BUCKET_NAME=rag-uploads-bronze

# S3 region (default: us-east-1)
S3_REGION=us-east-1

# Use SSL for S3 connections (default: true)
S3_USE_SSL=true

# ================================================
# Event Publishing Configuration
# ================================================

# Event publish mode: "nats" or "webhook" (default: nats)
EVENT_PUBLISH_MODE=nats

# NATS subject for events (default: file.load.completed)
NATS_SUBJECT=file.load.completed

# Webhook Configuration (required if EVENT_PUBLISH_MODE=webhook)
# WEBHOOK_URL=https://example.com/webhook
# WEBHOOK_SECRET=your-webhook-secret-min-32-chars
# WEBHOOK_TIMEOUT=10

# ================================================
# JWT Authentication Configuration (REQUIRED)
# ================================================

# RSA public key for JWT validation (RS256) - PEM format
# Required for authentication middleware
# JWT_PUBLIC_KEY=-----BEGIN PUBLIC KEY-----\nMIIBIj...\n-----END PUBLIC KEY-----

# JWT algorithm (default: RS256)
JWT_ALGORITHM=RS256

# ================================================
# Observability Configuration
# ================================================

# Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)
LOG_LEVEL=INFO

# Log format: json or console (default: json)
LOG_FORMAT=json

# Enable Prometheus metrics (default: true)
METRICS_ENABLED=true

# ================================================
# Server Configuration
# ================================================

# Server host (default: 0.0.0.0)
HOST=0.0.0.0

# Server port (default: 8000)
PORT=8000

# Number of worker processes (default: 1)
WORKERS=1
```

### Common Pitfalls to Avoid

1. **Forgetting SecretStr for passwords**: Use `SecretStr` type for sensitive fields to prevent accidental logging
2. **Not validating conditional requirements**: Use `@model_validator` to check NATS vs webhook requirements
3. **Hardcoding defaults in multiple places**: Define defaults only in settings class, reference settings everywhere
4. **Not using singleton pattern**: Without @lru_cache, settings reload on every call (inefficient)
5. **Missing field validators**: Add `Field(gt=0)` for positive integers, custom validators for complex rules
6. **Exposing secrets in error messages**: Validation errors should NOT include secret values
7. **Not updating .env.example**: Keep .env.example in sync with all settings for new developers
8. **Replacing instead of extending .env.example**: Story 1.3 created initial file - extend it, don't replace

### Integration with Future Stories

**This story enables:**
- **Story 2.2 (JWT Validation)**: JWT_PUBLIC_KEY configuration for RS256 validation
- **Story 3.2 (Redis Session Store)**: REDIS_URL for session persistence
- **Story 3.3 (Rate Limiting)**: MAX_CONCURRENT_UPLOADS for workspace rate limits
- **Story 5.2 (MinIO Storage)**: MINIO_ENDPOINT, S3_BUCKET_NAME for file assembly
- **Story 5.3 (ClamAV Scanner)**: CLAMAV_HOST, CLAMAV_PORT for virus scanning
- **Story 5.5 (NATS Publisher)**: NATS_URL, NATS_SUBJECT for event publishing
- **Story 5.7 (Webhook Alternative)**: WEBHOOK_URL, WEBHOOK_SECRET for webhooks
- **Story 6.1 (Metrics)**: METRICS_ENABLED for Prometheus
- **Story 6.2 (Logging)**: LOG_LEVEL, LOG_FORMAT for structured logging

### Non-Functional Requirements Addressed

- **NFR-I2**: S3-compatible API configuration (works with MinIO or AWS S3)
- **NFR-I3**: Redis connection configuration for atomic operations
- **NFR-I4**: ClamAV TCP socket configuration
- **NFR-I6**: JWT RS256/HS256 configuration with externalized public key
- **NFR-S4**: JWT validation configuration for 100% request enforcement
- **NFR-SC2**: MAX_CONCURRENT_UPLOADS configurable without code changes

### References

- [Source: artifacts/planning-artifacts/epics.md#Story 1.4] - Story acceptance criteria
- [Source: artifacts/planning-artifacts/architecture.md#Configuration Management] - Configuration patterns
- [Source: artifacts/planning-artifacts/architecture.md#External Service Dependencies] - Service connection requirements
- [Source: artifacts/implementation-artifacts/1-3-set-up-docker-compose-with-all-external-services.md] - .env.example baseline and service endpoints
- [Source: pyproject.toml] - pydantic-settings>=2.14.0 dependency confirmed

## Dev Agent Record

### Agent Model Used

Claude Sonnet 4.5 (GitHub Copilot)

### Implementation Plan

Implemented following Test-Driven Development (TDD) approach:

**RED Phase:**
- Created comprehensive unit tests (test_settings.py) covering all validation rules
- Created integration tests (test_config_loading.py) for environment loading
- Verified tests failed before implementation

**GREEN Phase:**
- Implemented AppSettings class with all required fields and validators
- Added field-level validators for positive integers
- Implemented @field_validator for webhook URL HTTPS enforcement
- Implemented @model_validator for conditional NATS/webhook requirements
- Used SecretStr for sensitive credentials (passwords, secrets)
- Implemented singleton pattern with @lru_cache
- Updated __init__.py exports for clean imports
- Extended .env.example with comprehensive documentation

**REFACTOR Phase:**
- Fixed linting issues with ruff format
- Resolved mypy type checking warnings
- Added comprehensive docstrings following Google style
- Ensured all tests pass (27/27)

### Debug Log References

None - implementation succeeded without major debugging sessions.

### Completion Notes List

✅ **Configuration Implementation Complete**

**Files Created:**
- `src/infrastructure/config/settings.py` - AppSettings class with 40+ configuration fields
- `tests/unit/infrastructure/config/test_settings.py` - 21 unit tests covering validation
- `tests/integration/infrastructure/test_config_loading.py` - 5 integration tests

**Key Accomplishments:**
1. ✅ Type-safe configuration with Pydantic Settings BaseSettings
2. ✅ All required fields enforced: MINIO_ENDPOINT, S3_BUCKET_NAME, CLAMAV_HOST, JWT_PUBLIC_KEY
3. ✅ Conditional validation: NATS mode requires NATS_URL, webhook mode requires WEBHOOK_URL + SECRET
4. ✅ Security: SecretStr protects MINIO_ROOT_PASSWORD and WEBHOOK_SECRET from logging
5. ✅ Validation: Positive integers, HTTPS enforcement, comprehensive error messages
6. ✅ Singleton pattern ensures one instance with @lru_cache
7. ✅ Extended .env.example with detailed documentation for all 40+ settings
8. ✅ 27 tests passing (21 unit + 5 integration + 1 domain)
9. ✅ Code quality: ruff linting passed, mypy type checking passed

**Acceptance Criteria Verification:**
- AC1: ✅ settings.py exists with AppSettings class
- AC2: ✅ Inherits from BaseSettings
- AC3: ✅ All required configs present (Redis, MinIO, NATS, ClamAV, JWT, MAX_CONCURRENT_UPLOADS)
- AC4: ✅ Type annotations and defaults on all fields
- AC5: ✅ Loads from .env file with case-insensitive env vars
- AC6: ✅ ValidationError raised for missing required fields with clear messages
- AC7: ✅ Singleton pattern with get_settings() using @lru_cache

**Technical Decisions:**
- Used `Literal["nats", "webhook"]` for type-safe mode selection
- Validators use Pydantic v2 @field_validator and @model_validator decorators
- Settings are exported from config/__init__.py for clean imports
- Added `extra="ignore"` to allow unknown env vars without errors
- Type ignore added for get_settings() to handle Pydantic's env loading pattern

### File List

**New Files:**
- src/infrastructure/config/settings.py
- tests/unit/infrastructure/__init__.py
- tests/unit/infrastructure/config/__init__.py
- tests/unit/infrastructure/config/test_settings.py
- tests/integration/infrastructure/__init__.py
- tests/integration/infrastructure/test_config_loading.py

**Modified Files:**
- src/infrastructure/config/__init__.py
- .env.example
- artifacts/implementation-artifacts/sprint-status.yaml

## Change Log

**2026-05-04** - Story 1.4 Implementation Complete

**Added:**
- Centralized configuration management with Pydantic Settings
- AppSettings class with 40+ configuration fields for all external services
- Type-safe configuration validation at application startup
- Singleton pattern for efficient settings access via get_settings()
- Comprehensive .env.example documentation with 150+ lines of guidance
- 21 unit tests covering all validation rules and edge cases
- 5 integration tests for environment loading and overrides

**Configuration Coverage:**
- Application settings: file size limits, chunk size, session TTL, MIME types
- Redis: connection URL for session state
- MinIO/S3: endpoint, credentials, bucket, SSL, region
- NATS: URL, subject, event mode configuration
- ClamAV: host, port, timeout for virus scanning
- JWT: public key, algorithm for RS256 validation
- Webhook: URL, secret, timeout as NATS alternative
- Observability: log level, format, metrics enablement
- Server: host, port, workers configuration

**Validation Features:**
- Required field enforcement with clear error messages
- Conditional validation: NATS mode requires NATS_URL, webhook mode requires WEBHOOK_URL + SECRET
- Field validators: positive integers, HTTPS enforcement (except localhost)
- SecretStr protection for passwords and secrets (prevents logging exposure)
- Case-insensitive environment variable loading
- Unknown environment variables ignored gracefully

**Quality Assurance:**
- All 27 tests passing (100% pass rate)
- Ruff linting passed (zero violations)
- Mypy type checking passed (zero errors)
- TDD approach: tests written before implementation
- Comprehensive docstrings following Google style

### Review Findings

#### Decision Needed

- [x] [Review][Decision] JWT_PUBLIC_KEY missing actionable example in .env.example — JWT_PUBLIC_KEY is REQUIRED but only shown commented with placeholder in .env.example:109-115. Developers copying .env.example will get validation errors without clear guidance. All other REQUIRED fields have uncommented values. Decision needed: Should we provide an example test key, clearer instructions, or document key generation?

- [x] [Review][Decision] S3_USE_SSL default contradicts local dev setup — Default is `true` in .env.example:52-53 but comment says "Set to false for local MinIO without TLS". Local development with docker-compose will fail immediately with documented defaults since MinIO container runs without TLS. Decision needed: Should default be `false` for dev, or should docker-compose be configured with TLS?

- [x] [Review][Decision] chunk_size could exceed max_file_size — No validation in settings.py:26 prevents `chunk_size > max_file_size`, which would break chunking logic. Decision needed: Should this raise validation error, or is this a valid edge case (single chunk upload)?

#### Patch Needed

- [x] [Review][Patch] Redis URL database path invalid [.env.example:33] — `redis://localhost:6379/doc_uploads` - Redis only accepts numeric database IDs 0-15, not string paths. This will fail at runtime. Fix: Change to `redis://localhost:6379/0` or another valid number 0-15.

- [x] [Review][Patch] S3 bucket name violates naming rules [.env.example:47] — `S3_BUCKET_NAME=rag-data/bronze` contains slash, violating S3 bucket naming (lowercase alphanumeric, hyphens only, 3-63 chars). Appears to confuse bucket name with object prefix. Fix: Change to `rag-data-bronze` or just `rag-data`.

- [x] [Review][Patch] allowed_mime_types can be empty list [settings.py:28] — No min_length validation. Empty allowlist would reject all uploads. Fix: Add `min_length=1` to Field definition.

- [x] [Review][Patch] redis_url missing scheme validation [settings.py:31] — No validation that URL uses redis:// or rediss:// scheme. Invalid URLs will fail at runtime with unclear errors. Fix: Add @field_validator to check scheme.

- [x] [Review][Patch] minio_endpoint allows empty string [settings.py:34] — No min_length check, empty string allowed. MinIO client init fails with empty endpoint. Fix: Add `min_length=1` to Field definition.

- [x] [Review][Patch] minio_root_user allows empty string [settings.py:35] — No min_length check. Auth to MinIO fails with empty username. Fix: Add `min_length=1` to Field definition.

- [x] [Review][Patch] minio_root_password allows empty SecretStr [settings.py:36] — No validation prevents empty password. Fix: Add @field_validator checking `len(v.get_secret_value()) > 0`.

- [x] [Review][Patch] s3_bucket_name missing S3 naming rules validation [settings.py:37] — No validation for S3 bucket naming rules (lowercase, no special chars, length 3-63). Invalid names fail at runtime. Fix: Add @field_validator for S3 naming compliance.

- [x] [Review][Patch] nats_url missing scheme validation [settings.py:42] — No validation that URL uses nats:// or tls:// scheme when set. Fix: Add @field_validator to check scheme.

- [x] [Review][Patch] nats_subject missing format validation [settings.py:43] — No validation for NATS subject rules (no spaces, valid hierarchy). Invalid subjects fail at publish. Fix: Add @field_validator for NATS subject format.

- [x] [Review][Patch] clamav_host allows empty string [settings.py:47] — No min_length check. ClamAV client fails with empty host. Fix: Add `min_length=1` to Field definition.

- [x] [Review][Patch] clamav_port missing bounds validation [settings.py:48] — Should be 1-65535. Out-of-range ports fail socket connection. Fix: Add `ge=1, le=65535` to Field definition.

- [x] [Review][Patch] clamav_timeout missing positive validation [settings.py:49] — Should be gt=0. Fix: Add `gt=0` to Field definition.

- [x] [Review][Patch] jwt_public_key missing PEM format validation [settings.py:52] — No validation of PEM format. Invalid keys fail at runtime with all auth requests rejected. Fix: Add @field_validator using cryptography.load_pem_public_key().

- [x] [Review][Patch] webhook_secret allows empty when webhook mode [settings.py:56] — validate_event_mode_requirements checks existence but not emptiness. Fix: Check `len(self.webhook_secret.get_secret_value()) > 0` in model validator.

- [x] [Review][Patch] webhook_timeout missing positive validation [settings.py:57] — Should be gt=0. Fix: Add `gt=0` to Field definition.

- [x] [Review][Patch] log_level missing enum validation [settings.py:60] — No validation for valid levels (DEBUG/INFO/WARNING/ERROR/CRITICAL). Invalid values fail logger init. Fix: Add @field_validator or use Literal type.

- [x] [Review][Patch] port missing bounds validation [settings.py:65] — Should be 1-65535. Invalid ports fail server bind. Fix: Add `ge=1, le=65535` to Field definition.

- [x] [Review][Patch] workers missing positive validation [settings.py:66] — Should be gt=0. Zero or negative workers cause process manager errors. Fix: Add `gt=0` to Field definition.

- [x] [Review][Patch] max_file_size missing upper bound [settings.py:26] — No upper limit could allow exabyte values causing OOM. Fix: Add reasonable upper bound like `le=10_737_418_240` (10 GB).

#### Deferred

- [x] [Review][Defer] No migration path for breaking changes — Existing deployments with old Redis URL, credentials, or concurrent upload limits will break. Deferred: Migration documentation is a separate concern from implementation correctness.

- [x] [Review][Defer] AC#3 incomplete compared to dev notes — Acceptance criteria list doesn't include all REQUIRED fields (missing S3_BUCKET_NAME, webhook fields). Deferred: Spec quality issue, not implementation issue. Implementation correctly follows dev notes.

- [x] [Review][Defer] .env parse error handling — Syntax errors in .env file produce cryptic errors. Deferred: Pydantic Settings handles this, additional wrapping is optional enhancement.

- [x] [Review][Defer] JWT algorithm mismatch validation — No validation that jwt_algorithm matches jwt_public_key type (RS256 with RSA). Deferred: JWT library will catch this, additional validation is nice-to-have.
