# Algo Trading System v0.4.0

Quantitative trading system for crypto perpetual futures (Bybit). Designed with fund-level architecture: signal layer, risk layer, execution layer, portfolio layer, infrastructure layer.

**Active strategy:** TSMOM (Time-Series Momentum + Volatility Management) — based on Moskowitz, Ooi, Pedersen (2012), used by AQR Capital and Man Group.

**Status:** Paper trading on Bybit testnet. Robustness validated (walk-forward, Monte Carlo, regime segmentation). Two code review rounds completed. 192 tests, Docker + CI/CD.

---

## Backtest Results (730 days, Mar 2024 - Mar 2026)

| Metric | BTC/USDT (7x) | ETH/USDT (7x) |
|--------|:-:|:-:|
| **Total Return** | **+70.9%** | **+141.5%** |
| **Sharpe Ratio** | 1.09 | 1.85 |
| **Max Drawdown** | 23.0% | 18.3% |
| **Win Rate** | 38% | 40% |
| **Profit Factor** | 1.56 | 2.01 |
| **Trades** | 120 | 124 |

With realistic fees (maker 0.02%, taker 0.055%, dynamic slippage, 0.01%/8h funding).

### Robustness Validation

| Test | Result |
|------|--------|
| **Monte Carlo** (10k reshuffles) | 0% probability of negative return, 95% CI MaxDD 12-32% |
| **Walk-Forward** (11 OOS folds) | 7/11 profitable, mean Sharpe 0.75, WF efficiency 77% |
| **Regime Segmentation** | Bull +83%, Bear +55%, Chop -42% (expected for trend-following) |

---

## Architecture

```
Signal Layer        Risk Layer           Execution Layer      Portfolio Layer
┌─────────────┐    ┌──────────────┐     ┌──────────────┐    ┌──────────────┐
│ TSMOM       │    │ Vol Targeting│     │ Market Orders│    │ PnL Tracking │
│ Regime Filt.│───>│ DD Deleverage│────>│ Trailing Stop│───>│    Rolling   │
│ Multi-ROC   │    │ Position Cap │     │ Paper/Live   │    │    Metrics   │
└─────────────┘    └──────────────┘     └──────────────┘    └──────────────┘
                                                                    │
Infrastructure Layer                                                v
┌──────────────────────────────────────────────────────────────────────┐
│ Docker + VPS │ Telegram Alerts │ Web Dashboard │ SQLite │ CI/CD      │
└──────────────────────────────────────────────────────────────────────┘
```

### Signal Flow

1. **Fetch candles** (OHLCV) from Bybit via ccxt
2. **Compute indicators** — ROC, EWMA Vol, ADX, ATR, EMA, Regime Filter
3. **Check regime** — "trending" = proceed, "choppy" = skip entry
4. **Generate signals** — LONG/SHORT/CLOSE based on composite momentum score
5. **Risk check** — vol-scaled sizing, drawdown deleveraging, leverage cap
6. **Execute** — market order with ATR stop-loss
7. **Monitor** — rolling Sharpe, expectancy, degradation alerts

---

## Key Features

### Signal Layer
- **Multi-period momentum** — 48h / 336h / 1440h ROC with weighted composite score
- **Regime filter** — ADX + efficiency ratio + vol z-score classifier; blocks entries in choppy markets
- **EWMA volatility** — exponentially weighted vol reacts faster to regime shifts than rolling std
- **Timeframe-agnostic** — params in hours, auto-converted to bar counts for any timeframe (1h, 4h, 1d)

### Risk Layer
- **Volatility targeting** — scales position size to 50% annualized vol target
- **Drawdown deleveraging** — linear position reduction from 10% DD (full size) to 25% DD (zero)
- **ATR trailing stop** — 3.5x ATR, moves with price, no fixed TP (shared `trail_stop()` logic)
- **ATR SL sanity clamp** — stop-loss distance capped at 15% of price (prevents absurd SL from data gaps)
- **Max leverage cap** — 5x notional/equity hard limit per position
- **Max drawdown halt** — full stop at 25%

