"""Focused lifecycle checks for one-time FactorIndicator grid binding."""

from datetime import timedelta

import backtrader as bt
import pandas as pd
import pytest

from backtrader.lineiterator import LineIterator
from backtrader.research import FactorIndicator, FactorSpec, ResearchSpec, align_to_grid
from backtrader.strategies.factor_strategy import FactorStrategy


class _GridLeaf(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.close_lines = self.field_lines("close")

    def next(self):
        for data, close in zip(self.target_datas, self.close_lines):
            self.outputs[data].factor[0] = close[0]


class _OrdinaryBridge(bt.Indicator):
    lines = ("value",)

    def __init__(self):
        self.child = _GridLeaf.bind(*self.datas)

    def next(self):
        self.lines.value[0] = self.child.outputs[self.datas[0]].factor[0]


class _GridRoot(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.bridge = _OrdinaryBridge(self.datas[0])

    def next(self):
        data = self.datas[0]
        self.outputs[data].factor[0] = self.bridge.value[0] + 1.0


class _CountingFactorStrategy(FactorStrategy):
    calculation_times_calls = 0

    def _calculation_times(self):
        type(self).calculation_times_calls += 1
        return super()._calculation_times()


def _run_factor_strategy(monkeypatch, *, runonce=False):
    index = pd.date_range("2026-01-01 16:00", periods=4, freq="D", tz="UTC", name="close_time")
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("A",),
        groups={"A": "x"},
        source_timezone="UTC",
        snapshot_id="grid-binding-test",
        price_basis="test",
        calendar_id="test",
        frequency="1day",
    )
    frame = pd.DataFrame(
        {
            name: values
            for name, values in {
                "open": [10.0, 11.0, 12.0, 13.0],
                "high": [11.0, 12.0, 13.0, 14.0],
                "low": [9.0, 10.0, 11.0, 12.0],
                "close": [10.0, 11.0, 12.0, 13.0],
                "volume": [100.0, 110.0, 120.0, 130.0],
            }.items()
        },
        index=index,
    )
    bind_calls = []
    original_bind = FactorIndicator._bind_grid

    def counted_bind(self, grid):
        bind_calls.append(self)
        return original_bind(self, grid)

    monkeypatch.setattr(FactorIndicator, "_bind_grid", counted_bind)
    _CountingFactorStrategy.calculation_times_calls = 0

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    cerebro.adddata(align_to_grid(frame, research, "A").feed, name="A")
    cerebro.addstrategy(
        _CountingFactorStrategy,
        research=research,
        factors={
            "f": FactorSpec(
                name="f",
                indicator=_GridRoot,
                panel_line="factor",
                field_bindings={"close": "feed:target:close"},
                mode="native",
            )
        },
    )
    strategy = cerebro.run(runonce=runonce)[0]
    return strategy, bind_calls


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_factor_strategy_materializes_once_and_binds_factor_below_ordinary_indicator(
    monkeypatch, runonce
):
    strategy, bind_calls = _run_factor_strategy(monkeypatch, runonce=runonce)
    root = strategy._factor_instances_by_name["f"][0]
    child = root.bridge.child
    nodes = strategy._factor_graphs[id(root)][0]

    assert _CountingFactorStrategy.calculation_times_calls == 1
    assert bind_calls == [root]
    assert set(nodes) == {root, child}
    assert all(node._factor_grid is strategy._grid for node in nodes)
    assert strategy.get_panel().factors.xs("A", level="asset")["f"].tolist() == [
        11.0,
        12.0,
        13.0,
        14.0,
    ]
    assert root.lifecycle_diagnostics["coverage_matches"]
    assert child.lifecycle_diagnostics["coverage_matches"]


def test_grid_binding_deduplicates_shared_and_cyclic_iterator_paths(monkeypatch):
    strategy, _ = _run_factor_strategy(monkeypatch)
    root = strategy._factor_instances_by_name["f"][0]
    bridge = root.bridge
    child = bridge.child

    # The binding walk must cross ordinary indicators and tolerate aliases and
    # cycles, while still assigning one shared immutable grid to factor nodes.
    bridge_children = bridge._lineiterators[LineIterator.IndType]
    bridge_children.extend((child, root))
    equal_grid = tuple(list(strategy._grid))
    assert equal_grid == strategy._grid
    assert equal_grid is not strategy._grid
    root._bind_grid(equal_grid)
    assert root._factor_grid is equal_grid
    assert child._factor_grid is equal_grid
    with pytest.raises(RuntimeError, match="cyclic nodes"):
        FactorStrategy._freeze_factor_graph(root)


def test_grid_binding_rejects_different_sequence_without_replacing_existing_grid(monkeypatch):
    strategy, _ = _run_factor_strategy(monkeypatch)
    root = strategy._factor_instances_by_name["f"][0]
    child = root.bridge.child
    original_grid = strategy._grid
    different_grid = (original_grid[0] + timedelta(seconds=1),) + original_grid[1:]

    with pytest.raises(RuntimeError, match="already bound to a different sequence"):
        root._bind_grid(different_grid)

    assert root._factor_grid is original_grid
    assert child._factor_grid is original_grid
