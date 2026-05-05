"""Unit tests for Redis key builder - workspace-scoped key generation.

Tests workspace isolation guarantees (FR26, NFR-S5) and key pattern compliance.
"""

from uuid import UUID, uuid4

import pytest

from src.infrastructure.redis.key_builder import (
    dedup_key,
    rate_limit_field,
    rate_limit_key,
    session_key,
)


class TestSessionKey:
    """Tests for session_key() - upload session storage keys."""

    def test_generates_correct_pattern(self) -> None:
        """Test session_key follows pattern: session:workspace_{id}:document_{id}."""
        ws_id = UUID("12345678-1234-5678-1234-567812345678")
        doc_id = UUID("87654321-8765-4321-8765-432187654321")

        key = session_key(ws_id, doc_id)

        expected = f"session:workspace_{ws_id}:document_{doc_id}"
        assert key == expected
        assert key.startswith("session:workspace_")
        assert f":document_{doc_id}" in key

    def test_with_valid_uuids(self) -> None:
        """Test session_key with valid random UUIDs."""
        ws_id = uuid4()
        doc_id = uuid4()

        key = session_key(ws_id, doc_id)

        assert str(ws_id) in key
        assert str(doc_id) in key
        assert key.startswith("session:")

    def test_raises_error_on_none_workspace_id(self) -> None:
        """Test session_key raises ValueError when workspace_id is None."""
        doc_id = uuid4()

        with pytest.raises(
            ValueError, match="workspace_id cannot be None - required for isolation"
        ):
            session_key(None, doc_id)  # type: ignore

    def test_raises_error_on_none_document_id(self) -> None:
        """Test session_key raises ValueError when document_id is None."""
        ws_id = uuid4()

        with pytest.raises(ValueError, match="document_id cannot be None"):
            session_key(ws_id, None)  # type: ignore

    def test_raises_error_on_nil_workspace_id(self) -> None:
        """Test session_key raises ValueError when workspace_id is NIL UUID."""
        nil_uuid = UUID("00000000-0000-0000-0000-000000000000")
        doc_id = uuid4()

        with pytest.raises(ValueError, match="NIL UUID not allowed for workspace_id"):
            session_key(nil_uuid, doc_id)

    def test_raises_error_on_nil_document_id(self) -> None:
        """Test session_key raises ValueError when document_id is NIL UUID."""
        ws_id = uuid4()
        nil_uuid = UUID("00000000-0000-0000-0000-000000000000")

        with pytest.raises(ValueError, match="NIL UUID not allowed for document_id"):
            session_key(ws_id, nil_uuid)

    def test_raises_type_error_on_string_workspace_id(self) -> None:
        """Test session_key raises TypeError when workspace_id is a string."""
        doc_id = uuid4()

        with pytest.raises(TypeError, match="workspace_id must be UUID, got str"):
            session_key("12345678-1234-5678-1234-567812345678", doc_id)  # type: ignore

    def test_raises_type_error_on_string_document_id(self) -> None:
        """Test session_key raises TypeError when document_id is a string."""
        ws_id = uuid4()

        with pytest.raises(TypeError, match="document_id must be UUID, got str"):
            session_key(ws_id, "87654321-8765-4321-8765-432187654321")  # type: ignore

    def test_workspace_isolation_same_document_different_workspaces(self) -> None:
        """Test same document_id in different workspaces produces different keys."""
        ws_id_1 = uuid4()
        ws_id_2 = uuid4()
        doc_id = uuid4()

        key_1 = session_key(ws_id_1, doc_id)
        key_2 = session_key(ws_id_2, doc_id)

        assert key_1 != key_2
        assert str(ws_id_1) in key_1
        assert str(ws_id_2) in key_2
        assert str(doc_id) in key_1
        assert str(doc_id) in key_2

    def test_uses_snake_case_with_colon_separators(self) -> None:
        """Test session_key uses snake_case with colon separators (Implementation Pattern #2)."""
        ws_id = uuid4()
        doc_id = uuid4()

        key = session_key(ws_id, doc_id)

        # Verify pattern structure
        assert key.count(":") == 2  # Two colon separators
        assert "workspace_" in key  # snake_case prefix
        assert "document_" in key  # snake_case prefix
        # Ensure no kebab-case or camelCase
        assert "-workspace-" not in key
        assert "Workspace" not in key
        assert "Document" not in key

    def test_key_uniqueness(self) -> None:
        """Test each workspace+document combination produces unique key."""
        keys = set()
        for _ in range(10):
            ws_id = uuid4()
            doc_id = uuid4()
            key = session_key(ws_id, doc_id)
            assert key not in keys, "Duplicate key generated"
            keys.add(key)


