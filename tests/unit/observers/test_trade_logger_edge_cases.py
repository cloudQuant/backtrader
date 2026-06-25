#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""Edge case unit tests for TradeLogger bare-except logging fixes.

Tests cover:
- _collect_indicators logs on attribute access failure
- _extract_indicator_values logs on line read failure
- _save_position_snapshot logs on file write failure
- MySQL insert methods log on failure
- _store_provider / _session_id / _get_datetime_str defensive accessors
- _safe_order_info edge cases
- _make_duplicate_key with zero/None values
- _base_event structure
"""

import datetime as dt
import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backtrader.observers.trade_logger import TradeLogger
from backtrader.utils import AutoOrderedDict


# ===========================================================================
# Helpers
# ===========================================================================


def _make_bare_logger(**overrides):
    """Create a minimal TradeLogger without full backtrader plumbing."""
    tl = object.__new__(TradeLogger)
    tl.p = SimpleNamespace(
        log_ticks=True,
        log_bars=True,
        log_orders=True,
        log_trades=True,
        log_positions=True,
        log_indicators=True,
        log_signals=True,
        log_system=True,
        log_monitoring=True,
        log_errors=True,
        log_position_snapshot=False,
        log_to_console=False,
        log_format="json",
        log_dir="/tmp/test_trade_logger",
        snapshot_file="test_snapshot.yaml",
        mysql_enabled=False,
        submit_count_warn_threshold=0,
        cancel_count_warn_threshold=0,
        submit_cancel_total_warn_threshold=0,
        duplicate_order_warn_threshold=0,
        duplicate_order_window_seconds=60.0,
    )
    for k, v in overrides.items():
        setattr(tl.p, k, v)

    tl._order_logger = None
    tl._trade_logger = None
    tl._position_logger = None
    tl._indicator_logger = None
    tl._signal_logger = None
    tl._system_logger = None
    tl._monitor_logger = None
    tl._tick_logger = None
    tl._bar_logger = None
    tl._error_logger = None
    tl._mysql_conn = None
    tl._last_position_state = {}
    tl._run_id = "test-run-1"
    tl._monitoring = {}
    tl._duplicate_requests = {}
    tl._triggered_thresholds = set()
    tl._loggers_initialized = True
    tl._owner = None
    tl._ensure_loggers_initialized = lambda: None
    tl._get_strategy_name = lambda: "TestStrategy"
    tl._get_datetime_str = lambda: "2024-01-01 00:00:00"
    tl._log_time_str = lambda: "2024-01-01T00:00:00+08:00"
    tl._store_provider = lambda: ""
    tl._session_id = lambda: ""
    return tl


# ===========================================================================
# _collect_indicators logging tests
# ===========================================================================


class TestCollectIndicatorsLogging:
    """Verify _collect_indicators logs errors instead of silently skipping."""

    def test_attr_access_failure_logged(self, caplog):
        """When getattr raises, a debug log should be emitted."""
        tl = _make_bare_logger()

        # Create an owner with a problematic attribute
        class BadOwner:
            """Mock owner that raises on bad_attr access."""

            _lineiterators = {}
            IndType = 0

            def __dir__(self):
                """Return list of attributes."""
                return ["good_attr", "bad_attr"]

            def __getattr__(self, name):
                """Raise on bad_attr, return value on good_attr."""
                if name == "bad_attr":
                    raise RuntimeError("attr explosion")
                if name == "good_attr":
                    return 42  # Not an indicator
                raise AttributeError(name)

        tl._owner = BadOwner()

        with caplog.at_level(logging.DEBUG):
            result = tl._collect_indicators()

        assert any("Failed to read indicator attr" in r.message for r in caplog.records)
        assert isinstance(result, dict)


class TestExtractIndicatorValuesLogging:
    """Verify _extract_indicator_values logs on line read failure."""

    def test_line_read_failure_logged(self, caplog):
        """When reading a line value raises, a debug log should be emitted."""
        tl = _make_bare_logger()

        class BadLine:
            """Mock line that raises on access."""

            def __len__(self):
                """Return 1."""
                return 1

            def __getitem__(self, idx):
                """Raise IndexError."""
                raise IndexError("no data")

        class FakeLines:
            """Mock lines object."""

            def getlinealiases(self):
                """Return line aliases."""
                return ["value"]

            def __getattr__(self, name):
                """Return BadLine for 'value', raise otherwise."""
                if name == "value":
                    return BadLine()
                raise AttributeError(name)

        class FakeIndicator:
            """Mock indicator with FakeLines."""
            lines = FakeLines()

        indicators_dict = {}
        with caplog.at_level(logging.DEBUG):
            tl._extract_indicator_values(FakeIndicator(), indicators_dict)

        assert any("Failed to read indicator line" in r.message for r in caplog.records)


# ===========================================================================
# Defensive accessor tests
# ===========================================================================


class TestDefensiveAccessors:
    """Test _store_provider, _session_id, _get_datetime_str edge cases."""

    def test_store_provider_no_owner(self):
        """Should return empty string when owner is None."""
        tl = _make_bare_logger()
        tl._owner = None
        # Call the real method
        result = TradeLogger._store_provider(tl)
        assert result == ""

    def test_session_id_no_owner(self):
        """Should return empty string when owner is None."""
        tl = _make_bare_logger()
        tl._owner = None
        result = TradeLogger._session_id(tl)
        assert result == ""

    def test_get_datetime_str_no_owner(self):
        """Should fall back to current time when owner has no datetime."""
        tl = _make_bare_logger()
        tl._owner = SimpleNamespace()  # No datetime attribute
        result = TradeLogger._get_datetime_str(tl)
        assert isinstance(result, str)
        assert len(result) > 0
        parsed = dt.datetime.fromisoformat(result)
        assert parsed.tzinfo is not None

    def test_get_datetime_str_normalizes_naive_strategy_time(self):
        """Strategy datetimes should not be logged as ambiguous naive strings."""
        tl = _make_bare_logger()
        tl._owner = SimpleNamespace(
            datetime=SimpleNamespace(datetime=lambda: dt.datetime(2026, 6, 23, 3, 31))
        )

        result = TradeLogger._get_datetime_str(tl)

        assert result == "2026-06-23T03:31:00.000+00:00"

    def test_get_strategy_name_no_owner(self):
        """When _owner is None, should return the stable fallback name."""
        tl = _make_bare_logger()
        tl._owner = None
        result = TradeLogger._get_strategy_name(tl)
        assert result == "Unknown"

    def test_store_provider_failure_logged(self, caplog):
        """Store provider accessor failures should emit a debug log."""
        tl = _make_bare_logger()

        class BadOwner:
            """Mock owner that raises on broker property access."""

            @property
            def broker(self):
                """Raise RuntimeError."""
                raise RuntimeError("broker boom")

        tl._owner = BadOwner()

        with caplog.at_level(logging.DEBUG):
            result = TradeLogger._store_provider(tl)

        assert result == ""
        assert any("Failed to read store provider" in record.message for record in caplog.records)

    def test_session_id_failure_logged(self, caplog):
        """Session id accessor failures should emit a debug log."""
        tl = _make_bare_logger()

        class BadOwner:
            """Mock owner that raises on broker property access."""

            @property
            def broker(self):
                """Raise RuntimeError."""
                raise RuntimeError("broker boom")

        tl._owner = BadOwner()

        with caplog.at_level(logging.DEBUG):
            result = TradeLogger._session_id(tl)

        assert result == ""
        assert any("Failed to read session id" in record.message for record in caplog.records)

    def test_get_datetime_failure_logged(self, caplog):
        """Datetime accessor failures should emit a debug log and return a fallback string."""
        tl = _make_bare_logger()
        tl._owner = SimpleNamespace(datetime=SimpleNamespace(datetime=lambda: (_ for _ in ()).throw(RuntimeError("dt boom"))))

        with caplog.at_level(logging.DEBUG):
            result = TradeLogger._get_datetime_str(tl)

        assert isinstance(result, str)
        parsed = dt.datetime.fromisoformat(result)
        assert parsed.tzinfo is not None
        assert any("Failed to read strategy datetime" in record.message for record in caplog.records)

    def test_get_strategy_name_failure_logged(self, caplog):
        """Strategy name accessor failures should emit a debug log and return Unknown."""
        tl = _make_bare_logger()

        class BrokenOwner:
            """Mock owner that raises on __class__ access."""

            @property
            def __class__(self):
                """Raise RuntimeError."""
                raise RuntimeError("class boom")

        tl._owner = BrokenOwner()

        with caplog.at_level(logging.DEBUG):
            result = TradeLogger._get_strategy_name(tl)

        assert result == "Unknown"
        assert any("Failed to read strategy name" in record.message for record in caplog.records)


# ===========================================================================
# _safe_order_info edge cases
# ===========================================================================


class TestSafeOrderInfo:
    """Test _safe_order_info with various info shapes."""

    def test_none_info(self):
        """Test that None info returns None."""
        order = SimpleNamespace(info=None)
        assert TradeLogger._safe_order_info(order, "key") is None

    def test_dict_like_info(self):
        """Test that dict-like info is accessed correctly."""
        order = SimpleNamespace(info={"error_code": "test_err"})
        assert TradeLogger._safe_order_info(order, "error_code") == "test_err"

    def test_attr_based_info(self):
        """Test that attr-based info is accessed correctly."""
        order = SimpleNamespace(info=SimpleNamespace(error_code="attr_err"))
        assert TradeLogger._safe_order_info(order, "error_code") == "attr_err"

    def test_missing_key_returns_default(self):
        """Test that missing key returns default value."""
        order = SimpleNamespace(info={})
        assert TradeLogger._safe_order_info(order, "missing", "fallback") == "fallback"

    def test_broken_get_returns_default(self):
        """Test that broken get() returns default value."""
        class BrokenInfo:
            """Mock info that raises on get()."""

            def get(self, key, default=None):
                """Raise TypeError."""
                raise TypeError("broken")
        order = SimpleNamespace(info=BrokenInfo())
        assert TradeLogger._safe_order_info(order, "key", "safe") == "safe"

    def test_broken_attr_access_falls_back_to_get(self):
        """Test that broken attr access falls back to get()."""
        class BrokenAttrInfo:
            """Mock info that raises on attr access but get() works."""

            def __getattr__(self, name):
                """Raise on error_code, AttributeError otherwise."""
                if name == "error_code":
                    raise RuntimeError("attr boom")
                raise AttributeError(name)

            def get(self, key, default=None):
                """Return from-get for error_code."""
                if key == "error_code":
                    return "from-get"
                return default

        order = SimpleNamespace(info=BrokenAttrInfo())
        assert TradeLogger._safe_order_info(order, "error_code", "safe") == "from-get"

    def test_empty_auto_ordered_dict_is_treated_as_missing(self):
        """Test that empty AutoOrderedDict is treated as missing."""
        order = SimpleNamespace(info=AutoOrderedDict())
        assert TradeLogger._safe_order_info(order, "external_order_id") is None
        assert TradeLogger._safe_order_info(order, "error_code", "") == ""


# ===========================================================================
# _make_duplicate_key edge cases
# ===========================================================================


class TestMakeDuplicateKey:
    """Test duplicate key generation with edge values."""

    def test_all_none_details(self):
        """Test that all None details produces correct key."""
        key = TradeLogger._make_duplicate_key(None, "submit", {})
        assert isinstance(key, tuple)
        assert len(key) == 7
        assert key == ("submit", "", "", "", "", "", "")

    def test_zero_values_in_details(self):
        """Zero values should appear as '0' in the key, not empty string."""
        details = {
            "data_name": "BTC",
            "side": "buy",
            "offset": "open",
            "size": 0,
            "price": 0.0,
            "order_ref": 0,
        }
        key = TradeLogger._make_duplicate_key(None, "submit", details)
        assert key == ("submit", "BTC", "buy", "open", "0", "0.0", "0")

    def test_false_value_is_preserved(self):
        """False should be preserved as 'False' rather than collapsed to empty string."""
        details = {
            "data_name": "BTC",
            "side": False,
            "offset": None,
            "size": 1,
            "price": None,
            "order_ref": None,
        }
        key = TradeLogger._make_duplicate_key(None, "submit", details)
        assert key == ("submit", "BTC", "False", "", "1", "", "")


# ===========================================================================
# _base_event structure test
# ===========================================================================


class TestBaseEvent:
    """Test base event payload structure."""

    def test_base_event_has_required_fields(self):
        """Test that base_event has all required fields."""
        tl = _make_bare_logger()
        payload = tl._base_event("test_event", level="WARNING", custom_field="value")

        assert payload["event_type"] == "test_event"
        assert payload["level"] == "WARNING"
        assert payload["run_id"] == "test-run-1"
        assert payload["strategy_name"] == "TestStrategy"
        assert payload["custom_field"] == "value"
        assert "log_time" in payload
        assert "event_time" in payload

    def test_base_event_defaults_event_time_to_log_time(self):
        """System events before the first bar should use wall-clock time."""
        tl = _make_bare_logger()

        payload = tl._base_event("session_started")

        assert payload["log_time"] == "2024-01-01T00:00:00+08:00"
        assert payload["event_time"] == payload["log_time"]

    def test_base_event_normalizes_naive_explicit_event_time_to_utc(self):
        """Gateway/store events should not write ambiguous naive timestamps."""
        tl = _make_bare_logger()

        payload = tl._base_event(
            "store_connected",
            event_time="2026-06-24T17:15:06.535",
        )

        assert payload["event_time"] == "2026-06-24T17:15:06.535+00:00"

    def test_base_event_preserves_explicit_aware_event_time(self):
        """Gateway/store events should keep source timestamps with offsets."""
        tl = _make_bare_logger()

        payload = tl._base_event(
            "store_connected",
            event_time="2026-06-24T17:15:06.535+08:00",
        )

        assert payload["event_time"] == "2026-06-24T17:15:06.535+08:00"


class TestTradeDatetimeFields:
    """Test trade log timestamp selection."""

    class _FakeDateLine:
        def __init__(self, current_dt):
            self.current_dt = current_dt

        def datetime(self, *args):
            return self.current_dt

    class _FakeData:
        _name = "XAUUSD"

        def __init__(self, current_dt, numdates=None):
            self.datetime = TestTradeDatetimeFields._FakeDateLine(current_dt)
            self._numdates = dict(numdates or {})

        def num2date(self, value):
            return self._numdates[value]

    def test_open_trade_zero_dtopen_uses_current_data_datetime(self):
        """Simulated/open trades with dtopen=0 must not write a 1970 timestamp."""
        tl = _make_bare_logger()
        tl._get_datetime_str = lambda: "1970-01-01T00:00:00.000+00:00"
        trade = SimpleNamespace(
            ref=1,
            data=self._FakeData(dt.datetime(2026, 6, 25, 4, 6)),
            size=-0.01,
            price=3983.9903186,
            value=-39.839903186,
            pnl=0.0,
            pnlcomm=-0.00278879322302,
            commission=0.00278879322302,
            isclosed=False,
            isopen=True,
            baropen=25,
            barclose=0,
            barlen=0,
            dtopen=0.0,
            dtclose=0.0,
        )

        payload = TradeLogger._format_trade(tl, trade)

        assert payload["datetime"] == "2026-06-25T04:06:00.000+00:00"
        assert payload["dtopen"] == "2026-06-25T04:06:00.000+00:00"
        assert payload["dtclose"] is None
        assert not payload["datetime"].startswith("1970-01-01")

    def test_closed_trade_prefers_backtrader_open_close_numdates(self):
        """Closed trade logs should use trade dtopen/dtclose before data current time."""
        tl = _make_bare_logger()
        trade = SimpleNamespace(
            ref=2,
            data=self._FakeData(
                dt.datetime(2026, 6, 25, 4, 30),
                {
                    101.0: dt.datetime(2026, 6, 25, 4, 6),
                    102.0: dt.datetime(2026, 6, 25, 4, 12),
                },
            ),
            size=0.0,
            price=3984.0,
            value=0.0,
            pnl=1.0,
            pnlcomm=0.9,
            commission=0.1,
            isclosed=True,
            isopen=False,
            baropen=25,
            barclose=31,
            barlen=6,
            dtopen=101.0,
            dtclose=102.0,
        )

        payload = TradeLogger._format_trade(tl, trade)

        assert payload["datetime"] == "2026-06-25T04:12:00.000+00:00"
        assert payload["dtopen"] == "2026-06-25T04:06:00.000+00:00"
        assert payload["dtclose"] == "2026-06-25T04:12:00.000+00:00"


class TestMarketEventTimeFields:
    """Test tick/bar event timestamp normalization for JSON logs."""

    def test_notify_bar_event_normalizes_datetime_and_local_time(self):
        """Bar logs should expose timezone-aware ISO strings for datetime fields."""
        tl = _make_bare_logger()
        messages = []
        tl._bar_logger = SimpleNamespace(info=messages.append)

        TradeLogger.notify_bar_event(
            tl,
            {
                "symbol": "rb2610",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 10,
                "timestamp": 1782156719.0,
                "local_time": 1782329081.1869645,
                "datetime": "2026-06-23 03:31:00",
            },
        )

        assert len(messages) == 1
        payload = json.loads(messages[0])
        assert payload["datetime"] == "2026-06-23T03:31:00.000+00:00"
        assert payload["timestamp"] == 1782156719.0

        local_time = dt.datetime.fromisoformat(payload["local_time"])
        assert local_time.tzinfo is not None
        assert local_time.timestamp() == pytest.approx(1782329081.1869645, abs=0.002)
