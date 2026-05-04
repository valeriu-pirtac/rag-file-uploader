"""Integration tests for configuration loading from environment."""

from pathlib import Path

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


class TestConfigurationLoading:
    """Test settings load from .env file and environment variables."""

    def test_load_from_env_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test settings load from .env file."""
        env_file = tmp_path / ".env"
        # Escape newlines in JWT key for .env file format
        jwt_key_escaped = TEST_JWT_PUBLIC_KEY.replace("\n", "\\n")
        env_file.write_text(
            f"""
MINIO_ENDPOINT=minio:9000
S3_BUCKET_NAME=test-bucket
CLAMAV_HOST=clamav
JWT_PUBLIC_KEY={jwt_key_escaped}
NATS_URL=nats://localhost:4222
MAX_CONCURRENT_UPLOADS=8
MAX_FILE_SIZE=838860800
REDIS_URL=redis://test:6379/1
"""
        )

        # Change to temp directory so .env is found
        monkeypatch.chdir(tmp_path)

        # Clear cache and reload settings
        get_settings.cache_clear()

        settings = AppSettings()

        assert settings.max_concurrent_uploads == 8
        assert settings.max_file_size == 838860800
        assert settings.redis_url == "redis://test:6379/1"
        assert settings.minio_endpoint == "minio:9000"
        assert settings.s3_bucket_name == "test-bucket"

    def test_environment_variables_override_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test environment variables override .env file values."""
        env_file = tmp_path / ".env"
        # Escape newlines in JWT key for .env file format
        jwt_key_escaped = TEST_JWT_PUBLIC_KEY.replace("\n", "\\n")
        env_file.write_text(
            f"""
MINIO_ENDPOINT=minio:9000
S3_BUCKET_NAME=test-bucket
CLAMAV_HOST=clamav
JWT_PUBLIC_KEY={jwt_key_escaped}
NATS_URL=nats://localhost:4222
MAX_CONCURRENT_UPLOADS=5
"""
        )

        # Set environment variable to override .env file
        monkeypatch.setenv("MAX_CONCURRENT_UPLOADS", "9")
        monkeypatch.chdir(tmp_path)

        get_settings.cache_clear()

        settings = AppSettings()

        assert settings.max_concurrent_uploads == 9  # Env var wins

    def test_case_insensitive_env_vars(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that environment variables are case-insensitive."""
        monkeypatch.setenv("minio_endpoint", "minio:9000")  # lowercase
        monkeypatch.setenv("s3_bucket_name", "test-bucket")
        monkeypatch.setenv("clamav_host", "clamav")
        monkeypatch.setenv("jwt_public_key", TEST_JWT_PUBLIC_KEY)
        monkeypatch.setenv("nats_url", "nats://localhost:4222")

        get_settings.cache_clear()

        settings = AppSettings()

        assert settings.minio_endpoint == "minio:9000"
        assert settings.s3_bucket_name == "test-bucket"

    def test_validation_errors_on_startup_missing_required(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that missing required settings raise clear validation errors."""
        # Clear all required env vars
        for key in ["MINIO_ENDPOINT", "S3_BUCKET_NAME", "CLAMAV_HOST", "JWT_PUBLIC_KEY"]:
            monkeypatch.delenv(key, raising=False)

        get_settings.cache_clear()

        with pytest.raises(ValidationError) as exc_info:
            AppSettings()

        error_msg = str(exc_info.value)
        # Should mention the missing required fields
        assert "minio_endpoint" in error_msg.lower() or "field required" in error_msg.lower()

    def test_extra_env_vars_ignored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that unknown environment variables are ignored."""
        monkeypatch.setenv("MINIO_ENDPOINT", "minio:9000")
        monkeypatch.setenv("S3_BUCKET_NAME", "test-bucket")
        monkeypatch.setenv("CLAMAV_HOST", "clamav")
        monkeypatch.setenv("JWT_PUBLIC_KEY", TEST_JWT_PUBLIC_KEY)
        monkeypatch.setenv("NATS_URL", "nats://localhost:4222")
        monkeypatch.setenv("UNKNOWN_VAR", "should-be-ignored")
        monkeypatch.setenv("ANOTHER_UNKNOWN", "also-ignored")

        get_settings.cache_clear()

        # Should not raise validation error
        settings = AppSettings()
        assert settings.minio_endpoint == "minio:9000"
