"""Tests for RollingMetrics — live degradation monitoring."""
import numpy as np
import pytest

from src.core.models import PortfolioSnapshot
from src.portfolio.rolling_metrics import RollingMetrics


def _make_snapshots(equities: list[float], start_ts: int = 0) -> list[PortfolioSnapshot]:
    """Create PortfolioSnapshot list from equity values."""
    return [
        PortfolioSnapshot(
            timestamp=start_ts + i * 3600_000,
            equity=eq,
            cash=eq,
            unrealized_pnl=0,
            realized_pnl=eq - equities[0],
            positions_count=0,
        )
        for i, eq in enumerate(equities)
    ]


def _make_trades(pnls: list[float], start_ts: int = 0) -> list[dict]:
    """Create closed trade dicts from PnL values."""
    return [
        {"pnl": pnl, "timestamp": start_ts + i * 86400_000}
        for i, pnl in enumerate(pnls)
    ]


class TestRollingMetrics:
    def test_empty_curve_returns_zeros(self):
        rm = RollingMetrics()
        result = rm.compute([], [])
        assert result["rolling_sharpe"] == 0.0
        assert result["rolling_expectancy"] == 0.0
        assert result["degradation_alert"] is False

    def test_single_snapshot_returns_zeros(self):
        rm = RollingMetrics()
        snaps = _make_snapshots([10000.0])
        result = rm.compute(snaps, [])
        assert result["rolling_sharpe"] == 0.0

    def test_uptrend_positive_sharpe(self):
        rm = RollingMetrics(window_bars=100, bars_per_year=8760)
        # Steady uptrend
        equities = [10000 + i * 5 for i in range(100)]
        snaps = _make_snapshots(equities)
        result = rm.compute(snaps, [])
        assert result["rolling_sharpe"] > 0

    def test_downtrend_negative_sharpe(self):
        rm = RollingMetrics(window_bars=100, bars_per_year=8760)
        equities = [10000 - i * 5 for i in range(100)]
        snaps = _make_snapshots(equities)
        result = rm.compute(snaps, [])
        assert result["rolling_sharpe"] < 0

    def test_expectancy_with_trades(self):
        rm = RollingMetrics(window_bars=500)
        snaps = _make_snapshots([10000] * 10)
        # 3 wins of $100, 2 losses of -$50
        trades = _make_trades([100, -50, 100, -50, 100])
        result = rm.compute(snaps, trades)
        # Win rate = 3/5 = 0.6
        assert abs(result["rolling_win_rate"] - 0.6) < 0.01
        # Expectancy = 0.6 * 100 - 0.4 * 50 = 60 - 20 = 40
        assert abs(result["rolling_expectancy"] - 40.0) < 0.01

    def test_profit_factor_with_trades(self):
        rm = RollingMetrics(window_bars=500)
        snaps = _make_snapshots([10000] * 10)
        trades = _make_trades([100, -50, 200, -30])
        result = rm.compute(snaps, trades)
        # Gross profit = 300, gross loss = 80
        assert abs(result["rolling_pf"] - 300 / 80) < 0.01

    def test_trade_frequency(self):
        rm = RollingMetrics(window_bars=500)
        # 10 snapshots × 1h = 10 hours
        snaps = _make_snapshots([10000] * 10, start_ts=0)
        # 5 trades in that window
        trades = _make_trades([10, -5, 10, -5, 10], start_ts=0)
        result = rm.compute(snaps, trades)
        # Duration = 9h = 9/168 weeks
        assert result["trade_frequency_7d"] > 0

    def test_degradation_alert_triggered(self):
        """Alert when Sharpe crosses below threshold."""
        rm = RollingMetrics(window_bars=50, sharpe_alert_threshold=0.0)

        # First call: positive Sharpe (uptrend)
        up_snaps = _make_snapshots([10000 + i * 10 for i in range(50)])
        rm.compute(up_snaps, [])
        # prev_sharpe is now positive

        # Second call: negative Sharpe (downtrend) → should alert
        down_snaps = _make_snapshots([10000 - i * 10 for i in range(50)])
        result = rm.compute(down_snaps, [])
        assert result["degradation_alert"] is True

    def test_no_alert_when_above_threshold(self):
        rm = RollingMetrics(window_bars=50, sharpe_alert_threshold=0.0)
        snaps = _make_snapshots([10000 + i * 10 for i in range(50)])
        result = rm.compute(snaps, [])
        assert result["degradation_alert"] is False

    def test_window_slicing(self):
        """Only uses last window_bars snapshots."""
        rm = RollingMetrics(window_bars=10, bars_per_year=8760)
        # 100 snapshots: first 90 down, last 10 up
        down = [10000 - i * 100 for i in range(90)]
        up = [down[-1] + i * 100 for i in range(10)]
        snaps = _make_snapshots(down + up)
        result = rm.compute(snaps, [])
        # Should reflect only the last 10 (uptrend) → positive Sharpe
        assert result["rolling_sharpe"] > 0
