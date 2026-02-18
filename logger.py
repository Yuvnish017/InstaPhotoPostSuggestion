import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import datetime


class Logger:
    def __init__(self, log_file_name):
        self.file_path = os.path.join("./logs", log_file_name)
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
        # file_handler = logging.FileHandler(filename=self.file_path, mode="a")
        formatter = logging.Formatter(logging_format)
        file_handler.setFormatter(formatter)

        self.logger = logging.getLogger(log_file_name)

        if not self.logger.handlers:
            self.logger.addHandler(file_handler)
        self.logger.setLevel(logging.DEBUG)

        # Prevent logs from propagating to the root logger( and appearing in console / other logs)
        self.logger.propagate = False
        self.logger.info(f"Starting logging at {datetime.now()}")

    def debug(self, msg):
        self.logger.debug(msg)

    def info(self, msg):
        self.logger.info(msg)

    def warning(self, msg):
        self.logger.warning(msg)

    def critical(self, msg):
        self.logger.critical(msg)

    def error(self, msg):
        self.logger.error(msg)

    def log_file_path(self):
        return self.file_path
