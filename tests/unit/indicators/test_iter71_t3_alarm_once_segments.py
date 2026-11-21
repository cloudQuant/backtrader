"""Focused runnext/runonce coverage for the migrated T3 alarm indicator."""

import math

import pandas as pd
import pytest

import backtrader as bt
from backtrader.indicators.contrib.t3_alarm_indicator import T3AlarmIndicator


class _SegmentedT3AlarmIndicator(T3AlarmIndicator):
    """Exercise the public once(start, end) contract with repeated slices."""

    _segment_size = 2

    def once(self, start, end):
        for chunk_start in range(start, end, self._segment_size):
            chunk_end = min(end, chunk_start + self._segment_size)
            super().once(chunk_start, chunk_end)


class _SegmentedWithEmptyT3AlarmIndicator(T3AlarmIndicator):
    """Insert zero-length slices between non-empty once segments."""

    _segment_size = 2

    def once(self, start, end):
        for chunk_start in range(start, end, self._segment_size):
            chunk_end = min(end, chunk_start + self._segment_size)
            super().once(chunk_start, chunk_end)
            super().once(chunk_end, chunk_end)
            super().once(0, 0)


class _EmptyOnceAfterNextT3AlarmIndicator(T3AlarmIndicator):
    """Probe that an empty once call cannot reset next-mode state."""

    def next(self):
        super().next()
        super().once(0, 0)


class _CaptureT3Strategy(bt.Strategy):
    params = (
        ("indicator_class", T3AlarmIndicator),
        ("period", 3),
        ("shift", 0),
        ("method", "ema"),
    )

    def __init__(self):
        self.indicator = self.p.indicator_class(
            self.data,
            ma_period=self.p.period,
            ma_shift=self.p.shift,
            ma_method=self.p.method,
        )

    def stop(self):
        self.snapshot = {
            name: list(getattr(self.indicator.lines, name).array)
            for name in ("ma2", "direction", "buy_sig", "sell_sig")
        }
        self.minperiod = self.indicator._minperiod


def _run_t3(values, *, runonce, indicator_class=T3AlarmIndicator,
            period=3, shift=0, method="ema", return_indicator=False):
    frame = pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": [1.0] * len(values),
            "openinterest": [0.0] * len(values),
        },
        index=pd.date_range("2020-01-01", periods=len(values), freq="D"),
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(
        _CaptureT3Strategy,
        indicator_class=indicator_class,
        period=period,
        shift=shift,
        method=method,
    )
    strategy = cerebro.run()[0]
    result = (strategy.snapshot, strategy.minperiod)
    if return_indicator:
        return result + (strategy.indicator,)
    return result


def _assert_line_equal(left, right):
    assert len(left) == len(right)
    for index, (left_value, right_value) in enumerate(zip(left, right)):
        if isinstance(left_value, float) and math.isnan(left_value):
            assert isinstance(right_value, float) and math.isnan(right_value), index
        else:
            assert left_value == pytest.approx(right_value), index


def _assert_snapshots_equal(left, right):
    assert left.keys() == right.keys()
    for name in left:
        _assert_line_equal(left[name], right[name])


def test_t3_once_keeps_direction_across_arbitrary_segments():
    # The second downward slope is exactly the first item of a two-bar once
    # segment. A reversal at that boundary must still see the prior uptrend.
    values = [float(value) for value in (
        10, 11, 12, 13, 14, 15, 16, 15, 14, 13, 12, 11,
        10, 9, 8, 7, 6, 5, 4, 3, 2, 1,
    )]
    next_result, next_minperiod = _run_t3(values, runonce=False)
    segmented_result, segmented_minperiod = _run_t3(
        values, runonce=True, indicator_class=_SegmentedT3AlarmIndicator
    )

    assert next_minperiod == segmented_minperiod == 5
    _assert_snapshots_equal(next_result, segmented_result)
    assert next_result["sell_sig"][9] == 1.0


def test_t3_empty_once_segments_do_not_break_next_or_later_once_state():
    values = [float(value) for value in (
        10, 11, 12, 13, 14, 15, 16, 15, 14, 13, 12, 11,
        10, 9, 8, 7, 6, 5, 4, 3, 2, 1,
    )]
    next_result, _ = _run_t3(
        values,
        runonce=False,
        indicator_class=_EmptyOnceAfterNextT3AlarmIndicator,
    )
    segmented_result, _ = _run_t3(
        values,
        runonce=True,
        indicator_class=_SegmentedWithEmptyT3AlarmIndicator,
    )
    expected_result, _ = _run_t3(values, runonce=False)

    _assert_snapshots_equal(expected_result, next_result)
    _assert_snapshots_equal(expected_result, segmented_result)
    assert next_result["sell_sig"][9] == 1.0
    assert segmented_result["sell_sig"][9] == 1.0


def test_t3_zero_and_internal_empty_ranges_leave_arrays_and_state_untouched():
    values = [float(value) for value in (
        10, 11, 12, 13, 14, 15, 16, 15, 14, 13, 12, 11,
        10, 9, 8, 7, 6, 5, 4, 3, 2, 1,
    )]
    _, _, indicator = _run_t3(values, runonce=False, return_indicator=True)
    lines = (indicator.lines.direction, indicator.lines.buy_sig,
             indicator.lines.sell_sig)
    before = [list(line.array) for line in lines]
    previous_direction = indicator._prev_direction

    indicator.once(0, 0)
    assert indicator._prev_direction == previous_direction
    middle = len(indicator.lines.direction.array) // 2
    indicator._prev_direction = -previous_direction or 1
    mismatched_state = indicator._prev_direction
    indicator.once(middle, middle)

    assert indicator._prev_direction == mismatched_state
    for line, previous_values in zip(lines, before):
        _assert_line_equal(previous_values, list(line.array))


@pytest.mark.parametrize("method", ("ema", "sma", "smma"))
def test_t3_segmented_once_keeps_direction_when_ma_is_missing(method):
    values = [
        10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0,
        float("nan"), 16.0, 15.0, 14.0, 13.0, 12.0, 11.0, 10.0,
        9.0, 8.0, 7.0, 6.0, 5.0,
    ]
    next_result, _ = _run_t3(values, runonce=False, method=method)
    segmented_result, _ = _run_t3(
        values,
        runonce=True,
        indicator_class=_SegmentedT3AlarmIndicator,
        method=method,
    )

    _assert_snapshots_equal(next_result, segmented_result)
    assert next_result["direction"][9] == 1.0


@pytest.mark.parametrize("method", ("ema", "sma", "smma"))
@pytest.mark.parametrize("shift", (0, 2))
def test_t3_default_once_matches_next_with_warmup_and_missing_values(method, shift):
    values = [
        10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 15.0, 14.0,
        13.0, 12.0, 11.0, 10.0, float("nan"), 8.0, 7.0, 8.0,
        9.0, 10.0, 9.0, 8.0, 7.0, 8.0, 9.0, 10.0,
    ]
    next_result, next_minperiod = _run_t3(
        values, runonce=False, method=method, shift=shift
    )
    once_result, once_minperiod = _run_t3(
        values, runonce=True, method=method, shift=shift
    )

    assert next_minperiod == once_minperiod == 5
    _assert_snapshots_equal(next_result, once_result)
    assert any(math.isnan(value) for value in next_result["ma2"])
    assert all(
        math.isnan(value) for value in next_result["direction"][:4]
    )
