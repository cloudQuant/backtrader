"""R71-037 regression coverage for CorrectedAverageIndicator range continuity."""

import math

import backtrader as bt
import pandas as pd
import pytest


_PERIOD = 12
_MINPERIOD = _PERIOD + 3
_BASE = 99.92223503333333


def _synthetic_closes():
    """Build an MP15 sequence that exposes state loss at index 15."""
    values = [_BASE] * 40
    values[3] = _BASE - 1.0963132
    values[15] = _BASE - 1.0
    for index in range(16, len(values)):
        values[index] = _BASE + (((index * 7) % 9) - 4) * 0.07
    values[24] = float("nan")
    return values


def _reference_corrected_average(values, period):
    """Compute SMA, population deviation, warmup, and the recursive filter."""
    result = [float("nan")] * len(values)
    first_output = period + 2
    previous = None

    for index in range(first_output, len(values)):
        window = values[index - period + 1 : index + 1]
        if len(window) != period or any(value != value for value in window):
            ma = float("nan")
            std = float("nan")
        else:
            ma = math.fsum(window) / period
            mean_square = math.fsum(value * value for value in window) / period
            variance = abs(mean_square - ma * ma)
            std = math.sqrt(variance)

        current_previous = ma if previous is None else previous
        if current_previous != current_previous:
            current_previous = ma

        variance = std * std
        previous_delta = (current_previous - ma) ** 2
        if previous_delta < variance or previous_delta == 0:
            coefficient = 0.0
        else:
            coefficient = 1.0 - variance / previous_delta

        current = current_previous + coefficient * (ma - current_previous)
        result[index] = current
        previous = current

    return result


def _run_cerebro(values, *, runonce, segmented=False):
    frame = pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": [1.0] * len(values),
            "openinterest": [0.0] * len(values),
        },
        index=pd.date_range("2024-01-01", periods=len(values), freq="D"),
    )
    once_ranges = []

    if segmented:

        class SegmentedCorrectedAverage(bt.indicators.CorrectedAverageIndicator):
            """Split each runonce request into consecutive small ranges."""

            alias = ()

            def once(self, start, end):
                while start < end:
                    segment_end = min(start + 3, end)
                    once_ranges.append((start, segment_end))
                    super().once(start, segment_end)
                    start = segment_end

        indicator_cls = SegmentedCorrectedAverage
    else:
        indicator_cls = bt.indicators.CorrectedAverageIndicator

    result = {}

    class CorrectedAverageProbe(bt.Strategy):
        def __init__(self):
            self.indicator = indicator_cls(self.data, length=_PERIOD)

        def stop(self):
            result["minperiod"] = self.indicator._minperiod
            result["values"] = [float(value) for value in self.indicator.corrected.array]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(CorrectedAverageProbe)
    cerebro.run(runonce=runonce, preload=True)
    result["once_ranges"] = once_ranges
    return result


def _assert_values_match(actual, expected):
    assert len(actual) == len(expected)
    for index, (actual_value, expected_value) in enumerate(zip(actual, expected)):
        if math.isnan(expected_value):
            assert math.isnan(actual_value), f"index {index}: {actual_value!r}"
        else:
            assert actual_value == pytest.approx(
                expected_value, rel=1e-12, abs=1e-12
            ), f"index {index}"


def test_corrected_average_cerebro_modes_keep_state_across_once_ranges():
    """Streaming, full once, and consecutive once segments match the reference."""
    values = _synthetic_closes()
    expected = _reference_corrected_average(values, _PERIOD)

    streaming = _run_cerebro(values, runonce=False)
    batched = _run_cerebro(values, runonce=True)
    segmented = _run_cerebro(values, runonce=True, segmented=True)

    for result in (streaming, batched, segmented):
        assert result["minperiod"] == _MINPERIOD
        _assert_values_match(result["values"], expected)

    assert all(math.isnan(value) for value in expected[:_MINPERIOD - 1])
    assert streaming["values"][15] == pytest.approx(99.8308756, abs=1e-10)
    assert batched["values"][15] == pytest.approx(99.8308756, abs=1e-10)
    assert len(segmented["once_ranges"]) > 3
    assert all(
        left[1] == right[0]
        for left, right in zip(segmented["once_ranges"], segmented["once_ranges"][1:])
    )
    assert all(math.isnan(value) for value in expected[24:36])
    assert math.isfinite(expected[36])
