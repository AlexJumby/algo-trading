# Risk Management

The risk layer transforms raw signals into position-sized orders with stop losses. Three mechanisms work together to control risk.

## Position Sizing Formula

```
base_size  = equity * pos_pct * leverage
vol_scalar = target_vol / realized_vol        (clamped 0.2x - 3.0x)
dd_scalar  = 1.0 - (drawdown - soft) / (hard - soft)  (linear 1.0 -> 0.0)
final_size = base_size * vol_scalar * dd_scalar
hard_cap   = equity * max_leverage_exposure
```

### Example

With equity = $10,000, leverage = 7x, BTC at $90,000:

```
base_size  = $10,000 * 0.15 * 7 = $10,500 notional
vol_scalar = 0.50 / 0.65 = 0.77 (vol is high, reduce size)
dd_scalar  = 1.0 (no drawdown)
final_size = $10,500 * 0.77 = $8,085 notional = 0.0898 BTC
```

## 1. Volatility Targeting

Scales position size inversely to realized volatility.

**Goal:** Keep portfolio risk approximately constant regardless of market conditions.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `target_vol` | 0.50 | Target annualized volatility (50%) |
| `vol_lookback` | 336h | EWMA volatility lookback |
| `max_vol_scalar` | 3.0 | Maximum position multiplier |
| `min_vol_scalar` | 0.2 | Minimum position multiplier |
| `vol_mode` | ewma | "ewma" or "simple" rolling std |

**How it works:**

```
realized_vol = EWMA_std(returns, span=336h) * sqrt(8760)
vol_scalar   = target_vol / realized_vol
vol_scalar   = clamp(vol_scalar, 0.2, 3.0)
```

- High volatility (crypto crash) -> smaller positions
- Low volatility (consolidation) -> larger positions
- EWMA reacts faster to regime shifts than simple rolling std

## 2. Drawdown-Based Deleveraging

Gradually reduces position size as drawdown increases. Unlike a hard stop that goes from 100% to 0%, this scales linearly.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `drawdown_soft_pct` | 0.10 | Start reducing size at 10% DD |
| `max_drawdown_pct` | 0.25 | Zero position size at 25% DD |

**How it works:**

```
if drawdown < 10%:
    dd_scalar = 1.0         (full size)
elif drawdown >= 25%:
    dd_scalar = 0.0         (no new trades)
else:
    dd_scalar = 1.0 - (drawdown - 0.10) / (0.25 - 0.10)
```

**Example values:**

| Drawdown | dd_scalar | Effect |
|----------|-----------|--------|
| 0% - 10% | 1.00 | Full position size |
| 12.5% | 0.83 | 83% of normal size |
| 15% | 0.67 | 67% of normal size |
| 17.5% | 0.50 | Half size |
| 20% | 0.33 | Third size |
| 25%+ | 0.00 | No new trades |

**Why gradual?** A binary stop at 25% means you go from full size to zero instantly. With gradual deleveraging, you reduce exposure as risk increases, and you're still in the market (with small size) to catch a recovery.

## 3. Stop-Loss Management

### Initial Stop-Loss

Set at entry using ATR:

```
LONG:  stop_loss = entry_price - ATR(14) * 3.0
SHORT: stop_loss = entry_price + ATR(14) * 3.0
```

#### ATR Sanity Clamp

ATR can spike to absurd values when data has gaps (observed on Bybit testnet: trading pauses cause ATR to reach $127K, producing SL at $464K). To prevent this:

```
max_sl_distance = entry_price * 0.15      # 15% max
if atr_sl > max_sl_distance:
    atr_sl = max_sl_distance              # clamped with warning
```

This ensures no stop-loss is ever placed more than 15% away from entry, regardless of ATR value.

### Trailing Stop

The stop moves in the direction of profit (never against). Logic is shared via `trail_stop()` in `execution/stops.py`, used by both backtest and live engines:

```
LONG:  new_stop = current_price - ATR(14) * 3.5
       if new_stop > current_stop: update

SHORT: new_stop = current_price + ATR(14) * 3.5
       if new_stop < current_stop: update
```

No fixed take-profit. The trailing stop lets winners run while protecting profits.

### Data Gap Protection

The data feed detects gaps in OHLCV timestamps after paginated fetch. If any gap exceeds 3x the expected candle interval, a warning is logged. This alerts operators that ATR and other indicators may be unreliable for that period.

## 4. Hard Limits

| Limit | Value | Description |
|-------|-------|-------------|
| `max_leverage_exposure` | 5.0 | Max notional / equity per position |
| `max_open_positions` | 3 | Maximum concurrent positions |
| `max_drawdown_pct` | 0.25 | Full trading halt |

## Risk in Practice

From Monte Carlo simulation (10,000 reshuffles of actual trades):

- **0% probability** of negative return
- **17% probability** of MaxDD > 25% (with unlucky trade ordering)
- **7% probability** of MaxDD > 30%
- Median MaxDD: 18.3%

This means the 25% hard stop is well-calibrated — it would trigger in about 17% of random trade orderings.
