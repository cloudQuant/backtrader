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

import atexit
import functools
import logging
import os
import re
import sys
import threading
import time
from datetime import date, timedelta
from logging.handlers import TimedRotatingFileHandler
from typing import List

# Root namespace for every backtrader logger. ``get_logger(__name__)`` from
# inside the package already yields names like "backtrader.xxx"; a single
# ``configure_logging`` call on this root therefore controls them all.
ROOT_LOGGER_NAME = "backtrader"

DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s"
DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

# Marker so configure_logging can recognize and replace only the handlers it
# installed, never the ones a host application may have attached.
_BT_HANDLER_FLAG = "_backtrader_managed"
_CONFIG_LOCK = threading.RLock()
_THROTTLE_LOCK = threading.RLock()
_PROCESS_PID = os.getpid()
_logging_config = None
_warned_failures = set()

# Standard library pattern for libraries: install a NullHandler at import so
# backtrader stays silent (and warning-free) until the user opts in.
_root_logger = logging.getLogger(ROOT_LOGGER_NAME)
_root_logger.propagate = False
if not any(isinstance(h, logging.NullHandler) for h in _root_logger.handlers):
    _root_logger.addHandler(logging.NullHandler())


def _serialized_configuration(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        with _CONFIG_LOCK:
            return function(*args, **kwargs)

    return wrapped


def _warn_once(key, message):
    """Report a logging failure without exposing record or exception payloads."""
    if key in _warned_failures:
        return
    _warned_failures.add(key)
    try:
        print("backtrader: " + message, file=sys.stderr)
    except Exception:  # nosec B110
        # No remaining safe diagnostic sink.
        pass


_SECRET_VALUE = re.compile(
    r"(?i)(\b(?:password|passwd|passphrase|api[_-]?key|api[_-]?secret|secret|"
    r"access[_-]?token|refresh[_-]?token|authorization)\b[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)"
)
_BEARER_VALUE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
_URL_PASSWORD = re.compile(r"(://[^\s/:@]+:)[^\s/@]+(@)")


class _RedactingFormatter(logging.Formatter):
    """Redact common credential fields in messages and rendered tracebacks."""

    def format(self, record):
        rendered = super().format(record)
        rendered = _BEARER_VALUE.sub(r"\1 [REDACTED]", rendered)
        rendered = _SECRET_VALUE.sub(r"\1[REDACTED]", rendered)
        return _URL_PASSWORD.sub(r"\1[REDACTED]\2", rendered)


class _NonFatalHandlerMixin:
    _closed: bool

    def handleError(self, record):
        _warn_once("write", "log write failed; further logging failures are suppressed")


class _SafeStreamHandler(_NonFatalHandlerMixin, logging.StreamHandler):
    pass


def _get_logging_config_snapshot():
    """Return only opt-in split-file configuration, never live handlers."""
    with _CONFIG_LOCK:
        return None if _logging_config is None else dict(_logging_config)


def _restore_logging_config(snapshot):
    """Restore configured split logging in optimization workers; None is inert."""
    if snapshot is None:
        return
    with _CONFIG_LOCK:
        managed = [
            handler
            for handler in _root_logger.handlers
            if getattr(handler, _BT_HANDLER_FLAG, False)
        ]
        if (
            snapshot == _logging_config
            and managed
            and all(
                getattr(handler, "_owner_pid", os.getpid()) == os.getpid() for handler in managed
            )
        ):
            return
        configure_logging(**snapshot)
        # A scoped DEBUG sink alone cannot enable a fresh worker's child
        # logger: its default NOTSET level would inherit the root INFO level.
        # Restore the explicit levels that created these scopes with the same
        # config snapshot used for the split handlers.
        for scope in snapshot.get("_debug_scopes", ()):
            get_logger(scope).setLevel(logging.DEBUG)


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


def _is_output_enabled_for(level, logger=None):
    """Return whether an opt-in output can receive ``level`` from ``logger``.

    A library logger at ``NOTSET`` inherits the host root's effective level
    even when backtrader has only its default :class:`logging.NullHandler`.
    Lifecycle diagnostics must not mistake that host setting for an explicit
    backtrader logging opt-in because evaluating a diagnostic may call a live
    broker or feed accessor.  A non-null handler on the backtrader root is
    either installed by :func:`configure_logging` or deliberately attached by
    the host, so it is the required output boundary.
    """
    level_int = _level_to_int(level)
    with _CONFIG_LOCK:
        current = logger or logging.getLogger(ROOT_LOGGER_NAME)
        if not current.isEnabledFor(level_int):
            return False
        while current is not None:
            if any(not isinstance(handler, logging.NullHandler) for handler in current.handlers):
                return True
            if not current.propagate:
                return False
            current = current.parent
        return False


def _level_to_int(level):
    """Coerce a level given as int or name into the logging int constant."""
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        resolved = logging.getLevelName(level.upper())
        if isinstance(resolved, int):
            return resolved
    raise ValueError(f"invalid logging level: {level!r}")


def _normalize_debug_scopes(scopes):
    """Normalize internal split-file DEBUG logger prefixes."""
    if scopes is None:
        return ()
    if isinstance(scopes, str):
        raise ValueError("_debug_scopes must be an iterable of logger names")
    try:
        candidates = tuple(scopes)
    except TypeError as exc:
        raise ValueError("_debug_scopes must be an iterable of logger names") from exc

    normalized = []
    for scope in candidates:
        if not isinstance(scope, str) or not scope:
            raise ValueError("_debug_scopes entries must be non-empty logger names")
        normalized.append(get_logger(scope).name)
    return tuple(sorted(set(normalized)))


def _remove_managed_handlers(logger):
    """Remove only handlers previously installed by configure_logging()."""
    for handler in list(logger.handlers):
        if getattr(handler, _BT_HANDLER_FLAG, False):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # nosec B110
                # Handler may already be closed; closing is best-effort cleanup
                # during logging reconfiguration. Logging here could recurse
                # into the handler being torn down, so stay silent.
                pass


def _close_handler_safely(handler):
    """Keep cleanup failures from replacing configuration errors or state."""
    try:
        handler.close()
    except Exception:
        _warn_once(
            "handler_close",
            "log handler close failed; further close failures are suppressed",
        )


@_serialized_configuration
def configure_logging(
    level="INFO",
    log_file=None,
    fmt=None,
    datefmt=None,
    console=True,
    max_bytes=10 * 1024 * 1024,
    backup_count=5,
    propagate=False,
    *,
    log_dir=None,
    script_name=None,
    backend="auto",
    retention_days=30,
    _debug_scopes=(),
):
    """Configure the ``backtrader`` logger hierarchy (opt-in).

    Backtrader emits nothing until you call this. It configures only the
    ``backtrader`` logger (never the root logger), so it will not clobber a
    host application's logging. Calling it again replaces backtrader-managed
    handlers (idempotent) while leaving host-added handlers untouched.

    Args:
        level: Level as int (``logging.INFO``) or name (``"INFO"``).
        log_file: If given, also write to this single file via a
            :class:`~logging.handlers.RotatingFileHandler`. Mutually exclusive
            with ``log_dir``.
        log_dir: If given, enable the iteration-29 split-file layout
            ``log_dir/<script>/<YYYY_MM_DD>/{error,warning,info}.log``
            (plus ``debug.log`` when ``level=DEBUG``). ``<script>`` comes from
            ``script_name`` or auto-detection of ``sys.argv[0]``.
        script_name: Directory name under ``log_dir``. ``None`` auto-detects
            from ``sys.argv[0]`` (``xxx/run.py`` -> ``xxx_run``).
        backend: ``"auto"`` (default; prefer the optional ``spdlog`` package,
            fall back to stdlib with one diagnostic), ``"spdlog"`` (raise ``ImportError``
            if unavailable) or ``"stdlib"``.
        retention_days: Date directories older than this many days under the
            script's own directory are removed at configure/rollover time.
        fmt: Message format. Defaults to :data:`DEFAULT_FORMAT`.
        datefmt: Date format. Defaults to :data:`DEFAULT_DATEFMT`.
        console: Whether to add a stderr ``StreamHandler``.
        max_bytes: Rotating file handler size before rollover (``log_file``).
        backup_count: Number of rotated backups to keep (``log_file``).
        propagate: Whether the backtrader logger propagates to the root
            logger (default ``False``).

    Returns:
        logging.Logger: The configured ``backtrader`` root logger.
    """
    from logging.handlers import RotatingFileHandler

    global _logging_config
    if log_dir is not None and log_file is not None:
        raise ValueError("log_dir and log_file are mutually exclusive; pass only one")
    if backend not in {"auto", "stdlib", "spdlog"}:
        raise ValueError(f"invalid backend: {backend!r}")
    if retention_days is not None and (
        isinstance(retention_days, bool)
        or not isinstance(retention_days, int)
        or retention_days < 0
    ):
        raise ValueError("retention_days must be a non-negative integer or None")
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    level_int = _level_to_int(level)
    debug_scopes = _normalize_debug_scopes(_debug_scopes)
    formatter = _RedactingFormatter(fmt or DEFAULT_FORMAT, datefmt or DEFAULT_DATEFMT)
    spdlog_mod = None
    snapshot = None
    if log_dir is not None:
        log_dir = os.path.abspath(os.fspath(log_dir))
        script = _sanitize_script_name(script_name) if script_name else _detect_script_name()
        script_dir = os.path.join(log_dir, script)
        if os.path.islink(script_dir):
            raise ValueError("script log directory must not be a symbolic link")
        if backend != "stdlib":
            spdlog_mod = _detect_spdlog()
            if spdlog_mod is None and backend == "spdlog":
                raise ImportError("backend='spdlog' requested but the spdlog package is not usable")
            if spdlog_mod is None:
                _warn_once("backend", "spdlog unavailable; using stdlib logging")
        snapshot = {
            "level": level_int,
            "log_dir": log_dir,
            "script_name": script,
            # Persist the requested policy, not this process's selected
            # implementation.  ``auto`` must re-probe in a spawned worker
            # where spdlog may be unavailable.
            "backend": backend,
            "retention_days": retention_days,
            "fmt": fmt,
            "datefmt": datefmt,
            "console": console,
            "propagate": propagate,
        }
        if debug_scopes:
            snapshot["_debug_scopes"] = debug_scopes

    # Build first: invalid configuration must not destroy a working logger.
    pending: List[logging.Handler] = []
    handler: logging.Handler
    try:
        if console:
            pending.append(_SafeStreamHandler())
        if log_file is not None:
            os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
            pending.append(
                RotatingFileHandler(
                    log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
                )
            )
        if log_dir is not None:
            debug_scope_filter = (
                _NamePrefixFilter(debug_scopes)
                if debug_scopes and level_int > logging.DEBUG
                else None
            )
            matrix = (
                ("error", logging.ERROR, None),
                ("warning", logging.WARNING, _ExactLevelFilter(logging.WARNING)),
                ("info", logging.INFO, _ExactLevelFilter(logging.INFO)),
                ("debug", logging.DEBUG, _ExactLevelFilter(logging.DEBUG)),
            )
            for level_name, handler_level, exact in matrix:
                if level_name == "debug" and level_int > logging.DEBUG and not debug_scopes:
                    continue
                if spdlog_mod is not None:
                    handler = SpdlogHandler(
                        spdlog_mod, script_dir, level_name, handler_level, exact, retention_days
                    )
                else:
                    handler = _DailyLevelFileHandler(
                        script_dir, level_name, handler_level, exact, retention_days
                    )
                if level_name == "debug" and debug_scope_filter is not None:
                    handler.addFilter(debug_scope_filter)
                pending.append(handler)
        for handler in pending:
            handler.setFormatter(formatter)
            setattr(handler, _BT_HANDLER_FLAG, True)
    except Exception:
        for handler in pending:
            _close_handler_safely(handler)
        raise

    previous = [h for h in logger.handlers if getattr(h, _BT_HANDLER_FLAG, False)]
    logger.handlers = [h for h in logger.handlers if h not in previous] + pending
    for handler in previous:
        _close_handler_safely(handler)
    logger.setLevel(level_int)
    logger.propagate = propagate
    _logging_config = snapshot
    if log_dir is not None:
        _cleanup_retention(script_dir, retention_days)
    return logger


@_serialized_configuration
def set_level(level, name=None):
    """Set the level of a backtrader logger at runtime.

    Args:
        level: Level as int or name.
        name: Sub-logger name (``__name__``-style). ``None`` targets the root.
            A root-level update with active split-file logging atomically
            rebuilds its handler matrix, so a DEBUG transition creates
            ``debug.log`` and is inherited by optimization workers. A named
            DEBUG update creates a DEBUG sink restricted to that logger's
            hierarchy, leaving unrelated loggers at the configured root level.
    """
    level_int = _level_to_int(level)
    if name is None and _logging_config is not None:
        snapshot = dict(_logging_config)
        snapshot["level"] = level_int
        configure_logging(**snapshot)
        return
    target = get_logger(name)
    if name is not None and _logging_config is not None:
        old_scopes = set(_logging_config.get("_debug_scopes", ()))
        scopes = set(old_scopes)
        if level_int == logging.DEBUG:
            scopes.add(target.name)
        else:
            scopes.discard(target.name)
        if scopes != old_scopes:
            # Split-file routing has no DEBUG sink above INFO. Register a
            # prefix-filtered sink for this child instead of widening the
            # entire backtrader hierarchy to DEBUG.
            snapshot = dict(_logging_config)
            if scopes:
                snapshot["_debug_scopes"] = tuple(sorted(scopes))
            else:
                snapshot.pop("_debug_scopes", None)
            configure_logging(**snapshot)
    target.setLevel(level_int)


@_serialized_configuration
def reset_logging():
    """Remove backtrader-managed handlers and restore the default NullHandler.

    Mainly useful in tests to return to the pristine, no-output state. Also
    flushes and releases any spdlog-side resources held by managed handlers.
    """
    global _logging_config
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    with _THROTTLE_LOCK:
        _throttle_state.clear()
    _remove_managed_handlers(logger)
    logger.setLevel(logging.NOTSET)
    logger.propagate = False
    _logging_config = None
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


# ===========================================================================
# Iteration 29: split-file logging (log_dir/<script>/<YYYY_MM_DD>/<level>.log)
# with level-exact routing, daily rollover, retention cleanup, optional
# spdlog write backend (stdlib fallback) and throttled storm suppression.
# See docs/_internal/opts/requirements/迭代29-日志体系完善/.
# ===========================================================================

_DATE_DIR_RE = re.compile(r"^\d{4}_\d{2}_\d{2}$")

# Test hook: override to freeze the "current day" (rollover tests monkeypatch
# this instead of relying on the real clock crossing midnight).
_today = date.today

# Test hook for the multiprocess pid; None means "detect from environment".
_MP_PID = None


def _mp_log_suffix():
    """File suffix isolating child-process logs: ``.p<pid>`` or ``""``.

    Under cerebro optimize (maxcpus>1) each spawned worker opens its own
    level files; the main process keeps the unsuffixed names.
    """
    global _MP_PID
    if _MP_PID is not None:
        return f".p{_MP_PID}"
    if os.getpid() != _PROCESS_PID:
        return f".p{os.getpid()}"
    try:
        import multiprocessing

        if multiprocessing.parent_process() is not None:
            return f".p{os.getpid()}"
    except Exception:  # nosec B110
        # Process detection must not break logging teardown.
        pass
    return ""


def _detect_script_name(default="backtrader"):
    """Derive the log directory name from ``sys.argv[0]``.

    ``xxx/run.py`` -> ``xxx_run`` (path separators become underscores so the
    relative-path structure survives as a flat directory name). Interactive
    interpreters, ``-c`` and ``<stdin>`` fall back to ``default``.
    """
    argv0 = sys.argv[0] if sys.argv and sys.argv[0] else ""
    if not argv0 or argv0 in ("<stdin>", "-c") or argv0.startswith("<"):
        return default
    return _sanitize_script_name(os.path.splitext(argv0.replace("\\", "/"))[0], default)


def _sanitize_script_name(name, default="backtrader"):
    """Keep both inferred and explicit names in one safe path component."""
    name = str(name).replace("\\", "/").strip("./")
    name = re.sub(r"[^A-Za-z0-9_.\-]", "_", name)
    return name or default


def _day_directory(script_dir, day):
    day_dir = os.path.join(script_dir, day.strftime("%Y_%m_%d"))
    if os.path.islink(script_dir) or os.path.islink(day_dir):
        raise OSError("symbolic links are not allowed in split log directories")
    os.makedirs(day_dir, exist_ok=True)
    return day_dir


def _cleanup_retention(script_dir, retention_days):
    """Delete this script's date dirs older than ``retention_days`` days.

    Scoped to ``script_dir`` only: other scripts' directories and non-date
    entries are never touched. Failures warn once on stderr and never raise
    (logging teardown must not break a running backtest).
    """
    if retention_days is None or os.path.islink(script_dir) or not os.path.isdir(script_dir):
        return
    try:
        cutoff = _today() - timedelta(days=int(retention_days))
        for entry in os.listdir(script_dir):
            if not _DATE_DIR_RE.match(entry):
                continue
            try:
                day = date(int(entry[0:4]), int(entry[5:7]), int(entry[8:10]))
            except ValueError:
                continue
            if day < cutoff:
                import shutil

                path = os.path.join(script_dir, entry)
                if os.path.islink(path) or not os.path.isdir(path):
                    continue
                shutil.rmtree(path)
    except Exception:  # cleanup must never affect trading
        _warn_once("retention", "log retention cleanup failed")


class _ExactLevelFilter(logging.Filter):
    """Pass only records whose level *equals* the configured level."""

    def __init__(self, level):
        super().__init__()
        self.level = level

    def filter(self, record):
        return record.levelno == self.level


class _NamePrefixFilter(logging.Filter):
    """Pass records from explicitly enabled logger subtrees."""

    def __init__(self, prefixes):
        super().__init__()
        self.prefixes = tuple(prefixes)

    def filter(self, record):
        return any(
            record.name == prefix or record.name.startswith(prefix + ".")
            for prefix in self.prefixes
        )


class _DailyLevelFileHandler(_NonFatalHandlerMixin, logging.FileHandler):
    """Stdlib-backend file handler writing ``<script_dir>/<date>/<level>.log``.

    Lazily rolls to a new date directory on the first record emitted after
    midnight; runs retention cleanup on each rollover. ``os.path.dirname``
    is empty only for relative single-component paths, which never happens
    here because the constructor always joins ``script_dir``.
    """

    def __init__(self, script_dir, level_name, handler_level, exact_filter, retention_days):
        self._script_dir = script_dir
        self._level_name = level_name
        self._retention_days = retention_days
        self._owner_pid = os.getpid()
        self._cur_date = _today()
        path = self._path_for(self._cur_date)
        super().__init__(path, mode="a", encoding="utf-8", delay=False)
        self.setLevel(handler_level)
        if exact_filter is not None:
            self.addFilter(exact_filter)

    def _path_for(self, day):
        day_dir = _day_directory(self._script_dir, day)
        path = os.path.join(day_dir, f"{self._level_name}{_mp_log_suffix()}.log")
        if os.path.islink(path):
            raise OSError("symbolic links are not allowed for split log files")
        return path

    def emit(self, record):
        if self._closed:
            return
        try:
            today = _today()
            if today != self._cur_date or self._owner_pid != os.getpid():
                self._rotate(today)
            super().emit(record)
        except Exception:
            self.handleError(record)

    def _rotate(self, today):
        path = os.path.abspath(self._path_for(today))
        new_stream = open(path, "a", encoding="utf-8")
        old_stream = self.stream
        self.stream = new_stream
        self.baseFilename = path
        self._cur_date = today
        self._owner_pid = os.getpid()
        if old_stream is not None:
            old_stream.close()
        _cleanup_retention(self._script_dir, self._retention_days)


def _detect_spdlog():
    """Return the ``spdlog`` module if usable, else ``None``.

    Probe contract (frozen in D29-13): import succeeds, required symbols
    exist, and a smoke write to a temp file works. Never raises.
    """
    try:
        import spdlog

        if not all(hasattr(spdlog, name) for name in ("FileLogger", "LogLevel", "drop")):
            return None
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            probe_name = f"bt_backend_probe.{os.getpid()}.{time.monotonic_ns()}"
            try:
                probe = spdlog.FileLogger(probe_name, os.path.join(tmp, "probe.log"), truncate=True)
                probe.set_pattern("%v")
                probe.set_level(spdlog.LogLevel.TRACE)
                probe.flush_on(spdlog.LogLevel.WARN)
                probe.info("probe")
                probe.flush()
                with open(os.path.join(tmp, "probe.log"), encoding="utf-8") as stream:
                    if "probe" not in stream.read():
                        return None
            finally:
                spdlog.drop(probe_name)
        return spdlog
    except Exception:
        return None


class SpdlogHandler(_NonFatalHandlerMixin, logging.Handler):
    """spdlog-backend handler mirroring :class:`_DailyLevelFileHandler`.

    The framework layer owns the layout: the Python formatter renders the
    full line and spdlog writes it with pattern ``%v`` (message only), so
    line format matches the stdlib backend. Date rollover drops and reopens
    the underlying spdlog logger on the new path.
    """

    _METHODS = (
        (logging.CRITICAL, "critical"),
        (logging.ERROR, "error"),
        (logging.WARNING, "warn"),
        (logging.INFO, "info"),
    )

    def __init__(
        self, spdlog_mod, script_dir, level_name, handler_level, exact_filter, retention_days
    ):
        super().__init__(level=handler_level)
        self._mod = spdlog_mod
        self._script_dir = script_dir
        self._level_name = level_name
        self._retention_days = retention_days
        self._owner_pid = os.getpid()
        self._cur_date = _today()
        self._unique = f"bt.{level_name}.{os.getpid()}.{id(self):x}"
        if exact_filter is not None:
            self.addFilter(exact_filter)
        self._path = self._path_for(self._cur_date)
        self._logger = self._open_logger(self._path)

    def _path_for(self, day):
        day_dir = _day_directory(self._script_dir, day)
        path = os.path.join(day_dir, f"{self._level_name}{_mp_log_suffix()}.log")
        if os.path.islink(path):
            raise OSError("symbolic links are not allowed for split log files")
        return path

    def _open_logger(self, path):
        open(path, "a", encoding="utf-8").close()  # config-time file creation
        lg = self._mod.FileLogger(self._unique, path, truncate=False)
        lg.set_pattern("%v")  # the Python formatter already rendered the line
        lg.set_level(self._mod.LogLevel.TRACE)  # filtering stays on our side
        lg.flush_on(self._mod.LogLevel.WARN)
        return lg

    def _method_for(self, levelno):
        for lvl, name in self._METHODS:
            if levelno >= lvl:
                return name
        return "debug"

    def emit(self, record):
        if self._closed:
            return
        try:
            today = _today()
            if today != self._cur_date or self._owner_pid != os.getpid():
                self._rotate(today)
            line = self.format(record)
            getattr(self._logger, self._method_for(record.levelno))(line)
        except Exception:
            self.handleError(record)

    def _rotate(self, today):
        path = self._path_for(today)
        if self._owner_pid == os.getpid():
            self._logger.flush()
            self._mod.drop(self._unique)
        self._unique = f"bt.{self._level_name}.{os.getpid()}.{id(self):x}"
        self._logger = self._open_logger(path)
        self._path = path
        self._cur_date = today
        self._owner_pid = os.getpid()
        _cleanup_retention(self._script_dir, self._retention_days)

    def flush(self):
        self.acquire()
        try:
            if getattr(self, "_owner_pid", None) != os.getpid() or self._closed:
                return
            try:
                self._logger.flush()
            except Exception:  # nosec B110
                # Best-effort cleanup only.
                pass
        finally:
            self.release()

    def close(self):
        self.acquire()
        try:
            if getattr(self, "_owner_pid", None) == os.getpid() and not self._closed:
                try:
                    self._logger.flush()
                    self._mod.drop(self._unique)
                except Exception:  # nosec B110
                    # Best-effort cleanup only.
                    pass
            super().close()
        finally:
            self.release()


def flush_all():
    """Flush every managed handler (use before reading log files in tests)."""
    for handler in tuple(logging.getLogger(ROOT_LOGGER_NAME).handlers):
        if not getattr(handler, _BT_HANDLER_FLAG, False):
            continue
        try:
            handler.flush()
        except Exception:  # nosec B110
            # Best-effort cleanup only.
            pass


# ---------------------------------------------------------------------------
# Throttled storm suppression (FR29-05): first occurrence logs in full, then
# repeats are counted and only summarized every ``every`` events or ``window``
# seconds; a final summary is emitted at interpreter exit.
# ---------------------------------------------------------------------------

_throttle_state: dict = {}
_throttle_enabled = True


def set_throttle(enabled):
    """Enable/disable storm suppression (diagnostic mode: disable)."""
    global _throttle_enabled
    _throttle_enabled = enabled


def _throttled(func, logger, key, msg, *args, every=100, window=60.0, exc_info=True):
    level = logging.WARNING if func is logging.Logger.warning else logging.ERROR
    if not _is_output_enabled_for(level, logger=logger):
        return
    if not _throttle_enabled:
        func(logger, msg, *args, exc_info=exc_info)
        return
    exception = exc_info if isinstance(exc_info, tuple) else sys.exc_info() if exc_info else None
    exception_type = exception[0] if exception else None
    state_key = (logger.name, key, level, exception_type)
    now = time.monotonic()
    first = False
    summary = None
    with _THROTTLE_LOCK:
        state = _throttle_state.get(state_key)
        if state is None:
            _throttle_state[state_key] = {"count": 0, "total": 1, "last": now}
            first = True
        else:
            state["count"] += 1
            state["total"] += 1
            if state["count"] >= every or (now - state["last"]) >= window:
                summary = (state["count"], state["total"])
                state["count"] = 0
                state["last"] = now
    if first:
        func(logger, msg, *args, exc_info=exc_info)
    elif summary is not None:
        func(
            logger,
            "previous %s repeated %d more times (key=%s, total=%d)",
            msg.splitlines()[0] if msg else msg,
            summary[0],
            key,
            summary[1],
        )


def throttled_error(logger, key, msg, *args, every=100, window=60.0, exc_info=True):
    """logger.error with storm suppression: first full, repeats summarized."""
    _throttled(
        logging.Logger.error, logger, key, msg, *args, every=every, window=window, exc_info=exc_info
    )


def throttled_warning(logger, key, msg, *args, every=100, window=60.0, exc_info=True):
    """logger.warning with storm suppression (same contract as error)."""
    _throttled(
        logging.Logger.warning,
        logger,
        key,
        msg,
        *args,
        every=every,
        window=window,
        exc_info=exc_info,
    )


def flush_throttle_summary():
    """Emit one summary line per key with unreported repeats (atexit hook)."""
    with _THROTTLE_LOCK:
        pending = list(_throttle_state.items())
        _throttle_state.clear()
    for (logger_name, key, level, _exception_type), state in pending:
        if state["count"] > 0:
            logging.getLogger(logger_name).log(
                level,
                "suppressed %d repeat occurrence(s) of key=%s (total=%d)",
                state["count"],
                key,
                state["total"],
            )
    flush_all()


def _after_fork():
    """Do not inherit another thread's configuration/throttle locks or counts."""
    global _CONFIG_LOCK, _THROTTLE_LOCK
    _CONFIG_LOCK = threading.RLock()
    _THROTTLE_LOCK = threading.RLock()
    _throttle_state.clear()
    _warned_failures.clear()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)


atexit.register(flush_throttle_summary)
