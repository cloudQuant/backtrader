"""Tests for iteration 29 logging capabilities in backtrader.utils.log_message.

Covers the split-file layout ``log_dir/<script>/<YYYY_MM_DD>/<level>.log``:
- level-exact routing (error/warning/info) + CRITICAL into error.log
- script-name detection/sanitization/explicit override from sys.argv[0]
- lazy midnight rollover to a new date directory
- retention cleanup scoped to the script's own directory
- log_dir/log_file mutual exclusion, idempotency, default silence
- throttled error/warning storm suppression
- backend selection: spdlog preferred, stdlib fallback (auto/explicit)
- write-failure isolation (log calls never raise)

The stdlib backend group always runs. The spdlog group runs only when the
optional ``spdlog`` package is importable (skip records the probe result).
"""

import logging
import multiprocessing
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest

import backtrader as bt
from backtrader.utils import log_message

try:
    import spdlog  # noqa: F401

    HAS_SPDLOG = True
except ImportError:
    HAS_SPDLOG = False

BACKENDS = [
    "stdlib",
    pytest.param("spdlog", marks=pytest.mark.skipif(not HAS_SPDLOG, reason="spdlog unavailable")),
]


@pytest.fixture(autouse=True)
def _clean_logging():
    """Reset logging and throttle state around every test."""
    log_message.reset_logging()
    log_message._throttle_state.clear()
    log_message.set_throttle(True)
    yield
    log_message.reset_logging()
    log_message._throttle_state.clear()
    log_message.set_throttle(True)


def _configure(tmp_path, backend="stdlib", script_name="testrun", **kwargs):
    kwargs.setdefault("level", "INFO")
    kwargs.setdefault("console", False)
    return bt.configure_logging(
        log_dir=str(tmp_path / "logs"), script_name=script_name, backend=backend, **kwargs
    )


def _emit_all(logger):
    logger.info("an info line")
    logger.warning("a warning line")
    logger.error("an error line")


def _read(path):
    return path.read_text(encoding="utf-8")


def _managed_handlers(logger):
    return [
        handler for handler in logger.handlers if getattr(handler, "_backtrader_managed", False)
    ]


# ---------------------------------------------------------------------------
# layout + routing (parametrized over available backends)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", BACKENDS)
def test_log_dir_creates_daily_level_files(tmp_path, backend):
    """Configuring log_dir immediately creates today's empty level files."""
    _configure(tmp_path, backend=backend)
    today = date.today().strftime("%Y_%m_%d")
    day_dir = tmp_path / "logs" / "testrun" / today
    assert (day_dir / "error.log").is_file()
    assert (day_dir / "warning.log").is_file()
    assert (day_dir / "info.log").is_file()
    assert not (day_dir / "debug.log").exists()  # INFO level -> no debug file


@pytest.mark.parametrize("backend", BACKENDS)
def test_exact_level_routing(tmp_path, backend):
    """Level-exact routing: no cross-contamination; CRITICAL lands in error.log."""
    _configure(tmp_path, backend=backend)
    logger = bt.get_logger("routing")
    _emit_all(logger)
    logger.critical("a critical line")
    log_message.flush_all()
    today = date.today().strftime("%Y_%m_%d")
    day_dir = tmp_path / "logs" / "testrun" / today
    err, warn, info = (
        _read(day_dir / "error.log"),
        _read(day_dir / "warning.log"),
        _read(day_dir / "info.log"),
    )
    assert "an error line" in err
    assert "a critical line" in err
    assert "a warning line" in warn
    assert "an info line" in info
    assert "a warning line" not in err
    assert "a warning line" not in info
    assert "an info line" not in warn
    assert "an info line" not in err


@pytest.mark.parametrize("backend", BACKENDS)
def test_midnight_rollover_to_new_dir(tmp_path, backend, monkeypatch):
    """After the (mocked) date flips, new records land in the new date dir."""
    _configure(tmp_path, backend=backend)
    today = date.today()
    tomorrow = today + timedelta(days=1)
    logger = bt.get_logger("roll")
    logger.info("before midnight")
    monkeypatch.setattr(log_message, "_today", staticmethod(lambda: tomorrow))
    logger.info("after midnight")
    log_message.flush_all()
    d0 = tmp_path / "logs" / "testrun" / today.strftime("%Y_%m_%d")
    d1 = tmp_path / "logs" / "testrun" / tomorrow.strftime("%Y_%m_%d")
    assert "before midnight" in _read(d0 / "info.log")
    assert "after midnight" in _read(d1 / "info.log")


