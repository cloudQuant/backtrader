"""Log Message Module - Logging utilities for backtrader.

This module is the **single logging entry point** for the whole framework.
It builds on Python's standard ``logging`` under the hood (no third-party
``spdlog`` dependency) but framework and user code should go through the
helpers exposed here rather than importing ``logging`` directly:

- :func:`get_logger` — get a logger under the ``backtrader`` namespace.
- :func:`configure_logging` — opt-in handler/level setup (stderr + optional
  rotating file). Until this is called, backtrader emits nothing (a
  ``NullHandler`` is installed on the root ``backtrader`` logger).
- :func:`set_level` / :func:`reset_logging` — runtime level control / test
  reset.
- :class:`SpdLogManager` — legacy per-file logger factory (daily rotation),
  kept for backward compatibility and reused internally by the strategy
  TradeLogger path.

See ``docs/LOGGING_GUIDELINES.md`` for level-usage conventions.

Example:
    >>> from backtrader.utils.log_message import get_logger, configure_logging
    >>> configure_logging(level="INFO", log_file="run.log")
    >>> logger = get_logger(__name__)
    >>> logger.info("Strategy started")

    # Legacy factory (still supported):
    >>> log_manager = SpdLogManager(file_name="mylog.log")
    >>> logger = log_manager.create_logger()
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler

# Root namespace for every backtrader logger. ``get_logger(__name__)`` from
# inside the package already yields names like "backtrader.xxx"; a single
# ``configure_logging`` call on this root therefore controls them all.
ROOT_LOGGER_NAME = "backtrader"

DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s"
DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

# Marker so configure_logging can recognize and replace only the handlers it
# installed, never the ones a host application may have attached.
_BT_HANDLER_FLAG = "_backtrader_managed"

# Standard library pattern for libraries: install a NullHandler at import so
# backtrader stays silent (and warning-free) until the user opts in.
_root_logger = logging.getLogger(ROOT_LOGGER_NAME)
if not any(isinstance(h, logging.NullHandler) for h in _root_logger.handlers):
    _root_logger.addHandler(logging.NullHandler())


def get_logger(name=None):
    """Return a logger under the ``backtrader`` namespace.

    Args:
        name: Usually ``__name__`` of the calling module. If it already starts
            with ``"backtrader"`` it is used as-is; otherwise it is nested
            under the ``backtrader`` root (e.g. ``"mystuff"`` ->
            ``"backtrader.mystuff"``). ``None`` returns the root logger.

    Returns:
        logging.Logger: A logger in the backtrader hierarchy.
    """
    if not name:
        return logging.getLogger(ROOT_LOGGER_NAME)
    if name == ROOT_LOGGER_NAME or name.startswith(ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def _level_to_int(level):
    """Coerce a level given as int or name into the logging int constant."""
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        resolved = logging.getLevelName(level.upper())
        if isinstance(resolved, int):
            return resolved
    raise ValueError(f"invalid logging level: {level!r}")


def _remove_managed_handlers(logger):
    """Remove only handlers previously installed by configure_logging()."""
    for handler in list(logger.handlers):
        if getattr(handler, _BT_HANDLER_FLAG, False):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                # Handler may already be closed; closing is best-effort cleanup.
                pass


def configure_logging(
    level="INFO",
    log_file=None,
    fmt=None,
    datefmt=None,
    console=True,
    max_bytes=10 * 1024 * 1024,
    backup_count=5,
    propagate=False,
):
    """Configure the ``backtrader`` logger hierarchy (opt-in).

    Backtrader emits nothing until you call this. It configures only the
    ``backtrader`` logger (never the root logger), so it will not clobber a
    host application's logging. Calling it again replaces backtrader-managed
    handlers (idempotent) while leaving host-added handlers untouched.

    Args:
        level: Level as int (``logging.INFO``) or name (``"INFO"``).
        log_file: If given, also write to this file via a
            :class:`~logging.handlers.RotatingFileHandler`.
        fmt: Message format. Defaults to :data:`DEFAULT_FORMAT`.
        datefmt: Date format. Defaults to :data:`DEFAULT_DATEFMT`.
        console: Whether to add a stderr ``StreamHandler``.
        max_bytes: Rotating file handler size before rollover.
        backup_count: Number of rotated backups to keep.
        propagate: Whether the backtrader logger propagates to the root
            logger (default ``False``).

    Returns:
        logging.Logger: The configured ``backtrader`` root logger.
    """
    from logging.handlers import RotatingFileHandler

    logger = logging.getLogger(ROOT_LOGGER_NAME)
    level_int = _level_to_int(level)
    formatter = logging.Formatter(fmt or DEFAULT_FORMAT, datefmt or DEFAULT_DATEFMT)

    _remove_managed_handlers(logger)

    if console:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        setattr(stream_handler, _BT_HANDLER_FLAG, True)
        logger.addHandler(stream_handler)

    if log_file:
        log_dir = os.path.dirname(os.path.abspath(log_file))
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        setattr(file_handler, _BT_HANDLER_FLAG, True)
        logger.addHandler(file_handler)

    logger.setLevel(level_int)
    logger.propagate = propagate
    return logger


def set_level(level, name=None):
    """Set the level of a backtrader logger at runtime.

    Args:
        level: Level as int or name.
        name: Sub-logger name (``__name__``-style). ``None`` targets the root.
    """
    get_logger(name).setLevel(_level_to_int(level))


def reset_logging():
    """Remove backtrader-managed handlers and restore the default NullHandler.

    Mainly useful in tests to return to the pristine, no-output state.
    """
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    _remove_managed_handlers(logger)
    logger.setLevel(logging.NOTSET)
    logger.propagate = True
    if not any(isinstance(h, logging.NullHandler) for h in logger.handlers):
        logger.addHandler(logging.NullHandler())


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
                self.file_name,
                when="midnight",
                interval=1,
                backupCount=30,
                encoding="utf-8",
                atTime=at_time,
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
