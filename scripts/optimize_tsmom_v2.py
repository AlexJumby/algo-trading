"""Fast 2-stage TSMOM optimizer.

Stage 1: Coarse grid with ~100 combos (find sweet spots)
Stage 2: Fine-tune around best (leverage, position size, thresholds)
"""
import itertools
import sys
import time
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


def run_one(df, params, leverage, pos_pct, max_dd=0.35):
    data_feed = HistoricalDataFeed(df.copy())
    broker = BacktestBroker(commission=0.001, slippage=0.0005)
    portfolio = PortfolioTracker(10000.0)

    strategy = STRATEGY_REGISTRY["tsmom"]()
    sc = StrategyConfig(name="tsmom", params=params)
    strategy.setup(sc)

    rc = RiskConfig(
        max_position_size_pct=pos_pct,
        max_open_positions=3,
        max_drawdown_pct=max_dd,
        default_stop_loss_pct=0.03,
        default_take_profit_pct=0.06,
    )
    rm = RiskManager(rc, portfolio, leverage=leverage)

    ac = AppConfig(
        exchange=ExchangeConfig(),
        pairs=[TradingPairConfig(symbol=SYMBOL, market_type=MarketType.FUTURES, leverage=leverage)],
        strategy=sc, risk=rc,
        backtest=BacktestConfig(initial_capital=10000.0),
    )

    engine = BacktestEngine(data_feed, strategy, rm, broker, portfolio, ac)
    return engine.run(symbol=SYMBOL, silent=True)


def build_params(roc_s, roc_m, roc_l, w_long, entry_thr, adx_thr, sl_m, trail_m, cooldown=12):
    w_rest = 1.0 - w_long
    return {
        "roc_short": roc_s,
        "roc_medium": roc_m,
        "roc_long": roc_l,
        "w_short": round(w_rest * 0.4, 2),
        "w_medium": round(w_rest * 0.6, 2),
        "w_long": w_long,
        "entry_threshold": entry_thr,
        "vol_lookback": roc_m,
        "target_vol": 0.50,
        "max_vol_scalar": 3.0,
        "min_vol_scalar": 0.2,
        "adx_period": 14,
        "adx_threshold": adx_thr,
        "trend_ema": 200 if roc_l <= 720 else 400,
        "atr_period": 14,
        "atr_sl_mult": sl_m,
        "trailing_atr_mult": trail_m,
        "cooldown_bars": cooldown,
        "lookback_bars": max(roc_l + 200, 800),
    }


def print_table(results, title, top=15):
    table = Table(title=title)
    table.add_column("#", style="dim")
    table.add_column("Return", style="green")
    table.add_column("Sharpe", style="cyan")
    table.add_column("MaxDD", style="red")
    table.add_column("WR", style="yellow")
    table.add_column("PF")
    table.add_column("Trades")
    table.add_column("AvgPnL")
    table.add_column("BestTrade", style="green")
    table.add_column("Key", style="dim", max_width=60)

    for i, r in enumerate(results[:top], 1):
        table.add_row(
            str(i),
            f"{r['total_return_pct']:+.1%}",
            f"{r['sharpe_ratio']:.3f}",
            f"{r['max_drawdown_pct']:.1%}",
            f"{r['win_rate']:.0%}",
            f"{r['profit_factor']:.2f}" if r['profit_factor'] != float('inf') else "inf",
            str(r['total_trades']),
            f"${r['avg_trade_pnl']:.1f}",
            f"${r.get('best_trade', 0):.0f}",
            r.get("key", ""),
        )
    console.print()
    console.print(table)


