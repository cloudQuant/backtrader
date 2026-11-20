"""Regression tests for live-guarded panel input relation plans."""

from __future__ import annotations

import pandas as pd
import pytest

import backtrader as bt
import backtrader.research.operators as operators
from backtrader.research.operators import (
    Add,
    CrossSectionalRank,
    OperatorInputError,
)


def _frame(offset: float, count: int = 8) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=count, freq="D")
    close = [offset + float(i + 1) for i in range(count)]
    open_ = [value + 0.25 for value in close]
    return pd.DataFrame(
        {
            "open": open_,
            "high": [value + 1.0 for value in close],
            "low": [value - 1.0 for value in close],
            "close": close,
            "volume": [100.0] * count,
            "openinterest": [0.0] * count,
        },
        index=index,
    )


def _add_feeds(cerebro: bt.Cerebro, count: int = 3) -> None:
    for index in range(count):
        cerebro.adddata(
            bt.feeds.PandasData(dataname=_frame(10.0 * index)),
            name="asset-%d" % index,
        )


@pytest.mark.parametrize(
    "exactbars",
    (pytest.param(False, id="standard"), pytest.param(1, id="exactbars-qbuffer")),
)
def test_panel_value_and_right_value_relations_are_resolved_at_bind_not_each_bar(
    monkeypatch, exactbars
):
    original = operators._line_target_relation
    calls = [0]

    def counted(source, target, seen=None):
        calls[0] += 1
        return original(source, target, seen)

    monkeypatch.setattr(operators, "_line_target_relation", counted)

    class PanelRelationProbe(bt.Strategy):
        def __init__(self):
            feeds = tuple(self.datas)
            self.value_nodes = tuple(
                Add(Add(data.close, data.open).value, 2.0) for data in feeds
            )
            self.right_nodes = tuple(
                Add(data.high, data.low) for data in feeds
            )
            values = tuple(node.value for node in self.value_nodes)
            right_values = tuple(node.value for node in self.right_nodes)
            self.rank = CrossSectionalRank.bind(*feeds, values=values)
            self.product = operators._MultiplyPanel.bind(
                *feeds, values=values, right_values=right_values
            )
            self.rows = []

        def start(self):
            # Bind-time relation proofs may consult the slow resolver once;
            # the live path should use their structural guard after this point.
            self.relation_calls_at_start = calls[0]

        def next(self):
            if not self.rows:
                self.feeds_use_qbuffer = all(
                    data.close.mode == operators.LineBuffer.QBuffer
                    for data in self.datas
                )
            self.rows.append(
                tuple(self.rank.outputs[data].value[0] for data in self.datas)
            )

        def stop(self):
            self.runtime_relation_calls = calls[0] - self.relation_calls_at_start

    cerebro = bt.Cerebro(
        stdstats=False, runonce=False, preload=False, exactbars=exactbars
    )
    _add_feeds(cerebro)
    cerebro.addstrategy(PanelRelationProbe)
    strategy = cerebro.run()[0]

    assert len(strategy.rows) == 8
    assert strategy.runtime_relation_calls == 0
    assert strategy.feeds_use_qbuffer is bool(exactbars)
    for data in strategy.datas:
        assert strategy.rank.outputs[data].value[0] == pytest.approx(
            (strategy.datas.index(data) + 1) / len(strategy.datas)
        )
        assert strategy.product.outputs[data].value[0] == pytest.approx(
            strategy.value_nodes[strategy.datas.index(data)].value[0]
            * strategy.right_nodes[strategy.datas.index(data)].value[0]
        )


def test_cross_feed_panel_input_remains_fail_closed():
    class CrossFeedProbe(bt.Strategy):
        def __init__(self):
            feeds = tuple(self.datas)
            self.rank = CrossSectionalRank.bind(
                *feeds,
                values=(Add(feeds[1].close, feeds[1].open).value, feeds[1].close),
            )

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    _add_feeds(cerebro, count=2)
    cerebro.addstrategy(CrossFeedProbe)

    with pytest.raises(OperatorInputError, match="target feed"):
        cerebro.run()


def test_relation_plan_topology_change_falls_back_and_stays_fail_closed(monkeypatch):
    original = operators._line_target_relation
    calls = [0]

    def counted(source, target, seen=None):
        calls[0] += 1
        return original(source, target, seen)

    monkeypatch.setattr(operators, "_line_target_relation", counted)

    class MutatedTopologyProbe(bt.Strategy):
        def __init__(self):
            feeds = tuple(self.datas)
            self.source = Add(feeds[0].close, feeds[0].open)
            self.rank = CrossSectionalRank.bind(
                *feeds, values=(self.source.value, feeds[1].close)
            )

        def start(self):
            self.calls_before_mutation = calls[0]
            # Change both the expression edge and its target claim. The plan
            # must miss, then the ordinary resolver must reject the cross-feed
            # relation rather than reuse the bind-time proof.
            self.source._operand_args = (self.datas[1].close, self.datas[0].open)
            self.source.value._factor_research_target = self.datas[1]

        def next(self):
            self.rank.outputs[self.datas[0]].value[0]

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    _add_feeds(cerebro, count=2)
    cerebro.addstrategy(MutatedTopologyProbe)

    with pytest.raises(OperatorInputError, match="target feed"):
        cerebro.run()

    assert calls[0] > 0


