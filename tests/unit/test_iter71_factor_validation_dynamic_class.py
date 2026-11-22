"""Cerebro regressions for the explicitly enabled experimental fast plan.

The production validator uses the full check; this module opts in only to
keep the unaccepted fast-plan regression coverage available.
"""

from collections import defaultdict
from types import SimpleNamespace

import backtrader as bt
import pytest

from backtrader.research.factor_indicator import FactorIndicator
from backtrader.lineiterator import LineIterator
from backtrader.strategies.factor_strategy import FactorStrategy
from tests.unit.test_iter71_research_batch7_10 import (
    _CompositeFactor,
    _ProbeSink,
    _build_r71_114_cerebro,
)


@pytest.fixture(autouse=True)
def _exercise_experimental_fast_plan(monkeypatch):
    monkeypatch.setattr(
        FactorStrategy,
        "_validate_research_ownership",
        FactorStrategy._validate_research_ownership_experimental,
    )


class _DynamicClassIndicator(bt.Indicator):
    lines = ("value",)

    @property
    def __class__(self):
        state = object.__getattribute__(self, "__dict__")
        if state.get("raise_from_class", False):
            raise RuntimeError("dynamic class failed")
        return FactorIndicator if state.get("pretend_factor", False) else type(self)

    def next(self):
        self.lines.value[0] = 0.0


class _PlainIndicator(bt.Indicator):
    lines = ("value",)

    def next(self):
        self.lines.value[0] = 0.0


def _install_deep_dynamic_node(monkeypatch, node_class=_DynamicClassIndicator):
    original = _CompositeFactor.__init__

    def initialize(self, *args, **kwargs):
        original(self, *args, **kwargs)
        node = node_class(self.datas[0])
        # Register it below an existing nested factor, so it exercises both
        # graph traversal and the per-object factor classification.
        children = node._owner._lineiterators[node._ltype]
        index = next(i for i, child in enumerate(children) if child is node)
        children.pop(index)
        node._owner = self.left
        self.left._lineiterators[node._ltype].append(node)
        self.dynamic_node = node

    monkeypatch.setattr(_CompositeFactor, "__init__", initialize)


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("exception", [False, True])
def test_dynamic_class_falls_back_or_propagates_before_next_point(monkeypatch, runonce, exception):
    _install_deep_dynamic_node(monkeypatch)
    observations = []

    class MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor == 1:
                node = self._factor_instances_by_name["f"][0].dynamic_node
                setattr(node, "raise_from_class" if exception else "pretend_factor", True)
                if not exception:
                    observations.append(self._factor_validation_fast_plan is None)
            super()._collect_grid_point()

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=MutatingStrategy, sink=sink, periods=4
    )
    expected = "dynamic class failed" if exception else "factor graph changed"
    with pytest.raises(RuntimeError, match=expected):
        cerebro.run(runonce=runonce)
    if not exception:
        assert observations == [True]
    assert len(sink.points) == 1
    assert sink.closed and not sink.finalized


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("access_kind", ["getattribute", "clock_property"])
def test_clock_accessors_do_not_add_ownership_failures(monkeypatch, runonce, access_kind):
    _install_deep_dynamic_node(monkeypatch, _PlainIndicator)
    observations = []

    class MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor != 1:
                return super()._collect_grid_point()
            node = self._factor_instances_by_name["f"][0].dynamic_node
            assert self._factor_validation_fast_plan is not None
            reads = []
            with monkeypatch.context() as patch:
                if access_kind == "getattribute":
                    original = _PlainIndicator.__getattribute__

                    def guarded(obj, name):
                        if obj is node and name == "_clock":
                            reads.append(name)
                            raise RuntimeError("clock getter was called")
                        return original(obj, name)

                    patch.setattr(_PlainIndicator, "__getattribute__", guarded)
                else:
                    def clock_property(_obj):
                        reads.append("_clock")
                        raise RuntimeError("clock property was called")

                    patch.setattr(_PlainIndicator, "_clock", property(clock_property), raising=False)
                # Compare to the full validator, clearing its instance scratch
                # just as the public wrapper does before the next validation.
                try:
                    self._validate_research_ownership_full()
                finally:
                    self._factor_validation_child_counts.clear()
                    self._factor_validation_host_counts.clear()
                    self._factor_validation_observed.clear()
                    self._factor_validation_visited.clear()
                    self._factor_validation_pending.clear()
                super()._collect_grid_point()
                observations.append(tuple(reads))

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=MutatingStrategy, sink=sink, periods=4
    )
    cerebro.run(runonce=runonce)
    assert observations == [()]
    assert len(sink.points) == 4
    assert sink.closed and sink.finalized