def main():
    df = HistoricalDataManager.load_csv(DATA_PATH)
    console.print(f"[bold]Loaded {len(df)} bars ({len(df)/24:.0f} days)[/bold]")
    t0 = time.time()

    # ================================================================
    # STAGE 1: Coarse grid — find best lookback / weight / threshold
    # ================================================================
    console.print("\n[bold cyan]Stage 1: Coarse grid (momentum structure)[/bold cyan]")

    stage1_configs = [
        # (roc_s, roc_m, roc_l, w_long, entry_thr, adx_thr, sl_m, trail_m, lev, pos)
        # Vary the core momentum structure with fixed leverage=5, pos=0.15
        (24, 168, 720, 0.4, 0.01, 20, 2.0, 2.5, 5, 0.15),
        (24, 168, 720, 0.5, 0.01, 20, 2.0, 3.0, 5, 0.15),
        (24, 168, 720, 0.6, 0.01, 20, 2.0, 3.0, 5, 0.15),
        (24, 168, 1440, 0.4, 0.01, 20, 2.0, 3.0, 5, 0.15),
        (24, 168, 1440, 0.5, 0.01, 20, 2.0, 3.0, 5, 0.15),
        (24, 168, 1440, 0.5, 0.02, 20, 2.0, 3.0, 5, 0.15),
        (24, 168, 1440, 0.6, 0.01, 20, 2.0, 3.0, 5, 0.15),
        (24, 168, 1440, 0.6, 0.02, 20, 3.0, 3.5, 5, 0.15),
        (24, 336, 720, 0.4, 0.01, 20, 2.0, 3.0, 5, 0.15),
        (24, 336, 720, 0.5, 0.01, 20, 2.0, 3.0, 5, 0.15),
        (24, 336, 1440, 0.4, 0.01, 20, 2.0, 3.0, 5, 0.15),
        (24, 336, 1440, 0.5, 0.01, 20, 2.0, 3.0, 5, 0.15),
        (24, 336, 1440, 0.5, 0.02, 22, 3.0, 3.5, 5, 0.15),
        (24, 336, 1440, 0.6, 0.02, 22, 3.0, 3.5, 5, 0.15),
        (48, 168, 720, 0.4, 0.01, 20, 2.0, 3.0, 5, 0.15),
        (48, 168, 720, 0.5, 0.02, 20, 2.5, 3.0, 5, 0.15),
        (48, 168, 1440, 0.4, 0.01, 20, 2.0, 3.0, 5, 0.15),
        (48, 168, 1440, 0.5, 0.02, 22, 3.0, 3.5, 5, 0.15),
        (48, 336, 720, 0.4, 0.01, 20, 2.0, 3.0, 5, 0.15),
        (48, 336, 720, 0.5, 0.02, 20, 2.5, 3.0, 5, 0.15),
        (48, 336, 1440, 0.4, 0.01, 20, 2.0, 3.0, 5, 0.15),
        (48, 336, 1440, 0.5, 0.02, 22, 3.0, 3.5, 5, 0.20),
        (48, 336, 1440, 0.6, 0.02, 22, 3.0, 3.5, 5, 0.20),
        # Original winner from quick test
        (48, 336, 1440, 0.5, 0.02, 22, 3.0, 3.5, 5, 0.15),
        # Faster momentum
        (12, 72, 336, 0.35, 0.008, 18, 2.0, 2.5, 5, 0.15),
        (12, 72, 720, 0.4, 0.01, 20, 2.0, 3.0, 5, 0.15),
        (24, 72, 336, 0.35, 0.01, 18, 2.0, 2.5, 5, 0.15),
        (24, 72, 720, 0.4, 0.01, 20, 2.0, 3.0, 5, 0.15),
    ]

    results1 = []
    for i, cfg in enumerate(stage1_configs):
        roc_s, roc_m, roc_l, wl, ethr, adx, slm, trm, lev, pos = cfg
        params = build_params(roc_s, roc_m, roc_l, wl, ethr, adx, slm, trm)
        key = f"roc={roc_s}/{roc_m}/{roc_l} wL={wl} thr={ethr} adx={adx} sl={slm} trail={trm}"
        try:
            r = run_one(df, params, lev, pos)
            if r and r["total_trades"] >= 5:
                r["key"] = key
                r["cfg"] = cfg
                results1.append(r)
                console.print(f"  [{i+1}/{len(stage1_configs)}] {key}: {r['total_return_pct']:+.1%} Sharpe={r['sharpe_ratio']:.3f}")
        except Exception as e:
            console.print(f"  [{i+1}/{len(stage1_configs)}] [red]{key}: {e}[/red]")

    # Sort by composite score
    for r in results1:
        r["score"] = r["sharpe_ratio"] * (r["total_trades"] ** 0.2) * (1 + r["total_return_pct"])
    results1.sort(key=lambda r: r["score"], reverse=True)
    print_table(results1, "Stage 1: Coarse Grid Results")

    if not results1:
        console.print("[red]No valid stage 1 results[/red]")
        return

    # ================================================================
    # STAGE 2: Fine-tune best 3 configs with leverage/position/stops
    # ================================================================
    console.print("\n[bold cyan]Stage 2: Fine-tune leverage, position size, stops[/bold cyan]")

    top3 = results1[:3]
    results2 = []

    for base in top3:
        cfg = base["cfg"]
        roc_s, roc_m, roc_l, wl, ethr, adx_base, slm_base, trm_base, _, _ = cfg

        # Fine-tune grid around the winner
        fine_grid = list(itertools.product(
            [max(0, adx_base - 3), adx_base, adx_base + 3],   # ADX threshold
            [max(1.5, slm_base - 0.5), slm_base, slm_base + 0.5],   # SL mult
            [max(2.0, trm_base - 0.5), trm_base, trm_base + 0.5],   # Trail mult
            [3, 5, 7, 10],                                     # Leverage
            [0.10, 0.15, 0.20, 0.25],                          # Position size
        ))

        for adx_thr, sl_m, tr_m, lev, pos in fine_grid:
            params = build_params(roc_s, roc_m, roc_l, wl, ethr, adx_thr, sl_m, tr_m)
            key = f"roc={roc_s}/{roc_m}/{roc_l} wL={wl} adx={adx_thr} sl={sl_m} trail={tr_m} lev={lev} pos={pos}"
            try:
                r = run_one(df, params, lev, pos)
                if r and r["total_trades"] >= 5:
                    r["key"] = key
                    r["leverage"] = lev
                    r["pos_pct"] = pos
                    r["params"] = params
                    results2.append(r)
            except Exception:
                pass

        console.print(f"  Fine-tuned roc={roc_s}/{roc_m}/{roc_l}: {len(fine_grid)} combos done")

    # Sort by composite score
    for r in results2:
        r["score"] = r["sharpe_ratio"] * (r["total_trades"] ** 0.2) * (1 + r["total_return_pct"])
    results2.sort(key=lambda r: r["score"], reverse=True)
    print_table(results2, "Stage 2: Fine-Tuned Results", top=20)

    # ================================================================
    # FINAL: Print best configuration
    # ================================================================
    if results2:
        best = results2[0]
        elapsed = time.time() - t0
        console.print()
        console.rule("[bold green]BEST TSMOM CONFIGURATION[/bold green]")
        console.print()
        console.print(f"[bold green]Total Return: {best['total_return_pct']:+.1%}[/bold green]")
        console.print(f"[bold green]Annualized:   ~{best['total_return_pct']/2:+.1%}/year[/bold green]")
        console.print(f"Sharpe: {best['sharpe_ratio']:.3f}")
        console.print(f"Sortino: {best['sortino_ratio']:.3f}")
        console.print(f"Max DD: {best['max_drawdown_pct']:.1%}")
        console.print(f"Win Rate: {best['win_rate']:.0%}")
        console.print(f"Profit Factor: {best['profit_factor']:.2f}")
        console.print(f"Trades: {best['total_trades']}")
        console.print(f"Avg Trade: ${best['avg_trade_pnl']:.2f}")
        console.print(f"Best Trade: ${best['best_trade']:.2f}")
        console.print(f"Worst Trade: ${best['worst_trade']:.2f}")
        console.print()
        console.print("strategy:")
        console.print("  name: tsmom")
        console.print("  params:")
        for k, v in best["params"].items():
            console.print(f"    {k}: {v}")
        console.print()
        console.print(f"leverage: {best['leverage']}")
        console.print(f"position_pct: {best['pos_pct']}")
        console.print(f"\nOptimization took {elapsed:.0f}s")


if __name__ == "__main__":
    main()
