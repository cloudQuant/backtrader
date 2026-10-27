"""Count-only, bounded capacity snapshots for a synthetic live run."""

from collections import deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backtrader.linebuffer import LineBuffer
from backtrader.research.live_capacity import LiveCapacitySampler
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarSlot,
    LiveCohortCalendar,
)
from backtrader.stores.registered_sim import RegisteredSimStore, RegisteredSimWrapper


UTC = timezone.utc


def _line(*, bounded):
    line = LineBuffer()
    if bounded:
        line.qbuffer()
    line.forward()
    line[0] = 1.0
    return line


class _SyntheticFactor:
    def __init__(self, lines):
        self.lines = SimpleNamespace(lines=list(lines))
        self.children = []
        self.outputs = {"A": {"value": lines[0]}}

    def getindicators(self):
        return self.children

    @property
    def lifecycle_capacity_facts(self):
        return {
            "schema": "backtrader.factor_lifecycle_capacity.v1",
            "status": "OBSERVED",
            "call_count": 150,
            "once_range_count": 0,
            "call_sample_count": 64,
            "once_range_sample_count": 0,
            "sample_limit": 64,
            "call_samples_bounded": True,
            "once_range_samples_bounded": True,
        }


class _SyntheticCohort:
    cohort_id = "synthetic-cohort"
    epoch_id = 9

    def __init__(self, **overrides):
        self.overrides = overrides

    def capacity_facts(self):
        facts = {
            "schema": "backtrader.live_cohort_capacity.v1",
            "status": "OBSERVED",
            "member_count": 1,
            "pending_slot_count": 1,
            "pending_bar_count": 2,
            "max_pending_slots": 4,
            "max_pending_bars": 8,
            "window_receipt_count": 12,
            "window_receipt_limit": 32,
            "window_receipt_member_limit": 32,
            "window_receipt_member_limits_match": True,
            "recent_signature_count": 12,
            "recent_signature_order_count": 12,
            "recent_signature_limit": 32,
            "diagnostic_gap_count": 1,
            "diagnostic_gap_limit": 64,
            "limits_respected": True,
        }
        facts.update(self.overrides)
        return facts


class _SyntheticStrategy:
    def __init__(self, cohort, factor, data):
        self.datas = (data,)
        self.live_factors = SimpleNamespace(
            cohort=cohort,
            factor_instances={"alpha": {"A": factor}},
        )
        self.order_events = deque((object(), object()), maxlen=2)
        self.trade_events = deque((object(),), maxlen=3)
        self.children = [data, factor]

    def getindicators(self):
        return self.children


class _SyntheticData:
    def __init__(self, line):
        self.lines = SimpleNamespace(lines=[line])
        self.children = []

    def getindicators(self):
        return self.children


def _registered_store(*, terminal_limit=3, states=()):
    api = RegisteredSimWrapper(registered_sim_terminal_order_limit=terminal_limit)
    api._order_state.update(states)
    store = RegisteredSimStore(
        api=api,
        terminal_order_limit=terminal_limit,
        autostart=False,
    )
    return store, api


def _success_case(*, cohort=None, factor=None):
    cohort = cohort or _SyntheticCohort()
    bounded = _line(bounded=True)
    unbounded = _line(bounded=False)
    factor = factor or _SyntheticFactor((bounded, unbounded))
    data = _SyntheticData(bounded)
    factor.children.append(data)
    data.children.append(factor)  # bounded cycle must terminate and dedupe
    strategy = _SyntheticStrategy(cohort, factor, data)
    store, api = _registered_store(
        states=(
            ("private-active-1", "active"),
            ("private-active-2", "active"),
            ("private-unknown", "unknown"),
            ("private-terminal-1", "terminal"),
            ("private-terminal-2", "terminal"),
        )
    )
    return strategy, cohort, store, api


def test_live_capacity_samples_are_count_only_deduplicated_and_bounded():
    strategy, cohort, store, _api = _success_case()
    sampler = LiveCapacitySampler("synthetic-run", (10, 20), max_samples=2)

    first = sampler.sample(10, strategy=strategy, cohort=cohort, store=store)
    second = sampler.sample(20, strategy=strategy, cohort=cohort, store=store)
    report = sampler.report()

    assert first["status"] == second["status"] == "OBSERVED"
    assert first["acceptance_evaluated"] is False
    assert report["status"] == "RECORDED_NOT_EVALUATED"
    assert report["sample_count"] == report["max_samples"] == 2
    assert first["lines"]["line_buffer_count"] == 2  # shared line counted once
    assert first["lines"]["bounded_line_buffer_count"] == 1
    assert first["lines"]["unbounded_line_buffer_count"] == 1
    assert first["lines"]["retained_line_value_count"] == 2
    assert first["diagnostics"]["call_count"] == 150
    assert first["diagnostics"]["call_sample_count"] == 64
    assert first["cohort"]["pending_bar_count"] == 2
    assert first["strategy_events"]["events"]["order_events"] == {
        "count": 2,
        "limit": 2,
        "bounded": True,
    }
    assert first["orders"]["active_order_count"] == 2
    assert first["orders"]["unknown_order_count"] == 1
    assert first["orders"]["terminal_order_count"] == 2
    assert first["orders"]["active_unknown_limit"] is None
    assert first["orders"]["active_unknown_bounded"] is False
    assert first["orders"]["terminal_order_limit"] == 3
    assert "private-active-1" not in repr(report)
    assert "private-unknown" not in repr(report)
    assert "private-terminal-1" not in repr(report)


