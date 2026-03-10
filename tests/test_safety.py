"""Tests for safety-critical features introduced in code review v3/v4.

Covers:
- ATR/SL clamp in RiskManager (MAX_SL_PCT = 15%)
- ATR clamp in trail_stop()
- Per-symbol state isolation in TSMOM, Breakout, MomentumV3
- Breakout CLOSE signal correctness (not always true)
- Stop slippage in check_stops (fill at market price, not SL level)
"""
import pandas as pd
import pytest

from src.core.config import RiskConfig, StrategyConfig
from src.core.enums import OrderType, Side, SignalAction
from src.core.models import Fill, Order, Position, Signal
from src.execution.stops import MAX_SL_PCT, trail_stop
from src.portfolio.tracker import PortfolioTracker
from src.risk.manager import RiskManager
from src.strategies.breakout import BreakoutTrendStrategy
from src.strategies.momentum import MomentumV3Strategy
from src.strategies.tsmom import TSMOMStrategy


# ---------------------------------------------------------------------------
# trail_stop() ATR clamp
# ---------------------------------------------------------------------------


class TestTrailStopClamp:
    def test_normal_atr_not_clamped(self):
        """Normal ATR distance should pass through unchanged."""
        pos = Position(
            symbol="BTC/USDT", side=Side.BUY, quantity=0.1,
            entry_price=80000, current_price=82000,
        )
        # ATR=1500, mult=3.5 → distance=5250, max_distance=82000*0.15=12300
        updated = trail_stop(pos, 82000, atr=1500, mult=3.5)
        assert updated is True
        assert pos.stop_loss == pytest.approx(82000 - 1500 * 3.5)

    def test_extreme_atr_clamped(self):
        """Absurd ATR (data gap) should be clamped to 15% of price."""
        pos = Position(
            symbol="BTC/USDT", side=Side.BUY, quantity=0.1,
            entry_price=80000, current_price=82000,
        )
        # ATR=127000 (data gap), mult=3.5 → distance=444500 >> max
        updated = trail_stop(pos, 82000, atr=127000, mult=3.5)
        assert updated is True
        max_distance = 82000 * MAX_SL_PCT
        assert pos.stop_loss == pytest.approx(82000 - max_distance)

    def test_extreme_atr_clamped_short(self):
        """Clamp also works for short positions."""
        pos = Position(
            symbol="ETH/USDT", side=Side.SELL, quantity=1.0,
            entry_price=3000, current_price=2800,
        )
        updated = trail_stop(pos, 2800, atr=50000, mult=2.0)
        assert updated is True
        max_distance = 2800 * MAX_SL_PCT
        assert pos.stop_loss == pytest.approx(2800 + max_distance)

    def test_trail_stop_only_moves_in_profit_direction(self):
        """Trail stop should never move against profit."""
        pos = Position(
            symbol="BTC/USDT", side=Side.BUY, quantity=0.1,
            entry_price=80000, current_price=85000,
            stop_loss=83000,
        )
        # Price dropped to 82000 → new SL would be lower → should NOT update
        updated = trail_stop(pos, 82000, atr=500, mult=3.5)
        assert updated is False
        assert pos.stop_loss == 83000  # unchanged


# ---------------------------------------------------------------------------
# RiskManager ATR SL clamp (entry SL)
# ---------------------------------------------------------------------------


class TestRiskManagerSLClamp:
    @pytest.fixture
    def risk_mgr(self):
        config = RiskConfig(
            max_position_size_pct=0.15,
            max_open_positions=3,
            max_drawdown_pct=0.25,
            default_stop_loss_pct=0.02,
            default_take_profit_pct=0.04,
        )
        portfolio = PortfolioTracker(initial_capital=10000.0)
        return RiskManager(config, portfolio, leverage=7)

    def test_normal_atr_sl_not_clamped(self, risk_mgr):
        """Normal ATR SL ($3000 on $80k BTC) should not be clamped."""
        signal = Signal(
            timestamp=1, symbol="BTC/USDT",
            action=SignalAction.LONG, strength=1.0,
            metadata={"atr_sl": 3000, "atr": 1000},
        )
        order = risk_mgr.evaluate(signal, current_price=80000)
        assert order.stop_loss == pytest.approx(80000 - 3000)

    def test_extreme_atr_sl_clamped_long(self, risk_mgr):
        """ATR SL > 15% of price should be clamped (LONG)."""
        signal = Signal(
            timestamp=1, symbol="BTC/USDT",
            action=SignalAction.LONG, strength=1.0,
            metadata={"atr_sl": 127000, "atr": 42333},
        )
        order = risk_mgr.evaluate(signal, current_price=80000)
        max_sl = 80000 * RiskManager.MAX_SL_PCT
        assert order.stop_loss == pytest.approx(80000 - max_sl)

    def test_extreme_atr_sl_clamped_short(self, risk_mgr):
        """ATR SL > 15% of price should be clamped (SHORT)."""
        signal = Signal(
            timestamp=1, symbol="BTC/USDT",
            action=SignalAction.SHORT, strength=1.0,
            metadata={"atr_sl": 50000, "atr": 16666},
        )
        order = risk_mgr.evaluate(signal, current_price=80000)
        max_sl = 80000 * RiskManager.MAX_SL_PCT
        assert order.stop_loss == pytest.approx(80000 + max_sl)