@pytest.mark.parametrize("backend", BACKENDS)
def test_retention_cleanup_removes_expired_dirs(tmp_path, backend):
    """Only this script's expired date dirs are removed; others untouched."""
    _configure(tmp_path, backend=backend, retention_days=30)
    logs_root = tmp_path / "logs"
    old = date.today() - timedelta(days=40)
    keep = date.today() - timedelta(days=5)
    for script, day, marker in (
        ("testrun", old, "old-self"),
        ("testrun", keep, "keep-self"),
        ("otherscript", old, "old-other"),
    ):
        d = logs_root / script / day.strftime("%Y_%m_%d")
        d.mkdir(parents=True, exist_ok=True)
        (d / "info.log").write_text(marker, encoding="utf-8")
    (logs_root / "testrun" / "not_a_date").mkdir(exist_ok=True)
    # reconfigure triggers retention cleanup again
    _configure(tmp_path, backend=backend, retention_days=30)
    assert not (logs_root / "testrun" / old.strftime("%Y_%m_%d")).exists()
    assert (logs_root / "testrun" / keep.strftime("%Y_%m_%d") / "info.log").exists()
    assert (logs_root / "otherscript" / old.strftime("%Y_%m_%d") / "info.log").exists()
    assert (logs_root / "testrun" / "not_a_date").exists()


# ---------------------------------------------------------------------------
# script-name detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", BACKENDS)
def test_script_name_from_argv0(tmp_path, backend, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["xxx/run.py"])
    _configure(tmp_path, backend=backend, script_name=None)
    today = date.today().strftime("%Y_%m_%d")
    assert (tmp_path / "logs" / "xxx_run" / today / "info.log").is_file()
    log_message.reset_logging()
    monkeypatch.setattr(sys, "argv", ["run.py"])
    _configure(tmp_path, backend=backend, script_name=None)
    assert (tmp_path / "logs" / "run" / today / "info.log").is_file()


def test_script_name_sanitize_and_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["my dir/bad*name.py"])
    assert log_message._detect_script_name() == "my_dir_bad_name"
    monkeypatch.setattr(sys, "argv", ["-c"])
    assert log_message._detect_script_name() == "backtrader"
    monkeypatch.setattr(sys, "argv", ["<stdin>"])
    assert log_message._detect_script_name() == "backtrader"
    monkeypatch.setattr(sys, "argv", [])
    assert log_message._detect_script_name() == "backtrader"


@pytest.mark.parametrize("backend", BACKENDS)
def test_script_name_explicit_override(tmp_path, backend):
    _configure(tmp_path, backend=backend, script_name="custom")
    today = date.today().strftime("%Y_%m_%d")
    assert (tmp_path / "logs" / "custom" / today / "info.log").is_file()


# ---------------------------------------------------------------------------
# contracts: exclusion, idempotency, silence, multiprocess suffix
# ---------------------------------------------------------------------------


def test_log_dir_and_log_file_mutually_exclusive(tmp_path):
    with pytest.raises(ValueError):
        bt.configure_logging(
            level="INFO",
            log_dir=str(tmp_path / "logs"),
            log_file=str(tmp_path / "run.log"),
            console=False,
        )


def test_silent_default_no_files_created(tmp_path):
    """Without configure_logging, emitting records creates nothing on disk."""
    logger = bt.get_logger("silent")
    logger.info("nothing should be written")
    logger.error("nor this")
    assert not (tmp_path / "logs").exists()
    assert not any(
        getattr(h, "_backtrader_managed", False) for h in logging.getLogger("backtrader").handlers
    )


def test_default_throttled_warning_does_not_retain_hot_path_state():
    """A NullHandler-only library logger must not throttle or retain events."""
    host_root = logging.getLogger()
    prior_level = host_root.level
    host_root.setLevel(logging.WARNING)
    try:
        logger = bt.get_logger("silent_throttle")
        for _ in range(250):
            log_message.throttled_warning(logger, "silent-key", "should remain silent")
        assert not log_message._throttle_state
    finally:
        host_root.setLevel(prior_level)


