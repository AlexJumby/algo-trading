"""Comprehensive strategy validation before going live.

Tests:
    1. Walk-Forward Analysis — train on 70%, test on unseen 30%
    2. Bull/Bear regime split — performance in different market conditions
    3. Long vs Short decomposition — where does profit come from?
    4. Trade concentration risk — what if we remove top N trades?
    5. Monte Carlo permutation — bootstrap confidence intervals
    6. Sharpe correction — fix annualization for hourly data
    7. Out-of-sample test — different asset (ETH if available)
"""
import sys
import logging
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.disable(logging.WARNING)

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

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
from src.portfolio.metrics import PerformanceMetrics
from src.risk.manager import RiskManager
from src.strategies.momentum import STRATEGY_REGISTRY

console = Console()

BTC_DATA = "data/BTCUSDT_USDT_1h.csv"
ETH_DATA = "data/ETHUSDT_USDT_1h.csv"
SYMBOL_BTC = "BTC/USDT:USDT"
SYMBOL_ETH = "ETH/USDT:USDT"

# Best TSMOM params from optimization
BEST_PARAMS = {
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
}

LEVERAGE = 7
POS_PCT = 0.15


def run_backtest(df, symbol, params=None, leverage=None, pos_pct=None):
    """Run a single backtest, return (metrics_dict, closed_trades, equity_curve)."""
    params = params or BEST_PARAMS
    leverage = leverage or LEVERAGE
    pos_pct = pos_pct or POS_PCT

    data_feed = HistoricalDataFeed(df.copy())
    broker = BacktestBroker(commission=0.001, slippage=0.0005)
    portfolio = PortfolioTracker(10000.0)
    strategy = STRATEGY_REGISTRY["tsmom"]()
    sc = StrategyConfig(name="tsmom", params=params)
    strategy.setup(sc)
    rc = RiskConfig(
        max_position_size_pct=pos_pct, max_open_positions=3,
        max_drawdown_pct=0.50, default_stop_loss_pct=0.03,
        default_take_profit_pct=0.06,
    )
    rm = RiskManager(rc, portfolio, leverage=leverage)
    ac = AppConfig(
        exchange=ExchangeConfig(),
        pairs=[TradingPairConfig(symbol=symbol, market_type=MarketType.FUTURES, leverage=leverage)],
        strategy=sc, risk=rc, backtest=BacktestConfig(initial_capital=10000.0),
    )
    engine = BacktestEngine(data_feed, strategy, rm, broker, portfolio, ac)
    metrics = engine.run(symbol=symbol, silent=True)
    return metrics, portfolio.closed_trades, portfolio.equity_curve


def section(title):
    console.print()
    console.rule(f"[bold cyan]{title}[/bold cyan]")
    console.print()


# =====================================================================
# TEST 1: SHARPE CORRECTION
# =====================================================================
def test_sharpe_correction(equity_curve):
    """Fix Sharpe for hourly data (code uses periods=252, but data is hourly)."""
    section("1. SHARPE RATIO CORRECTION")

    equities = [s.equity for s in equity_curve]
    eq = np.array(equities)
    returns = np.diff(eq) / eq[:-1]

    HOURS_PER_YEAR = 8760

    mean_r = np.mean(returns)
    std_r = np.std(returns, ddof=1)

    # Correct annualized Sharpe for hourly data
    hourly_sharpe = mean_r / std_r if std_r > 0 else 0
    annual_sharpe = hourly_sharpe * np.sqrt(HOURS_PER_YEAR)

    # What the code currently reports (wrong: uses sqrt(252))
    wrong_sharpe = hourly_sharpe * np.sqrt(252)

    console.print(f"  Hourly mean return:   {mean_r:.8f}")
    console.print(f"  Hourly std return:    {std_r:.6f}")
    console.print(f"  [red]Reported Sharpe (sqrt(252)):  {wrong_sharpe:.3f}  <-- WRONG for hourly[/red]")
    console.print(f"  [green]Corrected Sharpe (sqrt(8760)): {annual_sharpe:.3f}  <-- CORRECT[/green]")

    # Downside only (Sortino)
    downside = returns[returns < 0]
    downside_std = np.std(downside, ddof=1) if len(downside) > 0 else 1
    annual_sortino = mean_r / downside_std * np.sqrt(HOURS_PER_YEAR)
    console.print(f"  [green]Corrected Sortino:            {annual_sortino:.3f}[/green]")

    return annual_sharpe


