"""Exact rolling sums for large simple standard-deviation windows."""

from __future__ import annotations

import datetime as dt
import math

import backtrader as bt
import pytest

from backtrader.indicators.deviation import _add_fsum_partial


class _SyntheticValues(bt.feed.DataBase):
    """Feed deterministic values through the real Cerebro lifecycle."""

    params = (("input_values", ()),)

    def __init__(self):
        super().__init__()
        self._index = 0

    def _load(self):
        if self._index >= len(self.p.input_values):
            return False

        value = float(self.p.input_values[self._index])
        moment = dt.datetime(2026, 1, 1) + dt.timedelta(minutes=self._index)
        self.lines.datetime[0] = bt.date2num(moment)
        self.lines.open[0] = value
        self.lines.high[0] = value
        self.lines.low[0] = value
        self.lines.close[0] = value
        self.lines.volume[0] = 1.0
        self.lines.openinterest[0] = 0.0
        self._index += 1
        return True


class _Probe(bt.Strategy):
    params = (
        ("period", 64),
        ("indicator_cls", bt.indicators.StandardDeviation),
    )

    def __init__(self):
        self.deviation = self.p.indicator_cls(self.data.close, period=self.p.period)

    def stop(self):
        self.result = list(self.deviation.stddev.array)


class _DynamicProbe(bt.Strategy):
    """Change the runnext period after output on two known bars."""

    params = (("period", 64),)

    def __init__(self):
        self.deviation = bt.indicators.StandardDeviation(
            self.data.close, period=self.p.period
        )

    def next(self):
        if len(self) == 80:
            self.deviation.p.period = 32
        elif len(self) == 110:
            self.deviation.p.period = 64

    def stop(self):
        self.result = list(self.deviation.stddev.array)


class _MutatingFinishDeviation(bt.indicators.StandardDeviation):
    """Preserve the behavior of subclasses whose finish hook mutates input."""

    def __init__(self):
        self.finish_calls = 0
        super().__init__()

    def _finish(self, meansq, mean):
        result = super()._finish(meansq, mean)
        self.finish_calls += 1
        if self.finish_calls == 5:
            self.data.array[10] = 999.0
        return result


class _ReferenceMutatingDeviation(_MutatingFinishDeviation):
    """Force the original runonce loop for the mutating subclass reference."""

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.stddev.array
        period = self.p.period
        actual_end = min(end, len(darray))
        nan_val = float("nan")

        while len(larray) < end:
            larray.append(nan_val)
        for index in range(min(period - 1, len(larray), actual_end)):
            larray[index] = nan_val

        self._once_simple_fsum(
            actual_end,
            darray,
            larray,
            period,
            None,
            nan_val,
            period - 1,
        )


class _CountingDeviation(bt.indicators.StandardDeviation):
    """Make otherwise-valid _finish calls observable for fallback coverage."""

    def __init__(self):
        self.finish_calls = 0
        super().__init__()

    def _finish(self, meansq, mean):
        self.finish_calls += 1
        return super()._finish(meansq, mean)


class _LegacyDeviation(bt.indicators.StandardDeviation):
    """Run the pre-optimization simple-window loop regardless of class."""

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.stddev.array
        period = self.p.period
        actual_end = min(end, len(darray))
        nan_val = float("nan")

        while len(larray) < end:
            larray.append(nan_val)
        for index in range(min(period - 1, len(larray), actual_end)):
            larray[index] = nan_val

        self._once_simple_fsum(
            actual_end,
            darray,
            larray,
            period,
            None,
            nan_val,
            period - 1,
        )


class _ReferenceCountingDeviation(_CountingDeviation):
    """Use the original simple per-window loop as an independent reference."""

    def once(self, start, end):
        darray = self.data.array
        larray = self.lines.stddev.array
        period = self.p.period
        actual_end = min(end, len(darray))
        nan_val = float("nan")

        while len(larray) < end:
            larray.append(nan_val)
        for index in range(min(period - 1, len(larray), actual_end)):
            larray[index] = nan_val

        self._once_simple_fsum(
            actual_end,
            darray,
            larray,
            period,
            None,
            nan_val,
            period - 1,
        )


class _CountingProbe(bt.Strategy):
    params = (("indicator_cls", _CountingDeviation), ("period", 64))

    def __init__(self):
        self.deviation = self.p.indicator_cls(self.data.close, period=self.p.period)

    def stop(self):
        self.result = list(self.deviation.stddev.array)
        self.finish_calls = self.deviation.finish_calls


