import logging
import logging.config
import re
from pathlib import Path

import yaml

# Matches Telegram bot tokens: bot<digits>:<alphanumeric+_->
_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]{20,}")


class TokenRedactingFilter(logging.Filter):
    """Scrub Telegram bot tokens from log records.

    Redacts token patterns in both msg and args without consuming args,
    so third-party formatters (e.g. uvicorn AccessFormatter) still work.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact the message template itself
        record.msg = _TOKEN_RE.sub("[REDACTED]", str(record.msg))
        # Redact any string arguments (without removing args)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: _TOKEN_RE.sub("[REDACTED]", str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _TOKEN_RE.sub("[REDACTED]", str(a)) if isinstance(a, str) else a
                    for a in record.args
                )
        return True


def setup_logging(config_path: str = "config/logging.yaml", log_level: str = "INFO") -> None:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file) as f:
            config = yaml.safe_load(f)
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(
            level=getattr(logging, log_level.upper(), logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # Apply token redaction filter to root and algo_trading handlers.
    # Safe for all loggers (including uvicorn) because the filter
    # no longer consumes record.args.
    redact_filter = TokenRedactingFilter()
    for handler in logging.root.handlers:
        handler.addFilter(redact_filter)
    for lg in logging.Logger.manager.loggerDict.values():
        if isinstance(lg, logging.Logger):
            for handler in lg.handlers:
                handler.addFilter(redact_filter)

    # Suppress httpx/httpcore DEBUG/INFO — they log full URLs including
    # Telegram bot tokens. Force WARNING regardless of logging.yaml state.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root = logging.getLogger("algo_trading")
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"algo_trading.{name}")


def get_trade_logger() -> logging.Logger:
    return logging.getLogger("algo_trading.trades")