# ---------------------------------------------------------------------------
# Per-symbol state isolation — TSMOM
# ---------------------------------------------------------------------------


class TestTSMOMPerSymbolState:
    @pytest.fixture
    def strategy(self):
        s = TSMOMStrategy()
        s.setup(StrategyConfig(
            name="tsmom",
            params={
                "timeframe": "1h",
                "vol_mode": "simple",
                "roc_short": 24, "roc_medium": 168, "roc_long": 720,
                "vol_lookback": 168, "trend_ema": 200,
                "cooldown_bars": 24,
            },
        ))
        return s

    def test_btc_fill_does_not_affect_eth_state(self, strategy):
        """BTC fill should not reset ETH cooldown."""
        btc_fill = Fill(
            order_id="1", symbol="BTC/USDT:USDT", side=Side.BUY,
            quantity=0.1, price=80000, fee=1.0, timestamp=1000,
        )
        strategy.on_fill(btc_fill)

        btc_state = strategy._get_state("BTC/USDT:USDT")
        eth_state = strategy._get_state("ETH/USDT:USDT")

        assert btc_state["bars_since_fill"] == 0
        assert btc_state["in_position"] is True
        assert eth_state["bars_since_fill"] == 999  # untouched
        assert eth_state["in_position"] is False

    def test_sync_state_restores_positions(self, strategy):
        """sync_state should set in_position for portfolio positions."""
        portfolio = PortfolioTracker(initial_capital=10000.0)
        portfolio.open_positions["BTC/USDT:USDT"] = Position(
            symbol="BTC/USDT:USDT", side=Side.BUY, quantity=0.1,
            entry_price=80000, current_price=82000,
        )
        strategy.sync_state(portfolio)

        btc_state = strategy._get_state("BTC/USDT:USDT")
        assert btc_state["in_position"] is True


# ---------------------------------------------------------------------------
# Per-symbol state isolation — Breakout
# ---------------------------------------------------------------------------


class TestBreakoutPerSymbolState:
    @pytest.fixture
    def strategy(self):
        s = BreakoutTrendStrategy()
        s.setup(StrategyConfig(
            name="breakout",
            params={"cooldown_bars": 6},
        ))
        return s

    def test_btc_fill_does_not_affect_eth(self, strategy):
        btc_fill = Fill(
            order_id="1", symbol="BTC/USDT:USDT", side=Side.BUY,
            quantity=0.1, price=80000, fee=1.0, timestamp=1000,
        )
        strategy.on_fill(btc_fill)

        btc_state = strategy._get_state("BTC/USDT:USDT")
        eth_state = strategy._get_state("ETH/USDT:USDT")

        assert btc_state["bars_since_fill"] == 0
        assert btc_state["in_position"] is True
        assert btc_state["position_side"] == "long"
        assert eth_state["bars_since_fill"] == 999
        assert eth_state["in_position"] is False

    def test_sync_state_breakout(self, strategy):
        portfolio = PortfolioTracker(initial_capital=10000.0)
        portfolio.open_positions["BTC/USDT:USDT"] = Position(
            symbol="BTC/USDT:USDT", side=Side.SELL, quantity=0.1,
            entry_price=80000, current_price=78000,
        )
        strategy.sync_state(portfolio)

        st = strategy._get_state("BTC/USDT:USDT")
        assert st["in_position"] is True
        assert st["position_side"] == "short"


# ---------------------------------------------------------------------------
# Per-symbol state isolation — MomentumV3
# ---------------------------------------------------------------------------


class TestMomentumV3PerSymbolState:
    @pytest.fixture
    def strategy(self):
        s = MomentumV3Strategy()
        s.setup(StrategyConfig(
            name="momentum_v3",
            params={"cooldown_bars": 10},
        ))
        return s

    def test_btc_fill_does_not_affect_eth(self, strategy):
        btc_fill = Fill(
            order_id="1", symbol="BTC/USDT:USDT", side=Side.BUY,
            quantity=0.1, price=80000, fee=1.0, timestamp=1000,
        )
        strategy.on_fill(btc_fill)

        btc_state = strategy._get_state("BTC/USDT:USDT")
        eth_state = strategy._get_state("ETH/USDT:USDT")

        assert btc_state["bars_since_close"] == 0
        assert eth_state["bars_since_close"] == 999


# ---------------------------------------------------------------------------
# Breakout CLOSE signal — not always true
# ---------------------------------------------------------------------------


