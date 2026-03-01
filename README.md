# Algo Trading Bot for Bybit

Algorithmic trading bot for Bybit exchange (Spot + USDT Perpetual Futures).

**Active strategy: TSMOM** (Time-Series Momentum + Volatility Management) — an academic approach used by hedge funds like AQR and Man Group.

---

## Backtest Results (730 days, March 2024 - March 2026)

| Metric | BTC/USDT (7x) | ETH/USDT (5x) |
|--------|:-:|:-:|
| **Total Return** | **+70.9%** | **+141.5%** |
| **Annual Return** | ~35%/yr | ~71%/yr |
| **Sharpe Ratio** | 1.09 | 1.85 |
| **Sortino Ratio** | 1.02 | 1.84 |
| **Max Drawdown** | 23.0% | 18.3% |
| **Win Rate** | 38% | 40% |
| **Profit Factor** | 1.56 | 2.01 |
| **Trades** | 120 | 124 |
| **Avg Trade PnL** | $59 | $114 |

### Validation Summary

| Test | Result |
|------|--------|
| Corrected Sharpe | 1.09 (>0.5 institutional grade) |
| Walk-Forward (70/30) | Test +38% > Train +28%, no overfitting |
| Bear market | +47% when BTC was -21% |
| Long + Short | Both profitable (65%/35%) |
| Monte Carlo (10k sims) | 92.5% probability of profit |
| ETH Out-of-Sample | +141% with same params |

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy config
cp config/settings.example.yaml config/settings.yaml

# 3. Fetch historical data (mainnet, no keys needed)
python scripts/fetch_historical.py --symbol "BTC/USDT:USDT" --days 730

# 4. Run backtest
python scripts/run_backtest.py

# 5. Validate strategy
python scripts/validate_strategy.py

# 6. Run paper trading (testnet, no real money)
python scripts/run_live.py --mode paper
```

---

## How It Works

### Architecture

The bot runs a simple loop every hour (or other timeframe):

1. **Fetch candles** (OHLCV) from exchange
2. **Compute indicators** — ROC, Realized Vol, ADX, ATR, EMA
3. **Generate signals** — LONG, SHORT or CLOSE based on momentum score
4. **Check risks** — position sizing with vol targeting, drawdown limits
5. **Place order** — on exchange (live) or virtually (paper/backtest)
6. **Track PnL** — equity curve, drawdown, trade log

```
Bybit API  ->  Indicators  ->  Strategy   ->  Risk Manager  ->  Order  ->  Portfolio
(candles)      (ROC/Vol/       (TSMOM:        (vol-scaled       (buy/     (PnL,
                ADX/ATR)       momentum       position size,     sell)     equity)
                               score)         trailing SL)
```

### TSMOM Strategy

Based on academic research: Moskowitz, Ooi, Pedersen (2012) "Time Series Momentum".

**Core idea**: Assets that have been going up tend to keep going up. Assets going down tend to keep going down. This is the most statistically robust trading signal across all asset classes.

**Entry (LONG)**:
- Composite momentum score > threshold (2%)
  - 48h ROC (16% weight) + 336h ROC (24%) + 1440h ROC (60%) = weighted score
- ADX > 22 (market is trending, not ranging)
- Price above 400-period EMA (uptrend)
- +DI > -DI (bullish directional movement)
- Short-term ROC positive (immediate momentum confirms)

**Entry (SHORT)**: Mirror conditions for downtrend.

**Exit**:
- Momentum reversal (composite score flips sign)
- ATR trailing stop (3.5x ATR) — lets winners run
- Max drawdown circuit breaker (25%)

**Volatility Targeting**:
- Measures 14-day realized volatility
- Scales position size: `vol_scalar = target_vol / realized_vol`
- High vol -> smaller positions. Low vol -> bigger positions.
- This is the key insight that makes professional trend-following work.

### Risk Management

- **Position size**: 15% of equity per trade (leveraged: 15% x 7 = 105% notional)
- **Stop-Loss**: 3x ATR (wide, avoids noise)
- **Trailing Stop**: 3.5x ATR (moves with price, locks in profits)
- **No fixed TP**: Let winners run indefinitely
- **Max positions**: 3 simultaneous
- **Max drawdown**: 25% — trading halts
- **Cooldown**: 24 bars (1 day) after any close
- **Vol targeting**: 50% annualized target

---

## Available Strategies

| Strategy | Name | Description |
|----------|------|-------------|
| **TSMOM** | `tsmom` | Time-Series Momentum + Vol Management. Active, best performer. |
| Momentum V1 | `momentum` | EMA crossover + RSI + MACD. Simple baseline. |
| Momentum V2 | `momentum_v2` | V1 + trend filter + ATR SL/TP + volume. |
| Momentum V3 | `momentum_v3` | V1 + trailing stop + cooldown. |
| Breakout | `breakout` | Donchian Channel breakout + ADX. Experimental. |

To switch strategy, change `strategy.name` in `config/settings.yaml`.

---

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/run_backtest.py` | Run backtest with current config |
| `scripts/run_live.py` | Live or paper trading |
| `scripts/fetch_historical.py` | Download OHLCV data from Bybit |
| `scripts/validate_strategy.py` | Full validation suite (7 tests) |
| `scripts/optimize.py` | Grid optimizer for momentum strategies |
| `scripts/optimize_tsmom_v2.py` | 2-stage optimizer for TSMOM |
| `scripts/finetune_tsmom.py` | Quick leverage/position fine-tuning |
| `scripts/test_tsmom.py` | Compare multiple TSMOM configs |

