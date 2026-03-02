"""Telegram Bot API notifications for trade events.

Reads config from environment variables:
    TELEGRAM_BOT_TOKEN  — token from @BotFather
    TELEGRAM_CHAT_ID    — your chat/group ID

If not configured, all methods are silent no-ops.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx

from src.utils.logger import get_logger

logger = get_logger("notifications.telegram")


class TelegramNotifier:
    """Fire-and-forget Telegram notifications. Never raises."""

    API_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.enabled = bool(self.token and self.chat_id)
        self._client: httpx.Client | None = None

        if self.enabled:
            self._client = httpx.Client(timeout=10)
            logger.info("Telegram notifications enabled")
        else:
            logger.info("Telegram notifications disabled (no token/chat_id)")

    # ------------------------------------------------------------------
    # Low-level send
    # ------------------------------------------------------------------

    def send(self, message: str) -> None:
        """Send a markdown message. Silently swallows errors."""
        if not self.enabled or not self._client:
            return
        try:
            self._client.post(
                self.API_URL.format(token=self.token),
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
            )
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")

    # ------------------------------------------------------------------
    # High-level event methods
    # ------------------------------------------------------------------

    def notify_engine_start(
        self, pairs: list[str], strategy: str, mode: str,
    ) -> None:
        msg = (
            "*Bot Started*\n"
            f"Mode: `{mode}`\n"
            f"Strategy: `{strategy}`\n"
            f"Pairs: {', '.join(f'`{p}`' for p in pairs)}\n"
            f"Time: {_now()}"
        )
        self.send(msg)

    def notify_trade_open(
        self, symbol: str, side: str, qty: float, price: float,
        sl: float | None, equity: float,
    ) -> None:
        sl_str = f"${sl:,.2f}" if sl else "trailing"
        msg = (
            f"*Trade Opened*\n"
            f"{'🟢' if side == 'buy' else '🔴'} `{side.upper()}` `{symbol}`\n"
            f"Qty: `{qty:.6f}` @ `${price:,.2f}`\n"
            f"SL: `{sl_str}`\n"
            f"Equity: `${equity:,.2f}`"
        )
        self.send(msg)

    def notify_trade_close(
        self, symbol: str, side: str, qty: float,
        entry_price: float, exit_price: float,
        pnl: float, trigger: str, equity: float, drawdown: float,
    ) -> None:
        emoji = "✅" if pnl >= 0 else "❌"
        msg = (
            f"*Trade Closed* ({trigger})\n"
            f"{emoji} `{side.upper()}` `{symbol}`\n"
            f"Entry: `${entry_price:,.2f}` → Exit: `${exit_price:,.2f}`\n"
            f"PnL: `${pnl:,.2f}`\n"
            f"Equity: `${equity:,.2f}` | DD: `{drawdown:.1%}`"
        )
        self.send(msg)

    def notify_trailing_stop(
        self, symbol: str, old_sl: float | None, new_sl: float, price: float,
    ) -> None:
        old_str = f"${old_sl:,.2f}" if old_sl else "None"
        msg = (
            f"*Trailing Stop Updated*\n"
            f"`{symbol}` @ `${price:,.2f}`\n"
            f"SL: `{old_str}` → `${new_sl:,.2f}`"
        )
        self.send(msg)

    def notify_status(
        self, equity: float, cash: float, drawdown: float,
        open_positions: dict, closed_count: int,
    ) -> None:
        lines = [
            f"*Status Report* ({_now()})",
            f"Equity: `${equity:,.2f}`",
            f"Cash: `${cash:,.2f}`",
            f"Drawdown: `{drawdown:.1%}`",
            f"Open: `{len(open_positions)}` | Closed: `{closed_count}`",
        ]
        for sym, pos in open_positions.items():
            lines.append(
                f"  `{sym}`: {pos.side.value} "
                f"pnl=`${pos.unrealized_pnl:,.2f}` "
                f"sl=`${pos.stop_loss:,.2f}`" if pos.stop_loss else
                f"  `{sym}`: {pos.side.value} pnl=`${pos.unrealized_pnl:,.2f}`"
            )
        self.send("\n".join(lines))

    def notify_error(self, error_msg: str) -> None:
        msg = f"*Error*\n```\n{error_msg[:500]}\n```"
        self.send(msg)

    def notify_max_drawdown_halt(self, drawdown_pct: float) -> None:
        msg = (
            f"*MAX DRAWDOWN HALT*\n"
            f"Drawdown: `{drawdown_pct:.1%}`\n"
            f"New trades suspended!"
        )
        self.send(msg)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
