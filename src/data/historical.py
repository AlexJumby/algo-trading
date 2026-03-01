from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("data.historical")


class HistoricalDataManager:
    """Fetch historical OHLCV data from exchange and cache as CSV."""

    @staticmethod
    def fetch_from_exchange(
        exchange_client,
        symbol: str,
        timeframe: str,
        since: int,
        until: int | None = None,
        limit_per_request: int = 200,
    ) -> pd.DataFrame:
        """Fetch historical data with pagination. `since` and `until` are Unix ms."""
        all_data = []
        current_since = since

        while True:
            logger.info(f"Fetching {symbol} {timeframe} from {current_since}")
            df = exchange_client.fetch_ohlcv(
                symbol, timeframe, since=current_since, limit=limit_per_request
            )
            if df.empty:
                break

            all_data.append(df)
            last_ts = int(df.iloc[-1]["timestamp"])

            if until and last_ts >= until:
                break
            if len(df) < limit_per_request:
                break

            current_since = last_ts + 1
            time.sleep(0.5)  # Rate limit

        if not all_data:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        result = pd.concat(all_data, ignore_index=True)
        result = result.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
        result = result.reset_index(drop=True)

        if until:
            result = result[result["timestamp"] <= until]

        logger.info(f"Fetched {len(result)} bars for {symbol} {timeframe}")
        return result

    @staticmethod
    def save_csv(df: pd.DataFrame, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        logger.info(f"Saved {len(df)} bars to {path}")

    @staticmethod
    def load_csv(path: str | Path) -> pd.DataFrame:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Data file not found: {path}")
        df = pd.read_csv(path)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        df["timestamp"] = df["timestamp"].astype(int)
        return df
