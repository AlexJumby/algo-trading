"""Breakout Trend-Following Strategy.

Designed to capture large price swings (20-100%+ moves) in crypto.

Core logic:
    1. ENTRY: Price breaks above Donchian Channel high (LONG) or below low (SHORT)
    2. FILTER: ADX > threshold (trending market, avoid choppy sideways)
    3. FILTER: EMA trend direction confirmation
    4. EXIT: ATR trailing stop (no fixed TP — let winners run)
    5. EXIT: Price crosses back below Donchian midline (early exit if trend weakens)

Key differences from EMA crossover:
    - Catches the START of big moves (breakout), not the middle (crossover)
    - Uses trailing stop to ride entire trends
    - ADX filter avoids whipsaw-heavy ranging markets
    - Designed for leveraged futures (position sizer uses leverage)
"""
from __future__ import annotations

import pandas as pd

from src.core.config import StrategyConfig
from src.core.enums import SignalAction
from src.core.models import Fill, Signal
from src.indicators.adx import ADXIndicator
from src.indicators.atr import ATRIndicator
from src.indicators.bbands import BollingerBands
from src.indicators.donchian import DonchianChannel
from src.indicators.ema import EMAIndicator
from src.strategies.base import BaseStrategy


class BreakoutTrendStrategy(BaseStrategy):
    """Donchian breakout + ADX + ATR trailing stop."""

    def setup(self, config: StrategyConfig) -> None:
        p = config.params

        # Donchian
        self.dc_entry_period = p.get("dc_entry_period", 48)  # ~2 days on 1h
        self.dc_exit_period = p.get("dc_exit_period", 24)   # ~1 day on 1h

        # ADX filter
        self.adx_period = p.get("adx_period", 14)
        self.adx_threshold = p.get("adx_threshold", 20)

        # Trend EMA
        self.trend_ema = p.get("trend_ema", 100)

        # ATR for SL
        self.atr_period = p.get("atr_period", 14)
        self.atr_sl_mult = p.get("atr_sl_mult", 2.0)

        # Cooldown
        self.cooldown_bars = p.get("cooldown_bars", 6)

        # BB squeeze detection (optional)
        self.bb_period = p.get("bb_period", 20)
        self.bb_squeeze_threshold = p.get("bb_squeeze_threshold", 0.0)  # 0 = disabled

        self._bars_since_fill = 999
        self._last_position_side = None  # track to avoid re-entry same direction

        self.indicators = [
            DonchianChannel(self.dc_entry_period),
            DonchianChannel(self.dc_exit_period),
            ADXIndicator(self.adx_period),
            ATRIndicator(self.atr_period),
            EMAIndicator(self.trend_ema),
            BollingerBands(self.bb_period),
        ]

    def on_fill(self, fill: Fill) -> None:
        self._bars_since_fill = 0

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        self._bars_since_fill += 1

        if len(df) < 3:
            return []

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        dc_entry_h = f"dc_{self.dc_entry_period}_high"
        dc_entry_l = f"dc_{self.dc_entry_period}_low"
        dc_exit_h = f"dc_{self.dc_exit_period}_high"
        dc_exit_l = f"dc_{self.dc_exit_period}_low"
        dc_exit_mid = f"dc_{self.dc_exit_period}_mid"
        adx_col = f"adx_{self.adx_period}"
        di_plus = f"di_plus_{self.adx_period}"
        di_minus = f"di_minus_{self.adx_period}"
        atr_col = f"atr_{self.atr_period}"
        ema_col = f"ema_{self.trend_ema}"
        bb_width = f"bb_{self.bb_period}_width"

        required = [dc_entry_h, dc_entry_l, dc_exit_mid, adx_col, atr_col, ema_col]
        if any(pd.isna(curr.get(col)) for col in required):
            return []

        close = float(curr["close"])
        high = float(curr["high"])
        low = float(curr["low"])
        prev_close = float(prev["close"])
        adx = float(curr[adx_col])
        atr = float(curr[atr_col])
        trend = float(curr[ema_col])
        di_p = float(curr[di_plus])
        di_m = float(curr[di_minus])

        # Previous bar's Donchian levels (use shift to avoid lookahead)
        prev_dc_high = float(prev[dc_entry_h]) if not pd.isna(prev[dc_entry_h]) else None
        prev_dc_low = float(prev[dc_entry_l]) if not pd.isna(prev[dc_entry_l]) else None
        dc_mid = float(curr[dc_exit_mid])

        if prev_dc_high is None or prev_dc_low is None:
            return []

        in_cooldown = self._bars_since_fill < self.cooldown_bars

        # BB squeeze filter (optional)
        squeeze_ok = True
        if self.bb_squeeze_threshold > 0 and bb_width in df.columns:
            bw = float(curr[bb_width]) if not pd.isna(curr.get(bb_width)) else 999
            # Squeeze = low bandwidth. After squeeze, look for expansion.
            prev_bw = float(prev[bb_width]) if not pd.isna(prev.get(bb_width)) else 999
            squeeze_ok = bw > prev_bw  # bandwidth expanding (breakout from squeeze)

        signals = []

        # ---- BREAKOUT LONG ----
        # Close breaks above previous Donchian high + ADX trending + above EMA
        breakout_long = (
            close > prev_dc_high
            and prev_close <= prev_dc_high
            and adx > self.adx_threshold
            and close > trend
            and di_p > di_m
            and not in_cooldown
            and squeeze_ok
        )

        # ---- BREAKOUT SHORT ----
        breakout_short = (
            close < prev_dc_low
            and prev_close >= prev_dc_low
            and adx > self.adx_threshold
            and close < trend
            and di_m > di_p
            and not in_cooldown
            and squeeze_ok
        )

        if breakout_long:
            signals.append(Signal(
                timestamp=int(curr["timestamp"]),
                symbol="",
                action=SignalAction.LONG,
                strength=1.0,
                metadata={
                    "atr": atr,
                    "atr_sl": atr * self.atr_sl_mult,
                    "adx": adx,
                    "no_tp": True,
                    "trigger": "donchian_breakout_long",
                },
            ))

        elif breakout_short:
            signals.append(Signal(
                timestamp=int(curr["timestamp"]),
                symbol="",
                action=SignalAction.SHORT,
                strength=1.0,
                metadata={
                    "atr": atr,
                    "atr_sl": atr * self.atr_sl_mult,
                    "adx": adx,
                    "no_tp": True,
                    "trigger": "donchian_breakout_short",
                },
            ))

        # ---- EXIT: price crosses Donchian midline against position ----
        # (only if no new entry signal generated this bar)
        if not signals:
            # For longs: exit if close drops below exit Donchian midline
            # For shorts: exit if close rises above exit Donchian midline
            if close < dc_mid or close > dc_mid:
                signals.append(Signal(
                    timestamp=int(curr["timestamp"]),
                    symbol="",
                    action=SignalAction.CLOSE,
                    strength=1.0,
                    metadata={"trigger": "donchian_mid_exit", "dc_mid": dc_mid},
                ))

        return signals
