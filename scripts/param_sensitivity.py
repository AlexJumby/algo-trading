"""Parameter Sensitivity Analysis for TSMOM Strategy.

For each key parameter:
1. Create ±20% grid (5 points: -20%, -10%, base, +10%, +20%)
2. Run backtest for each value (all other params at base)
3. Report Sharpe, MaxDD, PF, trades for each point
4. Classify as ROBUST / MODERATE / FRAGILE

Usage:
    python -m scripts.param_sensitivity
    python -m scripts.param_sensitivity --symbol ETH/USDT:USDT --data data/ETHUSDT_USDT_1h.csv
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from src.core.config import (
    AppConfig, BacktestConfig, ExchangeConfig,
    RiskConfig, StrategyConfig, TradingPairConfig,
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

# Parameters to test and their types
SENSITIVE_PARAMS: dict[str, tuple[str, str]] = {
    "ROC Short":        ("roc_short",           "int"),
    "ROC Medium":       ("roc_medium",          "int"),
    "ROC Long":         ("roc_long",            "int"),
    "Entry Threshold":  ("entry_threshold",     "float"),
    "Vol Lookback":     ("vol_lookback",        "int"),
    "ADX Threshold":    ("adx_threshold",       "int"),
    "Trend EMA":        ("trend_ema",           "int"),
    "ATR SL Mult":      ("atr_sl_mult",         "float"),
    "Trailing ATR":     ("trailing_atr_mult",   "float"),
    "Target Vol":       ("target_vol",          "float"),
}

# Shift percentages
SHIFTS = [-0.20, -0.10, 0.0, +0.10, +0.20]


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
    "regime_enabled": False,  # Disable regime filter for fair comparison
}


def apply_shift(base_value: float, shift: float, param_type: str) -> float:
    """Apply a percentage shift to a base value."""
    shifted = base_value * (1 + shift)
    if param_type == "int":
        return max(1, round(shifted))
    return round(shifted, 6)


def run_one(df, params: dict, symbol: str, leverage: int, pos_pct: float) -> dict | None:
    """Run a single backtest and return results."""
    data_feed = HistoricalDataFeed(df.copy())
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

    engine = BacktestEngine(data_feed, strategy, risk_mgr, broker, portfolio, app_config)
    try:
        return engine.run(symbol=symbol, silent=True)
    except Exception:
        return None


def classify_robustness(
    sharpes: list[float], base_sharpe: float,
) -> str:
    """Classify parameter as ROBUST / MODERATE / FRAGILE."""
    if base_sharpe <= 0:
        return "FRAGILE"
    min_sharpe = min(sharpes)
    if min_sharpe >= 0.8 * base_sharpe:
        return "ROBUST"
    if min_sharpe < 0.5 or any(s < 0 for s in sharpes):
        return "FRAGILE"
    return "MODERATE"


def main():
    parser = argparse.ArgumentParser(description="TSMOM Parameter Sensitivity Analysis")
    parser.add_argument("--data", default="data/BTCUSDT_USDT_1h.csv")
    parser.add_argument("--symbol", default="BTC/USDT:USDT")
    parser.add_argument("--leverage", type=int, default=7)
    parser.add_argument("--pos-pct", type=float, default=0.15)
    parser.add_argument("--output", default=None, help="JSON output file")
    args = parser.parse_args()

    df = HistoricalDataManager.load_csv(args.data)
    console.print(f"[bold]Loaded {len(df)} bars ({len(df) / 24:.0f} days)[/bold]")

    total_runs = len(SENSITIVE_PARAMS) * len(SHIFTS)
    console.print(f"Running {total_runs} backtests ({len(SENSITIVE_PARAMS)} params × {len(SHIFTS)} shifts)...\n")

    # Run base case first
    base_result = run_one(df, BASE_PARAMS, args.symbol, args.leverage, args.pos_pct)
    if not base_result:
        console.print("[red]Base case failed![/red]")
        return
    base_sharpe = base_result["sharpe_ratio"]
    console.print(f"Base Sharpe: {base_sharpe:.3f} | Return: {base_result['total_return_pct']:.1%} | Trades: {base_result['total_trades']}\n")

    all_results: dict[str, list[dict]] = {}

    with Progress(console=console) as progress:
        task = progress.add_task("Sensitivity analysis...", total=total_runs)

        for display_name, (param_key, param_type) in SENSITIVE_PARAMS.items():
            base_value = BASE_PARAMS[param_key]
            param_results = []

            for shift in SHIFTS:
                shifted_value = apply_shift(base_value, shift, param_type)
                params = copy.deepcopy(BASE_PARAMS)
                params[param_key] = shifted_value

                result = run_one(df, params, args.symbol, args.leverage, args.pos_pct)

                entry = {
                    "shift": shift,
                    "value": shifted_value,
                    "sharpe": result["sharpe_ratio"] if result else 0.0,
                    "max_dd": result["max_drawdown_pct"] if result else 1.0,
                    "pf": result["profit_factor"] if result else 0.0,
                    "trades": result["total_trades"] if result else 0,
                    "return_pct": result["total_return_pct"] if result else 0.0,
                }
                param_results.append(entry)
                progress.advance(task)

            all_results[display_name] = param_results

    # Print results table
    table = Table(title="Parameter Sensitivity Analysis (±20%)", show_lines=True)
    table.add_column("Parameter", style="cyan", min_width=16)
    table.add_column("-20%", justify="center", min_width=8)
    table.add_column("-10%", justify="center", min_width=8)
    table.add_column("Base", justify="center", style="bold", min_width=8)
    table.add_column("+10%", justify="center", min_width=8)
    table.add_column("+20%", justify="center", min_width=8)
    table.add_column("Status", justify="center", min_width=10)

    for display_name, results in all_results.items():
        sharpes = [r["sharpe"] for r in results]
        status = classify_robustness(sharpes, base_sharpe)

        status_style = {
            "ROBUST": "[bold green]ROBUST[/bold green]",
            "MODERATE": "[bold yellow]MODERATE[/bold yellow]",
            "FRAGILE": "[bold red]FRAGILE[/bold red]",
        }[status]

        cells = []
        for r in results:
            s = r["sharpe"]
            if s >= 0.8 * base_sharpe:
                cells.append(f"[green]{s:.2f}[/green]")
            elif s < 0.5 or s < 0:
                cells.append(f"[red]{s:.2f}[/red]")
            else:
                cells.append(f"[yellow]{s:.2f}[/yellow]")

        base_val = BASE_PARAMS[SENSITIVE_PARAMS[display_name][0]]
        param_label = f"{display_name}\n({base_val})"

        table.add_row(param_label, *cells, status_style)

    console.print()
    console.print(table)

    # Summary
    robust_count = sum(
        1 for results in all_results.values()
        if classify_robustness([r["sharpe"] for r in results], base_sharpe) == "ROBUST"
    )
    fragile_count = sum(
        1 for results in all_results.values()
        if classify_robustness([r["sharpe"] for r in results], base_sharpe) == "FRAGILE"
    )

    console.print()
    console.print(f"[bold]Summary:[/bold] {robust_count} ROBUST / "
                  f"{len(all_results) - robust_count - fragile_count} MODERATE / "
                  f"{fragile_count} FRAGILE out of {len(all_results)} parameters")

    if fragile_count == 0:
        console.print("[bold green]✓ Strategy is robust to ±20% parameter shifts[/bold green]")
    elif fragile_count <= 2:
        console.print("[bold yellow]⚠ Some parameters are fragile — review before going live[/bold yellow]")
    else:
        console.print("[bold red]✗ Strategy is fragile — likely overfitted[/bold red]")

    # Export JSON
    if args.output:
        export = {
            "base_sharpe": base_sharpe,
            "base_return": base_result["total_return_pct"],
            "params": all_results,
            "summary": {
                "robust": robust_count,
                "moderate": len(all_results) - robust_count - fragile_count,
                "fragile": fragile_count,
            },
        }
        with open(args.output, "w") as f:
            json.dump(export, f, indent=2, default=str)
        console.print(f"\nResults exported to {args.output}")


if __name__ == "__main__":
    main()