def test_configure_log_dir_idempotent(tmp_path):
    _configure(tmp_path)
    _configure(tmp_path)
    logger = logging.getLogger("backtrader")
    logger.warning("dup check")
    log_message.flush_all()
    today = date.today().strftime("%Y_%m_%d")
    warn = _read(tmp_path / "logs" / "testrun" / today / "warning.log")
    assert warn.count("dup check") == 1


def test_multiprocess_suffix(monkeypatch, tmp_path):
    """Child-process level files carry a .p<pid> suffix; parent files don't."""
    assert log_message._mp_log_suffix() == ""
    import multiprocessing as mp

    monkeypatch.setattr(mp, "parent_process", lambda: object(), raising=False)
    monkeypatch.setattr(log_message, "_MP_PID", 4242)
    assert log_message._mp_log_suffix() == ".p4242"
    monkeypatch.setattr(log_message, "_MP_PID", None)
    # _MP_PID cleared -> the (monkeypatched) child-process detection applies
    assert log_message._mp_log_suffix().startswith(".p")


# ---------------------------------------------------------------------------
# throttle
# ---------------------------------------------------------------------------


def test_throttled_error_first_then_summary(tmp_path):
    _configure(tmp_path)
    logger = bt.get_logger("throttle")
    for _ in range(250):
        log_message.throttled_error(logger, "key-a", "boom %s", "x", every=100, window=60.0)
    log_message.flush_throttle_summary()
    log_message.flush_all()
    today = date.today().strftime("%Y_%m_%d")
    err = _read(tmp_path / "logs" / "testrun" / today / "error.log")
    full = err.count("boom x")
    assert full >= 1  # first full record
    assert full < 250  # suppression active
    assert "repeated" in err.lower() or "suppressed" in err.lower()


def test_throttle_disabled_in_diagnostic_mode(tmp_path):
    _configure(tmp_path)
    logger = bt.get_logger("diag")
    log_message.set_throttle(False)
    for _ in range(5):
        log_message.throttled_error(logger, "key-b", "diag boom", every=100, window=60.0)
    log_message.flush_throttle_summary()
    log_message.flush_all()
    today = date.today().strftime("%Y_%m_%d")
    err = _read(tmp_path / "logs" / "testrun" / today / "error.log")
    assert err.count("diag boom") == 5


# ---------------------------------------------------------------------------
# backend selection & isolation
# ---------------------------------------------------------------------------


