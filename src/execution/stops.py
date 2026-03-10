"""Shared trailing-stop logic used by both backtest and live engines."""
from __future__ import annotations

from src.core.enums import Side
from src.core.models import Position
from src.utils.logger import get_logger

logger = get_logger("stops")

MAX_SL_PCT = 0.15  # Max stop-loss distance as fraction of price


def trail_stop(pos: Position, price: float, atr: float, mult: float) -> bool:
    """Move stop-loss in the direction of profit (trailing stop).

    ATR distance is clamped to MAX_SL_PCT of price to prevent absurd
    stop levels from data gaps (e.g. ATR $127K → SL at $464K).

    Returns True if the stop was updated, False otherwise.
    """
    distance = atr * mult
    max_distance = price * MAX_SL_PCT
    if distance > max_distance:
        logger.warning(
            f"Trail ATR distance clamped: {distance:.2f} -> {max_distance:.2f}"
        )
        distance = max_distance

    if pos.side == Side.BUY:
        new_sl = price - distance
        if pos.stop_loss is None or new_sl > pos.stop_loss:
            pos.stop_loss = new_sl
            return True
    else:
        new_sl = price + distance
        if pos.stop_loss is None or new_sl < pos.stop_loss:
            pos.stop_loss = new_sl
            return True
    return False