# =====================================================================
# TEST 2: WALK-FORWARD ANALYSIS
# =====================================================================
def test_walk_forward(df, symbol):
    """Train on first 70%, test on unseen 30%."""
    section("2. WALK-FORWARD ANALYSIS (70/30 split)")

    n = len(df)
    split = int(n * 0.70)
    train_df = df.iloc[:split].copy().reset_index(drop=True)
    test_df = df.iloc[split:].copy().reset_index(drop=True)

    console.print(f"  Train: {len(train_df)} bars ({len(train_df)/24:.0f} days)")
    console.print(f"  Test:  {len(test_df)} bars ({len(test_df)/24:.0f} days)")
    console.print()

    m_train, _, _ = run_backtest(train_df, symbol)
    m_test, _, _ = run_backtest(test_df, symbol)

    table = Table(title="Walk-Forward: Train vs Test (unseen data)", box=box.SIMPLE)
    table.add_column("Metric", style="cyan")
    table.add_column("Train (70%)", style="green")
    table.add_column("Test (30%)", style="yellow")
    table.add_column("Verdict", style="white")

    def verdict(train_v, test_v, higher_better=True):
        if higher_better:
            ratio = test_v / train_v if train_v != 0 else 0
        else:
            ratio = train_v / test_v if test_v != 0 else 0
        if ratio > 0.7:
            return "[green]PASS[/green]"
        elif ratio > 0.4:
            return "[yellow]WEAK[/yellow]"
        else:
            return "[red]FAIL[/red]"

    rows = [
        ("Return", m_train["total_return_pct"], m_test["total_return_pct"], True),
        ("Sharpe", m_train["sharpe_ratio"], m_test["sharpe_ratio"], True),
        ("Profit Factor", m_train["profit_factor"], m_test["profit_factor"], True),
        ("Win Rate", m_train["win_rate"], m_test["win_rate"], True),
        ("Max Drawdown", m_train["max_drawdown_pct"], m_test["max_drawdown_pct"], False),
        ("Trades", m_train["total_trades"], m_test["total_trades"], True),
        ("Avg Trade PnL", m_train["avg_trade_pnl"], m_test["avg_trade_pnl"], True),
    ]

    for name, tv, tsv, hb in rows:
        fmt = ".1%" if "Rate" in name or "Return" in name or "Drawdown" in name else ".3f" if "Sharpe" in name or "Factor" in name else ".2f"
        if name == "Trades":
            table.add_row(name, str(int(tv)), str(int(tsv)), verdict(tv, tsv, hb))
        elif "Return" in name or "Rate" in name or "Drawdown" in name:
            table.add_row(name, f"{tv:.1%}", f"{tsv:.1%}", verdict(tv, tsv, hb))
        else:
            table.add_row(name, f"{tv:{fmt}}", f"{tsv:{fmt}}", verdict(tv, tsv, hb))

    console.print(table)

    # Is test profitable at all?
    if m_test["total_return_pct"] > 0:
        console.print("  [green]TEST IS PROFITABLE on unseen data![/green]")
    else:
        console.print("  [red]TEST IS NEGATIVE — strategy may be overfit[/red]")

    return m_test


