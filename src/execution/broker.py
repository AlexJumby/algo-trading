from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from src.core.enums import OrderType, Side
from src.core.models import Fill, Order
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.portfolio.tracker import PortfolioTracker

logger = get_logger("broker")


class Broker(ABC):
    """Abstract broker interface. Three implementations:
    LiveBroker, PaperBroker, BacktestBroker."""

    @abstractmethod
    def submit_order(self, order: Order, **kwargs) -> Fill | None:
        """Submit an order and return the fill, or None if rejected."""
        ...

    @abstractmethod
    def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        ...

    @abstractmethod
    def cancel_all(self, symbol: str | None = None) -> int:
        """Cancel all open orders. Return count cancelled."""
        ...

    def check_stops(
        self,
        portfolio: PortfolioTracker,
        prices: dict[str, float],
        timestamp: int,
    ) -> list[Fill]:
        """Check if any open position's SL or TP has been hit.

        Routes the close through submit_order so slippage and fees are applied.
        """
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
