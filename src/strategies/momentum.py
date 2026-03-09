from __future__ import annotations

import pandas as pd

from src.core.config import StrategyConfig
from src.core.enums import SignalAction
from src.core.models import Signal
from src.indicators.atr import ATRIndicator
from src.indicators.ema import EMAIndicator
from src.indicators.macd import MACDIndicator
from src.indicators.rsi import RSIIndicator
from src.strategies.base import BaseStrategy


class MomentumStrategy(BaseStrategy):
    """Original EMA crossover + RSI + MACD. Kept for backwards compatibility."""

    def setup(self, config: StrategyConfig) -> None:
        params = config.params
        self.fast_period = params.get("fast_ema", 12)
        self.slow_period = params.get("slow_ema", 26)
        self.rsi_period = params.get("rsi_period", 14)
        self.rsi_overbought = params.get("rsi_overbought", 70)
        self.rsi_oversold = params.get("rsi_oversold", 30)
        self.macd_fast = params.get("macd_fast", 12)
        self.macd_slow = params.get("macd_slow", 26)
        self.macd_signal = params.get("macd_signal", 9)

        self.indicators = [
            EMAIndicator(self.fast_period),
            EMAIndicator(self.slow_period),
            RSIIndicator(self.rsi_period),
            MACDIndicator(self.macd_fast, self.macd_slow, self.macd_signal),
        ]

    def generate_signals(self, df: pd.DataFrame, symbol: str = "") -> list[Signal]:
        if len(df) < 2:
            return []

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        fast_col = f"ema_{self.fast_period}"
        slow_col = f"ema_{self.slow_period}"
        rsi_col = f"rsi_{self.rsi_period}"

        if any(pd.isna(curr[col]) for col in [fast_col, slow_col, rsi_col, "macd_hist"]):
            return []

        cross_up = prev[fast_col] <= prev[slow_col] and curr[fast_col] > curr[slow_col]
        cross_down = prev[fast_col] >= prev[slow_col] and curr[fast_col] < curr[slow_col]

        rsi_val = float(curr[rsi_col])
        macd_hist = float(curr["macd_hist"])

        signals = []

        if cross_up and rsi_val < self.rsi_overbought and macd_hist > 0:
            signals.append(Signal(
                timestamp=int(curr["timestamp"]),
                symbol="",
                action=SignalAction.LONG,
                strength=min(abs(macd_hist) / 100, 1.0),
                metadata={"rsi": rsi_val, "macd_hist": macd_hist, "trigger": "ema_cross_up"},
            ))
        elif cross_down and rsi_val > self.rsi_oversold and macd_hist < 0:
            signals.append(Signal(
                timestamp=int(curr["timestamp"]),
                symbol="",
                action=SignalAction.SHORT,
                strength=min(abs(macd_hist) / 100, 1.0),
                metadata={"rsi": rsi_val, "macd_hist": macd_hist, "trigger": "ema_cross_down"},
            ))

        if rsi_val >= self.rsi_overbought or rsi_val <= self.rsi_oversold:
            signals.append(Signal(
                timestamp=int(curr["timestamp"]),
                symbol="",
                action=SignalAction.CLOSE,
                strength=1.0,
                metadata={"rsi": rsi_val, "trigger": "rsi_extreme"},
            ))

        return signals


