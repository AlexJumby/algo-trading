"""Grid search parameter optimizer for backtesting.

Usage:
    python scripts/optimize.py --data data/BTCUSDT_mainnet_1h.csv
"""

import argparse
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.table import Table

from src.core.config import AppConfig, BacktestConfig, RiskConfig, StrategyConfig
from src.core.config import ExchangeConfig, TradingPairConfig
from src.core.enums import MarketType
from src.data.feed import HistoricalDataFeed
from src.data.historical import HistoricalDataManager
from src.engine.backtest_engine import BacktestEngine
from src.execution.backtest_broker import BacktestBroker
from src.portfolio.metrics import PerformanceMetrics
from src.portfolio.tracker import PortfolioTracker
from src.risk.manager import RiskManager
from src.strategies.momentum import STRATEGY_REGISTRY

console = Console()


def run_single_backtest(df, strategy_name, params, risk_config, backtest_config, symbol):
    """Run a single backtest with given params. Returns metrics dict."""
    data_feed = HistoricalDataFeed(df.copy())
    broker = BacktestBroker(
        commission=backtest_config.commission_pct,
        slippage=backtest_config.slippage_pct,
    )
    portfolio = PortfolioTracker(backtest_config.initial_capital)

    strategy_cls = STRATEGY_REGISTRY.get(strategy_name)
    if not strategy_cls:
        return None

    strategy = strategy_cls()
    strategy_config = StrategyConfig(name=strategy_name, params=params)
    strategy.setup(strategy_config)

    risk_mgr = RiskManager(risk_config, portfolio)

    config = AppConfig(
        exchange=ExchangeConfig(),
        pairs=[TradingPairConfig(symbol=symbol, market_type=MarketType.FUTURES)],
        strategy=strategy_config,
        risk=risk_config,
        backtest=backtest_config,
    )

    engine = BacktestEngine(data_feed, strategy, risk_mgr, broker, portfolio, config)
    engine.run(symbol=symbol, silent=True)

    metrics = PerformanceMetrics(portfolio)
    return metrics.compute_all()


def main():
    parser = argparse.ArgumentParser(description="Optimize strategy parameters")
    parser.add_argument("--data", required=True, help="CSV data file")
    parser.add_argument("--symbol", default="BTC/USDT:USDT")
    parser.add_argument("--strategy", default="momentum_v2", choices=list(STRATEGY_REGISTRY.keys()))
    parser.add_argument("--capital", type=float, default=10000.0)
    parser.add_argument("--top", type=int, default=15, help="Show top N results")
    args = parser.parse_args()

    df = HistoricalDataManager.load_csv(args.data)
    console.print(f"Loaded {len(df)} bars ({len(df)/24:.0f} days)")

    backtest_config = BacktestConfig(
        initial_capital=args.capital,
        commission_pct=0.001,
        slippage_pct=0.0005,
    )

    # ---- Parameter grid ----
    if args.strategy == "momentum_v2":
        param_grid = {
            "fast_ema": [9, 12],
            "slow_ema": [21, 26],
            "trend_ema": [100, 200],
            "rsi_period": [14],
            "rsi_overbought": [65, 70],
            "rsi_oversold": [30, 35],
            "atr_period": [14],
            "atr_sl_mult": [1.5, 2.0, 2.5],
            "atr_tp_mult": [2.0, 3.0, 4.0],
            "volume_period": [20],
            "require_volume": [True, False],
            "lookback_bars": [200],
        }
    else:  # momentum v1
        param_grid = {
            "fast_ema": [8, 12, 15],
            "slow_ema": [21, 26, 30],
            "rsi_period": [14],
            "rsi_overbought": [65, 70, 75],
            "rsi_oversold": [25, 30, 35],
            "lookback_bars": [100],
        }

    risk_configs = [
        RiskConfig(
            max_position_size_pct=pct,
            max_open_positions=3,
            max_drawdown_pct=0.25,
            default_stop_loss_pct=0.02,
            default_take_profit_pct=0.04,
        )
        for pct in [0.03, 0.05, 0.08]
    ]

    # Generate all combinations
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combos = list(itertools.product(*values))
    total = len(combos) * len(risk_configs)

    console.print(f"Testing {total} parameter combinations...")
    console.print()

    results = []
    from rich.progress import Progress
    with Progress(console=console) as progress:
        task = progress.add_task("Optimizing...", total=total)

        for risk_config in risk_configs:
            for combo in combos:
                params = dict(zip(keys, combo))
                try:
                    metrics = run_single_backtest(
                        df, args.strategy, params, risk_config, backtest_config, args.symbol
                    )
                    if metrics and metrics["total_trades"] >= 3:
                        results.append({
                            "params": params,
                            "risk_pct": risk_config.max_position_size_pct,
                            **metrics,
                        })
                except Exception:
                    pass
                progress.advance(task)

    if not results:
        console.print("[red]No valid results found[/red]")
        return

    # Sort by Sharpe ratio (primary), then by total return
    results.sort(key=lambda r: (r["sharpe_ratio"], r["total_return_pct"]), reverse=True)

    # Show top results
    table = Table(title=f"Top {args.top} Parameter Combinations — {args.strategy}")
    table.add_column("#", style="dim")
    table.add_column("Return", style="green")
    table.add_column("Sharpe", style="cyan")
    table.add_column("MaxDD", style="red")
    table.add_column("WinRate", style="yellow")
    table.add_column("Trades")
    table.add_column("PF")
    table.add_column("Key Params", style="dim")

    for i, r in enumerate(results[:args.top], 1):
        p = r["params"]
        if args.strategy == "momentum_v2":
            key = f"ema={p['fast_ema']}/{p['slow_ema']} trend={p['trend_ema']} rsi={p['rsi_oversold']}-{p['rsi_overbought']} atr_sl={p['atr_sl_mult']} atr_tp={p['atr_tp_mult']} vol={p['require_volume']} risk={r['risk_pct']}"
        else:
            key = f"ema={p['fast_ema']}/{p['slow_ema']} rsi={p['rsi_oversold']}-{p['rsi_overbought']} risk={r['risk_pct']}"

        table.add_row(
            str(i),
            f"{r['total_return_pct']:+.1%}",
            f"{r['sharpe_ratio']:.2f}",
            f"{r['max_drawdown_pct']:.1%}",
            f"{r['win_rate']:.0%}",
            str(r["total_trades"]),
            f"{r['profit_factor']:.2f}" if r['profit_factor'] != float('inf') else "inf",
            key,
        )

    console.print()
    console.print(table)

    # Print best params as YAML
    best = results[0]
    console.print()
    console.rule("[bold green]Best Parameters[/bold green]")
    console.print()
    console.print("strategy:")
    console.print(f"  name: {args.strategy}")
    console.print("  params:")
    for k, v in best["params"].items():
        console.print(f"    {k}: {v}")
    console.print()
    console.print("risk:")
    console.print(f"  max_position_size_pct: {best['risk_pct']}")
    console.print()


if __name__ == "__main__":
    main()
