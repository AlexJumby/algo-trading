from abc import ABC, abstractmethod

import pandas as pd


class Indicator(ABC):
    """Base class for all technical indicators.
    Each indicator receives a DataFrame and returns it with new column(s) added."""

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def columns(self) -> list[str]:
        ...
