from __future__ import annotations

import signal
import sys
import time

from rich.console import Console
from rich.live import Live
from rich.table import Table

from src.core.config import AppConfig, TradingPairConfig
from src.core.enums import MarketType
from src.data.feed import CcxtDataFeed
from src.execution.broker import Broker
from src.exchange.bybit_client import BybitClient
from src.portfolio.tracker import PortfolioTracker
from src.risk.manager import RiskManager
from src.strategies.base import BaseStrategy
from src.utils.logger import get_logger

logger = get_logger("live_engine")
console = Console()

# Timeframe to seconds mapping
TIMEFRAME_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900,
    "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
    "6h": 21600, "12h": 43200, "1d": 86400,
}


class LiveEngine:
    """Live/paper trading engine. Polls on each candle close."""

    def __init__(
        self,
        data_feed: CcxtDataFeed,
        strategy: BaseStrategy,
        risk_manager: RiskManager,
        broker: Broker,
        portfolio: PortfolioTracker,
        config: AppConfig,
        exchange_client: BybitClient | None = None,
    ):
        self.data_feed = data_feed
        self.strategy = strategy
        self.risk_mgr = risk_manager
        self.broker = broker
        self.portfolio = portfolio
        self.config = config
        self.exchange_client = exchange_client
        self._running = False

    def run(self) -> None:
        self._running = True
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        pairs = self.config.pairs
        timeframe = pairs[0].timeframe
        poll_interval = TIMEFRAME_SECONDS.get(timeframe, 3600)
        lookback = self.config.strategy.params.get("lookback_bars", 100)

        # Set leverage for futures pairs
        if self.exchange_client:
            for pair in pairs:
                if pair.market_type == MarketType.FUTURES and pair.leverage > 1:
                    try:
                        self.exchange_client.set_leverage(pair.symbol, pair.leverage)
                    except Exception as e:
                        logger.warning(f"Could not set leverage for {pair.symbol}: {e}")

        console.print(f"[bold green]Live engine started[/bold green]")
        console.print(f"  Pairs: {[p.symbol for p in pairs]}")
        console.print(f"  Timeframe: {timeframe}")
        console.print(f"  Strategy: {self.config.strategy.name}")
        console.print(f"  Poll interval: {poll_interval}s")
        console.print()

        while self._running:
            try:
                self._tick(pairs, lookback)
                self._print_status()

                logger.info(f"Sleeping {poll_interval}s until next candle")
                for _ in range(poll_interval):
                    if not self._running:
                        break
                    time.sleep(1)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                time.sleep(30)

        logger.info("Live engine stopped")

    def _tick(self, pairs: list[TradingPairConfig], lookback: int) -> None:
        for pair in pairs:
            symbol = pair.symbol
            timeframe = pair.timeframe

            try:
                # Fetch latest bars
                df = self.data_feed.get_latest_bars(symbol, timeframe, lookback)
                if len(df) < lookback:
                    logger.warning(f"Insufficient data for {symbol}: {len(df)}/{lookback}")
                    continue

                current_price = self.data_feed.get_current_price(symbol)

                # Apply indicators and generate signals
                df = self.strategy.apply_indicators(df)
                signals = self.strategy.generate_signals(df)

                # Update prices for portfolio tracking
                self.portfolio.update_prices({symbol: current_price})

                # Process signals
                for signal_obj in signals:
                    signal_obj.symbol = symbol
                    order = self.risk_mgr.evaluate(signal_obj, current_price)
                    if order:
                        order.market_type = pair.market_type
                        order.leverage = pair.leverage
                        fill = self.broker.submit_order(order)
                        if fill:
                            self.portfolio.on_fill(fill)
                            self.strategy.on_fill(fill)

                # Take snapshot
                self.portfolio.take_snapshot(int(time.time() * 1000))

            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}", exc_info=True)

    def _print_status(self) -> None:
        table = Table(title="Portfolio Status", show_lines=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Equity", f"${self.portfolio.equity:.2f}")
        table.add_row("Cash", f"${self.portfolio.cash:.2f}")
        table.add_row("Open Positions", str(len(self.portfolio.open_positions)))
        table.add_row("Closed Trades", str(len(self.portfolio.closed_trades)))
        table.add_row("Drawdown", f"{self.portfolio.current_drawdown_pct:.2%}")

        for symbol, pos in self.portfolio.open_positions.items():
            table.add_row(
                f"  {symbol}",
                f"{pos.side.value} qty={pos.quantity:.6f} "
                f"entry={pos.entry_price:.2f} pnl={pos.unrealized_pnl:.2f}"
            )

        console.print(table)

    def _shutdown(self, signum, frame) -> None:
        logger.info("Shutdown signal received")
        self._running = False
