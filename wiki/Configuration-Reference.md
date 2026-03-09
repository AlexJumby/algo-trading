# Configuration Reference

All configuration is in `config/settings.yaml`.

## Trading Pairs

```yaml
pairs:
  - symbol: "BTC/USDT:USDT"
    market_type: futures
    timeframe: "1h"
    leverage: 7
  - symbol: "ETH/USDT:USDT"
    market_type: futures
    timeframe: "1h"
    leverage: 7
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | string | Bybit perpetual pair (format: `BASE/QUOTE:SETTLE`) |
| `market_type` | string | `futures` for USDT-margined perpetuals |
| `timeframe` | string | Candle timeframe: `1h`, `4h`, `1d` |
| `leverage` | int | Position leverage (applied on exchange) |

## Strategy Parameters

```yaml
strategy:
  name: tsmom
  params:
    # Momentum
    roc_short: 48
    roc_medium: 336
    roc_long: 1440
    w_short: 0.16
    w_medium: 0.24
    w_long: 0.60
    entry_threshold: 0.02

    # Volatility
    vol_lookback: 336
    target_vol: 0.50
    vol_mode: "ewma"

    # Trend filters
    adx_period: 14
    adx_threshold: 22
    trend_ema: 400

    # Stops
    atr_period: 14
    atr_sl_mult: 3.0
    trailing_atr_mult: 3.5

    # Regime filter
    regime_enabled: true
    regime_period: 14
    regime_threshold: 0.4

    # Misc
    cooldown_bars: 24
    lookback_bars: 1640
```

### Momentum Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `roc_short` | 48 | Short-term ROC period (hours) |
| `roc_medium` | 336 | Medium-term ROC period (hours) |
| `roc_long` | 1440 | Long-term ROC period (hours) |
| `w_short` | 0.16 | Weight for short ROC in composite score |
| `w_medium` | 0.24 | Weight for medium ROC |
| `w_long` | 0.60 | Weight for long ROC |
| `entry_threshold` | 0.02 | Minimum composite score to enter (2%) |

### Volatility Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `vol_lookback` | 336 | Volatility estimation window (hours) |
| `target_vol` | 0.50 | Target annualized volatility (50%) |
| `vol_mode` | ewma | `"ewma"` (faster reaction) or `"simple"` (rolling std) |
| `max_vol_scalar` | 3.0 | Max position size multiplier |
| `min_vol_scalar` | 0.2 | Min position size multiplier |

### Trend Filter Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `adx_period` | 14 | ADX computation period (bars) |
| `adx_threshold` | 22 | Minimum ADX for trend confirmation |
| `trend_ema` | 400 | Long-term EMA for trend direction (bars) |

### Stop-Loss Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `atr_period` | 14 | ATR computation period (bars) |
| `atr_sl_mult` | 3.0 | Initial stop-loss = entry ± ATR * mult |
| `trailing_atr_mult` | 3.5 | Trailing stop = price ± ATR * mult |

### Regime Filter Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `regime_enabled` | true | Enable/disable regime filter |
| `regime_period` | 14 | Period for ADX and efficiency ratio |
| `regime_threshold` | 0.4 | Score threshold (0-1): above = trending |

### Misc Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `cooldown_bars` | 24 | Bars to wait after closing before new entry |
| `lookback_bars` | 1640 | Data warmup (must cover longest indicator) |

## Risk Parameters

```yaml
risk:
  max_position_size_pct: 0.15
  max_open_positions: 3
  max_drawdown_pct: 0.25
  max_leverage_exposure: 5.0
  drawdown_soft_pct: 0.10
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_position_size_pct` | 0.15 | Base position = equity * this * leverage |
| `max_open_positions` | 3 | Maximum concurrent positions |
| `max_drawdown_pct` | 0.25 | Full trading halt at this drawdown |
| `max_leverage_exposure` | 5.0 | Max notional/equity ratio per position |
| `drawdown_soft_pct` | 0.10 | Start reducing size at this drawdown |
| `default_stop_loss_pct` | 0.03 | Fallback stop-loss (if ATR unavailable) |
| `default_take_profit_pct` | 0.06 | Fallback take-profit (not used with trailing) |

## Backtest Parameters

```yaml
backtest:
  initial_capital: 10000
  commission: 0.001
  slippage: 0.0005
  funding_rate_pct: 0.0001
  funding_interval_hours: 8
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `initial_capital` | 10000 | Starting equity ($) |
| `commission` | 0.001 | Trading fee per side (0.1%) |
| `slippage` | 0.0005 | Simulated slippage (0.05%) |
| `funding_rate_pct` | 0.0001 | Perpetual funding rate (0.01%) |
| `funding_interval_hours` | 8 | Funding charge interval |

## Environment Variables

Set in `.env` file or export directly:

| Variable | Required | Description |
|----------|----------|-------------|
| `BYBIT_API_KEY` | Yes | Bybit API key (testnet or mainnet) |
| `BYBIT_API_SECRET` | Yes | Bybit API secret |
| `TELEGRAM_BOT_TOKEN` | No | Telegram bot token for notifications |
| `TELEGRAM_CHAT_ID` | No | Telegram chat ID for notifications |

## Tuning Tips

1. **More aggressive:** Increase `leverage`, decrease `entry_threshold`, decrease `adx_threshold`
2. **More conservative:** Decrease `leverage`, increase `entry_threshold`, enable regime filter
3. **Less trading:** Increase `cooldown_bars`, increase `entry_threshold`
4. **Wider stops:** Increase `atr_sl_mult` and `trailing_atr_mult` (fewer stop-outs, larger losses when stopped)
5. **Tighter regime filter:** Increase `regime_threshold` above 0.4 (more chop filtering, fewer trades)
