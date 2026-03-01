"""Quick fine-tune: test top 3 TSMOM configs with different leverage/position combos."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
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

DATA_PATH = "data/BTCUSDT_USDT_1h.csv"
SYMBOL = "BTC/USDT:USDT"

import logging
logging.disable(logging.WARNING)


def run_one(df, params, leverage, pos_pct, max_dd=0.50):
    data_feed = HistoricalDataFeed(df.copy())
    broker = BacktestBroker(commission=0.001, slippage=0.0005)
    portfolio = PortfolioTracker(10000.0)
    strategy = STRATEGY_REGISTRY["tsmom"]()
    sc = StrategyConfig(name="tsmom", params=params)
    strategy.setup(sc)
    rc = RiskConfig(
        max_position_size_pct=pos_pct, max_open_positions=3,
        max_drawdown_pct=max_dd, default_stop_loss_pct=0.03,
        default_take_profit_pct=0.06,
    )
    rm = RiskManager(rc, portfolio, leverage=leverage)
    ac = AppConfig(
        exchange=ExchangeConfig(),
        pairs=[TradingPairConfig(symbol=SYMBOL, market_type=MarketType.FUTURES, leverage=leverage)],
        strategy=sc, risk=rc, backtest=BacktestConfig(initial_capital=10000.0),
    )
    engine = BacktestEngine(data_feed, strategy, rm, broker, portfolio, ac)
    return engine.run(symbol=SYMBOL, silent=True)


# Top 3 base configs from Stage 1
BASE_CONFIGS = {
    "fast_12/72/336": {
        "roc_short": 12, "roc_medium": 72, "roc_long": 336,
        "w_short": 0.26, "w_medium": 0.39, "w_long": 0.35,
        "entry_threshold": 0.008,
        "vol_lookback": 72, "target_vol": 0.50,
        "max_vol_scalar": 3.0, "min_vol_scalar": 0.2,
        "adx_period": 14, "adx_threshold": 18,
        "trend_ema": 200,
        "atr_period": 14, "atr_sl_mult": 2.0,
        "trailing_atr_mult": 2.5,
        "cooldown_bars": 8,
        "lookback_bars": 536,
    },
    "slow_48/336/1440": {
        "roc_short": 48, "roc_medium": 336, "roc_long": 1440,
        "w_short": 0.16, "w_medium": 0.24, "w_long": 0.60,
        "entry_threshold": 0.02,
        "vol_lookback": 336, "target_vol": 0.50,
        "max_vol_scalar": 3.0, "min_vol_scalar": 0.2,
        "adx_period": 14, "adx_threshold": 22,
        "trend_ema": 400,
        "atr_period": 14, "atr_sl_mult": 3.0,
        "trailing_atr_mult": 3.5,
        "cooldown_bars": 24,
        "lookback_bars": 1640,
    },
    "med_24/336/1440": {
        "roc_short": 24, "roc_medium": 336, "roc_long": 1440,
        "w_short": 0.16, "w_medium": 0.24, "w_long": 0.60,
        "entry_threshold": 0.02,
        "vol_lookback": 336, "target_vol": 0.50,
        "max_vol_scalar": 3.0, "min_vol_scalar": 0.2,
        "adx_period": 14, "adx_threshold": 22,
        "trend_ema": 400,
        "atr_period": 14, "atr_sl_mult": 3.0,
        "trailing_atr_mult": 3.5,
        "cooldown_bars": 12,
        "lookback_bars": 1640,
    },
}

# Leverage / position size combos to test
LEVERAGE_POS = [
    (3, 0.10), (3, 0.15), (3, 0.20),
    (5, 0.10), (5, 0.15), (5, 0.20),
    (7, 0.10), (7, 0.15),
    (10, 0.08), (10, 0.10),
]


def main():
    df = HistoricalDataManager.load_csv(DATA_PATH)
    console.print(f"[bold]Loaded {len(df)} bars ({len(df)/24:.0f} days)[/bold]")

    all_results = []

    for name, params in BASE_CONFIGS.items():
        console.print(f"\n[cyan]Testing {name}...[/cyan]")
        for lev, pos in LEVERAGE_POS:
            try:
                r = run_one(df, params, lev, pos)
                if r and r["total_trades"] >= 5:
                    label = f"{name} lev{lev} pos{pos}"
                    all_results.append({
                        "label": label,
                        "name": name,
                        "leverage": lev,
                        "pos_pct": pos,
                        "params": params,
                        **r,
                    })
                    ret = r["total_return_pct"]
                    console.print(f"  lev={lev} pos={pos}: {ret:+.1%} Sharpe={r['sharpe_ratio']:.3f} DD={r['max_drawdown_pct']:.1%}")
            except Exception as e:
                console.print(f"  lev={lev} pos={pos}: [red]ERR {e}[/red]")

    # Sort by risk-adjusted score
    for r in all_results:
        # Penalize high drawdown, reward Sharpe and returns
        dd_penalty = max(0, r["max_drawdown_pct"] - 0.25) * 2
        r["score"] = r["sharpe_ratio"] * (1 + r["total_return_pct"]) * (1 - dd_penalty)

    all_results.sort(key=lambda r: r["score"], reverse=True)

    # Print results
    table = Table(title="TSMOM Fine-Tune Results (Top 20)")
    table.add_column("#", style="dim")
    table.add_column("Config", style="cyan", max_width=40)
    table.add_column("Return", style="green")
    table.add_column("Annual", style="green")
    table.add_column("Sharpe", style="yellow")
    table.add_column("Sortino", style="yellow")
    table.add_column("MaxDD", style="red")
    table.add_column("WR")
    table.add_column("PF")
    table.add_column("Trades")
    table.add_column("AvgPnL")

    for i, r in enumerate(all_results[:20], 1):
        annual = r["total_return_pct"] / 2  # ~2 years of data
        table.add_row(
            str(i), r["label"],
            f"{r['total_return_pct']:+.1%}",
            f"~{annual:+.0%}/yr",
            f"{r['sharpe_ratio']:.3f}",
            f"{r['sortino_ratio']:.3f}",
            f"{r['max_drawdown_pct']:.1%}",
            f"{r['win_rate']:.0%}",
            f"{r['profit_factor']:.2f}" if r['profit_factor'] != float('inf') else "inf",
            str(r['total_trades']),
            f"${r['avg_trade_pnl']:.1f}",
        )

    console.print()
    console.print(table)

    # Best config
    if all_results:
        best = all_results[0]
        console.print()
        console.rule("[bold green]BEST CONFIG[/bold green]")
        console.print(f"[bold]{best['label']}[/bold]")
        console.print(f"Return: {best['total_return_pct']:+.1%} (~{best['total_return_pct']/2:+.0%}/year)")
        console.print(f"Sharpe: {best['sharpe_ratio']:.3f}")
        console.print(f"MaxDD: {best['max_drawdown_pct']:.1%}")
        console.print(f"Best trade: ${best['best_trade']:.2f}")
        console.print(f"Worst trade: ${best['worst_trade']:.2f}")
        console.print()
        console.print("[bold]YAML config:[/bold]")
        console.print("strategy:")
        console.print("  name: tsmom")
        console.print("  params:")
        for k, v in best["params"].items():
            console.print(f"    {k}: {v}")
        console.print(f"\nleverage: {best['leverage']}")
        console.print(f"max_position_size_pct: {best['pos_pct']}")

        # Also show safest high-return config (DD < 20%)
        safe = [r for r in all_results if r["max_drawdown_pct"] < 0.20 and r["total_return_pct"] > 0.30]
        if safe:
            safe.sort(key=lambda r: r["total_return_pct"], reverse=True)
            s = safe[0]
            console.print()
            console.rule("[bold blue]SAFEST HIGH-RETURN CONFIG (DD < 20%)[/bold blue]")
            console.print(f"[bold]{s['label']}[/bold]")
            console.print(f"Return: {s['total_return_pct']:+.1%} (~{s['total_return_pct']/2:+.0%}/year)")
            console.print(f"Sharpe: {s['sharpe_ratio']:.3f}, MaxDD: {s['max_drawdown_pct']:.1%}")


if __name__ == "__main__":
    main()
