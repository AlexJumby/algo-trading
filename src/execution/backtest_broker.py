from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from src.core.enums import OrderType, Side
from src.core.models import Fill, Order
from src.execution.broker import Broker
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.portfolio.tracker import PortfolioTracker

logger = get_logger("backtest_broker")


class BacktestBroker(Broker):
    """Simulates order execution for backtesting.

    Supports two fee modes:
        1. **Legacy** (backward compat):  flat commission + flat slippage %
        2. **Realistic**: maker/taker fee split + dynamic slippage (base + impact)
    """

    def __init__(
        self,
        commission: float = 0.001,
        slippage: float = 0.0005,
        *,
        taker_fee: Optional[float] = None,
        maker_fee: Optional[float] = None,
        slippage_base: Optional[float] = None,
        slippage_impact: Optional[float] = None,
    ):
        # Legacy flat model
        self._legacy_commission = commission
        self._legacy_slippage = slippage

        # Realistic model (None → fallback to legacy)
        self._taker_fee = taker_fee
        self._maker_fee = maker_fee
        self._slippage_base = slippage_base
        self._slippage_impact = slippage_impact

        self._order_counter = 0

    # ── Helpers ─────────────────────────────────────────────

    def _compute_slippage_pct(self, notional: float) -> float:
        """Dynamic slippage: base + impact * (notional / $100k).

        Falls back to flat legacy slippage if realistic params not set.
        """
        if self._slippage_base is not None:
            base = self._slippage_base
            impact = self._slippage_impact or 0.0
            return base + impact * (notional / 100_000)
        return self._legacy_slippage

    def _compute_fee(self, notional: float, is_taker: bool = True) -> float:
        """Compute trading fee. Market orders are taker by default."""
        if self._taker_fee is not None:
            rate = self._taker_fee if is_taker else (self._maker_fee or 0.0)
            return notional * rate
        return notional * self._legacy_commission

    # ── Order execution ────────────────────────────────────

    def submit_order(self, order: Order, **kwargs) -> Fill | None:
        current_price = kwargs.get("current_price", order.price)
        timestamp = kwargs.get("timestamp", int(time.time() * 1000))

        if current_price is None or current_price <= 0:
            return None

        # Notional before slippage (for dynamic slippage calculation)
        raw_notional = order.quantity * current_price
        slip_pct = self._compute_slippage_pct(raw_notional)

        fill_price = current_price
        if order.side == Side.BUY:
            fill_price *= 1 + slip_pct
        else:
            fill_price *= 1 - slip_pct

        notional = order.quantity * fill_price
        fee = self._compute_fee(notional, is_taker=True)
        self._order_counter += 1

        fill = Fill(
            order_id=f"bt_{self._order_counter}",
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            fee=fee,
            timestamp=timestamp,
        )

        logger.debug(
            f"Fill: {order.side.value} {order.symbol} qty={order.quantity:.6f} "
            f"price={fill_price:.2f} fee={fee:.4f}"
        )
        return fill

    def check_stops(
        self,
        portfolio: PortfolioTracker,
        prices: dict[str, float],
        timestamp: int,
    ) -> list[Fill]:
        """Check if any open position's SL or TP has been hit. Returns fills."""
        fills = []

        for symbol, pos in list(portfolio.open_positions.items()):
            price = prices.get(symbol)
            if price is None:
                continue

            hit_sl = False
            hit_tp = False

            if pos.side == Side.BUY:
                if pos.stop_loss and price <= pos.stop_loss:
                    hit_sl = True
                if pos.take_profit and price >= pos.take_profit:
                    hit_tp = True
            else:  # SELL / SHORT
                if pos.stop_loss and price >= pos.stop_loss:
                    hit_sl = True
                if pos.take_profit and price <= pos.take_profit:
                    hit_tp = True

            if hit_sl or hit_tp:
                close_side = Side.SELL if pos.side == Side.BUY else Side.BUY
                exit_price = pos.stop_loss if hit_sl else pos.take_profit

                close_order = Order(
                    symbol=symbol,
                    side=close_side,
                    order_type=OrderType.MARKET,
                    quantity=pos.quantity,
                )
                fill = self.submit_order(
                    close_order,
                    current_price=exit_price,
                    timestamp=timestamp,
                )
                if fill:
                    fills.append(fill)
                    trigger = "SL" if hit_sl else "TP"
                    logger.info(
                        f"{trigger} hit for {symbol}: exit at {exit_price:.2f}"
                    )

        return fills

    def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        return []  # Backtest broker has no pending orders

    def cancel_all(self, symbol: str | None = None) -> int:
        return 0
