"""Focused once/next parity tests for the extremum index indicators."""

import math
from array import array
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import backtrader as bt
import backtrader.indicators.basicops as basicops
from backtrader.indicators.basicops import (
    FindFirstIndex,
    FindLastIndex,
    _once_monotonic_index,
)


_INDEX_INDICATORS = (
    bt.indicators.FindFirstIndexHighest,
    bt.indicators.FindFirstIndexLowest,
    bt.indicators.FindLastIndexHighest,
    bt.indicators.FindLastIndexLowest,
)


def _frame(values):
    values = np.asarray(values, dtype=float)
    index = pd.date_range("2021-01-01", periods=len(values), freq="min")
    return pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": np.ones(len(values)),
            "openinterest": np.zeros(len(values)),
        },
        index=index,
    )


def _reference(values, period, choose_max, choose_latest):
    result = [float("nan")] * len(values)
    chooser = max if choose_max else min
    for current in range(period - 1, len(values)):
        window = values[current - period + 1 : current + 1]
        extreme = chooser(window)
        matches = [index for index, value in enumerate(window) if value == extreme]
        if not matches:
            raise StopIteration
        selected = matches[-1] if choose_latest else matches[0]
        result[current] = float(period - selected - 1)
    return result


def _assert_float(actual, expected):
    if math.isnan(expected):
        assert math.isnan(actual)
    else:
        assert actual.hex() == expected.hex()


def _sequences(period):
    values = [0.0] * 80
    values[0:4] = [5.0, 5.0, -0.0, 0.0]
    for index in range(4, 36):
        values[index] = -0.0 if index % 2 == 0 else 0.0
    values[36:40] = [8.0, 8.0, -3.0, -3.0]
    for index in range(40, 76):
        values[index] = -0.0 if index % 2 == 0 else 0.0
    if period > 1:
        # The NaN participates inside recent windows but is never a window's
        # first item, which is the separate StopIteration edge below.
        values[-4] = float("nan")
    return tuple(values)


def _run_cerebro(sequences, period, *, runonce, exactbars=0):
    class Probe(bt.Strategy):
        params = (("period", period),)

        def __init__(self):
            self.indicators = [
                [indicator(data.close, period=self.p.period) for indicator in _INDEX_INDICATORS]
                for data in self.datas
            ]
            self.rows = []

        def _record(self):
            self.rows.append(
                tuple(
                    tuple(float(indicator[0]) for indicator in group)
                    for group in self.indicators
                )
            )

        def prenext(self):
            self._record()

        def nextstart(self):
            self._record()

        def next(self):
            self._record()

    cerebro = bt.Cerebro(
        stdstats=False,
        runonce=runonce,
        preload=not exactbars,
        exactbars=exactbars,
    )
    for values in sequences:
        cerebro.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].rows


@pytest.mark.parametrize("period", (1, 8, 32, 64))
def test_index_extrema_runonce_and_next_match_builtin_ties_and_nan(period):
    first = _sequences(period)
    second = list(reversed(first))
    second = [0.0 if math.isnan(value) else value for value in second]
    if period > 1:
        second[-4] = float("nan")
    sequences = (first, tuple(second))
    if period == 1:
        # A NaN is the first value of a period-one window and is intentionally
        # covered by the explicit exception check, not this parity fixture.
        sequences = tuple(
            tuple(0.0 if math.isnan(value) else value for value in seq)
            for seq in sequences
        )

    once_rows = _run_cerebro(sequences, period, runonce=True)
    next_rows = _run_cerebro(sequences, period, runonce=False)

    for rows in (once_rows, next_rows):
        assert len(rows) == len(sequences[0])
        for feed_index, values in enumerate(sequences):
            for indicator_index, (choose_max, choose_latest) in enumerate(
                ((True, True), (False, True), (True, False), (False, False))
            ):
                expected = _reference(values, period, choose_max, choose_latest)
                actual = [row[feed_index][indicator_index] for row in rows]
                assert len(actual) == len(expected)
                for current, (got, wanted) in enumerate(zip(actual, expected)):
                    try:
                        _assert_float(got, wanted)
                    except AssertionError as error:
                        raise AssertionError(
                            (period, rows is once_rows, feed_index,
                             indicator_index, current, got, wanted)
                        ) from error

    assert len(once_rows) == len(next_rows)
    for once_row, next_row in zip(once_rows, next_rows):
        for once_feed, next_feed in zip(once_row, next_row):
            for once_value, next_value in zip(once_feed, next_feed):
                _assert_float(once_value, next_value)


