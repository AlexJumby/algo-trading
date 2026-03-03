"""Tests for RegimeFilter indicator and TSMOM integration."""
import numpy as np
import pandas as pd
import pytest

from src.indicators.regime import RegimeFilter


def _make_df(n: int = 300, trend: str = "up") -> pd.DataFrame:
    """Generate synthetic OHLCV data with a known regime."""
    np.random.seed(42)
    if trend == "up":
        # Strong uptrend — low noise, consistent direction
        prices = 100 + np.cumsum(np.random.uniform(0.1, 0.5, n))
    elif trend == "down":
        prices = 200 - np.cumsum(np.random.uniform(0.1, 0.5, n))
    elif trend == "choppy":
        # Mean-reverting noise — no directional move
        prices = 100 + np.cumsum(np.random.normal(0, 1, n))
        # Force mean reversion
        prices = 100 + (prices - prices.mean()) * 0.3
    else:
        prices = np.full(n, 100.0)

    high = prices + np.random.uniform(0, 1, n)
    low = prices - np.random.uniform(0, 1, n)
    return pd.DataFrame({
        "open": prices,
        "high": high,
        "low": low,
        "close": prices,
        "volume": np.random.uniform(100, 1000, n),
        "timestamp": np.arange(n) * 3600 * 1000,
    })


class TestRegimeFilter:
    def test_columns_added(self):
        rf = RegimeFilter(period=14)
        df = _make_df(200, "up")
        result = rf.compute(df)
        assert "regime_14" in result.columns
        assert "regime_state_14" in result.columns

    def test_name_property(self):
        rf = RegimeFilter(period=14)
        assert rf.name == "Regime(14)"

    def test_columns_property(self):
        rf = RegimeFilter(period=14)
        assert rf.columns == ["regime_14", "regime_state_14"]

    def test_score_range_0_to_1(self):
        rf = RegimeFilter(period=14)
        df = _make_df(300, "up")
        result = rf.compute(df)
        scores = result["regime_14"].dropna()
        assert scores.min() >= 0.0
        assert scores.max() <= 1.0

    def test_trending_detection_uptrend(self):
        rf = RegimeFilter(period=14, threshold=0.3)
        df = _make_df(300, "up")
        result = rf.compute(df)
        # Last bars should be trending (strong directional move)
        last_state = result["regime_state_14"].iloc[-1]
        assert last_state == "trending"

    def test_choppy_detection(self):
        rf = RegimeFilter(period=14, threshold=0.5)
        df = _make_df(300, "choppy")
        result = rf.compute(df)
        # Choppy data should have lower scores on average
        avg_score = result["regime_14"].iloc[-50:].mean()
        assert avg_score < 0.7  # Not as high as trending

    def test_custom_parameters(self):
        rf = RegimeFilter(period=20, vol_period=100, threshold=0.6)
        df = _make_df(300, "up")
        result = rf.compute(df)
        assert "regime_20" in result.columns
        assert "regime_state_20" in result.columns

    def test_custom_weights(self):
        rf = RegimeFilter(period=14, w_adx=0.5, w_er=0.3, w_vol=0.2)
        df = _make_df(200, "up")
        result = rf.compute(df)
        assert "regime_14" in result.columns

    def test_state_values(self):
        rf = RegimeFilter(period=14)
        df = _make_df(200, "up")
        result = rf.compute(df)
        unique_states = set(result["regime_state_14"].dropna().unique())
        assert unique_states.issubset({"trending", "choppy"})


class TestEfficiencyRatio:
    def test_straight_up_high_er(self):
        """Perfectly directional price → ER near 1.0."""
        prices = pd.Series(np.linspace(100, 200, 50))
        er = RegimeFilter._compute_efficiency_ratio(prices, 10)
        # Last values should be close to 1.0
        assert er.iloc[-1] > 0.8

    def test_flat_low_er(self):
        """Flat-ish noisy price → ER near 0."""
        np.random.seed(99)
        prices = pd.Series(100 + np.random.normal(0, 0.01, 100))
        er = RegimeFilter._compute_efficiency_ratio(prices, 10)
        assert er.iloc[-1] < 0.5


class TestTSMOMRegimeIntegration:
    """Test that regime filter integrates correctly with TSMOM strategy."""

    def test_regime_enabled_adds_indicator(self):
        from src.core.config import StrategyConfig
        from src.strategies.tsmom import TSMOMStrategy

        strategy = TSMOMStrategy()
        config = StrategyConfig(name="tsmom", params={"regime_enabled": True})
        strategy.setup(config)
        indicator_names = [i.name for i in strategy.indicators]
        assert any("Regime" in n for n in indicator_names)

    def test_regime_disabled_no_indicator(self):
        from src.core.config import StrategyConfig
        from src.strategies.tsmom import TSMOMStrategy

        strategy = TSMOMStrategy()
        config = StrategyConfig(name="tsmom", params={"regime_enabled": False})
        strategy.setup(config)
        indicator_names = [i.name for i in strategy.indicators]
        assert not any("Regime" in n for n in indicator_names)
