"""Cerebro checks for QQECloud's recursive runonce boundary state."""

from datetime import datetime, timedelta
import math

import backtrader as bt
import pandas as pd
import pytest


_BAR_COUNT = 180
_SHORT_BAR_COUNT = 40
_SEGMENT_SIZE = 11


def _frame(count):
    close = [
        100.0 + index * 0.09 + math.sin(index * 0.19) * 2.3
        + math.cos(index * 0.037) * 4.0
        for index in range(count)
    ]
    open_ = [value - math.sin(index * 0.41) * 1.1 for index, value in enumerate(close)]
    high = [
        max(open_value, close_value) + 0.8 + (index % 5) * 0.13
        for index, (open_value, close_value) in enumerate(zip(open_, close))
    ]
    low = [
        min(open_value, close_value) - 0.7 - (index % 3) * 0.11
        for index, (open_value, close_value) in enumerate(zip(open_, close))
    ]
    start = datetime(2020, 1, 1)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": [1000.0 + index for index in range(count)],
            "openinterest": [0.0] * count,
        },
        index=pd.DatetimeIndex(
            [start + timedelta(days=index) for index in range(count)]
        ),
    )


def _run(*, runonce, count=_BAR_COUNT, segmented=False):
    class ProbedQQECloud(bt.indicators.QQECloudIndicator):
        def __init__(self):
            self.once_segments = []
            super().__init__()

        def once(self, start, end):
            segment_size = _SEGMENT_SIZE if segmented else max(end - start, 1)
            for segment_start in range(start, end, segment_size):
                segment_end = min(segment_start + segment_size, end)
                previous = (
                    float(self.lines.down.array[segment_start - 1])
                    if segment_start > 0
                    else None
                )
                self.once_segments.append(
                    (segment_start, segment_end, previous)
                )
                super().once(segment_start, segment_end)

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = ProbedQQECloud(self.data)

        def stop(self):
            self.result = {
                "minperiod": self.indicator._minperiod,
                "up": list(self.indicator.up.array),
                "down": list(self.indicator.down.array),
                "xrsi": list(self.indicator._xrsi.array),
                "xxmom": list(self.indicator._xxmom.array),
                "once_segments": list(self.indicator.once_segments),
                "indicator": self.indicator,
            }

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(count)))
    cerebro.addstrategy(Probe)
    return cerebro.run(runonce=runonce, preload=True)[0].result


def _reference_down(xrsi, xxmom, minperiod, darfactor):
    """Apply QQECloud's published trailing-reference recurrence per bar."""
    result = [float("nan")] * len(xrsi)
    previous_tr = 50.0
    for index in range(minperiod - 1, len(xrsi)):
        if previous_tr != previous_tr:
            previous_tr = 50.0
        current_xrsi = float(xrsi[index])
        previous_xrsi = float(xrsi[index - 1]) if index > 0 else current_xrsi
        dar = float(xxmom[index]) * darfactor
        previous_value = previous_tr
        value = previous_value
        if current_xrsi < previous_value:
            value = current_xrsi + dar
            if previous_xrsi < previous_value and value > previous_value:
                value = previous_value
        elif current_xrsi > previous_value:
            value = current_xrsi - dar
            if previous_xrsi > previous_value and value < previous_value:
                value = previous_value
        result[index] = value
        previous_tr = value
    return result


def _assert_exact(actual, expected):
    assert len(actual) == len(expected)
    for index, (actual_value, expected_value) in enumerate(zip(actual, expected)):
        if math.isnan(expected_value):
            assert math.isnan(actual_value), index
        else:
            assert actual_value == expected_value, index


@pytest.mark.parametrize(
    "segmented",
    (False, True),
    ids=("cerebro-once", "repeated-once-segments"),
)
def test_qqe_cloud_once_carries_trailing_reference_across_segments(segmented):
    next_result = _run(runonce=False)
    once_result = _run(runonce=True, segmented=segmented)

    assert next_result["minperiod"] == once_result["minperiod"] == 78
    _assert_exact(next_result["up"], once_result["up"])
    _assert_exact(next_result["xrsi"], once_result["xrsi"])
    _assert_exact(next_result["xxmom"], once_result["xxmom"])

    expected_down = _reference_down(
        next_result["xrsi"],
        next_result["xxmom"],
        next_result["minperiod"],
        darfactor=4.236,
    )
    _assert_exact(next_result["down"], expected_down)
    _assert_exact(once_result["down"], expected_down)

    segments = once_result["once_segments"]
    assert segments[0][:2] == (77, 78)
    assert math.isnan(segments[0][2])
    assert segments[1][0] == 78
    assert math.isfinite(segments[1][2])
    assert segments[1][2] == expected_down[77]

    if segmented:
        assert len(segments) > 2
        assert math.isnan(segments[0][2])
        for segment_start, _, previous in segments[1:]:
            assert math.isfinite(previous)
            assert previous == expected_down[segment_start - 1]


def test_qqe_cloud_short_history_keeps_uninitialized_down_line_nan():
    next_result = _run(runonce=False, count=_SHORT_BAR_COUNT)
    once_result = _run(runonce=True, count=_SHORT_BAR_COUNT)

    assert next_result["minperiod"] == once_result["minperiod"] == 78
    assert all(math.isnan(value) for value in next_result["down"])
    assert all(math.isnan(value) for value in once_result["down"])
    assert not next_result["once_segments"]
    assert not once_result["once_segments"]


def _write_line(line, values):
    for index in range(len(line.array)):
        line.array[index] = float("nan")
    for index, value in enumerate(values):
        line.array[index] = value


def _synthetic_once_outputs(segments):
    result = _run(runonce=True)
    indicator = result["indicator"]
    indicator.p.darfactor = 1.0
    xrsi = [60.0, 61.0, 62.0, 63.0, 64.0]
    xxmom = [1.0, float("nan"), 1.0, 1.0, 1.0]
    _write_line(indicator._xrsi, xrsi)
    _write_line(indicator._xxmom, xxmom)
    _write_line(indicator.down, [float("nan")] * len(xrsi))

    start = 0
    for end in segments:
        indicator.once(start, end)
        start = end

    expected = _reference_down(xrsi, xxmom, 1, darfactor=1.0)
    actual = list(indicator.down.array[: len(xrsi)])
    return actual, expected


@pytest.mark.parametrize(
    "segments",
    ((5,), (2, 5), (1, 2, 4, 5)),
    ids=("one-once", "split-after-nan", "multiple-boundaries"),
)
def test_qqe_cloud_synthetic_nan_trailing_state_matches_next(segments):
    actual, expected = _synthetic_once_outputs(segments)
    _assert_exact(actual, [59.0, float("nan"), 61.0, 62.0, 63.0])
    _assert_exact(actual, expected)
