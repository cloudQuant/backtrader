import importlib.util
import math
from pathlib import Path
import sys
from types import MethodType

import backtrader as bt
import pandas as pd
import pytest

from backtrader.errors import FactorComputationError
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.specs import FactorSpec
from backtrader.strategies.factor_strategy import FactorStrategy
from tests.unit.test_factor_research_representatives import _frames, _research_feed, _research_spec


def frame(values):
    return pd.DataFrame(
        dict.fromkeys(("open", "high", "low", "close", "volume"), values),
        index=pd.date_range("2024-01-01", periods=len(values), freq="min"),
    )


def reference(values, size=1.0):
    seed = None
    prev = None
    up = False
    output = []
    for price in values:
        if math.isnan(price):
            output.append((math.nan,) * 3)
            continue
        if seed is None:
            seed = price
            output.append((0.0, 0.0, 0.0))
        elif prev is None:
            if abs(price - seed) < size:
                output.append((0.0, 0.0, 0.0))
            elif price > seed:
                prev = (price, seed, 1.0)
                up = True
                output.append(prev)
            else:
                prev = (seed, price, -1.0)
                up = False
                output.append(prev)
        else:
            hi, lo, count = prev
            if price >= hi + size:
                prev = (price, hi, count + 1.0 if up else 1.0)
                up = True
            elif price <= lo - size:
                prev = (lo, price, -1.0 if up else count - 1.0)
                up = False
            output.append(prev)
    return output


def equal(actual, expected):
    for a, e in zip(actual, expected):
        if math.isnan(e):
            assert math.isnan(a)
        else:
            assert a == pytest.approx(e)


@pytest.mark.parametrize("runonce,exactbars", [(False, 0), (True, 0), (False, 1)])
@pytest.mark.parametrize(
    "values",
    [
        [math.nan, 100, 100, 102, 102, 99],
        [100, math.nan, 100, 102, 102, 99],
        [100, 102, math.nan, math.nan, 102, 103, 100, 99],
        [100, 98, math.nan, 98, 97, 100, 101],
    ],
)
def test_nan_does_not_advance_state_and_valid_values_recover(runonce, exactbars, values):
    class Driver(bt.Strategy):
        def __init__(self):
            self.renko = bt.ind.RenkoLineBreak(self.data, min_box_size=1, point=1)
            self.rows = []

        def next(self):
            self.rows.append(tuple(float(line[0]) for line in self.renko.lines))

    c = bt.Cerebro(stdstats=False, runonce=runonce, exactbars=exactbars)
    c.adddata(bt.feeds.PandasData(dataname=frame(values)))
    c.addstrategy(Driver)
    s = c.run(preload=True)[0]
    assert s.renko._minperiod == 1
    assert len(s.rows) == len(values)
    for actual, expected in zip(s.rows, reference(values)):
        equal(actual, expected)


@pytest.mark.parametrize("runonce", [False, True])
def test_actual_strategy_trend_is_neutral_on_missing_initialized_bar(runonce, monkeypatch):
    path = (
        Path(__file__).resolve().parents[3] / "tests/functional/strategies/mean_reversion/"
        "test_0306_1123_renko_line_break_vs_rsi_ea.py"
    )
    spec = importlib.util.spec_from_file_location("renko_strategy_fixture", path)
    obj = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, obj)
    spec.loader.exec_module(obj)

    class Recorder(obj.RenkoLineBreakVsRsiStrategy):
        def __init__(self):
            super().__init__()
            self.trends = []

        def next(self):
            self.trends.append((len(self.data), self._trend()))

    values = [100, 100, 100, 100, 101, 102, math.nan, 102, 103, 100]
    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(bt.feeds.PandasData(dataname=frame(values)))
    c.addstrategy(Recorder, min_box_size=1, point=1)
    s = c.run(preload=True)[0]
    assert dict(s.trends)[7] == obj.NO_TREND


def test_replay_values_match_current_visible_bars():
    values = [100, 100, 100, 100, 102, math.nan, 103, 103, 99, 99, 98, 98]
    df = frame(values)
    df.loc[:, "open"] = 100.0
    df.loc[:, "high"] = 110.0
    df.loc[:, "low"] = 90.0
    df.loc[:, "volume"] = 1.0

    class Driver(bt.Strategy):
        def __init__(self):
            self.renko = bt.ind.RenkoLineBreak(self.data, min_box_size=1, point=1)
            self.samples = []

        def next(self):
            history = list(self.data.close.get(size=len(self.data)))
            result = tuple(float(line[0]) for line in self.renko.lines)
            self.samples.append((history, result))

    c = bt.Cerebro(stdstats=False)
    c.replaydata(
        bt.feeds.PandasData(dataname=df, timeframe=bt.TimeFrame.Minutes),
        timeframe=bt.TimeFrame.Minutes,
        compression=3,
    )
    c.addstrategy(Driver)
    samples = c.run()[0].samples
    assert any(math.isnan(h[-1]) for h, _ in samples)
    for history, result in samples:
        equal(result, reference(history)[-1])


