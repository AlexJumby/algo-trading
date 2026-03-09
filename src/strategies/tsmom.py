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

import pandas as pd

from src.core.config import StrategyConfig, bars_per_year, hours_to_bars
from src.core.enums import SignalAction
from src.core.models import Fill, Signal
from src.indicators.adx import ADXIndicator
from src.indicators.atr import ATRIndicator
from src.indicators.ema import EMAIndicator
from src.indicators.realized_vol import RealizedVolatility
from src.indicators.regime import RegimeFilter
from src.indicators.roc import ROCIndicator
from src.strategies.base import BaseStrategy


class TSMOMStrategy(BaseStrategy):
    """Time-Series Momentum with volatility management."""

    def setup(self, config: StrategyConfig) -> None:
        p = config.params

        # --- Timeframe (injected by run_backtest / run_live) ---
        tf = p.get("timeframe", "1h")
        self._timeframe = tf
        self._bars_per_year = bars_per_year(tf)

        # --- Momentum lookback periods (config values are in HOURS) ---
        # Convert hours → bar counts for the active timeframe.
        # On 1h these produce identical values to the old code.
        self.roc_short = hours_to_bars(p.get("roc_short", 24), tf)     # 1 day
        self.roc_medium = hours_to_bars(p.get("roc_medium", 168), tf)  # 7 days
        self.roc_long = hours_to_bars(p.get("roc_long", 720), tf)      # 30 days

        # --- Momentum weights ---
        self.w_short = p.get("w_short", 0.20)
        self.w_medium = p.get("w_medium", 0.40)
        self.w_long = p.get("w_long", 0.40)

        # --- Entry threshold: composite momentum score must exceed this ---
        self.entry_threshold = p.get("entry_threshold", 0.01)  # 1%

        # --- Volatility targeting ---
        self.vol_lookback = hours_to_bars(p.get("vol_lookback", 168), tf)  # 7 days
        self.target_vol = p.get("target_vol", 0.40)        # 40% annualized target
        self.max_vol_scalar = p.get("max_vol_scalar", 3.0)  # Max position scale
        self.min_vol_scalar = p.get("min_vol_scalar", 0.2)  # Min position scale

        # --- ADX trend filter (already in bars — do NOT convert) ---
        self.adx_period = p.get("adx_period", 14)
        self.adx_threshold = p.get("adx_threshold", 20)

        # --- Trend EMA (hours → bars) ---
        self.trend_ema_period = hours_to_bars(p.get("trend_ema", 200), tf)

        # --- ATR for stop-loss (already in bars — do NOT convert) ---
        self.atr_period = p.get("atr_period", 14)
        self.atr_sl_mult = p.get("atr_sl_mult", 2.0)

        # --- Cooldown after position close (already in bars) ---
        self.cooldown_bars = p.get("cooldown_bars", 12)

        # --- Max holding period (bars) — 0 = disabled ---
        self.max_hold_bars = p.get("max_hold_bars", 0)

        # --- Volatility mode ---
        self.vol_mode = p.get("vol_mode", "simple")

        # --- Regime filter ---
        self.regime_enabled = p.get("regime_enabled", True)
        self.regime_period = p.get("regime_period", self.adx_period)
        self.regime_threshold = p.get("regime_threshold", 0.4)

        # --- Per-symbol state ---
        self._state: dict[str, dict] = {}

        # --- Indicators ---
        self.indicators = [
            ROCIndicator(self.roc_short),
            ROCIndicator(self.roc_medium),
            ROCIndicator(self.roc_long),
            RealizedVolatility(
                self.vol_lookback,
                annualization_factor=self._bars_per_year,
                mode=self.vol_mode,
            ),
            ADXIndicator(self.adx_period),
            ATRIndicator(self.atr_period),
            EMAIndicator(self.trend_ema_period),
        ]
        if self.regime_enabled:
            self.indicators.append(
                RegimeFilter(
                    period=self.regime_period,
                    vol_period=self.vol_lookback,
                    threshold=self.regime_threshold,
                )
            )

    def _get_state(self, symbol: str) -> dict:
        """Get per-symbol state, creating defaults if needed."""
        if symbol not in self._state:
            self._state[symbol] = {
                "bars_since_fill": 999,
                "bars_in_position": 0,
                "in_position": False,
            }
        return self._state[symbol]

    def on_fill(self, fill: Fill) -> None:
        st = self._get_state(fill.symbol)
        st["bars_since_fill"] = 0
        if st["in_position"]:
            st["in_position"] = False
            st["bars_in_position"] = 0
        else:
            st["in_position"] = True
            st["bars_in_position"] = 0

    def sync_state(self, portfolio) -> None:
        """Sync per-symbol state with actual portfolio positions."""
        for symbol, pos in portfolio.open_positions.items():
            st = self._get_state(symbol)
            st["in_position"] = True

    def generate_signals(self, df: pd.DataFrame, symbol: str = "") -> list[Signal]:
        st = self._get_state(symbol)
        st["bars_since_fill"] += 1
        if st["in_position"]:
            st["bars_in_position"] += 1

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

        # --- Regime filter ---
        regime_state = None
        regime_score = None
        if self.regime_enabled:
            regime_col = f"regime_state_{self.regime_period}"
            regime_score_col = f"regime_{self.regime_period}"
            regime_state = str(curr.get(regime_col, "trending"))
            regime_score = float(curr.get(regime_score_col, 0.5))

        # --- Filters ---
        trending = adx > self.adx_threshold
        in_cooldown = st["bars_since_fill"] < self.cooldown_bars

        signals = []

        # --- EXIT SIGNALS (check first) ---
        if st["in_position"]:
            # Max hold period exit
            if self.max_hold_bars > 0 and st["bars_in_position"] >= self.max_hold_bars:
                signals.append(Signal(
                    timestamp=int(curr["timestamp"]),
                    symbol="",
                    action=SignalAction.CLOSE,
                    strength=1.0,
                    metadata={"trigger": "max_hold_exit", "bars_held": st["bars_in_position"]},
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
        # Regime filter: skip entries in choppy markets
        if self.regime_enabled and regime_state == "choppy":
            return signals  # Only exits above, no new entries

        if not st["in_position"] and not in_cooldown:
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
                # vol_scalar passed via metadata so PositionSizer can
                # scale UP or DOWN (Signal.strength is capped at 1.0).
                signals.append(Signal(
                    timestamp=int(curr["timestamp"]),
                    symbol="",
                    action=SignalAction.LONG,
                    strength=1.0,
                    metadata={
                        "atr": atr,
                        "atr_sl": atr * self.atr_sl_mult,
                        "no_tp": True,
                        "trigger": "tsmom_long",
                        "mom_score": round(mom_score, 4),
                        "vol_scalar": round(vol_scalar, 2),
                        "realized_vol": round(realized_vol, 4),
                        "adx": round(adx, 1),
                        "regime_score": (
                            round(regime_score, 2) if regime_score is not None else None
                        ),
                    },
                ))

            elif short_conditions:
                signals.append(Signal(
                    timestamp=int(curr["timestamp"]),
                    symbol="",
                    action=SignalAction.SHORT,
                    strength=1.0,
                    metadata={
                        "atr": atr,
                        "atr_sl": atr * self.atr_sl_mult,
                        "no_tp": True,
                        "trigger": "tsmom_short",
                        "mom_score": round(mom_score, 4),
                        "vol_scalar": round(vol_scalar, 2),
                        "realized_vol": round(realized_vol, 4),
                        "adx": round(adx, 1),
                        "regime_score": (
                            round(regime_score, 2) if regime_score is not None else None
                        ),
                    },
                ))

        return signals
