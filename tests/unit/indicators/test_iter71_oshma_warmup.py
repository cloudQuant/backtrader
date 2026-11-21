"""OsHMA and HMA use complete WMA windows on each data clock."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.hma import HMA, OsHMAIndicator
from backtrader.errors import FactorComputationContext, FactorComputationError


def frame(count, freq="D"):
    values = [100 + i * 0.11 + math.sin(i * 0.31) * 2 + (i % 7) * 0.17 for i in range(count)]
    return pd.DataFrame({name: values for name in ("open", "high", "low", "close")},
                        index=pd.date_range("2024-01-01", periods=count, freq=freq))


def wma(values, period):
    result = [math.nan] * len(values)
    for end in range(period - 1, len(values)):
        window = values[end - period + 1:end + 1]
        if all(math.isfinite(value) for value in window):
            result[end] = sum((i + 1) * value for i, value in enumerate(window)) / (period * (period + 1) / 2)
    return result


def hma(values, period):
    half = wma(values, max(1, period // 2))
    full = wma(values, period)
    return wma([2 * x - y for x, y in zip(half, full)], max(1, math.isqrt(period)))


def same(actual, expected):
    assert len(actual) == len(expected)
    for i, (a, e) in enumerate(zip(actual, expected)):
        if math.isnan(e):
            assert math.isnan(a), i
        else:
            assert a == pytest.approx(e, rel=1e-11, abs=1e-11), i


def execute(data, runonce, *, fast=13, slow=26, primary=None, upstream=1, subclass=False):
    class CustomHMA(HMA):
        pass

    class Probe(bt.Strategy):
        def __init__(self):
            source = self.datas[-1]
            line = source.close if upstream == 1 else bt.ind.SMA(source.close, period=upstream)
            self.hma = (CustomHMA if subclass else HMA)(line, period=slow)
            self.hist = OsHMAIndicator(source, fast_hma=fast, slow_hma=slow)
            self.starts = []

        def nextstart(self):
            self.starts.append((len(self.datas[-1]), len(self)))
            super().nextstart()

    engine = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    if primary is not None:
        engine.adddata(bt.feeds.PandasData(dataname=primary))
    engine.adddata(bt.feeds.PandasData(dataname=data))
    engine.addstrategy(Probe)
    return engine.run()[0]


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("count", [1, 20, 29, 30, 31, 100])
def test_full_series_and_warmup_boundary(runonce, count):
    data = frame(count)
    strategy = execute(data, runonce)
    prices = list(data.close)
    fast, slow = hma(prices, 13), hma(prices, 26)
    assert strategy.hma._minperiod == 30
    assert strategy.hist._minperiod == 30
    same(strategy.hma.hma.array, slow)
    same(strategy.hist.hist.array, [x - y for x, y in zip(fast, slow)])
    assert strategy.starts == ([(30, 30)] if count >= 30 else [])


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("fast,slow", [(1, 2), (2, 1), (26, 13), (9, 16)])
def test_period_order_and_small_periods(runonce, fast, slow):
    data = frame(60)
    strategy = execute(data, runonce, fast=fast, slow=slow)
    expected_period = max(p + math.isqrt(p) - 1 for p in (fast, slow))
    assert strategy.hist._minperiod == expected_period
    a, b = hma(list(data.close), fast), hma(list(data.close), slow)
    same(strategy.hist.hist.array, [x - y for x, y in zip(a, b)])


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_hma_subclass_and_upstream_minperiod(runonce):
    data = frame(80)
    strategy = execute(data, runonce, upstream=4, subclass=True)
    values = list(data.close)
    averaged = [math.nan] * 3 + [sum(values[i-3:i+1]) / 4 for i in range(3, len(values))]
    assert strategy.hma._minperiod == 33
    same(strategy.hma.hma.array, hma(averaged, 26))
    assert strategy.starts == [(33, 33)]


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_secondary_feed_owns_indicator_clock(runonce):
    data = frame(50, freq="3D")
    strategy = execute(data, runonce, primary=frame(150))
    fast, slow = hma(list(data.close), 13), hma(list(data.close), 26)
    same(strategy.hist.hist.array, [x - y for x, y in zip(fast, slow)])
    assert strategy.starts and strategy.starts[0][0] == 30


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_missing_price_recovers_after_complete_window(runonce):
    data = frame(100)
    data.iloc[45, data.columns.get_loc("close")] = math.nan
    strategy = execute(data, runonce)
    fast, slow = hma(list(data.close), 13), hma(list(data.close), 26)
    same(strategy.hist.hist.array, [x - y for x, y in zip(fast, slow)])
    assert math.isfinite(strategy.hist.hist.array[75])


def test_once_writes_only_requested_segment():
    strategy = execute(frame(100), True)
    for indicator, line in ((strategy.hma, strategy.hma.hma),
                            (strategy.hist, strategy.hist.hist)):
        expected = list(line.array)
        for i in range(45, 50):
            line.array[i] = -999.0
        indicator.once(45, 50)
        same(line.array, expected)


@pytest.mark.parametrize("indicator_type", [HMA, OsHMAIndicator], ids=["hma", "histogram"])
def test_subclass_next_override_is_called_in_both_modes(indicator_type):
    class Child(indicator_type):
        def next(self):
            super().next()
            self.lines[0][0] += 7.0

    def run(runonce):
        class Probe(bt.Strategy):
            def __init__(self):
                self.indicator = Child(self.data, **({"period": 3} if indicator_type is HMA
                                                     else {"fast_hma": 2, "slow_hma": 3}))

        engine = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
        engine.adddata(bt.feeds.PandasData(dataname=frame(30)))
        engine.addstrategy(Probe)
        return list(engine.run()[0].indicator.lines[0].array)

    next_values, once_values = run(False), run(True)
    same(once_values, next_values)
    assert math.isfinite(next_values[-1])


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_hma_subclass_calculate_override_is_dispatched(runonce):
    class Child(HMA):
        def _calculate(self, values):
            return super()._calculate(values) + 3.0

    data = frame(40)
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = Child(self.data, period=3)

    engine = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    engine.adddata(bt.feeds.PandasData(dataname=data))
    engine.addstrategy(Probe)
    values = list(engine.run()[0].indicator.hma.array)
    expected = hma(list(data.close), 3)
    same(values, [value + 3.0 for value in expected])


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
@pytest.mark.parametrize("indicator_type", [HMA, OsHMAIndicator], ids=["hma", "histogram"])
@pytest.mark.parametrize("overflow", [False, True], ids=["missing", "overflow"])
def test_strict_context_propagates_overflow_and_allows_missing(runonce, indicator_type, overflow):
    data = frame(8)
    data.loc[:, "close"] = 1e308 if overflow else math.nan

    class Probe(bt.Strategy):
        def __init__(self):
            self._factor_strict_context = FactorComputationContext("oshma", phase="next")
            params = {"period": 1} if indicator_type is HMA else {"fast_hma": 1, "slow_hma": 1}
            self.indicator = indicator_type(self.data, **params)

    engine = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    engine.adddata(bt.feeds.PandasData(dataname=data))
    engine.addstrategy(Probe)
    if overflow:
        with pytest.raises(FactorComputationError):
            engine.run()
    else:
        indicator = engine.run()[0].indicator
        assert all(math.isnan(value) for value in indicator.lines[0].array)


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_strict_factor_graph_rejects_intermediate_overflow(runonce):
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec
    from backtrader.strategies.factor_strategy import FactorStrategy
    from tests.unit.test_factor_research_representatives import _frames, _research_feed, _research_spec

    data = _frames(periods=25)["asset-0"].copy()
    for field in ("open", "high", "low", "close"):
        data.loc[:, field] = 1e308
    research = _research_spec({"asset-0": data})

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.child = OsHMAIndicator(self.data, fast_hma=1, slow_hma=1)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.hist[0]

    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(_research_feed(data, research, "asset-0"), name="asset-0")
    spec = FactorSpec(name="oshma", indicator=Factor, panel_line="factor",
                      field_bindings={"close": "feed:target:close"}, mode="native")
    engine.addstrategy(FactorStrategy, research=research, factors={"oshma": spec})
    with pytest.raises(FactorComputationError):
        engine.run(preload=True)


def test_replay_matches_reference_on_each_revision():
    class Probe(bt.Strategy):
        def __init__(self):
            self.hist = OsHMAIndicator(self.data, fast_hma=3, slow_hma=5)
            self.rows = []

        def next(self):
            prices = list(self.data.close.get(size=len(self.data)))
            self.rows.append((len(self.data), prices, float(self.hist.hist[0])))

    engine = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    engine.replaydata(bt.feeds.PandasData(dataname=frame(100, freq="min")),
                      timeframe=bt.TimeFrame.Minutes, compression=5)
    engine.addstrategy(Probe)
    rows = engine.run()[0].rows
    assert rows and rows[0][0] == 6
    assert any(a[0] == b[0] for a, b in zip(rows, rows[1:]))
    for _, prices, actual in rows:
        fast, slow = hma(prices, 3), hma(prices, 5)
        assert actual == pytest.approx(fast[-1] - slow[-1], rel=1e-11, abs=1e-11)
