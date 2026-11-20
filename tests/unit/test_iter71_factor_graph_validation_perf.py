"""Per-bar factor graph validation remains mutation-sensitive with an index."""

import backtrader as bt
import pandas as pd
import pytest

from backtrader.lineiterator import LineIterator
from backtrader.research import (
    FactorIndicator,
    FactorSink,
    FactorSpec,
    ResearchSpec,
    align_to_grid,
)
from backtrader.strategies.factor_strategy import FactorStrategy


class _Leaf(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.close_line = self.field_lines("close")[0]

    def next(self):
        self.outputs[self.target_datas[0]].factor[0] = self.close_line[0]


class _PairRoot(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self.left = _Leaf.bind(*self.target_datas)
        self.right = _Leaf.bind(*self.target_datas)

    def next(self):
        data = self.target_datas[0]
        self.outputs[data].factor[0] = (
            self.left.outputs[data].factor[0] + self.right.outputs[data].factor[0]
        )


class _ProbeSink(FactorSink):
    def __init__(self):
        self.points = []
        self.finalized = False
        self.closed = False

    def on_point(self, *args):
        self.points.append(args)

    def finalize(self, context):
        self.finalized = True
        return object()

    def close(self):
        self.closed = True


class _ReplaceContainerAtStart(FactorStrategy):
    def start(self):
        root = self._factor_instances_by_name["f"][0]
        root._lineiterators[LineIterator.IndType] = list(root._lineiterators[LineIterator.IndType])


class _ReplaceContainerAfterFirstBar(FactorStrategy):
    def _collect_grid_point(self):
        if self._grid_cursor == 1:
            root = self._factor_instances_by_name["f"][0]
            root._lineiterators[LineIterator.IndType] = list(
                root._lineiterators[LineIterator.IndType]
            )
        super()._collect_grid_point()


class _ReplaceChildAfterFirstBar(FactorStrategy):
    def _collect_grid_point(self):
        if self._grid_cursor == 1:
            root = self._factor_instances_by_name["f"][0]
            root._lineiterators[LineIterator.IndType][0] = root.right
        super()._collect_grid_point()


class _ChangeOwnerAfterFirstBar(FactorStrategy):
    def _collect_grid_point(self):
        if self._grid_cursor == 1:
            root = self._factor_instances_by_name["f"][0]
            root.left._owner = self
        super()._collect_grid_point()


class _MigrateChildBucketAfterFirstBar(FactorStrategy):
    def _collect_grid_point(self):
        if self._grid_cursor == 1:
            root = self._factor_instances_by_name["f"][0]
            lineiterators = root._lineiterators
            lineiterators[LineIterator.IndType].remove(root.left)
            lineiterators[LineIterator.ObsType].append(root.left)
            root.left._ltype = LineIterator.ObsType
        super()._collect_grid_point()


def _cerebro(runonce, strategy, sink):
    index = pd.date_range("2025-03-01 16:00", periods=5, tz="UTC", name="close_time")
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("A",),
        groups={"A": "x"},
        source_timezone="UTC",
        snapshot_id="iter71-factor-validation",
        price_basis="test",
        calendar_id="test",
        frequency="1day",
    )
    values = [10.0 + i for i in range(len(index))]
    frame = pd.DataFrame(
        dict.fromkeys(("open", "high", "low", "close", "volume"), values), index=index
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    cerebro.adddata(align_to_grid(frame, research, "A").feed, name="A")
    cerebro.addstrategy(
        strategy,
        research=research,
        factors={
            "f": FactorSpec(
                name="f",
                indicator=_PairRoot,
                panel_line="factor",
                field_bindings={"close": "feed:target:close"},
                mode="native",
            )
        },
        sink=sink,
    )
    return cerebro


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("strategy", [_ReplaceContainerAtStart, _ReplaceContainerAfterFirstBar])
def test_equivalent_child_list_replacement_remains_valid(runonce, strategy):
    sink = _ProbeSink()
    cerebro = _cerebro(runonce, strategy, sink)

    (_result,) = cerebro.run(runonce=runonce)

    assert len(sink.points) == 5
    assert sink.finalized and sink.closed
    assert [point[2]["f"] for point in sink.points] == [20.0, 22.0, 24.0, 26.0, 28.0]


@pytest.mark.parametrize(
    "strategy",
    [
        _ReplaceChildAfterFirstBar,
        _ChangeOwnerAfterFirstBar,
        _MigrateChildBucketAfterFirstBar,
    ],
    ids=["same_length_child_replacement", "owner_change", "ltype_bucket_migration"],
)
@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_live_child_identity_and_owner_changes_block_later_sink_points(runonce, strategy):
    sink = _ProbeSink()
    cerebro = _cerebro(runonce, strategy, sink)

    with pytest.raises(RuntimeError, match="factor graph changed"):
        cerebro.run(runonce=runonce)

    assert len(sink.points) == 1
    assert not sink.finalized
    assert sink.closed


def test_instance_scratch_rejects_overlapping_validation_call():
    sink = _ProbeSink()
    (strategy,) = _cerebro(False, FactorStrategy, sink).run(runonce=False)

    assert strategy._factor_validation_lock.acquire(blocking=False)
    try:
        with pytest.raises(RuntimeError, match="validation is already active"):
            strategy._validate_research_ownership()
    finally:
        strategy._factor_validation_lock.release()
