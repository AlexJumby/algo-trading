from __future__ import annotations

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from src.core.config import AppConfig
from src.core.enums import Side
from src.data.feed import HistoricalDataFeed
from src.execution.backtest_broker import BacktestBroker
from src.portfolio.metrics import PerformanceMetrics
from src.portfolio.tracker import PortfolioTracker
from src.risk.manager import RiskManager
from src.strategies.base import BaseStrategy
from src.utils.logger import get_logger

logger = get_logger("backtest")
console = Console()


class BacktestEngine:
    def __init__(
        self,
        data_feed: HistoricalDataFeed,
        strategy: BaseStrategy,
        risk_manager: RiskManager,
        broker: BacktestBroker,
        portfolio: PortfolioTracker,
        config: AppConfig,
    ):
        self.data_feed = data_feed
        self.strategy = strategy
        self.risk_mgr = risk_manager
        self.broker = broker
        self.portfolio = portfolio
        self.config = config

    def run(self, symbol: str | None = None, silent: bool = False) -> dict:
        """Run backtest and return performance metrics.

        Args:
            symbol: Trading pair to backtest.
            silent: If True, skip progress bar and result printing (fast mode for optimizer).
        """
        symbol = symbol or self.config.pairs[0].symbol
        lookback = self.config.strategy.params.get("lookback_bars", 100)
        total_bars = len(self.data_feed)

        if not silent:
            logger.info(f"Starting backtest for {symbol}, {total_bars} bars")

        self._run_loop(symbol, lookback, silent, total_bars)

        # Compute metrics
        metrics = PerformanceMetrics(self.portfolio)
        results = metrics.compute_all()

        if not silent:
            self._print_results(results, symbol)
        return results

    def _run_loop(self, symbol: str, lookback: int, silent: bool, total_bars: int) -> None:
        """Core bar-by-bar loop, optionally with progress bar."""
        if silent:
            self._run_loop_silent(symbol, lookback)
        else:
            self._run_loop_progress(symbol, lookback, total_bars)

    def _run_loop_silent(self, symbol: str, lookback: int) -> None:
        """Fast loop: pre-compute indicators once, then iterate."""
        # Pre-compute all indicators on the full dataset (huge speedup)
        full_df = self.data_feed._full_data.copy()
        full_df = self.strategy.apply_indicators(full_df)
        total = len(full_df)

        # Trailing stop config from strategy params
        trail_mult = self.config.strategy.params.get("trailing_atr_mult", 0)
        atr_period = self.config.strategy.params.get("atr_period", 14)
        atr_col = f"atr_{atr_period}" if trail_mult > 0 else None

        for idx in range(total - 1):
            current_price = float(full_df.iloc[idx]["close"])
            timestamp = int(full_df.iloc[idx]["timestamp"])

            if idx >= lookback - 1:
                window = full_df.iloc[max(0, idx - lookback + 1):idx + 1]
                signals = self.strategy.generate_signals(window)

                # Trailing stop: move SL in profit direction
                if trail_mult > 0 and atr_col and atr_col in full_df.columns:
                    atr_val = float(full_df.iloc[idx][atr_col])
                    self._trail_stops(symbol, current_price, atr_val, trail_mult)

                stop_fills = self.broker.check_stops(
                    self.portfolio, {symbol: current_price}, timestamp,
                )
                for fill in stop_fills:
                    self.portfolio.on_fill(fill)
                    self.strategy.on_fill(fill)

                for signal in signals:
                    signal.symbol = symbol
                    order = self.risk_mgr.evaluate(signal, current_price)
                    if order:
                        fill = self.broker.submit_order(
                            order, current_price=current_price, timestamp=timestamp,
                        )
                        if fill:
                            self.portfolio.on_fill(fill)
                            self.strategy.on_fill(fill)
                            if symbol in self.portfolio.open_positions:
                                pos = self.portfolio.open_positions[symbol]
                                pos.stop_loss = order.stop_loss
                                pos.take_profit = order.take_profit

            self.portfolio.update_prices({symbol: current_price})
            self.portfolio.take_snapshot(timestamp)

    def _trail_stops(
        self, symbol: str, price: float, atr: float, mult: float,
    ) -> None:
        """Move stop-loss in the direction of profit (trailing stop)."""
        if symbol not in self.portfolio.open_positions:
            return
        pos = self.portfolio.open_positions[symbol]
        if pos.side == Side.BUY:
            new_sl = price - atr * mult
            if pos.stop_loss is None or new_sl > pos.stop_loss:
                pos.stop_loss = new_sl
        else:
            new_sl = price + atr * mult
            if pos.stop_loss is None or new_sl < pos.stop_loss:
                pos.stop_loss = new_sl

    def _run_loop_progress(self, symbol: str, lookback: int, total_bars: int) -> None:
        """Loop with Rich progress bar for interactive use."""
        # Trailing stop config from strategy params
        trail_mult = self.config.strategy.params.get("trailing_atr_mult", 0)
        atr_period = self.config.strategy.params.get("atr_period", 14)
        atr_col = f"atr_{atr_period}" if trail_mult > 0 else None

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"Backtesting {symbol}", total=total_bars)

            while not self.data_feed.is_exhausted:
                df = self.data_feed.get_latest_bars(symbol, "1h", lookback)
                current_price = self.data_feed.get_current_price(symbol)
                timestamp = self.data_feed.current_timestamp

                if len(df) >= lookback:
                    df = self.strategy.apply_indicators(df)
                    signals = self.strategy.generate_signals(df)

                    # Trailing stop: move SL in profit direction
                    if trail_mult > 0 and atr_col and atr_col in df.columns:
                        last_row = df.iloc[-1]
                        if not pd.isna(last_row.get(atr_col)):
                            atr_val = float(last_row[atr_col])
                            self._trail_stops(symbol, current_price, atr_val, trail_mult)

                    stop_fills = self.broker.check_stops(
                        self.portfolio, {symbol: current_price}, timestamp,
                    )
                    for fill in stop_fills:
                        self.portfolio.on_fill(fill)
                        self.strategy.on_fill(fill)

                    for signal in signals:
                        signal.symbol = symbol
                        order = self.risk_mgr.evaluate(signal, current_price)
                        if order:
                            fill = self.broker.submit_order(
                                order, current_price=current_price, timestamp=timestamp,
                            )
                            if fill:
                                self.portfolio.on_fill(fill)
                                self.strategy.on_fill(fill)
                                if symbol in self.portfolio.open_positions:
                                    pos = self.portfolio.open_positions[symbol]
                                    pos.stop_loss = order.stop_loss
                                    pos.take_profit = order.take_profit

                self.portfolio.update_prices({symbol: current_price})
                self.portfolio.take_snapshot(timestamp)
                self.data_feed.advance()
                progress.advance(task)

    def _print_results(self, results: dict, symbol: str) -> None:
        console.print()
        console.rule(f"[bold blue]Backtest Results — {symbol}[/bold blue]")

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Total Return", f"{results['total_return_pct']:.2%}")
        table.add_row("Total PnL", f"${results['total_pnl']:.2f}")
        table.add_row("Sharpe Ratio", f"{results['sharpe_ratio']:.3f}")
        table.add_row("Sortino Ratio", f"{results['sortino_ratio']:.3f}")
        table.add_row("Max Drawdown", f"{results['max_drawdown_pct']:.2%}")
        table.add_row("Win Rate", f"{results['win_rate']:.2%}")
        table.add_row("Profit Factor", f"{results['profit_factor']:.3f}")
        table.add_row("Total Trades", str(results['total_trades']))
        table.add_row("Avg Trade PnL", f"${results['avg_trade_pnl']:.2f}")
        table.add_row("Best Trade", f"${results['best_trade']:.2f}")
        table.add_row("Worst Trade", f"${results['worst_trade']:.2f}")
        table.add_row("Avg Win", f"${results['avg_win']:.2f}")
        table.add_row("Avg Loss", f"${results['avg_loss']:.2f}")

        console.print(table)
        console.print()
