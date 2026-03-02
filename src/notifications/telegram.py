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
        """Send an HTML message. Silently swallows errors."""
        if not self.enabled or not self._client:
            return
        try:
            resp = self._client.post(
                self.API_URL.format(token=self.token),
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            if resp.status_code != 200:
                logger.warning(
                    f"Telegram API {resp.status_code}: {resp.text[:200]}"
                )
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")

    # ------------------------------------------------------------------
    # High-level event methods
    # ------------------------------------------------------------------

    def notify_engine_start(
        self, pairs: list[str], strategy: str, mode: str,
    ) -> None:
        pairs_str = ", ".join(f"<code>{p}</code>" for p in pairs)
        msg = (
            "<b>Bot Started</b>\n"
            f"Mode: <code>{mode}</code>\n"
            f"Strategy: <code>{strategy}</code>\n"
            f"Pairs: {pairs_str}\n"
            f"Time: {_now()}"
        )
        self.send(msg)

    def notify_trade_open(
        self, symbol: str, side: str, qty: float, price: float,
        sl: float | None, equity: float,
    ) -> None:
        icon = "🟢" if side == "buy" else "🔴"
        sl_str = f"${sl:,.2f}" if sl else "trailing"
        msg = (
            f"<b>Trade Opened</b>\n"
            f"{icon} <code>{side.upper()}</code> <code>{symbol}</code>\n"
            f"Qty: <code>{qty:.6f}</code> @ <code>${price:,.2f}</code>\n"
            f"SL: <code>{sl_str}</code>\n"
            f"Equity: <code>${equity:,.2f}</code>"
        )
        self.send(msg)

    def notify_trade_close(
        self, symbol: str, side: str, qty: float,
        entry_price: float, exit_price: float,
        pnl: float, trigger: str, equity: float, drawdown: float,
    ) -> None:
        emoji = "✅" if pnl >= 0 else "❌"
        msg = (
            f"<b>Trade Closed</b> ({trigger})\n"
            f"{emoji} <code>{side.upper()}</code> <code>{symbol}</code>\n"
            f"Entry: <code>${entry_price:,.2f}</code> → "
            f"Exit: <code>${exit_price:,.2f}</code>\n"
            f"PnL: <code>${pnl:,.2f}</code>\n"
            f"Equity: <code>${equity:,.2f}</code> | "
            f"DD: <code>{drawdown:.1%}</code>"
        )
        self.send(msg)

    def notify_trailing_stop(
        self, symbol: str, old_sl: float | None, new_sl: float, price: float,
    ) -> None:
        old_str = f"${old_sl:,.2f}" if old_sl else "None"
        msg = (
            f"<b>Trailing Stop Updated</b>\n"
            f"<code>{symbol}</code> @ <code>${price:,.2f}</code>\n"
            f"SL: <code>{old_str}</code> → <code>${new_sl:,.2f}</code>"
        )
        self.send(msg)

    def notify_status(
        self, equity: float, cash: float, drawdown: float,
        open_positions: dict, closed_count: int,
    ) -> None:
        lines = [
            f"<b>Status Report</b> ({_now()})",
            f"Equity: <code>${equity:,.2f}</code>",
            f"Cash: <code>${cash:,.2f}</code>",
            f"Drawdown: <code>{drawdown:.1%}</code>",
            f"Open: <code>{len(open_positions)}</code> | "
            f"Closed: <code>{closed_count}</code>",
        ]
        for sym, pos in open_positions.items():
            sl_str = f" sl=<code>${pos.stop_loss:,.2f}</code>" if pos.stop_loss else ""
            lines.append(
                f"  <code>{sym}</code>: {pos.side.value} "
                f"pnl=<code>${pos.unrealized_pnl:,.2f}</code>{sl_str}"
            )
        self.send("\n".join(lines))

    def notify_error(self, error_msg: str) -> None:
        safe_msg = error_msg[:500].replace("<", "&lt;").replace(">", "&gt;")
        msg = f"<b>Error</b>\n<pre>{safe_msg}</pre>"
        self.send(msg)

    def notify_max_drawdown_halt(self, drawdown_pct: float) -> None:
        msg = (
            f"<b>MAX DRAWDOWN HALT</b>\n"
            f"Drawdown: <code>{drawdown_pct:.1%}</code>\n"
            f"New trades suspended!"
        )
        self.send(msg)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
