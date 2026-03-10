import logging
import logging.config
import re
from pathlib import Path

import yaml

# Matches Telegram bot tokens: bot<digits>:<alphanumeric+_->
_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]{20,}")


class TokenRedactingFilter(logging.Filter):
    """Scrub Telegram bot tokens from all log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            # Format the message early so we can redact it
            record.msg = str(record.msg) % record.args
            record.args = None
        record.msg = _TOKEN_RE.sub("[REDACTED]", str(record.msg))
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

    # Apply token redaction filter to ALL handlers
    redact_filter = TokenRedactingFilter()
    for handler in logging.root.handlers:
        handler.addFilter(redact_filter)
    for lg in logging.Logger.manager.loggerDict.values():
        if isinstance(lg, logging.Logger):
            for handler in lg.handlers:
                handler.addFilter(redact_filter)

    root = logging.getLogger("algo_trading")
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"algo_trading.{name}")


def get_trade_logger() -> logging.Logger:
    return logging.getLogger("algo_trading.trades")
