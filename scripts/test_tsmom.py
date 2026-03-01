"""Quick test of TSMOM strategy with multiple configurations."""
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

# Configs to test
CONFIGS = [
    # === Baseline: conservative ===
    {
        "label": "TSMOM base 24/168/720 adx20 trail2.0 lev3",
        "strategy_params": {
            "roc_short": 24, "roc_medium": 168, "roc_long": 720,
            "w_short": 0.2, "w_medium": 0.4, "w_long": 0.4,
            "entry_threshold": 0.01,
            "vol_lookback": 168, "target_vol": 0.40,
            "max_vol_scalar": 3.0, "min_vol_scalar": 0.2,
            "adx_period": 14, "adx_threshold": 20,
            "trend_ema": 200,
            "atr_period": 14, "atr_sl_mult": 2.0,
            "trailing_atr_mult": 2.5,
            "cooldown_bars": 12,
            "lookback_bars": 800,
        },
        "leverage": 3,
        "position_pct": 0.15,
    },
    # === Higher vol target + more leverage ===
    {
        "label": "TSMOM aggr 24/168/720 adx20 trail2.5 lev5",
        "strategy_params": {
            "roc_short": 24, "roc_medium": 168, "roc_long": 720,
            "w_short": 0.2, "w_medium": 0.4, "w_long": 0.4,
            "entry_threshold": 0.01,
            "vol_lookback": 168, "target_vol": 0.50,
            "max_vol_scalar": 3.0, "min_vol_scalar": 0.2,
            "adx_period": 14, "adx_threshold": 20,
            "trend_ema": 200,
            "atr_period": 14, "atr_sl_mult": 2.5,
            "trailing_atr_mult": 3.0,
            "cooldown_bars": 12,
            "lookback_bars": 800,
        },
        "leverage": 5,
        "position_pct": 0.15,
    },
    # === Shorter lookbacks — more responsive ===
    {
        "label": "TSMOM fast 12/72/336 adx18 trail2.0 lev3",
        "strategy_params": {
            "roc_short": 12, "roc_medium": 72, "roc_long": 336,
            "w_short": 0.3, "w_medium": 0.35, "w_long": 0.35,
            "entry_threshold": 0.008,
            "vol_lookback": 72, "target_vol": 0.40,
            "max_vol_scalar": 3.0, "min_vol_scalar": 0.2,
            "adx_period": 14, "adx_threshold": 18,
            "trend_ema": 100,
            "atr_period": 14, "atr_sl_mult": 2.0,
            "trailing_atr_mult": 2.5,
            "cooldown_bars": 8,
            "lookback_bars": 400,
        },
        "leverage": 3,
        "position_pct": 0.12,
    },
    # === Long-term trend: bigger lookbacks ===
    {
        "label": "TSMOM slow 48/336/1440 adx22 trail3.0 lev5",
        "strategy_params": {
            "roc_short": 48, "roc_medium": 336, "roc_long": 1440,
            "w_short": 0.15, "w_medium": 0.35, "w_long": 0.50,
            "entry_threshold": 0.02,
            "vol_lookback": 336, "target_vol": 0.50,
            "max_vol_scalar": 3.0, "min_vol_scalar": 0.2,
            "adx_period": 14, "adx_threshold": 22,
            "trend_ema": 400,
            "atr_period": 14, "atr_sl_mult": 3.0,
            "trailing_atr_mult": 3.5,
            "cooldown_bars": 24,
            "lookback_bars": 1500,
        },
        "leverage": 5,
        "position_pct": 0.20,
    },
    # === No ADX filter — pure momentum ===
    {
        "label": "TSMOM nofilter 24/168/720 trail2.5 lev3",
        "strategy_params": {
            "roc_short": 24, "roc_medium": 168, "roc_long": 720,
            "w_short": 0.25, "w_medium": 0.35, "w_long": 0.40,
            "entry_threshold": 0.015,
            "vol_lookback": 168, "target_vol": 0.45,
            "max_vol_scalar": 3.0, "min_vol_scalar": 0.2,
            "adx_period": 14, "adx_threshold": 0,   # <-- disabled
            "trend_ema": 200,
            "atr_period": 14, "atr_sl_mult": 2.5,
            "trailing_atr_mult": 3.0,
            "cooldown_bars": 12,
            "lookback_bars": 800,
        },
        "leverage": 3,
        "position_pct": 0.15,
    },
    # === Medium aggressive with max holding period ===
    {
        "label": "TSMOM maxhold 24/168/720 hold480 lev5",
        "strategy_params": {
            "roc_short": 24, "roc_medium": 168, "roc_long": 720,
            "w_short": 0.2, "w_medium": 0.4, "w_long": 0.4,
            "entry_threshold": 0.01,
            "vol_lookback": 168, "target_vol": 0.45,
            "max_vol_scalar": 3.0, "min_vol_scalar": 0.2,
            "adx_period": 14, "adx_threshold": 20,
            "trend_ema": 200,
            "atr_period": 14, "atr_sl_mult": 2.0,
            "trailing_atr_mult": 2.5,
            "cooldown_bars": 12,
            "max_hold_bars": 480,  # 20 days max hold
            "lookback_bars": 800,
        },
        "leverage": 5,
        "position_pct": 0.15,
    },
]


