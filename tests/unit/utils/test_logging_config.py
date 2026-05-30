"""Tests for the unified logging entry points in backtrader.utils.log_message.

These cover the Sprint 2 logging foundation:
- get_logger() namespacing
- default silence (NullHandler, no output until configured)
- configure_logging() handler/level setup + idempotency + host-handler safety
- set_level() runtime control
- reset_logging() restores the pristine state
"""

import logging

import pytest

import backtrader as bt
from backtrader.utils import log_message


@pytest.fixture(autouse=True)
def _clean_logging():
    """Ensure each test starts and ends from the pristine NullHandler state."""
    log_message.reset_logging()
    yield
    log_message.reset_logging()


def test_get_logger_namespacing():
    assert bt.get_logger("mymod").name == "backtrader.mymod"
    assert bt.get_logger("backtrader.x").name == "backtrader.x"
    assert bt.get_logger(None).name == "backtrader"
    assert bt.get_logger().name == "backtrader"


def test_exposed_at_top_level():
    assert bt.get_logger is log_message.get_logger
    assert bt.configure_logging is log_message.configure_logging
    assert bt.set_level is log_message.set_level
    assert bt.reset_logging is log_message.reset_logging


def test_default_is_silent():
    """Without configure_logging() the backtrader logger emits nothing."""
    root = logging.getLogger("backtrader")
    assert any(isinstance(h, logging.NullHandler) for h in root.handlers)
    # No managed (stream/file) handlers should be present by default.
    assert not any(getattr(h, "_backtrader_managed", False) for h in root.handlers)


def test_configure_logging_adds_console_handler_and_level():
    logger = bt.configure_logging(level="DEBUG", console=True)
    assert logger.level == logging.DEBUG
    managed = [h for h in logger.handlers if getattr(h, "_backtrader_managed", False)]
    assert len(managed) == 1
    assert isinstance(managed[0], logging.StreamHandler)
    # configuring backtrader must not enable propagation to the root logger
    assert logger.propagate is False


def test_configure_logging_is_idempotent():
    bt.configure_logging(level="INFO")
    bt.configure_logging(level="INFO")
    logger = logging.getLogger("backtrader")
    managed = [h for h in logger.handlers if getattr(h, "_backtrader_managed", False)]
    # Repeated calls must not stack handlers.
    assert len(managed) == 1


def test_configure_logging_does_not_remove_host_handlers():
    """A handler the host app attaches to the backtrader logger must survive."""
    logger = logging.getLogger("backtrader")
    host_handler = logging.NullHandler()
    logger.addHandler(host_handler)
    bt.configure_logging(level="INFO")
    bt.configure_logging(level="WARNING")
    assert host_handler in logger.handlers


def test_configure_logging_file_output(tmp_path):
    log_file = tmp_path / "logs" / "run.log"
    logger = bt.configure_logging(level="INFO", log_file=str(log_file), console=False)
    bt.get_logger("filetest").info("hello-file")
    for h in logger.handlers:
        try:
            h.flush()
        except Exception:
            pass
    assert log_file.exists()
    assert "hello-file" in log_file.read_text(encoding="utf-8")


def test_set_level_runtime():
    bt.configure_logging(level="WARNING")
    bt.set_level("DEBUG")
    assert logging.getLogger("backtrader").level == logging.DEBUG
    bt.set_level(logging.ERROR, name="sub")
    assert logging.getLogger("backtrader.sub").level == logging.ERROR


def test_invalid_level_raises():
    with pytest.raises(ValueError):
        bt.configure_logging(level="NOPE")


def test_reset_logging_restores_nullhandler():
    bt.configure_logging(level="DEBUG")
    log_message.reset_logging()
    logger = logging.getLogger("backtrader")
    assert any(isinstance(h, logging.NullHandler) for h in logger.handlers)
    assert not any(getattr(h, "_backtrader_managed", False) for h in logger.handlers)


def test_spdlogmanager_still_works(tmp_path):
    """Legacy factory must keep working and stay under the backtrader namespace."""
    log_file = tmp_path / "legacy.log"
    logger = log_message.SpdLogManager(
        file_name=str(log_file), logger_name="legacy"
    ).create_logger()
    assert logger.name == "backtrader.legacy"
    logger.info("legacy-msg")
    for h in logger.handlers:
        try:
            h.flush()
        except Exception:
            pass
    assert log_file.exists()
