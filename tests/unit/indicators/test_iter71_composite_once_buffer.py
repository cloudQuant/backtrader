"""Runonce buffer regression coverage for default composite indicators."""

from datetime import datetime, timedelta
import math

import backtrader as bt
import pandas as pd
import pytest
from backtrader.indicator import Indicator
from backtrader.lineiterator import LineIterator


_BAR_COUNT = 160
_PERIOD = 14
_CLOSES = tuple(
    100.0 + index * 0.17 + math.sin(index * 0.23) for index in range(_BAR_COUNT)
)


class _IndicatorProbe(bt.Strategy):
    params = (("indicator_cls", None), ("indicator_kwargs", None))

    def __init__(self):
        self.indicator = self.p.indicator_cls(
            self.data, **(self.p.indicator_kwargs or {})
        )


def _frame(closes=_CLOSES):
    start = datetime(2025, 1, 1)
    return pd.DataFrame(
        {
            "open": [close - 0.2 for close in closes],
            "high": [close + 1.0 + (index % 3) * 0.1 for index, close in enumerate(closes)],
            "low": [close - 1.0 - (index % 2) * 0.1 for index, close in enumerate(closes)],
            "close": closes,
            "volume": [100.0 + index for index in range(len(closes))],
            "openinterest": [0.0] * len(closes),
        },
        index=pd.DatetimeIndex(
            [start + timedelta(days=index) for index in range(len(closes))]
        ),
    )


def _run(indicator_cls, runonce, closes=_CLOSES, indicator_kwargs=None):
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(closes)))
    cerebro.addstrategy(
        _IndicatorProbe,
        indicator_cls=indicator_cls,
        indicator_kwargs=indicator_kwargs,
    )
    return cerebro.run(runonce=runonce, preload=True)[0]


def _line_values(indicator):
    return [list(line.array) for line in indicator.lines]


def _assert_values_match(actual, expected):
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected):
        if math.isnan(expected_value):
            assert math.isnan(actual_value)
        else:
            assert actual_value == pytest.approx(expected_value, rel=1e-11, abs=1e-11)


def _sma(values, period):
    result = [float("nan")] * len(values)
    for end in range(period - 1, len(values)):
        window = values[end - period + 1 : end + 1]
        if all(math.isfinite(value) for value in window):
            result[end] = math.fsum(window) / period
    return result


def _mean_deviation_reference(values, period):
    mean = _sma(values, period)
    absdev = [
        abs(value - average) if math.isfinite(average) else float("nan")
        for value, average in zip(values, mean)
    ]
    return _sma(absdev, period)


def _cci_reference(frame, period, factor=0.015):
    typical = [
        (high + low + close) / 3.0
        for high, low, close in zip(frame.high, frame.low, frame.close)
    ]
    mean = _sma(typical, period)
    absdev = [
        abs(value - average) if math.isfinite(average) else float("nan")
        for value, average in zip(typical, mean)
    ]
    mean_deviation = _sma(absdev, period)

    result = []
    for value, average, deviation in zip(typical, mean, mean_deviation):
        if not math.isfinite(average) or not math.isfinite(deviation) or deviation == 0.0:
            result.append(float("nan"))
        else:
            result.append((value - average) / (factor * deviation))
    return result


def _indicator_tree_lines(indicator):
    seen_objects = set()
    seen_lines = set()
    stack = [indicator]
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen_objects:
            continue
        seen_objects.add(id(current))

        try:
            for line in current.lines:
                if id(line) not in seen_lines:
                    seen_lines.add(id(line))
                    yield current, line
        except (AttributeError, TypeError):
            pass

        for group in getattr(current, "_lineiterators", {}).values():
            stack.extend(group)


