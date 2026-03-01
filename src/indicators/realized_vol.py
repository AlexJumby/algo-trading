"""Realized Volatility indicator for volatility targeting.

Measures recent annualized volatility using standard deviation of log returns.

For 1h bars: annualization factor = sqrt(8760) (hours per year).

Used by TSMOM strategy to:
    1. Scale position sizes inversely with volatility (vol targeting)
    2. Normalize momentum signals across different vol regimes
"""
import numpy as np
import pandas as pd

from src.indicators.base import Indicator

# Hours in a year (365.25 * 24)
HOURS_PER_YEAR = 8766


class RealizedVolatility(Indicator):
    """Rolling annualized realized volatility from hourly returns."""

    def __init__(self, period: int = 168):
        """
        Args:
            period: Lookback window in bars (default 168 = 7 days of 1h bars).
        """
        self.period = period

    @property
    def name(self) -> str:
        return f"RealVol({self.period})"

    @property
    def columns(self) -> list[str]:
        return [f"rvol_{self.period}"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        log_ret = np.log(df["close"] / df["close"].shift(1))
        rolling_std = log_ret.rolling(window=self.period).std()
        # Annualize: std * sqrt(periods_per_year)
        df[f"rvol_{self.period}"] = rolling_std * np.sqrt(HOURS_PER_YEAR)
        return df
