from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from src.core.config import ExchangeConfig
from src.core.models import Fill, Order, Position


class ExchangeClient(ABC):
    """Abstract exchange client interface."""

    @abstractmethod
    def connect(self, config: ExchangeConfig) -> None:
        ...

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int = 100,
    ) -> pd.DataFrame:
        ...

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> dict:
        ...

    @abstractmethod
    def fetch_balance(self) -> dict:
        ...

    @abstractmethod
    def create_order(self, order: Order) -> Fill:
        ...

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> None:
        ...

    @abstractmethod
    def fetch_positions(self, symbol: str | None = None) -> list[Position]:
        ...

    @abstractmethod
    def set_leverage(self, symbol: str, leverage: int) -> None:
        ...
