from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from src.portfolio.tracker import PortfolioTracker


class PerformanceMetrics:
    def __init__(self, tracker: PortfolioTracker, bars_per_year: float = 8760):
        self.tracker = tracker
        self._bars_per_year = bars_per_year

    def compute_all(self) -> dict:
        return {
            "total_return_pct": self.total_return(),
            "sharpe_ratio": self.sharpe_ratio(),
            "sortino_ratio": self.sortino_ratio(),
            "max_drawdown_pct": self.max_drawdown(),
            "win_rate": self.win_rate(),
            "profit_factor": self.profit_factor(),
            "total_trades": len(self.tracker.closed_trades),
            "total_pnl": self.total_pnl(),
            "avg_trade_pnl": self.avg_trade_pnl(),
            "best_trade": self.best_trade(),
            "worst_trade": self.worst_trade(),
            "avg_win": self.avg_win(),
            "avg_loss": self.avg_loss(),
        }

    def total_return(self) -> float:
        if not self.tracker.equity_curve:
            return 0.0
        final_eq = self.tracker.equity_curve[-1].equity
        return (final_eq - self.tracker.initial_capital) / self.tracker.initial_capital

    def total_pnl(self) -> float:
        return sum(t["pnl"] for t in self.tracker.closed_trades)

    def avg_trade_pnl(self) -> float:
        trades = self.tracker.closed_trades
        if not trades:
            return 0.0
        return self.total_pnl() / len(trades)

    def best_trade(self) -> float:
        trades = self.tracker.closed_trades
        if not trades:
            return 0.0
        return max(t["pnl"] for t in trades)

    def worst_trade(self) -> float:
        trades = self.tracker.closed_trades
        if not trades:
            return 0.0
        return min(t["pnl"] for t in trades)

    def win_rate(self) -> float:
        trades = self.tracker.closed_trades
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t["pnl"] > 0)
        return wins / len(trades)

    def avg_win(self) -> float:
        wins = [t["pnl"] for t in self.tracker.closed_trades if t["pnl"] > 0]
        return float(np.mean(wins)) if wins else 0.0

    def avg_loss(self) -> float:
        losses = [t["pnl"] for t in self.tracker.closed_trades if t["pnl"] <= 0]
        return float(np.mean(losses)) if losses else 0.0

    def profit_factor(self) -> float:
        gross_profit = sum(t["pnl"] for t in self.tracker.closed_trades if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in self.tracker.closed_trades if t["pnl"] < 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    def sharpe_ratio(self, risk_free_rate: float = 0.0, periods: int | None = None) -> float:
        """Annualized Sharpe ratio.

        Uses self._bars_per_year unless explicit `periods` is passed.
        """
        periods = periods if periods is not None else int(self._bars_per_year)
        returns = self._equity_returns()
        if len(returns) < 2:
            return 0.0
        excess = returns - risk_free_rate / periods
        std = float(np.std(excess, ddof=1))
        if std == 0:
            return 0.0
        return float(np.sqrt(periods) * np.mean(excess) / std)

    def sortino_ratio(self, risk_free_rate: float = 0.0, periods: int | None = None) -> float:
        """Annualized Sortino ratio.

        Uses self._bars_per_year unless explicit `periods` is passed.
        """
        periods = periods if periods is not None else int(self._bars_per_year)
        returns = self._equity_returns()
        if len(returns) < 2:
            return 0.0
        excess = returns - risk_free_rate / periods
        downside = returns[returns < 0]
        if len(downside) == 0:
            return float("inf") if float(np.mean(excess)) > 0 else 0.0
        downside_std = float(np.std(downside, ddof=1))
        if downside_std == 0:
            return 0.0
        return float(np.sqrt(periods) * np.mean(excess) / downside_std)

    def max_drawdown(self) -> float:
        equities = [s.equity for s in self.tracker.equity_curve]
        if not equities:
            return 0.0
        peak = equities[0]
        max_dd = 0.0
        for eq in equities:
            peak = max(peak, eq)
            if peak > 0:
                dd = (peak - eq) / peak
                max_dd = max(max_dd, dd)
        return max_dd

    def _equity_returns(self) -> np.ndarray:
        equities = [s.equity for s in self.tracker.equity_curve]
        if len(equities) < 2:
            return np.array([])
        equities_arr = np.array(equities)
        returns = np.diff(equities_arr) / equities_arr[:-1]
        return returns
