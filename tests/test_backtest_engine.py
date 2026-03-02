import pytest

from src.core.config import AppConfig, StrategyConfig
from src.data.feed import HistoricalDataFeed
from src.engine.backtest_engine import BacktestEngine
from src.execution.backtest_broker import BacktestBroker
from src.portfolio.metrics import PerformanceMetrics
from src.portfolio.tracker import PortfolioTracker
from src.risk.manager import RiskManager
from src.strategies.momentum import MomentumStrategy


class TestBacktestBroker:
    def test_submit_order_applies_slippage_buy(self):
        from src.core.enums import OrderType, Side
        from src.core.models import Order

        broker = BacktestBroker(commission=0.001, slippage=0.001)
        order = Order(
            symbol="BTC/USDT", side=Side.BUY,
            order_type=OrderType.MARKET, quantity=0.01,
        )
        fill = broker.submit_order(order, current_price=50000.0, timestamp=1000)
        assert fill is not None
        assert fill.price > 50000.0  # Slippage should increase buy price

    def test_submit_order_applies_slippage_sell(self):
        from src.core.enums import OrderType, Side
        from src.core.models import Order

        broker = BacktestBroker(commission=0.001, slippage=0.001)
        order = Order(
            symbol="BTC/USDT", side=Side.SELL,
            order_type=OrderType.MARKET, quantity=0.01,
        )
        fill = broker.submit_order(order, current_price=50000.0, timestamp=1000)
        assert fill is not None
        assert fill.price < 50000.0  # Slippage should decrease sell price

    def test_commission_calculation(self):
        from src.core.enums import OrderType, Side
        from src.core.models import Order

        broker = BacktestBroker(commission=0.001, slippage=0.0)
        order = Order(
            symbol="BTC/USDT", side=Side.BUY,
            order_type=OrderType.MARKET, quantity=1.0,
        )
        fill = broker.submit_order(order, current_price=50000.0, timestamp=1000)
        expected_fee = 1.0 * 50000.0 * 0.001
        assert abs(fill.fee - expected_fee) < 0.01


class TestBacktestEngine:
    def test_full_backtest_run(self, sample_ohlcv_df, app_config):
        """End-to-end backtest should run without errors."""
        data_feed = HistoricalDataFeed(sample_ohlcv_df)
        broker = BacktestBroker(
            commission=app_config.backtest.commission_pct,
            slippage=app_config.backtest.slippage_pct,
        )
        portfolio = PortfolioTracker(app_config.backtest.initial_capital)

        strategy = MomentumStrategy()
        strategy.setup(app_config.strategy)

        risk_mgr = RiskManager(app_config.risk, portfolio)

        engine = BacktestEngine(data_feed, strategy, risk_mgr, broker, portfolio, app_config)
        results = engine.run(symbol="BTC/USDT:USDT")

        assert "total_return_pct" in results
        assert "sharpe_ratio" in results
        assert "max_drawdown_pct" in results
        assert "win_rate" in results
        assert "total_trades" in results
        assert isinstance(results["total_trades"], int)

    def test_equity_curve_populated(self, sample_ohlcv_df, app_config):
        data_feed = HistoricalDataFeed(sample_ohlcv_df)
        broker = BacktestBroker()
        portfolio = PortfolioTracker(10000.0)

        strategy = MomentumStrategy()
        strategy.setup(app_config.strategy)

        risk_mgr = RiskManager(app_config.risk, portfolio)
        engine = BacktestEngine(data_feed, strategy, risk_mgr, broker, portfolio, app_config)
        engine.run(symbol="BTC/USDT")

        assert len(portfolio.equity_curve) > 0

    def test_initial_capital_preserved_no_trades(self):
        """With flat data and no signals, capital should be ~preserved."""
        import pandas as pd
        from src.core.config import RiskConfig

        flat_df = pd.DataFrame({
            "timestamp": [1704067200000 + i * 3600000 for i in range(200)],
            "open": [50000.0] * 200,
            "high": [50000.0] * 200,
            "low": [50000.0] * 200,
            "close": [50000.0] * 200,
            "volume": [100.0] * 200,
        })

        from src.core.config import (
            AppConfig, ExchangeConfig, BacktestConfig,
            StrategyConfig, TradingPairConfig,
        )
        from src.core.enums import MarketType

        config = AppConfig(
            exchange=ExchangeConfig(),
            pairs=[TradingPairConfig(symbol="BTC/USDT", market_type=MarketType.SPOT)],
            strategy=StrategyConfig(name="momentum", params={
                "fast_ema": 12, "slow_ema": 26, "rsi_period": 14,
                "lookback_bars": 100,
            }),
            risk=RiskConfig(),
            backtest=BacktestConfig(initial_capital=10000.0),
        )

        data_feed = HistoricalDataFeed(flat_df)
        broker = BacktestBroker()
        portfolio = PortfolioTracker(10000.0)
        strategy = MomentumStrategy()
        strategy.setup(config.strategy)
        risk_mgr = RiskManager(config.risk, portfolio)

        engine = BacktestEngine(data_feed, strategy, risk_mgr, broker, portfolio, config)
        engine.run(symbol="BTC/USDT")

        # With flat data, no trades should happen, capital should be preserved
        assert portfolio.equity == pytest.approx(10000.0, rel=0.01)


