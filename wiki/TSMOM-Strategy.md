# TSMOM Strategy

**Time-Series Momentum** — a well-documented factor in financial markets. Based on the research of Moskowitz, Ooi, and Pedersen (2012), this strategy exploits the tendency of assets that have been going up to continue going up, and vice versa.

Used by institutional quant funds: AQR Capital Management, Man Group (AHL), Winton Group.

## Core Idea

Instead of comparing assets to each other (cross-sectional momentum), TSMOM looks at each asset's own price history. If BTC has been trending up for the past 60 days, go long. If trending down, go short.

## Signal Generation

### Composite Momentum Score

The strategy computes a **weighted ROC (Rate of Change)** across three timeframes:

```
score = 0.16 * ROC_48h + 0.24 * ROC_336h + 0.60 * ROC_1440h
```

Where ROC_N = (price_now - price_N_hours_ago) / price_N_hours_ago.

The heavy weighting on long-term momentum (60%) ensures the strategy follows major trends, not noise.

### Entry Conditions (LONG)

All must be true:
1. Composite momentum score > **2%** (entry threshold)
2. Regime filter = **"trending"** (not choppy market)
3. ADX > **22** (trend strength confirmed)
4. Price > **400-period EMA** (above long-term average)
5. +DI > -DI (bullish directional movement)
6. Short-term ROC > 0 (recent direction confirms)
7. Cooldown expired (**24 bars** since last trade close)

### Entry Conditions (SHORT)

Mirror of long conditions:
1. Composite momentum score < **-2%**
2. Regime = "trending"
3. ADX > 22
4. Price < 400-period EMA
5. -DI > +DI
6. Short-term ROC < 0
7. Cooldown expired

### Exit Conditions

Any one triggers an exit:
1. **Momentum reversal** — composite score flips sign
2. **ATR trailing stop** — 3.5x ATR, moves with price in profit direction
3. **Stop-loss hit** — 3.0x ATR initial stop

## Regime Filter

The regime filter prevents entries in choppy/sideways markets where trend-following loses money.

### How It Works

Three components combined into a single score (0 to 1):

| Component | Weight | What It Measures |
|-----------|--------|------------------|
| ADX (normalized) | 40% | Trend strength (0-100 mapped to 0-1) |
| Efficiency Ratio | 35% | Directional consistency (net move / total path) |
| Vol Z-Score | 25% | Current volatility vs historical (via sigmoid) |

```
regime_score = 0.40 * adx_norm + 0.35 * efficiency_ratio + 0.25 * vol_component
```

- Score > **0.4** = "trending" (entries allowed)
- Score <= 0.4 = "choppy" (entries blocked, exits still work)

### Efficiency Ratio (Kaufman)

```
ER = abs(close - close_N_bars_ago) / sum(abs(close[i] - close[i-1]) for i in range(N))
```

- ER = 1.0: perfectly straight line (strong trend)
- ER = 0.0: price went nowhere despite movement (pure chop)

### Why Gate Entries Only

In choppy markets, existing positions are still managed:
- Trailing stops can trigger exits
- Momentum reversal exits still work
- This prevents locking capital in positions opened during trending conditions

## Indicators Used

| Indicator | Period | Purpose |
|-----------|--------|---------|
| ROC (3 timeframes) | 48h, 336h, 1440h | Momentum measurement |
| ADX | 14 bars | Trend strength |
| ATR | 14 bars | Volatility for stops |
| EMA | 400 bars | Long-term trend direction |
| EWMA Volatility | 336h | Position sizing |
| Regime Filter | 14 bars | Market regime classification |

## Why These Parameters

- **ROC weights (0.16, 0.24, 0.60):** Heavy on long-term momentum. Short-term catches timing, medium confirms, long-term validates the trend.
- **Lookback 1640 bars:** Longest indicator (1440h ROC) needs this much warmup.
- **Cooldown 24 bars:** Prevents overtrading after a stop-loss hit. Common in trend-following to avoid re-entering the same failed trend.
- **ADX threshold 22:** Industry standard for "trending" classification. Below 20 is generally considered directionless.

## Multi-Symbol State Management

When trading multiple pairs (BTC + ETH), each symbol has independent strategy state:

```python
_state[symbol] = {
    "bars_since_fill": 999,   # cooldown counter
    "bars_in_position": 0,    # holding period
    "in_position": False,     # currently in trade
}
```

This prevents state corruption — e.g., BTC fill resetting ETH's cooldown counter, or BTC's `in_position` flag blocking ETH signals.

### Restart Recovery

On bot restart, `sync_state(portfolio)` re-syncs strategy state with actual exchange positions. Without this, the strategy would think it has no open positions and potentially open duplicate trades.

```python
def sync_state(self, portfolio):
    for symbol, pos in portfolio.open_positions.items():
        st = self._get_state(symbol)
        st["in_position"] = True
```

## Backtest Results

See [[Home]] for full results. Key insight: **win rate is only 38%, but average win is 2.5x average loss**. This is typical for trend-following — many small losses, few large wins.