@pytest.mark.parametrize("runonce", [False, True])
def test_nested_indicator_source_matches_independent_reference(runonce):
    values = [100, 100, 102, 103, math.nan, 102, 99, 98, 100, 101]

    class Raw(bt.Indicator):
        lines = ("close",)

        def next(self):
            self.lines.close[0] = self.data[0]

        def once(self, start, end):
            for index in range(start, end):
                self.lines.close.array[index] = self.data.array[index]

    class Driver(bt.Strategy):
        def __init__(self):
            self.raw = Raw(self.data.close)
            self.renko = bt.ind.RenkoLineBreak(self.raw, min_box_size=1, point=1)
            self.rows = []

        def next(self):
            self.rows.append(tuple(float(line[0]) for line in self.renko.lines))

    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(bt.feeds.PandasData(dataname=frame(values)))
    c.addstrategy(Driver)
    s = c.run(preload=True)[0]
    assert len(s.rows) == len(values)
    for actual, expected in zip(s.rows, reference(values)):
        equal(actual, expected)


@pytest.mark.parametrize("placement", ["subclass", "instance"])
def test_custom_next_keeps_callback_in_batch(placement):
    calls = []

    def custom(self):
        calls.append(len(self))
        self.lines.upper[0] = 77
        self.lines.lower[0] = 78
        self.lines.boxes[0] = 79

    class Custom(bt.ind.RenkoLineBreak):
        def next(self):
            custom(self)

    class Driver(bt.Strategy):
        def __init__(self):
            self.renko = (Custom if placement == "subclass" else bt.ind.RenkoLineBreak)(
                self.data, min_box_size=1, point=1
            )
            if placement == "instance":
                self.renko.next = MethodType(custom, self.renko)

    c = bt.Cerebro(stdstats=False, runonce=True)
    c.adddata(bt.feeds.PandasData(dataname=frame([100.0] * 8)))
    c.addstrategy(Driver)
    s = c.run(preload=True)[0]
    assert len(calls) == 8
    assert list(s.renko.boxes.array) == [79.0] * 8


@pytest.mark.parametrize("runonce", [False, True])
def test_asynchronous_second_feed_uses_its_own_bar_clock(runonce):
    values = [100, 101, 102, math.nan, 102, 99, 98, 100, 103, 102]
    slow = frame(values)
    slow.index = pd.date_range("2024-01-01", periods=len(values), freq="2min")

    class Driver(bt.Strategy):
        def __init__(self):
            self.renko = bt.ind.RenkoLineBreak(self.data1, min_box_size=1, point=1)
            self.rows = []

        def next(self):
            self.rows.append((len(self.data1), tuple(float(line[0]) for line in self.renko.lines)))

    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(bt.feeds.PandasData(dataname=frame([100.0] * 20)))
    c.adddata(bt.feeds.PandasData(dataname=slow))
    c.addstrategy(Driver)
    rows = c.run(preload=True)[0].rows
    assert rows
    for length, actual in rows:
        equal(actual, reference(values[:length])[-1])


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("infinity", [math.inf, -math.inf])
def test_strict_factor_rejects_raw_infinity(runonce, infinity):
    class Raw(bt.Indicator):
        lines = ("close",)

        def next(self):
            self.lines.close.array[self.lines.close.idx] = (
                infinity if len(self) == 5 else float(self.data[0])
            )

        def once(self, start, end):
            for i in range(start, end):
                self.lines.close.array[i] = infinity if i == 4 else float(self.data.array[i])

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = ("close",)
        required_fields = formula_fields
        lookback_h = 0

        def __init__(self):
            super().__init__()
            Factor.instance = self
            self.raw = Raw(self.data.close)
            self.renko = bt.ind.RenkoLineBreak(self.raw, min_box_size=1, point=1)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.renko.boxes[0]

    frames = _frames(periods=10)
    data = frames["asset-0"]
    research = _research_spec({"asset-0": data})
    c = bt.Cerebro(stdstats=False, runonce=runonce)
    c.adddata(_research_feed(data, research, "asset-0"), name="asset-0")
    factor = FactorSpec(
        name="renko",
        indicator=Factor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode="native",
    )
    c.addstrategy(FactorStrategy, research=research, factors={factor.name: factor})
    with pytest.raises(FactorComputationError) as caught:
        c.run(preload=True)
    assert caught.value.factor == "renko"
    assert isinstance(caught.value.__cause__, ArithmeticError)
    assert Factor.instance._factor_strict_context.failed is True
