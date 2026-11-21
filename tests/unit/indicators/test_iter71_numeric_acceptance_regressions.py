"""Regression checks against the pre-optimization window contracts."""

import datetime as dt
from array import array
import math

import backtrader as bt
import backtrader.indicators.basicops as basicops
import backtrader.indicators.sma as sma
import pytest


class _Feed(bt.feed.DataBase):
    params = (("input_values", ()),)

    def __init__(self):
        super().__init__()
        self.index = 0

    def _load(self):
        if self.index == len(self.p.input_values):
            return False
        value = self.p.input_values[self.index]
        self.datetime[0] = bt.date2num(dt.datetime(2026, 1, 1) + dt.timedelta(minutes=self.index))
        self.open[0] = self.high[0] = self.low[0] = self.close[0] = value
        self.volume[0] = 1.0
        self.openinterest[0] = 0.0
        self.index += 1
        return True


class _Probe(bt.Strategy):
    params = (("indicator", None), ("period", 32))

    def __init__(self):
        self.indicator = self.p.indicator(self.data.close, period=self.p.period)


def _indicator(indicator, period, count=120):
    engine = bt.Cerebro(stdstats=False, runonce=False, preload=True)
    engine.adddata(_Feed(input_values=[float((i * 17) % 37) for i in range(count)]))
    engine.addstrategy(_Probe, indicator=indicator, period=period)
    return engine.run()[0].indicator


@pytest.mark.parametrize("period", [16, 32])
def test_sma_nan_check_precedes_overflow_for_each_window(period):
    indicator = _indicator(bt.indicators.SMA, period)
    src, dst = indicator.data.array, indicator.lines[0].array
    src[0], src[1], src[2] = 1e308, 1e308, math.nan
    for i in range(len(dst)):
        dst[i] = -12345.0

    indicator.once(period - 1, period + 4)

    # HEAD checks for NaN before calling fsum, even when earlier finite
    # elements would overflow fsum. Recovery begins when the NaN leaves.
    for i in range(period - 1, period + 2):
        assert math.isnan(dst[i])
    for i in range(period + 2, period + 4):
        assert dst[i] == math.fsum(src[i - period + 1 : i + 1]) / period
    assert dst[period + 4] == -12345.0


def test_stddev_partial_once_recomputes_same_prefix_as_head():
    period = 32
    indicator = _indicator(bt.indicators.StandardDeviation, period)
    src, dst = indicator.data.array, indicator.lines[0].array
    for i in range(len(dst)):
        dst[i] = -12345.0

    indicator.once(70, 100)

    for i in range(period - 1, 100):
        window = src[i - period + 1 : i + 1]
        mean = math.fsum(window) / period
        meansq = math.fsum(v * v for v in window) / period
        assert dst[i] == math.sqrt(abs(meansq - mean * mean))
    assert dst[100] == -12345.0


@pytest.mark.parametrize(
    "indicator_type,module,threshold",
    [
        (bt.indicators.SumN, basicops, "_MIN_PERIOD_FOR_SUM_ONCE"),
        (bt.indicators.SMA, sma, "_MIN_PERIOD_FOR_ROLLING_ONCE"),
    ],
)
def test_ordered_fsum_overflow_preserves_once_fallback(
    monkeypatch, indicator_type, module, threshold
):
    calls = []
    original = bt.Indicator.once_via_next

    def observed_fallback(self, start, end):
        calls.append((start, end))
        return original(self, start, end)

    monkeypatch.setattr(bt.Indicator, "once_via_next", observed_fallback)
    initial_threshold = getattr(module, threshold)
    outcomes = []
    for use_original_window in (False, True):
        monkeypatch.setattr(module, threshold, 1_000_000 if use_original_window else initial_threshold)
        indicator = _indicator(indicator_type, 32)
        src, dst = indicator.data.array, indicator.lines[0].array
        values = [-1e308, 1e308, 1e308, -1e308] + [0.0] * 28 + [-1e308]
        for index, value in enumerate(values):
            src[index] = value
        for index in range(31, 36):
            dst[index] = -12345.0
        assert math.fsum(src[:32]) == 0.0
        with pytest.raises(OverflowError):
            math.fsum(src[1:33])
        previous_calls = len(calls)
        indicator.once(31, 36)
        assert calls[previous_calls:] == [(31, 36)]
        outcomes.append(list(dst[31:36]))
    assert outcomes[0] == outcomes[1]


