"""Actual Backtrader regression coverage for LineCCI warm-up (R71-034)."""

from datetime import datetime, timedelta
import math

import backtrader as bt
import pandas as pd
import pytest
from backtrader.lineiterator import LineIterator


_MA_PERIOD = 3
_FAST_PERIOD = 4
_SLOW_PERIOD = 7
_CLOSES = tuple(
    100.0 + index * 0.7 + math.sin(index * 0.61) * 3.0 + math.cos(index * 0.19)
    for index in range(80)
)


class _CCIDualProbe(bt.Strategy):
    def __init__(self):
        self.cci = bt.indicators.CCIDualOnMA(
            self.data,
            ma_period=_MA_PERIOD,
            fast_period=_FAST_PERIOD,
            slow_period=_SLOW_PERIOD,
        )
        self.linecci_indicators = {
            child.p.period: child
            for child in self.cci._lineiterators[LineIterator.IndType]
            if child.__class__.__name__ == "LineCCI"
        }
        self.linecci_minperiods = {
            period: child._minperiod
            for period, child in self.linecci_indicators.items()
        }


class _DirectLineCCIProbe(bt.Strategy):
    def __init__(self):
        self.cci = bt.indicators.LineCCI(self.data.close, period=_FAST_PERIOD)


def _frame_for_closes(closes):
    start = datetime(2025, 1, 1)
    return pd.DataFrame(
        {
            "open": [close - 0.2 for close in closes],
            "high": [close + 1.0 for close in closes],
            "low": [close - 1.0 for close in closes],
            "close": closes,
            "volume": [100.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.DatetimeIndex(
            [start + timedelta(days=index) for index in range(len(closes))]
        ),
    )


def _run_ccidual(runonce, closes=_CLOSES):
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame_for_closes(closes)))
    cerebro.addstrategy(_CCIDualProbe)
    return cerebro.run(runonce=runonce, preload=True)[0]


def _run_linecci(runonce, closes=_CLOSES):
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame_for_closes(closes)))
    cerebro.addstrategy(_DirectLineCCIProbe)
    return cerebro.run(runonce=runonce, preload=True)[0]


def _cci_reference(values, period):
    """Compute CCI from a complete, already-smoothed input sequence."""
    result = [float("nan")] * min(len(values), period - 1)
    for end in range(period, len(values) + 1):
        window = values[end - period : end]
        mean = sum(window) / period
        mean_deviation = sum(abs(value - mean) for value in window) / period
        if mean_deviation == 0.0:
            result.append(0.0)
        else:
            result.append((window[-1] - mean) / (0.015 * mean_deviation))
    return result


def _expected_ccidual(period, closes=_CLOSES):
    ma_values = [float("nan")] * min(len(closes), _MA_PERIOD - 1)
    for end in range(_MA_PERIOD, len(closes) + 1):
        ma_values.append(sum(closes[end - _MA_PERIOD : end]) / _MA_PERIOD)

    # The first MA is produced at input bar _MA_PERIOD.  Earlier CCI slots
    # remain undefined because LineCCI is not scheduled before its full window.
    if len(closes) < _MA_PERIOD:
        return [float("nan")] * len(closes)
    return [float("nan")] * (_MA_PERIOD - 1) + _cci_reference(
        ma_values[_MA_PERIOD - 1 :], period
    )


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_ccidual_linecci_minperiod_warmup_and_values_match_reference(runonce):
    """CCIDualOnMA waits for each full CCI window and emits real calculated values."""
    strategy = _run_ccidual(runonce)
    indicator = strategy.cci
    fast = list(indicator.lines.fast.array)
    slow = list(indicator.lines.slow.array)

    fast_first_valid = _MA_PERIOD + _FAST_PERIOD - 2
    slow_first_valid = _MA_PERIOD + _SLOW_PERIOD - 2
    assert strategy.linecci_minperiods[_FAST_PERIOD] == fast_first_valid + 1
    assert strategy.linecci_minperiods[_SLOW_PERIOD] == slow_first_valid + 1
    assert indicator._minperiod == slow_first_valid + 1

    fast_expected = _expected_ccidual(_FAST_PERIOD)
    slow_expected = _expected_ccidual(_SLOW_PERIOD)
    assert len(fast) == len(fast_expected) == len(_CLOSES)
    assert len(slow) == len(slow_expected) == len(_CLOSES)

    fast_child = strategy.linecci_indicators[_FAST_PERIOD].lines[0].array
    slow_child = strategy.linecci_indicators[_SLOW_PERIOD].lines[0].array
    assert len(fast_child) == len(fast)
    assert len(slow_child) == len(slow)

    for actual, expected in zip(fast, fast_expected):
        if math.isnan(expected):
            assert math.isnan(actual)
        else:
            assert actual == pytest.approx(expected)

    for actual, expected in zip(slow, slow_expected):
        if math.isnan(expected):
            assert math.isnan(actual)
        else:
            assert actual == pytest.approx(expected)

    # CCIDualOnMA's output lines are bindings to these child lines.  In
    # runonce mode the parent composite must not advance those bound outputs
    # a second time after the children have populated the real data domain.
    for parent_value, child_value in zip(fast, fast_child):
        if math.isnan(parent_value):
            assert math.isnan(child_value)
        else:
            assert parent_value == pytest.approx(child_value)
    for parent_value, child_value in zip(slow, slow_child):
        if math.isnan(parent_value):
            assert math.isnan(child_value)
        else:
            assert parent_value == pytest.approx(child_value)

    assert all(math.isnan(value) for value in fast[:fast_first_valid])
    assert all(math.isnan(value) for value in slow[:slow_first_valid])
    assert any(value != 0.0 for value in fast[fast_first_valid:])
    assert any(value != 0.0 for value in slow[slow_first_valid:])


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_ccidual_short_input_keeps_slow_line_undefined(runonce):
    """A feed shorter than the slow CCI window does not create placeholder zeros."""
    closes = _CLOSES[:_MA_PERIOD + _SLOW_PERIOD - 2]
    strategy = _run_ccidual(runonce, closes=closes)
    indicator = strategy.cci
    fast = list(indicator.lines.fast.array)
    slow = list(indicator.lines.slow.array)

    assert indicator._minperiod == _MA_PERIOD + _SLOW_PERIOD - 1
    assert len(fast) == len(slow) == len(closes)
    assert all(math.isnan(value) for value in slow)
    assert fast == pytest.approx(_expected_ccidual(_FAST_PERIOD, closes), nan_ok=True)
    assert all(math.isnan(value) for value in fast[:_MA_PERIOD + _FAST_PERIOD - 2])


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_linecci_standalone_uses_its_full_input_window(runonce):
    """Direct LineCCI use on a feed line preserves the same period contract."""
    strategy = _run_linecci(runonce)
    values = list(strategy.cci.lines.cci.array)
    expected = _cci_reference(_CLOSES, _FAST_PERIOD)

    assert strategy.cci._minperiod == _FAST_PERIOD
    assert len(values) == len(expected) == len(_CLOSES)
    for actual, reference in zip(values, expected):
        if math.isnan(reference):
            assert math.isnan(actual)
        else:
            assert actual == pytest.approx(reference)
