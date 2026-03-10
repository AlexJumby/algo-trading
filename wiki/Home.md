# Algo Trading System

Open-source quantitative trading system for crypto perpetual futures on Bybit.

## Quick Navigation

| Page | Description |
|------|-------------|
| [[Getting Started]] | Installation, data download, first backtest |
| [[Architecture]] | System design, 5-layer architecture, data flow |
| [[TSMOM Strategy]] | Strategy logic, entry/exit rules, math behind signals |
| [[Risk Management]] | Volatility targeting, drawdown deleveraging, position sizing |
| [[Deployment]] | Docker, VPS, Telegram bot, web dashboard |
| [[Validation]] | Walk-forward, Monte Carlo, regime-segmented backtest |
| [[Configuration Reference]] | All `settings.yaml` parameters explained |

## Current Status

- **Version:** v0.4.1
- **Mode:** Paper trading on Bybit testnet
- **Tests:** 209 passing
- **Strategy:** TSMOM (Time-Series Momentum)
- **Code reviews:** 4 rounds completed

## Backtest Performance (730 days)

| Metric | BTC (7x) | ETH (7x) |
|--------|:--------:|:--------:|
| Return | +70.9% | +141.5% |
| Sharpe | 1.09 | 1.85 |
| Max DD | 23.0% | 18.3% |
| Win Rate | 38% | 40% |
| Trades | 120 | 124 |

## Links

- [GitHub Repository](https://github.com/AlexJumby/algo-trading)
- [Issues](https://github.com/AlexJumby/algo-trading/issues)
- [Roadmap](https://github.com/AlexJumby/algo-trading#roadmap)