### Execution Layer
- **Bybit perpetuals** — USDT-margined futures via ccxt
- **Paper + live modes** — paper broker with realistic maker/taker fees
- **Dynamic slippage** — base + impact per $100k notional
- **Funding rate** — 0.01%/8h perpetual funding in backtest
- **Data gap detection** — warns when OHLCV data has gaps > 3x expected interval
- **Consolidated stop logic** — `check_stops()` in base Broker, `trail_stop()` in shared module

### Portfolio Layer
- **Rolling metrics** — 30-day Sharpe, Sortino, expectancy, win rate, profit factor
- **Degradation alerts** — Telegram alert when rolling Sharpe crosses below 0
- **Equity curve persistence** — SQLite snapshots every bar
- **Performance metrics** — Sharpe, Sortino, max DD, profit factor, best/worst trade
- **O(1) drawdown** — peak equity tracked incrementally, no full-curve scan

### Infrastructure
- **Docker deployment** — single `docker compose up -d`
- **Telegram notifications** — trade open/close, trailing stop, 4h status, degradation alerts
- **Web dashboard** — real-time equity curve, positions, trades (FastAPI + HTMX)
- **CI/CD** — GitHub Actions: test on push, auto-deploy to VPS
- **192 tests** — strategies, indicators, risk, portfolio, regime filter, deleveraging, rolling metrics, validation scripts

---

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Fetch data
python scripts/fetch_historical.py --symbol "BTC/USDT:USDT" --days 730

# Backtest
python scripts/run_backtest.py

# Parameter sensitivity analysis
python -m scripts.param_sensitivity

# Robustness validation
python -m scripts.monte_carlo              # Monte Carlo (10k reshuffles)
python -m scripts.regime_backtest          # Bull/Bear/Chop breakdown
python -m scripts.walk_forward             # Walk-forward OOS validation

# Paper trading (testnet)
export BYBIT_API_KEY=your_testnet_key
export BYBIT_API_SECRET=your_testnet_secret
python scripts/run_live.py --mode paper
```

---

## TSMOM Strategy

### Entry (LONG)
- Composite momentum > 2%: `0.16 * ROC_48h + 0.24 * ROC_336h + 0.60 * ROC_1440h`
- Regime = "trending" (composite ADX + efficiency ratio + vol z-score > 0.4)
- ADX > 22 (market is trending)
- Price > 400-period EMA (uptrend confirmed)
- +DI > -DI (bullish directional movement)
- Short-term ROC positive

### Entry (SHORT)
Mirror conditions for downtrend.

### Exit
- Momentum reversal (composite score flips sign)
- ATR trailing stop (3.5x ATR)
- Max holding period (if configured)

### Position Sizing
```
base_size    = equity * 15% * leverage
vol_scalar   = target_vol / realized_vol  (clamped 0.2x - 3.0x)
dd_scalar    = 1.0 - (drawdown - 10%) / (25% - 10%)  (linear 1.0→0.0)
final_size   = base_size * vol_scalar * dd_scalar
hard_cap     = equity * 5x max leverage
```

---

## Configuration

`config/settings.yaml`:

```yaml
pairs:
  - symbol: "BTC/USDT:USDT"
    market_type: futures
    timeframe: "1h"
    leverage: 7

strategy:
  name: tsmom
  params:
    vol_mode: "ewma"              # "simple" or "ewma"
    roc_short: 48                  # Hours
    roc_medium: 336
    roc_long: 1440
    w_short: 0.16
    w_medium: 0.24
    w_long: 0.60
    entry_threshold: 0.02
    vol_lookback: 336
    target_vol: 0.50
    adx_threshold: 22
    trend_ema: 400
    atr_sl_mult: 3.0
    trailing_atr_mult: 3.5
    cooldown_bars: 24
    lookback_bars: 1640
    # Regime filter
    regime_enabled: true
    regime_period: 14
    regime_threshold: 0.4