---

## Configuration

All settings in `config/settings.yaml`:

### API Keys

**Option 1: env variables (recommended)**
```bash
export BYBIT_API_KEY=your_key
export BYBIT_API_SECRET=your_secret
```

**Option 2: directly in config** (DO NOT commit to git!)
```yaml
exchange:
  api_key: "your_key"
  api_secret: "your_secret"
```

### TSMOM Strategy Parameters

```yaml
strategy:
  name: tsmom
  params:
    # Multi-period momentum lookback (hours)
    roc_short: 48          # 2-day momentum
    roc_medium: 336        # 14-day momentum
    roc_long: 1440         # 60-day momentum (strongest signal)
    # Momentum weights
    w_short: 0.16
    w_medium: 0.24
    w_long: 0.60           # Heavily weighted toward long-term
    # Entry threshold
    entry_threshold: 0.02  # Composite score must exceed 2%
    # Volatility targeting
    vol_lookback: 336      # 14-day realized vol window
    target_vol: 0.50       # Target 50% annualized portfolio vol
    # ADX trend filter
    adx_threshold: 22      # Only trade when ADX > 22
    # Stops
    atr_sl_mult: 3.0       # Initial stop: 3x ATR
    trailing_atr_mult: 3.5 # Trailing stop: 3.5x ATR
    cooldown_bars: 24      # 1-day cooldown after close
    lookback_bars: 1640    # Indicator warmup window
```

### Risk Parameters

```yaml
risk:
  max_position_size_pct: 0.15  # 15% equity per trade
  max_open_positions: 3
  max_drawdown_pct: 0.25       # Halt at 25% drawdown
  default_stop_loss_pct: 0.03
  default_take_profit_pct: 0.06
```

### Trading Pairs

```yaml
pairs:
  - symbol: "BTC/USDT:USDT"   # USDT perpetual futures
    market_type: futures
    timeframe: "1h"
    leverage: 7

  - symbol: "ETH/USDT:USDT"
    market_type: futures
    timeframe: "1h"
    leverage: 5
```

**Symbol format**:
- `BTC/USDT` — spot
- `BTC/USDT:USDT` — USDT perpetual futures

---

## Project Structure

```
algo_trading/
├── config/
│   ├── settings.yaml              # Your config (not in git)
│   └── settings.example.yaml      # Config template
│
├── src/
│   ├── core/                      # Base models and config
│   │   ├── config.py              # YAML config loader (Pydantic)
│   │   ├── enums.py               # Side, OrderType, MarketType, SignalAction
│   │   ├── models.py              # Signal, Order, Fill, Position
│   │   └── exceptions.py          # Custom errors
│   │
│   ├── indicators/                # Technical indicators
│   │   ├── base.py                # Base indicator class
│   │   ├── roc.py                 # Rate of Change (momentum core)
│   │   ├── realized_vol.py        # Realized Volatility (vol targeting)
│   │   ├── adx.py                 # Average Directional Index
│   │   ├── atr.py                 # Average True Range
│   │   ├── ema.py                 # Exponential Moving Average
│   │   ├── rsi.py                 # Relative Strength Index
│   │   ├── macd.py                # MACD
│   │   ├── donchian.py            # Donchian Channel
│   │   └── bbands.py              # Bollinger Bands
│   │
│   ├── strategies/                # Trading strategies
│   │   ├── base.py                # Base strategy class
│   │   ├── tsmom.py               # TSMOM (active, best performer)
│   │   ├── momentum.py            # EMA crossover (V1/V2/V3) + registry
│   │   └── breakout.py            # Donchian breakout
│   │
│   ├── risk/                      # Risk management
│   │   ├── manager.py             # SL/TP, leverage, vol-scaled sizing
│   │   └── position_sizer.py      # Fixed-fraction with leverage
│   │
│   ├── exchange/                  # Exchange connectivity
│   │   ├── base.py                # Abstract client
│   │   └── bybit_client.py        # Bybit via ccxt
│   │
│   ├── execution/                 # Order execution
│   │   ├── broker.py              # Abstract broker
│   │   ├── live_broker.py         # Real orders on exchange
│   │   ├── paper_broker.py        # Virtual orders (paper trading)
│   │   └── backtest_broker.py     # Backtest execution with SL/TP
│   │
│   ├── engine/                    # Trading engines
│   │   ├── backtest_engine.py     # Bar-by-bar backtest with trailing stops
│   │   └── live_engine.py         # Live/paper trading loop
│   │
│   ├── portfolio/                 # Portfolio tracking
│   │   ├── tracker.py             # PnL-based equity accounting
│   │   └── metrics.py             # Sharpe, Sortino, drawdown, win rate
│   │
│   └── utils/
│       └── logger.py              # Logging setup
│
├── scripts/                       # Entry points
│   ├── fetch_historical.py        # Download OHLCV data
│   ├── run_backtest.py            # Run backtest
│   ├── run_live.py                # Live/paper trading
│   ├── validate_strategy.py       # 7-test validation suite
│   ├── optimize.py                # Grid optimizer (momentum)
│   ├── optimize_tsmom_v2.py       # 2-stage TSMOM optimizer
│   ├── finetune_tsmom.py          # Quick leverage/pos tuning
│   └── test_tsmom.py              # TSMOM config comparison
│
├── tests/                         # 47 tests
├── data/                          # Downloaded CSV (in .gitignore)
└── logs/                          # Runtime logs (in .gitignore)
```

