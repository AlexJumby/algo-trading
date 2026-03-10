"""Tests for retry_on_transient decorator (Fix #5)."""
import time
from unittest.mock import MagicMock, patch

import ccxt
import pytest

from src.core.exceptions import ExchangeError
from src.exchange.bybit_client import BybitClient, retry_on_transient


# ---------------------------------------------------------------------------
# Direct decorator tests (fast, no real exchange)
# ---------------------------------------------------------------------------

class TestRetryDecorator:
    def test_succeeds_first_try(self):
        call_count = 0

        @retry_on_transient(max_attempts=3, base_delay=0.01)
        def fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert fn() == "ok"
        assert call_count == 1

    def test_retries_on_network_error(self):
        call_count = 0

        @retry_on_transient(max_attempts=3, base_delay=0.01)
        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ccxt.NetworkError("connection reset")
            return "recovered"

        assert fn() == "recovered"
        assert call_count == 3

    def test_retries_on_rate_limit(self):
        call_count = 0

        @retry_on_transient(max_attempts=3, base_delay=0.01)
        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ccxt.RateLimitExceeded("429")
            return "ok"

        assert fn() == "ok"
        assert call_count == 2

    def test_no_retry_on_bad_request(self):
        """Non-transient errors should NOT be retried."""
        call_count = 0

        @retry_on_transient(max_attempts=3, base_delay=0.01)
        def fn():
            nonlocal call_count
            call_count += 1
            raise ccxt.BadRequest("invalid symbol")

        with pytest.raises(ccxt.BadRequest):
            fn()
        assert call_count == 1  # No retry

    def test_no_retry_on_auth_error(self):
        call_count = 0

        @retry_on_transient(max_attempts=3, base_delay=0.01)
        def fn():
            nonlocal call_count
            call_count += 1
            raise ccxt.AuthenticationError("invalid key")

        with pytest.raises(ccxt.AuthenticationError):
            fn()
        assert call_count == 1

    def test_raises_after_max_attempts(self):
        call_count = 0

        @retry_on_transient(max_attempts=3, base_delay=0.01)
        def fn():
            nonlocal call_count
            call_count += 1
            raise ccxt.NetworkError("permanent failure")

        with pytest.raises(ExchangeError, match="failed after 3 attempts"):
            fn()
        assert call_count == 3

    def test_exponential_timing(self):
        """Verify delays grow exponentially (base_delay * 2^(attempt-1))."""
        call_count = 0

        @retry_on_transient(max_attempts=3, base_delay=0.05)
        def fn():
            nonlocal call_count
            call_count += 1
            raise ccxt.RequestTimeout("timeout")

        t0 = time.time()
        with pytest.raises(ExchangeError):
            fn()
        elapsed = time.time() - t0
        # Expected: 0.05 + 0.10 = 0.15s minimum
        assert elapsed >= 0.12  # allow small timing variance
        assert call_count == 3


# ---------------------------------------------------------------------------
# BybitClient integration: verify decorator is NOT on create_order
# ---------------------------------------------------------------------------

class TestRetryNotOnOrders:
    def test_create_order_does_not_retry(self):
        """create_order must NOT have retry — risk of double execution."""
        client = BybitClient()
        mock_exchange = MagicMock()
        mock_exchange.create_order.side_effect = ccxt.NetworkError("connection lost")
        client._exchange = mock_exchange

        order = MagicMock()
        order.symbol = "BTCUSDT"
        order.order_type = MagicMock(value="market")
        order.side = MagicMock(value="buy")
        order.quantity = 0.01
        order.price = None
        order.stop_loss = None
        order.take_profit = None
        order.params = {}

        with pytest.raises(ExchangeError):
            client.create_order(order)
        # Should have been called exactly once (no retry)
        assert mock_exchange.create_order.call_count == 1

    def test_cancel_order_does_not_retry(self):
        """cancel_order must NOT have retry."""
        client = BybitClient()
        mock_exchange = MagicMock()
        mock_exchange.cancel_order.side_effect = ccxt.NetworkError("timeout")
        client._exchange = mock_exchange

        with pytest.raises(ExchangeError):
            client.cancel_order("order-123", "BTCUSDT")
        assert mock_exchange.cancel_order.call_count == 1
