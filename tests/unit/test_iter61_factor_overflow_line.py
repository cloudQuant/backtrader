"""Infinite line reads retain strict and ordinary semantics across factor owners."""

import math
from collections import deque
from types import SimpleNamespace
import weakref

import pytest

from backtrader.errors import FactorComputationContext, FactorComputationError
from backtrader.linebuffer import LineBuffer


class BoundFactor:
    _factor_bound = True


class Owner:
    pass


def _line(owner, value):
    line = LineBuffer()
    line._owner = owner
    line.forward(size=2)
    # ``once`` implementations may write raw values without ``__setitem__``.
    line.array[0] = value
    line.array[1] = value
    return line


def _set_buffer_mode(line, useislice):
    if useislice:
        line.array = deque(line.array, maxlen=2)
    line.useislice = useislice


@pytest.mark.parametrize("value", (float("inf"), float("-inf")))
@pytest.mark.parametrize("ago", (0, -1))
def test_factor_owned_infinity_reads_as_missing(value, ago):
    factor = BoundFactor()
    indicator = Owner()
    indicator._owner = factor
    line = _line(indicator, value)
    assert math.isnan(line[ago])
    assert line.array[line._idx + ago] == value


@pytest.mark.parametrize("value", (float("inf"), float("-inf")))
@pytest.mark.parametrize("ago", (0, -1))
def test_ordinary_infinity_retains_legacy_zero(value, ago):
    line = _line(Owner(), value)
    assert line[ago] == 0.0


def test_factor_owned_infinity_resolves_owner_ref_proxy():
    factor = BoundFactor()
    indicator = Owner()
    indicator._owner = SimpleNamespace(_owner_ref=weakref.proxy(factor))
    line = _line(indicator, float("inf"))
    assert math.isnan(line[0])


def test_cycles_and_expired_owner_references_are_bounded():
    owner = Owner()
    owner._owner = owner
    assert _line(owner, float("inf"))[0] == 0.0

    owner = Owner()
    proxy = weakref.proxy(owner)
    line = _line(proxy, float("inf"))
    del owner
    assert line[0] == 0.0


def test_strict_factor_still_rejects_infinite_read():
    factor = BoundFactor()
    factor._factor_strict_context = FactorComputationContext("overflow", phase="next")
    line = _line(factor, float("inf"))
    with pytest.raises(FactorComputationError) as caught:
        _ = line[0]
    assert caught.value.factor == "overflow"
    assert isinstance(caught.value.__cause__, ArithmeticError)


@pytest.mark.parametrize("value", (float("inf"), float("-inf")))
@pytest.mark.parametrize("useislice", (False, True), ids=("array", "islice"))
@pytest.mark.parametrize("method", ("get", "getzero", "getzeroval"))
def test_all_window_readers_preserve_factor_missing(value, useislice, method):
    factor = BoundFactor()
    indicator = Owner()
    indicator._owner = factor
    line = _line(indicator, value)
    _set_buffer_mode(line, useislice)
    if method == "get":
        result = line.get(size=2)
    elif method == "getzero":
        result = line.getzero(size=2)
    else:
        result = (line.getzeroval(0),)
    assert len(result) == (1 if method == "getzeroval" else 2)
    assert all(math.isnan(v) for v in result)
    assert len(line.array) == 2
    assert all(v == value for v in line.array)


@pytest.mark.parametrize("useislice", (False, True), ids=("array", "islice"))
@pytest.mark.parametrize("method", ("get", "getzero", "getzeroval"))
def test_window_readers_preserve_ordinary_and_strict_behavior(useislice, method):
    ordinary = _line(Owner(), float("inf"))
    _set_buffer_mode(ordinary, useislice)
    factor = BoundFactor()
    factor._factor_strict_context = FactorComputationContext("overflow", phase="next")
    strict = _line(factor, float("inf"))
    _set_buffer_mode(strict, useislice)

    def read(line):
        if method == "get":
            return tuple(line.get(size=2))
        if method == "getzero":
            return tuple(line.getzero(size=2))
        return (line.getzeroval(0),)

    result = read(ordinary)
    assert len(result) == (1 if method == "getzeroval" else 2)
    assert all(value == 0.0 for value in result)
    with pytest.raises(FactorComputationError) as caught:
        read(strict)
    assert caught.value.factor == "overflow"
    assert isinstance(caught.value.__cause__, ArithmeticError)


def test_nested_factor_sma_window_does_not_turn_infinity_into_zero():
    import backtrader as bt
    import pandas as pd

    from backtrader.research import FactorIndicator

    class RawSource(bt.Indicator):
        lines = ("raw",)

        def next(self):
            index = len(self) - 1
            # Simulate an upstream once implementation's raw array overflow.
            self.lines.raw.array[self.lines.raw._idx] = (
                float("inf") if index == 2 else float(self.data[0])
            )

    class WindowFactor(FactorIndicator):
        lines = ("factor",)
        formula_fields = ("close",)

        @classmethod
        def lookback_h(cls):
            return 1

        def __init__(self):
            super().__init__()
            self.raw = RawSource(self.data)
            self.mean = bt.indicators.SMA(self.raw, period=2)

        def next(self):
            self.outputs[self.data].factor[0] = self.mean[0]

    class Driver(bt.Strategy):
        def __init__(self):
            self.factor = WindowFactor._bind_for_research(
                *self.datas,
                output_datas=self.datas,
                asset_names=("A",),
                factor_name="window",
                field_bindings={"close": "feed:target:close"},
                research=None,
                available_datas=self.datas,
                strict=False,
                mode="native",
            )

    index = pd.date_range("2025-01-01", periods=6, freq="D")
    frame = pd.DataFrame({"close": [100.0] * 6}, index=index)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name="A")
    cerebro.addstrategy(Driver)
    strategy = cerebro.run(runonce=False, preload=True)[0]
    result = list(strategy.factor.outputs[strategy.data].factor.array)
    assert result[1] == 100.0
    assert math.isnan(result[2]) and math.isnan(result[3])
    assert result[4:] == [100.0, 100.0]
