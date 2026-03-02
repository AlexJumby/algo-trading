from __future__ import annotations

import time
from typing import TYPE_CHECKING

from src.core.enums import Side
from src.core.models import Fill, Order
from src.exchange.base import ExchangeClient
from src.execution.broker import Broker
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.portfolio.tracker import PortfolioTracker

logger = get_logger("paper_broker")


class PaperBroker(Broker):
    """Simulates order fills using live market data but without placing real orders."""

    def __init__(self, exchange_client: ExchangeClient, slippage: float = 0.0005):
        self.client = exchange_client
        self.slippage = slippage
        self._order_counter = 0

    def submit_order(self, order: Order, **kwargs) -> Fill | None:
        try:
            ticker = self.client.fetch_ticker(order.symbol)
            current_price = float(ticker["last"])
        except Exception as e:
            logger.error(f"Failed to fetch price for paper order: {e}")
            return None

        fill_price = current_price
        if order.side == Side.BUY:
            fill_price *= 1 + self.slippage
        else:
            fill_price *= 1 - self.slippage

        fee = order.quantity * fill_price * 0.001  # Simulated 0.1% fee
        self._order_counter += 1

        fill = Fill(
            order_id=f"paper_{self._order_counter}",
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            fee=fee,
            timestamp=int(time.time() * 1000),
        )

        logger.info(
            f"[PAPER] {order.side.value} {order.symbol} "
            f"qty={order.quantity:.6f} price={fill_price:.2f}"
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
            else:
                if pos.stop_loss and price >= pos.stop_loss:
                    hit_sl = True
                if pos.take_profit and price <= pos.take_profit:
                    hit_tp = True

            if hit_sl or hit_tp:
                close_side = Side.SELL if pos.side == Side.BUY else Side.BUY
                exit_price = pos.stop_loss if hit_sl else pos.take_profit

                self._order_counter += 1
                fee = pos.quantity * exit_price * 0.001
                fill = Fill(
                    order_id=f"paper_stop_{self._order_counter}",
                    symbol=symbol,
                    side=close_side,
                    quantity=pos.quantity,
                    price=exit_price,
                    fee=fee,
                    timestamp=timestamp,
                )
                fills.append(fill)
                trigger = "SL" if hit_sl else "TP"
                logger.info(
                    f"[PAPER] {trigger} hit for {symbol}: exit at {exit_price:.2f}"
                )

        return fills

    def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        return []

    def cancel_all(self, symbol: str | None = None) -> int:
        return 0
