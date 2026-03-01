import pytest

from src.core.enums import MarketType, OrderType, Side, SignalAction
from src.core.models import Fill, OHLCVBar, Order, Position, Signal


class TestOHLCVBar:
    def test_create(self):
        bar = OHLCVBar(
            timestamp=1704067200000,
            open=50000.0,
            high=50500.0,
            low=49800.0,
            close=50200.0,
            volume=1234.5,
        )
        assert bar.close == 50200.0
        assert bar.dt.year == 2024

    def test_datetime_property(self):
        bar = OHLCVBar(
            timestamp=1704067200000,
            open=1, high=1, low=1, close=1, volume=1,
        )
        assert bar.dt.month == 1
        assert bar.dt.day == 1


class TestSignal:
    def test_create_long(self):
        signal = Signal(
            timestamp=1704067200000,
            symbol="BTC/USDT",
            action=SignalAction.LONG,
            strength=0.8,
        )
        assert signal.action == SignalAction.LONG
        assert signal.strength == 0.8

    def test_strength_bounds(self):
        with pytest.raises(Exception):
            Signal(
                timestamp=1, symbol="X", action=SignalAction.LONG, strength=1.5,
            )


class TestOrder:
    def test_create_market_order(self):
        order = Order(
            symbol="BTC/USDT",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=0.001,
        )
        assert order.side == Side.BUY
        assert order.market_type == MarketType.SPOT  # default

    def test_with_sl_tp(self):
        order = Order(
            symbol="BTC/USDT",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=0.001,
            stop_loss=49000.0,
            take_profit=52000.0,
        )
        assert order.stop_loss == 49000.0
        assert order.take_profit == 52000.0


class TestPosition:
    def test_long_pnl(self):
        pos = Position(
            symbol="BTC/USDT",
            side=Side.BUY,
            quantity=1.0,
            entry_price=50000.0,
            current_price=51000.0,
        )
        assert pos.unrealized_pnl == 1000.0

    def test_short_pnl(self):
        pos = Position(
            symbol="BTC/USDT",
            side=Side.SELL,
            quantity=1.0,
            entry_price=50000.0,
            current_price=49000.0,
        )
        assert pos.unrealized_pnl == 1000.0

    def test_short_negative_pnl(self):
        pos = Position(
            symbol="BTC/USDT",
            side=Side.SELL,
            quantity=1.0,
            entry_price=50000.0,
            current_price=51000.0,
        )
        assert pos.unrealized_pnl == -1000.0

    def test_zero_current_price(self):
        pos = Position(
            symbol="BTC/USDT",
            side=Side.BUY,
            quantity=1.0,
            entry_price=50000.0,
        )
        assert pos.unrealized_pnl == 0.0


class TestFill:
    def test_create(self):
        fill = Fill(
            order_id="123",
            symbol="BTC/USDT",
            side=Side.BUY,
            quantity=0.001,
            price=50000.0,
            fee=0.05,
            timestamp=1704067200000,
        )
        assert fill.price == 50000.0
        assert fill.fee == 0.05
