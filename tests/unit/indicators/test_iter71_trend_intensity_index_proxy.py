"""TII missing values remain invalid and cannot produce strategy trades."""

import math
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest

from tests.functional.strategies.mean_reversion.test_0092_0281_exp_trend_intensity_index import (
    ExpTrendIntensityIndexStrategy,
)


LENGTH1 = 8
LENGTH2 = 3
HIGH_LEVEL = 55.0
LOW_LEVEL = 45.0


def _prices(count=90):
    return [
        100.0 - 0.7 * index if index < 30 else 79.0 + 0.9 * (index - 30) for index in range(count)
    ]


def _frame(*, missing_index=None, count=90):
    prices = _prices(count)
    close = list(prices)
    if missing_index is not None:
        close[missing_index] = math.nan
    return pd.DataFrame(
        {
            "open": prices,
            "high": [value + 0.8 for value in prices],
            "low": [value - 0.8 for value in prices],
            "close": close,
            "volume": [1.0] * count,
            "openinterest": [0.0] * count,
            "spread": [0.0] * count,
        },
        index=pd.date_range("2020-01-01", periods=count),
    )


def _reference(close):
    """Calculate finite TII values and hold color across invalid TII bars."""
    nan = math.nan
    sma = [nan] * len(close)
    deviation = [nan] * len(close)
    for index in range(LENGTH1 - 1, len(close)):
        window = close[index - LENGTH1 + 1 : index + 1]
        if all(math.isfinite(value) for value in window):
            mean = math.fsum(window) / LENGTH1
            mean_square = math.fsum(value * value for value in window) / LENGTH1
            sma[index] = mean
            deviation[index] = math.sqrt(abs(mean_square - mean * mean))

    ema = [nan] * len(close)
    if len(close) >= LENGTH2:
        previous = math.fsum(close[:LENGTH2]) / LENGTH2
        ema[LENGTH2 - 1] = previous
        alpha = 2.0 / (LENGTH2 + 1.0)
        for index in range(LENGTH2, len(close)):
            previous = previous * (1.0 - alpha) + close[index] * alpha
            ema[index] = previous

    first_calculation = max(LENGTH1, LENGTH2) + 5 - 1
    tii = [nan] * len(close)
    color = [nan] * len(close)
    last_valid_color = None
    for index in range(first_calculation, len(close)):
        baseline, smoothed, raw_deviation = (
            sma[index],
            ema[index],
            deviation[index],
        )
        if not all(math.isfinite(value) for value in (baseline, smoothed, raw_deviation)):
            color[index] = nan if last_valid_color is None else last_valid_color
            continue

        value = 50.0 + (smoothed - baseline) / max(raw_deviation, 1e-8) * 10.0
        if not math.isfinite(value):
            color[index] = nan if last_valid_color is None else last_valid_color
            continue

        value = max(0.0, min(100.0, value))
        tii[index] = value
        if value <= LOW_LEVEL:
            last_valid_color = 0.0
        elif value >= HIGH_LEVEL:
            last_valid_color = 4.0
        else:
            last_valid_color = 2.0
        color[index] = last_valid_color

    return first_calculation + 1, tii, color


class _SegmentedTII(bt.indicators.TrendIntensityIndexProxy):
    """Exercise the stateful indicator through one-bar once slices."""

    def once(self, start, end):
        for index in range(start, end):
            super().once(index, index + 1)


def _run_indicator(runonce, *, missing_index=None, segmented=False):
    frame = _frame(missing_index=missing_index)
    indicator_class = _SegmentedTII if segmented else bt.indicators.TrendIntensityIndexProxy

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = indicator_class(
                self.data,
                length1=LENGTH1,
                length2=LENGTH2,
                high_level=HIGH_LEVEL,
                low_level=LOW_LEVEL,
            )

        def stop(self):
            self.result = (
                self.indicator._minperiod,
                list(self.indicator.tii.array),
                list(self.indicator.color_index.array),
            )

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    return frame, cerebro.run()[0].result


