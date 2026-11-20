"""Cerebro coverage for Bokeh RecorderAnalyzer data and instance keys."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.bokeh.analyzers.recorder import RecorderAnalyzer


def _assert_series(actual, expected):
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected):
        if math.isnan(expected_value):
            assert math.isnan(actual_value)
        else:
            assert actual_value == pytest.approx(expected_value)


@pytest.mark.parametrize("runonce", [False, True])
def test_recorder_preserves_unnamed_feed_and_duplicate_indicator_outputs(runonce):
    closes = [10.0, 20.0, 40.0, 50.0, 70.0, 80.0]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [100.0 + index for index in range(len(closes))],
        },
        index=pd.date_range("2024-01-01", periods=len(closes), freq="D"),
    )

    class Probe(bt.Strategy):
        def __init__(self):
            self.fast = bt.indicators.SimpleMovingAverage(
                self.data.close, period=2
            )
            self.slow = bt.indicators.SimpleMovingAverage(
                self.data.close, period=3
            )

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name="")
    cerebro.addstrategy(Probe)
    cerebro.addanalyzer(RecorderAnalyzer, _name="recorder")

    strategy = cerebro.run()[0]
    analysis = strategy.analyzers.recorder.get_analysis()

    # Keep the established result shape and fallback name for an unnamed feed.
    assert list(analysis) == ["data", "indicators"]
    assert list(analysis["data"]) == ["data0"]
    recorded_data = analysis["data"]["data0"]
    assert set(recorded_data) == {"datetime", "open", "high", "low", "close", "volume"}
    assert recorded_data["close"] == closes
    assert recorded_data["open"] == closes
    assert recorded_data["high"] == [value + 1.0 for value in closes]
    assert recorded_data["low"] == [value - 1.0 for value in closes]
    assert recorded_data["volume"] == [100.0 + index for index in range(len(closes))]
    assert len(recorded_data["datetime"]) == len(closes)

    indicators = analysis["indicators"]
    fast_key = f"{strategy.fast.__class__.__name__}#{id(strategy.fast)}"
    slow_key = f"{strategy.slow.__class__.__name__}#{id(strategy.slow)}"
    assert fast_key != slow_key
    assert set(indicators) == {fast_key, slow_key}
    assert list(indicators[fast_key]) == ["sma"]
    assert list(indicators[slow_key]) == ["sma"]
    _assert_series(
        indicators[fast_key]["sma"], [float("nan"), 15.0, 30.0, 45.0, 60.0, 75.0]
    )
    _assert_series(
        indicators[slow_key]["sma"],
        [float("nan"), float("nan"), 70.0 / 3.0, 110.0 / 3.0, 160.0 / 3.0, 200.0 / 3.0],
    )