def test_index_extrema_nan_first_retains_builtin_search_exception():
    values = (float("nan"), 2.0, 3.0)
    for method, evalfunc in (
        (FindFirstIndex.func, max),
        (FindFirstIndex.func, min),
        (FindLastIndex.func, max),
        (FindLastIndex.func, min),
    ):
        owner = SimpleNamespace(
            p=SimpleNamespace(_evalfunc=evalfunc, period=len(values))
        )
        with pytest.raises(StopIteration):
            method(owner, values)


def test_monotonic_index_helper_preserves_positive_and_negative_infinity():
    values = array(
        "d",
        (3.0, float("inf"), 1.0, float("inf"), float("-inf"),
         float("-inf"), 4.0, 4.0, float("-inf"), float("inf"), 2.0),
    )
    period = 4

    for choose_max, choose_latest in (
        (True, True),
        (False, True),
        (True, False),
        (False, False),
    ):
        destination = array("d")
        _once_monotonic_index(
            values,
            destination,
            0,
            len(values),
            period,
            choose_max,
            choose_latest,
        )
        expected = _reference(
            tuple(values), period, choose_max, choose_latest
        )
        for got, wanted in zip(destination, expected):
            _assert_float(got, wanted)


def test_nan_first_keeps_existing_runonce_fallback_and_next_exception(monkeypatch):
    values = [float("nan")] + [float((index * 5) % 17) for index in range(79)]
    calls = []
    original = basicops._once_monotonic_index

    def observe(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(basicops, "_once_monotonic_index", observe)
    _run_cerebro((tuple(values),), 32, runonce=True)
    # Cerebro's optimized range begins after the first complete window; the
    # NaN-first window stays on the old oncestart/fallback path.
    assert calls

    with pytest.raises(StopIteration):
        _run_cerebro((tuple(values),), 32, runonce=False)


def test_midchunk_nan_left_edge_falls_back_and_overwrites_partial_results(
    monkeypatch,
):
    values = tuple(float((index * 7) % 19) for index in range(80))
    helper_calls = []
    fallback_calls = []
    original = basicops._once_monotonic_index

    def observe_helper(*args):
        helper_calls.append(args)
        return original(*args)

    def mark_fallback(indicator, start, end):
        fallback_calls.append((start, end))
        for index in range(start, end):
            indicator.lines[0].array[index] = -123.0

    monkeypatch.setattr(basicops, "_once_monotonic_index", observe_helper)
    monkeypatch.setattr(bt.indicators.Indicator, "once_via_next", mark_fallback)

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.FindFirstIndexHighest(
                self.data.close, period=32
            )

        def stop(self):
            self.data.close.array[10] = float("nan")
            destination = self.indicator.lines[0].array
            for index in range(len(destination)):
                destination[index] = float("nan")
            self.indicator.once(31, 55)
            self.output = list(destination)

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    cerebro.addstrategy(Probe)
    result = cerebro.run()[0]

    assert helper_calls == []
    assert fallback_calls == [(31, 55)]
    assert result.output[31:55] == [-123.0] * 24


def test_once_chunk_with_nan_at_window_left_edge_uses_generic_fallback(monkeypatch):
    values = tuple(float((index * 7) % 19) for index in range(48))
    calls = []
    original = basicops._once_monotonic_index

    def observe(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(basicops, "_once_monotonic_index", observe)

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.FindFirstIndexHighest(
                self.data.close, period=32
            )

        def stop(self):
            self.data.close.array[0] = float("nan")
            destination = self.indicator.lines[0].array
            for index in range(len(destination)):
                destination[index] = float("nan")
            self.indicator.once(31, 32)

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    cerebro.addstrategy(Probe)
    cerebro.run()

    assert calls == []


@pytest.mark.parametrize("period", (8, 32, 64))
def test_index_extrema_next_path_remains_correct_with_qbuffer(period):
    values = _sequences(period)
    ordinary_rows = _run_cerebro((values,), period, runonce=False)
    queued_rows = _run_cerebro((values,), period, runonce=False, exactbars=1)
    assert len(ordinary_rows) == len(queued_rows)
    for ordinary_row, queued_row in zip(ordinary_rows, queued_rows):
        for ordinary_value, queued_value in zip(ordinary_row[0], queued_row[0]):
            _assert_float(ordinary_value, queued_value)


@pytest.mark.parametrize("period", (32, 64))
def test_index_extrema_once_rebuilds_state_across_arbitrary_chunks(period):
    values = _sequences(period)
    size = len(values)

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicators = [
                indicator(self.data.close, period=period)
                for indicator in _INDEX_INDICATORS
            ]

        def stop(self):
            self.chunked = []
            chunks = (
                (0, period - 1),
                (period - 1, period),
                (period, size - 3),
                (size - 3, size),
            )
            for indicator in self.indicators:
                destination = indicator.lines[0].array
                for index in range(len(destination)):
                    destination[index] = float("nan")
                for start, end in chunks:
                    indicator.once(start, end)
                self.chunked.append(list(destination))

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    cerebro.addstrategy(Probe)
    result = cerebro.run()[0]

    for indicator_index, (choose_max, choose_latest) in enumerate(
        ((True, True), (False, True), (True, False), (False, False))
    ):
        expected = _reference(values, period, choose_max, choose_latest)
        for got, wanted in zip(result.chunked[indicator_index], expected):
            _assert_float(got, wanted)


def test_runonce_uses_deque_for_exact_index_extrema(monkeypatch):
    values = tuple(float((index * 19) % 23) for index in range(80))
    calls = []
    original = basicops._once_monotonic_index

    def observe(*args):
        calls.append((args[-2], args[-1]))
        return original(*args)

    monkeypatch.setattr(basicops, "_once_monotonic_index", observe)
    _run_cerebro((values,), 32, runonce=True)

    assert set(calls) == {(True, True), (False, True), (True, False), (False, False)}


def test_index_extrema_subclass_uses_generic_once_fallback():
    values = tuple(float((index * 13) % 17) for index in range(50))
    calls = []

    class CustomHighest(bt.indicators.FindFirstIndexHighest):
        def func(self, iterable):
            calls.append(tuple(iterable))
            return super().func(iterable)

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = CustomHighest(self.data.close, period=32)

        def stop(self):
            self.output = list(self.indicator.lines[0].array)

    cerebro = bt.Cerebro(stdstats=False, runonce=True, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    cerebro.addstrategy(Probe)
    result = cerebro.run()[0]

    assert len(calls) == len(values) - 32 + 1
    assert calls[0] == values[:32]
    expected = _reference(values, 32, choose_max=True, choose_latest=True)
    for got, wanted in zip(result.output, expected):
        _assert_float(got, wanted)


def test_index_extrema_instance_func_override_uses_generic_once_fallback():
    values = tuple(float((index * 11) % 19) for index in range(48))
    calls = []

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.FindFirstIndexHighest(
                self.data.close, period=32
            )

            def choose_zero(window):
                calls.append(tuple(window))
                return 0

            self.indicator.func = choose_zero

        def stop(self):
            self.output = list(self.indicator.lines[0].array)

    cerebro = bt.Cerebro(stdstats=False, runonce=True, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    cerebro.addstrategy(Probe)
    result = cerebro.run()[0]

    assert len(calls) == len(values) - 32 + 1
    assert calls[0] == values[:32]
    expected = [float("nan")] * 31 + [0.0] * (len(values) - 31)
    for got, wanted in zip(result.output, expected):
        _assert_float(got, wanted)
