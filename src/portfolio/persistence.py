"""SQLite persistence for portfolio data.

Write from the trading bot, read from the dashboard.
Uses WAL mode for safe concurrent access.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.core.models import PortfolioSnapshot
from src.utils.logger import get_logger

logger = get_logger("persistence")


class PortfolioDB:
    """Lightweight SQLite store for equity snapshots, trades, and positions."""

    def __init__(self, db_path: str = "data/portfolio.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        logger.info(f"Portfolio DB opened: {db_path}")

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                equity REAL NOT NULL,
                cash REAL NOT NULL,
                unrealized_pnl REAL NOT NULL,
                realized_pnl REAL NOT NULL,
                positions_count INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                quantity REAL NOT NULL,
                pnl REAL NOT NULL,
                fee REAL NOT NULL,
                timestamp INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS open_positions (
                symbol TEXT PRIMARY KEY,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                entry_price REAL NOT NULL,
                current_price REAL NOT NULL,
                stop_loss REAL,
                take_profit REAL,
                unrealized_pnl REAL NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_equity_ts
                ON equity_snapshots(timestamp);
            CREATE INDEX IF NOT EXISTS idx_trades_ts
                ON trades(timestamp);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write methods (called by bot)
    # ------------------------------------------------------------------

    def save_snapshot(self, snap: PortfolioSnapshot) -> None:
        self._conn.execute(
            """INSERT INTO equity_snapshots
               (timestamp, equity, cash, unrealized_pnl, realized_pnl, positions_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (snap.timestamp, snap.equity, snap.cash,
             snap.unrealized_pnl, snap.realized_pnl, snap.positions_count),
        )
        self._conn.commit()

    def save_trade(self, trade: dict) -> None:
        self._conn.execute(
            """INSERT INTO trades
               (symbol, side, entry_price, exit_price, quantity, pnl, fee, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (trade["symbol"], trade["side"], trade["entry_price"],
             trade["exit_price"], trade["quantity"], trade["pnl"],
             trade["fee"], trade["timestamp"]),
        )
        self._conn.commit()

    def save_open_positions(self, positions: dict) -> None:
        """Replace all open positions (full snapshot)."""
        self._conn.execute("DELETE FROM open_positions")
        for symbol, pos in positions.items():
            self._conn.execute(
                """INSERT INTO open_positions
                   (symbol, side, quantity, entry_price, current_price,
                    stop_loss, take_profit, unrealized_pnl)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, pos.side.value, pos.quantity, pos.entry_price,
                 pos.current_price, pos.stop_loss, pos.take_profit,
                 pos.unrealized_pnl),
            )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read methods (called by dashboard and restore)
    # ------------------------------------------------------------------

    def get_equity_curve(self, since_ts: int = 0, limit: int = 10000) -> list[dict]:
        rows = self._conn.execute(
            """SELECT timestamp, equity, cash, unrealized_pnl, realized_pnl, positions_count
               FROM equity_snapshots
               WHERE timestamp >= ?
               ORDER BY timestamp ASC
               LIMIT ?""",
            (since_ts, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_trades(self, limit: int = 100) -> list[dict]:
        rows = self._conn.execute(
            """SELECT symbol, side, entry_price, exit_price, quantity, pnl, fee, timestamp
               FROM trades
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_open_positions(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM open_positions"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_snapshot(self) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM equity_snapshots ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_total_realized_pnl(self) -> float:
        row = self._conn.execute("SELECT COALESCE(SUM(pnl), 0) FROM trades").fetchone()
        return float(row[0])

    def get_total_fees(self) -> float:
        row = self._conn.execute("SELECT COALESCE(SUM(fee), 0) FROM trades").fetchone()
        return float(row[0])

    def get_trade_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM trades").fetchone()
        return int(row[0])

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()
