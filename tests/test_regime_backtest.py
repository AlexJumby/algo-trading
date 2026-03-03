"""Tests for regime-segmented backtest utilities."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.regime_backtest import classify_bars_simple, compute_regime_stats


def _make_df(closes: list[float]) -> pd.DataFrame:
    """Helper to build a minimal OHLCV DataFrame."""
    return pd.DataFrame({
        "timestamp": range(len(closes)),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [1000] * len(closes),
    })


class TestClassifyBarsSimple:
    def test_uptrend_classified_as_bull(self):
        """Strong uptrend should be mostly bull bars."""
        closes = [100 + i * 0.5 for i in range(600)]
        df = _make_df(closes)
        regimes = classify_bars_simple(df, ema_period=50, roc_period=100)
        bull_count = sum(1 for r in regimes[300:] if r == "bull")
        assert bull_count > len(regimes[300:]) * 0.5

    def test_downtrend_classified_as_bear(self):
        """Strong downtrend should be mostly bear bars."""
        closes = [200 - i * 0.5 for i in range(600)]
        df = _make_df(closes)
        regimes = classify_bars_simple(df, ema_period=50, roc_period=100)
        bear_count = sum(1 for r in regimes[300:] if r == "bear")
        assert bear_count > len(regimes[300:]) * 0.5

    def test_flat_classified_as_chop(self):
        """Flat price should be all chop after warmup."""
        closes = [100.0] * 600
        df = _make_df(closes)
        regimes = classify_bars_simple(df, ema_period=50, roc_period=100)
        chop_count = sum(1 for r in regimes[200:] if r == "chop")
        assert chop_count == len(regimes[200:])

    def test_early_bars_are_chop(self):
        """Bars before ema_period should always be chop."""
        closes = [100 + i for i in range(600)]
        df = _make_df(closes)
        regimes = classify_bars_simple(df, ema_period=200, roc_period=100)
        for r in regimes[:200]:
            assert r == "chop"

    def test_returns_correct_length(self):
        """Output length matches input."""
        closes = [100.0] * 500
        df = _make_df(closes)
        regimes = classify_bars_simple(df, ema_period=50, roc_period=100)
        assert len(regimes) == 500

    def test_only_valid_labels(self):
        """All labels are from the valid set."""
        closes = [100 + np.sin(i / 10) * 20 for i in range(600)]
        df = _make_df(closes)
        regimes = classify_bars_simple(df, ema_period=50, roc_period=100)
        assert all(r in ("bull", "bear", "chop") for r in regimes)

    def test_custom_roc_threshold(self):
        """Higher ROC threshold → more chop bars."""
        closes = [100 + i * 0.05 for i in range(600)]
        df = _make_df(closes)
        r_low = classify_bars_simple(df, ema_period=50, roc_period=100, roc_threshold=0.01)
        r_high = classify_bars_simple(df, ema_period=50, roc_period=100, roc_threshold=0.10)
        bull_low = sum(1 for r in r_low if r == "bull")
        bull_high = sum(1 for r in r_high if r == "bull")
        assert bull_low >= bull_high


class TestComputeRegimeStats:
    def test_all_bull(self):
        """All bars are bull → all returns in bull bucket."""
        equity = [10000 + i * 10 for i in range(100)]
        regimes = ["bull"] * 100
        stats = compute_regime_stats(equity, regimes)
        assert stats["bull"]["bars"] == 99  # n-1 returns
        assert stats["bull"]["total_return"] > 0
        assert stats["bear"]["bars"] == 0
        assert stats["chop"]["bars"] == 0

    def test_all_bear_losing(self):
        """Declining equity in bear → negative return."""
        equity = [10000 - i * 10 for i in range(100)]
        regimes = ["bear"] * 100
        stats = compute_regime_stats(equity, regimes)
        assert stats["bear"]["total_return"] < 0

    def test_empty_equity(self):
        """Empty inputs → all zeros."""
        stats = compute_regime_stats([], [])
        assert stats["bull"]["bars"] == 0
        assert stats["bear"]["bars"] == 0
        assert stats["chop"]["bars"] == 0

    def test_mixed_regimes(self):
        """Returns correctly attributed to regime at each bar."""
        equity = [10000, 10100, 10050, 10200]
        regimes = ["bull", "bull", "bear", "chop"]
        stats = compute_regime_stats(equity, regimes)
        assert stats["bull"]["bars"] == 1
        assert stats["bear"]["bars"] == 1
        assert stats["chop"]["bars"] == 1

    def test_pct_time_sums_to_one(self):
        """Percentage of time across regimes sums to ~1.0."""
        equity = [10000 + i * 5 for i in range(100)]
        regimes = ["bull"] * 40 + ["bear"] * 30 + ["chop"] * 30
        stats = compute_regime_stats(equity, regimes)
        total_pct = sum(s["pct_time"] for s in stats.values())
        assert abs(total_pct - 1.0) < 0.02

    def test_sharpe_positive_for_uptrend(self):
        """Consistent gains should produce positive Sharpe approx."""
        equity = [10000 + i * 10 for i in range(200)]
        regimes = ["bull"] * 200
        stats = compute_regime_stats(equity, regimes)
        assert stats["bull"]["sharpe_approx"] > 0

    def test_equity_change_sign(self):
        """Equity change has correct sign."""
        equity = [10000, 10500, 10300]
        regimes = ["bull", "bull", "bear"]
        stats = compute_regime_stats(equity, regimes)
        assert stats["bull"]["equity_change"] > 0  # 10000→10500 is positive
        assert stats["bear"]["equity_change"] < 0  # 10500→10300 is negative