@pytest.mark.parametrize(
    "indicator_cls, indicator_kwargs, expected_minperiod",
    (
        (bt.indicators.MeanDeviation, {"period": _PERIOD}, 2 * _PERIOD - 1),
        (bt.indicators.CCI, {"period": _PERIOD}, 2 * _PERIOD - 1),
        (bt.indicators.TypicalPrice, {}, 1),
        (bt.indicators.DonchianChannelIndicator, {}, 20),
    ),
    ids=("mean-deviation", "cci", "line-operation", "inherited-multiline"),
)
def test_default_composite_runonce_buffers_match_data_domain(
    indicator_cls, indicator_kwargs, expected_minperiod
):
    """Default no-op next wrappers must not append after child lines are filled."""
    runnext = _run(indicator_cls, runonce=False, indicator_kwargs=indicator_kwargs)
    runonce = _run(indicator_cls, runonce=True, indicator_kwargs=indicator_kwargs)

    assert runnext.indicator._minperiod == expected_minperiod
    assert runonce.indicator._minperiod == expected_minperiod

    next_values = _line_values(runnext.indicator)
    once_values = _line_values(runonce.indicator)
    assert len(once_values) == len(next_values)
    assert len(once_values) > 0
    for actual, expected in zip(once_values, next_values):
        assert len(actual) == len(expected) == _BAR_COUNT
        _assert_values_match(actual, expected)

    for _, line in _indicator_tree_lines(runonce.indicator):
        assert len(line.array) == _BAR_COUNT

    assert any(math.isfinite(value) for values in once_values for value in values)

    frame = _frame()
    if indicator_cls is bt.indicators.MeanDeviation:
        _assert_values_match(
            once_values[0], _mean_deviation_reference(_CLOSES, _PERIOD)
        )
    elif indicator_cls is bt.indicators.CCI:
        _assert_values_match(once_values[0], _cci_reference(frame, _PERIOD))
    elif indicator_cls is bt.indicators.TypicalPrice:
        expected = [
            (high + low + close) / 3.0
            for high, low, close in zip(frame.high, frame.low, frame.close)
        ]
        _assert_values_match(once_values[0], expected)


@pytest.mark.parametrize(
    "indicator_cls",
    (bt.indicators.MeanDeviation, bt.indicators.CCI),
    ids=("mean-deviation", "cci"),
)
def test_default_composite_short_history_stays_undefined(indicator_cls):
    """Runonce retains short warm-up NaNs and does not grow a partial buffer."""
    kwargs = {"period": _PERIOD}
    closes = _CLOSES[: 2 * _PERIOD - 2]
    runnext = _run(indicator_cls, runonce=False, closes=closes, indicator_kwargs=kwargs)
    runonce = _run(indicator_cls, runonce=True, closes=closes, indicator_kwargs=kwargs)

    assert runonce.indicator._minperiod == runnext.indicator._minperiod == 2 * _PERIOD - 1
    assert len(runonce.indicator.lines[0].array) == len(closes)
    assert len(runnext.indicator.lines[0].array) == len(closes)
    assert all(math.isnan(value) for value in runonce.indicator.lines[0].array)
    assert all(math.isnan(value) for value in runnext.indicator.lines[0].array)


class _PureBoundBase(Indicator):
    lines = ("value",)

    def __init__(self):
        self.lifecycle_events = []
        self.next_calls = 0
        self.lines.value = self.data.close * 2.0
        self.addminperiod(3)


class _PureBoundDerived(_PureBoundBase):
    pass


class _StaticNextDerived(_PureBoundBase):
    def next(self):
        self.next_calls += 1
        self.lines.value[0] = float(self.data.close[0]) * 3.0


class _NextWriterMixin:
    def next(self):
        self.next_calls += 1
        self.lines.value[0] = float(self.data.close[0]) * 4.0


class _MixinNextDerived(_NextWriterMixin, _PureBoundBase):
    pass


class _DynamicNextDerived(_PureBoundBase):
    pass


def _dynamic_next(self):
    self.next_calls += 1
    self.lines.value[0] = -123.0


# Deliberately change the method after Indicator.__init_subclass__ has run.
_DynamicNextDerived.next = _dynamic_next


def _type_created_next(self):
    self.next_calls += 1
    self.lines.value[0] = float(self.data.close[0]) * 5.0


# This dynamic subclass includes next during class creation, so the framework
# dispatch hook can select once_via_next as it does for a normally declared subclass.
_TypeCreatedNextDerived = type(
    "_TypeCreatedNextDerived", (_PureBoundBase,), {"next": _type_created_next}
)


