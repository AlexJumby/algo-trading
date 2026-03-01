from __future__ import annotations

from src.core.models import Fill, Order
from src.exchange.base import ExchangeClient
from src.execution.broker import Broker
from src.utils.logger import get_logger

logger = get_logger("live_broker")


class LiveBroker(Broker):
    """Executes real orders on the exchange."""

    def __init__(self, exchange_client: ExchangeClient):
        self.client = exchange_client

    def submit_order(self, order: Order, **kwargs) -> Fill | None:
        try:
            fill = self.client.create_order(order)
            logger.info(
                f"Order filled: {order.side.value} {order.symbol} "
                f"qty={fill.quantity:.6f} price={fill.price:.2f}"
            )
            return fill
        except Exception as e:
            logger.error(f"Order failed: {e}")
            return None

    def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        return []  # TODO: implement via exchange client

    def cancel_all(self, symbol: str | None = None) -> int:
        return 0  # TODO: implement via exchange client
