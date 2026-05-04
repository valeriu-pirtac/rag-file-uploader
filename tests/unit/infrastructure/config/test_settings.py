"""Unit tests for AppSettings configuration management."""

import pytest
from pydantic import ValidationError

from src.infrastructure.config.settings import AppSettings, get_settings


# Test RSA public key for JWT validation
TEST_JWT_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqc7D4YqrpKAQyZ8T/O/h
AEr7u9btVsE5EJKf7Q2N2qu8gsjTCWXXxK36xETMuR2arSCsry/j71syUXVblHXb
ByiipaKzzpBv/AcWip2kMucmQ/4AoMGdmBav7MKVNhuMf7rIg1udhpc1HdUKiMHd
vWXXuGqyltQ5XTcUgjZWqfQF58GKvq9SIcIQpcLk24ZaN9RaQXsut6PQALQBXfFS
cqE2zJ4JX9zhCAo2zMGouj5QGvAstEPsi9fs0mm/pjACihRA1KPn75hB8exOonBd
AFLuPKEGvpNPzmUGmPoNVyJSC3vxl1L0PjUDuLjJpV+hyRpfwKShLcS94KspanuN
CwIDAQAB
-----END PUBLIC KEY-----"""


class TestSettingsDefaults:
    """Test settings load with default values."""

    def test_settings_with_defaults(self) -> None:
        """Test settings load with default values when required fields provided."""
        settings = AppSettings(
            minio_endpoint="minio:9000",
            s3_bucket_name="test-bucket",
            clamav_host="clamav",
            jwt_public_key=TEST_JWT_PUBLIC_KEY,
            nats_url="nats://localhost:4222",  # Required for default nats mode
        )
        assert settings.max_file_size == 524_288_000
        assert settings.max_concurrent_uploads == 10
        assert settings.chunk_size == 26_214_400
        assert settings.session_ttl_hours == 24
        assert settings.redis_url == "redis://localhost:6379/0"
        assert settings.allowed_mime_types == ["application/pdf"]
        assert settings.event_publish_mode == "nats"
        assert settings.log_level == "INFO"
        assert settings.host == "0.0.0.0"
        assert settings.port == 8000


class TestRequiredFields:
    """Test validation of required configuration fields."""

    def test_minio_endpoint_required(self) -> None:
        """Test that minio_endpoint is required."""
        with pytest.raises(ValidationError) as exc_info:
            AppSettings(
                s3_bucket_name="test-bucket",
                clamav_host="clamav",
                jwt_public_key=TEST_JWT_PUBLIC_KEY,
            )
        errors = exc_info.value.errors()
        field_names = [error["loc"][0] for error in errors]
        assert "minio_endpoint" in field_names

    def test_s3_bucket_name_required(self) -> None:
        """Test that s3_bucket_name is required."""
        with pytest.raises(ValidationError) as exc_info:
            AppSettings(
                minio_endpoint="minio:9000",
                clamav_host="clamav",
                jwt_public_key=TEST_JWT_PUBLIC_KEY,
            )
        errors = exc_info.value.errors()
        field_names = [error["loc"][0] for error in errors]
        assert "s3_bucket_name" in field_names

    def test_clamav_host_required(self) -> None:
        """Test that clamav_host is required."""
        with pytest.raises(ValidationError) as exc_info:
            AppSettings(
                minio_endpoint="minio:9000",
                s3_bucket_name="test-bucket",
                jwt_public_key=TEST_JWT_PUBLIC_KEY,
            )
        errors = exc_info.value.errors()
        field_names = [error["loc"][0] for error in errors]
        assert "clamav_host" in field_names

    def test_jwt_public_key_required(self) -> None:
        """Test that jwt_public_key is required."""
        with pytest.raises(ValidationError) as exc_info:
            AppSettings(
                minio_endpoint="minio:9000",
                s3_bucket_name="test-bucket",
                clamav_host="clamav",
            )
        errors = exc_info.value.errors()
        field_names = [error["loc"][0] for error in errors]
        assert "jwt_public_key" in field_names


class TestFieldValidation:
    """Test field-level validation rules."""

    def test_max_file_size_must_be_positive(self) -> None:
        """Test that max_file_size must be greater than 0."""
        with pytest.raises(ValidationError) as exc_info:
            AppSettings(
                max_file_size=-1,
                minio_endpoint="minio:9000",
                s3_bucket_name="test",
                clamav_host="clamav",
                jwt_public_key=TEST_JWT_PUBLIC_KEY,
            )
        errors = exc_info.value.errors()
        assert any(
            error["loc"][0] == "max_file_size" and "greater than 0" in str(error["msg"])
            for error in errors
        )

    def test_max_concurrent_uploads_must_be_positive(self) -> None:
        """Test that max_concurrent_uploads must be greater than 0."""
        with pytest.raises(ValidationError) as exc_info:
            AppSettings(
                max_concurrent_uploads=0,
                minio_endpoint="minio:9000",
                s3_bucket_name="test",
                clamav_host="clamav",
                jwt_public_key=TEST_JWT_PUBLIC_KEY,
            )
        errors = exc_info.value.errors()
        assert any(error["loc"][0] == "max_concurrent_uploads" for error in errors)

    def test_max_concurrent_uploads_must_not_exceed_10(self) -> None:
        """Test that max_concurrent_uploads must not exceed 10."""
        with pytest.raises(ValidationError) as exc_info:
            AppSettings(
                max_concurrent_uploads=11,
                minio_endpoint="minio:9000",
                s3_bucket_name="test",
                clamav_host="clamav",
                jwt_public_key=TEST_JWT_PUBLIC_KEY,
                nats_url="nats://localhost:4222",
            )
        errors = exc_info.value.errors()
        assert any(
            error["loc"][0] == "max_concurrent_uploads"
            and "less than or equal to 10" in str(error["msg"])
            for error in errors
        )

    def test_chunk_size_must_be_positive(self) -> None:
        """Test that chunk_size must be greater than 0."""
        with pytest.raises(ValidationError) as exc_info:
            AppSettings(
                chunk_size=-100,
                minio_endpoint="minio:9000",
                s3_bucket_name="test",
                clamav_host="clamav",
                jwt_public_key=TEST_JWT_PUBLIC_KEY,
            )
        errors = exc_info.value.errors()
        assert any(
            error["loc"][0] == "chunk_size" and "greater than 0" in str(error["msg"])
            for error in errors
        )

    def test_session_ttl_hours_must_be_positive(self) -> None:
        """Test that session_ttl_hours must be greater than 0."""
        with pytest.raises(ValidationError) as exc_info:
            AppSettings(
                session_ttl_hours=0,
                minio_endpoint="minio:9000",
                s3_bucket_name="test",
                clamav_host="clamav",
                jwt_public_key=TEST_JWT_PUBLIC_KEY,
            )
        errors = exc_info.value.errors()
        assert any(error["loc"][0] == "session_ttl_hours" for error in errors)


class TestNATSValidation:
    """Test conditional validation for NATS event mode."""

    def test_nats_url_required_when_nats_mode(self) -> None:
        """Test that NATS_URL is required when event_publish_mode is 'nats'."""
        with pytest.raises(ValidationError) as exc_info:
            AppSettings(
                event_publish_mode="nats",
                nats_url=None,
                minio_endpoint="minio:9000",
                s3_bucket_name="test",
                clamav_host="clamav",
                jwt_public_key=TEST_JWT_PUBLIC_KEY,
            )
        assert "NATS_URL is required" in str(exc_info.value)

    def test_nats_url_optional_when_webhook_mode(self) -> None:
        """Test that NATS_URL is not required when event_publish_mode is 'webhook'."""
        settings = AppSettings(
            event_publish_mode="webhook",
            webhook_url="https://example.com/webhook",
            webhook_secret="my-secret-value-here",
            nats_url=None,
            minio_endpoint="minio:9000",
            s3_bucket_name="test",
            clamav_host="clamav",
            jwt_public_key=TEST_JWT_PUBLIC_KEY,
        )
        assert settings.event_publish_mode == "webhook"
        assert settings.nats_url is None


class TestWebhookValidation:
    """Test conditional validation for webhook event mode."""

    def test_webhook_url_required_when_webhook_mode(self) -> None:
        """Test that webhook_url is required when event_publish_mode is 'webhook'."""
        with pytest.raises(ValidationError) as exc_info:
            AppSettings(
                event_publish_mode="webhook",
                webhook_url=None,
                webhook_secret="secret",
                minio_endpoint="minio:9000",
                s3_bucket_name="test",
                clamav_host="clamav",
                jwt_public_key=TEST_JWT_PUBLIC_KEY,
            )
        assert "WEBHOOK_URL is required" in str(exc_info.value)

    def test_webhook_secret_required_when_webhook_mode(self) -> None:
        """Test that webhook_secret is required when event_publish_mode is 'webhook'."""
        with pytest.raises(ValidationError) as exc_info:
            AppSettings(
                event_publish_mode="webhook",
                webhook_url="https://example.com/webhook",
                webhook_secret=None,
                minio_endpoint="minio:9000",
                s3_bucket_name="test",
                clamav_host="clamav",
                jwt_public_key=TEST_JWT_PUBLIC_KEY,
            )
        assert "WEBHOOK_SECRET is required" in str(exc_info.value)

    def test_webhook_url_enforces_https(self) -> None:
        """Test webhook URL validation requires HTTPS (except localhost)."""
        with pytest.raises(ValidationError) as exc_info:
            AppSettings(
                event_publish_mode="webhook",
                webhook_url="http://example.com/webhook",
                webhook_secret="secret",
                minio_endpoint="minio:9000",
                s3_bucket_name="test",
                clamav_host="clamav",
                jwt_public_key=TEST_JWT_PUBLIC_KEY,
            )
        assert "must use HTTPS" in str(exc_info.value)

    def test_webhook_url_allows_localhost_http(self) -> None:
        """Test webhook URL allows http://localhost for development."""
        settings = AppSettings(
            event_publish_mode="webhook",
            webhook_url="http://localhost:8080/webhook",
            webhook_secret="secret",
            minio_endpoint="minio:9000",
            s3_bucket_name="test",
            clamav_host="clamav",
            jwt_public_key=TEST_JWT_PUBLIC_KEY,
        )
        assert settings.webhook_url == "http://localhost:8080/webhook"

    def test_webhook_url_allows_127_http(self) -> None:
        """Test webhook URL allows http://127.0.0.1 for development."""
        settings = AppSettings(
            event_publish_mode="webhook",
            webhook_url="http://127.0.0.1:8080/webhook",
            webhook_secret="secret",
            minio_endpoint="minio:9000",
            s3_bucket_name="test",
            clamav_host="clamav",
            jwt_public_key=TEST_JWT_PUBLIC_KEY,
        )
        assert settings.webhook_url == "http://127.0.0.1:8080/webhook"


