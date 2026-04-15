import logging
import os
from datetime import datetime


class TestLogger:
    def __init__(self, test_name: str):
        self._test_name = test_name
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        # Configure logger with both stream and file output.
        log_dir = "results/logs"
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = f"{log_dir}/{timestamp}_{self._test_name}.log"
        logger = logging.getLogger(f"test_{self._test_name}")
        logger.setLevel(logging.INFO)
        logger.propagate = False

        # Avoid duplicate handlers when logger is instantiated repeatedly.
        if logger.handlers:
            return logger

        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
        logger.addHandler(file_handler)

        return logger

    def info(self, message: str):
        self.logger.info(message)

    def error(self, message: str):
        self.logger.error(message)

    def debug(self, message: str):
        self.logger.debug(message)

    def warning(self, message: str):
        self.logger.warning(message)
