"""Time-Series Momentum + Volatility Management Strategy (TSMOM).

Based on academic research:
    - Moskowitz, Ooi, Pedersen (2012) "Time Series Momentum"
    - AQR Capital / Man Group style trend following

Core concepts:
    1. Multi-period momentum: Weighted average of ROC across multiple lookback periods
       (short-term, medium-term, long-term) for robust trend detection.
    2. Volatility targeting: Scale position size so portfolio targets a specific
       annualized volatility. High vol = smaller positions, low vol = bigger positions.
       This is the key insight that makes professional trend-following work.
    3. Momentum quality filter: ADX ensures we only trade in trending markets.
    4. ATR trailing stop: No fixed TP — let winners run, cut losers.
    5. Drawdown scaling: Reduce position size after drawdowns (risk-off).

Why this beats EMA crossover:
    - EMA crossover is a lagging signal that catches the MIDDLE of moves
    - TSMOM captures the statistically proven tendency for trends to PERSIST
    - Vol targeting makes returns more consistent across market regimes
    - Multiple lookback periods are more robust than a single crossover
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.core.config import StrategyConfig
from src.core.enums import SignalAction
from src.core.models import Fill, Signal
from src.indicators.adx import ADXIndicator
from src.indicators.atr import ATRIndicator
from src.indicators.ema import EMAIndicator
from src.indicators.realized_vol import RealizedVolatility
from src.indicators.roc import ROCIndicator
from src.strategies.base import BaseStrategy


class TSMOMStrategy(BaseStrategy):
    """Time-Series Momentum with volatility management."""

    def setup(self, config: StrategyConfig) -> None:
        p = config.params

        # --- Momentum lookback periods (in hours) ---
        self.roc_short = p.get("roc_short", 24)       # 1 day
        self.roc_medium = p.get("roc_medium", 168)     # 7 days
        self.roc_long = p.get("roc_long", 720)         # 30 days

        # --- Momentum weights ---
        self.w_short = p.get("w_short", 0.20)
        self.w_medium = p.get("w_medium", 0.40)
        self.w_long = p.get("w_long", 0.40)

        # --- Entry threshold: composite momentum score must exceed this ---
        self.entry_threshold = p.get("entry_threshold", 0.01)  # 1%

        # --- Volatility targeting ---
        self.vol_lookback = p.get("vol_lookback", 168)     # 7 days
        self.target_vol = p.get("target_vol", 0.40)        # 40% annualized target
        self.max_vol_scalar = p.get("max_vol_scalar", 3.0)  # Max position scale
        self.min_vol_scalar = p.get("min_vol_scalar", 0.2)  # Min position scale

        # --- ADX trend filter ---
        self.adx_period = p.get("adx_period", 14)
        self.adx_threshold = p.get("adx_threshold", 20)

        # --- Trend EMA (directional filter) ---
        self.trend_ema_period = p.get("trend_ema", 200)

        # --- ATR for stop-loss ---
        self.atr_period = p.get("atr_period", 14)
        self.atr_sl_mult = p.get("atr_sl_mult", 2.0)

        # --- Cooldown after position close ---
        self.cooldown_bars = p.get("cooldown_bars", 12)

        # --- Max holding period (bars) — 0 = disabled ---
        self.max_hold_bars = p.get("max_hold_bars", 0)

        # --- Internal state ---
        self._bars_since_fill = 999
        self._bars_in_position = 0
        self._in_position = False

        # --- Indicators ---
        self.indicators = [
            ROCIndicator(self.roc_short),
            ROCIndicator(self.roc_medium),
            ROCIndicator(self.roc_long),
            RealizedVolatility(self.vol_lookback),
            ADXIndicator(self.adx_period),
            ATRIndicator(self.atr_period),
            EMAIndicator(self.trend_ema_period),
        ]

    def on_fill(self, fill: Fill) -> None:
        self._bars_since_fill = 0
        # Toggle position tracking
        if self._in_position:
            # This is a close fill
            self._in_position = False
            self._bars_in_position = 0
        else:
            # This is an open fill
            self._in_position = True
            self._bars_in_position = 0

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        self._bars_since_fill += 1
        if self._in_position:
            self._bars_in_position += 1

        if len(df) < 3:
            return []

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        # --- Column names ---
        roc_s = f"roc_{self.roc_short}"
        roc_m = f"roc_{self.roc_medium}"
        roc_l = f"roc_{self.roc_long}"
        rvol_col = f"rvol_{self.vol_lookback}"
        adx_col = f"adx_{self.adx_period}"
        di_plus = f"di_plus_{self.adx_period}"
        di_minus = f"di_minus_{self.adx_period}"
        atr_col = f"atr_{self.atr_period}"
        ema_col = f"ema_{self.trend_ema_period}"

        # Check all required columns exist and are not NaN
        required = [roc_s, roc_m, roc_l, rvol_col, adx_col, atr_col, ema_col]
        if any(pd.isna(curr.get(col)) for col in required):
            return []

        # --- Extract values ---
        close = float(curr["close"])
        roc_short_val = float(curr[roc_s])
        roc_med_val = float(curr[roc_m])
        roc_long_val = float(curr[roc_l])
        realized_vol = float(curr[rvol_col])
        adx = float(curr[adx_col])
        di_p = float(curr[di_plus])
        di_m = float(curr[di_minus])
        atr = float(curr[atr_col])
        trend = float(curr[ema_col])

        # Previous bar momentum (for momentum change detection)
        prev_roc_s = float(prev[roc_s]) if not pd.isna(prev.get(roc_s)) else 0.0
        prev_roc_m = float(prev[roc_m]) if not pd.isna(prev.get(roc_m)) else 0.0
        prev_roc_l = float(prev[roc_l]) if not pd.isna(prev.get(roc_l)) else 0.0

        # --- Composite momentum score ---
        mom_score = (
            self.w_short * roc_short_val
            + self.w_medium * roc_med_val
            + self.w_long * roc_long_val
        )

        prev_mom_score = (
            self.w_short * prev_roc_s
            + self.w_medium * prev_roc_m
            + self.w_long * prev_roc_l
        )

        # --- Volatility scalar ---
        # vol_scalar = target_vol / realized_vol (clamped)
        if realized_vol > 0.01:
            vol_scalar = self.target_vol / realized_vol
            vol_scalar = max(self.min_vol_scalar, min(vol_scalar, self.max_vol_scalar))
        else:
            vol_scalar = 1.0

        # --- Filters ---
        trending = adx > self.adx_threshold
        in_cooldown = self._bars_since_fill < self.cooldown_bars

        signals = []

        # --- EXIT SIGNALS (check first) ---
        if self._in_position:
            # Max hold period exit
            if self.max_hold_bars > 0 and self._bars_in_position >= self.max_hold_bars:
                signals.append(Signal(
                    timestamp=int(curr["timestamp"]),
                    symbol="",
                    action=SignalAction.CLOSE,
                    strength=1.0,
                    metadata={"trigger": "max_hold_exit", "bars_held": self._bars_in_position},
                ))
                return signals

            # Momentum reversal exit: composite score flips sign or drops below threshold
            momentum_reversed = (
                (mom_score < -self.entry_threshold / 2 and prev_mom_score > 0)
                or (mom_score > self.entry_threshold / 2 and prev_mom_score < 0)
            )

            if momentum_reversed:
                signals.append(Signal(
                    timestamp=int(curr["timestamp"]),
                    symbol="",
                    action=SignalAction.CLOSE,
                    strength=1.0,
                    metadata={
                        "trigger": "momentum_reversal",
                        "mom_score": mom_score,
                        "prev_mom_score": prev_mom_score,
                    },
                ))
                return signals

        # --- ENTRY SIGNALS ---
        if not self._in_position and not in_cooldown:
            # --- LONG entry ---
            long_conditions = (
                mom_score > self.entry_threshold
                and trending
                and close > trend               # Above trend EMA
                and di_p > di_m                  # +DI > -DI (bullish directional)
                and roc_short_val > 0            # Short-term momentum positive
            )

            # --- SHORT entry ---
            short_conditions = (
                mom_score < -self.entry_threshold
                and trending
                and close < trend               # Below trend EMA
                and di_m > di_p                  # -DI > +DI (bearish directional)
                and roc_short_val < 0            # Short-term momentum negative
            )

            if long_conditions:
                # Strength = vol_scalar (capped at 1.0 for position sizer)
                strength = min(vol_scalar, 1.0)

                signals.append(Signal(
                    timestamp=int(curr["timestamp"]),
                    symbol="",
                    action=SignalAction.LONG,
                    strength=strength,
                    metadata={
                        "atr": atr,
                        "atr_sl": atr * self.atr_sl_mult,
                        "no_tp": True,
                        "trigger": "tsmom_long",
                        "mom_score": round(mom_score, 4),
                        "vol_scalar": round(vol_scalar, 2),
                        "realized_vol": round(realized_vol, 4),
                        "adx": round(adx, 1),
                    },
                ))

            elif short_conditions:
                strength = min(vol_scalar, 1.0)

                signals.append(Signal(
                    timestamp=int(curr["timestamp"]),
                    symbol="",
                    action=SignalAction.SHORT,
                    strength=strength,
                    metadata={
                        "atr": atr,
                        "atr_sl": atr * self.atr_sl_mult,
                        "no_tp": True,
                        "trigger": "tsmom_short",
                        "mom_score": round(mom_score, 4),
                        "vol_scalar": round(vol_scalar, 2),
                        "realized_vol": round(realized_vol, 4),
                        "adx": round(adx, 1),
                    },
                ))

        return signals
