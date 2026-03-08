"""Unit tests for TradeLogger monitoring counters and thresholds."""

from __future__ import annotations

import collections
from types import SimpleNamespace

from backtrader.observers.trade_logger import TradeLogger


def _make_logger(**params):
    logger = object.__new__(TradeLogger)
    logger.p = SimpleNamespace(
        submit_count_warn_threshold=params.get("submit_count_warn_threshold", 0),
        cancel_count_warn_threshold=params.get("cancel_count_warn_threshold", 0),
        submit_cancel_total_warn_threshold=params.get("submit_cancel_total_warn_threshold", 0),
        duplicate_order_warn_threshold=params.get("duplicate_order_warn_threshold", 0),
        duplicate_order_window_seconds=params.get("duplicate_order_window_seconds", 60.0),
    )
    logger._monitoring = collections.Counter()
    logger._duplicate_requests = collections.defaultdict(collections.deque)
    logger._triggered_thresholds = set()
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


def test_submit_and_total_thresholds_emit_warning_once():
    """Submit and submit-cancel-total thresholds should fire once when crossed."""
    logger, events = _make_logger(
        submit_count_warn_threshold=2,
        submit_cancel_total_warn_threshold=2,
    )
    details = {
        "data_name": "rb2610",
        "side": "buy",
        "offset": "open",
        "size": 1,
        "price": 3500.0,
    }

    logger._track_request_monitoring("submit", details)
    logger._track_request_monitoring("submit", details)
    logger._track_request_monitoring("submit", details)

    assert logger._monitoring["submit_count"] == 3
    assert logger._monitoring["submit_cancel_total"] == 3
    assert [event["event_type"] for event in events].count("submit_count_threshold_reached") == 1
    assert [event["event_type"] for event in events].count(
        "submit_cancel_total_threshold_reached"
    ) == 1


def test_duplicate_submit_detection_and_threshold():
    """Repeated matching requests inside the time window should count as duplicates."""
    logger, events = _make_logger(
        duplicate_order_warn_threshold=1,
        duplicate_order_window_seconds=60.0,
    )
    details = {
        "data_name": "rb2610",
        "side": "buy",
        "offset": "open",
        "size": 1,
        "price": 3500.0,
    }

    logger._track_request_monitoring("submit", details)
    logger._track_request_monitoring("submit", details)

    assert logger._monitoring["duplicate_submit_count"] == 1
    event_types = [event["event_type"] for event in events]
    assert "duplicate_order_detected" in event_types
    assert "duplicate_order_threshold_reached" in event_types


def test_cancel_threshold_uses_separate_counter():
    """Cancel requests should update cancel-specific counters independently."""
    logger, events = _make_logger(cancel_count_warn_threshold=2)
    details = {
        "data_name": "rb2610",
        "side": "buy",
        "offset": "open",
        "size": 1,
        "price": 3500.0,
        "order_ref": "btapi-1",
    }

    logger._track_request_monitoring("cancel", details)
    logger._track_request_monitoring("cancel", details)

    assert logger._monitoring["cancel_count"] == 2
    assert logger._monitoring["submit_cancel_total"] == 2
    assert [event["event_type"] for event in events].count("cancel_count_threshold_reached") == 1
