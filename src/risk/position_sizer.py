from __future__ import annotations

from src.core.config import RiskConfig
from src.core.models import Signal


class PositionSizer:
    def __init__(self, config: RiskConfig):
        self.config = config

    def compute_size(
        self, equity: float, price: float, signal: Signal, leverage: int = 1,
    ) -> float:
        method = self.config.position_sizing_method
        if method == "fixed_fraction":
            return self._fixed_fraction(equity, price, signal, leverage)
        return self._fixed_fraction(equity, price, signal, leverage)

    def _fixed_fraction(
        self, equity: float, price: float, signal: Signal, leverage: int = 1,
    ) -> float:
        """Risk a fixed percentage of equity per trade.

        With leverage, the margin (equity * pct) controls a larger notional position:
            notional = margin * leverage
            quantity = notional / price
        """
        margin = equity * self.config.max_position_size_pct
        if price <= 0:
            return 0.0
        notional = margin * max(leverage, 1)
        quantity = notional / price
        # Scale by signal strength
        quantity *= signal.strength
        return quantity