class TestPortfolioTracker:
    def test_initial_state(self):
        pt = PortfolioTracker(10000.0)
        assert pt.cash == 10000.0
        assert pt.equity == 10000.0
        assert len(pt.open_positions) == 0

    def test_on_fill_open(self):
        from src.core.enums import Side
        from src.core.models import Fill

        pt = PortfolioTracker(10000.0)
        fill = Fill(
            order_id="1", symbol="BTC/USDT", side=Side.BUY,
            quantity=0.01, price=50000.0, fee=0.5, timestamp=1000,
        )
        pt.on_fill(fill)
        assert "BTC/USDT" in pt.open_positions
        assert pt.open_positions["BTC/USDT"].quantity == 0.01


class TestPerformanceMetrics:
    def test_empty_tracker(self):
        pt = PortfolioTracker(10000.0)
        metrics = PerformanceMetrics(pt)
        results = metrics.compute_all()
        assert results["total_trades"] == 0
        assert results["win_rate"] == 0.0

    def test_custom_bars_per_year(self):
        """bars_per_year should be used by Sharpe/Sortino."""
        pt = PortfolioTracker(10000.0)
        m1 = PerformanceMetrics(pt, bars_per_year=8760)
        m2 = PerformanceMetrics(pt, bars_per_year=2191)
        # Both should produce 0.0 on empty tracker, but check they don't crash
        assert m1.sharpe_ratio() == 0.0
        assert m2.sortino_ratio() == 0.0


class TestRealisticFees:
    """Test BacktestBroker with maker/taker fee model."""

    def test_taker_fee_applied(self):
        from src.core.enums import OrderType, Side
        from src.core.models import Order

        broker = BacktestBroker(
            commission=0.001, slippage=0.0,
            taker_fee=0.00055, maker_fee=0.0002,
        )
        order = Order(
            symbol="BTC/USDT", side=Side.BUY,
            order_type=OrderType.MARKET, quantity=1.0,
        )
        fill = broker.submit_order(order, current_price=50000.0, timestamp=1000)
        # Fee should be taker: 50000 * 0.00055 = 27.50
        assert abs(fill.fee - 50000.0 * 0.00055) < 0.01

    def test_dynamic_slippage(self):
        from src.core.enums import OrderType, Side
        from src.core.models import Order

        broker = BacktestBroker(
            commission=0.001, slippage=0.0,
            slippage_base=0.0003, slippage_impact=0.0002,
        )
        # Small order
        order = Order(
            symbol="BTC/USDT", side=Side.BUY,
            order_type=OrderType.MARKET, quantity=0.01,
        )
        fill_small = broker.submit_order(order, current_price=50000.0, timestamp=1)

        # Large order ($200k notional)
        broker2 = BacktestBroker(
            commission=0.001, slippage=0.0,
            slippage_base=0.0003, slippage_impact=0.0002,
        )
        order_large = Order(
            symbol="BTC/USDT", side=Side.BUY,
            order_type=OrderType.MARKET, quantity=4.0,
        )
        fill_large = broker2.submit_order(order_large, current_price=50000.0, timestamp=2)

        # Large order should have higher slippage
        slip_small = fill_small.price - 50000.0
        slip_large = fill_large.price - 50000.0
        assert slip_large > slip_small

    def test_legacy_backward_compat(self):
        """Without taker/maker, should use legacy commission/slippage."""
        from src.core.enums import OrderType, Side
        from src.core.models import Order

        broker = BacktestBroker(commission=0.001, slippage=0.0005)
        order = Order(
            symbol="BTC/USDT", side=Side.BUY,
            order_type=OrderType.MARKET, quantity=1.0,
        )
        fill = broker.submit_order(order, current_price=50000.0, timestamp=1)
        # Legacy fee: notional * 0.001
        expected_fee = fill.price * 0.001
        assert abs(fill.fee - expected_fee) < 0.01
        # Legacy slippage: price * (1 + 0.0005)
        assert abs(fill.price - 50000.0 * 1.0005) < 0.01
