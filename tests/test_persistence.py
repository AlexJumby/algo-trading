"""Tests for SQLite portfolio persistence."""
import os
import tempfile

import pytest

from src.core.enums import Side
from src.core.models import Fill, PortfolioSnapshot, Position
from src.portfolio.persistence import PortfolioDB
from src.portfolio.tracker import PortfolioTracker


@pytest.fixture
def db():
    """Create a temp DB for each test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = PortfolioDB(path)
    yield database
    database.close()
    os.unlink(path)


class TestPortfolioDB:
    def test_save_and_get_snapshot(self, db):
        snap = PortfolioSnapshot(
            timestamp=1000, equity=10500.0, cash=9000.0,
            unrealized_pnl=500.0, realized_pnl=200.0, positions_count=1,
        )
        db.save_snapshot(snap)

        curve = db.get_equity_curve()
        assert len(curve) == 1
        assert curve[0]["equity"] == 10500.0
        assert curve[0]["timestamp"] == 1000

    def test_get_latest_snapshot(self, db):
        for i in range(3):
            snap = PortfolioSnapshot(
                timestamp=1000 + i, equity=10000 + i * 100, cash=9000.0,
                unrealized_pnl=0, realized_pnl=0, positions_count=0,
            )
            db.save_snapshot(snap)

        latest = db.get_latest_snapshot()
        assert latest["equity"] == 10200.0
        assert latest["timestamp"] == 1002

    def test_save_and_get_trade(self, db):
        trade = {
            "symbol": "BTC/USDT:USDT",
            "side": "buy",
            "entry_price": 60000.0,
            "exit_price": 62000.0,
            "quantity": 0.1,
            "pnl": 200.0,
            "fee": 12.0,
            "timestamp": 2000,
        }
        db.save_trade(trade)

        trades = db.get_trades()
        assert len(trades) == 1
        assert trades[0]["symbol"] == "BTC/USDT:USDT"
        assert trades[0]["pnl"] == 200.0

    def test_get_total_realized_pnl(self, db):
        for pnl in [100.0, -50.0, 300.0]:
            db.save_trade({
                "symbol": "BTC/USDT:USDT", "side": "buy",
                "entry_price": 60000, "exit_price": 61000,
                "quantity": 0.01, "pnl": pnl, "fee": 5.0, "timestamp": 1000,
            })
        assert db.get_total_realized_pnl() == 350.0

    def test_get_total_fees(self, db):
        for fee in [5.0, 3.0, 7.0]:
            db.save_trade({
                "symbol": "ETH/USDT:USDT", "side": "sell",
                "entry_price": 3000, "exit_price": 2900,
                "quantity": 0.1, "pnl": 10.0, "fee": fee, "timestamp": 1000,
            })
        assert db.get_total_fees() == 15.0

    def test_save_and_get_open_positions(self, db):
        positions = {
            "BTC/USDT:USDT": Position(
                symbol="BTC/USDT:USDT", side=Side.BUY,
                quantity=0.1, entry_price=60000.0, current_price=61000.0,
                stop_loss=58000.0, take_profit=None,
            ),
        }
        db.save_open_positions(positions)

        result = db.get_open_positions()
        assert len(result) == 1
        assert result[0]["symbol"] == "BTC/USDT:USDT"
        assert result[0]["stop_loss"] == 58000.0

    def test_open_positions_replaced_on_save(self, db):
        pos1 = {"BTC/USDT:USDT": Position(
            symbol="BTC/USDT:USDT", side=Side.BUY,
            quantity=0.1, entry_price=60000, current_price=60000,
        )}
        db.save_open_positions(pos1)
        assert len(db.get_open_positions()) == 1

        # Save empty — should clear
        db.save_open_positions({})
        assert len(db.get_open_positions()) == 0

    def test_empty_db(self, db):
        assert db.get_equity_curve() == []
        assert db.get_trades() == []
        assert db.get_open_positions() == []
        assert db.get_latest_snapshot() is None
        assert db.get_total_realized_pnl() == 0.0
        assert db.get_total_fees() == 0.0


class TestTrackerWithDB:
    def test_tracker_persists_trade(self, db):
        tracker = PortfolioTracker(10000.0, db=db)

        # Open position
        tracker.on_fill(Fill(
            order_id="1", symbol="BTC/USDT:USDT", side=Side.BUY,
            quantity=0.1, price=60000.0, fee=6.0, timestamp=1000,
        ))
        assert db.get_trade_count() == 0  # No trade yet, just opened

        # Close position
        tracker.on_fill(Fill(
            order_id="2", symbol="BTC/USDT:USDT", side=Side.SELL,
            quantity=0.1, price=62000.0, fee=6.2, timestamp=2000,
        ))
        assert db.get_trade_count() == 1
        trades = db.get_trades()
        assert trades[0]["pnl"] > 0

    def test_tracker_persists_snapshot(self, db):
        tracker = PortfolioTracker(10000.0, db=db)
        tracker.take_snapshot(1000)

        curve = db.get_equity_curve()
        assert len(curve) == 1
        assert curve[0]["equity"] == 10000.0

    def test_tracker_restores_from_db(self, db):
        # First tracker: make some trades
        tracker1 = PortfolioTracker(10000.0, db=db)
        tracker1.on_fill(Fill(
            order_id="1", symbol="BTC/USDT:USDT", side=Side.BUY,
            quantity=0.1, price=60000.0, fee=6.0, timestamp=1000,
        ))
        tracker1.on_fill(Fill(
            order_id="2", symbol="BTC/USDT:USDT", side=Side.SELL,
            quantity=0.1, price=62000.0, fee=6.2, timestamp=2000,
        ))
        saved_pnl = tracker1._realized_pnl

        # Second tracker: should restore state
        tracker2 = PortfolioTracker(10000.0, db=db)
        assert tracker2._realized_pnl == saved_pnl
        assert len(tracker2.closed_trades) == 1
