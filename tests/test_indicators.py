import numpy as np
import pandas as pd
import pytest

from src.indicators.ema import EMAIndicator
from src.indicators.macd import MACDIndicator
from src.indicators.realized_vol import RealizedVolatility, HOURS_PER_YEAR
from src.indicators.rsi import RSIIndicator


class TestEMAIndicator:
    def test_compute_adds_column(self, small_ohlcv_df):
        ema = EMAIndicator(period=10)
        result = ema.compute(small_ohlcv_df.copy())
        assert "ema_10" in result.columns
        assert not result["ema_10"].isna().all()

    def test_name(self):
        ema = EMAIndicator(period=20)
        assert ema.name == "EMA(20)"
        assert ema.columns == ["ema_20"]

    def test_ema_smooths_data(self, small_ohlcv_df):
        ema = EMAIndicator(period=10)
        result = ema.compute(small_ohlcv_df.copy())
        ema_std = result["ema_10"].dropna().std()
        close_std = result["close"].std()
        assert ema_std < close_std  # EMA should be smoother

    def test_different_periods(self, small_ohlcv_df):
        fast = EMAIndicator(period=5)
        slow = EMAIndicator(period=20)
        df = small_ohlcv_df.copy()
        df = fast.compute(df)
        df = slow.compute(df)
        assert "ema_5" in df.columns
        assert "ema_20" in df.columns


class TestRSIIndicator:
    def test_compute_adds_column(self, small_ohlcv_df):
        rsi = RSIIndicator(period=14)
        result = rsi.compute(small_ohlcv_df.copy())
        assert "rsi_14" in result.columns

    def test_rsi_range(self, small_ohlcv_df):
        rsi = RSIIndicator(period=14)
        result = rsi.compute(small_ohlcv_df.copy())
        valid = result["rsi_14"].dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_name(self):
        rsi = RSIIndicator(period=14)
        assert rsi.name == "RSI(14)"
        assert rsi.columns == ["rsi_14"]


class TestMACDIndicator:
    def test_compute_adds_columns(self, small_ohlcv_df):
        macd = MACDIndicator(fast=12, slow=26, signal=9)
        result = macd.compute(small_ohlcv_df.copy())
        assert "macd" in result.columns
        assert "macd_signal" in result.columns
        assert "macd_hist" in result.columns

    def test_macd_hist_is_difference(self, small_ohlcv_df):
        macd = MACDIndicator()
        result = macd.compute(small_ohlcv_df.copy())
        valid = result.dropna(subset=["macd", "macd_signal", "macd_hist"])
        np.testing.assert_allclose(
            valid["macd_hist"].values,
            (valid["macd"] - valid["macd_signal"]).values,
            atol=1e-10,
        )

    def test_name(self):
        macd = MACDIndicator(12, 26, 9)
        assert macd.name == "MACD(12,26,9)"
        assert macd.columns == ["macd", "macd_signal", "macd_hist"]


class TestRealizedVolatility:
    def test_simple_mode_default(self, small_ohlcv_df):
        rv = RealizedVolatility(period=20)
        result = rv.compute(small_ohlcv_df.copy())
        assert "rvol_20" in result.columns
        valid = result["rvol_20"].dropna()
        assert len(valid) > 0
        assert (valid >= 0).all()

    def test_simple_mode_column_name(self):
        rv = RealizedVolatility(period=168)
        assert rv.columns == ["rvol_168"]
        assert rv.name == "RealVol(168)"

    def test_ewma_mode(self, small_ohlcv_df):
        rv = RealizedVolatility(period=20, mode="ewma")
        result = rv.compute(small_ohlcv_df.copy())
        assert "rvol_20" in result.columns
        valid = result["rvol_20"].dropna()
        assert len(valid) > 0
        assert (valid >= 0).all()

    def test_ewma_fewer_nans_than_simple(self, small_ohlcv_df):
        """EWMA should produce values earlier (fewer leading NaNs)."""
        df1 = small_ohlcv_df.copy()
        df2 = small_ohlcv_df.copy()
        rv_simple = RealizedVolatility(period=20, mode="simple")
        rv_ewma = RealizedVolatility(period=20, mode="ewma")
        rv_simple.compute(df1)
        rv_ewma.compute(df2)
        nan_simple = df1["rvol_20"].isna().sum()
        nan_ewma = df2["rvol_20"].isna().sum()
        assert nan_ewma <= nan_simple

    def test_custom_annualization(self, small_ohlcv_df):
        """Custom annualization_factor should produce different values."""
        df1 = small_ohlcv_df.copy()
        df2 = small_ohlcv_df.copy()
        rv_default = RealizedVolatility(period=20)
        rv_custom = RealizedVolatility(period=20, annualization_factor=2191.5)
        rv_default.compute(df1)
        rv_custom.compute(df2)
        valid1 = df1["rvol_20"].dropna()
        valid2 = df2["rvol_20"].dropna()
        assert len(valid1) == len(valid2)
        # 4h annualization < 1h → lower vol values
        assert valid2.mean() < valid1.mean()

    def test_default_annualization_is_hours_per_year(self):
        rv = RealizedVolatility()
        assert rv.ann_factor == HOURS_PER_YEAR

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown vol mode"):
            RealizedVolatility(mode="invalid")
