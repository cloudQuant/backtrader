"""Batch evaluation when XPeriodCandleColor receives a multi-line indicator."""

import math
import types

import pandas as pd
import pytest

import backtrader as bt


def frame(count=50):
    prices = [100.0 + i * 0.2 + i % 5 * 0.17 for i in range(count)]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [v + 1.0 + i % 3 * 0.1 for i, v in enumerate(prices)],
            "low": [v - 1.0 - i % 2 * 0.1 for i, v in enumerate(prices)],
            "close": [v + i % 4 * 0.12 for i, v in enumerate(prices)],
            "volume": [1.0] * count,
        },
        index=pd.date_range("2024-01-01", periods=count, freq="h"),
    )


class SmoothedOHLC(bt.Indicator):
    alias = ()
    lines = ("open", "high", "low", "close")

    def __init__(self):
        for name, period in (("open", 3), ("high", 4), ("low", 2), ("close", 5)):
            setattr(self.lines, name, bt.ind.SMA(getattr(self.data, name), period=period))


def _snapshot(indicator):
    return [[float(v) for v in line.array] for line in indicator.lines]


def _equal_lines(left, right):
    assert len(left) == len(right)
    for a, b in zip(left, right):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            if math.isnan(x):
                assert math.isnan(y)
            else:
                assert x == pytest.approx(y, rel=1e-12, abs=1e-12)


def _run_shared(once, secondary=False, missing=False):
    slow = frame(30 if secondary else 50)
    if missing:
        slow.iloc[17, slow.columns.get_loc("close")] = math.nan
    if secondary:
        slow.index = pd.date_range("2024-01-01", periods=len(slow), freq="D")
    fast = frame(120)
    fast.index = pd.date_range("2024-01-01", periods=len(fast), freq="6h")

    class Probe(bt.Strategy):
        def __init__(self):
            source_data = self.datas[1] if secondary else self.data
            self.source = SmoothedOHLC(source_data)
            self.first = bt.ind.XPeriodCandleColor(self.source, cperiod=5, ma_length=3)
            self.second = bt.ind.XPeriodCandleColor(self.source, cperiod=2, ma_length=1)
            self.sibling = bt.ind.SMA(self.source.close, period=4)
            self.downstream = bt.ind.SMA(self.first.xclose, period=3)

    engine = bt.Cerebro(stdstats=False, runonce=once)
    if secondary:
        engine.adddata(bt.feeds.PandasData(dataname=fast))
    engine.adddata(bt.feeds.PandasData(dataname=slow))
    engine.addstrategy(Probe)
    return engine.run()[0]


@pytest.mark.parametrize("secondary", [False, True])
@pytest.mark.parametrize("missing", [False, True])
def test_upstream_shared_siblings_and_downstream_match_next(secondary, missing):
    iterative = _run_shared(False, secondary, missing)
    batch = _run_shared(True, secondary, missing)
    for name in ("source", "first", "second", "sibling", "downstream"):
        _equal_lines(_snapshot(getattr(iterative, name)), _snapshot(getattr(batch, name)))


@pytest.mark.parametrize("upstream", [False, True])
def test_subclass_hooks_and_next_overrides_keep_dispatch(upstream):
    class Hooked(bt.ind.XPeriodCandleColor):
        alias = ()

        def __init__(self):
            self.hooks = []
            super().__init__()

        def prenext(self):
            self.hooks.append(("pre", len(self.data)))

        def nextstart(self):
            self.hooks.append(("start", len(self.data)))
            super().nextstart()

        def next(self):
            self.hooks.append(("next", len(self.data)))
            super().next()
            self.lines.xclose[0] += 10.0

    class Probe(bt.Strategy):
        def __init__(self):
            source = SmoothedOHLC(self.data) if upstream else self.data
            self.indicator = Hooked(source, cperiod=5, ma_length=3)

    results = []
    for once in (False, True):
        engine = bt.Cerebro(stdstats=False, runonce=once)
        engine.adddata(bt.feeds.PandasData(dataname=frame()))
        engine.addstrategy(Probe)
        results.append(engine.run()[0].indicator)
    assert results[0].hooks == results[1].hooks
    _equal_lines(_snapshot(results[0]), _snapshot(results[1]))


def test_rebinding_next_during_batch_is_seen_on_next_bar():
    class Dynamic(bt.ind.XPeriodCandleColor):
        alias = ()

        def __init__(self):
            self.calls = []
            super().__init__()

        def next(self):
            self.calls.append(("original", len(self.data)))
            bt.ind.XPeriodCandleColor.next(self)
            if len(self.data) == 12:
                self.next = types.MethodType(replacement, self)

    def replacement(indicator):
        indicator.calls.append(("replacement", len(indicator.data)))
        bt.ind.XPeriodCandleColor.next(indicator)

    class Probe(bt.Strategy):
        def __init__(self):
            self.source = SmoothedOHLC(self.data)
            self.indicator = Dynamic(self.source, cperiod=5, ma_length=3)

    outputs = []
    for once in (False, True):
        engine = bt.Cerebro(stdstats=False, runonce=once)
        engine.adddata(bt.feeds.PandasData(dataname=frame()))
        engine.addstrategy(Probe)
        outputs.append(engine.run()[0].indicator)
    assert outputs[0].calls == outputs[1].calls
    assert ("original", 12) in outputs[1].calls
    assert ("replacement", 13) in outputs[1].calls
    _equal_lines(_snapshot(outputs[0]), _snapshot(outputs[1]))


