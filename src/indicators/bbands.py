import pandas as pd

from src.indicators.base import Indicator


class BollingerBands(Indicator):
    """Bollinger Bands — volatility envelope around SMA.

    Columns added:
        bb_{period}_upper: upper band (SMA + mult * stddev)
        bb_{period}_lower: lower band (SMA - mult * stddev)
        bb_{period}_mid:   middle band (SMA)
        bb_{period}_width: bandwidth (upper - lower) / mid — measures squeeze
    """

    def __init__(self, period: int = 20, mult: float = 2.0):
        self.period = period
        self.mult = mult

    @property
    def name(self) -> str:
        return f"BB({self.period},{self.mult})"

    @property
    def columns(self) -> list[str]:
        p = self.period
        return [f"bb_{p}_upper", f"bb_{p}_lower", f"bb_{p}_mid", f"bb_{p}_width"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.period
        sma = df["close"].rolling(window=p).mean()
        std = df["close"].rolling(window=p).std()

        df[f"bb_{p}_mid"] = sma
        df[f"bb_{p}_upper"] = sma + self.mult * std
        df[f"bb_{p}_lower"] = sma - self.mult * std
        df[f"bb_{p}_width"] = (df[f"bb_{p}_upper"] - df[f"bb_{p}_lower"]) / sma

        return df
