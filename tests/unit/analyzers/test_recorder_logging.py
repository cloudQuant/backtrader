"""Bounded logging from the optional Bokeh recorder's per-bar path."""

from importlib.metadata import PackageNotFoundError, version
import logging
from logging.handlers import BufferingHandler
from types import SimpleNamespace

import pytest

from backtrader.utils import log_message


def test_recorder_repeated_missing_bar_is_bounded(monkeypatch):
    try:
        version("bokeh")
    except PackageNotFoundError:
        pytest.skip("optional Bokeh distribution is not installed")

    from backtrader.bokeh.analyzers import recorder

    logger = logging.Logger(recorder.__name__, logging.WARNING)
    handler = BufferingHandler(100)
    logger.addHandler(handler)
    monkeypatch.setattr(recorder, "logger", logger)
    monkeypatch.setattr(log_message, "_throttle_state", {})
    monkeypatch.setattr(log_message, "_throttle_enabled", True)
    data = SimpleNamespace(_name="TEST")
    analyzer = SimpleNamespace(
        strategy=SimpleNamespace(datas=[data]), _data={"TEST": {"datetime": []}}
    )

    for _ in range(250):
        recorder.RecorderAnalyzer._record_datas(analyzer)

    assert analyzer._data == {"TEST": {"datetime": []}}
    assert len(handler.buffer) == 3
    assert sum("repeated" in record.getMessage() for record in handler.buffer) == 2
    assert sum(state["total"] for state in log_message._throttle_state.values()) == 250