@pytest.mark.parametrize("runonce", [False, True])
def test_custom_getattribute_has_same_owner_reads_as_full(monkeypatch, runonce):
    _install_deep_dynamic_node(monkeypatch, _PlainIndicator)
    observations = []

    class MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor != 1:
                return super()._collect_grid_point()
            node = self._factor_instances_by_name["f"][0].dynamic_node
            counts = []
            reads = []
            original = _PlainIndicator.__getattribute__

            def counting(obj, name):
                if obj is node and name == "_owner":
                    reads.append(name)
                return original(obj, name)

            with monkeypatch.context() as patch:
                patch.setattr(_PlainIndicator, "__getattribute__", counting)
                try:
                    self._validate_research_ownership_full()
                    counts.append(len(reads))
                finally:
                    self._factor_validation_child_counts.clear()
                    self._factor_validation_host_counts.clear()
                    self._factor_validation_observed.clear()
                    self._factor_validation_visited.clear()
                    self._factor_validation_pending.clear()
                reads.clear()
                super()._collect_grid_point()
                counts.append(len(reads))
            observations.append(tuple(counts))

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=MutatingStrategy, sink=sink, periods=4
    )
    cerebro.run(runonce=runonce)
    assert observations[0][0] > 0
    assert observations[0][0] == observations[0][1]
    assert len(sink.points) == 4


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("install_before_build", [False, True])
def test_custom_getattr_is_not_consumed_before_full(monkeypatch, runonce, install_before_build):
    def changing_owner(node, name):
        state = object.__getattribute__(node, "__dict__")
        if name == "_owner" and "owner_backup" in state:
            state["owner_reads"] += 1
            return object() if state["owner_reads"] == 1 else state["owner_backup"]
        return super(_PlainIndicator, node).__getattr__(name)

    _install_deep_dynamic_node(monkeypatch, _PlainIndicator)
    if install_before_build:
        monkeypatch.setattr(_PlainIndicator, "__getattr__", changing_owner)
    observations = []

    class MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor == 1:
                node = self._factor_instances_by_name["f"][0].dynamic_node
                observations.append(self._factor_validation_fast_plan is None)
                if not install_before_build:
                    monkeypatch.setattr(_PlainIndicator, "__getattr__", changing_owner)
                state = object.__getattribute__(node, "__dict__")
                state["owner_backup"] = state.pop("_owner")
                state["owner_reads"] = 0
            super()._collect_grid_point()

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=MutatingStrategy, sink=sink, periods=4
    )
    with pytest.raises(RuntimeError, match="factor graph changed"):
        cerebro.run(runonce=runonce)
    assert observations == [install_before_build]
    assert len(sink.points) == 1
    assert sink.closed and not sink.finalized


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("install_before_build", [False, True])
def test_stateful_cerebro_getter_is_not_consumed_before_full(
    monkeypatch, runonce, install_before_build
):
    state = {"armed": False, "reads": 0}
    original = bt.Cerebro.__getattribute__

    def changing_strategies(cerebro, name):
        if name == "runningstrats" and state["armed"]:
            state["reads"] += 1
            if state["reads"] == 1:
                return [state["rogue"]]
        return original(cerebro, name)

    if install_before_build:
        monkeypatch.setattr(bt.Cerebro, "__getattribute__", changing_strategies)
    observations = []

    class MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor == 1:
                root = self._factor_instances_by_name["f"][0]
                observations.append(self._factor_validation_fast_plan is None)
                state["rogue"] = SimpleNamespace(
                    _lineiterators={LineIterator.IndType: [root]}
                )
                if not install_before_build:
                    monkeypatch.setattr(bt.Cerebro, "__getattribute__", changing_strategies)
                state["armed"] = True
            super()._collect_grid_point()

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=MutatingStrategy, sink=sink, periods=4
    )
    with pytest.raises(RuntimeError, match="multiple scheduling paths"):
        cerebro.run(runonce=runonce)
    assert observations == [install_before_build]
    assert state["reads"] >= 1
    assert len(sink.points) == 1
    assert sink.closed and not sink.finalized


@pytest.mark.parametrize("runonce", [False, True])
def test_stateful_cerebro_runningstrats_property_is_not_consumed_before_full(monkeypatch, runonce):
    state = {"reads": 0}

    class MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor != 1:
                return super()._collect_grid_point()
            cerebro = self.cerebro
            root = self._factor_instances_by_name["f"][0]
            actual = object.__getattribute__(cerebro, "__dict__")["runningstrats"]
            rogue = SimpleNamespace(_lineiterators={LineIterator.IndType: [root]})

            def changing_strategies(_cerebro):
                state["reads"] += 1
                return [rogue] if state["reads"] == 1 else actual

            with monkeypatch.context() as patch:
                patch.setattr(bt.Cerebro, "runningstrats", property(changing_strategies), raising=False)
                super()._collect_grid_point()

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=MutatingStrategy, sink=sink, periods=4
    )
    with pytest.raises(RuntimeError, match="multiple scheduling paths"):
        cerebro.run(runonce=runonce)
    assert state["reads"] == 1
    assert len(sink.points) == 1
    assert sink.closed and not sink.finalized


