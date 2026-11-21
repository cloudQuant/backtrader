"""TRIX vectorized output must match its incremental calculation."""

from datetime import datetime
import math

import backtrader as bt
from backtrader.indicators.trix import Trix, TrixSignal
import pandas as pd
import pytest


def _frame(closes):
    index = pd.date_range(datetime(2024, 1, 1), periods=len(closes), freq="min")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=index,
    )


def _ema(values, period):
    result = [float("nan")] * len(values)
    start = next(
        (index for index, value in enumerate(values) if not math.isnan(value)),
        len(values),
    )
    seed = start + period - 1
    if seed >= len(values):
        return result

    result[seed] = sum(values[start : seed + 1]) / period
    alpha = 2.0 / (period + 1.0)
    for index in range(seed + 1, len(values)):
        result[index] = result[index - 1] * (1.0 - alpha) + values[index] * alpha
    return result


def _reference_trix(closes, period, rocperiod):
    ema3 = closes
    for _ in range(3):
        ema3 = _ema(ema3, period)

    result = [float("nan")] * len(closes)
    for index in range(len(closes)):
        previous_index = index - rocperiod
        if previous_index < 0:
            continue
        current = ema3[index]
        previous = ema3[previous_index]
        if math.isnan(previous):
            continue
        if previous == 0.0:
            result[index] = 0.0
        elif not math.isnan(current):
            result[index] = 100.0 * (current / previous - 1.0)
    return result


def _run_indicator(
    closes,
    *,
    period,
    runonce,
    rocperiod=1,
    signal_period=None,
    source_period=None,
):
    result = {}

    class Probe(bt.Strategy):
        def __init__(self):
            source = self.data.close
            if source_period is not None:
                source = bt.indicators.SMA(source, period=source_period)
            if signal_period is None:
                self.indicator = Trix(source, period=period, _rocperiod=rocperiod)
            else:
                self.indicator = TrixSignal(
                    source,
                    period=period,
                    _rocperiod=rocperiod,
                    sigperiod=signal_period,
                )
            result["indicator"] = self.indicator
            result["minperiod"] = self.indicator._minperiod

        def stop(self):
            result["trix"] = [float(value) for value in self.indicator.lines.trix.array]
            if signal_period is not None:
                result["signal"] = [
                    float(value) for value in self.indicator.lines.signal.array
                ]

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(closes)))
    cerebro.addstrategy(Probe)
    cerebro.run()
    return result


def _assert_same_values(actual, expected):
    assert len(actual) == len(expected)
    for index, (actual_value, expected_value) in enumerate(zip(actual, expected)):
        if math.isnan(expected_value):
            assert math.isnan(actual_value), (index, actual_value, expected_value)
        else:
            assert actual_value == pytest.approx(expected_value, abs=1e-12), (
                index,
                actual_value,
                expected_value,
            )


@pytest.mark.parametrize(("period", "rocperiod"), ((1, 1), (2, 1), (3, 2)))
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_trix_matches_sma_seeded_reference(period, rocperiod, runonce):
    closes = [10.0 + ((index * 7) % 13) + index * 0.2 for index in range(40)]

    result = _run_indicator(
        closes,
        period=period,
        rocperiod=rocperiod,
        runonce=runonce,
    )
    expected = _reference_trix(closes, period, rocperiod)

    assert result["minperiod"] == 3 * period + rocperiod - 2
    assert next(i for i, value in enumerate(expected) if not math.isnan(value)) == (
        result["minperiod"] - 1
    )
    _assert_same_values(result["trix"], expected)


def test_trix_once_writes_only_the_requested_slice():
    closes = [20.0 + ((index * 5) % 11) for index in range(24)]
    result = _run_indicator(closes, period=2, runonce=False)
    indicator = result["indicator"]
    line = indicator.lines.trix.array
    start, end = 2, 10
    sentinel = -9876.5
    expected = _reference_trix(closes, 2, 1)

    for index in range(len(line)):
        line[index] = sentinel

    indicator.once(start, end)

    assert list(line[:start]) == [sentinel] * start
    assert list(line[end:]) == [sentinel] * (len(line) - end)
    _assert_same_values(list(line[start:end]), expected[start:end])


def test_trix_once_matches_next_with_missing_input():
    closes = [15.0 + ((index * 3) % 9) for index in range(32)]
    closes[10] = float("nan")
    expected = _reference_trix(closes, 2, 1)

    once_result = _run_indicator(closes, period=2, runonce=True)
    next_result = _run_indicator(closes, period=2, runonce=False)

    _assert_same_values(once_result["trix"], next_result["trix"])
    _assert_same_values(once_result["trix"], expected)
    assert all(math.isnan(value) for value in once_result["trix"][10:])


def test_trix_zero_denominator_matches_next_when_current_is_missing():
    closes = [0.0] * 32
    closes[12] = float("nan")

    once_result = _run_indicator(closes, period=2, runonce=True)
    next_result = _run_indicator(closes, period=2, runonce=False)
    expected = _reference_trix(closes, period=2, rocperiod=1)

    assert once_result["trix"][12] == 0.0
    assert next_result["trix"][12] == 0.0
    _assert_same_values(once_result["trix"], next_result["trix"])
    _assert_same_values(once_result["trix"], expected)


