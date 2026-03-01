import numpy as np
import pandas as pd
import pytest

from src.core.config import (
    AppConfig,
    BacktestConfig,
    ExchangeConfig,
    RiskConfig,
    StrategyConfig,
    TradingPairConfig,
)
from src.core.enums import MarketType


@pytest.fixture
def sample_ohlcv_df() -> pd.DataFrame:
    """Generate 200 bars of synthetic OHLCV data with a clear trend."""
    np.random.seed(42)
    n = 200
    base_price = 50000.0
    timestamps = list(range(1704067200000, 1704067200000 + n * 3600000, 3600000))

    # Create a trend: first 100 bars up, next 100 bars down
    trend = np.concatenate([
        np.linspace(0, 2000, 100),  # Uptrend
        np.linspace(2000, 0, 100),  # Downtrend
    ])
    noise = np.random.normal(0, 100, n)
    closes = base_price + trend + noise

    data = {
        "timestamp": timestamps[:n],
        "open": closes - np.random.uniform(0, 50, n),
        "high": closes + np.random.uniform(0, 100, n),
        "low": closes - np.random.uniform(0, 100, n),
        "close": closes,
        "volume": np.random.uniform(100, 1000, n),
    }
    return pd.DataFrame(data)


@pytest.fixture
def small_ohlcv_df() -> pd.DataFrame:
    """Small DataFrame for indicator tests."""
    return pd.DataFrame({
        "timestamp": [1704067200000 + i * 3600000 for i in range(50)],
        "open": [100 + i * 0.5 for i in range(50)],
        "high": [101 + i * 0.5 for i in range(50)],
        "low": [99 + i * 0.5 for i in range(50)],
        "close": [100 + i * 0.5 + (0.5 if i % 2 == 0 else -0.3) for i in range(50)],
        "volume": [1000 + i * 10 for i in range(50)],
    })


@pytest.fixture
def app_config() -> AppConfig:
    return AppConfig(
        exchange=ExchangeConfig(
            name="bybit",
            api_key="test_key",
            api_secret="test_secret",
            testnet=True,
        ),
        pairs=[
            TradingPairConfig(
                symbol="BTC/USDT:USDT",
                market_type=MarketType.FUTURES,
                timeframe="1h",
                leverage=5,
            ),
        ],
        strategy=StrategyConfig(
            name="momentum",
            params={
                "fast_ema": 12,
                "slow_ema": 26,
                "rsi_period": 14,
                "rsi_overbought": 70,
                "rsi_oversold": 30,
                "macd_fast": 12,
                "macd_slow": 26,
                "macd_signal": 9,
                "lookback_bars": 100,
            },
        ),
        risk=RiskConfig(),
        backtest=BacktestConfig(
            initial_capital=10000.0,
            commission_pct=0.001,
            slippage_pct=0.0005,
        ),
    )
