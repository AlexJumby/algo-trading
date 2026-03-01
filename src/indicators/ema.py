import pandas as pd

from src.indicators.base import Indicator


class EMAIndicator(Indicator):
    def __init__(self, period: int = 20):
        self.period = period

    @property
    def name(self) -> str:
        return f"EMA({self.period})"

    @property
    def columns(self) -> list[str]:
        return [f"ema_{self.period}"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df[f"ema_{self.period}"] = df["close"].ewm(span=self.period, adjust=False).mean()
        return df
