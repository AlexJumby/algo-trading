from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.config import RiskConfig
from src.core.enums import OrderType, Side, SignalAction
from src.core.models import Order, Signal
from src.risk.position_sizer import PositionSizer
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.portfolio.tracker import PortfolioTracker

logger = get_logger("risk")


class RiskManager:
    def __init__(self, config: RiskConfig, portfolio: PortfolioTracker, leverage: int = 1):
        self.config = config
        self.portfolio = portfolio
        self.sizer = PositionSizer(config)
        self.leverage = leverage

    def evaluate(self, signal: Signal, current_price: float) -> Order | None:
        """Convert a Signal into an Order after risk checks. Returns None if rejected."""

        # CLOSE signals bypass entry checks
        if signal.action == SignalAction.CLOSE:
            return self._build_close_order(signal, current_price)

        if signal.action == SignalAction.HOLD:
            return None

        # Check max open positions
        if len(self.portfolio.open_positions) >= self.config.max_open_positions:
            logger.warning(f"Max positions ({self.config.max_open_positions}) reached, rejecting")
            return None

        # Check max drawdown
        if self.portfolio.current_drawdown_pct > self.config.max_drawdown_pct:
            logger.warning(
                f"Max drawdown ({self.config.max_drawdown_pct:.1%}) exceeded "
                f"(current: {self.portfolio.current_drawdown_pct:.1%}), trading halted"
            )
            return None

        # Check if already have a position in same direction
        if signal.symbol in self.portfolio.open_positions:
            existing = self.portfolio.open_positions[signal.symbol]
            if (signal.action == SignalAction.LONG and existing.side == Side.BUY) or (
                signal.action == SignalAction.SHORT and existing.side == Side.SELL
            ):
                return None  # Already positioned in this direction

        # Position sizing (with leverage for futures)
        quantity = self.sizer.compute_size(
            equity=self.portfolio.equity,
            price=current_price,
            signal=signal,
            leverage=self.leverage,
        )
        if quantity <= 0:
            return None

        # Compute SL/TP — use ATR-based if provided by strategy, else fixed %
        sl_price = self._compute_stop_loss(signal.action, current_price, signal.metadata)
        # TP is optional — breakout strategies use trailing stop instead
        no_tp = signal.metadata.get("no_tp", False) if signal.metadata else False
        tp_price = None if no_tp else self._compute_take_profit(signal.action, current_price, signal.metadata)

        side = Side.BUY if signal.action == SignalAction.LONG else Side.SELL

        order = Order(
            symbol=signal.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            stop_loss=sl_price,
            take_profit=tp_price,
        )

        tp_str = f"{tp_price:.2f}" if tp_price is not None else "trailing"
        logger.info(
            f"Signal -> Order: {signal.action.value} {signal.symbol} "
            f"qty={quantity:.6f} sl={sl_price:.2f} tp={tp_str}"
        )
        return order

    def _build_close_order(self, signal: Signal, current_price: float) -> Order | None:
        """Build a close order for an existing position."""
        if signal.symbol not in self.portfolio.open_positions:
            return None
        pos = self.portfolio.open_positions[signal.symbol]
        close_side = Side.SELL if pos.side == Side.BUY else Side.BUY
        return Order(
            symbol=signal.symbol,
            side=close_side,
            order_type=OrderType.MARKET,
            quantity=pos.quantity,
        )

    def _compute_stop_loss(self, action: SignalAction, price: float, metadata: dict = None) -> float:
        # ATR-based SL if provided by strategy
        if metadata and "atr_sl" in metadata:
            atr_sl = metadata["atr_sl"]
            if action == SignalAction.LONG:
                return price - atr_sl
            elif action == SignalAction.SHORT:
                return price + atr_sl

        # Fallback to fixed %
        pct = self.config.default_stop_loss_pct
        if action == SignalAction.LONG:
            return price * (1 - pct)
        elif action == SignalAction.SHORT:
            return price * (1 + pct)
        return price

    def _compute_take_profit(self, action: SignalAction, price: float, metadata: dict = None) -> float:
        # ATR-based TP if provided by strategy
        if metadata and "atr_tp" in metadata:
            atr_tp = metadata["atr_tp"]
            if action == SignalAction.LONG:
                return price + atr_tp
            elif action == SignalAction.SHORT:
                return price - atr_tp

        # Fallback to fixed %
        pct = self.config.default_take_profit_pct
        if action == SignalAction.LONG:
            return price * (1 + pct)
        elif action == SignalAction.SHORT:
            return price * (1 - pct)
        return price