@pytest.mark.parametrize("period,expected,conversions", [(20, 0.5, 0), (64, 0.0, 136)])
def test_stddev_nonstandard_storage_keeps_head_conversion_order(period, expected, conversions):
    class Value(float):
        count = 0

        def __float__(self):
            Value.count += 1
            return 100.0

    indicator = _indicator(bt.indicators.StandardDeviation, period, count=100)
    indicator.data.array = [Value(i % 2 + 1) for i in range(100)]
    indicator.once(0, 100)
    assert indicator.lines[0].array[period - 1] == expected
    assert Value.count == conversions


def test_stddev_general_path_does_not_call_overridden_rolling_fallback():
    class CustomDeviation(bt.ind.StandardDeviation):
        def _once_simple_fsum(self, *args):
            raise AssertionError("HEAD's general path does not dispatch this hook")

    indicator = _indicator(CustomDeviation, 20, count=100)
    indicator.once(0, 100)
    window = indicator.data.array[:20]
    mean = math.fsum(window) / 20
    expected = math.sqrt(abs(math.fsum(v * v for v in window) / 20 - mean * mean))
    assert indicator.lines[0].array[19] == expected


def test_stddev_preserves_period_comparison_exception():
    class RaisingPeriod(int):
        def __ge__(self, other):
            raise RuntimeError("period comparison")

    indicator = _indicator(bt.ind.StandardDeviation, 20, count=100)
    indicator.p.period = RaisingPeriod(20)
    with pytest.raises(RuntimeError, match="period comparison"):
        indicator.once(0, 100)


@pytest.mark.parametrize("period", [20, 64])
def test_stddev_end_int_subclass_does_not_gain_subtraction(period):
    class End(int):
        def __sub__(self, other):
            raise RuntimeError("end subtraction must not be called")

    indicator = _indicator(bt.ind.StandardDeviation, period, count=100)
    indicator.once(0, End(70))
    window = indicator.data.array[70 - period : 70]
    mean = math.fsum(window) / period
    expected = math.sqrt(abs(math.fsum(v * v for v in window) / period - mean * mean))
    assert indicator.lines[0].array[69] == expected


@pytest.mark.parametrize("raise_after", [None, 5])
def test_stddev_reads_safepow_for_each_window(raise_after):
    class Parameters:
        def __init__(self, original):
            self.original = original
            self.reads = 0

        def __getattr__(self, name):
            return getattr(self.original, name)

        @property
        def safepow(self):
            self.reads += 1
            if raise_after is not None and self.reads > raise_after:
                raise RuntimeError("safepow getter failed")
            return self.reads % 2 == 0

    indicator = _indicator(bt.ind.StandardDeviation, 20, count=100)
    params = Parameters(indicator.p)
    indicator.p = params
    if raise_after is None:
        indicator.once(0, 100)
        assert params.reads == 81
    else:
        with pytest.raises(RuntimeError, match="safepow getter failed"):
            indicator.once(0, 100)
        assert params.reads == raise_after + 1


@pytest.mark.parametrize("custom_accessor", [True, False])
def test_stddev_safepow_callback_can_modify_later_window(custom_accessor):
    indicator = _indicator(bt.ind.StandardDeviation, 20, count=100)
    source = indicator.data.array
    if custom_accessor:
        class Parameters:
            def __init__(self, original):
                self.original = original
                self.reads = 0

            def __getattr__(self, name):
                return getattr(self.original, name)

            @property
            def safepow(self):
                self.reads += 1
                if self.reads == 1:
                    source[1] = 1000.0
                return True

        indicator.p = Parameters(indicator.p)
    else:
        manager = object.__getattribute__(indicator.p, "_param_manager")
        original_get = manager.get
        reads = []

        def get(name, *args, **kwargs):
            if name == "safepow":
                reads.append(None)
                if len(reads) == 1:
                    source[1] = 1000.0
            return original_get(name, *args, **kwargs)

        manager.get = get

    indicator.once(0, 100)
    assert indicator.lines[0].array[20] == 213.93771874075875