---

## Deployment

### Option 1: Docker (recommended)

```bash
# On your machine — push to GitHub/GitLab
git init && git add -A && git commit -m "init"
git remote add origin git@github.com:you/algo-trading.git
git push -u origin main

# On server
git clone git@github.com:you/algo-trading.git
cd algo-trading

# Configure
cp config/settings.example.yaml config/settings.yaml
nano config/settings.yaml

cp .env.example .env
nano .env                    # API keys

# Start
docker compose up -d         # -d = background
docker compose logs -f       # View logs
docker compose down          # Stop
```

**Switch to live trading**: in `docker-compose.yml` change:
```yaml
command: ["scripts/run_live.py", "--mode", "live"]
```

### Option 2: VPS without Docker

```bash
git clone <repo> /opt/algo_trading
cd /opt/algo_trading
bash deploy/setup-vps.sh

nano /opt/algo_trading/.env
nano /opt/algo_trading/config/settings.yaml

# Service management
systemctl start algo-trading
systemctl stop algo-trading
systemctl status algo-trading
journalctl -u algo-trading -f
```

Bot auto-restarts on crash or server reboot.

### Server Recommendations

| Provider | Plan | Price |
|---|---|---|
| **Hetzner** (Germany) | CX22 — 2 vCPU, 4GB RAM | ~$4/mo |
| **DigitalOcean** | Basic — 1 vCPU, 1GB RAM | $6/mo |
| **AWS Lightsail** | 1 vCPU, 512MB RAM | $3.50/mo |

The bot needs ~50MB RAM, wakes up once per hour. Any cheap VPS works.

---

## How to Add a New Strategy

1. Create `src/strategies/my_strategy.py`
2. Inherit from `BaseStrategy`
3. Implement `setup()` and `generate_signals()`
4. Register in `STRATEGY_REGISTRY` (in `momentum.py`)

```python
from src.strategies.base import BaseStrategy
from src.core.models import Signal
from src.core.enums import SignalAction

class MyStrategy(BaseStrategy):
    def setup(self, config):
        self.indicators = [...]

    def generate_signals(self, df):
        # Return list of signals based on indicator values
        return [Signal(
            timestamp=..., symbol="",
            action=SignalAction.LONG, strength=1.0,
            metadata={"atr_sl": atr * 2.0, "no_tp": True},
        )]
```

5. In `config/settings.yaml`:
```yaml
strategy:
  name: my_strategy
```

---

## Logs

- `logs/algo_trading.log` — all bot actions (DEBUG level)
- `logs/trades.log` — trades only (OPEN / CLOSE with prices and PnL)

---

## FAQ

**Q: Is it safe to run?**
By default the bot runs on **testnet** (Bybit test network). No real money is used. To switch to mainnet, explicitly set `testnet: false` in config and confirm launch.

**Q: How many pairs can I trade?**
As many as you want — add them to `pairs` in config. Each pair is processed every tick.

**Q: How often does the bot trade?**
TSMOM with slow lookbacks (48/336/1440h) generates ~60 trades per year per asset. Signals appear when multi-period momentum crosses the threshold — roughly every few days.

**Q: What if internet drops?**
The bot logs the error and retries after 30 seconds. Stop-Loss orders on the exchange trigger independently of the bot.

**Q: How to stop the bot?**
`Ctrl+C` — graceful shutdown.

**Q: How to get Bybit testnet API keys?**
1. Go to https://testnet.bybit.com
2. Register
3. Go to API Management
4. Create a key with trading permissions

**Q: Why is win rate only 38%?**
This is normal for trend-following strategies. You lose frequently on small trades and win rarely on big ones. The average win ($430) is 2.5x the average loss ($171). This is how AQR, Man Group, and Turtle Traders operate.

**Q: What is Volatility Targeting?**
The strategy measures recent price volatility and adjusts position size accordingly. When the market is chaotic (high vol), it trades smaller. When calm (low vol), it trades bigger. This normalizes returns across market regimes and is the key innovation that separates professional trend-following from amateur trading.