class TestBreakoutCloseSignal:
    @pytest.fixture
    def strategy(self):
        s = BreakoutTrendStrategy()
        s.setup(StrategyConfig(
            name="breakout",
            params={
                "dc_entry_period": 48, "dc_exit_period": 24,
                "adx_period": 14, "adx_threshold": 20,
                "trend_ema": 100, "atr_period": 14,
                "atr_sl_mult": 2.0, "cooldown_bars": 6,
            },
        ))
        return s

    def _make_df(self, close, dc_mid, n=5):
        """Create minimal df with needed columns for breakout signal check."""
        data = {
            "timestamp": list(range(1000, 1000 + n)),
            "open": [close] * n,
            "high": [close + 100] * n,
            "low": [close - 100] * n,
            "close": [close] * n,
            "volume": [1000] * n,
            "dc_48_high": [close + 500] * n,
            "dc_48_low": [close - 500] * n,
            "dc_24_high": [close + 300] * n,
            "dc_24_low": [close - 300] * n,
            "dc_24_mid": [dc_mid] * n,
            "adx_14": [25] * n,
            "di_plus_14": [30] * n,
            "di_minus_14": [20] * n,
            "atr_14": [500] * n,
            "ema_100": [close - 100] * n,
        }
        return pd.DataFrame(data)

    def test_no_close_when_not_in_position(self, strategy):
        """No CLOSE signal when strategy has no position."""
        # close=80000, dc_mid=79500 → close > dc_mid but no position
        df = self._make_df(close=80000, dc_mid=79500)
        signals = strategy.generate_signals(df, symbol="BTC/USDT")

        close_signals = [s for s in signals if s.action == SignalAction.CLOSE]
        assert len(close_signals) == 0

    def test_close_long_when_below_mid(self, strategy):
        """CLOSE signal for LONG when price drops below dc_mid."""
        # Simulate being in a long position
        fill = Fill(
            order_id="1", symbol="BTC/USDT", side=Side.BUY,
            quantity=0.1, price=80000, fee=1.0, timestamp=1000,
        )
        strategy.on_fill(fill)

        # close=79000, dc_mid=79500 → close < dc_mid → should exit long
        df = self._make_df(close=79000, dc_mid=79500, n=5)
        # Advance cooldown past threshold
        for _ in range(10):
            strategy.generate_signals(df, symbol="BTC/USDT")

        signals = strategy.generate_signals(df, symbol="BTC/USDT")
        close_signals = [s for s in signals if s.action == SignalAction.CLOSE]
        assert len(close_signals) == 1

    def test_no_close_long_when_above_mid(self, strategy):
        """No CLOSE signal for LONG when price is above dc_mid."""
        fill = Fill(
            order_id="1", symbol="BTC/USDT", side=Side.BUY,
            quantity=0.1, price=80000, fee=1.0, timestamp=1000,
        )
        strategy.on_fill(fill)

        # close=81000, dc_mid=79500 → close > dc_mid → should NOT exit long
        df = self._make_df(close=81000, dc_mid=79500, n=5)
        for _ in range(10):
            strategy.generate_signals(df, symbol="BTC/USDT")

        signals = strategy.generate_signals(df, symbol="BTC/USDT")
        close_signals = [s for s in signals if s.action == SignalAction.CLOSE]
        assert len(close_signals) == 0


# ---------------------------------------------------------------------------
# check_stops — fill at market price (gap slippage)
# ---------------------------------------------------------------------------


class TestStopSlippage:
    """check_stops should fill at market price, not at SL level."""

    def test_sl_gap_fill_at_market_price(self):
        """When price gaps through SL, fill should be at market price."""
        from src.execution.backtest_broker import BacktestBroker

        broker = BacktestBroker(commission=0.001, slippage=0.0)
        portfolio = PortfolioTracker(initial_capital=10000.0)

        # Open a LONG position with SL at 78000
        portfolio.open_positions["BTC/USDT"] = Position(
            symbol="BTC/USDT", side=Side.BUY, quantity=0.1,
            entry_price=80000, current_price=80000,
            stop_loss=78000, take_profit=None,
        )

        # Price gaps down to 75000 (below SL of 78000)
        fills = broker.check_stops(
            portfolio, {"BTC/USDT": 75000}, timestamp=2000,
        )

        assert len(fills) == 1
        # Fill should be at 75000 (market price), not 78000 (SL level)
        assert fills[0].price == pytest.approx(75000, rel=0.01)

    def test_tp_gap_fill_at_market_price(self):
        """When price gaps through TP, fill should be at market price."""
        from src.execution.backtest_broker import BacktestBroker

        broker = BacktestBroker(commission=0.001, slippage=0.0)
        portfolio = PortfolioTracker(initial_capital=10000.0)

        # Open a LONG position with TP at 85000
        portfolio.open_positions["BTC/USDT"] = Position(
            symbol="BTC/USDT", side=Side.BUY, quantity=0.1,
            entry_price=80000, current_price=80000,
            stop_loss=None, take_profit=85000,
        )

        # Price gaps up to 87000 (above TP of 85000)
        fills = broker.check_stops(
            portfolio, {"BTC/USDT": 87000}, timestamp=2000,
        )

        assert len(fills) == 1
        # Fill at 87000 (market), not 85000 (TP)
        assert fills[0].price == pytest.approx(87000, rel=0.01)
