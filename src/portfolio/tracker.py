from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.enums import Side
from src.core.models import Fill, Position, PortfolioSnapshot
from src.utils.logger import get_trade_logger

if TYPE_CHECKING:
    from src.portfolio.persistence import PortfolioDB

trade_logger = get_trade_logger()


class PortfolioTracker:
    """Track portfolio state via PnL-based accounting.

    Equity formula:
        equity = initial_capital + realized_pnl + unrealized_pnl - open_entry_fees

    Where:
        - realized_pnl: net PnL of all closed trades (gross pnl minus entry+exit fees)
        - unrealized_pnl: gross mark-to-market PnL on open positions
        - open_entry_fees: fees paid to open currently-held positions
    """

    def __init__(self, initial_capital: float, db: PortfolioDB | None = None):
        self.initial_capital = initial_capital
        self.db = db
        self.open_positions: dict[str, Position] = {}
        self.closed_trades: list[dict] = []
        self.equity_curve: list[PortfolioSnapshot] = []
        self._realized_pnl = 0.0
        self._total_fees = 0.0
        self._position_entry_fees: dict[str, float] = {}
        self._peak_equity = initial_capital

        # Restore state from DB if available
        if db:
            self._restore_from_db()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def equity(self) -> float:
        open_fees = sum(self._position_entry_fees.values())
        return self.initial_capital + self._realized_pnl + self.unrealized_pnl - open_fees

    @property
    def cash(self) -> float:
        """Available cash (equity minus notional value of open positions)."""
        pos_value = sum(
            p.quantity * p.entry_price for p in self.open_positions.values()
        )
        return self.equity - pos_value

    @property
    def unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.open_positions.values())

    @property
    def total_fees(self) -> float:
        return self._total_fees

    @property
    def current_drawdown_pct(self) -> float:
        if self._peak_equity <= 0:
            return 0.0
        current_eq = self.equity
        return max(0.0, (self._peak_equity - current_eq) / self._peak_equity)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_fill(self, fill: Fill) -> None:
        """Process a fill: open, add-to, or close a position."""
        symbol = fill.symbol
        self._total_fees += fill.fee

        if symbol in self.open_positions:
            pos = self.open_positions[symbol]

            if fill.side != pos.side:
                # ---- Closing (full or partial) ----
                close_qty = min(fill.quantity, pos.quantity)

                gross_pnl = self._compute_gross_pnl(pos, close_qty, fill.price)

                # Proportional entry-fee attribution
                fee_ratio = close_qty / pos.quantity
                entry_fee_portion = self._position_entry_fees.get(symbol, 0.0) * fee_ratio
                total_trade_fee = entry_fee_portion + fill.fee
                net_pnl = gross_pnl - total_trade_fee

                self._realized_pnl += net_pnl

                if fill.quantity >= pos.quantity:
                    # Full close
                    self._position_entry_fees.pop(symbol, None)
                    self._close_position(symbol, net_pnl, total_trade_fee, fill)
                else:
                    # Partial close
                    self._position_entry_fees[symbol] -= entry_fee_portion
                    pos.quantity -= close_qty
                    trade_dict = {
                        "symbol": symbol,
                        "side": pos.side.value,
                        "entry_price": pos.entry_price,
                        "exit_price": fill.price,
                        "quantity": close_qty,
                        "pnl": net_pnl,
                        "fee": total_trade_fee,
                        "timestamp": fill.timestamp,
                    }
                    self.closed_trades.append(trade_dict)
                    if self.db:
                        self.db.save_trade(trade_dict)
                        self.db.save_open_positions(self.open_positions)
                return

            # ---- Adding to existing position (same side) ----
            total_qty = pos.quantity + fill.quantity
            pos.entry_price = (
                pos.entry_price * pos.quantity + fill.price * fill.quantity
            ) / total_qty
            pos.quantity = total_qty
            self._position_entry_fees[symbol] = (
                self._position_entry_fees.get(symbol, 0.0) + fill.fee
            )
        else:
            # ---- Opening new position ----
            self._position_entry_fees[symbol] = fill.fee
            self.open_positions[symbol] = Position(
                symbol=symbol,
                side=fill.side,
                quantity=fill.quantity,
                entry_price=fill.price,
                current_price=fill.price,
                stop_loss=None,
                take_profit=None,
            )
            trade_logger.info(
                f"OPEN {fill.side.value} {symbol} qty={fill.quantity:.6f} "
                f"price={fill.price:.2f}"
            )

    # ------------------------------------------------------------------
    # DB restore
    # ------------------------------------------------------------------

    def _restore_from_db(self) -> None:
        """Restore realized PnL and trade history from SQLite on startup."""
        if not self.db:
            return
        self._realized_pnl = self.db.get_total_realized_pnl()
        self._total_fees = self.db.get_total_fees()
        self.closed_trades = self.db.get_trades(limit=50000)
        # Update peak equity based on restored state
        self._peak_equity = max(self._peak_equity, self.equity)
        trade_logger.info(
            f"Restored from DB: {len(self.closed_trades)} trades, "
            f"realized_pnl=${self._realized_pnl:.2f}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_gross_pnl(pos: Position, close_qty: float, exit_price: float) -> float:
        """Price-difference PnL, no fees."""
        if pos.side == Side.BUY:
            return (exit_price - pos.entry_price) * close_qty
        else:
            return (pos.entry_price - exit_price) * close_qty

    def _close_position(
        self, symbol: str, pnl: float, fee: float, fill: Fill,
    ) -> None:
        pos = self.open_positions.pop(symbol)
        trade_dict = {
            "symbol": symbol,
            "side": pos.side.value,
            "entry_price": pos.entry_price,
            "exit_price": fill.price,
            "quantity": pos.quantity,
            "pnl": pnl,
            "fee": fee,
            "timestamp": fill.timestamp,
        }
        self.closed_trades.append(trade_dict)
        trade_logger.info(
            f"CLOSE {pos.side.value} {symbol} qty={pos.quantity:.6f} "
            f"entry={pos.entry_price:.2f} exit={fill.price:.2f} pnl={pnl:.2f}"
        )
        if self.db:
            self.db.save_trade(trade_dict)
            self.db.save_open_positions(self.open_positions)

    # ------------------------------------------------------------------
    # Funding costs
    # ------------------------------------------------------------------

    def apply_funding_cost(self, cost: float) -> None:
        """Deduct a funding cost from realized PnL (reduces equity)."""
        self._realized_pnl -= cost
        self._total_fees += cost

    # ------------------------------------------------------------------
    # Price updates & snapshots
    # ------------------------------------------------------------------

    def update_prices(self, prices: dict[str, float]) -> None:
        for symbol, price in prices.items():
            if symbol in self.open_positions:
                self.open_positions[symbol].current_price = price

    def take_snapshot(self, timestamp: int) -> PortfolioSnapshot:
        eq = self.equity
        if eq > self._peak_equity:
            self._peak_equity = eq
        snapshot = PortfolioSnapshot(
            timestamp=timestamp,
            equity=eq,
            cash=self.cash,
            unrealized_pnl=self.unrealized_pnl,
            realized_pnl=self._realized_pnl,
            positions_count=len(self.open_positions),
        )
        self.equity_curve.append(snapshot)
        if self.db:
            self.db.save_snapshot(snapshot)
            self.db.save_open_positions(self.open_positions)
        return snapshot
