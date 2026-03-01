from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Union

import yaml
from pydantic import BaseModel, Field

from src.core.enums import MarketType


class ExchangeConfig(BaseModel):
    name: str = "bybit"
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = True
    rate_limit: bool = True


class TradingPairConfig(BaseModel):
    symbol: str
    market_type: MarketType
    timeframe: str = "1h"
    leverage: int = 1


class StrategyConfig(BaseModel):
    name: str = "momentum"
    params: dict = Field(default_factory=dict)


class RiskConfig(BaseModel):
    max_position_size_pct: float = 0.02
    max_open_positions: int = 3
    max_drawdown_pct: float = 0.10
    default_stop_loss_pct: float = 0.02
    default_take_profit_pct: float = 0.04
    position_sizing_method: str = "fixed_fraction"


class BacktestConfig(BaseModel):
    start_date: str = "2024-01-01"
    end_date: str = "2025-01-01"
    initial_capital: float = 10000.0
    commission_pct: float = 0.001
    slippage_pct: float = 0.0005


class AppConfig(BaseModel):
    exchange: ExchangeConfig
    pairs: List[TradingPairConfig]
    strategy: StrategyConfig
    risk: RiskConfig
    backtest: Optional[BacktestConfig] = None
    log_level: str = "INFO"

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> AppConfig:
        with open(path) as f:
            raw = yaml.safe_load(f)

        if os.getenv("BYBIT_API_KEY"):
            raw.setdefault("exchange", {})["api_key"] = os.getenv("BYBIT_API_KEY")
        if os.getenv("BYBIT_API_SECRET"):
            raw.setdefault("exchange", {})["api_secret"] = os.getenv("BYBIT_API_SECRET")

        return cls(**raw)
