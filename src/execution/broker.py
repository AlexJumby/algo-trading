from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.models import Fill, Order


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