class _MutatingProbe(bt.Strategy):
    params = (("period", 64), ("indicator_cls", _MutatingFinishDeviation))

    def __init__(self):
        self.deviation = self.p.indicator_cls(self.data.close, period=self.p.period)

    def stop(self):
        self.result = list(self.deviation.stddev.array)
        self.finish_calls = self.deviation.finish_calls


class _ReferenceMutatingProbe(bt.Strategy):
    params = (("period", 64), ("indicator_cls", _ReferenceMutatingDeviation))

    def __init__(self):
        self.deviation = self.p.indicator_cls(self.data.close, period=self.p.period)

    def stop(self):
        self.result = list(self.deviation.stddev.array)
        self.finish_calls = self.deviation.finish_calls


class _InstancePatchProbe(bt.Strategy):
    params = (
        ("period", 64),
        ("indicator_cls", bt.indicators.StandardDeviation),
    )

    def __init__(self):
        self.deviation = self.p.indicator_cls(self.data.close, period=self.p.period)
        self.finish_calls = 0
        original_finish = self.deviation._finish

        def patched_finish(meansq, mean):
            self.finish_calls += 1
            result = original_finish(meansq, mean)
            if self.finish_calls == 5:
                self.data.close.array[10] = 999.0
            return result

        self.deviation._finish = patched_finish

    def stop(self):
        self.result = list(self.deviation.stddev.array)


def _run(values, *, period, runonce, probe=_Probe, **probe_params):
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
    cerebro.adddata(_SyntheticValues(input_values=values), name="SYNTH")
    cerebro.addstrategy(probe, period=period, **probe_params)
    (strategy,) = cerebro.run(runonce=runonce, preload=True)
    return strategy


def _run_counting(values, indicator_cls):
    cerebro = bt.Cerebro(stdstats=False, runonce=True, preload=True)
    cerebro.adddata(_SyntheticValues(input_values=values), name="SYNTH")
    cerebro.addstrategy(_CountingProbe, indicator_cls=indicator_cls, period=64)
    (strategy,) = cerebro.run(runonce=True, preload=True)
    return strategy


def _values(count, *, offset=0.0):
    return [
        offset + ((index * 17) % 37 - 18) * 0.125 + (index % 5) * 0.0001
        for index in range(count)
    ]


def _assert_same_float_sequence(actual, expected):
    assert len(actual) == len(expected)
    for index, (actual_value, expected_value) in enumerate(zip(actual, expected)):
        if math.isnan(expected_value):
            assert math.isnan(actual_value), index
        else:
            assert actual_value == expected_value, (index, actual_value, expected_value)


@pytest.mark.parametrize("period", (63, 64, 127, 257))
@pytest.mark.parametrize("offset", (0.0, 1e8), ids=("near-zero", "large-offset"))
def test_simple_stddev_runonce_matches_runnext_exactly(period, offset):
    values = _values(700, offset=offset)

    runnext = _run(values, period=period, runonce=False).result
    runonce = _run(values, period=period, runonce=True).result

    _assert_same_float_sequence(runonce, runnext)


def test_rolling_expansion_keeps_cancellation_windows_bit_exact():
    values = ([1e16, 1.0, -1e16, 1.0] * 50) + _values(300)

    runnext = _run(values, period=64, runonce=False).result
    runonce = _run(values, period=64, runonce=True).result

    _assert_same_float_sequence(runonce, runnext)


@pytest.mark.parametrize("special", (math.nan, math.inf, -math.inf, 1e200))
def test_simple_stddev_unusual_values_keep_the_original_window_fallback(special):
    values = _values(240)
    values[91] = special

    runnext = _run(values, period=64, runonce=False).result
    runonce = _run(values, period=64, runonce=True).result

    _assert_same_float_sequence(runonce, runnext)


def test_late_fallback_does_not_repeat_subclass_finish_side_effects():
    values = _values(160)
    values[91] = math.nan

    actual = _run_counting(values, _CountingDeviation)
    expected = _run_counting(values, _ReferenceCountingDeviation)

    _assert_same_float_sequence(actual.result, expected.result)
    assert actual.finish_calls == expected.finish_calls


def test_subclass_finish_source_mutation_uses_the_original_window_path():
    values = _values(180)

    candidate = _run(values, period=64, runonce=True, probe=_MutatingProbe)
    reference = _run(values, period=64, runonce=True, probe=_ReferenceMutatingProbe)

    _assert_same_float_sequence(candidate.result, reference.result)
    assert candidate.finish_calls == reference.finish_calls


