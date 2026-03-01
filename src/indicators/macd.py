import pandas as pd

from src.indicators.base import Indicator


class MACDIndicator(Indicator):
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast = fast
        self.slow = slow
        self.signal_period = signal

    @property
    def name(self) -> str:
        return f"MACD({self.fast},{self.slow},{self.signal_period})"

    @property
    def columns(self) -> list[str]:
        return ["macd", "macd_signal", "macd_hist"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        ema_fast = df["close"].ewm(span=self.fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=self.slow, adjust=False).mean()

        df["macd"] = ema_fast - ema_slow
        df["macd_signal"] = df["macd"].ewm(span=self.signal_period, adjust=False).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]

        return df
