from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class MarketType(str, Enum):
    SPOT = "spot"
    FUTURES = "futures"


class SignalAction(str, Enum):
    LONG = "long"
    SHORT = "short"
    CLOSE = "close"
    HOLD = "hold"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
