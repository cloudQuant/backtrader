"""Missing-value parity for unary line operations and CCI composites."""

import math
import operator

import backtrader as bt
import pandas as pd
import pytest
from backtrader.indicators.contrib.close_line_cci import CloseLineCCI
from backtrader.linebuffer import LineOwnOperation


_BAR_COUNT = 160
_NAN_INDEX = 100
_PERIOD = 14


class _ArraySource:
    """Small source for direct LineOwnOperation contract checks."""

    def __init__(self, values):
        self.array = list(values)
        self.index = 0

    def __getitem__(self, ago):
        return self.array[self.index + ago]


def _missing_fixture():
    close = [
        100.0 + index * 0.13 + ((index * 7) % 13) * 0.47
        + math.sin(index * 0.3) * 2.2
        for index in range(_BAR_COUNT)
    ]
    high = [value + 1.1 + (index % 4) * 0.2 for index, value in enumerate(close)]
    low = [value - 0.9 - (index % 3) * 0.25 for index, value in enumerate(close)]
    close[_NAN_INDEX] = high[_NAN_INDEX] = low[_NAN_INDEX] = float("nan")
    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": [1000.0] * _BAR_COUNT,
            "openinterest": [0.0] * _BAR_COUNT,
        },
        index=pd.date_range("2026-01-01", periods=_BAR_COUNT, freq="D"),
    )


def _run_abs_sma(runonce):
    values = [1.0, -2.0, 3.0, float("nan"), -5.0, 6.0]
    frame = pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": [1.0] * len(values),
            "openinterest": [0.0] * len(values),
        },
        index=pd.date_range("2026-02-01", periods=len(values), freq="D"),
    )
    result = {}

    class AbsProbe(bt.Strategy):
        def __init__(self):
            self.absolute = bt.indicators.SMA(abs(self.data.close), period=1)

        def stop(self):
            result["values"] = tuple(self.absolute.lines[0].array)

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(AbsProbe)
    cerebro.run()
    return tuple(values), result["values"]


def _run_cci_composites(runonce):
    frame = _missing_fixture()
    result = {}

    class CompositeProbe(bt.Strategy):
        def __init__(self):
            self.mean_dev = bt.indicators.MeanDeviation(
                self.data.close, period=_PERIOD
            )
            self.cci = bt.indicators.CCI(self.data, period=_PERIOD)
            self.close_cci = CloseLineCCI(self.data.close, period=_PERIOD)
            self.wave = bt.indicators.BinaryWaveIndicator(self.data)

        def stop(self):
            # Preserve complete arrays and lengths.  In particular, do not
            # slice the nested CCI outputs to the data length and hide any
            # once-mode buffer extension while comparing their input domain.
            result["input_length"] = len(self.data)
            result["series"] = {
                "mean_dev": tuple(self.mean_dev.lines.meandev.array),
                "cci": tuple(self.cci.lines.cci.array),
                "close_cci": tuple(self.close_cci.lines.cci.array),
                "wave_cci": tuple(self.wave.cci.lines.cci.array),
                "wave_raw": tuple(self.wave.lines.raw.array),
                "wave": tuple(self.wave.lines.wave.array),
            }

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(CompositeProbe)
    cerebro.run()
    return result


def _assert_domain_series_equal(left, right, domain_length, line_name):
    assert len(left) >= domain_length, f"{line_name}: runnext buffer shorter than data"
    assert len(right) >= domain_length, f"{line_name}: runonce buffer shorter than data"
    for index in range(domain_length):
        actual = left[index]
        expected = right[index]
        if math.isnan(expected):
            assert math.isnan(actual), f"{line_name}[{index}] expected NaN, got {actual!r}"
        else:
            assert actual == pytest.approx(expected), (
                f"{line_name}[{index}] expected {expected!r}, got {actual!r}"
            )


def test_lineownoperation_once_preserves_missing_input_and_keeps_inf_policy():
    values = (None, float("nan"), float("inf"), float("-inf"), -3.0, 2.0)
    source = _ArraySource(values)
    operation = LineOwnOperation(source, operator.abs)

    # This is the read path used by MovingAverageSimple.next().  Directly
    # calling LineOwnOperation.next() still has its older normalization
    # behavior; that method is not used to read this SMA window.
    # Missing values stay missing here; infinities retain their existing
    # zero-normalization rule.
    window_values = []
    for index in range(len(values)):
        source.index = index
        window_values.append(operation[0])
    assert math.isnan(window_values[0])
    assert math.isnan(window_values[1])
    assert window_values[2:4] == [0.0, 0.0]
    assert window_values[4:] == [3.0, 2.0]

    operation.once(0, len(values))
    actual = tuple(operation.array)
    assert len(actual) == len(values)
    assert math.isnan(actual[0])
    assert math.isnan(actual[1])
    assert actual[2:] == (0.0, 0.0, 3.0, 2.0)


def test_lineownoperation_fallback_once_preserves_missing_input():
    attempts = {"count": 0}

    def flaky_abs(value):
        attempts["count"] += 1
        if attempts["count"] == 3:
            raise ValueError("force the per-element fallback")
        return abs(value)

    values = (float("nan"), 2.0, 3.0, float("inf"), float("-inf"))
    operation = LineOwnOperation(_ArraySource(values), flaky_abs)
    operation.once(0, len(values))

    actual = tuple(operation.array)
    assert len(actual) == len(values)
    assert math.isnan(actual[0])
    assert actual[1:] == (2.0, 3.0, 0.0, 0.0)


def test_direct_lineownoperation_next_keeps_its_legacy_nonfinite_policy():
    # This is deliberately separate from the __getitem__ path consumed by
    # MovingAverageSimple.next(); direct LineOwnOperation.next() is not changed
    # by the narrowly scoped once-mode repair.
    for value in (None, float("nan"), float("inf"), float("-inf")):
        source = _ArraySource((value,))
        operation = LineOwnOperation(source, operator.abs)
        operation.forward()
        operation.next()
        assert operation.array[0] == 0.0


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_abs_moving_average_keeps_nan_and_preserves_full_buffer_length(runonce):
    source, actual = _run_abs_sma(runonce)
    assert len(actual) == len(source)
    for index, value in enumerate(source):
        if math.isnan(value):
            assert math.isnan(actual[index])
        else:
            assert actual[index] == pytest.approx(abs(value))


def test_cci_mean_deviation_and_binary_wave_match_across_execution_modes():
    runnext = _run_cci_composites(runonce=False)
    runonce = _run_cci_composites(runonce=True)

    assert runnext["input_length"] == runonce["input_length"] == _BAR_COUNT
    for name in ("wave_raw", "wave"):
        assert len(runnext["series"][name]) == len(runonce["series"][name]) == _BAR_COUNT

    # Nested LineIterator outputs can carry a longer runonce backing buffer;
    # retain and inspect the complete arrays, and require the full data domain
    # to exist before checking every in-domain value.
    for name in ("mean_dev", "cci", "close_cci", "wave_cci"):
        _assert_domain_series_equal(
            runnext["series"][name],
            runonce["series"][name],
            _BAR_COUNT,
            name,
        )

    for name in ("mean_dev", "cci", "close_cci", "wave_cci"):
        values = runonce["series"][name]
        assert all(math.isnan(values[index]) for index in range(100, 127)), name
        assert math.isfinite(values[127]), name

    _assert_domain_series_equal(
        runnext["series"]["wave_raw"], runonce["series"]["wave_raw"], _BAR_COUNT, "wave_raw"
    )
    _assert_domain_series_equal(
        runnext["series"]["wave"], runonce["series"]["wave"], _BAR_COUNT, "wave"
    )
