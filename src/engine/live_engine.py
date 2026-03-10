from __future__ import annotations

import signal
import time

import pandas as pd
from rich.console import Console
from rich.table import Table

from src.core.config import (
    AppConfig, TradingPairConfig,
    TIMEFRAME_SECONDS,
    bars_per_year as _bars_per_year,
)
from src.core.enums import MarketType
from src.data.feed import CcxtDataFeed
from src.execution.broker import Broker
from src.execution.paper_broker import PaperBroker
from src.execution.stops import trail_stop
from src.exchange.bybit_client import BybitClient
from src.notifications.telegram import TelegramNotifier
from src.portfolio.rolling_metrics import RollingMetrics
from src.portfolio.tracker import PortfolioTracker
from src.risk.manager import RiskManager
from src.strategies.base import BaseStrategy
from src.utils.logger import get_logger

logger = get_logger("live_engine")
console = Console()

STOP_CHECK_INTERVAL = 300  # Check stops every 5 minutes between candles
STATUS_INTERVAL = 4 * 3600  # Periodic Telegram status every 4 hours


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
        notifier: TelegramNotifier | None = None,
    ):
        self.data_feed = data_feed
        self.strategy = strategy
        self.risk_mgr = risk_manager
        self.broker = broker
        self.portfolio = portfolio
        self.config = config
        self.exchange_client = exchange_client
        self.notifier = notifier
        self._running = False
        self._halted = False

        # Trailing stop config from strategy params
        self._trail_mult = config.strategy.params.get("trailing_atr_mult", 0)
        self._atr_period = config.strategy.params.get("atr_period", 14)
        self._atr_col = f"atr_{self._atr_period}" if self._trail_mult > 0 else None

        # Max drawdown threshold
        self._max_dd = config.risk.max_drawdown_pct

        # Periodic status timer
        self._last_status_time = 0.0

        # Rolling performance monitors
        tf = config.strategy.params.get("timeframe", config.pairs[0].timeframe)
        bpy = _bars_per_year(tf)
        self._rolling_metrics = RollingMetrics(
            window_bars=720,  # ~30 days at 1h
            bars_per_year=bpy,
            sharpe_alert_threshold=0.0,
        )
        self._last_rolling: dict = {}

    def run(self) -> None:
        self._running = True
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        pairs = self.config.pairs
        timeframe = pairs[0].timeframe
        poll_interval = TIMEFRAME_SECONDS.get(timeframe, 3600)
        lookback = self.config.strategy.params.get("lookback_bars", 100)
        mode = "paper" if isinstance(self.broker, PaperBroker) else "live"

        # Set leverage for futures pairs
        if self.exchange_client:
            for pair in pairs:
                if pair.market_type == MarketType.FUTURES and pair.leverage > 1:
                    try:
                        self.exchange_client.set_leverage(pair.symbol, pair.leverage)
                    except Exception as e:
                        logger.warning(f"Could not set leverage for {pair.symbol}: {e}")

        # Sync existing positions from exchange on startup
        self._sync_positions(pairs)
        # Also sync strategy state for DB-restored positions
        self.strategy.sync_state(self.portfolio)

        console.print("[bold green]Live engine started[/bold green]")
        console.print(f"  Pairs: {[p.symbol for p in pairs]}")
        console.print(f"  Timeframe: {timeframe}")
        console.print(f"  Strategy: {self.config.strategy.name}")
        console.print(f"  Poll interval: {poll_interval}s")
        console.print(f"  Trailing stop: {self._trail_mult}x ATR({self._atr_period})")
        console.print(f"  Max drawdown halt: {self._max_dd:.0%}")
        console.print()

        # Telegram: engine started
        if self.notifier:
            self.notifier.notify_engine_start(
                [p.symbol for p in pairs], self.config.strategy.name, mode,
            )
        self._last_status_time = time.time()

        while self._running:
            try:
                self._tick(pairs, lookback)
                self._print_status()

                # Periodic Telegram status (every 4h)
                if self.notifier and time.time() - self._last_status_time >= STATUS_INTERVAL:
                    self.notifier.notify_status(
                        self.portfolio.equity, self.portfolio.cash,
                        self.portfolio.current_drawdown_pct,
                        self.portfolio.open_positions,
                        len(self.portfolio.closed_trades),
                        rolling_metrics=self._last_rolling,
                    )
                    self._last_status_time = time.time()

                # Sleep until next candle, but check stops every 5 min
                logger.info(f"Sleeping {poll_interval}s until next candle")
                elapsed = 0
                while elapsed < poll_interval and self._running:
                    sleep_chunk = min(STOP_CHECK_INTERVAL, poll_interval - elapsed)
                    for _ in range(sleep_chunk):
                        if not self._running:
                            break
                        time.sleep(1)
                    elapsed += sleep_chunk

                    # Mid-candle stop check (only if we have open positions)
                    if self._running and elapsed < poll_interval and self.portfolio.open_positions:
                        self._check_stops_quick(pairs)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                if self.notifier:
                    self.notifier.notify_error(str(e))
                time.sleep(30)

        logger.info("Live engine stopped")

    def _sync_positions(self, pairs: list[TradingPairConfig]) -> None:
        """Sync open positions from exchange on startup (recover from restarts)."""
        if not self.exchange_client:
            return

        try:
            exchange_positions = self.exchange_client.fetch_positions()
            pair_symbols = {p.symbol for p in pairs}

            for pos in exchange_positions:
                if pos.symbol not in pair_symbols:
                    continue
                if pos.symbol in self.portfolio.open_positions:
                    continue

                self.portfolio.open_positions[pos.symbol] = pos
                logger.info(
                    f"Synced position: {pos.side.value} {pos.symbol} "
                    f"qty={pos.quantity:.6f} entry={pos.entry_price:.2f} "
                    f"sl={pos.stop_loss}"
                )

            if exchange_positions:
                logger.info(f"Synced {len(exchange_positions)} position(s) from exchange")
            else:
                logger.info("No open positions on exchange")
        except Exception as e:
            logger.warning(f"Could not sync positions: {e}")

    def _tick(self, pairs: list[TradingPairConfig], lookback: int) -> None:
        now_ms = int(time.time() * 1000)

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

                # Apply indicators
                df = self.strategy.apply_indicators(df)

                # Update prices for portfolio tracking
                self.portfolio.update_prices({symbol: current_price})

                # --- Trailing stop: move SL in profit direction ---
                if self._trail_mult > 0 and self._atr_col and self._atr_col in df.columns:
                    last_row = df.iloc[-1]
                    if not pd.isna(last_row.get(self._atr_col)):
                        atr_val = float(last_row[self._atr_col])
                        if symbol in self.portfolio.open_positions:
                            pos = self.portfolio.open_positions[symbol]
                            old_sl = pos.stop_loss
                            updated = trail_stop(pos, current_price, atr_val, self._trail_mult)
                            if updated:
                                old = f"${old_sl:,.2f}" if old_sl else "None"
                                new = f"${pos.stop_loss:,.2f}"
                                logger.info(
                                    f"Trailing stop updated {symbol}: "
                                    f"{old} -> {new}"
                                )
                                if self.notifier:
                                    self.notifier.notify_trailing_stop(
                                        symbol, old_sl, pos.stop_loss, current_price,
                                    )
                                is_live = not isinstance(self.broker, PaperBroker)
                                if is_live and self.exchange_client:
                                    try:
                                        self.exchange_client.update_trading_stop(
                                            symbol, pos.stop_loss,
                                        )
                                    except Exception as e:
                                        logger.warning(
                                            f"Could not update exchange stop "
                                            f"for {symbol}: {e}"
                                        )

                # --- Check stops (paper mode) ---
                if isinstance(self.broker, PaperBroker):
                    stop_fills = self.broker.check_stops(
                        self.portfolio, {symbol: current_price}, now_ms,
                    )
                    for fill in stop_fills:
                        # Get trade info before on_fill removes the position
                        closed_pos = self.portfolio.open_positions.get(symbol)
                        self.portfolio.on_fill(fill)
                        self.strategy.on_fill(fill)
                        # Telegram: trade closed by stop
                        if self.notifier and closed_pos:
                            self.notifier.notify_trade_close(
                                symbol, closed_pos.side.value, closed_pos.quantity,
                                closed_pos.entry_price, fill.price,
                                (self.portfolio.closed_trades[-1]["pnl"]
                                 if self.portfolio.closed_trades else 0),
                                "SL", self.portfolio.equity,
                                self.portfolio.current_drawdown_pct,
                            )

                # --- Max drawdown halt ---
                if self._halted:
                    continue

                if self.portfolio.current_drawdown_pct >= self._max_dd:
                    logger.warning(
                        f"MAX DRAWDOWN {self.portfolio.current_drawdown_pct:.1%} "
                        f">= {self._max_dd:.0%} — halting new trades!"
                    )
                    self._halted = True
                    if self.notifier:
                        self.notifier.notify_max_drawdown_halt(
                            self.portfolio.current_drawdown_pct,
                        )
                    continue

                # --- Generate signals and trade ---
                signals = self.strategy.generate_signals(df, symbol)

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

                            # Store SL/TP on the portfolio position
                            if symbol in self.portfolio.open_positions:
                                pos = self.portfolio.open_positions[symbol]
                                pos.stop_loss = order.stop_loss
                                pos.take_profit = order.take_profit
                                # Telegram: trade opened
                                if self.notifier:
                                    self.notifier.notify_trade_open(
                                        symbol, fill.side.value, fill.quantity,
                                        fill.price, order.stop_loss,
                                        self.portfolio.equity,
                                    )
                            else:
                                # Position was closed (exit signal)
                                if self.notifier and self.portfolio.closed_trades:
                                    last_trade = self.portfolio.closed_trades[-1]
                                    self.notifier.notify_trade_close(
                                        symbol, last_trade["side"], last_trade["quantity"],
                                        last_trade["entry_price"], last_trade["exit_price"],
                                        last_trade["pnl"], "signal",
                                        self.portfolio.equity,
                                        self.portfolio.current_drawdown_pct,
                                    )

            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}", exc_info=True)
                if self.notifier:
                    self.notifier.notify_error(f"{symbol}: {e}")

        # Take snapshot ONCE per tick (after all pairs processed)
        self.portfolio.take_snapshot(now_ms)

        # Rolling metrics (after enough data)
        if len(self.portfolio.equity_curve) >= 48:
            self._last_rolling = self._rolling_metrics.compute(
                self.portfolio.equity_curve,
                self.portfolio.closed_trades,
            )
            if self._last_rolling.get("degradation_alert") and self.notifier:
                self.notifier.notify_degradation(self._last_rolling)

    def _check_stops_quick(self, pairs: list[TradingPairConfig]) -> None:
        """Quick mid-candle stop check — only fetch price + check SL/TP."""
        if not isinstance(self.broker, PaperBroker):
            return

        now_ms = int(time.time() * 1000)
        for pair in pairs:
            symbol = pair.symbol
            if symbol not in self.portfolio.open_positions:
                continue
            try:
                price = self.data_feed.get_current_price(symbol)
                self.portfolio.update_prices({symbol: price})

                closed_pos = self.portfolio.open_positions.get(symbol)
                stop_fills = self.broker.check_stops(
                    self.portfolio, {symbol: price}, now_ms,
                )
                for fill in stop_fills:
                    self.portfolio.on_fill(fill)
                    self.strategy.on_fill(fill)
                    logger.info(f"[MID-CANDLE] Stop triggered for {symbol} at {price:.2f}")
                    if self.notifier and closed_pos:
                        self.notifier.notify_trade_close(
                            symbol, closed_pos.side.value, closed_pos.quantity,
                            closed_pos.entry_price, fill.price,
                            (self.portfolio.closed_trades[-1]["pnl"]
                             if self.portfolio.closed_trades else 0),
                            "SL (mid-candle)", self.portfolio.equity,
                            self.portfolio.current_drawdown_pct,
                        )
            except Exception as e:
                logger.debug(f"Mid-candle check failed for {symbol}: {e}")

    def _print_status(self) -> None:
        table = Table(title="Portfolio Status", show_lines=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Equity", f"${self.portfolio.equity:.2f}")
        table.add_row("Cash", f"${self.portfolio.cash:.2f}")
        table.add_row("Open Positions", str(len(self.portfolio.open_positions)))
        table.add_row("Closed Trades", str(len(self.portfolio.closed_trades)))
        table.add_row("Drawdown", f"{self.portfolio.current_drawdown_pct:.2%}")
        if self._halted:
            table.add_row("STATUS", "[bold red]HALTED (max drawdown)[/bold red]")

        for symbol, pos in self.portfolio.open_positions.items():
            sl_str = f"sl={pos.stop_loss:.2f}" if pos.stop_loss else "sl=None"
            table.add_row(
                f"  {symbol}",
                f"{pos.side.value} qty={pos.quantity:.6f} "
                f"entry={pos.entry_price:.2f} pnl={pos.unrealized_pnl:.2f} {sl_str}"
            )

        console.print(table)

    def _shutdown(self, signum, frame) -> None:
        logger.info("Shutdown signal received")
        self._running = False
