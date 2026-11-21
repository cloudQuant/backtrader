import builtins
import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.errors import FactorComputationError
from backtrader import linebuffer
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.specs import FactorSpec
from backtrader.strategies.factor_strategy import FactorStrategy
from tests.unit.test_factor_research_representatives import _frames, _research_feed, _research_spec


@pytest.mark.parametrize("period", [3, 37])
@pytest.mark.parametrize("runonce,exactbars", [(False, 0), (True, 0), (False, 1)])
def test_public_feed_projected_window_oracle(period, runonce, exactbars):
    values = [float(i % 5 + 1) for i in range(100)]
    values[46], values[55], values[65], values[66] = math.inf, -math.inf, math.nan, -0.0
    frame = pd.DataFrame(
        {name: [1.0] * 100 for name in ("open", "high", "low", "close", "volume")},
        index=pd.date_range("2024-01-01", periods=100, freq="min"),
    )

    class RawFeed(bt.feeds.PandasData):
        def _load(self):
            ok = super()._load()
            if ok:
                self.close.array[self.close.idx] = values[len(self) - 1]
            return ok

    class Driver(bt.Strategy):
        def __init__(self):
            self.high = bt.ind.Highest(self.data.close, period=period)
            self.low = bt.ind.Lowest(self.data.close, period=period)
            self.rows = []

        def next(self):
            self.rows.append((len(self.data), self.high[0], self.low[0]))

    c = bt.Cerebro(stdstats=False, runonce=runonce, exactbars=exactbars)
    c.adddata(RawFeed(dataname=frame))
    c.addstrategy(Driver)
    rows = c.run(preload=True)[0].rows
    assert rows
    projected = [0.0 if math.isinf(v) else v for v in values]
    for index, high, low in rows:
        window = projected[index - period : index]
        for actual, expected in ((high, max(window)), (low, min(window))):
            if math.isnan(expected):
                assert math.isnan(actual)
            else:
                assert actual == expected
                if actual == 0:
                    assert math.copysign(1.0, actual) == math.copysign(1.0, expected)


def test_replay_actual_current_window():
    frame = pd.DataFrame(
        {
            name: [float(i % 7 + 1) for i in range(100)]
            for name in ("open", "high", "low", "close", "volume")
        },
        index=pd.date_range("2024-01-01", periods=100, freq="min"),
    )

    class RawFeed(bt.feeds.PandasData):
        def _load(self):
            ok = super()._load()
            if ok and len(self) in (22, 43):
                self.close.array[self.close.idx] = math.inf if len(self) == 22 else -math.inf
            return ok

    class Driver(bt.Strategy):
        def __init__(self):
            self.high = bt.ind.Highest(self.data.close, period=3)
            self.low = bt.ind.Lowest(self.data.close, period=3)
            self.rows = []

        def next(self):
            window = list(self.data.close.get(size=3))
            self.rows.append((window, self.high[0], self.low[0]))

    c = bt.Cerebro(stdstats=False)
    c.replaydata(
        RawFeed(dataname=frame, timeframe=bt.TimeFrame.Minutes),
        timeframe=bt.TimeFrame.Minutes,
        compression=3,
    )
    c.addstrategy(Driver)
    rows = c.run()[0].rows
    assert len(rows) > 60
    for window, high, low in rows:
        assert high == max(window)
        assert low == min(window)


def test_unrelated_output_error_keeps_original_fallback(monkeypatch):
    frame = pd.DataFrame(
        {name: [1.0] * 100 for name in ("open", "high", "low", "close", "volume")},
        index=pd.date_range("2024-01-01", periods=100, freq="min"),
    )

    class Driver(bt.Strategy):
        def __init__(self):
            self.indicator = bt.ind.Highest(self.data.close, period=32)

    c = bt.Cerebro(stdstats=False, runonce=False)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Driver)
    indicator = c.run(preload=True)[0].indicator
    indicator.data.array[95] = math.inf

    class FailingOutput(list):
        def __setitem__(self, index, value):
            raise FactorComputationError("output failure", factor="test", asset=None, phase="once")

    indicator.lines[0].array = FailingOutput([0.0] * 100)
    calls = []
    monkeypatch.setattr(
        bt.Indicator, "once_via_next", lambda self, start, end: calls.append((start, end))
    )
    indicator.once(31, 36)
    assert calls == [(31, 36)]


