class AlgoTradingError(Exception):
    """Base exception for algo trading system."""


class ConfigError(AlgoTradingError):
    """Invalid or missing configuration."""


class ExchangeError(AlgoTradingError):
    """Error communicating with the exchange."""


class InsufficientFunds(AlgoTradingError):
    """Not enough balance to execute order."""


class StrategyError(AlgoTradingError):
    """Error in strategy computation."""


class RiskLimitExceeded(AlgoTradingError):
    """Risk limit exceeded, order rejected."""


class DataError(AlgoTradingError):
    """Error fetching or processing market data."""
