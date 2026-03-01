from __future__ import annotations

import time
from typing import TYPE_CHECKING

from src.core.enums import OrderType, Side
from src.core.models import Fill, Order
from src.execution.broker import Broker
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.portfolio.tracker import PortfolioTracker

logger = get_logger("backtest_broker")


class BacktestBroker(Broker):
    """Simulates order execution for backtesting with commission and slippage."""

    def __init__(self, commission: float = 0.001, slippage: float = 0.0005):
        self.commission = commission
        self.slippage = slippage
        self._order_counter = 0

    def submit_order(self, order: Order, **kwargs) -> Fill | None:
        current_price = kwargs.get("current_price", order.price)
        timestamp = kwargs.get("timestamp", int(time.time() * 1000))

        if current_price is None or current_price <= 0:
            return None

        fill_price = current_price
        if order.side == Side.BUY:
            fill_price *= 1 + self.slippage
        else:
            fill_price *= 1 - self.slippage

        fee = order.quantity * fill_price * self.commission
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
