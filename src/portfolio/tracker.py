from __future__ import annotations

from src.core.enums import Side
from src.core.models import Fill, Position, PortfolioSnapshot
from src.utils.logger import get_trade_logger

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

    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.open_positions: dict[str, Position] = {}
        self.closed_trades: list[dict] = []
        self.equity_curve: list[PortfolioSnapshot] = []
        self._realized_pnl = 0.0
        self._total_fees = 0.0
        self._position_entry_fees: dict[str, float] = {}

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
        if not self.equity_curve:
            return 0.0
        peak = max(snap.equity for snap in self.equity_curve)
        current_eq = self.equity
        if peak <= 0:
            return 0.0
        return max(0.0, (peak - current_eq) / peak)

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
                    self.closed_trades.append({
                        "symbol": symbol,
                        "side": pos.side.value,
                        "entry_price": pos.entry_price,
                        "exit_price": fill.price,
                        "quantity": close_qty,
                        "pnl": net_pnl,
                        "fee": total_trade_fee,
                        "timestamp": fill.timestamp,
                    })
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
        self.closed_trades.append({
            "symbol": symbol,
            "side": pos.side.value,
            "entry_price": pos.entry_price,
            "exit_price": fill.price,
            "quantity": pos.quantity,
            "pnl": pnl,
            "fee": fee,
            "timestamp": fill.timestamp,
        })
        trade_logger.info(
            f"CLOSE {pos.side.value} {symbol} qty={pos.quantity:.6f} "
            f"entry={pos.entry_price:.2f} exit={fill.price:.2f} pnl={pnl:.2f}"
        )

    # ------------------------------------------------------------------
    # Price updates & snapshots
    # ------------------------------------------------------------------

    def update_prices(self, prices: dict[str, float]) -> None:
        for symbol, price in prices.items():
            if symbol in self.open_positions:
                self.open_positions[symbol].current_price = price

    def take_snapshot(self, timestamp: int) -> PortfolioSnapshot:
        snapshot = PortfolioSnapshot(
            timestamp=timestamp,
            equity=self.equity,
            cash=self.cash,
            unrealized_pnl=self.unrealized_pnl,
            realized_pnl=self._realized_pnl,
            positions_count=len(self.open_positions),
        )
        self.equity_curve.append(snapshot)
        return snapshot
