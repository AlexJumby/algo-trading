import pandas as pd

from src.indicators.base import Indicator


class ATRIndicator(Indicator):
    """Average True Range — measures volatility."""

    def __init__(self, period: int = 14):
        self.period = period

    @property
    def name(self) -> str:
        return f"ATR({self.period})"

    @property
    def columns(self) -> list[str]:
        return [f"atr_{self.period}"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"]
        low = df["low"]
        close = df["close"]

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df[f"atr_{self.period}"] = true_range.ewm(span=self.period, adjust=False).mean()

        return df
