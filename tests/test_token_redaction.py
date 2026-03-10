"""Tests for Telegram token redaction in logs (Fix #3)."""
import logging

from src.utils.logger import TokenRedactingFilter


class TestTokenRedaction:
    def setup_method(self):
        self.filt = TokenRedactingFilter()

    def _make_record(self, msg: str, args=None) -> logging.LogRecord:
        record = logging.LogRecord(
            name="test", level=logging.WARNING,
            pathname="", lineno=0, msg=msg,
            args=args, exc_info=None,
        )
        return record

    def test_token_scrubbed(self):
        record = self._make_record(
            "POST https://api.telegram.org/bot123456789:ABCdef_ghiJKLmnop-12345678/sendMessage"
        )
        self.filt.filter(record)
        assert "123456789" not in record.msg
        assert "[REDACTED]" in record.msg
        assert "sendMessage" in record.msg

    def test_normal_message_unchanged(self):
        record = self._make_record("Fetched 100 bars for BTCUSDT")
        self.filt.filter(record)
        assert record.msg == "Fetched 100 bars for BTCUSDT"

    def test_multiple_tokens_scrubbed(self):
        record = self._make_record(
            "url1=bot111:AAA_bbb_ccc_ddd_eee_fff url2=bot222:ZZZ_yyy_xxx_www_vvv_uuu"
        )
        self.filt.filter(record)
        assert "111" not in record.msg
        assert "222" not in record.msg
        assert record.msg.count("[REDACTED]") == 2

    def test_args_redacted_in_place(self):
        """Token in args is redacted without consuming args (uvicorn compat)."""
        record = self._make_record(
            "Request to %s failed",
            ("https://api.telegram.org/bot999:ABCDEFGHIJ_klmnopqrst/sendMessage",),
        )
        self.filt.filter(record)
        # Args should still be a tuple (not None) — uvicorn needs them
        assert isinstance(record.args, tuple)
        # But the token inside should be scrubbed
        assert "999" not in record.args[0]
        assert "[REDACTED]" in record.args[0]