def test_live_capacity_fails_closed_on_missing_fields_or_mismatched_cohort():
    class MissingDiagnosticFields(_SyntheticFactor):
        @property
        def lifecycle_capacity_facts(self):
            return {
                "schema": "backtrader.factor_lifecycle_capacity.v1",
                "status": "OBSERVED",
                "call_count": 1,
            }

    bad_factor = MissingDiagnosticFields((_line(bounded=False),))
    strategy, cohort, store, _api = _success_case(factor=bad_factor)
    strategy.live_factors.cohort = object()
    del strategy.trade_events

    sampler = LiveCapacitySampler("synthetic-run", (1,), max_samples=1)
    row = sampler.sample(1, strategy=strategy, cohort=cohort, store=store)

    assert row["status"] == "INCOMPLETE"
    assert row["cohort_identity"]["reason_code"] == "run_cohort_mismatch"
    assert row["strategy_events"]["status"] == "INCOMPLETE"
    assert sampler.report()["status"] == "INCOMPLETE"
    assert sampler.report()["acceptance_evaluated"] is False


def test_live_capacity_graph_limit_and_unbounded_order_history_are_explicit():
    strategy, cohort, store, api = _success_case()
    api._order_state["too-many-terminal-1"] = "terminal"
    api._order_state["too-many-terminal-2"] = "terminal"
    # The configured terminal cap is three; the wrapper reports the overage.
    sampler = LiveCapacitySampler(
        "synthetic-run",
        (1,),
        max_samples=1,
        max_graph_nodes=1,
    )

    row = sampler.sample(1, strategy=strategy, cohort=cohort, store=store)

    assert row["status"] == "INCOMPLETE"
    assert row["lines"]["status"] == "INCOMPLETE"
    assert "graph_node_limit_exceeded" in row["lines"]["issues"]
    assert row["orders"]["status"] == "INCOMPLETE"
    assert row["orders"]["reason_code"] == "terminal_order_cap_exceeded"
    assert row["orders"]["terminal_order_count"] == 4
    assert row["orders"]["terminal_order_limit"] == 3
    assert sampler.report()["status"] == "INCOMPLETE"


def test_live_capacity_distinguishes_unobservable_line_objects_from_zero():
    cohort = _SyntheticCohort()
    known_line = _line(bounded=True)
    unknown_line = object()
    factor = _SyntheticFactor((known_line,))
    data = _SyntheticData(unknown_line)
    strategy = _SyntheticStrategy(cohort, factor, data)
    store, _api = _registered_store()

    row = LiveCapacitySampler("synthetic-run", (1,), max_samples=1).sample(
        1, strategy=strategy, cohort=cohort, store=store
    )

    assert row["status"] == "INCOMPLETE"
    assert row["lines"]["line_buffer_count"] == 1
    assert row["lines"]["bounded_line_buffer_count"] == 1
    assert row["lines"]["unobservable_line_reference_count"] >= 1
    assert "line_object_unsupported" in row["lines"]["issues"]


def test_live_capacity_distinguishes_unavailable_capacity_from_unbounded_line():
    cohort = _SyntheticCohort()
    malformed_line = _line(bounded=True)
    malformed_line.array = object()
    factor = _SyntheticFactor((malformed_line,))
    data = _SyntheticData(malformed_line)
    strategy = _SyntheticStrategy(cohort, factor, data)
    store, _api = _registered_store()

    row = LiveCapacitySampler("synthetic-run", (1,), max_samples=1).sample(
        1, strategy=strategy, cohort=cohort, store=store
    )

    assert row["status"] == "INCOMPLETE"
    assert row["lines"]["line_buffer_count"] == 1
    assert row["lines"]["bounded_line_buffer_count"] == 0
    assert row["lines"]["unbounded_line_buffer_count"] == 0
    assert row["lines"]["line_capacity_unavailable_count"] == 1
    assert "line_array_type_unsupported" in row["lines"]["issues"]


def _empty_live_cohort():
    start = datetime(2026, 10, 28, 9, 30, tzinfo=UTC)
    slot = LiveCalendarSlot(
        "slot-0",
        start,
        start + timedelta(minutes=1),
        start.date().isoformat(),
        "regular",
    )
    calendar = LiveCohortCalendar(
        calendar_id="capacity-calendar",
        version="v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="synthetic-clock",
        session_semantics="session-v1",
        slots=(slot,),
    )
    return LiveBarCohort("capacity-cohort", calendar, max_pending_slots=2, max_window_bars=3)


def test_live_cohort_capacity_facts_count_under_existing_lock_and_report_limits():
    cohort = _empty_live_cohort()
    with cohort._lock:
        cohort._members.update({"A": object(), "B": object()})
        cohort._pending.update({0: {"A": object()}, 1: {"A": object(), "B": object()}})
        cohort._window_receipts.update({"A": deque(maxlen=3), "B": deque(maxlen=3)})
        cohort._window_receipts["A"].extend((object(), object()))
        cohort._recent_signatures[(0, "A")] = object()
        cohort._recent_signature_order.append((0, "A"))
        cohort._gaps.append(object())

    facts = cohort.capacity_facts()

    assert facts["status"] == "OBSERVED"
    assert facts["member_count"] == 2
    assert facts["pending_slot_count"] == 2
    assert facts["pending_bar_count"] == 3
    assert facts["max_pending_slots"] == 2
    assert facts["max_pending_bars"] == 4
    assert facts["window_receipt_count"] == 2
    assert facts["window_receipt_limit"] == 6
    assert facts["recent_signature_count"] == 1
    assert facts["diagnostic_gap_count"] == 1
    assert "A" not in repr(facts)

    with cohort._lock:
        cohort._pending[2] = {"A": object()}
    over = cohort.capacity_facts()
    assert over["status"] == "OVER_CAPACITY_OR_UNAVAILABLE"
    assert over["limits_respected"] is False
