"""Shared trailing-stop logic used by both backtest and live engines."""
from __future__ import annotations

from src.core.enums import Side
from src.core.models import Position


def trail_stop(pos: Position, price: float, atr: float, mult: float) -> bool:
    """Move stop-loss in the direction of profit (trailing stop).

    Returns True if the stop was updated, False otherwise.
    """
    if pos.side == Side.BUY:
        new_sl = price - atr * mult
        if pos.stop_loss is None or new_sl > pos.stop_loss:
            pos.stop_loss = new_sl
            return True
    else:
        new_sl = price + atr * mult
        if pos.stop_loss is None or new_sl < pos.stop_loss:
            pos.stop_loss = new_sl
            return True
    return False