def test_relation_plan_falls_back_when_mro_adds_a_shadowing_data_descriptor(
    monkeypatch,
):
    original = operators._line_target_relation
    calls = [0]
    calls_at_mutation = []

    def counted(source, target, seen=None):
        calls[0] += 1
        return original(source, target, seen)

    monkeypatch.setattr(operators, "_line_target_relation", counted)

    class DescriptorMutationProbe(bt.Strategy):
        def __init__(self):
            feeds = tuple(self.datas)
            self.source = Add(feeds[0].close, feeds[0].open).value
            self.source._factor_research_target = feeds[0]
            self.rank = CrossSectionalRank.bind(*feeds, values=(self.source, feeds[1].close))

        def start(self):
            calls_at_mutation.append(calls[0])
            other_feed = self.datas[1]
            monkeypatch.setattr(
                operators.LineBuffer,
                "_factor_research_target",
                property(lambda _line: other_feed),
                raising=False,
            )

        def next(self):
            self.rank.outputs[self.datas[0]].value[0]

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    _add_feeds(cerebro, count=2)
    cerebro.addstrategy(DescriptorMutationProbe)

    with pytest.raises(OperatorInputError, match="target feed"):
        cerebro.run()

    assert calls_at_mutation
    assert calls[0] > calls_at_mutation[0]


def test_relation_plan_falls_back_when_mro_adds_a_descriptor_mixin(monkeypatch):
    original = operators._line_target_relation
    original_bases = operators.LineBuffer.__bases__
    original_mro = operators.LineBuffer.__mro__
    calls = [0]
    calls_at_mutation = []
    mutated_mros = []
    bases_changed = [False]

    def counted(source, target, seen=None):
        calls[0] += 1
        return original(source, target, seen)

    monkeypatch.setattr(operators, "_line_target_relation", counted)

    class MroMutationProbe(bt.Strategy):
        def __init__(self):
            feeds = tuple(self.datas)
            self.source = Add(feeds[0].close, feeds[0].open).value
            self.source._factor_research_target = feeds[0]
            self.rank = CrossSectionalRank.bind(*feeds, values=(self.source, feeds[1].close))

        def start(self):
            calls_at_mutation.append(calls[0])
            other_feed = self.datas[1]

            class TargetClaimMixin:
                @property
                def _factor_research_target(self):
                    return other_feed

            operators.LineBuffer.__bases__ = original_bases + (TargetClaimMixin,)
            bases_changed[0] = True
            mutated_mros.append(operators.LineBuffer.__mro__)

        def next(self):
            self.rank.outputs[self.datas[0]].value[0]

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    _add_feeds(cerebro, count=2)
    cerebro.addstrategy(MroMutationProbe)

    try:
        with pytest.raises(OperatorInputError, match="target feed"):
            cerebro.run()
    finally:
        if bases_changed[0]:
            operators.LineBuffer.__bases__ = original_bases

    assert mutated_mros
    assert mutated_mros[0] is not original_mro
    assert operators.LineBuffer.__bases__ == original_bases
    assert calls_at_mutation
    assert calls[0] > calls_at_mutation[0]


def test_rolling_window_relations_remain_fast_in_exactbars_qbuffer(monkeypatch):
    original = operators._line_target_relation
    calls = [0]

    def counted(source, target, seen=None):
        calls[0] += 1
        return original(source, target, seen)

    monkeypatch.setattr(operators, "_line_target_relation", counted)

    class RollingWindowProbe(bt.Strategy):
        def __init__(self):
            feeds = tuple(self.datas)
            self.left_nodes = tuple(
                Add(data.close, data.open) for data in feeds
            )
            self.right_nodes = tuple(
                Add(data.high, data.low) for data in feeds
            )
            self.correlation = operators._RollingCorrelationPanel.bind(
                *feeds,
                period=3,
                values=tuple(node.value for node in self.left_nodes),
                right_values=tuple(node.value for node in self.right_nodes),
            )
            self.rows = []

        def start(self):
            self.relation_calls_at_start = calls[0]

        def next(self):
            if not self.rows:
                self.inputs_use_qbuffer = all(
                    node.value.mode == operators.LineBuffer.QBuffer
                    for node in self.left_nodes + self.right_nodes
                )
            self.rows.append(
                tuple(
                    self.correlation.outputs[data].value[0]
                    for data in self.datas
                )
            )

        def stop(self):
            self.runtime_relation_calls = calls[0] - self.relation_calls_at_start

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False, exactbars=1)
    _add_feeds(cerebro, count=2)
    cerebro.addstrategy(RollingWindowProbe)
    strategy = cerebro.run()[0]

    assert len(strategy.rows) == 6
    assert strategy.inputs_use_qbuffer
    assert strategy.runtime_relation_calls == 0
    assert all(value == pytest.approx(1.0) for row in strategy.rows for value in row)


def test_custom_indicator_relation_keeps_the_general_resolver_fallback(monkeypatch):
    original = operators._line_target_relation
    calls = [0]

    def counted(source, target, seen=None):
        calls[0] += 1
        return original(source, target, seen)

    monkeypatch.setattr(operators, "_line_target_relation", counted)

    class CustomSource(bt.Indicator):
        lines = ("value",)

        def __getattribute__(self, name):
            return super().__getattribute__(name)

        def next(self):
            self.lines.value[0] = self.data.close[0] * 2.0

    class CustomSourceProbe(bt.Strategy):
        def __init__(self):
            feed = self.data
            self.source = CustomSource(feed)
            self.rank = CrossSectionalRank.bind(
                feed, values=(self.source.value,)
            )
            self.rows = []

        def start(self):
            self.relation_calls_at_start = calls[0]

        def next(self):
            self.rows.append(self.rank.outputs[self.data].value[0])

        def stop(self):
            self.runtime_relation_calls = calls[0] - self.relation_calls_at_start

    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    _add_feeds(cerebro, count=1)
    cerebro.addstrategy(CustomSourceProbe)
    strategy = cerebro.run()[0]

    assert len(strategy.rows) == 8
    assert strategy.runtime_relation_calls >= len(strategy.rows)