def test_trix_once_respects_upstream_minperiod():
    closes = [30.0 + ((index * 5) % 17) for index in range(40)]
    once_result = _run_indicator(
        closes, period=2, runonce=True, source_period=3
    )
    next_result = _run_indicator(
        closes, period=2, runonce=False, source_period=3
    )

    assert once_result["minperiod"] == next_result["minperiod"]
    first_finite = next(
        index
        for index, value in enumerate(next_result["trix"])
        if not math.isnan(value)
    )
    assert first_finite == once_result["minperiod"] - 1
    _assert_same_values(once_result["trix"], next_result["trix"])


def test_trix_signal_remains_consistent_with_fixed_trix_once():
    closes = [25.0 + ((index * 11) % 23) for index in range(45)]
    once_result = _run_indicator(
        closes, period=2, runonce=True, signal_period=4
    )
    next_result = _run_indicator(
        closes, period=2, runonce=False, signal_period=4
    )

    _assert_same_values(once_result["trix"], next_result["trix"])
    _assert_same_values(once_result["signal"], next_result["signal"])


def test_trix_signal_once_writes_only_the_requested_slice():
    closes = [25.0 + ((index * 11) % 23) for index in range(45)]
    result = _run_indicator(
        closes, period=2, runonce=False, signal_period=4
    )
    indicator = result["indicator"]
    trix_line = indicator.lines.trix.array
    signal_line = indicator.lines.signal.array
    expected_trix = list(trix_line)
    expected_signal = list(signal_line)
    start, end = 12, 28
    sentinel = -9876.5

    for index in range(len(signal_line)):
        signal_line[index] = sentinel

    indicator.once(start, end)

    _assert_same_values(list(trix_line), expected_trix)
    assert list(signal_line[:start]) == [sentinel] * start
    assert list(signal_line[end:]) == [sentinel] * (len(signal_line) - end)
    _assert_same_values(
        list(signal_line[start:end]), expected_signal[start:end]
    )


def test_trix_signal_once_initializes_warmup_and_cross_seed_slices():
    closes = [25.0 + ((index * 11) % 23) for index in range(32)]
    result = _run_indicator(
        closes, period=2, runonce=False, signal_period=4
    )
    indicator = result["indicator"]
    signal_line = indicator.lines.signal.array
    expected_signal = list(signal_line)
    seed = indicator._minperiod - 1
    start = seed - 2
    sentinel = -9876.5

    for index in range(len(signal_line)):
        signal_line[index] = sentinel

    indicator.once(start, seed)

    assert list(signal_line[:start]) == [sentinel] * start
    assert all(math.isnan(value) for value in signal_line[start:seed])
    assert list(signal_line[seed:]) == [sentinel] * (len(signal_line) - seed)

    for index in range(len(signal_line)):
        signal_line[index] = sentinel

    end = seed + 3
    indicator.once(start, end)

    assert list(signal_line[:start]) == [sentinel] * start
    assert all(math.isnan(value) for value in signal_line[start:seed])
    _assert_same_values(list(signal_line[seed:end]), expected_signal[seed:end])
    assert list(signal_line[end:]) == [sentinel] * (len(signal_line) - end)


def test_trix_signal_nan_propagation_matches_next():
    closes = [25.0 + ((index * 11) % 23) for index in range(45)]
    closes[15] = float("nan")

    once_result = _run_indicator(
        closes, period=2, runonce=True, signal_period=4
    )
    next_result = _run_indicator(
        closes, period=2, runonce=False, signal_period=4
    )

    _assert_same_values(once_result["trix"], next_result["trix"])
    _assert_same_values(once_result["signal"], next_result["signal"])


def test_trix_signal_does_not_recover_after_nan_in_once_recurrence():
    closes = [25.0 + ((index * 11) % 23) for index in range(24)]
    result = _run_indicator(
        closes, period=2, runonce=False, signal_period=4
    )
    indicator = result["indicator"]
    ema3 = indicator.ema3.lines[0].array
    source = [100.0 + index for index in range(len(ema3))]
    source[5] = float("nan")
    for index, value in enumerate(source):
        ema3[index] = value

    indicator.once(0, len(ema3))

    expected_trix = [float("nan")] * len(source)
    first_valid = indicator._minperiod - 1
    for index in range(first_valid, len(source)):
        current = source[index]
        previous = source[index - 1]
        if math.isnan(current) or math.isnan(previous):
            continue
        expected_trix[index] = 100.0 * (current / previous - 1.0)

    expected_signal = [float("nan")] * len(source)
    seed = next(
        (index for index, value in enumerate(expected_trix) if not math.isnan(value)),
        None,
    )
    if seed is not None:
        expected_signal[seed] = expected_trix[seed]
        alpha = indicator.signal_alpha
        alpha1 = indicator.signal_alpha1
        for index in range(seed + 1, len(source)):
            expected_signal[index] = (
                expected_signal[index - 1] * alpha1 + expected_trix[index] * alpha
            )

    _assert_same_values(list(indicator.lines.trix.array), expected_trix)
    _assert_same_values(list(indicator.lines.signal.array), expected_signal)
