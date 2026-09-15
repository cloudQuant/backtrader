"""Focused logging regression coverage for matplotlib date-locator fallbacks."""

from __future__ import annotations

import datetime
import logging

import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg", force=True)

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.dates import date2num
from matplotlib.figure import Figure

import backtrader.plot.locator as locator_module
from backtrader.utils import log_message

_SECRET = "synthetic-secret"
_LEGACY_FALLBACK_KEY = "plot.locator.legacy_interval_api_fallback"
_AXIS_SYNC_KEY = "plot.locator.axis_interval_sync_recovery"
_LEGACY_FALLBACK_MESSAGE = (
    "AutoDateLocator legacy interval API unavailable; using axis interval fallback"
)
_AXIS_SYNC_MESSAGE = (
    "AutoDateLocator axis interval synchronization failed; retaining locator fallback"
)
_MESSAGES_BY_KEY = {
    _LEGACY_FALLBACK_KEY: _LEGACY_FALLBACK_MESSAGE,
    _AXIS_SYNC_KEY: _AXIS_SYNC_MESSAGE,
}


class _RecordingHandler(logging.Handler):
    """Capture records without rendering a third-party exception payload."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture(autouse=True)
def _reset_logging_state():
    log_message.reset_logging()
    log_message._throttle_state.clear()
    log_message.set_throttle(True)
    yield
    log_message.reset_logging()
    log_message._throttle_state.clear()
    log_message.set_throttle(True)


@pytest.fixture
def _capture_locator_logging(monkeypatch):
    logger = logging.Logger("backtrader.plot.locator.test", logging.WARNING)
    logger.propagate = False
    handler = _RecordingHandler()
    logger.addHandler(handler)
    monkeypatch.setattr(locator_module, "logger", logger)
    return handler


def _make_agg_locator():
    dmin = datetime.datetime(2024, 1, 1)
    dmax = datetime.datetime(2024, 1, 10)
    dates = [date2num(dmin + datetime.timedelta(days=index)) for index in range(10)]
    figure = Figure()
    FigureCanvasAgg(figure)
    axis = figure.add_subplot(111).xaxis
    locator = locator_module.AutoDateLocator(dates)
    axis.set_major_locator(locator)
    return axis, locator, dmin, dmax


def _records_for_key(handler, key):
    message = _MESSAGES_BY_KEY[key]
    return [record for record in handler.records if message in record.getMessage()]


def _assert_bounded_static_warning(records, key):
    assert len(records) == 3
    assert all(record.levelno == logging.WARNING for record in records)
    assert all(not record.exc_info for record in records)
    rendered = "\n".join(record.getMessage() for record in records)
    assert key in rendered
    assert _SECRET not in rendered
    assert "Traceback" not in rendered


def _assert_throttle_state(key, expected_total=250):
    states = [
        state
        for (
            _logger_name,
            state_key,
            _level,
            _exception_type,
        ), state in log_message._throttle_state.items()
        if state_key == key
    ]
    assert len(states) == 1
    assert states[0]["total"] == expected_total
    assert states[0]["count"] == 49


def test_agg_legacy_interval_fallback_is_bounded_and_returns_usable_locator(
    _capture_locator_logging,
):
    """Modern Agg repeatedly lacks the legacy interval API without log storms."""
    axis, auto_locator, dmin, dmax = _make_agg_locator()

    locators = [auto_locator.get_locator(dmin, dmax) for _ in range(250)]

    assert all(locator.axis is axis for locator in locators)
    assert locators[-1]()
    records = _records_for_key(_capture_locator_logging, _LEGACY_FALLBACK_KEY)
    _assert_bounded_static_warning(records, _LEGACY_FALLBACK_KEY)
    _assert_throttle_state(_LEGACY_FALLBACK_KEY)


def test_axis_interval_sync_failure_has_an_independent_bounded_warning(
    _capture_locator_logging, monkeypatch
):
    """A broken modern-axis sync retains the locator and reports a separate warning."""
    axis, auto_locator, dmin, dmax = _make_agg_locator()

    def _raise_axis_interval_failure(*_args, **_kwargs):
        raise RuntimeError(_SECRET)

    monkeypatch.setattr(axis, "set_view_interval", _raise_axis_interval_failure)
    locators = [auto_locator.get_locator(dmin, dmax) for _ in range(250)]

    assert all(locator.axis is axis for locator in locators)
    for key in (_LEGACY_FALLBACK_KEY, _AXIS_SYNC_KEY):
        _assert_bounded_static_warning(_records_for_key(_capture_locator_logging, key), key)
        _assert_throttle_state(key)