def main():
    df = HistoricalDataManager.load_csv(DATA_PATH)
    console.print(f"[bold]Loaded {len(df)} bars ({len(df)/24:.0f} days)[/bold]")
    console.print()

    table = Table(title="TSMOM Strategy Comparison")
    table.add_column("Config", style="cyan", max_width=50)
    table.add_column("Return", style="green")
    table.add_column("Sharpe", style="yellow")
    table.add_column("Sortino", style="yellow")
    table.add_column("MaxDD", style="red")
    table.add_column("WR", style="white")
    table.add_column("PF", style="white")
    table.add_column("Trades", style="dim")
    table.add_column("AvgPnL", style="dim")

    results_list = []

    for cfg in CONFIGS:
        label = cfg["label"]
        params = cfg["strategy_params"]
        leverage = cfg["leverage"]
        pos_pct = cfg["position_pct"]

        try:
            data_feed = HistoricalDataFeed(df.copy())
            broker = BacktestBroker(commission=0.001, slippage=0.0005)
            portfolio = PortfolioTracker(10000.0)

            strategy = STRATEGY_REGISTRY["tsmom"]()
            strategy_config = StrategyConfig(name="tsmom", params=params)
            strategy.setup(strategy_config)

            risk_config = RiskConfig(
                max_position_size_pct=pos_pct,
                max_open_positions=3,
                max_drawdown_pct=0.30,
                default_stop_loss_pct=0.03,
                default_take_profit_pct=0.06,
            )

            risk_mgr = RiskManager(risk_config, portfolio, leverage=leverage)

            app_config = AppConfig(
                exchange=ExchangeConfig(),
                pairs=[TradingPairConfig(
                    symbol=SYMBOL, market_type=MarketType.FUTURES,
                    leverage=leverage,
                )],
                strategy=strategy_config,
                risk=risk_config,
                backtest=BacktestConfig(initial_capital=10000.0),
            )

            engine = BacktestEngine(data_feed, strategy, risk_mgr, broker, portfolio, app_config)
            r = engine.run(symbol=SYMBOL, silent=True)

            table.add_row(
                label,
                f"{r['total_return_pct']:+.1%}",
                f"{r['sharpe_ratio']:.3f}",
                f"{r['sortino_ratio']:.3f}",
                f"{r['max_drawdown_pct']:.1%}",
                f"{r['win_rate']:.0%}",
                f"{r['profit_factor']:.2f}" if r['profit_factor'] != float('inf') else "inf",
                str(r['total_trades']),
                f"${r['avg_trade_pnl']:.2f}",
            )
            results_list.append((label, r))
            console.print(f"  [green]OK[/green] {label}: {r['total_return_pct']:+.1%}")

        except Exception as e:
            table.add_row(label, "[red]ERROR[/red]", "", "", "", "", "", "", "")
            console.print(f"  [red]FAIL[/red] {label}: {e}")
            import traceback
            traceback.print_exc()

    console.print()
    console.print(table)

    # Print best result details
    if results_list:
        best = max(results_list, key=lambda x: x[1].get("sharpe_ratio", -999))
        console.print()
        console.rule(f"[bold green]Best: {best[0]}[/bold green]")
        r = best[1]
        for k, v in r.items():
            if isinstance(v, float):
                console.print(f"  {k}: {v:.4f}")
            else:
                console.print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