def _assert_series(actual, expected):
    assert len(actual) == len(expected)
    for index, (got, want) in enumerate(zip(actual, expected)):
        if math.isnan(want):
            assert math.isnan(got), f"index {index}: expected NaN, got {got!r}"
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12), f"index {index}"


@pytest.mark.parametrize(
    "missing_index",
    [None, 36, 0],
    ids=["finite", "after-valid-color", "inside-ema-seed"],
)
def test_tii_next_once_and_segmented_once_match_missing_reference(missing_index):
    frame, runnext = _run_indicator(False, missing_index=missing_index)
    _, runonce = _run_indicator(True, missing_index=missing_index)
    _, segmented = _run_indicator(True, missing_index=missing_index, segmented=True)
    minperiod, expected_tii, expected_color = _reference(list(frame["close"]))

    for result in (runnext, runonce, segmented):
        assert result[0] == minperiod == max(LENGTH1, LENGTH2) + 5
        _assert_series(result[1], expected_tii)
        _assert_series(result[2], expected_color)

    _assert_series(runnext[1], runonce[1])
    _assert_series(runnext[2], runonce[2])
    _assert_series(runonce[1], segmented[1])
    _assert_series(runonce[2], segmented[2])

    if missing_index == 36:
        last_color = expected_color[missing_index - 1]
        assert last_color in (0.0, 2.0, 4.0)
        assert all(math.isnan(value) for value in expected_tii[missing_index:])
        assert all(value == last_color for value in expected_color[missing_index:])
    elif missing_index == 0:
        assert all(math.isnan(value) for value in expected_tii)
        assert all(math.isnan(value) for value in expected_color)


def _run_strategy(runonce, *, missing_index=None):
    frame = _frame(missing_index=missing_index)

    class RecordingStrategy(ExpTrendIntensityIndexStrategy):
        def __init__(self):
            super().__init__()
            self.entry_events = []
            self.close_events = []

        def _submit_entry(self, side, reason):
            self.entry_events.append((len(self.data0_feed), side, reason))
            super()._submit_entry(side, reason)

        def _submit_close(self, reason, reverse=None):
            self.close_events.append((len(self.data0_feed), reason, reverse))
            super()._submit_close(reason, reverse=reverse)

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.broker.setcash(1_000_000.0)
    cerebro.broker.setcommission(margin=0.01, mult=100.0, stocklike=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(
        RecordingStrategy,
        length1=LENGTH1,
        length2=LENGTH2,
        high_level=HIGH_LEVEL,
        low_level=LOW_LEVEL,
        signal_bar=1,
        stoploss_pips=1_000_000_000,
        takeprofit_pips=1_000_000_000,
    )
    return cerebro.run()[0]


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_strategy_blocks_open_and_close_signals_while_tii_is_invalid(runonce):
    open_missing = _run_strategy(runonce, missing_index=20)
    assert open_missing.entry_events == []
    assert open_missing.close_events == []

    # The close-completion callback is another entry path for a pending reverse.
    # It must use the same TII validity gate as the strategy's bar logic.
    completed_close = SimpleNamespace(
        status=2,
        Submitted=0,
        Accepted=1,
        Completed=2,
        Canceled=3,
        Margin=4,
        Rejected=5,
        executed=SimpleNamespace(price=80.0, size=-0.1),
    )
    open_missing.close_order = completed_close
    open_missing.pending_reverse = "long"
    open_missing.notify_order(completed_close)
    assert open_missing.entry_order is None

    finite = _run_strategy(runonce)
    assert finite.entry_events
    assert finite.close_events

    close_missing = _run_strategy(runonce, missing_index=36)
    assert close_missing.entry_events
    assert close_missing.close_events == []
    assert all(event[0] < 37 for event in close_missing.entry_events)
    assert close_missing.position.size > 0

    # A direct close request also leaves existing protective orders untouched
    # while the current TII value is unavailable.
    stop_order = close_missing.stop_order
    limit_order = close_missing.limit_order
    ExpTrendIntensityIndexStrategy._submit_close(close_missing, "invalid-value-probe")
    assert close_missing.close_order is None
    assert close_missing.stop_order is stop_order
    assert close_missing.limit_order is limit_order
