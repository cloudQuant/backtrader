"""Execution-mode and clock coverage for AsimmetricStochNRIndicator."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.asimmetric_stoch_nr_indicator import (
    AsimmetricStochNRIndicator,
)


def _frame(count=160, *, frequency="D"):
    close = [100.0 + 3.0 * math.sin(i * 0.25) + i * 0.03 for i in range(count)]
    return pd.DataFrame(
        {"open": close, "high": [x + 0.5 for x in close],
         "low": [x - 0.5 for x in close], "close": close,
         "volume": [100.0] * count},
        index=pd.date_range("2024-01-01", periods=count, freq=frequency),
    )


def _reference(rows, method):
    """Recompute the configured formula from raw rows, independent of line buffers."""
    result = [(math.nan, math.nan) for _ in rows]
    max_period, min_period = 5, 5
    for i in range(26, len(rows)):
        max_total = min_total = close_total = 0.0
        for offset in range(3):
            bar = i - offset
            max_total += max(rows[bar - j][0] for j in range(max_period))
            min_total += min(rows[bar - j][1] for j in range(min_period))
            close_total += rows[bar][2]
        difference = max_total - min_total
        if 21.0 - difference > 0:
            min_total -= (21.0 - difference) / 2.0
            difference = 21.0
        stoch = 100.0 * (close_total - min_total) / difference if difference else -2.0
        previous = result[i - 1][1]
        if method == "ema":
            signal = stoch if math.isnan(previous) else previous + (2.0 / 8.0) * (stoch - previous)
        elif method == "smma":
            signal = stoch if math.isnan(previous) else (6.0 * previous + stoch) / 7.0
        else:
            values = [result[j][0] for j in range(i - 6, i)] + [stoch]
            signal = sum(values) / len(values)
        result[i] = (stoch, signal)
        if previous > 55.0:
            max_period, min_period = 5, 12
        if previous < 45.0:
            max_period, min_period = 12, 5
    return result


def _assert_equal(actual, expected):
    assert len(actual) == len(expected)
    for i, (got, want) in enumerate(zip(actual, expected)):
        if math.isnan(want):
            assert math.isnan(got), (i, got, want)
        else:
            assert got == pytest.approx(want, rel=1e-12, abs=1e-12), i


class _Segmented(AsimmetricStochNRIndicator):
    def once(self, start, end):
        for begin in range(start, end, 7):
            super().once(begin, min(begin + 7, end))


def _run(frame, method, mode, *, segmented=False, multifeed=False):
    indicator_class = _Segmented if segmented else AsimmetricStochNRIndicator

    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = indicator_class(
                self.datas[-1], dmethod=method, overbought=55, oversold=45
            )

        def stop(self):
            self.values = [list(line.array) for line in self.indicator.lines]
            self.period = self.indicator._minperiod

    engine = bt.Cerebro(runonce=mode, preload=True, stdstats=False)
    if multifeed:
        engine.adddata(bt.feeds.PandasData(dataname=_frame(len(frame) * 3)))
    engine.adddata(bt.feeds.PandasData(dataname=frame))
    engine.addstrategy(Probe)
    return engine.run()[0]


def _rows(frame):
    return list(zip(frame.high.tolist(), frame.low.tolist(), frame.close.tolist()))


@pytest.mark.parametrize("method", ["sma", "ema", "smma"])
def test_full_and_segmented_batch_match_independent_formula(method):
    frame = _frame()
    expected = _reference(_rows(frame), method)
    for mode, segmented in [(False, False), (True, False), (True, True)]:
        result = _run(frame, method, mode, segmented=segmented)
        assert result.period == 27
        for index in range(2):
            _assert_equal(result.values[index], [row[index] for row in expected])


@pytest.mark.parametrize("method", ["sma", "ema"])
@pytest.mark.parametrize("field", ["high", "low", "close"])
def test_missing_input_preserves_newest_first_extrema_and_mode_parity(method, field):
    frame = _frame(90)
    frame.loc[frame.index[35], field] = math.nan
    expected = _reference(_rows(frame), method)
    for mode, segmented in [(False, False), (True, False), (True, True)]:
        result = _run(frame, method, mode, segmented=segmented)
        for index in range(2):
            _assert_equal(result.values[index], [row[index] for row in expected])


@pytest.mark.parametrize("mode", [False, True])
def test_secondary_feed_clock_matches_independent_reference(mode):
    frame = _frame(60, frequency="3D")
    result = _run(frame, "ema", mode, multifeed=True)
    expected = _reference(_rows(frame), "ema")
    for index in range(2):
        _assert_equal(result.values[index], [row[index] for row in expected])


def test_replay_recomputes_from_previous_completed_bar():
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = AsimmetricStochNRIndicator(
                self.data, dmethod="ema", overbought=55, oversold=45
            )
            self.samples = []

        def next(self):
            rows = [
                (float(self.data.high[-i]), float(self.data.low[-i]), float(self.data.close[-i]))
                for i in range(len(self.data) - 1, -1, -1)
            ]
            self.samples.append((len(self.data), rows,
                                 float(self.indicator.stoch[0]), float(self.indicator.signal[0])))

    engine = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    engine.replaydata(
        bt.feeds.PandasData(dataname=_frame(300, frequency="h"),
                            timeframe=bt.TimeFrame.Minutes, compression=60),
        timeframe=bt.TimeFrame.Minutes, compression=240,
    )
    engine.addstrategy(Probe)
    samples = engine.run()[0].samples
    assert any(a[0] == b[0] for a, b in zip(samples, samples[1:]))
    for _, rows, actual_stoch, actual_signal in samples:
        expected_stoch, expected_signal = _reference(rows, "ema")[-1]
        _assert_equal([actual_stoch, actual_signal], [expected_stoch, expected_signal])