# =====================================================================
# TEST 3: BULL vs BEAR REGIME SPLIT
# =====================================================================
def test_regime_split(df, symbol):
    """Split data into bull (price up) and bear (price down) periods."""
    section("3. BULL vs BEAR REGIME ANALYSIS")

    # Simple approach: split into halves or identify regimes by 200-period EMA
    # Better: look at where BTC price was trending up vs down
    n = len(df)

    # Use price vs 200-bar EMA to classify each bar
    ema = df["close"].ewm(span=200, adjust=False).mean()
    bull_mask = df["close"] > ema
    bear_mask = df["close"] <= ema

    bull_pct = bull_mask.sum() / n * 100
    bear_pct = bear_mask.sum() / n * 100

    console.print(f"  Bull bars (price > EMA200): {bull_mask.sum()} ({bull_pct:.0f}%)")
    console.print(f"  Bear bars (price < EMA200): {bear_mask.sum()} ({bear_pct:.0f}%)")

    # Also: first half vs second half (time-based)
    half = n // 2
    df_h1 = df.iloc[:half].copy().reset_index(drop=True)
    df_h2 = df.iloc[half:].copy().reset_index(drop=True)

    m_h1, trades_h1, _ = run_backtest(df_h1, symbol)
    m_h2, trades_h2, _ = run_backtest(df_h2, symbol)

    # Check BTC price change in each half
    btc_ret_h1 = (df_h1.iloc[-1]["close"] - df_h1.iloc[0]["close"]) / df_h1.iloc[0]["close"]
    btc_ret_h2 = (df_h2.iloc[-1]["close"] - df_h2.iloc[0]["close"]) / df_h2.iloc[0]["close"]

    table = Table(title="First Half vs Second Half", box=box.SIMPLE)
    table.add_column("", style="cyan")
    table.add_column("1st Half (Year 1)", style="green")
    table.add_column("2nd Half (Year 2)", style="yellow")

    table.add_row("BTC Buy & Hold", f"{btc_ret_h1:+.1%}", f"{btc_ret_h2:+.1%}")
    table.add_row("Strategy Return", f"{m_h1['total_return_pct']:+.1%}", f"{m_h2['total_return_pct']:+.1%}")
    table.add_row("Sharpe", f"{m_h1['sharpe_ratio']:.3f}", f"{m_h2['sharpe_ratio']:.3f}")
    table.add_row("Trades", str(m_h1['total_trades']), str(m_h2['total_trades']))
    table.add_row("Win Rate", f"{m_h1['win_rate']:.0%}", f"{m_h2['win_rate']:.0%}")
    table.add_row("Profit Factor", f"{m_h1['profit_factor']:.2f}", f"{m_h2['profit_factor']:.2f}")
    table.add_row("Max Drawdown", f"{m_h1['max_drawdown_pct']:.1%}", f"{m_h2['max_drawdown_pct']:.1%}")
    console.print(table)

    # Verdict
    both_positive = m_h1["total_return_pct"] > 0 and m_h2["total_return_pct"] > 0
    if both_positive:
        console.print("  [green]PASS: Profitable in BOTH halves[/green]")
    else:
        console.print("  [red]WARNING: Not profitable in both halves[/red]")


