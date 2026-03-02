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

        vol_scalar (from strategy metadata) can scale the position UP or DOWN
        based on volatility targeting.  A hard cap (max_leverage_exposure)
        prevents unreasonably large positions.
        """
        margin = equity * self.config.max_position_size_pct
        if price <= 0:
            return 0.0
        notional = margin * max(leverage, 1)
        quantity = notional / price

        # Scale by signal strength (always 1.0 for TSMOM now)
        quantity *= signal.strength

        # Apply vol_scalar from strategy metadata (two-way: can be > 1.0)
        vol_scalar = 1.0
        if signal.metadata:
            vol_scalar = signal.metadata.get("vol_scalar", 1.0)
        quantity *= vol_scalar

        # Hard cap: max notional / equity ratio
        max_lev = getattr(self.config, "max_leverage_exposure", 0)
        if max_lev > 0 and equity > 0:
            max_notional = equity * max_lev
            max_qty = max_notional / price
            quantity = min(quantity, max_qty)

        return quantity
