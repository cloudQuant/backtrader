"""Offline factor graph behavior through the normal Cerebro lifecycle."""

import importlib

import backtrader as bt
import pandas as pd
import pytest

from backtrader.research import (
    FactorComputationError,
    CsvSink,
    FactorIndicator,
    FactorSink,
    FactorSpec,
    ResearchSpec,
    align_to_grid,
)
from backtrader.strategies.factor_strategy import FactorStrategy
from backtrader.metabase import OwnerContext


class _Scaled(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.close_lines = self.field_lines("close")

    def next(self):
        for data, close in zip(self.target_datas, self.close_lines):
            self.outputs[data].factor[0] = close[0] * 2

    @classmethod
    def build(cls, ctx):
        return ctx.close * 2


class _Nested(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.child = _Scaled.bind(*self.target_datas)

    def next(self):
        for data in self.target_datas:
            self.outputs[data].factor[0] = self.child.outputs[data].factor[0] + 1


class _Average(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 2

    def __init__(self):
        super().__init__()
        self.averages = [bt.indicators.SMA(line, period=3) for line in self.field_lines("close")]

    def next(self):
        for data, average in zip(self.target_datas, self.averages):
            self.outputs[data].factor[0] = average[0]


class _WideAverage(_Average):
    def __init__(self):
        super().__init__()
        self.averages.extend(
            bt.indicators.SMA(self.field_lines("close")[0], period=3) for _ in range(49)
        )


class _CountingChild(bt.Indicator):
    lines = ("value",)

    def __init__(self):
        self.calls = 0

    def next(self):
        self.calls += 1
        self.lines.value[0] = self.data.close[0]


class _CountingFactor(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.counter = _CountingChild(self.datas[0])

    def next(self):
        self.outputs[self.datas[0]].factor[0] = self.counter.value[0]


class _CrossStrategyAlias(FactorStrategy):
    victim = None

    def start(self):
        first = self.cerebro.runningstrats[0]
        type(self).victim = first._factor_instances_by_name["f"][0].counter
        self.getindicators().append(type(self).victim)


class _LateCrossStrategyAlias(_CrossStrategyAlias):
    def start(self):
        pass

    def nextstart(self):
        super().nextstart()
        first = self.cerebro.runningstrats[0]
        type(self).victim = first._factor_instances_by_name["f"][0].counter
        self.getindicators().append(type(self).victim)


class _Intermediate(bt.Indicator):
    lines = ("value",)

    def __init__(self):
        self.child = _Scaled.bind(*self.datas)

    def next(self):
        self.lines.value[0] = self.child.outputs[self.datas[0]].factor[0]


class _ViaIntermediate(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.middle = _Intermediate(self.datas[0])

    def next(self):
        self.outputs[self.datas[0]].factor[0] = self.middle.value[0] + 1


class _ProbeSink(FactorSink):
    def __init__(self, fail=False):
        self.points = []
        self.finalized = False
        self.closed = False
        self.fail = fail

    def on_point(self, *args):
        self.points.append(args)
        if self.fail:
            raise ValueError("sink failure")

    def finalize(self, context):
        self.finalized = True
        return object()

    def close(self):
        self.closed = True


class _DroppedFactorStrategy(FactorStrategy):
    def start(self):
        root = self._factor_instances_by_name["f"][0]
        self.getindicators().remove(root)


class _DroppedNestedStrategy(FactorStrategy):
    def start(self):
        root = self._factor_instances_by_name["f"][0]
        root.getindicators().remove(root.child)


class _DroppedOrdinaryStrategy(FactorStrategy):
    def start(self):
        root = self._factor_instances_by_name["f"][0]
        root.getindicators()[:] = [
            item for item in root.getindicators() if item is not root.averages[0]
        ]


class _AddedOrdinaryStrategy(FactorStrategy):
    def start(self):
        root = self._factor_instances_by_name["f"][0]
        with OwnerContext.set_owner(root):
            extra = bt.indicators.SMA(root.datas[0].close, period=3)
        root.addindicator(extra)


class _DroppedIntermediateStrategy(FactorStrategy):
    def start(self):
        root = self._factor_instances_by_name["f"][0]
        root.middle.getindicators().remove(root.middle.child)


class _AddedFactorAtStart(FactorStrategy):
    def start(self):
        root = self._factor_instances_by_name["f"][0]
        with OwnerContext.set_owner(root):
            child = _Scaled.bind(*root.datas)
        root.addindicator(child)


class _AddedFactorAfterFirstBar(FactorStrategy):
    def start(self):
        root = self._factor_instances_by_name["f"][0]
        with OwnerContext.set_owner(root):
            child = _Scaled.bind(*root.datas)
        root.addindicator(child)
        root.getindicators()[:] = [item for item in root.getindicators() if item is not child]
        object.__setattr__(self, "extra", child)

    def _collect_grid_point(self):
        if self._grid_cursor == 1:
            self._factor_instances_by_name["f"][0].addindicator(self.extra)
        super()._collect_grid_point()


class _DuplicateNestedEdge(FactorStrategy):
    def start(self):
        root = self._factor_instances_by_name["f"][0]
        root.getindicators().append(root.child)


class _DuplicateHostEdge(FactorStrategy):
    def start(self):
        root = self._factor_instances_by_name["f"][0]
        self.getindicators().append(root.child)


class _LateErrorStrategy(FactorStrategy):
    def next(self):
        super().next()
        if self._grid_cursor == len(self._grid):
            raise ValueError("late strategy failure")


class _LateAnalyzer(bt.Analyzer):
    def next(self):
        if len(self.strategy) == 4:
            raise ValueError("late analyzer failure")


class _LateObserver(bt.Observer):
    lines = ("value",)

    def next(self):
        if len(self._owner) == 4:
            raise ValueError("late observer failure")


def _run(
    mode,
    runonce,
    nested=False,
    factor=None,
    sink=None,
    strategy=FactorStrategy,
    analyzer=None,
    observer=None,
    oldsync=False,
    return_cerebro=False,
    writer=None,
    broker=None,
):
    index = pd.date_range("2025-01-01 16:00", periods=4, tz="UTC", name="close_time")
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("A", "B"),
        groups={"A": "x", "B": "y"},
        source_timezone="UTC",
        snapshot_id="test",
        price_basis="test",
        calendar_id="test",
        frequency="1day",
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, oldsync=oldsync)
    if analyzer:
        cerebro.addanalyzer(analyzer)
    if observer:
        cerebro.addobserver(observer)
    if writer:
        cerebro.addwriter(writer)
    if broker:
        cerebro.setbroker(broker)
    for asset, values in (("A", [0.0, 1.0, 2.0, 3.0]), ("B", [4.0, 5.0, 6.0, 7.0])):
        frame = pd.DataFrame(
            {key: values for key in ("open", "high", "low", "close", "volume")}, index=index
        )
        cerebro.adddata(align_to_grid(frame, research, asset).feed, name=asset)
    spec = FactorSpec(
        name="f",
        indicator=factor or (_Nested if nested else _Scaled),
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        mode=mode,
    )
    cerebro.addstrategy(strategy, research=research, factors={"f": spec}, sink=sink)
    if return_cerebro:
        return cerebro
    return cerebro.run(runonce=runonce)[0]


@pytest.mark.parametrize("mode", ["native", "build"])
@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_group_graph_values_and_coverage(mode, runonce):
    strategy = _run(mode, runonce)
    assert bool(strategy.cerebro._dorunonce) is runonce
    assert strategy.cerebro._dopreload
    panel = strategy.get_panel().factors
    for asset, values in (("A", [0.0, 2.0, 4.0, 6.0]), ("B", [8.0, 10.0, 12.0, 14.0])):
        assert panel.xs(asset, level="asset")["f"].tolist() == values
    for instance in strategy._factor_instances_by_name["f"]:
        assert instance._owner is strategy
        assert sum(item is instance for item in strategy.getindicators()) == 1
        assert instance.lifecycle_diagnostics["coverage_matches"]
        assert instance.lifecycle_diagnostics["coverage_count"] == 4


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_nested_graph_values_and_coverage(runonce):
    strategy = _run("native", runonce, nested=True)
    panel = strategy.get_panel().factors
    assert panel.xs("A", level="asset")["f"].tolist() == [1.0, 3.0, 5.0, 7.0]
    for root in strategy._factor_instances_by_name["f"]:
        tree = strategy._factor_tree(root)
        assert len(tree) == 2
        assert root.child._owner is root
        for node in tree:
            assert node.lifecycle_diagnostics["coverage_matches"]
            assert node.lifecycle_diagnostics["coverage_count"] == 4


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_minperiod_warmup_is_driven_before_collection(runonce):
    strategy = _run("native", runonce, factor=_Average)
    values = strategy.get_panel().factors.xs("A", level="asset")["f"].tolist()
    assert pd.isna(values[0]) and pd.isna(values[1])
    assert values[2:] == pytest.approx([1.0, 2.0])
    for root in strategy._factor_instances_by_name["f"]:
        assert all(average._minperiod == 3 for average in root.averages)
        assert root.lifecycle_diagnostics["coverage_matches"]


@pytest.mark.parametrize("runonce", [False, True])
def test_wide_ordinary_indicator_graph_is_valid(runonce):
    strategy = _run("native", runonce, factor=_WideAverage)
    values = strategy.get_panel().factors.xs("A", level="asset")["f"].tolist()
    assert pd.isna(values[0]) and pd.isna(values[1])
    assert values[2:] == pytest.approx([1.0, 2.0])
    for root in strategy._factor_instances_by_name["f"]:
        assert len(root.averages) == 50
        assert root.lifecycle_diagnostics["coverage_matches"]


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("strategy", [_CrossStrategyAlias, _LateCrossStrategyAlias])
def test_cross_strategy_alias_of_factor_child_cannot_publish(runonce, strategy):
    first_sink, second_sink = _ProbeSink(), _ProbeSink()
    cerebro = _run("native", runonce, factor=_CountingFactor, sink=first_sink, return_cerebro=True)
    _, args, kwargs = cerebro.strats[0][0]
    cerebro.addstrategy(strategy, *args, **dict(kwargs, sink=second_sink))
    with pytest.raises(RuntimeError, match="multiple scheduling paths"):
        cerebro.run(runonce=runonce)
    if strategy is _CrossStrategyAlias:
        assert strategy.victim.calls == 0
        assert not first_sink.points and not second_sink.points
    assert not first_sink.finalized and not second_sink.finalized
    assert first_sink.closed and second_sink.closed


@pytest.mark.parametrize("runonce", [False, True])
def test_independent_factor_and_ordinary_strategy_graphs_coexist(runonce):
    class Ordinary(bt.Strategy):
        def __init__(self):
            self.average = bt.indicators.SMA(self.datas[0], period=2)

    cerebro = _run("native", runonce, factor=_CountingFactor, return_cerebro=True)
    _, args, kwargs = cerebro.strats[0][0]
    cerebro.addstrategy(FactorStrategy, *args, **kwargs)
    cerebro.addstrategy(Ordinary)
    first, second, _ordinary = cerebro.run(runonce=runonce)
    assert first.get_panel().factors.equals(second.get_panel().factors)
    first_child = first._factor_instances_by_name["f"][0].counter
    second_child = second._factor_instances_by_name["f"][0].counter
    assert first_child is not second_child
    assert first_child.calls == second_child.calls == 4


@pytest.mark.parametrize("runonce", [False, True])
def test_ordinary_strategy_cannot_schedule_a_factor_child(runonce):
    class OrdinaryAlias(bt.Strategy):
        def __init__(self):
            self.average = bt.indicators.SMA(self.datas[0], period=2)

        def start(self):
            first = self.cerebro.runningstrats[0]
            child = first._factor_instances_by_name["f"][0].counter
            self.average.getindicators().append(child)

    sink = _ProbeSink()
    cerebro = _run("native", runonce, factor=_CountingFactor, sink=sink, return_cerebro=True)
    cerebro.addstrategy(OrdinaryAlias)
    with pytest.raises(RuntimeError, match="multiple scheduling paths"):
        cerebro.run(runonce=runonce)
    assert not sink.points and not sink.finalized and sink.closed


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_removed_factor_rejects_before_sink_publication(runonce):
    sink = _ProbeSink()
    with pytest.raises(RuntimeError, match="missing from its owner graph"):
        _run("native", runonce, sink=sink, strategy=_DroppedFactorStrategy)
    assert not sink.points
    assert not sink.finalized
    assert sink.closed


def test_custom_sink_failure_is_preserved_and_closed():
    sink = _ProbeSink(fail=True)
    with pytest.raises(ValueError, match="sink failure"):
        _run("native", False, sink=sink)
    assert len(sink.points) == 1  # custom on_point may have external side effects
    assert not sink.finalized
    assert sink.closed


@pytest.mark.parametrize("runonce", [False, True])
def test_removed_nested_factor_cannot_publish(runonce):
    sink = _ProbeSink()
    with pytest.raises(RuntimeError, match="factor graph changed"):
        _run("native", runonce, nested=True, sink=sink, strategy=_DroppedNestedStrategy)
    assert not sink.points and not sink.finalized and sink.closed


@pytest.mark.parametrize("runonce", [False, True])
def test_factor_below_ordinary_indicator_has_grid_and_coverage(runonce):
    strategy = _run("native", runonce, factor=_ViaIntermediate)
    assert strategy.get_panel().factors.xs("A", level="asset")["f"].tolist() == [1.0, 3.0, 5.0, 7.0]
    for root in strategy._factor_instances_by_name["f"]:
        child = root.middle.child
        assert child.lifecycle_diagnostics["grid_count"] == 4
        assert child.lifecycle_diagnostics["coverage_matches"]


@pytest.mark.parametrize("runonce", [False, True])
def test_removed_factor_below_ordinary_indicator_cannot_publish(runonce):
    sink = _ProbeSink()
    with pytest.raises(RuntimeError, match="factor graph changed"):
        _run(
            "native",
            runonce,
            factor=_ViaIntermediate,
            sink=sink,
            strategy=_DroppedIntermediateStrategy,
        )
    assert not sink.points and not sink.finalized and sink.closed


@pytest.mark.parametrize("runonce", [False, True])
def test_removed_sma_cannot_publish(runonce):
    sink = _ProbeSink()
    with pytest.raises(RuntimeError, match="factor graph changed"):
        _run("native", runonce, factor=_Average, sink=sink, strategy=_DroppedOrdinaryStrategy)
    assert not sink.points and not sink.finalized and sink.closed


@pytest.mark.parametrize("runonce", [False, True])
def test_added_sma_cannot_publish(runonce):
    sink = _ProbeSink()
    with pytest.raises(RuntimeError, match="factor graph changed"):
        _run("native", runonce, factor=_Average, sink=sink, strategy=_AddedOrdinaryStrategy)
    assert not sink.points and not sink.finalized and sink.closed


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("strategy", [_AddedFactorAtStart, _AddedFactorAfterFirstBar])
def test_added_nested_factor_cannot_publish(runonce, strategy):
    sink = _ProbeSink()
    with pytest.raises(RuntimeError, match="factor graph changed"):
        _run("native", runonce, sink=sink, strategy=strategy)
    assert not sink.finalized and sink.closed


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("strategy", [_DuplicateNestedEdge, _DuplicateHostEdge])
def test_duplicate_scheduling_edge_cannot_publish(runonce, strategy):
    sink = _ProbeSink()
    with pytest.raises(RuntimeError):
        _run("native", runonce, nested=True, sink=sink, strategy=strategy)
    assert not sink.finalized and sink.closed


@pytest.mark.parametrize("runonce,oldsync", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("kind", ["strategy", "analyzer", "observer"])
def test_last_bar_failure_does_not_finalize_sink(runonce, oldsync, kind):
    sink = _ProbeSink()
    kwargs = (
        {"strategy": _LateErrorStrategy}
        if kind == "strategy"
        else {kind: {"analyzer": _LateAnalyzer, "observer": _LateObserver}[kind]}
    )
    with pytest.raises(ValueError, match="late %s failure" % kind):
        _run("native", runonce, oldsync=oldsync, sink=sink, **kwargs)
    assert len(sink.points) == 8
    assert not sink.finalized and sink.closed


def test_oldsync_runnext_clock_failure_does_not_publish():
    sink = _ProbeSink()
    with pytest.raises(RuntimeError, match="callback time does not match"):
        _run("native", False, oldsync=True, sink=sink)
    assert not sink.finalized and sink.closed


def test_cerebro_reuse_resets_failure_state():
    class FailOnce(FactorStrategy):
        fail = True

        def next(self):
            super().next()
            if type(self).fail and self._grid_cursor == len(self._grid):
                raise ValueError("first run")

    sink = _ProbeSink()
    cerebro = _run("native", False, strategy=FailOnce, sink=sink, return_cerebro=True)
    with pytest.raises(ValueError, match="first run"):
        cerebro.run(runonce=False)
    assert sink.closed and not sink.finalized
    FailOnce.fail = False
    cerebro.run(runonce=False)
    assert sink.finalized
    assert cerebro._factor_research_run_failed is False


def test_construction_failure_closes_sink():
    class FailingFactor(FactorIndicator):
        lines = ("factor",)
        formula_fields = ("close",)
        lookback_h = 0

        def __init__(self):
            super().__init__()
            raise ValueError("factor construction")

        def next(self):
            pass

    sink = _ProbeSink()
    with pytest.raises(FactorComputationError) as captured:
        _run("native", False, factor=FailingFactor, sink=sink)
    assert isinstance(captured.value.__cause__, ValueError)
    assert str(captured.value.__cause__) == "factor construction"
    assert sink.closed and not sink.finalized


def test_start_failure_closes_sink():
    class StartFailure(FactorStrategy):
        def start(self):
            raise ValueError("startup failure")

    sink = _ProbeSink()
    with pytest.raises(ValueError, match="startup failure"):
        _run("native", False, strategy=StartFailure, sink=sink)
    assert sink.closed and not sink.finalized


def test_stop_failure_closes_other_strategies_and_resources_preserving_first_error():
    import io

    events = []

    class StopFailure(bt.Analyzer):
        def stop(self):
            events.append("analyzer")
            raise ValueError("first analyzer failure")

    class BrokenWriter(bt.WriterFile):
        def __init__(self):
            super().__init__(out=io.StringIO())

        def stop(self):
            events.append("writer")
            super().stop()
            raise RuntimeError("writer failure")

    class BrokenBroker(bt.brokers.BackBroker):
        def stop(self):
            events.append("broker")
            super().stop()
            raise RuntimeError("broker failure")

    first, second = _ProbeSink(), _ProbeSink()
    cerebro = _run(
        "native",
        False,
        sink=first,
        analyzer=StopFailure,
        writer=BrokenWriter,
        broker=BrokenBroker(),
        return_cerebro=True,
    )
    _, args, kwargs = cerebro.strats[0][0]
    kwargs = dict(kwargs, sink=second)
    cerebro.addstrategy(FactorStrategy, *args, **kwargs)
    with pytest.raises(ValueError, match="first analyzer failure"):
        cerebro.run(runonce=False)
    assert first.closed and second.closed
    assert not second.finalized
    assert events.count("analyzer") == 2
    assert "writer" in events and "broker" in events


def test_base_exception_survives_stop_failures():
    class InterruptStrategy(FactorStrategy):
        def next(self):
            super().next()
            if self._grid_cursor == len(self._grid):
                raise KeyboardInterrupt("first interrupt")

    class BrokenBroker(bt.brokers.BackBroker):
        def stop(self):
            super().stop()
            raise ValueError("broker stop")

    sink = _ProbeSink()
    with pytest.raises(KeyboardInterrupt, match="first interrupt"):
        _run("native", False, sink=sink, strategy=InterruptStrategy, broker=BrokenBroker())
    assert sink.closed and not sink.finalized


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("failure", [None, "analyzer", "writer", "broker"])
def test_csv_publishes_only_after_teardown(tmp_path, runonce, failure):
    import io

    class FailingAnalyzer(bt.Analyzer):
        def stop(self):
            assert self.strategy.get_panel() is not None
            assert not output.exists()
            raise ValueError("analyzer teardown")

    class FailingWriter(bt.WriterFile):
        def __init__(self):
            super().__init__(out=io.StringIO())

        def stop(self):
            super().stop()
            raise ValueError("writer teardown")

    class FailingBroker(bt.brokers.BackBroker):
        def stop(self):
            super().stop()
            raise ValueError("broker teardown")

    output = tmp_path / "panel"
    sink = CsvSink(output)
    options = {}
    if failure == "analyzer":
        options["analyzer"] = FailingAnalyzer
    if failure == "writer":
        options["writer"] = FailingWriter
    if failure == "broker":
        options["broker"] = FailingBroker()
    if failure:
        with pytest.raises(ValueError, match=failure + " teardown"):
            _run("native", runonce, sink=sink, **options)
        assert not output.exists()
    else:
        strategy = _run("native", runonce, sink=sink)
        assert strategy.get_panel() is sink.panel
        assert {path.name for path in output.iterdir()} == {
            "factors.csv",
            "grid.csv",
            "prices_open.csv",
            "prices_close.csv",
            "universe.csv",
            "groups.csv",
        }
    assert sink._closed


def test_import_identity_and_retired_paths():
    import backtrader.research as research

    assert FactorStrategy.__module__ == "backtrader.strategies.factor_strategy"
    assert not hasattr(research, "FactorStrategy")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("backtrader.research.factor_strategy")