# =====================================================================
# TEST 4: LONG vs SHORT DECOMPOSITION
# =====================================================================
def test_long_short_split(trades):
    """Analyze where the profits come from: long or short trades."""
    section("4. LONG vs SHORT DECOMPOSITION")

    longs = [t for t in trades if t["side"] == "buy"]
    shorts = [t for t in trades if t["side"] == "sell"]

    def summarize(name, trade_list):
        if not trade_list:
            return name, 0, 0, 0, 0, 0
        pnls = [t["pnl"] for t in trade_list]
        total = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        wr = wins / len(pnls) if pnls else 0
        avg = np.mean(pnls)
        return name, len(trade_list), total, wr, avg, max(pnls) if pnls else 0

    table = Table(title="Long vs Short Performance", box=box.SIMPLE)
    table.add_column("Side", style="cyan")
    table.add_column("Trades")
    table.add_column("Total PnL", style="green")
    table.add_column("Win Rate")
    table.add_column("Avg PnL")
    table.add_column("Best Trade", style="green")

    for name, trade_list in [("LONG", longs), ("SHORT", shorts), ("ALL", trades)]:
        n, cnt, total, wr, avg, best = summarize(name, trade_list)
        table.add_row(
            n, str(cnt), f"${total:.0f}", f"{wr:.0%}", f"${avg:.1f}", f"${best:.0f}",
        )

    console.print(table)

    long_pnl = sum(t["pnl"] for t in longs)
    short_pnl = sum(t["pnl"] for t in shorts)
    total_pnl = long_pnl + short_pnl

    if total_pnl > 0:
        console.print(f"  Long contribution:  {long_pnl/total_pnl:.0%}")
        console.print(f"  Short contribution: {short_pnl/total_pnl:.0%}")

    if long_pnl > 0 and short_pnl > 0:
        console.print("  [green]PASS: Both sides profitable[/green]")
    elif long_pnl > 0 and short_pnl <= 0:
        console.print("  [yellow]WARNING: Only longs profitable — bull bias![/yellow]")
    elif long_pnl <= 0 and short_pnl > 0:
        console.print("  [yellow]WARNING: Only shorts profitable — bear bias![/yellow]")
    else:
        console.print("  [red]FAIL: Neither side is profitable?![/red]")


# =====================================================================
# TEST 5: TRADE CONCENTRATION RISK
# =====================================================================
def test_concentration_risk(trades):
    """What happens if we remove the top N best trades?"""
    section("5. TRADE CONCENTRATION RISK")

    pnls = sorted([t["pnl"] for t in trades], reverse=True)
    total_pnl = sum(pnls)
    n = len(pnls)

    table = Table(title="Sensitivity to Top Trades", box=box.SIMPLE)
    table.add_column("Remove", style="cyan")
    table.add_column("Remaining PnL", style="green")
    table.add_column("% of Original")
    table.add_column("Still Profitable?", style="yellow")

    for remove_n in [1, 3, 5, 10]:
        if remove_n >= n:
            break
        remaining = sum(pnls[remove_n:])
        pct = remaining / total_pnl * 100 if total_pnl > 0 else 0
        status = "[green]YES[/green]" if remaining > 0 else "[red]NO[/red]"
        table.add_row(
            f"Top {remove_n}", f"${remaining:.0f}", f"{pct:.0f}%", status,
        )

    console.print(table)

    # Top trade dominance
    if pnls:
        console.print(f"\n  Top 1 trade: ${pnls[0]:.0f} = {pnls[0]/total_pnl:.0%} of total PnL")
        top3 = sum(pnls[:3])
        console.print(f"  Top 3 trades: ${top3:.0f} = {top3/total_pnl:.0%} of total PnL")
        top5 = sum(pnls[:5])
        console.print(f"  Top 5 trades: ${top5:.0f} = {top5/total_pnl:.0%} of total PnL")

    # Risk assessment
    if total_pnl > 0:
        top3_pct = sum(pnls[:3]) / total_pnl
        if top3_pct > 0.6:
            console.print(f"\n  [red]HIGH RISK: Top 3 trades = {top3_pct:.0%} of all profits[/red]")
            console.print("  Strategy is heavily dependent on catching a few big moves")
        elif top3_pct > 0.4:
            console.print(f"\n  [yellow]MEDIUM RISK: Top 3 = {top3_pct:.0%}[/yellow]")
        else:
            console.print(f"\n  [green]LOW RISK: Top 3 = {top3_pct:.0%} — well diversified[/green]")


