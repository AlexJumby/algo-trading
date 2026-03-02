"""Tests for funding rate deduction in backtest engine."""
import pandas as pd

from src.core.config import (
    AppConfig,
    BacktestConfig,
    ExchangeConfig,
    RiskConfig,
    StrategyConfig,
    TradingPairConfig,
)
from src.core.enums import MarketType, Side
from src.core.models import Position
from src.data.feed import HistoricalDataFeed
from src.engine.backtest_engine import BacktestEngine
from src.execution.backtest_broker import BacktestBroker
from src.portfolio.tracker import PortfolioTracker
from src.risk.manager import RiskManager
from src.strategies.base import BaseStrategy


def _make_config(**bt_overrides):
    bt_kwargs = {
        "initial_capital": 10000.0,
        "commission_pct": 0.0,
        "slippage_pct": 0.0,
        "funding_rate_pct": 0.0001,
        "funding_interval_hours": 8,
    }
    bt_kwargs.update(bt_overrides)
    return AppConfig(
        exchange=ExchangeConfig(),
        pairs=[TradingPairConfig(symbol="BTC/USDT:USDT", market_type=MarketType.FUTURES)],
        strategy=StrategyConfig(name="momentum", params={"timeframe": "1h"}),
        risk=RiskConfig(),
        backtest=BacktestConfig(**bt_kwargs),
    )


def _make_engine(config):
    portfolio = PortfolioTracker(config.backtest.initial_capital)
    return BacktestEngine(
        data_feed=HistoricalDataFeed(pd.DataFrame()),
        strategy=BaseStrategy.__subclasses__()[0](),
        risk_manager=RiskManager(config.risk, portfolio),
        broker=BacktestBroker(),
        portfolio=portfolio,
        config=config,
    )


class TestFundingRate:
    def test_funding_deducted_with_open_position(self):
        """Funding should reduce realized_pnl (and thus equity)."""
        config = _make_config()
        engine = _make_engine(config)

        symbol = "BTC/USDT:USDT"
        engine.portfolio.open_positions[symbol] = Position(
            symbol=symbol, side=Side.BUY, quantity=0.1,
            entry_price=50000.0, current_price=50000.0,
            market_type=MarketType.FUTURES,
        )

        initial_equity = engine.portfolio.equity  # 10000

        # First call anchors timestamp — no charge
        engine._apply_funding(symbol, 50000.0, 0)
        assert engine.portfolio.equity == initial_equity

        # 8 hours later
        ts_8h = 8 * 3600 * 1000
        engine._apply_funding(symbol, 50000.0, ts_8h)

        # Expected: notional * rate * 1 period = 0.1 * 50000 * 0.0001 = 0.50
        expected_cost = 0.1 * 50000.0 * 0.0001
        assert abs(engine.portfolio.equity - (initial_equity - expected_cost)) < 0.01
        assert abs(engine._total_funding - expected_cost) < 0.01

    def test_no_funding_without_position(self):
        """No funding should be charged if no position is open."""
        config = _make_config()
        engine = _make_engine(config)

        engine._apply_funding("BTC/USDT:USDT", 50000.0, 0)
        engine._apply_funding("BTC/USDT:USDT", 50000.0, 8 * 3600 * 1000)

        assert engine.portfolio.equity == 10000.0
        assert engine._total_funding == 0.0

    def test_zero_funding_rate(self):
        """With funding_rate_pct=0, no funding should be charged."""
        config = _make_config(funding_rate_pct=0.0)
        engine = _make_engine(config)

        symbol = "BTC/USDT:USDT"
        engine.portfolio.open_positions[symbol] = Position(
            symbol=symbol, side=Side.BUY, quantity=1.0,
            entry_price=50000.0, current_price=50000.0,
            market_type=MarketType.FUTURES,
        )

        initial_equity = engine.portfolio.equity

        engine._apply_funding(symbol, 50000.0, 0)
        engine._apply_funding(symbol, 50000.0, 24 * 3600 * 1000)

        assert engine.portfolio.equity == initial_equity
        assert engine._total_funding == 0.0

    def test_multiple_funding_periods(self):
        """If 24h pass, 3 funding periods of 8h each should be charged."""
        config = _make_config()
        engine = _make_engine(config)

        symbol = "BTC/USDT:USDT"
        engine.portfolio.open_positions[symbol] = Position(
            symbol=symbol, side=Side.BUY, quantity=0.1,
            entry_price=50000.0, current_price=50000.0,
            market_type=MarketType.FUTURES,
        )

        initial_equity = engine.portfolio.equity

        engine._apply_funding(symbol, 50000.0, 0)  # Anchor
        engine._apply_funding(symbol, 50000.0, 24 * 3600 * 1000)  # 24h later

        # 3 periods x 0.1 x 50000 x 0.0001 = 1.50
        expected = 3 * 0.1 * 50000.0 * 0.0001
        assert abs(engine._total_funding - expected) < 0.01
        assert abs(engine.portfolio.equity - (initial_equity - expected)) < 0.01
