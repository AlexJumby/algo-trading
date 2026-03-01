import logging
import logging.config
from pathlib import Path

import yaml


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

    root = logging.getLogger("algo_trading")
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"algo_trading.{name}")


def get_trade_logger() -> logging.Logger:
    return logging.getLogger("algo_trading.trades")
