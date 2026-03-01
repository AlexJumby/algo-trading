"""Fetch historical OHLCV data from Bybit and save to CSV.

Usage:
    python scripts/fetch_historical.py
    python scripts/fetch_historical.py --symbol BTC/USDT --timeframe 1h --days 365
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to sys.path so `src` is importable from any cwd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import AppConfig
from src.data.historical import HistoricalDataManager
from src.exchange.bybit_client import BybitClient
from src.utils.logger import setup_logging, get_logger

logger = get_logger("fetch_historical")


def main():
    parser = argparse.ArgumentParser(description="Fetch historical OHLCV data from Bybit")
    parser.add_argument("--config", default="config/settings.yaml", help="Config file path")
    parser.add_argument("--symbol", default=None, help="Symbol (e.g., BTC/USDT)")
    parser.add_argument("--timeframe", default="1h", help="Candle timeframe")
    parser.add_argument("--days", type=int, default=365, help="Number of days to fetch")
    parser.add_argument("--output", default=None, help="Output CSV path")
    args = parser.parse_args()

    config = AppConfig.from_yaml(args.config)
    setup_logging(log_level=config.log_level)

    client = BybitClient()
    client.connect(config.exchange)

    symbols = [args.symbol] if args.symbol else [p.symbol for p in config.pairs]

    now = datetime.now(tz=timezone.utc)
    since = int((now - timedelta(days=args.days)).timestamp() * 1000)
    until = int(now.timestamp() * 1000)

    for symbol in symbols:
        logger.info(f"Fetching {symbol} {args.timeframe} for {args.days} days")
        df = HistoricalDataManager.fetch_from_exchange(
            client, symbol, args.timeframe, since=since, until=until
        )
        if df.empty:
            logger.warning(f"No data fetched for {symbol}")
            continue

        if args.output:
            out_path = args.output
        else:
            safe_symbol = symbol.replace("/", "").replace(":", "_")
            out_path = f"data/{safe_symbol}_{args.timeframe}.csv"

        HistoricalDataManager.save_csv(df, out_path)
        logger.info(f"Saved {len(df)} bars to {out_path}")


if __name__ == "__main__":
    main()