class TestSecretProtection:
    """Test that SecretStr fields protect sensitive data."""

    def test_secret_str_not_exposed_in_str(self) -> None:
        """Test that SecretStr fields don't expose values in str()."""
        settings = AppSettings(
            minio_root_password="secret123",
            webhook_secret="webhook-secret-value",
            minio_endpoint="minio:9000",
            s3_bucket_name="test",
            clamav_host="clamav",
            jwt_public_key=TEST_JWT_PUBLIC_KEY,
            event_publish_mode="webhook",
            webhook_url="https://example.com/hook",
        )
        settings_str = str(settings)
        assert "secret123" not in settings_str
        assert "webhook-secret-value" not in settings_str

    def test_secret_str_not_exposed_in_repr(self) -> None:
        """Test that SecretStr fields don't expose values in repr()."""
        settings = AppSettings(
            minio_root_password="secret123",
            webhook_secret="webhook-secret-value",
            minio_endpoint="minio:9000",
            s3_bucket_name="test",
            clamav_host="clamav",
            jwt_public_key=TEST_JWT_PUBLIC_KEY,
            event_publish_mode="webhook",
            webhook_url="https://example.com/hook",
        )
        settings_repr = repr(settings)
        assert "secret123" not in settings_repr
        assert "webhook-secret-value" not in settings_repr

    def test_secret_str_accessible_via_get_secret_value(self) -> None:
        """Test that SecretStr values are accessible via get_secret_value()."""
        settings = AppSettings(
            minio_root_password="secret123",
            webhook_secret="webhook-secret-value",
            minio_endpoint="minio:9000",
            s3_bucket_name="test",
            clamav_host="clamav",
            jwt_public_key=TEST_JWT_PUBLIC_KEY,
            event_publish_mode="webhook",
            webhook_url="https://example.com/hook",
        )
        assert settings.minio_root_password.get_secret_value() == "secret123"
        assert settings.webhook_secret.get_secret_value() == "webhook-secret-value"


