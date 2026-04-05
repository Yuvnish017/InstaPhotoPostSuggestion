"""Small wrapper around Python logging with rotating file output."""

import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import datetime
from config import LOGS_PATH


class Logger:
    """Project logger with per-module rotating file handlers."""

    def __init__(self, log_file_name: str):
        """Create or reuse a named logger bound to `LOGS_PATH/log_file_name`."""
        self.file_path = os.path.join(LOGS_PATH, log_file_name)
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

        logging_format = "%(asctime)s [%(levelname)s]: %(message)s"
        file_handler = RotatingFileHandler(
            self.file_path,
            mode='a',
            maxBytes=500000,  # 100 KB
            backupCount=5,  # keep 5 old logs
            encoding='utf-8',
            delay=False
        )
        formatter = logging.Formatter(logging_format)
        file_handler.setFormatter(formatter)

        self.logger = logging.getLogger(log_file_name)

        # Avoid duplicate handlers when modules are imported multiple times.
        if not self.logger.handlers:
            self.logger.addHandler(file_handler)
        self.logger.setLevel(logging.DEBUG)

        # Keep log lines isolated to dedicated files.
        self.logger.propagate = False
        self.logger.info(f"Starting logging at {datetime.now()}")

    def debug(self, msg: str) -> None:
        self.logger.debug(msg)

    def info(self, msg: str) -> None:
        self.logger.info(msg)

    def warning(self, msg: str) -> None:
        self.logger.warning(msg)

    def critical(self, msg: str) -> None:
        self.logger.critical(msg)

    def error(self, msg: str) -> None:
        self.logger.error(msg)

    def log_file_path(self) -> str:
        return self.file_path