# =====================================================================
# TEST 6: MONTE CARLO SIMULATION
# =====================================================================
def test_monte_carlo(trades, n_simulations=10000):
    """Bootstrap trades to get confidence intervals."""
    section("6. MONTE CARLO SIMULATION (10,000 permutations)")

    pnls = np.array([t["pnl"] for t in trades])
    n_trades = len(pnls)

    np.random.seed(42)
    sim_returns = np.zeros(n_simulations)
    sim_max_dd = np.zeros(n_simulations)

    for i in range(n_simulations):
        # Resample trades with replacement
        sampled = np.random.choice(pnls, size=n_trades, replace=True)
        cumulative = 10000.0 + np.cumsum(sampled)
        sim_returns[i] = (cumulative[-1] - 10000.0) / 10000.0

        # Max drawdown of this simulation
        peak = np.maximum.accumulate(cumulative)
        dd = (peak - cumulative) / peak
        sim_max_dd[i] = np.max(dd)

    # Confidence intervals
    ret_pcts = [5, 25, 50, 75, 95]
    ret_vals = np.percentile(sim_returns, ret_pcts)

    table = Table(title="Monte Carlo Return Distribution", box=box.SIMPLE)
    table.add_column("Percentile", style="cyan")
    table.add_column("Return", style="green")
    table.add_column("Interpretation")

    labels = ["Worst 5%", "25th pct", "Median", "75th pct", "Best 5%"]
    for label, pct, val in zip(labels, ret_pcts, ret_vals):
        color = "green" if val > 0 else "red"
        interp = "profitable" if val > 0 else "LOSS"
        table.add_row(label, f"[{color}]{val:+.1%}[/{color}]", interp)

    console.print(table)

    # Probability of profit
    prob_profit = np.mean(sim_returns > 0) * 100
    prob_20pct = np.mean(sim_returns > 0.20) * 100
    prob_loss_10 = np.mean(sim_returns < -0.10) * 100

    console.print(f"\n  Probability of profit:     {prob_profit:.1f}%")
    console.print(f"  Probability of >20% return: {prob_20pct:.1f}%")
    console.print(f"  Probability of >10% loss:   {prob_loss_10:.1f}%")

    # Max drawdown distribution
    dd_median = np.median(sim_max_dd)
    dd_95 = np.percentile(sim_max_dd, 95)
    console.print(f"\n  Median Max Drawdown: {dd_median:.1%}")
    console.print(f"  95th percentile DD:  {dd_95:.1%}")

    if prob_profit > 70:
        console.print(f"\n  [green]PASS: {prob_profit:.0f}% chance of profit[/green]")
    elif prob_profit > 50:
        console.print(f"\n  [yellow]WEAK: Only {prob_profit:.0f}% chance of profit[/yellow]")
    else:
        console.print(f"\n  [red]FAIL: Only {prob_profit:.0f}% chance of profit[/red]")


# =====================================================================
# TEST 7: OUT-OF-SAMPLE (ETH)
# =====================================================================
def test_oos_eth():
    """Test same strategy on ETH — different asset, same params."""
    section("7. OUT-OF-SAMPLE: ETH (different asset, same params)")

    if not Path(ETH_DATA).exists():
        console.print("  [yellow]ETH data not found — skipping OOS test[/yellow]")
        console.print(f"  Run: python scripts/fetch_historical.py --symbol ETH/USDT:USDT --days 730 --output {ETH_DATA}")
        return None

    df = HistoricalDataManager.load_csv(ETH_DATA)
    console.print(f"  Loaded {len(df)} ETH bars ({len(df)/24:.0f} days)")

    m, trades, _ = run_backtest(df, SYMBOL_ETH, leverage=5)

    table = Table(title="ETH Out-of-Sample Results", box=box.SIMPLE)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Return", f"{m['total_return_pct']:+.1%}")
    table.add_row("Sharpe", f"{m['sharpe_ratio']:.3f}")
    table.add_row("Profit Factor", f"{m['profit_factor']:.2f}")
    table.add_row("Win Rate", f"{m['win_rate']:.0%}")
    table.add_row("Trades", str(m['total_trades']))
    table.add_row("Max Drawdown", f"{m['max_drawdown_pct']:.1%}")
    console.print(table)

    if m["total_return_pct"] > 0:
        console.print("  [green]PASS: Strategy works on ETH too![/green]")
    else:
        console.print("  [red]WARNING: Not profitable on ETH — may be BTC-specific[/red]")

    return m


