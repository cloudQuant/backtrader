"""Log Message Module - Logging utilities for backtrader.

This module provides a unified logging interface using the Python
standard ``logging`` module. It supports file logging with daily
rotation and optional console output.

The ``SpdLogManager`` class is kept for backward compatibility but
now wraps ``logging.getLogger`` internally instead of requiring
the third-party ``spdlog`` package.

Classes:
    SpdLogManager: Logger factory (stdlib ``logging`` under the hood).

Example:
    >>> log_manager = SpdLogManager(file_name="mylog.log")
    >>> logger = log_manager.create_logger()
    >>> logger.info("Strategy started")
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler


class SpdLogManager:
    """Logger factory using the Python standard ``logging`` module.

    Creates loggers with daily file rotation and optional console output.
    API is kept compatible with the previous spdlog-based implementation.

    Attributes:
        file_name: Name of the log file.
        logger_name: Name for the logger.
        rotation_hour: Hour of day for log rotation (0-23).
        rotation_minute: Minute of hour for log rotation (0-59).
        print_info: Whether to also print to console.
    """

    _LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    def __init__(
        self,
        file_name="log_strategy_info.log",
        logger_name="hello",
        rotation_hour=0,
        rotation_minute=0,
        print_info=False,
    ):
        """Initialize the SpdLogManager.

        Args:
            file_name: Name of the output log file.
            logger_name: Name for the logger.
            rotation_hour: Hour (0-23) to rotate log files daily.
            rotation_minute: Minute (0-59) to rotate log files.
            print_info: Whether to also output to console.
        """
        self.file_name = file_name
        self.logger_name = logger_name
        self.rotation_hour = rotation_hour
        self.rotation_minute = rotation_minute
        self.print_info = print_info

    def create_logger(self):
        """Create and return a configured ``logging.Logger`` instance.

        Returns:
            logging.Logger: Logger with file handler (daily rotation)
            and optionally a console handler.
        """
        logger = logging.getLogger(f"backtrader.{self.logger_name}")

        # Avoid adding duplicate handlers on repeated calls
        if logger.handlers:
            return logger

        logger.setLevel(logging.DEBUG)
        formatter = logging.Formatter(self._LOG_FORMAT)

        # File handler with daily rotation
        if self.file_name:
            # Ensure the log directory exists
            log_dir = os.path.dirname(self.file_name)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)

            at_time = None
            if self.rotation_hour or self.rotation_minute:
                from datetime import time
                at_time = time(self.rotation_hour, self.rotation_minute)

            fh = TimedRotatingFileHandler(
                self.file_name, when="midnight", interval=1,
                backupCount=30, encoding="utf-8", atTime=at_time,
            )
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(formatter)
            logger.addHandler(fh)

        # Console handler
        if self.print_info:
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            ch.setFormatter(formatter)
            logger.addHandler(ch)

        return logger