def test_backend_auto_falls_back(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(log_message, "_detect_spdlog", lambda: None)
    log_message._warned_failures.clear()
    logger = _configure(tmp_path, backend="auto")
    _configure(tmp_path, backend="auto")
    logger.info("fallback works")
    log_message.flush_all()
    today = date.today().strftime("%Y_%m_%d")
    assert "fallback works" in _read(tmp_path / "logs" / "testrun" / today / "info.log")
    assert capsys.readouterr().err.count("spdlog unavailable") == 1
    assert _managed_handlers(logger)
    assert all(
        isinstance(handler, log_message._DailyLevelFileHandler)
        for handler in _managed_handlers(logger)
    )


@pytest.mark.skipif(not HAS_SPDLOG, reason="spdlog unavailable")
def test_auto_records_active_spdlog_backend(tmp_path):
    logger = _configure(tmp_path, backend="auto")
    assert _managed_handlers(logger)
    assert all(
        isinstance(handler, log_message.SpdlogHandler) for handler in _managed_handlers(logger)
    )
    assert log_message._get_logging_config_snapshot()["backend"] == "auto"


@pytest.mark.skipif(not HAS_SPDLOG, reason="spdlog unavailable")
def test_auto_cerebro_snapshot_reprobes_backend_on_restore(tmp_path, monkeypatch):
    """A spawned/unpickled auto policy must fall back when spdlog disappears."""
    logger = _configure(tmp_path, backend="auto")
    state = bt.Cerebro(stdstats=False).__getstate__()
    assert state["_logging_config"]["backend"] == "auto"
    assert all(
        isinstance(handler, log_message.SpdlogHandler) for handler in _managed_handlers(logger)
    )

    log_message.reset_logging()
    monkeypatch.setattr(log_message, "_detect_spdlog", lambda: None)
    restored = bt.Cerebro.__new__(bt.Cerebro)
    restored.__setstate__(state)

    logger = bt.get_logger()
    assert all(
        isinstance(handler, log_message._DailyLevelFileHandler)
        for handler in _managed_handlers(logger)
    )
    bt.get_logger("restored_auto").info("auto policy restored with stdlib")
    log_message.flush_all()
    today = date.today().strftime("%Y_%m_%d")
    info = tmp_path / "logs" / "testrun" / today / "info.log"
    assert "auto policy restored with stdlib" in info.read_text(encoding="utf-8")


def test_backend_explicit_spdlog_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(log_message, "_detect_spdlog", lambda: None)
    with pytest.raises(ImportError):
        bt.configure_logging(
            level="INFO", log_dir=str(tmp_path), script_name="t", backend="spdlog", console=False
        )


def test_get_logger_always_stdlib_logger(tmp_path):
    for backend in ["stdlib"] + (["spdlog"] if HAS_SPDLOG else []):
        _configure(tmp_path, backend=backend)
        assert isinstance(bt.get_logger("x"), logging.Logger)


def test_write_failure_does_not_raise(tmp_path, monkeypatch):
    _configure(tmp_path)
    logger = bt.get_logger("failpath")

    class _BrokenStream:
        def write(self, *a):
            raise OSError("disk full")

        def flush(self):
            pass

    for h in logging.getLogger("backtrader").handlers:
        if getattr(h, "_backtrader_managed", False):
            monkeypatch.setattr(h, "stream", _BrokenStream(), raising=False)
    logger.info("this must not raise")
    logger.error("nor this")


@pytest.mark.parametrize("backend", BACKENDS)
def test_debug_file_created_at_debug_level(tmp_path, backend):
    _configure(tmp_path, backend=backend, level="DEBUG")
    today = date.today().strftime("%Y_%m_%d")
    day_dir = tmp_path / "logs" / "testrun" / today
    assert (day_dir / "debug.log").is_file()
    logger = bt.get_logger("dbg")
    logger.debug("dbg line")
    log_message.flush_all()
    assert "dbg line" in _read(day_dir / "debug.log")


@pytest.mark.parametrize("backend", BACKENDS)
def test_set_level_rebuilds_active_split_file_handlers(tmp_path, backend):
    """A root INFO -> DEBUG transition creates debug.log and updates spawn state."""
    _configure(tmp_path, backend=backend, level="INFO")
    bt.set_level("DEBUG")

    snapshot = log_message._get_logging_config_snapshot()
    assert snapshot["level"] == logging.DEBUG
    logger = bt.get_logger("runtime-level")
    logger.debug("debug after runtime level update")
    log_message.flush_all()

    today = date.today().strftime("%Y_%m_%d")
    debug_file = tmp_path / "logs" / "testrun" / today / "debug.log"
    assert debug_file.is_file()
    assert "debug after runtime level update" in _read(debug_file)


@pytest.mark.parametrize("backend", BACKENDS)
def test_named_debug_level_creates_active_split_debug_sink(tmp_path, backend):
    """A child DEBUG request creates a sink without widening other children."""
    _configure(tmp_path, backend=backend, level="INFO")
    child = bt.get_logger("only_child")
    unrelated = bt.get_logger("unrelated_for_named_debug")
    bt.set_level("DEBUG", name="only_child")
    child.debug("named debug after runtime level update")
    unrelated.debug("unrelated debug must stay disabled")
    log_message.flush_all()

    snapshot = log_message._get_logging_config_snapshot()
    assert snapshot["level"] == logging.INFO
    assert snapshot["_debug_scopes"] == ("backtrader.only_child",)
    today = date.today().strftime("%Y_%m_%d")
    debug_file = tmp_path / "logs" / "testrun" / today / "debug.log"
    assert debug_file.is_file()
    assert "named debug after runtime level update" in _read(debug_file)
    assert "unrelated debug must stay disabled" not in _read(debug_file)


def test_legacy_positional_configuration(tmp_path):
    path = tmp_path / "legacy-positional.log"
    bt.configure_logging("INFO", path, "%(message)s", None, False)
    bt.get_logger("positional").info("old signature")
    log_message.flush_all()
    assert path.read_text() == "old signature\n"


def test_default_does_not_propagate_to_host_root(capsys):
    root = logging.getLogger()
    host = logging.StreamHandler()
    root.addHandler(host)
    try:
        bt.get_logger("silent-under-host").error("must remain silent")
        assert "must remain silent" not in capsys.readouterr().err
    finally:
        root.removeHandler(host)


@pytest.mark.parametrize("backend", BACKENDS)
def test_explicit_name_cannot_escape_log_root(tmp_path, backend):
    outside = tmp_path / "outside"
    old = date.today() - timedelta(days=40)
    expired = outside / old.strftime("%Y_%m_%d")
    expired.mkdir(parents=True)
    (expired / "keep.txt").write_text("do not remove")
    _configure(tmp_path, backend=backend, script_name="../outside")
    assert (expired / "keep.txt").read_text() == "do not remove"
    assert (tmp_path / "logs" / "outside" / date.today().strftime("%Y_%m_%d")).is_dir()


def test_retention_does_not_follow_symlink_or_delete_date_file(tmp_path):
    script = tmp_path / "logs" / "testrun"
    script.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (script / "2000_01_01").symlink_to(outside, target_is_directory=True)
    (script / "2000_01_02").write_text("date-named file")
    _configure(tmp_path)
    assert (script / "2000_01_01").is_symlink()
    assert (outside / "keep.txt").read_text() == "keep"
    assert (script / "2000_01_02").read_text() == "date-named file"


def test_script_symlink_is_rejected_without_cleanup(tmp_path):
    script = tmp_path / "logs" / "testrun"
    script.parent.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    script.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        _configure(tmp_path)


@pytest.mark.parametrize("backend", BACKENDS)
def test_rollover_failure_is_isolated_and_reported_once(tmp_path, monkeypatch, capsys, backend):
    _configure(tmp_path, backend=backend)
    log_message._warned_failures.clear()
    monkeypatch.setattr(log_message, "_today", lambda: date.today() + timedelta(days=1))

    def denied(*args, **kwargs):
        raise PermissionError("password=do-not-expose")

    monkeypatch.setattr(log_message.os, "makedirs", denied)
    for _ in range(3):
        bt.get_logger("rollover-failure").error("secret event")
    stderr = capsys.readouterr().err
    assert stderr.count("log write failed") == 1
    assert "do-not-expose" not in stderr
    assert "secret event" not in stderr


def test_retention_failure_warns_once(tmp_path, monkeypatch, capsys):
    import shutil

    script = tmp_path / "logs" / "testrun"
    (script / "2000_01_01").mkdir(parents=True)

    def denied(*args, **kwargs):
        raise PermissionError("private path")

    monkeypatch.setattr(shutil, "rmtree", denied)
    log_message._warned_failures.clear()
    log_message._cleanup_retention(str(script), 30)
    log_message._cleanup_retention(str(script), 30)
    assert capsys.readouterr().err.count("log retention cleanup failed") == 1
    log_message._after_fork()
    log_message._cleanup_retention(str(script), 30)
    assert capsys.readouterr().err.count("log retention cleanup failed") == 1


def test_invalid_reconfigure_preserves_active_logging(tmp_path, monkeypatch):
    _configure(tmp_path)
    monkeypatch.setattr(log_message, "_detect_spdlog", lambda: None)
    with pytest.raises(ImportError):
        _configure(tmp_path, backend="spdlog")
    bt.get_logger("still-active").info("configuration survived")
    log_message.flush_all()
    path = tmp_path / "logs" / "testrun" / date.today().strftime("%Y_%m_%d") / "info.log"
    assert "configuration survived" in path.read_text()


def test_failed_configuration_preserves_original_error_when_pending_close_fails(
    tmp_path, monkeypatch, capsys
):
    logger = _configure(tmp_path)
    previous = list(logger.handlers)
    snapshot = log_message._get_logging_config_snapshot()
    pending = [logging.NullHandler(), logging.NullHandler()]
    closed = []
    original_error = ValueError("api_key=private-configuration-payload")
    monkeypatch.setattr(log_message, "_warned_failures", set())

    for index, handler in enumerate(pending):
        original_close = handler.close

        def fail_close(index=index, original_close=original_close):
            closed.append(index)
            original_close()
            raise OSError("password=private-cleanup-payload")

        monkeypatch.setattr(handler, "close", fail_close)

    created = []

    def create_file_handler(*args, **kwargs):
        if created:
            raise original_error
        created.append(pending[1])
        return pending[1]

    monkeypatch.setattr(log_message, "_SafeStreamHandler", lambda: pending[0])
    monkeypatch.setattr(log_message, "_DailyLevelFileHandler", create_file_handler)
    with pytest.raises(ValueError) as captured:
        _configure(tmp_path / "replacement", level="DEBUG", console=True)

    assert captured.value is original_error
    assert closed == [0, 1]
    assert logger.handlers == previous
    assert logger.level == logging.INFO
    assert log_message._get_logging_config_snapshot() == snapshot
    assert capsys.readouterr().err == (
        "backtrader: log handler close failed; further close failures are suppressed\n"
    )


def test_reconfiguration_completes_when_previous_handlers_fail_to_close(
    tmp_path, monkeypatch, capsys
):
    logger = bt.configure_logging(level="WARNING", log_file=tmp_path / "old.log")
    previous = [h for h in logger.handlers if getattr(h, "_backtrader_managed", False)]
    closed = []
    monkeypatch.setattr(log_message, "_warned_failures", set())
    for index, handler in enumerate(previous):
        original_close = handler.close

        def fail_close(index=index, original_close=original_close):
            closed.append(index)
            original_close()
            raise OSError("password=private-cleanup-payload")

        monkeypatch.setattr(handler, "close", fail_close)

    logger = _configure(tmp_path / "replacement", level="DEBUG", propagate=True)

    assert closed == list(range(len(previous)))
    assert all(handler not in logger.handlers for handler in previous)
    assert logger.level == logging.DEBUG
    assert logger.propagate is True
    assert log_message._get_logging_config_snapshot() == {
        "level": logging.DEBUG,
        "log_dir": str(tmp_path / "replacement" / "logs"),
        "script_name": "testrun",
        "backend": "stdlib",
        "retention_days": 30,
        "fmt": None,
        "datefmt": None,
        "console": False,
        "propagate": True,
    }
    bt.get_logger("reconfiguration").debug("new configuration is active")
    log_message.flush_all()
    debug_file = (
        tmp_path
        / "replacement"
        / "logs"
        / "testrun"
        / date.today().strftime("%Y_%m_%d")
        / "debug.log"
    )
    assert "new configuration is active" in debug_file.read_text()
    assert capsys.readouterr().err == (
        "backtrader: log handler close failed; further close failures are suppressed\n"
    )


def test_configure_from_threads_does_not_duplicate_handlers(tmp_path):
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: _configure(tmp_path), range(20)))
    bt.get_logger("thread-config").info("one record")
    log_message.flush_all()
    path = tmp_path / "logs" / "testrun" / date.today().strftime("%Y_%m_%d") / "info.log"
    assert path.read_text().count("one record") == 1
    assert (
        len([h for h in bt.get_logger().handlers if getattr(h, "_backtrader_managed", False)]) == 3
    )


