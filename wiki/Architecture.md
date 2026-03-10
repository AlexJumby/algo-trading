# Architecture

The system follows a **5-layer architecture** inspired by institutional trading desks. Each layer has a single responsibility and communicates through well-defined interfaces.

## Layer Diagram

```
Signal Layer        Risk Layer           Execution Layer      Portfolio Layer
+-------------+    +--------------+     +--------------+    +--------------+
| TSMOM       |    | Vol Targeting|     | Market Orders|    | PnL Tracking |
| Regime Filt.|───>| DD Deleverage|────>| Trailing Stop|───>|   Rolling    |
| Multi-ROC   |    | Position Cap |     | Paper/Live   |    |   Metrics    |
+-------------+    +--------------+     +--------------+    +--------------+
                                                                    |
Infrastructure Layer                                                v
+----------------------------------------------------------------------+
| Docker + VPS | Telegram Alerts | Web Dashboard | SQLite | CI/CD      |
+----------------------------------------------------------------------+
```

## Data Flow (one tick cycle)

```
1. Fetch OHLCV candles (Bybit API via ccxt)
   - Detect data gaps (warn if gap > 3x expected interval)
        |
2. Compute indicators (ROC, EWMA Vol, ADX, ATR, EMA, Regime)
        |
3. Strategy generates signals (LONG / SHORT / EXIT)
   - Per-symbol state: cooldown, position tracking, bars held
        |
4. Risk manager evaluates signal:
   - Check regime: trending? choppy?
   - Compute position size (vol-scaled + DD deleverage)
   - Clamp ATR SL to max 15% of price
   - Enforce leverage cap
        |
5. Broker executes order:
   - Market order with ATR-based stop-loss
   - Trailing stop adjustment (shared trail_stop)
        |
6. Portfolio updates (ONCE per tick, after all pairs):
   - Process fill, update PnL
   - Take equity snapshot (single per tick)
   - Compute rolling metrics (single per tick)
        |
7. Notifications:
   - Telegram: trade alert, status report
   - Dashboard: equity curve, positions
   - Degradation alert if Sharpe drops
```

## Layer Details

### Signal Layer (`src/strategies/`, `src/indicators/`)

Generates trading signals from market data.

| Component | File | Purpose |
|-----------|------|---------|
| TSMOM Strategy | `strategies/tsmom.py` | Multi-period momentum + regime filter |
| Regime Filter | `indicators/regime.py` | ADX + efficiency ratio + vol z-score |
| Indicators | `indicators/*.py` | ROC, ADX, ATR, EMA, RSI, EWMA Vol, etc. |
| Strategy Base | `strategies/base.py` | Abstract interface for all strategies |
| Registry | `strategies/momentum.py` | Strategy lookup by name |

### Risk Layer (`src/risk/`)

Transforms signals into risk-controlled orders.

| Component | File | Purpose |
|-----------|------|---------|
| Risk Manager | `risk/manager.py` | Signal evaluation, order generation |
| Position Sizer | `risk/position_sizer.py` | Vol-targeting + drawdown scaling |

### Execution Layer (`src/execution/`, `src/engine/`)

Executes orders and manages the trading loop.

| Component | File | Purpose |
|-----------|------|---------|
| Backtest Engine | `engine/backtest_engine.py` | Historical simulation with funding |
| Live Engine | `engine/live_engine.py` | Real-time trading loop |
| Base Broker | `execution/broker.py` | Shared `check_stops()` logic |
| Backtest Broker | `execution/backtest_broker.py` | Simulated fills with realistic fees |
| Paper Broker | `execution/paper_broker.py` | Virtual order execution |
| Live Broker | `execution/live_broker.py` | Real exchange orders |
| Trail Stop | `execution/stops.py` | Shared `trail_stop()` — ATR-based trailing SL |
| Bybit Client | `exchange/bybit_client.py` | Exchange API wrapper (ccxt) |

### Portfolio Layer (`src/portfolio/`)

Tracks PnL, equity, and performance metrics.

| Component | File | Purpose |
|-----------|------|---------|
| Tracker | `portfolio/tracker.py` | Position management, PnL accounting |
| Metrics | `portfolio/metrics.py` | Sharpe, Sortino, max DD, profit factor |
| Rolling Metrics | `portfolio/rolling_metrics.py` | 30-day sliding window monitors |
| Persistence | `portfolio/persistence.py` | SQLite storage for equity/trades |

### Infrastructure Layer

| Component | Location | Purpose |
|-----------|----------|---------|
| Docker | `docker-compose.yml`, `Dockerfile` | Containerized deployment |
| Telegram | `notifications/telegram.py` | Trade alerts, status reports |
| Dashboard | `dashboard/` | Web UI (FastAPI + HTMX) |
| CI/CD | `.github/workflows/` | Test + auto-deploy |
| SQLite | `data/portfolio.db` | Persistent storage |

## Key Design Decisions

1. **PnL-based equity tracking** — equity = initial_capital + realized_pnl + unrealized_pnl - open_entry_fees. No simulated "cash balance" that can go negative.

2. **Silent mode for optimization** — `engine.run(silent=True)` pre-computes all indicators once and skips progress bars. Makes parameter sweeps 10x faster.

3. **Timeframe-agnostic parameters** — all strategy params are in hours, auto-converted to bar counts. Same config works for 1h, 4h, 1d candles.

4. **Regime gates entries, not exits** — in choppy markets, no new positions are opened, but existing positions are still managed (trailing stop, exits). This avoids locking capital in bad trades.

5. **Per-symbol strategy state** — strategies maintain `_state[symbol]` dicts (cooldown, position tracking, bars held) so multi-symbol trading (BTC+ETH) doesn't cause state corruption.

6. **O(1) drawdown tracking** — `_peak_equity` is updated incrementally in `take_snapshot()` instead of scanning the full equity curve. Critical for long-running live sessions.

7. **ATR SL sanity clamp** — stop-loss distance is capped at 15% of entry price. Prevents absurd SL values when data gaps cause ATR to spike (observed on Bybit testnet: ATR $127K → SL at $464K).

8. **Data gap detection** — after paginated OHLCV fetch, timestamps are checked for gaps > 3x expected interval. Warning is logged so operators know indicators may be unreliable.

9. **Shared stop logic** — `check_stops()` lives in base `Broker` class (not duplicated per broker), and `trail_stop()` is a standalone function in `execution/stops.py` used by both engines.

10. **Stop gap slippage** — when SL/TP triggers, fill is at market price (not the stop level). If price gaps through $78K SL to $75K, fill is at $75K. More realistic than assuming fills at exact stop levels.