@pytest.mark.parametrize(
    "indicator_cls, scale",
    (
        (_PureBoundDerived, 2.0),
        (_StaticNextDerived, 3.0),
        (_MixinNextDerived, 4.0),
        (_TypeCreatedNextDerived, 5.0),
    ),
    ids=("inherited-binding", "custom-next", "mixin-next", "dynamic-subclass-next"),
)
def test_once_dispatch_preserves_bound_and_custom_next_calculation(indicator_cls, scale):
    """The no-op guard preserves bindings and still executes late/custom next methods."""
    runnext = _run(indicator_cls, runonce=False)
    runonce = _run(indicator_cls, runonce=True)
    expected = [
        value * 2.0 if index < 2 else value * scale
        for index, value in enumerate(_CLOSES)
    ]

    next_values = runnext.indicator.lines.value.array
    once_values = runonce.indicator.lines.value.array
    assert len(next_values) == len(once_values) == _BAR_COUNT
    _assert_values_match(list(next_values), expected)
    _assert_values_match(list(once_values), expected)
    if scale != 2.0:
        assert runonce.indicator.next_calls == _BAR_COUNT - 2


def test_runtime_next_change_is_not_mistaken_for_default_noop():
    """A post-hook monkeypatch retains the old generic-once behavior and is unsupported."""
    strategy = _run(_DynamicNextDerived, runonce=True)

    assert strategy.indicator.next_calls == _BAR_COUNT - 2
    assert len(strategy.indicator.lines.value.array) == (
        2 * _BAR_COUNT - (strategy.indicator._minperiod - 1)
    )
    assert -123.0 in strategy.indicator.lines.value.array


class _CustomVectorOnce(Indicator):
    lines = ("value",)

    def __init__(self):
        self.once_segments = []
        self.addminperiod(3)

    def once(self, start, end):
        self.once_segments.append((start, end))
        source = self.data.close.array
        output = self.lines.value.array
        for index in range(start, end):
            output[index] = float(source[index]) * 6.0


def test_explicit_vectorized_once_is_not_replaced_by_the_noop_guard():
    strategy = _run(_CustomVectorOnce, runonce=True)
    values = list(strategy.indicator.lines.value.array)

    assert strategy.indicator._minperiod == 3
    assert len(values) == _BAR_COUNT
    assert strategy.indicator.once_segments == [(2, 3), (3, _BAR_COUNT)]
    assert all(math.isnan(value) for value in values[:2])
    _assert_values_match(values[2:], [value * 6.0 for value in _CLOSES[2:]])


def _lifecycle_composite(hook_name):
    indicator_cls = type(f"_Lifecycle{hook_name.title()}", (_PureBoundBase,), {})

    def hook(self, *args):
        self.lifecycle_events.append(hook_name)
        if hook_name == "oncestart":
            return LineIterator.oncestart(self, *args)

    setattr(indicator_cls, hook_name, hook)
    return indicator_cls


@pytest.mark.parametrize("hook_name", ("preonce", "oncestart", "prenext", "nextstart"))
def test_runtime_lifecycle_override_is_not_mistaken_for_default_composite(hook_name):
    """Any custom lifecycle identity opts out of the pure-wrapper no-op guard."""
    indicator_cls = _lifecycle_composite(hook_name)
    strategy = _run(indicator_cls, runonce=True)
    values = list(strategy.indicator.lines.value.array)

    assert len(values) == 2 * _BAR_COUNT - (strategy.indicator._minperiod - 1)
    _assert_values_match(values[:_BAR_COUNT], [value * 2.0 for value in _CLOSES])
    if hook_name in ("preonce", "oncestart"):
        assert hook_name in strategy.indicator.lifecycle_events


@pytest.mark.parametrize("hook_name", ("prenext", "nextstart"))
def test_custom_prenext_and_nextstart_remain_available_in_runnext(hook_name):
    indicator_cls = _lifecycle_composite(hook_name)
    strategy = _run(indicator_cls, runonce=False)

    assert hook_name in strategy.indicator.lifecycle_events
    _assert_values_match(
        list(strategy.indicator.lines.value.array), [value * 2.0 for value in _CLOSES]
    )