@pytest.mark.parametrize("runonce", [False, True])
def test_stateful_strategy_getter_is_not_consumed_before_full(monkeypatch, runonce):
    state = {"reads": 0}

    class MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor == 1:
                assert self._factor_validation_fast_plan is not None
                original = MutatingStrategy.__getattribute__

                def changing_graphs(strategy, name):
                    if strategy is self and name == "_factor_validation_graphs":
                        state["reads"] += 1
                        if state["reads"] == 1:
                            return {}
                    return original(strategy, name)

                monkeypatch.setattr(MutatingStrategy, "__getattribute__", changing_graphs)
            super()._collect_grid_point()

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=MutatingStrategy, sink=sink, periods=4
    )
    with pytest.raises(RuntimeError, match="factor graph changed"):
        cerebro.run(runonce=runonce)
    assert state["reads"] >= 1
    assert len(sink.points) == 1
    assert sink.closed and not sink.finalized


@pytest.mark.parametrize("runonce", [False, True])
def test_descriptor_type_metaclass_getter_is_not_called(monkeypatch, runonce):
    _install_deep_dynamic_node(monkeypatch, _PlainIndicator)
    calls = []

    class RaisingMeta(type):
        def __getattribute__(cls, name):
            if name == "__get__":
                calls.append(name)
                raise RuntimeError("descriptor metaclass getter ran")
            return type.__getattribute__(cls, name)

        @property
        def __mro__(cls):
            calls.append("__mro__")
            raise RuntimeError("descriptor metaclass mro ran")

        @property
        def __dict__(cls):
            calls.append("__dict__")
            raise RuntimeError("descriptor metaclass dict ran")

    class Sentinel(metaclass=RaisingMeta):
        pass

    class MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor != 1:
                return super()._collect_grid_point()
            assert self._factor_validation_fast_plan is not None
            with monkeypatch.context() as patch:
                patch.setattr(_PlainIndicator, "_owner", Sentinel(), raising=False)
                try:
                    self._validate_research_ownership_full()
                finally:
                    self._factor_validation_child_counts.clear()
                    self._factor_validation_host_counts.clear()
                    self._factor_validation_observed.clear()
                    self._factor_validation_visited.clear()
                    self._factor_validation_pending.clear()
                super()._collect_grid_point()

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=MutatingStrategy, sink=sink, periods=4
    )
    cerebro.run(runonce=runonce)
    assert calls == []
    assert len(sink.points) == 4
    assert sink.closed and sink.finalized


@pytest.mark.parametrize("runonce", [False, True])
def test_node_type_metaclass_descriptors_are_not_called(monkeypatch, runonce):
    calls = []
    state = {"armed": False}

    class NodeMeta(type):
        @property
        def __mro__(cls):
            if state["armed"]:
                calls.append("__mro__")
                raise RuntimeError("node metaclass property ran")
            return type.__dict__["__mro__"].__get__(cls, type(cls))

        @property
        def __dict__(cls):
            if state["armed"]:
                calls.append("__dict__")
                raise RuntimeError("node metaclass property ran")
            return type.__dict__["__dict__"].__get__(cls, type(cls))

        @property
        def __getattribute__(cls):
            if state["armed"]:
                calls.append("__getattribute__")
                raise RuntimeError("node metaclass property ran")
            return type.__getattribute__.__get__(cls, type(cls))

    class Node(_PlainIndicator, metaclass=NodeMeta):
        pass

    _install_deep_dynamic_node(monkeypatch, Node)

    class MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor == 1:
                assert self._factor_validation_fast_plan is not None
                state["armed"] = True
                try:
                    assert self._check_factor_validation_fast_plan(
                        self._factor_validation_fast_plan
                    )
                finally:
                    state["armed"] = False
            super()._collect_grid_point()

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=MutatingStrategy, sink=sink, periods=4
    )
    cerebro.run(runonce=runonce)
    assert calls == []
    assert len(sink.points) == 4
    assert sink.closed and sink.finalized


