"""Realized Volatility indicator for volatility targeting.

Measures recent annualized volatility using log returns.

Supports two modes:
    - "simple": Rolling standard deviation (all points equally weighted)
    - "ewma":   Exponentially weighted — reacts faster to vol regime shifts

The annualization factor is configurable so the indicator works with any
bar timeframe (1h, 4h, 1d, etc.).

Used by TSMOM strategy to:
    1. Scale position sizes inversely with volatility (vol targeting)
    2. Normalize momentum signals across different vol regimes
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from src.indicators.base import Indicator

# Hours in a year (365.25 * 24) — default annualization for 1h bars
HOURS_PER_YEAR = 8766


class RealizedVolatility(Indicator):
    """Rolling annualized realized volatility."""

    def __init__(
        self,
        period: int = 168,
        annualization_factor: Optional[float] = None,
        mode: str = "simple",
    ):
        """
        Args:
            period: Lookback window in bars (default 168 = 7 days of 1h bars).
            annualization_factor: Number of bars per year. Defaults to
                HOURS_PER_YEAR (8766) for backward compat with 1h data.
            mode: "simple" (rolling std) or "ewma" (exponentially weighted).
        """
        self.period = period
        self.ann_factor = (
            annualization_factor if annualization_factor is not None else HOURS_PER_YEAR
        )
        if mode not in ("simple", "ewma"):
            raise ValueError(f"Unknown vol mode '{mode}'. Use 'simple' or 'ewma'.")
        self.mode = mode

    @property
    def name(self) -> str:
        return f"RealVol({self.period})"

    @property
    def columns(self) -> list[str]:
        return [f"rvol_{self.period}"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        log_ret = np.log(df["close"] / df["close"].shift(1))

        if self.mode == "ewma":
            # EWMA variance → sqrt → annualize
            ewma_var = (log_ret ** 2).ewm(span=self.period, min_periods=2).mean()
            df[f"rvol_{self.period}"] = np.sqrt(ewma_var) * np.sqrt(self.ann_factor)
        else:
            # Simple rolling std → annualize
            rolling_std = log_ret.rolling(window=self.period).std()
            df[f"rvol_{self.period}"] = rolling_std * np.sqrt(self.ann_factor)

        return df
