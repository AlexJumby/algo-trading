"""Regime Filter — classify market as trending or choppy.

Composite score from three components:
    1. **ADX strength** — measures trend intensity (0-100 → normalized to 0-1)
    2. **Efficiency ratio** — net price move / sum of absolute bar moves.
       1.0 = perfectly directional, 0.0 = pure noise.
    3. **Volatility z-score** — current vol vs rolling mean vol.
       Positive z-score (vol expansion) often accompanies trend starts.

The final regime score is a weighted average of these three, clamped to [0, 1].
A score above *threshold* → "trending" (trade); below → "choppy" (don't enter).

Used by TSMOM to skip entries in choppy markets while still managing
existing positions (exits + trailing stops continue normally).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.indicators.base import Indicator


class RegimeFilter(Indicator):
    """Market regime classifier: trending vs choppy.

    Columns added:
        regime_{period}:       float 0.0 – 1.0 (composite regime score)
        regime_state_{period}: str   "trending" or "choppy"
    """

    def __init__(
        self,
        period: int = 14,
        vol_period: int = 168,
        threshold: float = 0.4,
        w_adx: float = 0.40,
        w_er: float = 0.35,
        w_vol: float = 0.25,
    ):
        """
        Args:
            period: ADX / efficiency-ratio lookback in bars.
            vol_period: Lookback for volatility z-score (longer window).
            threshold: Score below this → "choppy".
            w_adx, w_er, w_vol: Component weights (must sum to 1).
        """
        weight_sum = w_adx + w_er + w_vol
        if abs(weight_sum - 1.0) > 1e-6:
            raise ValueError(
                f"Regime filter weights must sum to 1.0, got {weight_sum:.4f} "
                f"(w_adx={w_adx}, w_er={w_er}, w_vol={w_vol})"
            )
        self.period = period
        self.vol_period = vol_period
        self.threshold = threshold
        self.w_adx = w_adx
        self.w_er = w_er
        self.w_vol = w_vol

    @property
    def name(self) -> str:
        return f"Regime({self.period})"

    @property
    def columns(self) -> list[str]:
        p = self.period
        return [f"regime_{p}", f"regime_state_{p}"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.period
        high = df["high"]
        low = df["low"]
        close = df["close"]

        # ── 1. ADX component (0-1) ──────────────────────────────────────
        adx_norm = self._compute_adx_normalized(high, low, close, p, df.index)

        # ── 2. Efficiency ratio (0-1) ───────────────────────────────────
        er = self._compute_efficiency_ratio(close, p)

        # ── 3. Volatility z-score component (0-1 via sigmoid) ───────────
        vol_comp = self._compute_vol_zscore_component(close, self.vol_period)

        # ── Composite score (weighted, clamped 0-1) ─────────────────────
        score = self.w_adx * adx_norm + self.w_er * er + self.w_vol * vol_comp
        score = score.clip(0.0, 1.0)

        # ── State classification ────────────────────────────────────────
        state = pd.Series("choppy", index=df.index, dtype="object")
        state[score >= self.threshold] = "trending"

        df[f"regime_{p}"] = score
        df[f"regime_state_{p}"] = state

        return df

    # ------------------------------------------------------------------
    # Component helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_adx_normalized(
        high: pd.Series, low: pd.Series, close: pd.Series,
        period: int, index: pd.Index,
    ) -> pd.Series:
        """ADX normalized to 0-1 (adx / 50, capped at 1.0)."""
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low

        plus_dm = pd.Series(0.0, index=index)
        minus_dm = pd.Series(0.0, index=index)
        plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
        minus_dm[(down_move > up_move) & (down_move > 0)] = down_move

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        alpha = 1.0 / period
        atr = true_range.ewm(alpha=alpha, adjust=False).mean()
        plus_di = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr
        minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr

        dx = (plus_di - minus_di).abs() / (plus_di + minus_di) * 100
        dx = dx.fillna(0)
        adx = dx.ewm(alpha=alpha, adjust=False).mean()

        # Normalize: ADX 50+ is very strong trend → cap at 1.0
        return (adx / 50.0).clip(0.0, 1.0)

    @staticmethod
    def _compute_efficiency_ratio(close: pd.Series, period: int) -> pd.Series:
        """Kaufman-style efficiency ratio: |net move| / sum(|bar moves|).

        1.0 = perfectly directional (straight line), 0.0 = pure noise.
        """
        net_move = (close - close.shift(period)).abs()
        bar_moves = close.diff().abs().rolling(window=period).sum()
        # Avoid division by zero
        er = net_move / bar_moves.replace(0, np.nan)
        return er.fillna(0.0).clip(0.0, 1.0)

    @staticmethod
    def _compute_vol_zscore_component(
        close: pd.Series, vol_period: int,
    ) -> pd.Series:
        """Volatility z-score → sigmoid → 0-1.

        Positive z-score (vol expansion) maps toward 1.0 (trending signal).
        Negative z-score (vol contraction) maps toward 0.0 (choppy signal).
        """
        log_ret = np.log(close / close.shift(1))
        # Short-term vol (last vol_period//4 bars)
        short_window = max(2, vol_period // 4)
        short_vol = log_ret.rolling(window=short_window).std()
        # Long-term vol
        long_vol = log_ret.rolling(window=vol_period).std()
        long_vol_std = long_vol.rolling(window=vol_period).std()

        # Z-score
        zscore = (short_vol - long_vol) / long_vol_std.replace(0, np.nan)
        zscore = zscore.fillna(0.0)

        # Sigmoid mapping to [0, 1]: 1 / (1 + exp(-z))
        component = 1.0 / (1.0 + np.exp(-zscore))
        return component
