"""Run live or paper trading.

Usage:
    python scripts/run_live.py                    # Paper trading (default, testnet)
    python scripts/run_live.py --mode live        # Live trading (use with caution!)
    python scripts/run_live.py --mode paper       # Paper trading on testnet
"""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path so `src` is importable from any cwd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.config import AppConfig
from src.data.feed import CcxtDataFeed
from src.engine.live_engine import LiveEngine
from src.exchange.bybit_client import BybitClient
from src.execution.live_broker import LiveBroker
from src.execution.paper_broker import PaperBroker
from src.portfolio.tracker import PortfolioTracker
from src.risk.manager import RiskManager
from src.strategies.momentum import STRATEGY_REGISTRY
from src.utils.logger import setup_logging, get_logger

logger = get_logger("run_live")


def main():
    parser = argparse.ArgumentParser(description="Run live/paper trading on Bybit")
    parser.add_argument("--config", default="config/settings.yaml", help="Config file path")
    parser.add_argument(
        "--mode", choices=["live", "paper"], default="paper",
        help="Trading mode (default: paper)",
    )
    parser.add_argument(
        "--capital", type=float, default=None,
        help="Initial capital for tracking (defaults to actual balance in live mode)",
    )
    args = parser.parse_args()

    config = AppConfig.from_yaml(args.config)
    setup_logging(log_level=config.log_level)

    # Safety check
    if args.mode == "live" and not config.exchange.testnet:
        logger.warning("=" * 60)
        logger.warning("  WARNING: LIVE TRADING ON MAINNET!")
        logger.warning("  Real money will be used.")
        logger.warning("=" * 60)
        response = input("Type 'YES' to confirm: ")
        if response != "YES":
            logger.info("Aborted.")
            sys.exit(0)

    # Connect to exchange
    client = BybitClient()
    client.connect(config.exchange)

    # Create data feed
    data_feed = CcxtDataFeed(client)

    # Create broker
    if args.mode == "paper":
        broker = PaperBroker(client)
        logger.info("Running in PAPER trading mode")
    else:
        broker = LiveBroker(client)
        logger.info("Running in LIVE trading mode")

    # Determine initial capital
    if args.capital:
        initial_capital = args.capital
    else:
        try:
            balance = client.fetch_balance()
            initial_capital = float(balance.get("total", {}).get("USDT", 0))
            if initial_capital == 0:
                initial_capital = 10000.0
                logger.warning(f"Could not detect balance, using default: ${initial_capital}")
        except Exception:
            initial_capital = 10000.0
            logger.warning(f"Could not fetch balance, using default: ${initial_capital}")

    logger.info(f"Initial capital: ${initial_capital:.2f}")

    # Create portfolio tracker
    portfolio = PortfolioTracker(initial_capital)

    # Create strategy
    strategy_cls = STRATEGY_REGISTRY.get(config.strategy.name)
    if not strategy_cls:
        logger.error(f"Unknown strategy: {config.strategy.name}")
        sys.exit(1)

    strategy = strategy_cls()
    strategy.setup(config.strategy)

    # Create risk manager
    risk_mgr = RiskManager(config.risk, portfolio)

    # Create and run engine
    engine = LiveEngine(
        data_feed=data_feed,
        strategy=strategy,
        risk_manager=risk_mgr,
        broker=broker,
        portfolio=portfolio,
        config=config,
        exchange_client=client,
    )
    engine.run()


if __name__ == "__main__":
    main()
