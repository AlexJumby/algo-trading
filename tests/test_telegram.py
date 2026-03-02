"""Tests for Telegram notifier."""
import os
from unittest.mock import MagicMock, patch

from src.notifications.telegram import TelegramNotifier


class TestTelegramNotifier:
    def test_disabled_when_no_env(self):
        """Notifier should be disabled when env vars are missing."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove any existing telegram vars
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            notifier = TelegramNotifier()
            assert not notifier.enabled
            assert notifier._client is None

    def test_enabled_when_env_set(self):
        """Notifier should be enabled when both env vars are set."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_CHAT_ID": "-100123",
        }):
            notifier = TelegramNotifier()
            assert notifier.enabled
            assert notifier._client is not None
            notifier._client.close()

    def test_send_disabled_noop(self):
        """send() should be a no-op when disabled."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            notifier = TelegramNotifier()
            # Should not raise
            notifier.send("Hello")

    def test_send_posts_message(self):
        """send() should POST to Telegram API when enabled."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_CHAT_ID": "-100123",
        }):
            notifier = TelegramNotifier()
            notifier._client = MagicMock()

            notifier.send("Test message")

            notifier._client.post.assert_called_once()
            call_args = notifier._client.post.call_args
            assert "123:ABC" in call_args[0][0]
            assert call_args[1]["json"]["chat_id"] == "-100123"
            assert call_args[1]["json"]["text"] == "Test message"
            assert call_args[1]["json"]["parse_mode"] == "Markdown"

    def test_send_swallows_exceptions(self):
        """send() should never raise, even if HTTP fails."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_CHAT_ID": "-100123",
        }):
            notifier = TelegramNotifier()
            notifier._client = MagicMock()
            notifier._client.post.side_effect = Exception("Network error")

            # Should not raise
            notifier.send("Test")

    def test_notify_engine_start(self):
        """notify_engine_start should call send with correct content."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_CHAT_ID": "-100123",
        }):
            notifier = TelegramNotifier()
            notifier.send = MagicMock()

            notifier.notify_engine_start(
                ["BTC/USDT:USDT", "ETH/USDT:USDT"], "tsmom_v1", "paper",
            )

            notifier.send.assert_called_once()
            msg = notifier.send.call_args[0][0]
            assert "Bot Started" in msg
            assert "paper" in msg
            assert "tsmom_v1" in msg
            assert "BTC/USDT:USDT" in msg

    def test_notify_trade_open(self):
        """notify_trade_open should include symbol, side, price, equity."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_CHAT_ID": "-100123",
        }):
            notifier = TelegramNotifier()
            notifier.send = MagicMock()

            notifier.notify_trade_open(
                "BTC/USDT:USDT", "buy", 0.1, 60000.0, 57000.0, 10000.0,
            )

            msg = notifier.send.call_args[0][0]
            assert "Trade Opened" in msg
            assert "BUY" in msg
            assert "BTC/USDT:USDT" in msg
            assert "$60,000.00" in msg

    def test_notify_trade_close(self):
        """notify_trade_close should include PnL and trigger."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_CHAT_ID": "-100123",
        }):
            notifier = TelegramNotifier()
            notifier.send = MagicMock()

            notifier.notify_trade_close(
                "ETH/USDT:USDT", "buy", 1.0,
                3000.0, 3500.0, 500.0, "SL",
                10500.0, 0.02,
            )

            msg = notifier.send.call_args[0][0]
            assert "Trade Closed" in msg
            assert "SL" in msg
            assert "$500.00" in msg

    def test_notify_trailing_stop(self):
        """notify_trailing_stop should show old → new SL."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_CHAT_ID": "-100123",
        }):
            notifier = TelegramNotifier()
            notifier.send = MagicMock()

            notifier.notify_trailing_stop("BTC/USDT:USDT", 57000.0, 58000.0, 62000.0)

            msg = notifier.send.call_args[0][0]
            assert "Trailing Stop" in msg
            assert "$57,000.00" in msg
            assert "$58,000.00" in msg

    def test_notify_error(self):
        """notify_error should wrap message in code block."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_CHAT_ID": "-100123",
        }):
            notifier = TelegramNotifier()
            notifier.send = MagicMock()

            notifier.notify_error("Connection timeout")

            msg = notifier.send.call_args[0][0]
            assert "Error" in msg
            assert "Connection timeout" in msg

    def test_notify_max_drawdown_halt(self):
        """notify_max_drawdown_halt should show DD percentage."""
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_CHAT_ID": "-100123",
        }):
            notifier = TelegramNotifier()
            notifier.send = MagicMock()

            notifier.notify_max_drawdown_halt(0.25)

            msg = notifier.send.call_args[0][0]
            assert "MAX DRAWDOWN HALT" in msg
            assert "25.0%" in msg

    def test_all_methods_noop_when_disabled(self):
        """All notify methods should be no-ops when disabled."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            notifier = TelegramNotifier()

            # None of these should raise
            notifier.notify_engine_start(["BTC"], "strat", "paper")
            notifier.notify_trade_open("BTC", "buy", 0.1, 100, 90, 1000)
            notifier.notify_trade_close("BTC", "buy", 0.1, 100, 110, 10, "SL", 1010, 0.01)
            notifier.notify_trailing_stop("BTC", 90, 95, 110)
            notifier.notify_status(1000, 900, 0.01, {}, 5)
            notifier.notify_error("test")
            notifier.notify_max_drawdown_halt(0.1)
