"""Walk-Forward Validation for TSMOM Strategy.

Tests out-of-sample performance across rolling time windows.
For each fold:
1. Warmup period: lookback_bars for indicator computation
2. Test period: 2 months (1460 bars @1h) of actual trading

Folds are non-overlapping in the test period, sliding forward in steps.

Usage:
    python -m scripts.walk_forward
    python -m scripts.walk_forward --data data/BTCUSDT_USDT_1h.csv --test-months 2
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from src.core.config import (
    AppConfig,
    BacktestConfig,
    ExchangeConfig,
    RiskConfig,
    StrategyConfig,
    TradingPairConfig,
)
from src.core.enums import MarketType
from src.data.feed import HistoricalDataFeed
from src.data.historical import HistoricalDataManager
from src.engine.backtest_engine import BacktestEngine
from src.execution.backtest_broker import BacktestBroker
from src.portfolio.tracker import PortfolioTracker
from src.risk.manager import RiskManager
from src.strategies.momentum import STRATEGY_REGISTRY

console = Console()

# Default TSMOM params (current production config)
BASE_PARAMS: dict = {
    "roc_short": 48,
    "roc_medium": 336,
    "roc_long": 1440,
    "w_short": 0.16,
    "w_medium": 0.24,
    "w_long": 0.60,
    "entry_threshold": 0.02,
    "vol_lookback": 336,
    "target_vol": 0.50,
    "max_vol_scalar": 3.0,
    "min_vol_scalar": 0.2,
    "adx_period": 14,
    "adx_threshold": 22,
    "trend_ema": 400,
    "atr_period": 14,
    "atr_sl_mult": 3.0,
    "trailing_atr_mult": 3.5,
    "cooldown_bars": 24,
    "lookback_bars": 1640,
    "vol_mode": "ewma",
    "regime_enabled": True,
    "regime_period": 14,
    "regime_threshold": 0.4,
}


def generate_folds(
    total_bars: int, warmup_bars: int, test_bars: int,
) -> list[tuple[int, int, int]]:
    """Generate non-overlapping walk-forward folds.

    Returns list of (data_start, test_start, data_end) tuples.
    Each fold uses data[data_start:data_end] for backtesting,
    where data[data_start:test_start] is warmup and
    data[test_start:data_end] is the test period.
    """
    folds = []
    fold_idx = 0
    while True:
        test_start = warmup_bars + fold_idx * test_bars
        test_end = test_start + test_bars
        if test_end > total_bars:
            break
        data_start = test_start - warmup_bars
        folds.append((data_start, test_start, test_end))
        fold_idx += 1
    return folds


def run_fold(
    df_slice, params: dict, symbol: str, leverage: int, pos_pct: float,
) -> dict | None:
    """Run backtest on a data slice and return results."""
    data_feed = HistoricalDataFeed(df_slice.copy())
    broker = BacktestBroker(commission=0.001, slippage=0.0005)
    portfolio = PortfolioTracker(10000.0)

    strategy = STRATEGY_REGISTRY["tsmom"]()
    strategy_config = StrategyConfig(name="tsmom", params=params)
    strategy.setup(strategy_config)

    risk_config = RiskConfig(
        max_position_size_pct=pos_pct,
        max_open_positions=3,
        max_drawdown_pct=0.35,
        default_stop_loss_pct=0.03,
        default_take_profit_pct=0.06,
    )
    risk_mgr = RiskManager(risk_config, portfolio, leverage=leverage)

    app_config = AppConfig(
        exchange=ExchangeConfig(),
        pairs=[TradingPairConfig(
            symbol=symbol, market_type=MarketType.FUTURES, leverage=leverage,
        )],
        strategy=strategy_config,
        risk=risk_config,
        backtest=BacktestConfig(initial_capital=10000.0),
    )

    engine = BacktestEngine(
        data_feed, strategy, risk_mgr, broker, portfolio, app_config,
    )
    try:
        return engine.run(symbol=symbol, silent=True)
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="Walk-Forward Validation")
    parser.add_argument("--data", default="data/BTCUSDT_USDT_1h.csv")
    parser.add_argument("--symbol", default="BTC/USDT:USDT")
    parser.add_argument("--leverage", type=int, default=7)
    parser.add_argument("--pos-pct", type=float, default=0.15)
    parser.add_argument("--test-months", type=int, default=2)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    df = HistoricalDataManager.load_csv(args.data)
    total_bars = len(df)
    console.print(f"[bold]Loaded {total_bars} bars ({total_bars / 24:.0f} days)[/bold]")

    warmup_bars = BASE_PARAMS["lookback_bars"]
    test_bars = args.test_months * 30 * 24  # approximate hours
    folds = generate_folds(total_bars, warmup_bars, test_bars)
    console.print(
        f"Walk-Forward: {len(folds)} folds × {args.test_months}mo test windows\n"
        f"Warmup: {warmup_bars} bars ({warmup_bars / 24:.0f} days)\n"
    )

    if not folds:
        console.print("[red]Not enough data for walk-forward validation[/red]")
        return

    # ---- Baseline: full-period backtest ----
    console.print("[dim]Running full-period baseline...[/dim]")
    baseline = run_fold(df, BASE_PARAMS, args.symbol, args.leverage, args.pos_pct)
    if not baseline:
        console.print("[red]Baseline backtest failed![/red]")
        return

    console.print(
        f"Baseline: Sharpe={baseline['sharpe_ratio']:.3f} | "
        f"Return={baseline['total_return_pct']:.1%} | "
        f"Trades={baseline['total_trades']}\n"
    )

    # ---- Run each fold ----
    fold_results = []
    with Progress(console=console) as progress:
        task = progress.add_task("Walk-forward folds...", total=len(folds))
        for i, (data_start, test_start, test_end) in enumerate(folds):
            df_slice = df.iloc[data_start:test_end].reset_index(drop=True)
            result = run_fold(
                df_slice, BASE_PARAMS, args.symbol, args.leverage, args.pos_pct,
            )

            if result:
                ts_start = int(df.iloc[test_start]["timestamp"])
                ts_end = int(
                    df.iloc[min(test_end - 1, total_bars - 1)]["timestamp"]
                )
                fold_results.append({
                    "fold": i + 1,
                    "test_start_bar": test_start,
                    "test_end_bar": test_end,
                    "ts_start": ts_start,
                    "ts_end": ts_end,
                    **result,
                })
            progress.advance(task)

    # ---- Results table ----
    table = Table(title="Walk-Forward Validation (OOS Results)", show_lines=True)
    table.add_column("Fold", justify="center", style="cyan")
    table.add_column("Period", justify="center")
    table.add_column("Return", justify="center")
    table.add_column("Sharpe", justify="center")
    table.add_column("Max DD", justify="center")
    table.add_column("Win Rate", justify="center")
    table.add_column("PF", justify="center")
    table.add_column("Trades", justify="center")

    for fr in fold_results:
        start_dt = datetime.fromtimestamp(fr["ts_start"] / 1000, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(fr["ts_end"] / 1000, tz=timezone.utc)
        period = f"{start_dt:%Y-%m-%d}\n{end_dt:%Y-%m-%d}"

        ret = fr["total_return_pct"]
        sharpe = fr["sharpe_ratio"]
        ret_style = "green" if ret > 0 else "red"
        sharpe_style = "green" if sharpe > 0 else "red"

        pf = fr["profit_factor"]
        pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"

        table.add_row(
            str(fr["fold"]),
            period,
            f"[{ret_style}]{ret:.1%}[/{ret_style}]",
            f"[{sharpe_style}]{sharpe:.2f}[/{sharpe_style}]",
            f"{fr['max_drawdown_pct']:.1%}",
            f"{fr['win_rate']:.0%}",
            pf_str,
            str(fr["total_trades"]),
        )

    console.print()
    console.print(table)

    # ---- Aggregate OOS metrics ----
    if fold_results:
        sharpes = [fr["sharpe_ratio"] for fr in fold_results]
        returns = [fr["total_return_pct"] for fr in fold_results]
        max_dds = [fr["max_drawdown_pct"] for fr in fold_results]
        profitable_folds = sum(1 for r in returns if r > 0)
        positive_sharpe_folds = sum(1 for s in sharpes if s > 0)

        console.print()
        console.print("[bold]Aggregate OOS Metrics:[/bold]")
        console.print(
            f"  Profitable folds:      {profitable_folds}/{len(fold_results)} "
            f"({profitable_folds / len(fold_results):.0%})"
        )
        console.print(
            f"  Positive Sharpe folds: {positive_sharpe_folds}/{len(fold_results)} "
            f"({positive_sharpe_folds / len(fold_results):.0%})"
        )
        console.print(f"  Mean OOS Sharpe:       {np.mean(sharpes):.3f}")
        console.print(f"  Median OOS Sharpe:     {np.median(sharpes):.3f}")
        console.print(f"  Mean OOS Return:       {np.mean(returns):.1%}")
        console.print(f"  Worst Fold Return:     {min(returns):.1%}")
        console.print(f"  Worst Fold Max DD:     {max(max_dds):.1%}")

        if baseline["sharpe_ratio"] > 0:
            wfe = np.mean(sharpes) / baseline["sharpe_ratio"]
            console.print(
                f"  WF Efficiency:         {wfe:.1%} (OOS Sharpe / IS Sharpe)"
            )

        # ---- Verdict ----
        console.print()
        if (
            profitable_folds >= len(fold_results) * 0.7
            and np.mean(sharpes) > 0.3
        ):
            console.print(
                "[bold green]✓ Walk-forward PASSED — "
                "strategy is robust across time periods[/bold green]"
            )
        elif profitable_folds >= len(fold_results) * 0.5:
            console.print(
                "[bold yellow]⚠ Walk-forward MIXED — "
                "some time periods underperform[/bold yellow]"
            )
        else:
            console.print(
                "[bold red]✗ Walk-forward FAILED — "
                "strategy may be overfit to specific period[/bold red]"
            )

    # ---- Export ----
    if args.output:
        export = {
            "baseline": {k: v for k, v in baseline.items()},
            "folds": fold_results,
            "aggregate": {
                "mean_sharpe": float(np.mean(sharpes)),
                "median_sharpe": float(np.median(sharpes)),
                "mean_return": float(np.mean(returns)),
                "profitable_folds": profitable_folds,
                "total_folds": len(fold_results),
            },
        }
        with open(args.output, "w") as f:
            json.dump(export, f, indent=2, default=str)
        console.print(f"\nResults exported to {args.output}")


if __name__ == "__main__":
    main()
