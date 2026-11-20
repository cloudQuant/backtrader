"""EMA missing-value parity coverage for R71-154."""

import math
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest


def _reference_ema(values, period, source_minperiod=1):
    """Compute the nextstart seed and recursive EMA without Backtrader code."""
    result = [float("nan")] * len(values)
    source_start = max(0, source_minperiod - 1)
    seed_index = source_start + period - 1
    if seed_index >= len(values):
        return result, seed_index + 1

    previous = sum(values[source_start : seed_index + 1]) / period
    result[seed_index] = previous
    alpha = 2.0 / (period + 1.0)
    alpha1 = 1.0 - alpha
    for index in range(seed_index + 1, len(values)):
        previous = previous * alpha1 + values[index] * alpha
        result[index] = previous

    return result, seed_index + 1


def _assert_matches(actual, expected):
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected):
        if math.isnan(expected_value):
            assert math.isnan(actual_value)
        else:
            assert actual_value == pytest.approx(
                expected_value, rel=1e-12, abs=1e-12
            )


def _run_ema(values, period, *, runonce, segmented=False, source_sma_period=None):
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
    result = {}
    once_ranges = []

    if segmented:

        class SegmentedEMA(bt.indicators.EMA):
            """Exercise the production once implementation over two ranges."""

            alias = ()

            def once(self, start, end):
                if end - start < 2:
                    once_ranges.append((start, end))
                    return super().once(start, end)

                split = start + (end - start) // 2
                once_ranges.extend(((start, split), (split, end)))
                super().once(start, split)
                super().once(split, end)

        indicator_cls = SegmentedEMA
    else:
        indicator_cls = bt.indicators.EMA

    class EMAProbeStrategy(bt.Strategy):
        def __init__(self):
            source = self.data.close
            if source_sma_period is not None:
                source = bt.indicators.SMA(source, period=source_sma_period)
            self.ema = indicator_cls(source, period=period)

        def stop(self):
            result["minperiod"] = self.ema._minperiod
            result["values"] = [float(value) for value in self.ema.array]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(EMAProbeStrategy)
    cerebro.run(runonce=runonce, preload=True)
    result["once_ranges"] = once_ranges
    return result


def _new_ema_once_probe(values, period, output):
    alpha = 2.0 / (period + 1.0)
    return SimpleNamespace(
        data=SimpleNamespace(array=list(values), _minperiod=1),
        lines=[SimpleNamespace(array=output)],
        alpha=alpha,
        alpha1=1.0 - alpha,
        p=SimpleNamespace(period=period),
    )


@pytest.mark.parametrize(
    "values,period",
    [
        ([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 3),
        ([1.0, 2.0, 3.0, 4.0, float("nan"), 6.0, 7.0, 8.0], 3),
        ([float("nan"), 2.0, 3.0, 4.0, 5.0, 6.0], 3),
        ([1.0, 2.0], 3),
    ],
    ids=("finite-regression", "middle-nan", "initial-nan", "short-history"),
)
def test_ema_cerebro_modes_match_independent_seed_and_nan_reference(values, period):
    """next, full once, and segmented once share the explicit EMA semantics."""
    expected, minperiod = _reference_ema(values, period)

    for runonce, segmented in ((False, False), (True, False), (True, True)):
        result = _run_ema(
            values, period, runonce=runonce, segmented=segmented
        )
        assert result["minperiod"] == minperiod
        _assert_matches(result["values"], expected)
        if segmented and len(values) >= period + 2:
            assert len(result["once_ranges"]) >= 2
        if segmented and len(values) > 4 and math.isnan(values[4]):
            # The chosen split is immediately after the mid-series NaN.
            assert any(start == 5 for start, _ in result["once_ranges"])


def test_ema_once_preserves_upstream_structural_warmup():
    """An upstream SMA's warmup is distinct from a NaN raw observation."""
    closes = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    source_minperiod = 3
    source = [float("nan"), float("nan")]
    source.extend(
        sum(closes[index - source_minperiod + 1 : index + 1]) / source_minperiod
        for index in range(source_minperiod - 1, len(closes))
    )
    expected, minperiod = _reference_ema(source, period=2, source_minperiod=3)

    for runonce, segmented in ((False, False), (True, False), (True, True)):
        result = _run_ema(
            closes,
            period=2,
            runonce=runonce,
            segmented=segmented,
            source_sma_period=source_minperiod,
        )
        assert result["minperiod"] == minperiod == 4
        _assert_matches(result["values"], expected)


def test_ema_once_seed_before_range_writes_only_requested_prefix():
    """A pre-seed range cannot rewrite later warmup or seed slots."""
    sentinel = -987654.321
    output = [sentinel] * 6
    probe = _new_ema_once_probe([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 3, output)

    bt.indicators.EMA.once(probe, 0, 1)

    assert math.isnan(output[0])
    assert output[1:] == [sentinel] * 5


def test_ema_once_seed_range_can_follow_a_skipped_warmup_segment():
    """A seed-only call does not fill an unrequested gap before the seed."""
    sentinel = -987654.321
    output = [sentinel] * 6
    probe = _new_ema_once_probe([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 3, output)

    bt.indicators.EMA.once(probe, 0, 1)
    bt.indicators.EMA.once(probe, 2, 3)

    assert math.isnan(output[0])
    assert output[1] == sentinel
    assert output[2] == pytest.approx(2.0)
    assert output[3:] == [sentinel] * 3


def test_ema_once_empty_range_does_not_resize_or_write_output():
    """Empty ranges have no output-side effects, even before the seed."""
    sentinel = -987654.321
    output = [sentinel] * 4
    probe = _new_ema_once_probe([1.0, 2.0, 3.0, 4.0], 3, output)

    bt.indicators.EMA.once(probe, 0, 0)

    assert output == [sentinel] * 4


def test_ema_once_short_destination_expands_only_to_requested_end():
    """A range before the seed cannot index or allocate the future seed slot."""
    output = []
    probe = _new_ema_once_probe([1.0, 2.0, 3.0, 4.0], 3, output)

    bt.indicators.EMA.once(probe, 0, 1)

    assert len(output) == 1
    assert math.isnan(output[0])
