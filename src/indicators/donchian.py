import pandas as pd

from src.indicators.base import Indicator


class DonchianChannel(Indicator):
    """Donchian Channel — N-period high/low breakout levels.

    Columns added:
        dc_{period}_high: rolling highest high
        dc_{period}_low:  rolling lowest low
        dc_{period}_mid:  midpoint
    """

    def __init__(self, period: int = 20):
        self.period = period

    @property
    def name(self) -> str:
        return f"Donchian({self.period})"

    @property
    def columns(self) -> list[str]:
        p = self.period
        return [f"dc_{p}_high", f"dc_{p}_low", f"dc_{p}_mid"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.period
        df[f"dc_{p}_high"] = df["high"].rolling(window=p).max()
        df[f"dc_{p}_low"] = df["low"].rolling(window=p).min()
        df[f"dc_{p}_mid"] = (df[f"dc_{p}_high"] + df[f"dc_{p}_low"]) / 2
        return df
