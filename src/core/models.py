from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from pydantic import BaseModel, Field

from src.core.enums import MarketType, OrderType, Side, SignalAction


class OHLCVBar(BaseModel):
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def dt(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp / 1000, tz=timezone.utc)


class Signal(BaseModel):
    timestamp: int
    symbol: str
    action: SignalAction
    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: Dict = Field(default_factory=dict)


class Order(BaseModel):
    id: Optional[str] = None
    symbol: str
    side: Side
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    market_type: MarketType = MarketType.SPOT
    leverage: int = 1
    params: Dict = Field(default_factory=dict)


class Fill(BaseModel):
    order_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    fee: float
    timestamp: int


class Position(BaseModel):
    symbol: str
    side: Side
    quantity: float
    entry_price: float
    current_price: float = 0.0
    market_type: MarketType = MarketType.SPOT
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    @property
    def unrealized_pnl(self) -> float:
        if self.current_price == 0.0:
            return 0.0
        diff = self.current_price - self.entry_price
        if self.side == Side.SELL:
            diff = -diff
        return diff * self.quantity


class PortfolioSnapshot(BaseModel):
    timestamp: int
    equity: float
    cash: float
    unrealized_pnl: float
    realized_pnl: float
    positions_count: int = 0