risk:
  max_position_size_pct: 0.15
  max_open_positions: 3
  max_drawdown_pct: 0.25
  max_leverage_exposure: 5.0
  drawdown_soft_pct: 0.10         # Start deleveraging at 10% DD
```

### API Keys (env vars recommended)
```bash
export BYBIT_API_KEY=your_key
export BYBIT_API_SECRET=your_secret
export TELEGRAM_BOT_TOKEN=your_bot_token
export TELEGRAM_CHAT_ID=your_chat_id
```

---

## Deployment (Docker)

```bash
# On VPS
git clone git@github.com:AlexJumby/algo-trading.git ~/algo_trading
cd ~/algo_trading
cp .env.example .env && nano .env     # API keys
nano config/settings.yaml              # Trading config

docker compose up -d                   # Start
docker compose logs -f --tail=50       # View logs
docker compose down                    # Stop
```

CI/CD: push to `main` → GitHub Actions runs tests → auto-deploys to VPS.

---

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/run_backtest.py` | Backtest with current config |
| `scripts/run_live.py` | Live or paper trading |
| `scripts/param_sensitivity.py` | Parameter robustness analysis (ROBUST/FRAGILE) |
| `scripts/walk_forward.py` | Walk-forward OOS validation (11 folds) |
| `scripts/monte_carlo.py` | Monte Carlo confidence intervals (10k reshuffles) |
| `scripts/regime_backtest.py` | Performance breakdown by market regime (bull/bear/chop) |
| `scripts/fetch_historical.py` | Download OHLCV from Bybit |
| `scripts/optimize_tsmom.py` | Grid search optimizer for TSMOM |
| `scripts/validate_strategy.py` | Full validation suite |

---

## Project Structure

```
algo_trading/
├── config/settings.yaml                # Trading config
├── src/
│   ├── core/                           # Config, models, enums
│   │   ├── config.py                   # Pydantic config + timeframe utils
│   │   ├── models.py                   # Signal, Order, Fill, Position
│   │   └── enums.py                    # Side, OrderType, SignalAction
│   ├── indicators/                     # Technical indicators
│   │   ├── base.py                     # Abstract Indicator class
│   │   ├── regime.py                   # Regime filter (ADX + ER + vol z-score)
│   │   ├── realized_vol.py            # Realized vol (simple + EWMA modes)
│   │   ├── roc.py, adx.py, atr.py    # Momentum, trend, volatility
│   │   ├── ema.py, rsi.py, macd.py   # Moving averages, oscillators
│   │   └── bbands.py, donchian.py     # Bands, channels
│   ├── strategies/                     # Trading strategies
│   │   ├── base.py                     # Abstract BaseStrategy
│   │   ├── tsmom.py                    # TSMOM (active, best performer)
│   │   ├── momentum.py                 # EMA crossover variants + registry
│   │   └── breakout.py                 # Donchian breakout
│   ├── risk/                           # Risk management
│   │   ├── manager.py                  # Signal→Order + risk checks
│   │   └── position_sizer.py          # Vol-scaled + DD deleveraging
│   ├── execution/                      # Order execution
│   │   ├── broker.py                  # Base broker (shared check_stops)
│   │   ├── backtest_broker.py         # Realistic fees + slippage
│   │   ├── paper_broker.py            # Virtual orders
│   │   ├── live_broker.py             # Real exchange orders
│   │   └── stops.py                   # Shared trail_stop() logic
│   ├── engine/                         # Trading loops
│   │   ├── backtest_engine.py         # Bar-by-bar + funding rate
│   │   └── live_engine.py             # Live loop + rolling monitors
│   ├── portfolio/                      # Portfolio tracking
│   │   ├── tracker.py                  # PnL accounting + equity curve
│   │   ├── metrics.py                  # Sharpe, Sortino, DD, win rate
│   │   ├── rolling_metrics.py         # 30d rolling monitors + alerts
│   │   └── persistence.py             # SQLite storage
│   ├── exchange/
│   │   └── bybit_client.py            # Bybit via ccxt
│   ├── notifications/
│   │   └── telegram.py                 # Trade alerts + degradation alerts
│   └── data/
│       ├── feed.py                     # Data feed (historical + live)
│       └── historical.py               # CSV data management
├── scripts/                            # Entry points + analysis tools
├── tests/                              # 192 tests
├── dashboard/                          # Web UI (FastAPI + HTMX)
├── docker-compose.yml
├── Dockerfile
└── .github/workflows/                  # CI/CD
    ├── ci.yml                          # Test on push
    └── deploy.yml                      # Auto-deploy to VPS
```

