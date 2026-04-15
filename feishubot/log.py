"""统一日志模块：输出到控制台和 logs/app.log。"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


_LOGGER_INITIALIZED = False


def _init_root_logger() -> None:
    global _LOGGER_INITIALIZED
    if _LOGGER_INITIALIZED:
        return

    base_dir = Path(__file__).parent.parent
    log_file = os.environ.get("FEISHU_BOT_LOG_FILE", str(base_dir / "logs" / "app.log"))
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("feishubot")
    root.setLevel(getattr(logging, log_level, logging.INFO))
    root.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(threadName)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    _LOGGER_INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """返回项目 logger。"""
    _init_root_logger()
    logger = logging.getLogger(f"feishubot.{name}")
    logger.setLevel(logging.getLogger("feishubot").level)
    return logger
