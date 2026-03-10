# Getting Started

## Requirements

- Python 3.10+
- pip

## Installation

```bash
git clone https://github.com/AlexJumby/algo-trading.git
cd algo-trading
pip install -r requirements.txt
```

## Download Historical Data

The system needs OHLCV candle data for backtesting. Data is fetched from Bybit:

```bash
# BTC — 730 days of 1h candles
python scripts/fetch_historical.py --symbol "BTC/USDT:USDT" --days 730

# ETH
python scripts/fetch_historical.py --symbol "ETH/USDT:USDT" --days 730
```

Data is saved to `data/BTCUSDT_USDT_1h.csv` with columns: `timestamp, open, high, low, close, volume`.

## Run Your First Backtest

```bash
python scripts/run_backtest.py
```

This runs the TSMOM strategy on BTC with default parameters and shows results:
- Total return, Sharpe ratio, max drawdown
- Trade-by-trade breakdown
- Equity curve visualization

### Backtest with custom symbol

```bash
python scripts/run_backtest.py --symbol "ETH/USDT:USDT" --data data/ETHUSDT_USDT_1h.csv
```

## Run Tests

```bash
python -m pytest --tb=short -q
```

Expected: 226 tests passing.

## Run Validation Suite

```bash
# Monte Carlo — confidence intervals (fastest, ~30 sec)
python -m scripts.monte_carlo

# Regime analysis — bull/bear/chop breakdown (~30 sec)
python -m scripts.regime_backtest

# Walk-forward — rolling OOS validation (~3-5 min)
python -m scripts.walk_forward

# Parameter sensitivity — robustness analysis (~5 min)
python -m scripts.param_sensitivity
```

## Next Steps

- [[TSMOM Strategy]] — understand the trading logic
- [[Deployment]] — run the bot on a VPS
- [[Configuration Reference]] — customize parameters
