"""Focused contracts for the guarded formula-presence relation fast path."""

from types import SimpleNamespace

import pytest

import tests.unit.test_factor_research_representatives as representatives
import backtrader.research.operators as alpha_operators
from backtrader.errors import FactorComputationError
from backtrader.linebuffer import LineBuffer
from backtrader.research import align_to_grid
from backtrader.research._helpers import panel
from backtrader.research.alpha101 import get_alpha
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.operators import CrossSectionalRank, OperatorReason
from tests.unit.test_factor_research_representatives import _frames, _run_subset


class _PresencePlanProbe(FactorIndicator):
    lines = ("factor",)
    alpha_id = 97
    case_id = "AF49-097-presence-relation-probe"
    lookback_h = 0
    formula = "rank(close) with ordinary formula-membership lines"
    formula_fields = ("close",)
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        self._result_lines = panel(
            self, "rank", CrossSectionalRank, self.field_lines("close")
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


class _ForeignPresencePlanProbe(_PresencePlanProbe):
    alpha_id = 98
    case_id = "AF49-098-foreign-presence-relation-probe"
    formula = "rank(close) with the first value bound to the next target"

    def __init__(self):
        FactorIndicator.__init__(self)
        self._nodes = {}
        close = self.field_lines("close")
        self._result_lines = panel(
            self, "rank_foreign", CrossSectionalRank, (close[1], close[0], close[2])
        )
        self.addminperiod(self.lookback_h + 1)


def _exact_aligned_feed(frame, research, asset):
    return align_to_grid(frame, research, asset).feed


def _run_three_assets(monkeypatch, factor_class=_PresencePlanProbe):
    monkeypatch.setattr(representatives, "_research_feed", _exact_aligned_feed)
    all_frames = _frames(periods=2)
    frames = {name: frame.copy(deep=True) for name, frame in list(all_frames.items())[:3]}
    strategy = _run_subset(frames, {"probe": factor_class}, runonce=False)
    return frames, strategy, strategy.factor_instances["probe"]._nodes[
        "rank" if factor_class is _PresencePlanProbe else "rank_foreign"
    ]


def test_standard_presence_members_use_a_guarded_plan_and_live_array(monkeypatch):
    frames, _, node = _run_three_assets(monkeypatch)
    assert len(node._member_relation_plans) == len(frames) == 3
    calls = []
    original = alpha_operators._line_target_relation

    def counted(source, target, seen=None):
        calls.append((source, target))
        return original(source, target, seen)

    monkeypatch.setattr(alpha_operators, "_line_target_relation", counted)
    for member, target, plan in zip(
        node._members, node._factor_target_datas, node._member_relation_plans
    ):
        assert plan is not None
        assert type(plan.owner) is alpha_operators._PresenceLine.lines
        assert alpha_operators._standard_lines_instance(plan.owner)
        assert plan.resolve(member, target) is True
        index = int(alpha_operators._target_clock_line(target)._idx)
        old_value = member.array[index]
        new_value = 0.0 if old_value != 0.0 else 1.0
        member.array[index] = new_value
        try:
            assert alpha_operators._read_panel_value(member, target, plan) == (
                new_value,
                OperatorReason.READY,
            )
        finally:
            member.array[index] = old_value
    assert calls == []


def test_custom_derived_presence_lines_container_falls_back(monkeypatch):
    _, _, node = _run_three_assets(monkeypatch)
    member, target, plan = (
        node._members[0],
        node._factor_target_datas[0],
        node._member_relation_plans[0],
    )
    assert plan is not None
    custom_lines_type = type(
        "CustomPresenceLines", (type(plan.owner),), {"__module__": __name__}
    )
    custom_owner = object.__new__(custom_lines_type)
    object.__setattr__(custom_owner, "_owner_ref", plan.indicator)
    object.__setattr__(custom_owner, "lines", [member])
    source_state = object.__getattribute__(member, "__dict__")
    original_owner = source_state["_owner"]
    source_state["_owner"] = custom_owner
    try:
        assert plan.resolve(member, target) is alpha_operators._PANEL_RELATION_MISS
        assert alpha_operators._presence_line_relation_plan(member, target) is None
    finally:
        source_state["_owner"] = original_owner


@pytest.mark.parametrize(
    "change",
    (
        "owner",
        "owner_lines",
        "target_marker",
        "indicator_datas",
        "source_marker",
    ),
)
def test_stale_presence_provenance_falls_back_to_the_original_resolver(monkeypatch, change):
    _, strategy, node = _run_three_assets(monkeypatch)
    member, target, plan = (
        node._members[0],
        node._factor_target_datas[0],
        node._member_relation_plans[0],
    )
    assert plan is not None
    source_state = object.__getattribute__(member, "__dict__")
    target_state = object.__getattribute__(target, "__dict__")
    missing = object()
    old_source_marker = source_state.get("_factor_research_target", missing)
    old_target_marker = target_state.get("_factor_research_target", missing)
    owner = source_state["_owner"]
    owner_state = object.__getattribute__(owner, "__dict__")
    if change == "owner":
        source_state["_owner"] = SimpleNamespace(_owner_ref=owner_state["_owner_ref"])
    elif change == "owner_lines":
        target_lines = owner_state["lines"]
        target_lines.remove(member)
    elif change == "target_marker":
        target_state["_factor_research_target"] = object()
    elif change == "indicator_datas":
        datas = object.__getattribute__(owner_state["_owner_ref"], "__dict__")["datas"]
        datas[0] = strategy.factor_instances["probe"]._factor_target_datas[1]
    else:
        source_state["_factor_research_target"] = strategy.factor_instances["probe"]._factor_target_datas[1]

    calls = []
    original = alpha_operators._line_target_relation

    def counted(source, selected_target, seen=None):
        calls.append((source, selected_target))
        return original(source, selected_target, seen)

    monkeypatch.setattr(alpha_operators, "_line_target_relation", counted)
    try:
        assert plan.resolve(member, target) is alpha_operators._PANEL_RELATION_MISS
        relation = alpha_operators._resolve_panel_relation(member, target, plan)
        expected_relation = {
            "source_marker": False,
            "indicator_datas": None,
        }.get(change, True)
        assert relation is expected_relation
        assert calls and calls[0] == (member, target)
    finally:
        if change == "owner":
            source_state["_owner"] = owner
        elif change == "owner_lines":
            target_lines.append(member)
        elif change == "target_marker":
            if old_target_marker is missing:
                target_state.pop("_factor_research_target", None)
            else:
                target_state["_factor_research_target"] = old_target_marker
        elif change == "indicator_datas":
            plan.datas[0] = target
        else:
            if old_source_marker is missing:
                source_state.pop("_factor_research_target", None)
            else:
                source_state["_factor_research_target"] = old_source_marker


@pytest.mark.parametrize("clock_owner", ("source", "owner", "indicator", "target"))
def test_clock_changes_preserve_the_provenance_relation(monkeypatch, clock_owner):
    _, _, node = _run_three_assets(monkeypatch)
    member, target, plan = (
        node._members[0],
        node._factor_target_datas[0],
        node._member_relation_plans[0],
    )
    assert plan is not None
    source_state = object.__getattribute__(member, "__dict__")
    owner = source_state["_owner"]
    indicator = object.__getattribute__(owner, "__dict__")["_owner_ref"]
    instance = {
        "source": member,
        "owner": owner,
        "indicator": indicator,
        "target": target,
    }[clock_owner]
    instance_state = object.__getattribute__(instance, "__dict__")
    missing = object()
    previous_clock = instance_state.get("_clock", missing)
    instance_state["_clock"] = object()

    calls = []
    original = alpha_operators._line_target_relation

    def counted(source, selected_target, seen=None):
        calls.append((source, selected_target))
        return original(source, selected_target, seen)

    monkeypatch.setattr(alpha_operators, "_line_target_relation", counted)
    try:
        assert original(member, target) is True
        assert plan.resolve(member, target) is True
        assert alpha_operators._resolve_panel_relation(member, target, plan) is True
        assert calls == []
    finally:
        if previous_clock is missing:
            instance_state.pop("_clock", None)
        else:
            instance_state["_clock"] = previous_clock


def test_custom_line_subclasses_do_not_receive_a_presence_plan(monkeypatch):
    _, _, node = _run_three_assets(monkeypatch)
    target = node._factor_target_datas[0]

    class CustomLine(LineBuffer):
        pass

    assert alpha_operators._presence_line_relation_plan(CustomLine(), target) is None


def test_foreign_input_preserves_the_original_error_context(monkeypatch):
    frames = _frames(periods=2)
    frames = {name: frame.copy(deep=True) for name, frame in list(frames.items())[:3]}
    with pytest.raises(FactorComputationError) as caught:
        _run_subset(frames, {"probe": _ForeignPresencePlanProbe}, runonce=False)
    monkeypatch.setattr(alpha_operators, "_presence_line_relation_plan", lambda source, target: None)
    with pytest.raises(FactorComputationError) as reference:
        _run_subset(frames, {"probe": _ForeignPresencePlanProbe}, runonce=False)
    assert caught.value.asset == reference.value.asset
    assert caught.value.phase == reference.value.phase == "next"
    assert type(caught.value.__cause__) is type(reference.value.__cause__)
    assert isinstance(caught.value.__cause__, alpha_operators.OperatorInputError)


def _operator_snapshot(strategy):
    factor = strategy.factor_instances["alpha3"]
    result = {}
    for name, node in factor._nodes.items():
        outputs = getattr(node, "outputs", None)
        if outputs is not None:
            for target, output in outputs.items():
                result[(name, target._name)] = (
                    tuple(output.value.array),
                    tuple(output.reason.array),
                )
            continue
        lines = node.lines
        value = getattr(lines, "value", None)
        reason = getattr(lines, "reason", None)
        if value is not None and reason is not None:
            result[(name, None)] = (tuple(value.array), tuple(reason.array))
    return result


def _same_float_array(left, right):
    return len(left) == len(right) and all(
        (a == b) or (a != a and b != b) for a, b in zip(left, right)
    )


def test_alpha003_exact_aligned_feeds_match_full_node_reasons_and_use_the_plan(monkeypatch):
    frames_all = _frames(periods=24)
    frames = {name: frame.copy(deep=True) for name, frame in list(frames_all.items())[:3]}
    plan_ids = set()
    plan_hits = []
    relation_calls = []
    original_bind = alpha_operators._presence_line_relation_plan
    original_resolve = alpha_operators._PresenceLineRelationPlan.resolve
    original_relation = alpha_operators._line_target_relation

    def bind(source, target):
        plan = original_bind(source, target)
        if plan is not None:
            plan_ids.add(id(source))
        return plan

    def resolve(plan, source, target):
        result = original_resolve(plan, source, target)
        if id(source) in plan_ids:
            plan_hits.append(result)
        return result

    def relation(source, target, seen=None):
        if id(source) in plan_ids:
            relation_calls.append((source, target))
        return original_relation(source, target, seen)

    monkeypatch.setattr(representatives, "_research_feed", _exact_aligned_feed)
    monkeypatch.setattr(alpha_operators, "_presence_line_relation_plan", bind)
    monkeypatch.setattr(alpha_operators._PresenceLineRelationPlan, "resolve", resolve)
    monkeypatch.setattr(alpha_operators, "_line_target_relation", relation)
    fast = _run_subset(frames, {"alpha3": get_alpha(3)}, runonce=False)
    fast_snapshot = _operator_snapshot(fast)
    assert len(plan_ids) == 3
    assert plan_hits and all(hit is True for hit in plan_hits)
    assert relation_calls == []
    assert len(fast_snapshot) >= 8

    fallback_ids = set()
    fallback_calls = []
    monkeypatch.setattr(
        alpha_operators,
        "_presence_line_relation_plan",
        lambda source, target: None,
    )
    monkeypatch.setattr(alpha_operators._PresenceLineRelationPlan, "resolve", original_resolve)

    def fallback_relation(source, target, seen=None):
        if type(source) is LineBuffer:
            owner = object.__getattribute__(source, "__dict__").get("_owner")
            owner_state = (
                object.__getattribute__(owner, "__dict__") if owner is not None else {}
            )
            indicator = owner_state.get("_owner_ref")
            if type(indicator) is alpha_operators._PresenceLine:
                fallback_ids.add(id(source))
                fallback_calls.append((source, target))
        return original_relation(source, target, seen)

    monkeypatch.setattr(alpha_operators, "_line_target_relation", fallback_relation)
    reference = _run_subset(frames, {"alpha3": get_alpha(3)}, runonce=False)
    reference_snapshot = _operator_snapshot(reference)
    assert len(fallback_ids) == 3
    assert fallback_calls
    assert fast_snapshot.keys() == reference_snapshot.keys()
    for key, (fast_values, fast_reasons) in fast_snapshot.items():
        reference_values, reference_reasons = reference_snapshot[key]
        assert _same_float_array(fast_values, reference_values), key
        assert _same_float_array(fast_reasons, reference_reasons), key