def test_inf_window_has_no_new_runtime_import_dependency(monkeypatch):
    frame = pd.DataFrame(
        {name: [1.0] * 10 for name in ("open", "high", "low", "close", "volume")},
        index=pd.date_range("2024-01-01", periods=10, freq="min"),
    )

    class Driver(bt.Strategy):
        def __init__(self):
            self.indicator = bt.ind.Highest(self.data.close, period=3)

    c = bt.Cerebro(stdstats=False, runonce=False)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Driver)
    indicator = c.run(preload=True)[0].indicator
    indicator.data.array[1] = math.inf
    original_import = builtins.__import__
    fallback = []

    def restricted(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 2 and name in ("errors", "linebuffer"):
            raise ImportError("relative import is denied")
        return original_import(name, globals, locals, fromlist, level)

    with monkeypatch.context() as context:
        context.setattr(builtins, "__import__", restricted)
        context.setattr(
            bt.Indicator, "once_via_next", lambda self, start, end: fallback.append((start, end))
        )
        indicator.once(2, 8)
    assert fallback == []
    assert list(indicator.lines[0].array[2:8]) == [1.0] * 6


def test_inf_window_does_not_call_getzero_override():
    frame = pd.DataFrame(
        {name: [1.0] * 12 for name in ("open", "high", "low", "close", "volume")},
        index=pd.date_range("2024-01-01", periods=12, freq="min"),
    )

    class Feed(bt.feeds.PandasData):
        def _load(self):
            ok = super()._load()
            if ok and len(self) == 6:
                self.close.array[self.close.idx] = math.inf
            return ok

    class Driver(bt.Strategy):
        def __init__(self):
            source = self.data.close
            original = source.getzero
            self.calls = []

            def getzero(idx=0, size=1):
                self.calls.append((idx, size))
                values = original(idx=idx, size=size)
                for i, value in enumerate(values):
                    if value == 0.0:
                        values[i] = 42.0
                return values

            source.getzero = getzero
            self.high = bt.ind.Highest(source, period=3)
            self.rows = []

        def next(self):
            if 6 <= len(self.data) <= 8:
                self.rows.append(self.high[0])

    for once in (False, True):
        c = bt.Cerebro(stdstats=False, runonce=once)
        c.adddata(Feed(dataname=frame))
        c.addstrategy(Driver)
        strategy = c.run(preload=True)[0]
        assert strategy.rows == [1.0, 1.0, 1.0]
        assert strategy.calls == []


def test_projection_error_propagates_instead_of_fallback(monkeypatch):
    frame = pd.DataFrame(
        {name: [1.0] * 10 for name in ("open", "high", "low", "close", "volume")},
        index=pd.date_range("2024-01-01", periods=10, freq="min"),
    )

    class Driver(bt.Strategy):
        def __init__(self):
            self.indicator = bt.ind.Highest(self.data.close, period=3)

    c = bt.Cerebro(stdstats=False, runonce=False)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Driver)
    indicator = c.run(preload=True)[0].indicator
    indicator.data.array[1] = math.inf
    calls = []

    source_line = indicator.data.lines[0]

    def context_getter(line):
        if line is source_line:
            raise ValueError("projection failure")

    monkeypatch.setattr(
        linebuffer.LineBuffer, "_factor_strict_context", property(context_getter), raising=False
    )
    monkeypatch.setattr(
        bt.Indicator, "once_via_next", lambda self, start, end: calls.append((start, end))
    )
    with pytest.raises(ValueError, match="projection failure"):
        indicator.once(2, 8)
    assert calls == []


