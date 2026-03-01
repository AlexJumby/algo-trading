import pandas as pd

from src.indicators.base import Indicator


class ADXIndicator(Indicator):
    """Average Directional Index — measures trend strength (0-100).

    ADX > 25 = trending market, < 20 = ranging/choppy.

    Columns added:
        adx_{period}: the ADX line
        di_plus_{period}: +DI (positive directional indicator)
        di_minus_{period}: -DI (negative directional indicator)
    """

    def __init__(self, period: int = 14):
        self.period = period

    @property
    def name(self) -> str:
        return f"ADX({self.period})"

    @property
    def columns(self) -> list[str]:
        p = self.period
        return [f"adx_{p}", f"di_plus_{p}", f"di_minus_{p}"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.period
        high = df["high"]
        low = df["low"]
        close = df["close"]

        # Directional Movement
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low

        plus_dm = pd.Series(0.0, index=df.index)
        minus_dm = pd.Series(0.0, index=df.index)

        plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
        minus_dm[(down_move > up_move) & (down_move > 0)] = down_move

        # True Range
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Smoothed averages (Wilder's smoothing = EWM with alpha=1/period)
        atr = true_range.ewm(alpha=1.0 / p, adjust=False).mean()
        plus_dm_smooth = plus_dm.ewm(alpha=1.0 / p, adjust=False).mean()
        minus_dm_smooth = minus_dm.ewm(alpha=1.0 / p, adjust=False).mean()

        # Directional Indicators
        plus_di = 100 * plus_dm_smooth / atr
        minus_di = 100 * minus_dm_smooth / atr

        # ADX
        dx = (plus_di - minus_di).abs() / (plus_di + minus_di) * 100
        dx = dx.fillna(0)
        adx = dx.ewm(alpha=1.0 / p, adjust=False).mean()

        df[f"adx_{p}"] = adx
        df[f"di_plus_{p}"] = plus_di
        df[f"di_minus_{p}"] = minus_di

        return df
