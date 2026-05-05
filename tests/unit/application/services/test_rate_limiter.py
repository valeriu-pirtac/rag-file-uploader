"""Unit tests for RedisRateLimiter service.

Tests verify rate limiting logic, workspace isolation, error handling,
and counter management with mocked Redis client.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import redis.exceptions

from src.application.services.rate_limiter import RedisRateLimiter
from src.domain.exceptions import InfrastructureError, RateLimitExceededError
from src.infrastructure.config.settings import AppSettings


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Create mocked Redis client."""
    mock = AsyncMock()
    # Default behavior: field doesn't exist (returns None)
    mock.hget.return_value = None
    mock.hincrby.return_value = 1
    mock.hset.return_value = True
    return mock


@pytest.fixture
def mock_settings() -> AppSettings:
    """Create mock settings with max_concurrent_uploads=10."""
    settings = MagicMock(spec=AppSettings)
    settings.max_concurrent_uploads = 10
    return settings


@pytest.fixture
def rate_limiter(mock_redis: AsyncMock, mock_settings: AppSettings) -> RedisRateLimiter:
    """Create RedisRateLimiter with mocked dependencies."""
    return RedisRateLimiter(mock_redis, mock_settings)


@pytest.fixture
def sample_workspace_id() -> UUID:
    """Create sample workspace UUID for testing."""
    return uuid4()


