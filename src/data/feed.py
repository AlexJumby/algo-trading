from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class DataFeed(ABC):
    """Provides OHLCV bar data. Abstracted so backtest and live share the same interface."""

    @abstractmethod
    def get_latest_bars(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        """Return the most recent `count` bars as a DataFrame with columns:
        [timestamp, open, high, low, close, volume]."""
        ...

    @abstractmethod
    def get_current_price(self, symbol: str) -> float:
        ...


class HistoricalDataFeed(DataFeed):
    """Feeds historical data bar-by-bar for backtesting."""

    def __init__(self, df: pd.DataFrame):
        self._full_data = df.reset_index(drop=True)
        self._current_index = 0

    def advance(self) -> None:
        self._current_index += 1

    def get_latest_bars(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        end = self._current_index + 1
        start = max(0, end - count)
        return self._full_data.iloc[start:end].copy()

    def get_current_price(self, symbol: str) -> float:
        return float(self._full_data.iloc[self._current_index]["close"])

    @property
    def current_timestamp(self) -> int:
        return int(self._full_data.iloc[self._current_index]["timestamp"])

    @property
    def is_exhausted(self) -> bool:
        return self._current_index >= len(self._full_data) - 1

    def __len__(self) -> int:
        return len(self._full_data)


class CcxtDataFeed(DataFeed):
    """Live data feed using ccxt exchange client."""

    def __init__(self, exchange_client):
        self.client = exchange_client

    def get_latest_bars(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        return self.client.fetch_ohlcv(symbol, timeframe, limit=count)

    def get_current_price(self, symbol: str) -> float:
        ticker = self.client.fetch_ticker(symbol)
        return float(ticker["last"])
