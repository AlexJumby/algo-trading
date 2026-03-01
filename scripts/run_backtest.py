"""Run backtesting on historical data.

Usage:
    python scripts/run_backtest.py
    python scripts/run_backtest.py --config config/settings.yaml --data data/BTCUSDT_USDT_1h.csv
"""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path so `src` is importable from any cwd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import AppConfig
from src.data.feed import HistoricalDataFeed
from src.data.historical import HistoricalDataManager
from src.engine.backtest_engine import BacktestEngine
from src.execution.backtest_broker import BacktestBroker
from src.portfolio.tracker import PortfolioTracker
from src.risk.manager import RiskManager
from src.strategies.momentum import STRATEGY_REGISTRY
from src.utils.logger import setup_logging, get_logger

logger = get_logger("run_backtest")


def main():
    parser = argparse.ArgumentParser(description="Run backtest on historical data")
    parser.add_argument("--config", default="config/settings.yaml", help="Config file path")
    parser.add_argument("--data", default=None, help="CSV data file (overrides auto-detection)")
    parser.add_argument("--symbol", default=None, help="Symbol to backtest")
    args = parser.parse_args()

    config = AppConfig.from_yaml(args.config)
    setup_logging(log_level=config.log_level)

    if not config.backtest:
        logger.error("No backtest section in config")
        sys.exit(1)

    symbol = args.symbol or config.pairs[0].symbol
    timeframe = config.pairs[0].timeframe

    # Load historical data
    if args.data:
        data_path = args.data
    else:
        safe_symbol = symbol.replace("/", "").replace(":", "_")
        data_path = f"data/{safe_symbol}_{timeframe}.csv"

    if not Path(data_path).exists():
        logger.error(
            f"Data file not found: {data_path}\n"
            f"Run: python scripts/fetch_historical.py --symbol {symbol} --timeframe {timeframe}"
        )
        sys.exit(1)

    logger.info(f"Loading data from {data_path}")
    df = HistoricalDataManager.load_csv(data_path)
    logger.info(f"Loaded {len(df)} bars")

    # Wire up components
    data_feed = HistoricalDataFeed(df)
    broker = BacktestBroker(
        commission=config.backtest.commission_pct,
        slippage=config.backtest.slippage_pct,
    )
    portfolio = PortfolioTracker(config.backtest.initial_capital)

    strategy_cls = STRATEGY_REGISTRY.get(config.strategy.name)
    if not strategy_cls:
        logger.error(f"Unknown strategy: {config.strategy.name}")
        sys.exit(1)

    strategy = strategy_cls()
    strategy.setup(config.strategy)

    leverage = config.pairs[0].leverage if config.pairs else 1
    risk_mgr = RiskManager(config.risk, portfolio, leverage=leverage)

    engine = BacktestEngine(data_feed, strategy, risk_mgr, broker, portfolio, config)
    results = engine.run(symbol=symbol)


if __name__ == "__main__":
    main()