@pytest.mark.parametrize("backend", BACKENDS)
def test_credentials_redacted_from_messages_and_tracebacks(tmp_path, backend):
    _configure(tmp_path, backend=backend)
    logger = bt.get_logger("redaction")
    logger.error("api_key=%s password='%s'", "key-value", "password with spaces")
    logger.error(
        "Authorization: Bearer %s url=https://user:%s@example.org", "bearer-value", "url-secret"
    )
    try:
        raise ValueError("passphrase=exception-secret")
    except ValueError:
        logger.exception("request failed")
    log_message.flush_all()
    path = tmp_path / "logs" / "testrun" / date.today().strftime("%Y_%m_%d") / "error.log"
    text = path.read_text()
    for secret in (
        "key-value",
        "password with spaces",
        "bearer-value",
        "url-secret",
        "exception-secret",
    ):
        assert secret not in text
    assert "ValueError" in text
    assert "[REDACTED]" in text


def test_throttle_counts_only_repeats_and_preserves_warning_level(tmp_path):
    _configure(tmp_path)
    logger = bt.get_logger("warn-throttle")
    for _ in range(3):
        log_message.throttled_warning(logger, "warn-key", "first warning", exc_info=False)
    log_message.flush_throttle_summary()
    path = tmp_path / "logs" / "testrun" / date.today().strftime("%Y_%m_%d")
    text = (path / "warning.log").read_text()
    assert "suppressed 2 repeat occurrence(s)" in text
    assert (path / "error.log").read_text() == ""