class MomentumV2Strategy(BaseStrategy):
    """Improved momentum strategy with:
    - Trend filter: 200 EMA — only trade in direction of major trend
    - ATR-based dynamic SL/TP instead of fixed %
    - MACD histogram must be increasing (momentum growing)
    - Volume confirmation — above 20-period average
    - No RSI exit — rely on opposite crossover or SL/TP
    """

    def setup(self, config: StrategyConfig) -> None:
        params = config.params
        self.fast_period = params.get("fast_ema", 9)
        self.slow_period = params.get("slow_ema", 21)
        self.trend_period = params.get("trend_ema", 200)
        self.rsi_period = params.get("rsi_period", 14)
        self.rsi_overbought = params.get("rsi_overbought", 65)
        self.rsi_oversold = params.get("rsi_oversold", 35)
        self.macd_fast = params.get("macd_fast", 12)
        self.macd_slow = params.get("macd_slow", 26)
        self.macd_signal = params.get("macd_signal", 9)
        self.atr_period = params.get("atr_period", 14)
        self.atr_sl_mult = params.get("atr_sl_mult", 2.0)
        self.atr_tp_mult = params.get("atr_tp_mult", 3.0)
        self.volume_period = params.get("volume_period", 20)
        self.require_volume = params.get("require_volume", True)

        self.indicators = [
            EMAIndicator(self.fast_period),
            EMAIndicator(self.slow_period),
            EMAIndicator(self.trend_period),
            RSIIndicator(self.rsi_period),
            MACDIndicator(self.macd_fast, self.macd_slow, self.macd_signal),
            ATRIndicator(self.atr_period),
        ]

    def generate_signals(self, df: pd.DataFrame, symbol: str = "") -> list[Signal]:
        if len(df) < 3:
            return []

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3]

        fast_col = f"ema_{self.fast_period}"
        slow_col = f"ema_{self.slow_period}"
        trend_col = f"ema_{self.trend_period}"
        rsi_col = f"rsi_{self.rsi_period}"
        atr_col = f"atr_{self.atr_period}"

        required_cols = [fast_col, slow_col, trend_col, rsi_col, "macd_hist", atr_col]
        if any(pd.isna(curr[col]) for col in required_cols):
            return []

        # ---- Filters ----
        close = float(curr["close"])
        trend_ema = float(curr[trend_col])
        rsi_val = float(curr[rsi_col])
        macd_hist = float(curr["macd_hist"])
        macd_hist_prev = float(prev["macd_hist"])
        atr = float(curr[atr_col])

        # Trend direction (price vs 200 EMA)
        is_uptrend = close > trend_ema
        is_downtrend = close < trend_ema

        # EMA crossover detection
        cross_up = prev[fast_col] <= prev[slow_col] and curr[fast_col] > curr[slow_col]
        cross_down = prev[fast_col] >= prev[slow_col] and curr[fast_col] < curr[slow_col]

        # MACD histogram must be growing in the signal direction
        macd_growing = macd_hist > macd_hist_prev
        macd_falling = macd_hist < macd_hist_prev

        # Volume confirmation: current volume > 20-period average
        vol_ok = True
        if self.require_volume and self.volume_period > 0:
            vol_avg = df["volume"].iloc[-self.volume_period:].mean()
            vol_ok = float(curr["volume"]) > vol_avg

        signals = []

        # ---- LONG entry ----
        if (cross_up
                and is_uptrend
                and rsi_val < self.rsi_overbought
                and rsi_val > self.rsi_oversold
                and macd_hist > 0
                and macd_growing
                and vol_ok):

            signals.append(Signal(
                timestamp=int(curr["timestamp"]),
                symbol="",
                action=SignalAction.LONG,
                strength=min(max(abs(macd_hist) / atr, 0.3), 1.0),
                metadata={
                    "rsi": rsi_val,
                    "macd_hist": macd_hist,
                    "atr": atr,
                    "atr_sl": atr * self.atr_sl_mult,
                    "atr_tp": atr * self.atr_tp_mult,
                    "trigger": "ema_cross_up_v2",
                },
            ))

        # ---- SHORT entry ----
        elif (cross_down
              and is_downtrend
              and rsi_val > self.rsi_oversold
              and rsi_val < self.rsi_overbought
              and macd_hist < 0
              and macd_falling
              and vol_ok):

            signals.append(Signal(
                timestamp=int(curr["timestamp"]),
                symbol="",
                action=SignalAction.SHORT,
                strength=min(max(abs(macd_hist) / atr, 0.3), 1.0),
                metadata={
                    "rsi": rsi_val,
                    "macd_hist": macd_hist,
                    "atr": atr,
                    "atr_sl": atr * self.atr_sl_mult,
                    "atr_tp": atr * self.atr_tp_mult,
                    "trigger": "ema_cross_down_v2",
                },
            ))

        # ---- EXIT on opposite crossover ----
        if cross_down and not signals:
            signals.append(Signal(
                timestamp=int(curr["timestamp"]),
                symbol="",
                action=SignalAction.CLOSE,
                strength=1.0,
                metadata={"trigger": "ema_cross_down_exit"},
            ))
        elif cross_up and not signals:
            signals.append(Signal(
                timestamp=int(curr["timestamp"]),
                symbol="",
                action=SignalAction.CLOSE,
                strength=1.0,
                metadata={"trigger": "ema_cross_up_exit"},
            ))

        return signals


