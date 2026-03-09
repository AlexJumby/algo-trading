from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Union

import yaml
from pydantic import BaseModel, Field

from src.core.enums import MarketType

# ── Timeframe utilities ──────────────────────────────────────────────

TIMEFRAME_MINUTES: dict[str, int] = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720, "1d": 1440,
}


TIMEFRAME_SECONDS: dict[str, int] = {k: v * 60 for k, v in TIMEFRAME_MINUTES.items()}
TIMEFRAME_MS: dict[str, int] = {k: v * 60_000 for k, v in TIMEFRAME_MINUTES.items()}


def timeframe_to_minutes(tf: str) -> int:
    """Convert timeframe string (e.g. '1h', '4h') to minutes."""
    if tf not in TIMEFRAME_MINUTES:
        raise ValueError(
            f"Unknown timeframe '{tf}'. "
            f"Supported: {list(TIMEFRAME_MINUTES.keys())}"
        )
    return TIMEFRAME_MINUTES[tf]


def bars_per_year(timeframe: str) -> float:
    """How many bars of `timeframe` fit in one calendar year (365.25 days)."""
    tf_min = timeframe_to_minutes(timeframe)
    return 365.25 * 24 * 60 / tf_min


def hours_to_bars(hours: int | float, timeframe: str) -> int:
    """Convert a duration in hours to the equivalent number of bars."""
    tf_min = timeframe_to_minutes(timeframe)
    return max(1, round(hours * 60 / tf_min))


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
    max_leverage_exposure: float = 5.0  # max notional/equity per position
    drawdown_soft_pct: float = 0.10  # start gradual deleveraging at this DD


class BacktestConfig(BaseModel):
    start_date: str = "2024-01-01"
    end_date: str = "2025-01-01"
    initial_capital: float = 10000.0

    # Legacy fee fields (backward compat — used when maker/taker are None)
    commission_pct: float = 0.001
    slippage_pct: float = 0.0005

    # Realistic fee model (set to enable; None = fallback to legacy)
    maker_fee_pct: Optional[float] = None       # e.g. 0.0002 (Bybit VIP0)
    taker_fee_pct: Optional[float] = None       # e.g. 0.00055 (Bybit VIP0)
    slippage_base_pct: Optional[float] = None   # e.g. 0.0003
    slippage_impact_pct: Optional[float] = None  # per $100k notional

    # Funding rate for perpetual futures
    funding_rate_pct: float = 0.0001    # 0.01% per funding interval
    funding_interval_hours: int = 8


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