def test_projected_windows_reobserve_mutated_source(monkeypatch):
    frame = pd.DataFrame(
        {name: [1.0] * 12 for name in ("open", "high", "low", "close", "volume")},
        index=pd.date_range("2024-01-01", periods=12, freq="min"),
    )

    class Feed(bt.feeds.PandasData):
        def _load(self):
            ok = super()._load()
            if ok and len(self) == 6:
                self.close.array[self.close.idx] = math.inf
            return ok

    class Driver(bt.Strategy):
        def __init__(self):
            self.node = bt.ind.Lowest(self.data.close, period=3)
            self.rows = []

        def next(self):
            self.rows.append(self.node[0])

    original = linebuffer._read_infinite_line
    outputs = []
    for once in (False, True):
        seen = []

        def read(line, value, seen=seen):
            seen.append(value)
            if len(seen) == 1:
                line.array[8] = -math.inf
            return original(line, value)

        monkeypatch.setattr(linebuffer, "_read_infinite_line", read)
        c = bt.Cerebro(stdstats=False, runonce=once)
        c.adddata(Feed(dataname=frame))
        c.addstrategy(Driver)
        strategy = c.run(preload=True)[0]
        outputs.append((strategy.rows, seen))
    assert outputs[0] == outputs[1]
    assert outputs[0][1] == [math.inf] * 3 + [-math.inf] * 3


class RawFactorSource(bt.Indicator):
    lines = ("raw",)
    infinity = math.inf

    def next(self):
        self.lines.raw.array[self.lines.raw.idx] = (
            self.infinity if len(self) == 5 else float(self.data[0])
        )

    def once(self, start, end):
        for i in range(start, end):
            self.lines.raw.array[i] = self.infinity if i == 4 else float(self.data.array[i])


class ExtremeFactor(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    required_fields = formula_fields
    lookback_h = 2
    operation = bt.ind.Highest

    def __init__(self):
        super().__init__()
        ExtremeFactor.instance = self
        self.raw = RawFactorSource(self.data)
        self.extreme = ExtremeFactor.operation(self.raw, period=3)

    def next(self):
        self.outputs[self.datas[0]].factor[0] = self.extreme[0]


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("infinity", [math.inf, -math.inf])
@pytest.mark.parametrize("operation", [bt.ind.Highest, bt.ind.Lowest])
def test_factor_strategy_strict_rejects_raw_infinity(runonce, infinity, operation, monkeypatch):
    monkeypatch.setattr(RawFactorSource, "infinity", infinity)
    monkeypatch.setattr(ExtremeFactor, "operation", operation)
    frames = _frames(periods=8)
    frame = frames["asset-0"]
    research = _research_spec({"asset-0": frame})
    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(_research_feed(frame, research, "asset-0"), name="asset-0")
    factor = FactorSpec(
        name="test_factor",
        indicator=ExtremeFactor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    c.addstrategy(FactorStrategy, research=research, factors={factor.name: factor})
    with pytest.raises(FactorComputationError) as caught:
        c.run(preload=True)
    assert caught.value.factor == "test_factor"
    assert caught.value.phase == ("once" if runonce else "next")
    assert isinstance(caught.value.__cause__, ArithmeticError)
    assert ExtremeFactor.instance._factor_strict_context.failed is True


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("infinity", [math.inf, -math.inf])
@pytest.mark.parametrize("operation", [bt.ind.Highest, bt.ind.Lowest])
def test_non_strict_factor_owned_infinity_is_missing_and_recovers(
    runonce, infinity, operation, monkeypatch
):
    monkeypatch.setattr(RawFactorSource, "infinity", infinity)
    monkeypatch.setattr(ExtremeFactor, "operation", operation)

    class Driver(bt.Strategy):
        def __init__(self):
            self.factor = ExtremeFactor._bind_for_research(
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

    frame = pd.DataFrame({"close": [100.0] * 8}, index=pd.date_range("2025-01-01", periods=8))
    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(bt.feeds.PandasData(dataname=frame), name="A")
    c.addstrategy(Driver)
    strategy = c.run(preload=True)[0]
    result = list(strategy.factor.outputs[strategy.data].factor.array)
    assert result[2:6] == [100.0] * 4
    assert math.isnan(result[6])
    assert result[7] == 100.0
