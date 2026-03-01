from __future__ import annotations

import time

from src.core.enums import Side
from src.core.models import Fill, Order
from src.exchange.base import ExchangeClient
from src.execution.broker import Broker
from src.utils.logger import get_logger

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

    def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        return []

    def cancel_all(self, symbol: str | None = None) -> int:
        return 0