def test_stddev_dynamic_p_descriptor_uses_original_window_calculation(monkeypatch):
    indicator = _indicator(bt.ind.StandardDeviation, 20, count=100)
    source = indicator.data.array

    class Parameters:
        def __init__(self, original):
            self.original = original
            self.reads = 0

        def __getattr__(self, name):
            return getattr(self.original, name)

        @property
        def safepow(self):
            self.reads += 1
            if self.reads == 1:
                source[1] = 1000.0
            return True

    params = Parameters(indicator.p)
    monkeypatch.setattr(bt.ind.StandardDeviation, "p", property(lambda _self: params))
    indicator.once(0, 100)
    assert indicator.lines[0].array[20] == 213.93771874075875


def test_stddev_parameter_manager_descriptor_is_not_read_by_fast_path_guard(monkeypatch):
    from backtrader.parameters import ParameterAccessor

    indicator = _indicator(bt.ind.StandardDeviation, 20, count=100)
    source = indicator.data.array
    reads = []

    def manager_property(params):
        reads.append(None)
        if len(reads) == 3:
            source[1] = 1000.0
        return object.__getattribute__(params, "__dict__")["_param_manager"]

    monkeypatch.setattr(ParameterAccessor, "_param_manager", property(manager_property), raising=False)
    indicator.once(0, 100)
    assert len(reads) == 83
    assert indicator.lines[0].array[20] == 213.93771874075875


def test_stddev_guard_does_not_compare_user_instance_dictionary_keys():
    indicator = _indicator(bt.ind.StandardDeviation, 20, count=100)
    source = indicator.data.array
    manager = object.__getattribute__(indicator.p, "_param_manager")
    state = object.__getattribute__(manager, "__dict__")
    original = state.copy()
    comparisons = []

    class Collision:
        def __hash__(self):
            return hash("_lazy_defaults")

        def __eq__(self, other):
            comparisons.append(other)
            source[1] = 1000.0
            return False

    state.clear()
    state[Collision()] = None
    state.update(original)
    comparisons.clear()
    source[1] = 17.0
    indicator.once(0, 100)
    assert comparisons == []
    assert indicator.lines[0].array[19] == 10.841932484571187


@pytest.mark.parametrize(
    "indicator_type,initial,first,expected",
    [
        (bt.ind.SumN, 1.0, 1.0, [32.0, 63.0, 125.0, 249.0, 497.0]),
        (bt.ind.AnyN, 0.0, 1.0, [1.0] * 5),
        (bt.ind.AllN, 1.0, 0.0, [0.0] * 5),
    ],
)
def test_rolling_operations_preserve_aliased_source_write_order(
    indicator_type, initial, first, expected
):
    indicator = _indicator(indicator_type, 32, count=100)
    source = indicator.data.array
    for index in range(len(source)):
        source[index] = initial
    source[0] = first
    indicator.lines[0].array = source
    indicator.once(31, 36)
    assert list(source[31:36]) == expected


def test_sma_preserves_aliased_source_write_order_for_late_segment():
    indicator = _indicator(bt.ind.SMA, 32, count=100)
    source = indicator.data.array
    for index in range(len(source)):
        source[index] = float(index)
    indicator.lines[0].array = source
    indicator.once(63, 70)
    # Actual HEAD once(), including its warmup writes and in-place windows.
    assert list(source[63:70]) == [
        47.5,
        48.015625,
        48.51611328125,
        49.00099182128906,
        49.469772815704346,
        49.92195321619511,
        50.357014254201204,
    ]


def test_sma_short_destination_keeps_head_fallback(monkeypatch):
    indicator = _indicator(bt.ind.SMA, 32, count=100)
    indicator.lines[0].array = array("d", [0.0])
    calls = []

    def fallback(_indicator, start, end):
        calls.append((start, end))

    monkeypatch.setattr(bt.Indicator, "once_via_next", fallback)
    indicator.once(0, 1)
    assert calls == [(0, 1)]
