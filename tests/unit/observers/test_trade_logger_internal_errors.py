"""Tests for TradeLogger internal error handling.

Tests that TradeLogger properly records internal errors when
serialization fails during tick and bar event notification.
"""
from types import SimpleNamespace

from backtrader.observers.trade_logger import TradeLogger


class _BrokenSerializable:
    """Mock class that fails on to_dict() for testing error handling."""

    def to_dict(self):
        """Raise RuntimeError to simulate serialization failure."""
        raise RuntimeError("boom")


def _make_logger():
    logger = object.__new__(TradeLogger)
    logger.p = SimpleNamespace(log_ticks=True, log_bars=True, log_to_console=False)
    logger._tick_logger = object()
    logger._bar_logger = object()
    logger._error_logger = object()
    logger._ensure_loggers_initialized = lambda: None
    logger._get_strategy_name = lambda: "TestStrategy"
    logger._log_time_str = lambda: "2026-03-18T09:30:00+08:00"
    logger._emit_payload = lambda *args, **kwargs: None
    events = []

    def _capture(category, event_type, level="INFO", **fields):
        payload = {
            "category": category,
            "event_type": event_type,
            "level": level,
            **fields,
        }
        events.append(payload)
        return payload

    logger._log_event = _capture
    return logger, events


def test_notify_tick_event_records_internal_error():
    """Test that notify_tick_event records internal error when serialization fails."""
    logger, events = _make_logger()

    logger.notify_tick_event(_BrokenSerializable())

    assert len(events) == 1
    assert events[0]["category"] == "error"
    assert events[0]["event_type"] == "observer_internal_error"
    assert events[0]["error_code"] == "notify_tick_event"


def test_notify_bar_event_records_internal_error():
    """Test that notify_bar_event records internal error when serialization fails."""
    logger, events = _make_logger()

    logger.notify_bar_event(_BrokenSerializable())

    assert len(events) == 1
    assert events[0]["category"] == "error"
    assert events[0]["event_type"] == "observer_internal_error"
    assert events[0]["error_code"] == "notify_bar_event"
