"""Regime-Segmented Backtest Analysis.

Runs a full backtest, classifies each bar by market regime
(bull / bear / chop), then breaks down PnL contribution by regime.

Classification: price vs 200-EMA + 480-bar directional ROC.
- Bull: close > EMA-200 AND ROC > +2%
- Bear: close < EMA-200 AND ROC < -2%
- Chop: everything else

Usage:
    python -m scripts.regime_backtest
    python -m scripts.regime_backtest --data data/BTCUSDT_USDT_1h.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
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


def classify_bars_simple(
    df: pd.DataFrame,
    ema_period: int = 200,
    roc_period: int = 480,
    roc_threshold: float = 0.02,
) -> list[str]:
    """Classify each bar as bull / bear / chop.

    - Bull: close > EMA and positive ROC above threshold
    - Bear: close < EMA and negative ROC below -threshold
    - Chop: everything else (sideways, near EMA, weak ROC)
    """
    close = df["close"].values

    # EMA
    ema = pd.Series(close).ewm(span=ema_period, adjust=False).mean().values

    # Rate of change over roc_period bars
    roc = np.zeros(len(close))
    for i in range(roc_period, len(close)):
        if close[i - roc_period] != 0:
            roc[i] = (close[i] - close[i - roc_period]) / close[i - roc_period]

    regimes: list[str] = []
    for i in range(len(close)):
        if i < ema_period:
            regimes.append("chop")  # Not enough data for reliable EMA
        elif close[i] > ema[i] and roc[i] > roc_threshold:
            regimes.append("bull")
        elif close[i] < ema[i] and roc[i] < -roc_threshold:
            regimes.append("bear")
        else:
            regimes.append("chop")

    return regimes


def compute_regime_stats(
    equity_values: list[float],
    regimes: list[str],
) -> dict[str, dict]:
    """Compute per-regime PnL statistics from equity curve + regime labels.

    Returns dict mapping regime -> {bars, pct_time, total_return,
        mean_return_per_bar, sharpe_approx, equity_change}.
    """
    n = min(len(equity_values), len(regimes))

    # Collect per-bar returns grouped by regime
    returns_by_regime: dict[str, list[float]] = {
        "bull": [], "bear": [], "chop": [],
    }

    for i in range(1, n):
        if equity_values[i - 1] == 0:
            continue
        ret = (equity_values[i] - equity_values[i - 1]) / equity_values[i - 1]
        regime = regimes[i]
        if regime in returns_by_regime:
            returns_by_regime[regime].append(ret)

    stats: dict[str, dict] = {}
    total_bars = sum(len(v) for v in returns_by_regime.values())

    for regime, rets in returns_by_regime.items():
        if not rets:
            stats[regime] = {
                "bars": 0,
                "pct_time": 0.0,
                "total_return": 0.0,
                "mean_return_per_bar": 0.0,
                "sharpe_approx": 0.0,
                "equity_change": 0.0,
            }
            continue

        rets_arr = np.array(rets)
        total_ret = float(np.prod(1 + rets_arr) - 1)
        mean_ret = float(np.mean(rets_arr))
        std_ret = (
            float(np.std(rets_arr, ddof=1)) if len(rets_arr) > 1 else 0.0
        )
        sharpe = (
            float(np.sqrt(8760) * mean_ret / std_ret) if std_ret > 0 else 0.0
        )
        equity_change = float(np.sum(rets_arr) * equity_values[0])

        stats[regime] = {
            "bars": len(rets),
            "pct_time": len(rets) / total_bars if total_bars > 0 else 0.0,
            "total_return": total_ret,
            "mean_return_per_bar": mean_ret,
            "sharpe_approx": sharpe,
            "equity_change": equity_change,
        }

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Regime-Segmented Backtest Analysis",
    )
    parser.add_argument("--data", default="data/BTCUSDT_USDT_1h.csv")
    parser.add_argument("--symbol", default="BTC/USDT:USDT")
    parser.add_argument("--leverage", type=int, default=7)
    parser.add_argument("--pos-pct", type=float, default=0.15)
    parser.add_argument("--ema-period", type=int, default=200)
    parser.add_argument("--roc-period", type=int, default=480)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    df = HistoricalDataManager.load_csv(args.data)
    console.print(f"[bold]Loaded {len(df)} bars ({len(df) / 24:.0f} days)[/bold]")

    # ---- Classify bars ----
    regimes = classify_bars_simple(df, args.ema_period, args.roc_period)
    regime_counts: dict[str, int] = {}
    for r in regimes:
        regime_counts[r] = regime_counts.get(r, 0) + 1

    console.print("\n[bold]Market Regime Distribution:[/bold]")
    for regime, count in sorted(regime_counts.items()):
        pct = count / len(regimes) * 100
        emoji = {"bull": "\U0001f7e2", "bear": "\U0001f534", "chop": "\U0001f7e1"}.get(
            regime, "\u26aa",
        )
        console.print(f"  {emoji} {regime.capitalize():>5}: {count:>6} bars ({pct:.1f}%)")
    console.print()

    # ---- Run full backtest ----
    console.print("[dim]Running full backtest...[/dim]")

    data_feed = HistoricalDataFeed(df.copy())
    broker = BacktestBroker(commission=0.001, slippage=0.0005)
    portfolio = PortfolioTracker(10000.0)

    strategy = STRATEGY_REGISTRY["tsmom"]()
    strategy_config = StrategyConfig(name="tsmom", params=BASE_PARAMS)
    strategy.setup(strategy_config)

    risk_config = RiskConfig(
        max_position_size_pct=args.pos_pct,
        max_open_positions=3,
        max_drawdown_pct=0.35,
        default_stop_loss_pct=0.03,
        default_take_profit_pct=0.06,
    )
    risk_mgr = RiskManager(risk_config, portfolio, leverage=args.leverage)

    app_config = AppConfig(
        exchange=ExchangeConfig(),
        pairs=[TradingPairConfig(
            symbol=args.symbol, market_type=MarketType.FUTURES,
            leverage=args.leverage,
        )],
        strategy=strategy_config,
        risk=risk_config,
        backtest=BacktestConfig(initial_capital=10000.0),
    )

    engine = BacktestEngine(
        data_feed, strategy, risk_mgr, broker, portfolio, app_config,
    )
    results = engine.run(symbol=args.symbol, silent=True)

    if not results:
        console.print("[red]Backtest failed![/red]")
        return

    console.print(
        f"Overall: Return={results['total_return_pct']:.1%} | "
        f"Sharpe={results['sharpe_ratio']:.3f} | "
        f"Trades={results['total_trades']}\n"
    )

    # ---- Per-regime breakdown ----
    equity_values = [snap.equity for snap in portfolio.equity_curve]
    ec_len = len(equity_values)
    regimes_trimmed = regimes[:ec_len]

    stats = compute_regime_stats(equity_values, regimes_trimmed)

    table = Table(title="Performance by Market Regime", show_lines=True)
    table.add_column("Regime", style="cyan", justify="center")
    table.add_column("Time %", justify="center")
    table.add_column("Return", justify="center")
    table.add_column("Sharpe (approx)", justify="center")
    table.add_column("Eq Change", justify="center")
    table.add_column("Bars", justify="center")

    for regime in ["bull", "bear", "chop"]:
        s = stats.get(regime, {})
        if not s or s["bars"] == 0:
            continue

        emoji = {
            "bull": "\U0001f7e2", "bear": "\U0001f534", "chop": "\U0001f7e1",
        }[regime]
        ret = s["total_return"]
        sharpe = s["sharpe_approx"]
        eq_chg = s["equity_change"]
        ret_style = "green" if ret > 0 else "red"
        sharpe_style = (
            "green" if sharpe > 0.5
            else ("red" if sharpe < 0 else "yellow")
        )
        eq_style = "green" if eq_chg > 0 else "red"

        table.add_row(
            f"{emoji} {regime.capitalize()}",
            f"{s['pct_time']:.0%}",
            f"[{ret_style}]{ret:.1%}[/{ret_style}]",
            f"[{sharpe_style}]{sharpe:.2f}[/{sharpe_style}]",
            f"[{eq_style}]${eq_chg:+,.0f}[/{eq_style}]",
            str(s["bars"]),
        )

    console.print(table)

    # ---- Analysis ----
    console.print()
    console.print("[bold]Analysis:[/bold]")

    bull_ret = stats.get("bull", {}).get("total_return", 0)
    bear_ret = stats.get("bear", {}).get("total_return", 0)
    chop_ret = stats.get("chop", {}).get("total_return", 0)

    if bull_ret > 0:
        console.print(
            f"  [green]\u2713[/green] Bull: profitable ({bull_ret:.1%})"
        )
    else:
        console.print(
            f"  [red]\u2717[/red] Bull: losing ({bull_ret:.1%})"
        )

    if bear_ret > 0:
        console.print(
            f"  [green]\u2713[/green] Bear: profitable ({bear_ret:.1%}) — "
            "trend-following captures downtrends"
        )
    else:
        console.print(
            f"  [yellow]\u2013[/yellow] Bear: losing ({bear_ret:.1%})"
        )

    if chop_ret > -0.05:
        console.print(
            f"  [green]\u2713[/green] Chop: controlled losses ({chop_ret:.1%}) — "
            "regime filter limits damage"
        )
    else:
        console.print(
            f"  [red]\u2717[/red] Chop: significant losses ({chop_ret:.1%}) — "
            "regime filter may need tuning"
        )

    # ---- Export ----
    if args.output:
        export = {
            "overall": {k: v for k, v in results.items()},
            "regime_distribution": regime_counts,
            "regime_stats": stats,
        }
        with open(args.output, "w") as f:
            json.dump(export, f, indent=2, default=str)
        console.print(f"\nResults exported to {args.output}")


if __name__ == "__main__":
    main()
