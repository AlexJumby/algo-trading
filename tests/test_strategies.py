import numpy as np
import pandas as pd
import pytest

from src.core.config import StrategyConfig
from src.core.enums import SignalAction
from src.strategies.momentum import MomentumStrategy, STRATEGY_REGISTRY
from src.strategies.tsmom import TSMOMStrategy


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


class TestTSMOMTimeframe:
    """Test TSMOM timeframe normalization."""

    def _make_tsmom(self, timeframe="1h", vol_mode="simple"):
        s = TSMOMStrategy()
        s.setup(StrategyConfig(
            name="tsmom",
            params={
                "timeframe": timeframe,
                "vol_mode": vol_mode,
                "roc_short": 24,
                "roc_medium": 168,
                "roc_long": 720,
                "vol_lookback": 168,
                "trend_ema": 200,
            },
        ))
        return s

    def test_1h_identity(self):
        """On 1h, bar counts should equal hour values (no conversion)."""
        s = self._make_tsmom("1h")
        assert s.roc_short == 24
        assert s.roc_medium == 168
        assert s.roc_long == 720
        assert s.vol_lookback == 168
        assert s.trend_ema_period == 200

    def test_4h_scaled(self):
        """On 4h, lookbacks should be 4x shorter in bars."""
        s = self._make_tsmom("4h")
        assert s.roc_short == 6      # 24h / 4h = 6 bars
        assert s.roc_medium == 42    # 168h / 4h = 42 bars
        assert s.roc_long == 180     # 720h / 4h = 180 bars
        assert s.vol_lookback == 42
        assert s.trend_ema_period == 50  # 200h / 4h = 50

    def test_1d_scaled(self):
        """On 1d, lookbacks are much shorter."""
        s = self._make_tsmom("1d")
        assert s.roc_short == 1   # 24h / 24h = 1 bar
        assert s.roc_medium == 7  # 168h / 24h = 7 bars
        assert s.roc_long == 30   # 720h / 24h = 30 bars

    def test_bar_params_not_converted(self):
        """adx_period, atr_period, cooldown_bars should NOT be converted."""
        s = self._make_tsmom("4h")
        assert s.adx_period == 14
        assert s.atr_period == 14
        assert s.cooldown_bars == 12

    def test_ewma_mode_passed_to_indicator(self):
        """vol_mode should be forwarded to RealizedVolatility."""
        s = self._make_tsmom("1h", vol_mode="ewma")
        # Find RealizedVolatility indicator
        from src.indicators.realized_vol import RealizedVolatility
        rv_indicators = [i for i in s.indicators if isinstance(i, RealizedVolatility)]
        assert len(rv_indicators) == 1
        assert rv_indicators[0].mode == "ewma"

    def test_vol_scalar_in_metadata_not_strength(self, sample_ohlcv_df):
        """Signal strength should be 1.0; vol_scalar in metadata."""
        s = self._make_tsmom("1h")
        df = s.apply_indicators(sample_ohlcv_df.copy())
        # Walk bars and collect entry signals
        for i in range(200, len(df)):
            window = df.iloc[:i + 1]
            signals = s.generate_signals(window)
            for sig in signals:
                if sig.action in (SignalAction.LONG, SignalAction.SHORT):
                    assert sig.strength == 1.0
                    assert "vol_scalar" in sig.metadata