def test_throttle_reset_starts_new_run_and_disabled_level_has_no_state(tmp_path):
    _configure(tmp_path, level="CRITICAL")
    logger = bt.get_logger("throttle-reset")
    log_message.throttled_warning(logger, "unused", "unused")
    assert not log_message._throttle_state
    _configure(tmp_path)
    log_message.throttled_error(logger, "once", "first", exc_info=False)
    log_message.flush_throttle_summary()
    assert not log_message._throttle_state
    path = tmp_path / "logs" / "testrun" / date.today().strftime("%Y_%m_%d") / "error.log"
    assert "suppressed" not in path.read_text()
    log_message.throttled_error(logger, "once", "new-run", exc_info=False)
    log_message.reset_logging()
    assert not log_message._throttle_state


def _process_log_worker(snapshot):
    if snapshot is not None:
        log_message._restore_logging_config(snapshot)
    for index in range(20):
        bt.get_logger("process").info("child pid=%d index=%d", os.getpid(), index)
    log_message.flush_all()


def _scoped_debug_process_worker(snapshot):
    """Fresh spawn target for scoped DEBUG state restoration."""
    log_message._restore_logging_config(snapshot)
    bt.get_logger("scoped_worker").debug("scoped worker debug")
    bt.get_logger("unrelated_worker").debug("unrelated worker debug")
    log_message.flush_all()


