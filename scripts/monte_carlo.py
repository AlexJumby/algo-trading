"""Monte Carlo Simulation for TSMOM Strategy.

Takes closed trades from a full backtest, reshuffles trade order N times,
and computes confidence intervals for return and max drawdown.

This tests whether the strategy's results are robust to trade ordering
or depend on a lucky sequence of wins/losses.

Usage:
    python -m scripts.monte_carlo
    python -m scripts.monte_carlo --data data/BTCUSDT_USDT_1h.csv --simulations 10000
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

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


def build_equity_curve(pnls: list[float], initial_capital: float) -> list[float]:
    """Build equity curve from sequential trade PnLs."""
    equity = [initial_capital]
    for pnl in pnls:
        equity.append(equity[-1] + pnl)
    return equity


def compute_max_drawdown(equity: list[float]) -> float:
    """Compute max peak-to-trough drawdown from equity curve."""
    if not equity:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for eq in equity:
        peak = max(peak, eq)
        if peak > 0:
            dd = (peak - eq) / peak
            max_dd = max(max_dd, dd)
    return max_dd


def run_monte_carlo(
    pnls: list[float],
    initial_capital: float,
    n_simulations: int = 10_000,
    seed: int = 42,
) -> dict:
    """Run Monte Carlo simulation by reshuffling trade PnLs.

    Returns dict with percentile stats for return and max drawdown.
    """
    rng = np.random.default_rng(seed)
    pnls_arr = np.array(pnls)

    returns = np.empty(n_simulations)
    max_dds = np.empty(n_simulations)

    for i in range(n_simulations):
        shuffled = rng.permutation(pnls_arr)
        equity = build_equity_curve(shuffled.tolist(), initial_capital)

        final_eq = equity[-1]
        returns[i] = (final_eq - initial_capital) / initial_capital
        max_dds[i] = compute_max_drawdown(equity)

    percentiles = [5, 25, 50, 75, 95]

    return {
        "n_simulations": n_simulations,
        "n_trades": len(pnls),
        "return_percentiles": {
            p: float(np.percentile(returns, p)) for p in percentiles
        },
        "max_dd_percentiles": {
            p: float(np.percentile(max_dds, p)) for p in percentiles
        },
        "prob_negative_return": float(np.mean(returns < 0)),
        "prob_dd_over_25": float(np.mean(max_dds > 0.25)),
        "prob_dd_over_30": float(np.mean(max_dds > 0.30)),
        "mean_return": float(np.mean(returns)),
        "std_return": float(np.std(returns)),
        "mean_max_dd": float(np.mean(max_dds)),
    }


def main():
    parser = argparse.ArgumentParser(description="Monte Carlo Simulation")
    parser.add_argument("--data", default="data/BTCUSDT_USDT_1h.csv")
    parser.add_argument("--symbol", default="BTC/USDT:USDT")
    parser.add_argument("--leverage", type=int, default=7)
    parser.add_argument("--pos-pct", type=float, default=0.15)
    parser.add_argument("--simulations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    df = HistoricalDataManager.load_csv(args.data)
    console.print(f"[bold]Loaded {len(df)} bars ({len(df) / 24:.0f} days)[/bold]")

    # ---- Run full backtest to collect trades ----
    console.print("[dim]Running full backtest to collect trades...[/dim]")

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

    if not results or results["total_trades"] < 10:
        console.print("[red]Not enough trades for Monte Carlo simulation[/red]")
        return

    pnls = [t["pnl"] for t in portfolio.closed_trades]
    actual_return = results["total_return_pct"]
    actual_sharpe = results["sharpe_ratio"]
    actual_dd = results["max_drawdown_pct"]

    console.print(
        f"Actual: Return={actual_return:.1%} | Sharpe={actual_sharpe:.3f} | "
        f"MaxDD={actual_dd:.1%} | Trades={len(pnls)}\n"
    )

    # ---- Run Monte Carlo ----
    console.print(
        f"[bold]Running {args.simulations:,} Monte Carlo simulations...[/bold]"
    )
    mc = run_monte_carlo(pnls, 10000.0, args.simulations, args.seed)

    # ---- Results table ----
    table = Table(
        title="Monte Carlo — Return & Drawdown Distribution", show_lines=True,
    )
    table.add_column("Percentile", justify="center", style="cyan")
    table.add_column("Total Return", justify="center")
    table.add_column("Max Drawdown", justify="center")

    for p in [5, 25, 50, 75, 95]:
        ret = mc["return_percentiles"][p]
        dd = mc["max_dd_percentiles"][p]
        ret_style = "green" if ret > 0 else "red"
        table.add_row(
            f"{p}th",
            f"[{ret_style}]{ret:.1%}[/{ret_style}]",
            f"{dd:.1%}",
        )

    console.print()
    console.print(table)

    # ---- Summary ----
    console.print()
    console.print("[bold]Summary:[/bold]")
    console.print(f"  Actual Return:           {actual_return:.1%}")
    console.print(
        f"  Mean MC Return:          "
        f"{mc['mean_return']:.1%} ± {mc['std_return']:.1%}"
    )
    console.print(
        f"  95% CI Return:           "
        f"[{mc['return_percentiles'][5]:.1%}, "
        f"{mc['return_percentiles'][95]:.1%}]"
    )
    console.print(
        f"  Prob(negative return):   {mc['prob_negative_return']:.1%}"
    )
    console.print(f"  Prob(MaxDD > 25%):       {mc['prob_dd_over_25']:.1%}")
    console.print(f"  Prob(MaxDD > 30%):       {mc['prob_dd_over_30']:.1%}")

    # ---- Verdict ----
    console.print()
    if mc["prob_negative_return"] < 0.05 and mc["return_percentiles"][5] > 0:
        console.print(
            "[bold green]✓ Monte Carlo: 95%+ confidence of positive returns — "
            "edge is real[/bold green]"
        )
    elif mc["prob_negative_return"] < 0.20:
        console.print(
            "[bold yellow]⚠ Monte Carlo: some risk of negative returns "
            "with unlucky trade ordering[/bold yellow]"
        )
    else:
        console.print(
            "[bold red]✗ Monte Carlo: high risk of negative returns — "
            "edge may be weak[/bold red]"
        )

    # ---- Export ----
    if args.output:
        export = {
            "actual": {
                "return_pct": actual_return,
                "sharpe": actual_sharpe,
                "max_dd": actual_dd,
                "trades": len(pnls),
            },
            "monte_carlo": mc,
        }
        with open(args.output, "w") as f:
            json.dump(export, f, indent=2, default=str)
        console.print(f"\nResults exported to {args.output}")


if __name__ == "__main__":
    main()