@pytest.mark.parametrize("runonce", [False, True])
def test_factor_name_key_equality_is_not_called_by_fast_path(runonce):
    state = {"armed": False, "calls": 0}

    class Name(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            if state["armed"]:
                state["calls"] += 1
                raise RuntimeError("factor name equality was called")
            return str.__eq__(self, other)

    class MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor == 1:
                original = self._factor_instances_by_name
                self._factor_instances_by_name = {Name(k): v for k, v in original.items()}
                state["armed"] = True
                try:
                    try:
                        self._validate_research_ownership_full()
                    finally:
                        self._factor_validation_child_counts.clear()
                        self._factor_validation_host_counts.clear()
                        self._factor_validation_observed.clear()
                        self._factor_validation_visited.clear()
                        self._factor_validation_pending.clear()
                    self._validate_research_ownership()
                finally:
                    state["armed"] = False
                    self._factor_instances_by_name = original
            super()._collect_grid_point()

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=MutatingStrategy, sink=sink, periods=4
    )
    cerebro.run(runonce=runonce)
    assert state["calls"] == 0
    assert len(sink.points) == 4
    assert sink.closed and sink.finalized


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("location", ["node_fields", "buckets", "graph_index"])
def test_nonbuiltin_keys_do_not_run_equality_before_full(runonce, location):
    state = {"armed": False, "calls": 0}

    class Name(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            if state["armed"]:
                state["calls"] += 1
                raise RuntimeError("field equality was called")
            return str.__eq__(self, other)

    class Number(int):
        __hash__ = int.__hash__

        def __eq__(self, other):
            if state["armed"]:
                state["calls"] += 1
                raise RuntimeError("index equality was called")
            return int.__eq__(self, other)

    observations = []

    class MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor == 1:
                root = self._factor_instances_by_name["f"][0]
                if location == "node_fields":
                    target = object.__getattribute__(root.left, "__dict__")
                    saved = target.copy()
                    value = target.pop("_owner")
                    target[Name("_owner")] = value
                else:
                    target = (root._lineiterators if location == "buckets"
                              else self._factor_validation_graphs)
                    saved = target.copy()
                    entries = [(Number(key), value) for key, value in target.items()]
                    target.clear()
                    target.update(entries)
                state["armed"] = True
                try:
                    observations.append(self._check_factor_validation_fast_plan(
                        self._factor_validation_fast_plan
                    ))
                finally:
                    state["armed"] = False
                    target.clear()
                    target.update(saved)
            super()._collect_grid_point()

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=MutatingStrategy, sink=sink, periods=4
    )
    cerebro.run(runonce=runonce)
    assert observations == [False]
    assert state["calls"] == 0
    assert len(sink.points) == 4


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("location", ["root", "nested", "host"])
def test_mapping_replacement_invalidates_even_with_identical_edges(runonce, location):
    observations = []

    class MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor == 1:
                root = self._factor_instances_by_name["f"][0]
                node = {"root": root, "nested": root.left, "host": self}[location]
                old = node._lineiterators
                node._lineiterators = defaultdict(list, {k: list(v) for k, v in old.items()})
                observations.append(self._check_factor_validation_fast_plan(
                    self._factor_validation_fast_plan
                ))
            super()._collect_grid_point()

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=MutatingStrategy, sink=sink, periods=4
    )
    cerebro.run(runonce=runonce)
    assert observations == [False]
    assert len(sink.points) == 4
    assert sink.closed and sink.finalized


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("index", ["graphs", "root_by_id", "expected_parents", "nested_ids", "children"])
def test_mutated_validation_indexes_do_not_skip_full_check(runonce, index):
    observations = []

    class MutatingStrategy(FactorStrategy):
        def _collect_grid_point(self):
            if self._grid_cursor == 1:
                root = self._factor_instances_by_name["f"][0]
                if index == "graphs":
                    self._factor_validation_graphs[id(root)] = ((), ())
                elif index == "root_by_id":
                    self._factor_validation_root_by_id[id(root)] = object()
                elif index == "expected_parents":
                    self._factor_validation_expected_parents[id(root)] = -1
                elif index == "nested_ids":
                    self._factor_validation_nested_ids.add(id(root))
                else:
                    children = next(c for _, c, _ in self._factor_validation_parents if c)
                    children.clear()
                observations.append(self._check_factor_validation_fast_plan(
                    self._factor_validation_fast_plan
                ))
            super()._collect_grid_point()

    sink = _ProbeSink()
    cerebro = _build_r71_114_cerebro(
        runonce=runonce, strategy_cls=MutatingStrategy, sink=sink, periods=4
    )
    with pytest.raises(RuntimeError, match="factor graph|multiple scheduling"):
        cerebro.run(runonce=runonce)
    assert observations == [False]
    assert len(sink.points) == 1
    assert sink.closed and not sink.finalized
