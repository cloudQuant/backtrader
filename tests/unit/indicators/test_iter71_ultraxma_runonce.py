"""Regression coverage for UltraXMAIndicator recursive runonce state (R71-037)."""

from datetime import datetime, timedelta
import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.adx_cross_hull_style_indicator import (
    UltraXMAIndicator,
)


_PERIODS = tuple(3 + 5 * index for index in range(11))


def _ema_last(values, period):
    """Return the EMA seeded by the first-period simple average."""
    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    for price in values[period:]:
        value = alpha * price + (1.0 - alpha) * value
    return value


def _mp61_reversal_closes():
    """Make 11 rising fan lines at MP61, then only the two slowest rise."""
    closes = [100.0 + index for index in range(60)] + [200.0]
    ema_levels = {period: _ema_last(closes, period) for period in _PERIODS}
    closes.append((ema_levels[43] + ema_levels[48]) / 2.0)
    return closes


def _trend_closes(length):
    """Return a deterministic path with several changes in direction."""
    return [
        100.0 + index * 0.17 + math.sin(index * 0.31) * 4.0
        + math.cos(index * 0.13) * 1.5
        for index in range(length)
    ]


def _frame(closes):
    dates = [datetime(2024, 1, 1) + timedelta(days=index) for index in range(len(closes))]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.DatetimeIndex(dates),
    )
    return frame


def _run(closes, *, runonce, indicator_class=UltraXMAIndicator):
    result = {}

    class CaptureIndicator(bt.Strategy):
        def __init__(self):
            self.indicator = indicator_class(self.data)

        def stop(self):
            result["minperiod"] = self.indicator._minperiod
            result["bulls"] = [float(value) for value in self.indicator.bulls.array]
            result["bears"] = [float(value) for value in self.indicator.bears.array]
            result["once_ranges"] = tuple(
                getattr(self.indicator, "_once_ranges", ())
            )

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(closes)))
    cerebro.addstrategy(CaptureIndicator)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _assert_same_line(actual, expected):
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected):
        if math.isnan(expected_value):
            assert math.isnan(actual_value)
        else:
            assert actual_value == pytest.approx(expected_value, abs=1e-12)


class _SegmentedUltraXMA(UltraXMAIndicator):
    """Exercise one Cerebro runonce calculation through contiguous once calls."""

    def __init__(self):
        self._once_ranges = []
        super().__init__()

    def once(self, start, end):
        if end - start <= 1:
            self._once_ranges.append((start, end))
            return super().once(start, end)

        segment_size = 7
        while start < end:
            segment_end = min(start + segment_size, end)
            self._once_ranges.append((start, segment_end))
            super().once(start, segment_end)
            start = segment_end


def test_ultraxma_mp61_first_recursive_bar_matches_runnext():
    closes = _mp61_reversal_closes()
    runnext = _run(closes, runonce=False)
    runonce = _run(closes, runonce=True)

    assert runnext["minperiod"] == runonce["minperiod"] == 61
    assert len(closes) == 62
    for result in (runnext, runonce):
        assert all(math.isnan(value) for value in result["bulls"][:60])
        assert all(math.isnan(value) for value in result["bears"][:60])
        assert result["bulls"][60] == pytest.approx(11.0)
        assert result["bears"][60] == pytest.approx(0.0)
        assert result["bulls"][61] == pytest.approx(6.5)
        assert result["bears"][61] == pytest.approx(4.5)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize(("bar_count", "first_valid"), ((60, None), (61, 60)))
def test_ultraxma_minperiod_warmup_boundary(runonce, bar_count, first_valid):
    result = _run(_mp61_reversal_closes()[:bar_count], runonce=runonce)

    assert result["minperiod"] == 61
    if first_valid is None:
        assert all(math.isnan(value) for value in result["bulls"])
        assert all(math.isnan(value) for value in result["bears"])
    else:
        assert all(math.isnan(value) for value in result["bulls"][:first_valid])
        assert all(math.isnan(value) for value in result["bears"][:first_valid])
        assert math.isfinite(result["bulls"][first_valid])
        assert math.isfinite(result["bears"][first_valid])


def test_ultraxma_full_runonce_sequence_matches_runnext():
    closes = _trend_closes(180)
    runnext = _run(closes, runonce=False)
    runonce = _run(closes, runonce=True)

    assert runnext["minperiod"] == runonce["minperiod"] == 61
    _assert_same_line(runonce["bulls"], runnext["bulls"])
    _assert_same_line(runonce["bears"], runnext["bears"])


def test_ultraxma_segmented_once_calls_keep_recursive_state():
    closes = _trend_closes(180)
    runnext = _run(closes, runonce=False)
    segmented = _run(
        closes, runonce=True, indicator_class=_SegmentedUltraXMA
    )

    assert len(segmented["once_ranges"]) > 3
    assert all(
        left[1] == right[0]
        for left, right in zip(segmented["once_ranges"], segmented["once_ranges"][1:])
    )
    _assert_same_line(segmented["bulls"], runnext["bulls"])
    _assert_same_line(segmented["bears"], runnext["bears"])


def test_ultraxma_nan_input_matches_runnext_without_reseeding():
    closes = _trend_closes(100)
    closes[74] = float("nan")
    runnext = _run(closes, runonce=False)
    runonce = _run(closes, runonce=True)

    _assert_same_line(runonce["bulls"], runnext["bulls"])
    _assert_same_line(runonce["bears"], runnext["bears"])
    assert all(math.isfinite(value) for value in runnext["bulls"][60:])
    assert all(math.isfinite(value) for value in runnext["bears"][60:])
