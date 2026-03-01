"""Grid optimizer for TSMOM slow configuration.

Focus: optimize the winning slow-lookback TSMOM formula.
"""
import itertools
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

DATA_PATH = "data/BTCUSDT_USDT_1h.csv"
SYMBOL = "BTC/USDT:USDT"


def run_one(df, params, leverage, pos_pct):
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
        pairs=[TradingPairConfig(symbol=SYMBOL, market_type=MarketType.FUTURES, leverage=leverage)],
        strategy=strategy_config,
        risk=risk_config,
        backtest=BacktestConfig(initial_capital=10000.0),
    )

    engine = BacktestEngine(data_feed, strategy, risk_mgr, broker, portfolio, app_config)
    return engine.run(symbol=SYMBOL, silent=True)


def main():
    df = HistoricalDataManager.load_csv(DATA_PATH)
    console.print(f"[bold]Loaded {len(df)} bars ({len(df)/24:.0f} days)[/bold]")

    # --- Grid: focused on slow lookback winner (reduced for speed) ---
    grid = {
        "roc_short":        [24, 48],
        "roc_medium":       [168, 336],
        "roc_long":         [720, 1440],
        "w_long":           [0.4, 0.5, 0.6],
        "entry_threshold":  [0.01, 0.02],
        "adx_threshold":    [18, 22],
        "atr_sl_mult":      [2.0, 3.0],
        "trailing_mult":    [2.5, 3.5],
    }

    leverage_options = [3, 5, 7]
    pos_pct_options = [0.15, 0.20]

    keys = list(grid.keys())
    values = list(grid.values())
    combos = list(itertools.product(*values))
    total = len(combos) * len(leverage_options) * len(pos_pct_options)

    console.print(f"Testing {total} combinations...")

    results = []
    with Progress(console=console) as progress:
        task = progress.add_task("Optimizing TSMOM...", total=total)

        for leverage in leverage_options:
            for pos_pct in pos_pct_options:
                for combo in combos:
                    p = dict(zip(keys, combo))

                    # Build full params
                    w_long = p["w_long"]
                    w_rest = 1.0 - w_long
                    params = {
                        "roc_short": p["roc_short"],
                        "roc_medium": p["roc_medium"],
                        "roc_long": p["roc_long"],
                        "w_short": round(w_rest * 0.4, 2),
                        "w_medium": round(w_rest * 0.6, 2),
                        "w_long": w_long,
                        "entry_threshold": p["entry_threshold"],
                        "vol_lookback": p["roc_medium"],  # Use medium period for vol
                        "target_vol": 0.50,
                        "max_vol_scalar": 3.0,
                        "min_vol_scalar": 0.2,
                        "adx_period": 14,
                        "adx_threshold": p["adx_threshold"],
                        "trend_ema": 200 if p["roc_long"] <= 720 else 400,
                        "atr_period": 14,
                        "atr_sl_mult": p["atr_sl_mult"],
                        "trailing_atr_mult": p["trailing_mult"],
                        "cooldown_bars": 12 if p["roc_short"] <= 48 else 24,
                        "lookback_bars": max(p["roc_long"] + 200, 800),
                    }

                    try:
                        r = run_one(df, params, leverage, pos_pct)
                        if r and r["total_trades"] >= 10:
                            results.append({
                                "params": params,
                                "leverage": leverage,
                                "pos_pct": pos_pct,
                                "roc": f"{p['roc_short']}/{p['roc_medium']}/{p['roc_long']}",
                                "grid": p,
                                **r,
                            })
                    except Exception:
                        pass
                    progress.advance(task)

    if not results:
        console.print("[red]No valid results[/red]")
        return

    # Sort by composite score: Sharpe * sqrt(trades) penalizes low-trade flukes
    for r in results:
        r["score"] = r["sharpe_ratio"] * (r["total_trades"] ** 0.3) * (1 + r["total_return_pct"])

    results.sort(key=lambda r: r["score"], reverse=True)

    table = Table(title="Top 20 TSMOM Configurations")
    table.add_column("#", style="dim")
    table.add_column("Return", style="green")
    table.add_column("Sharpe", style="cyan")
    table.add_column("MaxDD", style="red")
    table.add_column("WR", style="yellow")
    table.add_column("PF")
    table.add_column("Trades")
    table.add_column("AvgPnL")
    table.add_column("Key", style="dim", max_width=65)

    for i, r in enumerate(results[:20], 1):
        g = r["grid"]
        key = (
            f"roc={r['roc']} wL={g['w_long']} thr={g['entry_threshold']} "
            f"adx={g['adx_threshold']} sl={g['atr_sl_mult']} trail={g['trailing_mult']} "
            f"lev={r['leverage']} pos={r['pos_pct']}"
        )
        table.add_row(
            str(i),
            f"{r['total_return_pct']:+.1%}",
            f"{r['sharpe_ratio']:.3f}",
            f"{r['max_drawdown_pct']:.1%}",
            f"{r['win_rate']:.0%}",
            f"{r['profit_factor']:.2f}" if r['profit_factor'] != float('inf') else "inf",
            str(r['total_trades']),
            f"${r['avg_trade_pnl']:.1f}",
            key,
        )

    console.print()
    console.print(table)

    # Print best params
    best = results[0]
    console.print()
    console.rule("[bold green]Best Configuration[/bold green]")
    console.print()
    console.print("strategy:")
    console.print("  name: tsmom")
    console.print("  params:")
    for k, v in best["params"].items():
        console.print(f"    {k}: {v}")
    console.print()
    console.print(f"leverage: {best['leverage']}")
    console.print(f"position_pct: {best['pos_pct']}")
    console.print()
    console.print(f"[bold green]Return: {best['total_return_pct']:+.1%}[/bold green]")
    console.print(f"Sharpe: {best['sharpe_ratio']:.3f}")
    console.print(f"Max DD: {best['max_drawdown_pct']:.1%}")
    console.print(f"Trades: {best['total_trades']}")
    console.print(f"Best trade: ${best['best_trade']:.2f}")
    console.print(f"Avg Win: ${best['avg_win']:.2f}")
    console.print(f"Avg Loss: ${best['avg_loss']:.2f}")


if __name__ == "__main__":
    main()