def test_indicator_source_advance_hook_remains_in_batch_lifecycle():
    class TracedSource(SmoothedOHLC):
        alias = ()

        def __init__(self):
            self.batch_advances = 0
            super().__init__()

        def advance(self, size=1):
            if len(self.data) == 0:
                self.batch_advances += 1
            return super().advance(size)

    class Probe(bt.Strategy):
        def __init__(self):
            self.source = TracedSource(self.data)
            self.indicator = bt.ind.XPeriodCandleColor(self.source, cperiod=5, ma_length=3)

    engine = bt.Cerebro(stdstats=False, runonce=True)
    engine.adddata(bt.feeds.PandasData(dataname=frame()))
    engine.addstrategy(Probe)
    assert engine.run()[0].source.batch_advances == 50


def test_custom_source_advance_sees_original_cursor_sequence():
    class TracedSource(SmoothedOHLC):
        alias = ()

        def __init__(self):
            self.batch_positions = []
            super().__init__()

        def advance(self, size=1):
            if len(self.data) == 0:
                self.batch_positions.append(len(self))
            self.lines.advance(size=size)

    class Probe(bt.Strategy):
        def __init__(self):
            self.source = TracedSource(self.data)
            self.indicator = bt.ind.XPeriodCandleColor(self.source, cperiod=5, ma_length=3)

    engine = bt.Cerebro(stdstats=False, runonce=True)
    engine.adddata(bt.feeds.PandasData(dataname=frame()))
    engine.addstrategy(Probe)
    assert engine.run()[0].source.batch_positions == list(range(50))


def test_segmented_recalculation_preserves_cursor_and_other_slots():
    strategy = _run_shared(True)
    indicator = strategy.first
    lines = [*strategy.source.lines, *indicator.lines]
    lines.extend(line for child in indicator._lineiterators[0] for line in child.lines)
    old_positions = [(line.idx, line.lencount) for line in lines]
    old_values = _snapshot(indicator)
    indicator.once(12, 20)
    assert [(line.idx, line.lencount) for line in lines] == old_positions
    _equal_lines(old_values, _snapshot(indicator))


def test_failed_batch_callback_restores_shared_input_cursors():
    captured = []

    class Failing(bt.ind.XPeriodCandleColor):
        alias = ()

        def next(self):
            if len(self.data) == 12:
                raise RuntimeError("synthetic once failure")
            return super().next()

    class Probe(bt.Strategy):
        def __init__(self):
            self.source = SmoothedOHLC(self.data)
            self.indicator = Failing(self.source, cperiod=5, ma_length=3)
            captured.append(self)

    engine = bt.Cerebro(stdstats=False, runonce=True)
    engine.adddata(bt.feeds.PandasData(dataname=frame()))
    engine.addstrategy(Probe)
    with pytest.raises(RuntimeError, match="synthetic once failure"):
        engine.run()
    strategy = captured[0]
    assert all((line.idx, line.lencount) == (-1, 0) for line in strategy.source.lines)
    assert all(
        (line.idx, line.lencount) == (-1, 0)
        for child in strategy.indicator._lineiterators[0]
        for line in child.lines
    )


def _strict_factor(once, missing=False):
    from backtrader.research import align_to_grid
    from backtrader.research.factor_indicator import FactorIndicator
    from backtrader.research.specs import FactorSpec, ResearchSpec
    from backtrader.strategies.factor_strategy import FactorStrategy

    data = frame()
    if missing:
        data.iloc[18, data.columns.get_loc("close")] = math.nan
    data.index = data.index.tz_localize("UTC").rename("close_time")
    index = data.index
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=1)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("asset",),
        source_timezone="UTC",
        snapshot_id="xperiod-once",
        price_basis="synthetic",
        calendar_id="synthetic",
        frequency="1h",
        feed_time_kind="close_time",
        groups={"asset": "market"},
    )
    captured = []

    class Factor(FactorIndicator):
        lines = ("factor",)
        formula_fields = required_fields = ("open", "high", "low", "close")
        lookback_h = 0

        def __init__(self):
            super().__init__()
            self.source = SmoothedOHLC(self.data)
            self.child = bt.ind.XPeriodCandleColor(self.source, cperiod=5, ma_length=3)
            captured.append(self)

        def next(self):
            self.outputs[self.datas[0]].factor[0] = self.child.xclose[0]

    engine = bt.Cerebro(stdstats=False, runonce=once)
    engine.adddata(align_to_grid(data, research, "asset").feed, name="asset")
    spec = FactorSpec(
        name="period",
        indicator=Factor,
        panel_line="factor",
        field_bindings={field: f"feed:target:{field}" for field in Factor.required_fields},
        mode="native",
    )
    engine.addstrategy(FactorStrategy, research=research, factors={"period": spec})
    engine.run(preload=True)
    return captured[0]


@pytest.mark.parametrize("missing", [False, True])
def test_real_strict_factor_indicator_source_matches_next(missing):
    iterative = _strict_factor(False, missing)
    batch = _strict_factor(True, missing)
    _equal_lines(_snapshot(iterative.child), _snapshot(batch.child))


def test_strict_infinite_inner_value_still_fails_and_restores_cursors():
    from backtrader.errors import FactorComputationError
    from backtrader.research.strict import computation_scope

    factor = _strict_factor(True)
    child = factor.child
    line = child.smooth_open.lines[0]
    before = (line.idx, line.lencount)
    line.array[8] = float("inf")
    scope = computation_scope(factor._factor_strict_context, "once")
    with scope, pytest.raises(FactorComputationError) as caught:
        child.once(12, 13)
    assert isinstance(caught.value.__cause__, ArithmeticError)
    assert (line.idx, line.lencount) == before
