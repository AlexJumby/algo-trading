"""Rate of Change (ROC) indicator — core of time-series momentum.

ROC = (close - close[n]) / close[n]

Measures the percentage change over `period` bars.
Positive ROC → upward momentum, Negative → downward.
"""
import pandas as pd

from src.indicators.base import Indicator


class ROCIndicator(Indicator):
    """Rate of Change over a lookback period."""

    def __init__(self, period: int = 24):
        self.period = period

    @property
    def name(self) -> str:
        return f"ROC({self.period})"

    @property
    def columns(self) -> list[str]:
        return [f"roc_{self.period}"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        shifted = df["close"].shift(self.period)
        df[f"roc_{self.period}"] = (df["close"] - shifted) / shifted
        return df
