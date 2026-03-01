import pytest

from src.core.config import RiskConfig
from src.core.enums import Side, SignalAction
from src.core.models import Signal
from src.portfolio.tracker import PortfolioTracker
from src.risk.manager import RiskManager


class TestRiskManager:
    @pytest.fixture
    def risk_mgr(self):
        config = RiskConfig(
            max_position_size_pct=0.02,
            max_open_positions=2,
            max_drawdown_pct=0.10,
            default_stop_loss_pct=0.02,
            default_take_profit_pct=0.04,
        )
        portfolio = PortfolioTracker(initial_capital=10000.0)
        return RiskManager(config, portfolio)

    def test_long_signal_creates_order(self, risk_mgr):
        signal = Signal(
            timestamp=1, symbol="BTC/USDT", action=SignalAction.LONG, strength=1.0,
        )
        order = risk_mgr.evaluate(signal, current_price=50000.0)
        assert order is not None
        assert order.side == Side.BUY
        assert order.quantity > 0
        assert order.stop_loss is not None
        assert order.take_profit is not None

    def test_short_signal_creates_order(self, risk_mgr):
        signal = Signal(
            timestamp=1, symbol="BTC/USDT", action=SignalAction.SHORT, strength=1.0,
        )
        order = risk_mgr.evaluate(signal, current_price=50000.0)
        assert order is not None
        assert order.side == Side.SELL

    def test_hold_signal_returns_none(self, risk_mgr):
        signal = Signal(
            timestamp=1, symbol="BTC/USDT", action=SignalAction.HOLD,
        )
        assert risk_mgr.evaluate(signal, 50000.0) is None

    def test_max_positions_rejects(self, risk_mgr):
        # Fill up max positions
        from src.core.models import Position
        risk_mgr.portfolio.open_positions["BTC/USDT"] = Position(
            symbol="BTC/USDT", side=Side.BUY, quantity=0.1,
            entry_price=50000, current_price=50000,
        )
        risk_mgr.portfolio.open_positions["ETH/USDT"] = Position(
            symbol="ETH/USDT", side=Side.BUY, quantity=1.0,
            entry_price=3000, current_price=3000,
        )

        signal = Signal(
            timestamp=1, symbol="SOL/USDT", action=SignalAction.LONG, strength=1.0,
        )
        assert risk_mgr.evaluate(signal, 100.0) is None

    def test_stop_loss_long(self, risk_mgr):
        signal = Signal(
            timestamp=1, symbol="BTC/USDT", action=SignalAction.LONG, strength=1.0,
        )
        order = risk_mgr.evaluate(signal, 50000.0)
        assert order.stop_loss == 50000.0 * 0.98  # 2% below

    def test_take_profit_long(self, risk_mgr):
        signal = Signal(
            timestamp=1, symbol="BTC/USDT", action=SignalAction.LONG, strength=1.0,
        )
        order = risk_mgr.evaluate(signal, 50000.0)
        assert order.take_profit == 50000.0 * 1.04  # 4% above

    def test_stop_loss_short(self, risk_mgr):
        signal = Signal(
            timestamp=1, symbol="BTC/USDT", action=SignalAction.SHORT, strength=1.0,
        )
        order = risk_mgr.evaluate(signal, 50000.0)
        assert order.stop_loss == 50000.0 * 1.02

    def test_position_sizing(self, risk_mgr):
        signal = Signal(
            timestamp=1, symbol="BTC/USDT", action=SignalAction.LONG, strength=1.0,
        )
        order = risk_mgr.evaluate(signal, 50000.0)
        expected_qty = (10000.0 * 0.02) / 50000.0  # 2% of equity / price
        assert abs(order.quantity - expected_qty) < 1e-10

    def test_strength_affects_sizing(self, risk_mgr):
        signal_full = Signal(
            timestamp=1, symbol="BTC/USDT", action=SignalAction.LONG, strength=1.0,
        )
        signal_half = Signal(
            timestamp=1, symbol="ETH/USDT", action=SignalAction.LONG, strength=0.5,
        )
        order_full = risk_mgr.evaluate(signal_full, 50000.0)
        order_half = risk_mgr.evaluate(signal_half, 50000.0)
        assert abs(order_full.quantity - 2 * order_half.quantity) < 1e-10

    def test_close_signal_for_existing_position(self, risk_mgr):
        from src.core.models import Position
        risk_mgr.portfolio.open_positions["BTC/USDT"] = Position(
            symbol="BTC/USDT", side=Side.BUY, quantity=0.1,
            entry_price=50000, current_price=51000,
        )
        signal = Signal(
            timestamp=1, symbol="BTC/USDT", action=SignalAction.CLOSE, strength=1.0,
        )
        order = risk_mgr.evaluate(signal, 51000.0)
        assert order is not None
        assert order.side == Side.SELL
        assert order.quantity == 0.1

    def test_close_signal_no_position(self, risk_mgr):
        signal = Signal(
            timestamp=1, symbol="BTC/USDT", action=SignalAction.CLOSE, strength=1.0,
        )
        assert risk_mgr.evaluate(signal, 50000.0) is None
