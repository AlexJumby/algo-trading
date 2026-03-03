"""Rolling performance metrics for live degradation monitoring.

Computes Sharpe, expectancy, trade frequency, and win rate on a sliding
window of equity snapshots.  Fires a degradation alert when rolling
Sharpe drops below a configurable threshold.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from src.core.models import PortfolioSnapshot


class RollingMetrics:
    """Compute performance metrics on a sliding window of equity snapshots."""

    def __init__(
        self,
        window_bars: int = 720,
        bars_per_year: float = 8760,
        sharpe_alert_threshold: float = 0.0,
    ):
        """
        Args:
            window_bars: Lookback in bars (default 720 = 30 days at 1h).
            bars_per_year: Annualization factor.
            sharpe_alert_threshold: Alert if rolling Sharpe drops below this.
        """
        self.window_bars = window_bars
        self.bars_per_year = bars_per_year
        self.sharpe_alert_threshold = sharpe_alert_threshold
        self._prev_sharpe: Optional[float] = None

    def compute(
        self,
        equity_curve: list[PortfolioSnapshot],
        closed_trades: list[dict],
    ) -> dict:
        """Compute rolling metrics from recent equity snapshots and trades.

        Returns dict with keys:
            rolling_sharpe, rolling_sortino, rolling_expectancy,
            trade_frequency_7d, rolling_win_rate, rolling_pf,
            degradation_alert (bool).
        """
        result = {
            "rolling_sharpe": 0.0,
            "rolling_sortino": 0.0,
            "rolling_expectancy": 0.0,
            "trade_frequency_7d": 0.0,
            "rolling_win_rate": 0.0,
            "rolling_pf": 0.0,
            "degradation_alert": False,
        }

        if len(equity_curve) < 2:
            return result

        # Slice last window_bars snapshots
        window = equity_curve[-self.window_bars:]
        equities = np.array([s.equity for s in window])

        if len(equities) < 2:
            return result

        # Equity returns
        returns = np.diff(equities) / equities[:-1]

        # Rolling Sharpe
        std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
        if std > 0:
            result["rolling_sharpe"] = float(
                np.sqrt(self.bars_per_year) * np.mean(returns) / std
            )

        # Rolling Sortino
        downside = returns[returns < 0]
        down_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
        if down_std > 0:
            result["rolling_sortino"] = float(
                np.sqrt(self.bars_per_year) * np.mean(returns) / down_std
            )

        # Window time range for trade filtering
        window_start_ts = window[0].timestamp if window else 0
        window_end_ts = window[-1].timestamp if window else 0

        # Filter trades within window
        window_trades = [
            t for t in closed_trades
            if t.get("timestamp", 0) >= window_start_ts
        ]

        if window_trades:
            wins = [t["pnl"] for t in window_trades if t["pnl"] > 0]
            losses = [t["pnl"] for t in window_trades if t["pnl"] <= 0]
            total = len(window_trades)

            # Win rate
            result["rolling_win_rate"] = len(wins) / total if total > 0 else 0.0

            # Expectancy = P(win) * avg_win - P(loss) * |avg_loss|
            avg_win = float(np.mean(wins)) if wins else 0.0
            avg_loss = abs(float(np.mean(losses))) if losses else 0.0
            win_rate = result["rolling_win_rate"]
            result["rolling_expectancy"] = (
                win_rate * avg_win - (1 - win_rate) * avg_loss
            )

            # Profit factor
            gross_profit = sum(wins)
            gross_loss = abs(sum(t["pnl"] for t in window_trades if t["pnl"] < 0))
            if gross_loss > 0:
                result["rolling_pf"] = gross_profit / gross_loss
            elif gross_profit > 0:
                result["rolling_pf"] = float("inf")

            # Trade frequency: trades per 7 days
            if window_end_ts > window_start_ts:
                duration_days = (window_end_ts - window_start_ts) / (1000 * 86400)
                weeks = duration_days / 7.0
                if weeks > 0:
                    result["trade_frequency_7d"] = total / weeks

        # Degradation alert: Sharpe just crossed below threshold
        current_sharpe = result["rolling_sharpe"]
        if (
            self._prev_sharpe is not None
            and self._prev_sharpe >= self.sharpe_alert_threshold
            and current_sharpe < self.sharpe_alert_threshold
        ):
            result["degradation_alert"] = True

        self._prev_sharpe = current_sharpe
        return result