---

## Versioning

| Version | Date | Changes |
|---------|------|---------|
| **v0.4.0** | 2026-03-09 | Code review refactoring: ATR/SL clamp, per-symbol state, O(1) drawdown, stop dedup, data gap detection, snapshot fix |
| v0.3.1 | 2026-03-03 | Walk-forward validation, Monte Carlo CI, regime-segmented backtest |
| v0.3.0 | 2026-03-03 | Regime filter, drawdown deleveraging, rolling monitors, param sensitivity |
| v0.2.0 | 2026-03-02 | Timeframe normalization, EWMA vol, realistic fees/funding/slippage |
| v0.1.0 | 2026-03-01 | Infrastructure: Docker, Telegram, dashboard, CI/CD, SQLite |
| v0.0.1 | 2026-02-28 | Core engine, TSMOM strategy, backtesting, 47 tests |

---

## Roadmap

### Phase 1.2 — Validate Robustness ✅
- [x] Walk-forward validation (11 OOS folds, 7/11 profitable, WF efficiency 77%)
- [x] Monte Carlo confidence intervals (10k reshuffles, 0% prob of negative return)
- [x] Regime-segmented backtest (bull +83%, bear +55%, chop -42%)
- [ ] 4-8 weeks paper trading track record (in progress)

### Phase 1.3 — Code Review Hardening ✅
- [x] Code review round 1: O(1) drawdown, check_stops dedup, trail_stop extraction, encapsulation fixes
- [x] Code review round 2: ATR/SL clamp, per-symbol strategy state, snapshot dedup, data gap detection, sync_state on restart

### Phase 2 — Multi-Strategy
- [ ] Mean reversion strategy (for choppy markets)
- [ ] Strategy-level P&L separation
- [ ] Risk budget allocator (not just signal blending)
- [ ] Correlation monitoring between strategies

### Phase 3 — Fund Infrastructure
- [ ] PostgreSQL + immutable trade ledger
- [ ] NAV engine + investor reporting
- [ ] Monitoring (Grafana / Prometheus)
- [ ] Backup / disaster recovery

---

## FAQ

**Q: Is it safe to run?**
By default the bot runs on testnet. No real money. Set `testnet: false` for mainnet.

**Q: Why is win rate only 38%?**
Normal for trend-following. Small frequent losses, large rare wins. Average win ($430) is 2.5x average loss ($171). This is how AQR and Man Group operate.

**Q: What is the regime filter?**
It classifies the market as "trending" or "choppy" using ADX, efficiency ratio (directional consistency), and volatility z-score. In choppy markets, the bot doesn't open new positions — only manages existing ones.

**Q: How does drawdown deleveraging work?**
Instead of binary "trade or stop", position size scales linearly: 100% at 0-10% drawdown, 50% at 17.5%, 0% at 25%. This reduces risk gradually as losses accumulate.

**Q: How to run parameter sensitivity analysis?**
```bash
python -m scripts.param_sensitivity --data data/BTCUSDT_USDT_1h.csv --output results.json
```
Tests ±20% shift on 10 key parameters. Classifies each as ROBUST/MODERATE/FRAGILE.
