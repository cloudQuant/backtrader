"""Runonce extrema must match Python max/min window semantics exactly."""

import math

import numpy as np
import pandas as pd
import pytest

import backtrader as bt


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


def _run_cerebro(sequences, period, *, runonce, exactbars=0):
    class Probe(bt.Strategy):
        params = (("period", period),)

        def __init__(self):
            self.extrema = [
                (
                    bt.indicators.Highest(data.close, period=self.p.period),
                    bt.indicators.Lowest(data.close, period=self.p.period),
                )
                for data in self.datas
            ]
            self.rows = []

        def _record(self):
            self.rows.append(
                (
                    tuple(float(high[0]) for high, _ in self.extrema),
                    tuple(float(low[0]) for _, low in self.extrema),
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


def _reference(values, period, function):
    result = [float("nan")] * len(values)
    for index in range(period - 1, len(values)):
        # This intentionally uses the built-in directly: the ordering of NaN
        # and equal values is part of OperationN's existing contract.
        result[index] = float(function(values[index - period + 1 : index + 1]))
    return result


def _assert_same_float(actual, expected):
    if math.isnan(expected):
        assert math.isnan(actual)
    else:
        assert actual.hex() == expected.hex()


def _assert_rows_match_reference(rows, sequences, period):
    assert rows
    for feed_index, values in enumerate(sequences):
        expected_high = _reference(values, period, max)
        expected_low = _reference(values, period, min)
        actual_high = [row[0][feed_index] for row in rows]
        actual_low = [row[1][feed_index] for row in rows]
        assert len(actual_high) == len(expected_high)
        assert len(actual_low) == len(expected_low)
        for actual, expected in zip(actual_high, expected_high):
            _assert_same_float(actual, expected)
        for actual, expected in zip(actual_low, expected_low):
            _assert_same_float(actual, expected)


@pytest.mark.parametrize("period", (1, 4, 12, 32))
def test_highest_lowest_runonce_and_next_match_python_oracle_with_ties_and_nan(period):
    sequences = (
        (3.0, 3.0, -0.0, 0.0, float("nan"), 5.0, float("nan"), 5.0, -2.0, 4.0),
        (8.0, float("nan"), 8.0, 1.0, 1.0, -0.0, 0.0, 2.0, float("nan"), 7.0),
    )
    if period == 32:
        first = [-0.0, 0.0] + [0.0] * 30 + [1.0, 1.0] + [0.0] * 36
        second = [4.0, 4.0] + [float(index % 5) for index in range(68)]
        first[10] = float("nan")
        first[35] = float("nan")
        second[31] = float("nan")
        second[40] = -0.0
        second[41] = 0.0
        sequences = (tuple(first), tuple(second))
    once_rows = _run_cerebro(sequences, period, runonce=True)
    next_rows = _run_cerebro(sequences, period, runonce=False)

    _assert_rows_match_reference(once_rows, sequences, period)
    _assert_rows_match_reference(next_rows, sequences, period)
    assert len(once_rows) == len(next_rows)
    for once_row, next_row in zip(once_rows, next_rows):
        for once_group, next_group in zip(once_row, next_row):
            for once_value, next_value in zip(once_group, next_group):
                _assert_same_float(once_value, next_value)


@pytest.mark.parametrize("period", (3, 32))
def test_highest_lowest_next_path_remains_correct_with_qbuffer(period):
    sequences = (
        (4.0, 2.0, 2.0, float("nan"), 5.0, 1.0, 1.0, 9.0, -3.0),
    )
    if period == 32:
        values = [float((index * 5) % 13 - 6) for index in range(70)]
        values[0] = -0.0
        values[1] = 0.0
        values[12] = float("nan")
        values[48] = float("nan")
        sequences = (tuple(values),)

    ordinary_rows = _run_cerebro(sequences, period, runonce=False)
    queued_rows = _run_cerebro(sequences, period, runonce=False, exactbars=1)

    _assert_rows_match_reference(queued_rows, sequences, period)
    assert len(ordinary_rows) == len(queued_rows)
    for ordinary_row, queued_row in zip(ordinary_rows, queued_rows):
        for ordinary_group, queued_group in zip(ordinary_row, queued_row):
            for ordinary_value, queued_value in zip(ordinary_group, queued_group):
                _assert_same_float(ordinary_value, queued_value)


def test_runonce_extrema_match_builtin_over_raw_infinity_and_signed_zero():
    period = 32
    values = [float(index % 3) for index in range(70)]
    values[0] = float("nan")
    values[1] = -0.0
    values[2] = 0.0
    values[10] = float("inf")
    values[25] = float("-inf")
    values[40] = float("nan")
    values[45] = -0.0
    values[46] = 0.0
    values = tuple(values)

    class RawArraySource(bt.Indicator):
        lines = ("value",)
        params = (("samples", ()),)

        def once(self, start, end):
            # Write raw doubles to the array so this test reaches OperationN's
            # raw +/-infinity projection and signed-zero handling in once().
            destination = self.lines.value.array
            for index in range(start, end):
                destination[index] = self.p.samples[index]

    class Probe(bt.Strategy):
        def __init__(self):
            self.source = RawArraySource(self.data.close, samples=values)
            self.high = bt.indicators.Highest(self.source, period=period)
            self.low = bt.indicators.Lowest(self.source, period=period)

        def stop(self):
            self.raw_high = list(self.high.lines[0].array)
            self.raw_low = list(self.low.lines[0].array)

    cerebro = bt.Cerebro(stdstats=False, runonce=True, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame((1.0,) * len(values))))
    cerebro.addstrategy(Probe)
    result = cerebro.run()[0]

    projected = tuple(0.0 if math.isinf(v) else v for v in values)
    expected_high = _reference(projected, period, max)
    expected_low = _reference(projected, period, min)
    for actual, expected in zip(result.raw_high, expected_high):
        _assert_same_float(actual, expected)
    for actual, expected in zip(result.raw_low, expected_low):
        _assert_same_float(actual, expected)


@pytest.mark.parametrize("period", (1, 4, 32))
def test_once_rebuilds_window_state_across_arbitrary_chunks(period):
    values = (3.0, 1.0, 1.0, -0.0, 0.0, float("nan"), 5.0, 2.0, 2.0, -4.0)
    if period == 32:
        values = [float((index * 7) % 11 - 5) for index in range(50)]
        values[0] = -0.0
        values[1] = 0.0
        values[20] = float("nan")
        values[33] = float("nan")
        values[34] = -0.0
        values[35] = 0.0
        values = tuple(values)
    size = len(values)

    class Probe(bt.Strategy):
        def __init__(self):
            self.high = bt.indicators.Highest(self.data.close, period=period)
            self.low = bt.indicators.Lowest(self.data.close, period=period)

        def stop(self):
            outputs = []
            for indicator in (self.high, self.low):
                destination = indicator.lines[0].array
                for index in range(len(destination)):
                    destination[index] = float("nan")

                chunks = (
                    (0, period - 1),
                    (period - 1, period),
                    (period, size - 2),
                    (size - 2, size),
                )
                for start, end in chunks:
                    indicator.once(start, end)
                outputs.append(list(destination))
            self.chunked_high, self.chunked_low = outputs

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    cerebro.addstrategy(Probe)
    result = cerebro.run()[0]

    for actual, expected in zip(result.chunked_high, _reference(values, period, max)):
        _assert_same_float(actual, expected)
    for actual, expected in zip(result.chunked_low, _reference(values, period, min)):
        _assert_same_float(actual, expected)


def test_subclass_with_custom_extreme_function_uses_generic_once_path():
    values = (7.0, 2.0, 9.0, 1.0, 5.0, 3.0)
    calls = []

    def choose_last(window):
        calls.append(tuple(window))
        return window[-1]

    class CustomHighest(bt.indicators.Highest):
        func = staticmethod(choose_last)

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = CustomHighest(self.data.close, period=3)

        def stop(self):
            self.output = list(self.indicator.lines[0].array)

    cerebro = bt.Cerebro(stdstats=False, runonce=True, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    cerebro.addstrategy(Probe)
    result = cerebro.run()[0]

    expected = [float("nan")] * 2 + list(values[2:])
    assert len(calls) == len(values) - 2
    assert calls == [
        tuple(values[index - 2 : index + 1]) for index in range(2, len(values))
    ]
    for actual, wanted in zip(result.output, expected):
        _assert_same_float(actual, wanted)
