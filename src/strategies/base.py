from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from src.core.config import StrategyConfig
from src.core.models import Fill, Signal
from src.indicators.base import Indicator


class BaseStrategy(ABC):
    """Base class for all trading strategies.
    The same strategy class is used by both live engine and backtest engine."""

    def __init__(self):
        self.indicators: list[Indicator] = []

    @abstractmethod
    def setup(self, config: StrategyConfig) -> None:
        """Initialize indicators and strategy parameters from config."""
        ...

    def apply_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        for indicator in self.indicators:
            df = indicator.compute(df)
        return df

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame, symbol: str = "") -> list[Signal]:
        """Given a DataFrame with indicator columns computed,
        produce zero or more trading signals."""
        ...

    def on_fill(self, fill: Fill) -> None:
        """Optional callback when an order is filled."""
        pass

    def sync_state(self, portfolio) -> None:
        """Sync strategy state with actual portfolio (e.g. after restart)."""
        pass