class TestRedisRateLimiterCheckAndIncrement:
    """Test suite for check_and_increment method."""

    @pytest.mark.asyncio
    async def test_first_call_increments_from_zero(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that first call increments from 0 to 1 when field doesn't exist."""
        # Arrange: HGET returns None (field doesn't exist), HINCRBY returns 1
        mock_redis.hget.return_value = None
        mock_redis.hincrby.return_value = 1

        # Act
        await rate_limiter.check_and_increment(sample_workspace_id)

        # Assert
        expected_key = f"ratelimit:workspace_{sample_workspace_id}"
        mock_redis.hget.assert_called_once_with(expected_key, "active_uploads")
        mock_redis.hincrby.assert_called_once_with(expected_key, "active_uploads", 1)

    @pytest.mark.asyncio
    async def test_subsequent_calls_increment_counter_sequentially(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that subsequent calls increment counter sequentially."""
        # Arrange: Simulate counter progression 1 -> 2 -> 3
        mock_redis.hget.side_effect = [b"1", b"2"]
        mock_redis.hincrby.side_effect = [2, 3]

        # Act
        await rate_limiter.check_and_increment(sample_workspace_id)  # 1 -> 2
        await rate_limiter.check_and_increment(sample_workspace_id)  # 2 -> 3

        # Assert
        assert mock_redis.hget.call_count == 2
        assert mock_redis.hincrby.call_count == 2

    @pytest.mark.asyncio
    async def test_call_at_limit_succeeds(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that call #10 succeeds (reaches limit but doesn't exceed)."""
        # Arrange: Counter at 9, will increment to 10 (at limit, not over)
        mock_redis.hget.return_value = b"9"
        mock_redis.hincrby.return_value = 10

        # Act - should NOT raise
        await rate_limiter.check_and_increment(sample_workspace_id)

        # Assert
        mock_redis.hincrby.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_over_limit_raises_error(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that call #11 raises RateLimitExceededError."""
        # Arrange: Counter already at 10 (limit reached)
        mock_redis.hget.return_value = b"10"

        # Act & Assert
        with pytest.raises(RateLimitExceededError) as exc_info:
            await rate_limiter.check_and_increment(sample_workspace_id)

        # Verify exception attributes
        assert exc_info.value.workspace_id == str(sample_workspace_id)
        assert exc_info.value.current_count == 10
        assert exc_info.value.limit == 10
        assert exc_info.value.retry_after_seconds == 60

        # Verify HINCRBY was NOT called (counter not incremented)
        mock_redis.hincrby.assert_not_called()

    @pytest.mark.asyncio
    async def test_redis_key_pattern_verified(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that Redis key follows pattern: ratelimit:workspace_{workspace_id} with field active_uploads."""
        # Arrange
        mock_redis.hget.return_value = None
        mock_redis.hincrby.return_value = 1

        # Act
        await rate_limiter.check_and_increment(sample_workspace_id)

        # Assert
        expected_key = f"ratelimit:workspace_{sample_workspace_id}"
        mock_redis.hget.assert_called_once_with(expected_key, "active_uploads")
        mock_redis.hincrby.assert_called_once_with(expected_key, "active_uploads", 1)

    @pytest.mark.asyncio
    async def test_redis_connection_error_raises_infrastructure_error(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that Redis connection error raises InfrastructureError."""
        # Arrange: Simulate Redis connection failure
        mock_redis.hget.side_effect = redis.exceptions.ConnectionError("Connection refused")

        # Act & Assert
        with pytest.raises(InfrastructureError) as exc_info:
            await rate_limiter.check_and_increment(sample_workspace_id)

        assert "Rate limiter unavailable" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_race_condition_documented_in_code(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test documents known HGET+HINCRBY race condition.

        RACE CONDITION SCENARIO:
        1. Request A: HGET counter=9 (below limit)
        2. Request B: HGET counter=9 (below limit)  <- Race window here
        3. Request A: HINCRBY counter=10 (allowed)
        4. Request B: HINCRBY counter=11 (exceeds limit by 1!)

        This is a known limitation. HINCRBY is atomic but check+increment is not.
        Impact: 1 extra upload beyond limit (acceptable for v1).
        Future: Use Lua script for true atomicity.
        """
        # Simulate race condition: both requests see counter=9
        mock_redis.hget.return_value = b"9"
        mock_redis.hincrby.side_effect = [10, 11]  # Second call exceeds limit

        # Both requests pass check (race condition)
        await rate_limiter.check_and_increment(sample_workspace_id)  # Counter: 9 -> 10
        await rate_limiter.check_and_increment(sample_workspace_id)  # Counter: 9 -> 11 (race!)

        # Assert: Both increments happened (demonstrates race condition)
        assert mock_redis.hincrby.call_count == 2

    @pytest.mark.asyncio
    async def test_counter_corruption_raises_infrastructure_error(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that corrupted counter data (non-numeric) raises InfrastructureError."""
        # Arrange: Redis returns garbage data (not a number)
        mock_redis.hget.return_value = b"not_a_number"

        # Act & Assert
        with pytest.raises(InfrastructureError) as exc_info:
            await rate_limiter.check_and_increment(sample_workspace_id)

        assert "Rate limiter counter corrupted" in str(exc_info.value)


class TestRedisRateLimiterDecrement:
    """Test suite for decrement method."""

    @pytest.mark.asyncio
    async def test_decrement_existing_counter(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that decrement reduces counter correctly."""
        # Arrange
        mock_redis.hincrby.return_value = 4  # Counter: 5 -> 4

        # Act
        await rate_limiter.decrement(sample_workspace_id)

        # Assert
        expected_key = f"ratelimit:workspace_{sample_workspace_id}"
        mock_redis.hincrby.assert_called_once_with(expected_key, "active_uploads", -1)

    @pytest.mark.asyncio
    async def test_decrement_handles_non_existent_key(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that HINCRBY -1 on non-existent field returns -1, resets to 0."""
        # Arrange: HINCRBY on non-existent field returns -1
        mock_redis.hincrby.return_value = -1

        # Act
        await rate_limiter.decrement(sample_workspace_id)

        # Assert: Counter reset to 0 (defensive programming)
        expected_key = f"ratelimit:workspace_{sample_workspace_id}"
        mock_redis.hincrby.assert_called_once_with(expected_key, "active_uploads", -1)
        mock_redis.hset.assert_called_once_with(expected_key, "active_uploads", "0")

    @pytest.mark.asyncio
    async def test_decrement_handles_negative_counter(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that negative counter is reset to 0 (defensive)."""
        # Arrange: Counter somehow became negative
        mock_redis.hincrby.return_value = -3

        # Act
        await rate_limiter.decrement(sample_workspace_id)

        # Assert: Counter reset to 0
        expected_key = f"ratelimit:workspace_{sample_workspace_id}"
        mock_redis.hset.assert_called_once_with(expected_key, "active_uploads", "0")

    @pytest.mark.asyncio
    async def test_decrement_redis_connection_error_raises_infrastructure_error(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that Redis connection error raises InfrastructureError."""
        # Arrange
        mock_redis.hincrby.side_effect = redis.exceptions.ConnectionError("Connection lost")

        # Act & Assert
        with pytest.raises(InfrastructureError) as exc_info:
            await rate_limiter.decrement(sample_workspace_id)

        assert "Rate limiter unavailable" in str(exc_info.value)


class TestRedisRateLimiterGetCurrentCount:
    """Test suite for get_current_count method."""

    @pytest.mark.asyncio
    async def test_get_current_count_returns_counter_value(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that get_current_count returns current counter value."""
        # Arrange
        mock_redis.hget.return_value = b"7"

        # Act
        count = await rate_limiter.get_current_count(sample_workspace_id)

        # Assert
        assert count == 7
        expected_key = f"ratelimit:workspace_{sample_workspace_id}"
        mock_redis.hget.assert_called_once_with(expected_key, "active_uploads")

    @pytest.mark.asyncio
    async def test_get_current_count_returns_zero_for_non_existent_key(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that get_current_count returns 0 for non-existent field."""
        # Arrange: Field doesn't exist
        mock_redis.hget.return_value = None

        # Act
        count = await rate_limiter.get_current_count(sample_workspace_id)

        # Assert
        assert count == 0

    @pytest.mark.asyncio
    async def test_get_current_count_redis_connection_error_raises_infrastructure_error(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that Redis connection error raises InfrastructureError."""
        # Arrange
        mock_redis.hget.side_effect = redis.exceptions.TimeoutError("Timeout")

        # Act & Assert
        with pytest.raises(InfrastructureError) as exc_info:
            await rate_limiter.get_current_count(sample_workspace_id)

        assert "Rate limiter unavailable" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_current_count_counter_corruption_raises_infrastructure_error(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that corrupted counter data (non-numeric) raises InfrastructureError."""
        # Arrange: Redis returns garbage data (not a number)
        mock_redis.hget.return_value = b"garbage_data"

        # Act & Assert
        with pytest.raises(InfrastructureError) as exc_info:
            await rate_limiter.get_current_count(sample_workspace_id)

        assert "Rate limiter counter corrupted" in str(exc_info.value)


class TestRedisRateLimiterReset:
    """Test suite for reset method."""

    @pytest.mark.asyncio
    async def test_reset_sets_counter_to_zero(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that reset sets counter to 0."""
        # Act
        await rate_limiter.reset(sample_workspace_id)

        # Assert
        expected_key = f"ratelimit:workspace_{sample_workspace_id}"
        mock_redis.hset.assert_called_once_with(expected_key, "active_uploads", "0")

    @pytest.mark.asyncio
    async def test_reset_redis_connection_error_raises_infrastructure_error(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
        sample_workspace_id: UUID,
    ) -> None:
        """Test that Redis connection error raises InfrastructureError."""
        # Arrange
        mock_redis.hset.side_effect = redis.exceptions.RedisError("Redis error")

        # Act & Assert
        with pytest.raises(InfrastructureError) as exc_info:
            await rate_limiter.reset(sample_workspace_id)

        assert "Rate limiter unavailable" in str(exc_info.value)


class TestRedisRateLimiterWorkspaceIsolation:
    """Test suite for workspace isolation."""

    @pytest.mark.asyncio
    async def test_different_workspaces_have_separate_counters(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
    ) -> None:
        """Test that two different workspace IDs have separate counters."""
        # Arrange
        workspace_a = uuid4()
        workspace_b = uuid4()
        mock_redis.hget.return_value = None
        mock_redis.hincrby.return_value = 1

        # Act
        await rate_limiter.check_and_increment(workspace_a)
        await rate_limiter.check_and_increment(workspace_b)

        # Assert: Different Redis hash keys generated
        expected_key_a = f"ratelimit:workspace_{workspace_a}"
        expected_key_b = f"ratelimit:workspace_{workspace_b}"

        # Verify both keys were used
        hget_calls = [call[0][0] for call in mock_redis.hget.call_args_list]
        assert expected_key_a in hget_calls
        assert expected_key_b in hget_calls
        assert expected_key_a != expected_key_b

    @pytest.mark.asyncio
    async def test_workspace_a_hitting_limit_does_not_affect_workspace_b(
        self,
        rate_limiter: RedisRateLimiter,
        mock_redis: AsyncMock,
    ) -> None:
        """Test that workspace A hitting limit doesn't affect workspace B."""
        # Arrange
        workspace_a = uuid4()
        workspace_b = uuid4()

        # Workspace A at limit (10)
        # Workspace B at 0
        def hget_side_effect(key: str, field: str) -> bytes | None:
            if str(workspace_a) in key:
                return b"10"  # At limit
            elif str(workspace_b) in key:
                return None  # Empty
            return None

        mock_redis.hget.side_effect = hget_side_effect
        mock_redis.hincrby.return_value = 1

        # Act & Assert: Workspace A rejects (at limit)
        with pytest.raises(RateLimitExceededError):
            await rate_limiter.check_and_increment(workspace_a)

        # Workspace B allows (independent counter)
        await rate_limiter.check_and_increment(workspace_b)

        # Verify workspace B's HINCRBY was called (allowed)
        expected_key_b = f"ratelimit:workspace_{workspace_b}"
        hincrby_calls = [call[0][0] for call in mock_redis.hincrby.call_args_list]
        assert expected_key_b in hincrby_calls
