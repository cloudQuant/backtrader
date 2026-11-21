"""Real Cerebro coverage for XFisherIndicator's recursive warm-up state."""

from datetime import datetime, timedelta
import math

import backtrader as bt
import pandas as pd
import pytest


_COUNT = 90
_SEGMENT_SIZE = 7


def _frame(count):
    close = [
        80.0 + index * 0.17 + math.sin(index * 0.31) * 2.2
        + math.cos(index * 0.073) * 1.3
        for index in range(count)
    ]
    open_ = [value - math.sin(index * 0.27) * 0.8 for index, value in enumerate(close)]
    high = [
        max(open_value, close_value) + 0.6 + (index % 4) * 0.09
        for index, (open_value, close_value) in enumerate(zip(open_, close))
    ]
    low = [
        min(open_value, close_value) - 0.5 - (index % 3) * 0.07
        for index, (open_value, close_value) in enumerate(zip(open_, close))
    ]
    start = datetime(2021, 1, 1)
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


def _run(*, runonce, count=_COUNT, segmented=False, params=None):
    params = params or {}

    class ProbedXFisher(bt.indicators.XFisherIndicator):
        def __init__(self):
            self.once_segments = []
            super().__init__()

        def once(self, start, end):
            size = _SEGMENT_SIZE if segmented else max(end - start, 1)
            for segment_start in range(start, end, size):
                segment_end = min(segment_start + size, end)
                self.once_segments.append((segment_start, segment_end))
                super().once(segment_start, segment_end)

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = ProbedXFisher(self.data, **params)

        def stop(self):
            self.result = {
                "minperiod": self.indicator._minperiod,
                "xfisher": list(self.indicator.xfisher.array),
                "signal": list(self.indicator.signal.array),
                "once_segments": list(self.indicator.once_segments),
            }

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(count)))
    cerebro.addstrategy(Probe)
    return cerebro.run(runonce=runonce, preload=True)[0].result


def _reference_xfisher(frame, *, flength, ma_length, minperiod):
    """Apply the documented Williams %R/Fisher/EMA recurrence on every valid bar."""
    result = [math.nan] * len(frame)
    previous_value = 0.0
    previous_fish = 0.0
    previous_smooth = None
    alpha = 2.0 / (ma_length + 1.0)

    for index in range(flength - 1, len(frame)):
        start = index - flength + 1
        smax = max(float(value) for value in frame.high.iloc[start : index + 1])
        smin = min(float(value) for value in frame.low.iloc[start : index + 1])
        spread = smax - smin
        if spread == 0.0:
            spread = 1e-12

        wpr = (float(frame.close.iloc[index]) - smin) / spread
        value = (wpr - 0.5) + 0.67 * previous_value
        value = max(min(value, 0.999), -0.999)
        ratio = max((1.0 + value) / (1.0 - value), 1e-7)
        fish = 0.5 * math.log(ratio) + 0.5 * previous_fish
        smooth = (
            fish
            if previous_smooth is None
            else previous_smooth + alpha * (fish - previous_smooth)
        )

        if index >= minperiod - 1:
            result[index] = smooth

        previous_value = value
        previous_fish = fish
        previous_smooth = smooth

    return result


def _assert_equal(actual, expected):
    assert len(actual) == len(expected)
    for index, (got, want) in enumerate(zip(actual, expected)):
        if math.isnan(want):
            assert math.isnan(got), index
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12), index


@pytest.mark.parametrize(
    ("params", "minperiod"),
    [({}, 14), ({"flength": 3, "ma_length": 2}, 7)],
)
@pytest.mark.parametrize(
    ("runonce", "segmented"),
    [(False, False), (True, False), (True, True)],
    ids=("runnext", "runonce", "segmented-once"),
)
def test_x_fisher_recursive_output_includes_valid_prenext_bars(
    params, minperiod, runonce, segmented
):
    frame = _frame(_COUNT)
    result = _run(
        runonce=runonce,
        segmented=segmented,
        params=params,
    )
    flength = params.get("flength", 7)
    ma_length = params.get("ma_length", 5)

    assert result["minperiod"] == minperiod
    expected = _reference_xfisher(
        frame,
        flength=flength,
        ma_length=ma_length,
        minperiod=minperiod,
    )
    _assert_equal(result["xfisher"], expected)

    first_output = minperiod - 1
    assert math.isnan(result["signal"][first_output])
    for index in range(first_output + 1, _COUNT):
        assert result["signal"][index] == pytest.approx(
            expected[index - 1], rel=1e-12, abs=1e-12
        )

    if segmented:
        assert len(result["once_segments"]) > 1


@pytest.mark.parametrize("runonce", [False, True])
def test_x_fisher_short_history_keeps_lines_uninitialized(runonce):
    minperiod = 14
    result = _run(runonce=runonce, count=minperiod - 1)

    assert result["minperiod"] == minperiod
    assert all(math.isnan(value) for value in result["xfisher"])
    assert all(math.isnan(value) for value in result["signal"])