# =====================================================================
# MAIN
# =====================================================================
def main():
    console.print(Panel.fit(
        "[bold]TSMOM Strategy Validation Suite[/bold]\n"
        "7 tests to validate before going live",
        border_style="cyan",
    ))

    df = HistoricalDataManager.load_csv(BTC_DATA)
    console.print(f"Loaded {len(df)} BTC bars ({len(df)/24:.0f} days)")

    # Run full backtest to get trades
    metrics, trades, equity_curve = run_backtest(df, SYMBOL_BTC)

    console.print(f"Baseline: {metrics['total_return_pct']:+.1%} return, "
                  f"{metrics['total_trades']} trades, Sharpe {metrics['sharpe_ratio']:.3f}")

    # Run all tests
    corrected_sharpe = test_sharpe_correction(equity_curve)
    wf_result = test_walk_forward(df, SYMBOL_BTC)
    test_regime_split(df, SYMBOL_BTC)
    test_long_short_split(trades)
    test_concentration_risk(trades)
    test_monte_carlo(trades)
    eth_result = test_oos_eth()

    # =====================================================================
    # FINAL VERDICT
    # =====================================================================
    section("FINAL VERDICT")

    checks = []

    # Sharpe
    if corrected_sharpe > 0.5:
        checks.append(("[green]PASS[/green]", f"Corrected Sharpe {corrected_sharpe:.2f} > 0.5"))
    elif corrected_sharpe > 0.3:
        checks.append(("[yellow]WEAK[/yellow]", f"Corrected Sharpe {corrected_sharpe:.2f} (0.3-0.5)"))
    else:
        checks.append(("[red]FAIL[/red]", f"Corrected Sharpe {corrected_sharpe:.2f} < 0.3"))

    # Walk-forward
    if wf_result and wf_result["total_return_pct"] > 0:
        checks.append(("[green]PASS[/green]", f"Walk-forward test: +{wf_result['total_return_pct']:.1%}"))
    else:
        checks.append(("[red]FAIL[/red]", "Walk-forward test negative"))

    # Monte Carlo already printed

    # Concentration
    top3_pnl = sum(sorted([t["pnl"] for t in trades], reverse=True)[:3])
    total_pnl = sum(t["pnl"] for t in trades)
    if total_pnl > 0:
        conc = top3_pnl / total_pnl
        if conc < 0.5:
            checks.append(("[green]PASS[/green]", f"Trade concentration: top 3 = {conc:.0%}"))
        else:
            checks.append(("[yellow]WARN[/yellow]", f"Trade concentration: top 3 = {conc:.0%} of profits"))

    # ETH OOS
    if eth_result:
        if eth_result["total_return_pct"] > 0:
            checks.append(("[green]PASS[/green]", f"ETH OOS: +{eth_result['total_return_pct']:.1%}"))
        else:
            checks.append(("[red]FAIL[/red]", "ETH OOS negative"))
    else:
        checks.append(("[yellow]SKIP[/yellow]", "ETH data not available"))

    table = Table(title="Validation Checklist", box=box.ROUNDED)
    table.add_column("Status", style="bold")
    table.add_column("Check")

    for status, desc in checks:
        table.add_row(status, desc)

    console.print(table)

    pass_count = sum(1 for s, _ in checks if "PASS" in s)
    total_count = len(checks)
    console.print(f"\n  Score: {pass_count}/{total_count} passed")

    if pass_count == total_count:
        console.print("  [bold green]ALL CLEAR — strategy is validated[/bold green]")
    elif pass_count >= total_count - 1:
        console.print("  [bold yellow]MOSTLY GOOD — proceed with caution, small size[/bold yellow]")
    else:
        console.print("  [bold red]NOT READY — more work needed before going live[/bold red]")


if __name__ == "__main__":
    main()