class MomentumV3Strategy(BaseStrategy):
    """V3: Trend-following with trailing stop & cooldown.

    Key improvements over V2:
    - Trailing stop instead of fixed TP (let winners run)
    - Cooldown period after a close (avoid whipsaws)
    - Simpler entry: EMA cross + trend filter + RSI filter (no MACD growth requirement)
    - Strength fixed at 1.0 (full position sizing, no signal strength scaling)

    Uses engine-level trailing stop via `trailing_atr_mult` param.
    """

    def setup(self, config: StrategyConfig) -> None:
        params = config.params
        self.fast_period = params.get("fast_ema", 8)
        self.slow_period = params.get("slow_ema", 26)
        self.trend_period = params.get("trend_ema", 200)
        self.rsi_period = params.get("rsi_period", 14)
        self.rsi_overbought = params.get("rsi_overbought", 65)
        self.rsi_oversold = params.get("rsi_oversold", 25)
        self.macd_fast = params.get("macd_fast", 12)
        self.macd_slow = params.get("macd_slow", 26)
        self.macd_signal = params.get("macd_signal", 9)
        self.atr_period = params.get("atr_period", 14)
        self.atr_sl_mult = params.get("atr_sl_mult", 1.5)
        self.cooldown_bars = params.get("cooldown_bars", 10)

        self._bars_since_close = 999  # start ready to trade

        self.indicators = [
            EMAIndicator(self.fast_period),
            EMAIndicator(self.slow_period),
            EMAIndicator(self.trend_period),
            RSIIndicator(self.rsi_period),
            MACDIndicator(self.macd_fast, self.macd_slow, self.macd_signal),
            ATRIndicator(self.atr_period),
        ]

    def on_fill(self, fill) -> None:
        """Reset cooldown counter on close fills."""
        # Any fill triggers cooldown reset — the engine calls on_fill for opens and closes
        self._bars_since_close = 0

    def generate_signals(self, df: pd.DataFrame, symbol: str = "") -> list[Signal]:
        self._bars_since_close += 1

        if len(df) < 3:
            return []

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        fast_col = f"ema_{self.fast_period}"
        slow_col = f"ema_{self.slow_period}"
        trend_col = f"ema_{self.trend_period}"
        rsi_col = f"rsi_{self.rsi_period}"
        atr_col = f"atr_{self.atr_period}"

        required_cols = [fast_col, slow_col, trend_col, rsi_col, "macd_hist", atr_col]
        if any(pd.isna(curr[col]) for col in required_cols):
            return []

        close = float(curr["close"])
        trend_ema = float(curr[trend_col])
        rsi_val = float(curr[rsi_col])
        macd_hist = float(curr["macd_hist"])
        atr = float(curr[atr_col])

        is_uptrend = close > trend_ema
        is_downtrend = close < trend_ema

        cross_up = prev[fast_col] <= prev[slow_col] and curr[fast_col] > curr[slow_col]
        cross_down = prev[fast_col] >= prev[slow_col] and curr[fast_col] < curr[slow_col]

        signals = []
        in_cooldown = self._bars_since_close < self.cooldown_bars

        # ---- LONG entry ----
        if (cross_up
                and is_uptrend
                and rsi_val < self.rsi_overbought
                and macd_hist > 0
                and not in_cooldown):
            signals.append(Signal(
                timestamp=int(curr["timestamp"]),
                symbol="",
                action=SignalAction.LONG,
                strength=1.0,
                metadata={
                    "atr": atr,
                    "atr_sl": atr * self.atr_sl_mult,
                    "trigger": "ema_cross_up_v3",
                },
            ))

        # ---- SHORT entry ----
        elif (cross_down
              and is_downtrend
              and rsi_val > self.rsi_oversold
              and macd_hist < 0
              and not in_cooldown):
            signals.append(Signal(
                timestamp=int(curr["timestamp"]),
                symbol="",
                action=SignalAction.SHORT,
                strength=1.0,
                metadata={
                    "atr": atr,
                    "atr_sl": atr * self.atr_sl_mult,
                    "trigger": "ema_cross_down_v3",
                },
            ))

        # ---- EXIT on opposite crossover ----
        if cross_down and not signals:
            signals.append(Signal(
                timestamp=int(curr["timestamp"]),
                symbol="",
                action=SignalAction.CLOSE,
                strength=1.0,
                metadata={"trigger": "ema_cross_exit_v3"},
            ))
        elif cross_up and not signals:
            signals.append(Signal(
                timestamp=int(curr["timestamp"]),
                symbol="",
                action=SignalAction.CLOSE,
                strength=1.0,
                metadata={"trigger": "ema_cross_exit_v3"},
            ))

        return signals


from src.strategies.breakout import BreakoutTrendStrategy
from src.strategies.tsmom import TSMOMStrategy

STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "momentum": MomentumStrategy,
    "momentum_v2": MomentumV2Strategy,
    "momentum_v3": MomentumV3Strategy,
    "breakout": BreakoutTrendStrategy,
    "tsmom": TSMOMStrategy,
}
