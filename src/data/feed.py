from __future__ import annotations

import time
from abc import ABC, abstractmethod

import pandas as pd

from src.core.config import TIMEFRAME_MS
from src.utils.logger import get_logger

logger = get_logger("feed")


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

    @property
    def full_data(self) -> pd.DataFrame:
        """Public read-only access to the full dataset."""
        return self._full_data

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
    """Live data feed using ccxt exchange client.

    Handles pagination automatically: if more bars are requested than
    the exchange returns per call (e.g. Bybit max 1000), fetches in
    multiple batches and concatenates.
    """

    # Bybit returns max 1000 candles per request
    MAX_PER_REQUEST = 1000

    TF_MS = TIMEFRAME_MS

    def __init__(self, exchange_client):
        self.client = exchange_client

    def get_latest_bars(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        if count <= self.MAX_PER_REQUEST:
            return self.client.fetch_ohlcv(symbol, timeframe, limit=count)

        # Paginated fetch: work backwards from now
        tf_ms = self.TF_MS.get(timeframe, 3_600_000)
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - count * tf_ms

        all_frames = []
        cursor = start_ms

        while cursor < now_ms:
            batch = self.client.fetch_ohlcv(
                symbol, timeframe, since=cursor, limit=self.MAX_PER_REQUEST,
            )
            if batch.empty:
                break

            all_frames.append(batch)
            last_ts = int(batch.iloc[-1]["timestamp"])

            # Move cursor past the last bar
            cursor = last_ts + tf_ms

            if len(batch) < self.MAX_PER_REQUEST:
                break

        if not all_frames:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        combined = pd.concat(all_frames, ignore_index=True)
        combined = combined.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")

        # Detect data gaps (>3x expected interval)
        if len(combined) > 1:
            gaps = combined["timestamp"].diff().dropna()
            max_gap = gaps.max()
            if max_gap > tf_ms * 3:
                logger.warning(
                    f"Data gap detected for {symbol}: "
                    f"max gap = {max_gap / tf_ms:.0f} bars "
                    f"(expected 1). ATR/indicators may be unreliable."
                )

        return combined.tail(count).reset_index(drop=True)

    def get_current_price(self, symbol: str) -> float:
        ticker = self.client.fetch_ticker(symbol)
        return float(ticker["last"])
