import pandas as pd

from src.indicators.base import Indicator


class RSIIndicator(Indicator):
    def __init__(self, period: int = 14):
        self.period = period

    @property
    def name(self) -> str:
        return f"RSI({self.period})"

    @property
    def columns(self) -> list[str]:
        return [f"rsi_{self.period}"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)

        avg_gain = gain.ewm(alpha=1 / self.period, min_periods=self.period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / self.period, min_periods=self.period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, float("inf"))
        rsi = 100 - (100 / (1 + rs))

        df[f"rsi_{self.period}"] = rsi
        return df
