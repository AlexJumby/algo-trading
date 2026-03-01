import numpy as np
import pandas as pd
import pytest

from src.core.config import StrategyConfig
from src.core.enums import SignalAction
from src.strategies.momentum import MomentumStrategy, STRATEGY_REGISTRY


class TestMomentumStrategy:
    @pytest.fixture
    def strategy(self):
        s = MomentumStrategy()
        s.setup(StrategyConfig(
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
            },
        ))
        return s

    def test_setup_indicators(self, strategy):
        assert len(strategy.indicators) == 4  # 2 EMA + RSI + MACD

    def test_apply_indicators(self, strategy, sample_ohlcv_df):
        df = strategy.apply_indicators(sample_ohlcv_df.copy())
        assert "ema_12" in df.columns
        assert "ema_26" in df.columns
        assert "rsi_14" in df.columns
        assert "macd_hist" in df.columns

    def test_no_signals_on_small_data(self, strategy):
        df = pd.DataFrame({
            "timestamp": [1], "open": [100], "high": [101],
            "low": [99], "close": [100], "volume": [1000],
        })
        df = strategy.apply_indicators(df)
        signals = strategy.generate_signals(df)
        assert signals == []

    def test_signals_on_trend_data(self, strategy, sample_ohlcv_df):
        """On 200 bars of trend data, strategy should produce at least some signals."""
        df = strategy.apply_indicators(sample_ohlcv_df.copy())
        signals = strategy.generate_signals(df)
        # May or may not produce a signal on the last bar, but shouldn't crash
        assert isinstance(signals, list)
        for s in signals:
            assert s.action in (
                SignalAction.LONG, SignalAction.SHORT, SignalAction.CLOSE
            )

    def test_generate_signals_all_bars(self, strategy, sample_ohlcv_df):
        """Walk through all bars and collect signals."""
        df = strategy.apply_indicators(sample_ohlcv_df.copy())
        all_signals = []
        for i in range(30, len(df)):
            window = df.iloc[:i + 1]
            signals = strategy.generate_signals(window)
            all_signals.extend(signals)
        # On 200 bars with a clear trend, we should get at least some signals
        assert len(all_signals) > 0

    def test_registry(self):
        assert "momentum" in STRATEGY_REGISTRY
        assert STRATEGY_REGISTRY["momentum"] is MomentumStrategy