@pytest.mark.parametrize("backend", BACKENDS)
@pytest.mark.parametrize("start_method", ["spawn", "fork"])
def test_real_process_log_isolation(tmp_path, backend, start_method):
    if start_method not in multiprocessing.get_all_start_methods():
        pytest.skip(f"{start_method} is unavailable")
    _configure(tmp_path, backend=backend)
    snapshot = log_message._get_logging_config_snapshot() if start_method == "spawn" else None
    context = multiprocessing.get_context(start_method)
    processes = [context.Process(target=_process_log_worker, args=(snapshot,)) for _ in range(2)]
    for process in processes:
        process.start()
    try:
        for process in processes:
            process.join(30)
            assert process.exitcode == 0
        bt.get_logger("process").info("parent record")
        log_message.flush_all()
        day_dir = tmp_path / "logs" / "testrun" / date.today().strftime("%Y_%m_%d")
        parent = (day_dir / "info.log").read_text()
        assert "child pid=" not in parent
        assert "parent record" in parent
        for process in processes:
            child = (day_dir / f"info.p{process.pid}.log").read_text()
            assert len(child.splitlines()) == 20
            assert all(f"pid={process.pid}" in line for line in child.splitlines())
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)


@pytest.mark.parametrize("backend", BACKENDS)
def test_scoped_debug_snapshot_restores_child_level_in_fresh_spawn(tmp_path, backend):
    """A scoped DEBUG logger remains enabled in a fresh optimization worker."""
    _configure(tmp_path, backend=backend, level="INFO")
    bt.set_level("DEBUG", name="scoped_worker")
    snapshot = log_message._get_logging_config_snapshot()
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_scoped_debug_process_worker, args=(snapshot,))
    process.start()
    try:
        process.join(30)
        assert process.exitcode == 0
        day_dir = tmp_path / "logs" / "testrun" / date.today().strftime("%Y_%m_%d")
        debug = (day_dir / f"debug.p{process.pid}.log").read_text(encoding="utf-8")
        assert "scoped worker debug" in debug
        assert "unrelated worker debug" not in debug
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