class TestSingletonPattern:
    """Test that get_settings returns singleton instance."""

    def test_get_settings_returns_same_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test get_settings returns the same instance on multiple calls."""
        # Set required environment variables
        monkeypatch.setenv("MINIO_ENDPOINT", "minio:9000")
        monkeypatch.setenv("S3_BUCKET_NAME", "test-bucket")
        monkeypatch.setenv("CLAMAV_HOST", "clamav")
        monkeypatch.setenv("JWT_PUBLIC_KEY", TEST_JWT_PUBLIC_KEY)
        monkeypatch.setenv("NATS_URL", "nats://localhost:4222")

        # Clear cache to ensure clean test
        get_settings.cache_clear()

        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2

    def test_singleton_persists_across_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test singleton pattern maintains same object identity."""
        # Set required environment variables
        monkeypatch.setenv("MINIO_ENDPOINT", "minio:9000")
        monkeypatch.setenv("S3_BUCKET_NAME", "test-bucket")
        monkeypatch.setenv("CLAMAV_HOST", "clamav")
        monkeypatch.setenv("JWT_PUBLIC_KEY", TEST_JWT_PUBLIC_KEY)
        monkeypatch.setenv("NATS_URL", "nats://localhost:4222")

        get_settings.cache_clear()

        first_call = get_settings()
        second_call = get_settings()
        third_call = get_settings()

        assert first_call is second_call is third_call