def test_class_level_finish_patch_cannot_requalify_the_rolling_gate(monkeypatch):
    values = _values(180)
    deviation_class = bt.indicators.StandardDeviation
    original_finish = deviation_class._finish
    finish_calls = [0]

    def patched_finish(indicator, meansq, mean):
        result = original_finish(indicator, meansq, mean)
        finish_calls[0] += 1
        if finish_calls[0] == 5:
            indicator.data.array[10] = 999.0
        return result

    monkeypatch.setattr(deviation_class, "_finish", patched_finish)
    candidate = _run(
        values,
        period=64,
        runonce=True,
        indicator_cls=deviation_class,
    )
    candidate_calls = finish_calls[0]

    finish_calls[0] = 0
    reference = _run(
        values,
        period=64,
        runonce=True,
        indicator_cls=_LegacyDeviation,
    )

    _assert_same_float_sequence(candidate.result, reference.result)
    assert candidate_calls == finish_calls[0]


def test_instance_finish_patch_uses_the_original_window_path():
    values = _values(180)

    candidate = _run(
        values,
        period=64,
        runonce=True,
        probe=_InstancePatchProbe,
        indicator_cls=bt.indicators.StandardDeviation,
    )
    reference = _run(
        values,
        period=64,
        runonce=True,
        probe=_InstancePatchProbe,
        indicator_cls=_LegacyDeviation,
    )

    _assert_same_float_sequence(candidate.result, reference.result)
    assert candidate.finish_calls == reference.finish_calls


def test_module_class_replacement_cannot_requalify_a_subclass(
    monkeypatch,
):
    import backtrader.indicators.deviation as deviation_module

    values = _values(180)
    monkeypatch.setattr(
        deviation_module, "StandardDeviation", _MutatingFinishDeviation
    )
    candidate = _run(
        values,
        period=64,
        runonce=True,
        probe=_MutatingProbe,
        indicator_cls=deviation_module.StandardDeviation,
    )
    reference = _run(
        values,
        period=64,
        runonce=True,
        probe=_ReferenceMutatingProbe,
        indicator_cls=_ReferenceMutatingDeviation,
    )

    _assert_same_float_sequence(candidate.result, reference.result)
    assert candidate.finish_calls == reference.finish_calls


def test_finite_square_overflow_matches_the_legacy_once_path():
    values = _values(180)
    values[90] = 1e155

    runnext = _run(values, period=64, runonce=False).result
    runonce = _run(values, period=64, runonce=True).result
    legacy_once = _run_counting(values, _ReferenceCountingDeviation).result

    # This source path already differs by mode at this overflow boundary;
    # the optimization must retain the prior runonce projection exactly.
    assert math.isnan(runnext[90])
    assert math.isinf(runonce[90])
    _assert_same_float_sequence(runonce, legacy_once)


def test_fsum_expansion_remains_exact_while_terms_leave_and_enter():
    values = [
        1e16,
        1.0,
        -1e16,
        0.125,
        -0.125,
        1e-300,
        -1e-300,
        3.0,
        -2.0,
        7.0,
    ] * 4
    period = 7
    partials = []

    for value in values[:period]:
        assert _add_fsum_partial(partials, value)
    assert math.fsum(partials) == math.fsum(values[:period])

    for index in range(period, len(values)):
        assert _add_fsum_partial(partials, -values[index - period])
        assert _add_fsum_partial(partials, values[index])
        window = values[index - period + 1 : index + 1]
        assert math.fsum(partials) == math.fsum(window)


def test_runnext_period_changes_keep_the_existing_window_behavior():
    values = _values(180)
    actual = _run(values, period=64, runonce=False, probe=_DynamicProbe).result
    expected = []

    for index in range(len(values)):
        if index < 63:
            expected.append(float("nan"))
            continue

        period = 32 if 80 <= index < 110 else 64
        window = values[index - period + 1 : index + 1]
        mean = math.fsum(window) / period
        meansq = math.fsum(value * value for value in window) / period
        expected.append(math.sqrt(abs(meansq - mean * mean)))

    _assert_same_float_sequence(actual, expected)


def test_once_repeated_over_segments_matches_one_full_cerebro_pass():
    values = _values(700, offset=1e8)
    expected = _run(values, period=64, runonce=True).result
    strategy = _run(values, period=64, runonce=False)
    split = len(values) // 2

    strategy.deviation.once(0, split)
    strategy.deviation.once(split, len(values))

    _assert_same_float_sequence(
        list(strategy.deviation.stddev.array), expected
    )