class TestDedupKey:
    """Tests for dedup_key() - file deduplication scope keys."""

    def test_generates_correct_pattern(self) -> None:
        """Test dedup_key follows pattern: dedup:workspace_{id}."""
        ws_id = UUID("12345678-1234-5678-1234-567812345678")

        key = dedup_key(ws_id)

        expected = f"dedup:workspace_{ws_id}"
        assert key == expected
        assert key.startswith("dedup:workspace_")

    def test_with_valid_uuid(self) -> None:
        """Test dedup_key with valid random UUID."""
        ws_id = uuid4()

        key = dedup_key(ws_id)

        assert str(ws_id) in key
        assert key.startswith("dedup:")

    def test_raises_error_on_none_workspace_id(self) -> None:
        """Test dedup_key raises ValueError when workspace_id is None."""
        with pytest.raises(
            ValueError, match="workspace_id cannot be None - required for isolation"
        ):
            dedup_key(None)  # type: ignore

    def test_raises_error_on_nil_workspace_id(self) -> None:
        """Test dedup_key raises ValueError when workspace_id is NIL UUID."""
        nil_uuid = UUID("00000000-0000-0000-0000-000000000000")

        with pytest.raises(ValueError, match="NIL UUID not allowed for workspace_id"):
            dedup_key(nil_uuid)

    def test_raises_type_error_on_string_workspace_id(self) -> None:
        """Test dedup_key raises TypeError when workspace_id is a string."""
        with pytest.raises(TypeError, match="workspace_id must be UUID, got str"):
            dedup_key("12345678-1234-5678-1234-567812345678")  # type: ignore

    def test_workspace_isolation(self) -> None:
        """Test different workspaces produce different dedup keys."""
        ws_id_1 = uuid4()
        ws_id_2 = uuid4()

        key_1 = dedup_key(ws_id_1)
        key_2 = dedup_key(ws_id_2)

        assert key_1 != key_2
        assert str(ws_id_1) in key_1
        assert str(ws_id_2) in key_2

    def test_uses_snake_case_with_colon_separators(self) -> None:
        """Test dedup_key uses snake_case with colon separator."""
        ws_id = uuid4()

        key = dedup_key(ws_id)

        assert key.count(":") == 1  # One colon separator
        assert "workspace_" in key
        assert "-workspace-" not in key
        assert "Workspace" not in key

    def test_key_uniqueness(self) -> None:
        """Test each workspace produces unique dedup key."""
        keys = set()
        for _ in range(10):
            ws_id = uuid4()
            key = dedup_key(ws_id)
            assert key not in keys, "Duplicate key generated"
            keys.add(key)


class TestRateLimitKey:
    """Tests for rate_limit_key() - rate limit counter keys."""

    def test_generates_correct_pattern(self) -> None:
        """Test rate_limit_key follows pattern: ratelimit:workspace_{id} (hash key)."""
        ws_id = UUID("12345678-1234-5678-1234-567812345678")

        key = rate_limit_key(ws_id)

        expected = f"ratelimit:workspace_{ws_id}"
        assert key == expected
        assert key.startswith("ratelimit:workspace_")
        assert not key.endswith(":active_uploads")  # Field stored separately

    def test_with_valid_uuid(self) -> None:
        """Test rate_limit_key with valid random UUID."""
        ws_id = uuid4()

        key = rate_limit_key(ws_id)

        assert str(ws_id) in key
        assert key.startswith("ratelimit:")
        assert ":active_uploads" not in key  # Hash storage: field separate from key

    def test_raises_error_on_none_workspace_id(self) -> None:
        """Test rate_limit_key raises ValueError when workspace_id is None."""
        with pytest.raises(
            ValueError, match="workspace_id cannot be None - required for isolation"
        ):
            rate_limit_key(None)  # type: ignore

    def test_raises_error_on_nil_workspace_id(self) -> None:
        """Test rate_limit_key raises ValueError when workspace_id is NIL UUID."""
        nil_uuid = UUID("00000000-0000-0000-0000-000000000000")

        with pytest.raises(ValueError, match="NIL UUID not allowed for workspace_id"):
            rate_limit_key(nil_uuid)

    def test_raises_type_error_on_string_workspace_id(self) -> None:
        """Test rate_limit_key raises TypeError when workspace_id is a string."""
        with pytest.raises(TypeError, match="workspace_id must be UUID, got str"):
            rate_limit_key("12345678-1234-5678-1234-567812345678")  # type: ignore

    def test_workspace_isolation(self) -> None:
        """Test different workspaces produce different rate limit keys."""
        ws_id_1 = uuid4()
        ws_id_2 = uuid4()

        key_1 = rate_limit_key(ws_id_1)
        key_2 = rate_limit_key(ws_id_2)

        assert key_1 != key_2
        assert str(ws_id_1) in key_1
        assert str(ws_id_2) in key_2

    def test_uses_snake_case_with_colon_separators(self) -> None:
        """Test rate_limit_key uses snake_case with colon separator."""
        ws_id = uuid4()

        key = rate_limit_key(ws_id)

        assert key.count(":") == 1  # One colon separator (hash key pattern)
        assert "workspace_" in key
        # Hash storage: field name not in key (stored separately)
        assert "active_uploads" not in key
        # Ensure no kebab-case or camelCase
        assert "-workspace-" not in key
        assert "Workspace" not in key
        assert "activeUploads" not in key

    def test_key_uniqueness(self) -> None:
        """Test each workspace produces unique rate limit key."""
        keys = set()
        for _ in range(10):
            ws_id = uuid4()
            key = rate_limit_key(ws_id)
            assert key not in keys, "Duplicate key generated"
            keys.add(key)


class TestRateLimitField:
    """Tests for rate_limit_field() - returns hash field name for rate limiting."""

    def test_returns_active_uploads_field_name(self) -> None:
        """Test rate_limit_field returns 'active_uploads' field name."""
        field = rate_limit_field()
        assert field == "active_uploads"

    def test_returns_string(self) -> None:
        """Test rate_limit_field returns string type."""
        field = rate_limit_field()
        assert isinstance(field, str)

    def test_is_consistent(self) -> None:
        """Test rate_limit_field returns same value on multiple calls."""
        field1 = rate_limit_field()
        field2 = rate_limit_field()
        assert field1 == field2

    def test_uses_snake_case(self) -> None:
        """Test rate_limit_field uses snake_case naming convention."""
        field = rate_limit_field()
        assert "_" in field
        assert field.islower()
        assert "-" not in field  # No kebab-case


class TestPatternCompliance:
    """Cross-cutting tests for Redis key pattern compliance."""

    def test_all_keys_contain_workspace_scope(self) -> None:
        """Test all key functions include workspace_{id} for isolation guarantee."""
        ws_id = uuid4()
        doc_id = uuid4()

        session = session_key(ws_id, doc_id)
        dedup = dedup_key(ws_id)
        rate_limit = rate_limit_key(ws_id)

        for key in [session, dedup, rate_limit]:
            assert f"workspace_{ws_id}" in key, f"Key missing workspace scope: {key}"

    def test_no_uuid_truncation(self) -> None:
        """Test workspace_id appears in full in all keys (no truncation)."""
        ws_id = uuid4()
        doc_id = uuid4()
        full_ws_id = str(ws_id)

        keys = [
            session_key(ws_id, doc_id),
            dedup_key(ws_id),
            rate_limit_key(ws_id),
        ]

        for key in keys:
            assert full_ws_id in key, f"UUID truncated in key: {key} (expected {full_ws_id})"

    def test_uuid_format_lowercase_with_hyphens(self) -> None:
        """Test UUIDs are formatted as lowercase with hyphens (standard format)."""
        ws_id = UUID("ABCDEF01-2345-6789-ABCD-EF0123456789")
        doc_id = UUID("FEDCBA98-7654-3210-FEDC-BA9876543210")

        session = session_key(ws_id, doc_id)

        # UUID should be lowercase in key
        assert "abcdef01-2345-6789-abcd-ef0123456789" in session
        assert "fedcba98-7654-3210-fedc-ba9876543210" in session
        # Should NOT be uppercase
        assert "ABCDEF01" not in session
        assert "FEDCBA98" not in session
