"""Count-only, bounded capacity snapshots for a synthetic live run."""

from collections import deque
from datetime import datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path
import sys
import threading
from types import MethodType, SimpleNamespace

from backtrader.linebuffer import LineBuffer
from backtrader.research.live_capacity import LiveCapacityRunCapture, LiveCapacitySampler
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


def _run_capture_case(*, run_id="synthetic-run", epoch_id=9, calendar_id="capacity-calendar"):
    strategy, cohort, store, _api = _success_case()
    batch_holder = {"batch": None}
    cohort.calendar_id = calendar_id
    cohort.current_batch = lambda: batch_holder["batch"]
    strategy.p = SimpleNamespace(
        logical_run_id=run_id,
        replay_mode=False,
        cohort=cohort,
    )
    strategy._target_ids = ("A",)
    return strategy, cohort, store, batch_holder


def _run_capture_event(
    strategy,
    cohort,
    batch_holder,
    *,
    slot_index,
    batch_id=None,
    run_id="synthetic-run",
    epoch_id=9,
    calendar_id="capacity-calendar",
    engine_phase="grid_recorded",
):
    batch_id = batch_id or "batch-{}".format(slot_index)
    batch = SimpleNamespace(
        status="COMPLETE",
        batch_id=batch_id,
        cohort_id=cohort.cohort_id,
        epoch_id=epoch_id,
        calendar_id=calendar_id,
        slot_index=slot_index,
        members={
            "A": SimpleNamespace(
                envelope=SimpleNamespace(
                    source_role="live",
                    complete=True,
                    quality="GOOD",
                    present=True,
                    missing_fields=(),
                    quality_flags=(),
                )
            )
        },
    )
    batch_holder["batch"] = batch
    return {
        "readiness": "LIVE_READY",
        "replay_mode": False,
        "run_id": run_id,
        "cohort_id": cohort.cohort_id,
        "epoch_id": epoch_id,
        "calendar_id": calendar_id,
        "batch_id": batch_id,
        "slot_index": slot_index,
        "grid_ordinal": slot_index,
        "engine_phase": engine_phase,
    }


def _load_alpha003_strategy_for_capture_test():
    path = (
        Path(__file__).resolve().parents[3]
        / "examples"
        / "unified"
        / "028_alpha003_simnow_minute"
        / "alpha003_strategy.py"
    )
    spec = importlib.util.spec_from_file_location(
        "alpha003_live_capacity_capture_test", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def test_live_capacity_run_capture_binds_verified_boundaries_and_calendar_ordinals():
    strategy, cohort, store, batch_holder = _run_capture_case()
    capture = LiveCapacityRunCapture(
        "synthetic-run",
        epoch_id=9,
        calendar_id="capacity-calendar",
        calendar_slot_count=21,
        process_id=os.getpid(),
        process_create_time=1_800_000_000.5,
        max_samples=4,
    )

    for ordinal in range(3, 21):
        event = _run_capture_event(
            strategy,
            cohort,
            batch_holder,
            slot_index=ordinal,
            engine_phase="prenext_ready" if ordinal == 3 else "grid_recorded",
        )
        capture.observe(strategy, event, store=store)
        if ordinal == 3:
            # A repeated prenext/next callback for the exact same batch is one boundary.
            capture.observe(strategy, event, store=store)

    report = capture.report()

    assert report["status"] == "RECORDED_NOT_EVALUATED"
    assert report["acceptance_evaluated"] is False
    assert report["window_evaluation"] == "NOT_EVALUATED"
    assert report["growth_evaluation"] == "NOT_EVALUATED"
    assert report["stability_peak_claimed"] is False
    assert report["sampling_origin"] == "first_observed_verified_live_ready_callback"
    assert report["first_ready_engine_phase"] == "prenext_ready"
    assert report["window_start_ordinal"] == 3
    assert report["window_end_ordinal"] == 20
    assert report["expected_ordinals"] == (3, 8, 14, 20)
    assert report["sample_count"] == 4
    assert report["process_identity"] == {
        "status": "OBSERVED",
        "pid": os.getpid(),
        "create_time": 1_800_000_000.5,
    }
    samples = report["samples"]
    assert tuple(row["ordinal"] for row in samples) == report["expected_ordinals"]
    assert all(row["run_binding"]["run_id"] == "synthetic-run" for row in samples)
    assert all(row["run_binding"]["process_id"] == os.getpid() for row in samples)
    assert all(
        row["ready_boundary"]["ordinal_source"]
        == "live_cohort_batch_slot_index_zero_based"
        for row in samples
    )
    assert all(
        left["ready_boundary"]["monotonic_after_ns"]
        <= right["ready_boundary"]["monotonic_before_ns"]
        for left, right in zip(samples, samples[1:])
    )


def test_live_capacity_run_capture_rejects_binding_identity_and_checkpoint_gaps():
    strategy, cohort, store, batch_holder = _run_capture_case()
    capture = LiveCapacityRunCapture(
        "synthetic-run",
        epoch_id=9,
        calendar_id="capacity-calendar",
        calendar_slot_count=5,
        process_id=os.getpid(),
        process_create_time=1_800_000_000.5,
        max_samples=3,
    )
    first = _run_capture_event(strategy, cohort, batch_holder, slot_index=0)
    capture.observe(strategy, first, store=store)
    skipped = _run_capture_event(strategy, cohort, batch_holder, slot_index=3)
    capture.observe(strategy, skipped, store=store)
    report = capture.report()

    assert report["status"] == "INCOMPLETE"
    assert report["sample_count"] == 1
    assert "grid_checkpoint_skipped" in report["issues"]
    assert report["window_evaluation"] == "NOT_EVALUATED"

    mismatch = LiveCapacityRunCapture(
        "synthetic-run",
        epoch_id=9,
        calendar_id="capacity-calendar",
        calendar_slot_count=5,
        process_id=os.getpid(),
        process_create_time=1_800_000_000.5,
        max_samples=2,
    )
    wrong_run = _run_capture_event(
        strategy,
        cohort,
        batch_holder,
        slot_index=0,
        run_id="other-run",
    )
    mismatch.observe(strategy, wrong_run, store=store)
    mismatch_report = mismatch.report()
    assert mismatch_report["status"] == "INCOMPLETE"
    assert mismatch_report["sample_count"] == 0
    assert "ready_event_run_binding_mismatch" in mismatch_report["issues"]

    pid_mismatch = LiveCapacityRunCapture(
        "synthetic-run",
        epoch_id=9,
        calendar_id="capacity-calendar",
        calendar_slot_count=5,
        process_id=os.getpid() + 1,
        process_create_time=1_800_000_000.5,
        max_samples=2,
    )
    event = _run_capture_event(strategy, cohort, batch_holder, slot_index=0)
    pid_mismatch.observe(strategy, event, store=store)
    pid_report = pid_mismatch.report()
    assert pid_report["status"] == "INCOMPLETE"
    assert pid_report["sample_count"] == 0
    assert "process_id_changed" in pid_report["issues"]
    incomplete_members = LiveCapacityRunCapture(
        "synthetic-run",
        epoch_id=9,
        calendar_id="capacity-calendar",
        calendar_slot_count=5,
        process_id=os.getpid(),
        process_create_time=1_800_000_000.5,
        max_samples=2,
    )
    incomplete_event = _run_capture_event(strategy, cohort, batch_holder, slot_index=0)
    batch_holder["batch"].members = {}
    incomplete_members.observe(strategy, incomplete_event, store=store)
    incomplete_report = incomplete_members.report()
    assert incomplete_report["status"] == "INCOMPLETE"
    assert incomplete_report["sample_count"] == 0
    assert "ready_event_current_batch_members_incomplete" in incomplete_report["issues"]


def test_live_capacity_run_capture_without_process_identity_is_incomplete_nonfatal():
    strategy, cohort, store, batch_holder = _run_capture_case()
    capture = LiveCapacityRunCapture(
        "synthetic-run",
        epoch_id=9,
        calendar_id="capacity-calendar",
        calendar_slot_count=3,
        process_id=os.getpid(),
        process_create_time=None,
        process_identity_issue="process_create_time_unavailable",
        max_samples=2,
    )
    event = _run_capture_event(strategy, cohort, batch_holder, slot_index=0)

    capture.observe(strategy, event, store=store)
    report = capture.report()

    assert report["status"] == "INCOMPLETE"
    assert report["process_identity"]["status"] == "INCOMPLETE"
    assert report["sample_count"] == 0
    assert "process_create_time_unavailable" in report["issues"]
    assert report["acceptance_evaluated"] is False


def test_alpha003_prenext_verified_ready_callback_reaches_same_run_capture():
    strategy, cohort, store, batch_holder = _run_capture_case()
    production_strategy = _load_alpha003_strategy_for_capture_test()
    capture = LiveCapacityRunCapture(
        "synthetic-run",
        epoch_id=9,
        calendar_id="capacity-calendar",
        calendar_slot_count=3,
        process_id=os.getpid(),
        process_create_time=1_800_000_000.5,
        max_samples=2,
    )
    snapshot_holder = {"snapshot": None}
    cohort.current_batch = lambda: batch_holder["batch"]
    strategy.p = SimpleNamespace(
        logical_run_id="synthetic-run",
        replay_mode=False,
        cohort=cohort,
        live_ready_callback=None,
        live_capacity_callback=lambda owner, event: capture.observe(
            owner, event, store=store
        ),
    )
    strategy._target_ids = ("A",)
    strategy.live_factors.snapshot = lambda: snapshot_holder["snapshot"]
    strategy._current_batch_snapshot = lambda: (
        batch_holder["batch"],
        snapshot_holder["snapshot"],
    )
    strategy._clock_now = lambda: datetime.now(UTC)
    strategy._confirmed_live_ready_event = MethodType(
        production_strategy.Alpha003TargetStrategy._confirmed_live_ready_event,
        strategy,
    )
    strategy._capture_live_capacity_boundary = MethodType(
        production_strategy.Alpha003TargetStrategy._capture_live_capacity_boundary,
        strategy,
    )

    for slot_index in range(3):
        batch = SimpleNamespace(
            status="COMPLETE",
            batch_id="batch-{}".format(slot_index),
            cohort_id=cohort.cohort_id,
            epoch_id=cohort.epoch_id,
            calendar_id=cohort.calendar_id,
            slot_index=slot_index,
            close_time=datetime(2026, 10, 1, 9, slot_index, tzinfo=UTC),
            available_at=datetime(2026, 10, 1, 9, slot_index, 2, tzinfo=UTC),
            members={
                "A": SimpleNamespace(
                    envelope=SimpleNamespace(
                        source_role="live",
                        complete=True,
                        quality="GOOD",
                        present=True,
                        missing_fields=(),
                        quality_flags=(),
                    )
                )
            },
        )
        snapshot = SimpleNamespace(
            readiness="LIVE_READY",
            batch_complete=True,
            batch_id=batch.batch_id,
            cohort_id=batch.cohort_id,
            epoch_id=batch.epoch_id,
            calendar_id=batch.calendar_id,
            close_time=batch.close_time,
            available_at=batch.available_at,
        )
        if slot_index == 0:
            # A partial member set cannot establish LIVE_READY or start capture.
            batch.members = {}
            batch_holder["batch"] = batch
            snapshot_holder["snapshot"] = snapshot
            production_strategy.Alpha003TargetStrategy.prenext(strategy)
            assert getattr(strategy, "_live_capacity_callback_count", 0) == 0

            batch = SimpleNamespace(
                **{
                    **vars(batch),
                    "batch_id": "batch-0-valid",
                    "members": {
                        "A": SimpleNamespace(
                            envelope=SimpleNamespace(
                                source_role="live",
                                complete=True,
                                quality="GOOD",
                                present=True,
                                missing_fields=(),
                                quality_flags=(),
                            )
                        )
                    },
                }
            )
            snapshot = SimpleNamespace(
                readiness="LIVE_READY",
                batch_complete=True,
                batch_id=batch.batch_id,
                cohort_id=batch.cohort_id,
                epoch_id=batch.epoch_id,
                calendar_id=batch.calendar_id,
                close_time=batch.close_time,
                available_at=batch.available_at,
            )
        batch_holder["batch"] = batch
        snapshot_holder["snapshot"] = snapshot
        production_strategy.Alpha003TargetStrategy.prenext(strategy)
        if slot_index == 0:
            # The next-phase receipt for the same complete batch is deduplicated.
            strategy._capture_live_capacity_boundary(
                batch, snapshot, engine_phase="grid_recorded"
            )

    report = capture.report()
    assert strategy._live_capacity_callback_count == 4
    assert report["status"] == "RECORDED_NOT_EVALUATED"
    assert report["expected_ordinals"] == (0, 2)
    assert tuple(row["ordinal"] for row in report["samples"]) == (0, 2)
    assert all(row["run_binding"]["run_id"] == "synthetic-run" for row in report["samples"])
    assert all(row["ready_boundary"]["engine_phase"] == "prenext_ready" for row in report["samples"])


def test_alpha003_next_first_ready_capture_records_grid_recorded_phase():
    strategy, cohort, store, batch_holder = _run_capture_case()
    production_strategy = _load_alpha003_strategy_for_capture_test()
    capture = LiveCapacityRunCapture(
        "synthetic-run",
        epoch_id=9,
        calendar_id="capacity-calendar",
        calendar_slot_count=1,
        process_id=os.getpid(),
        process_create_time=1_800_000_000.5,
        max_samples=1,
    )
    batch = SimpleNamespace(
        status="COMPLETE",
        batch_id="next-first-ready",
        cohort_id=cohort.cohort_id,
        epoch_id=cohort.epoch_id,
        calendar_id=cohort.calendar_id,
        slot_index=0,
        close_time=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
        available_at=datetime(2026, 10, 1, 9, 0, 2, tzinfo=UTC),
        members={
            "A": SimpleNamespace(
                envelope=SimpleNamespace(
                    source_role="live",
                    complete=True,
                    quality="GOOD",
                    present=True,
                    missing_fields=(),
                    quality_flags=(),
                )
            )
        },
    )
    snapshot = SimpleNamespace(
        readiness="LIVE_READY",
        batch_complete=True,
        batch_id=batch.batch_id,
        cohort_id=batch.cohort_id,
        epoch_id=batch.epoch_id,
        calendar_id=batch.calendar_id,
        close_time=batch.close_time,
        available_at=batch.available_at,
    )
    batch_holder["batch"] = batch
    strategy.p = SimpleNamespace(
        logical_run_id="synthetic-run",
        replay_mode=False,
        cohort=cohort,
        live_ready_callback=None,
        live_capacity_callback=lambda owner, event: capture.observe(
            owner, event, store=store
        ),
        execution_enabled=False,
    )
    strategy._target_ids = ("A",)
    strategy.live_factors.snapshot = lambda: snapshot
    strategy._current_batch_snapshot = lambda: (batch, snapshot)
    strategy._clock_now = lambda: datetime(2026, 10, 1, 9, 0, 3, tzinfo=UTC)
    strategy._update_target_decision = lambda _batch, _snapshot, *, is_new: 0
    strategy._session_facts = lambda _batch: (None, False, None)
    strategy._live_facts = lambda _now: None
    strategy._coordinator = None
    strategy._live_shadow_order_count = 0
    strategy._risk_policy = None
    strategy._last_signal_target = None
    strategy._last_batch_id = None
    strategy._shutdown_requested = threading.Event()
    strategy.last_execution_block_reason = None
    strategy._record_decision_tape = lambda *_args: (True, {"record_id": "synthetic"}, None)
    strategy._source_receipt = lambda _batch, _snapshot, _reference: SimpleNamespace(
        readiness="LIVE_READY"
    )
    strategy._live_grid_decision = lambda *_args, **_kwargs: True
    strategy._gate_open_actions = production_strategy.Alpha003TargetStrategy._gate_open_actions
    strategy._confirmed_live_ready_event = MethodType(
        production_strategy.Alpha003TargetStrategy._confirmed_live_ready_event,
        strategy,
    )
    strategy._capture_live_capacity_boundary = MethodType(
        production_strategy.Alpha003TargetStrategy._capture_live_capacity_boundary,
        strategy,
    )
    strategy._run_live = MethodType(
        production_strategy.Alpha003TargetStrategy._run_live, strategy
    )

    # Run the production Strategy.next → _run_live path. The evidence boundary
    # records that the durable grid row was recorded during next; it does not
    # label the whole next callback as completed.
    production_strategy.Alpha003TargetStrategy.next(strategy)

    report = capture.report()
    assert strategy._live_capacity_callback_count == 1
    assert report["status"] == "RECORDED_NOT_EVALUATED"
    assert report["expected_ordinals"] == (0,)
    assert tuple(row["ordinal"] for row in report["samples"]) == (0,)
    assert report["samples"][0]["ready_boundary"]["engine_phase"] == "grid_recorded"
    assert report["samples"][0]["ready_boundary"]["batch_id"] == "next-first-ready"


def test_alpha003_capacity_callback_failure_is_nonfatal_and_visible():
    production_strategy = _load_alpha003_strategy_for_capture_test()

    def fail_callback(*_args):
        raise RuntimeError("synthetic observer failure")

    owner = SimpleNamespace(
        p=SimpleNamespace(
            live_capacity_callback=fail_callback
        ),
        _confirmed_live_ready_event=lambda _batch, _snapshot: {
            "readiness": "LIVE_READY",
            "replay_mode": False,
            "cohort_id": "synthetic-cohort",
            "epoch_id": 9,
            "calendar_id": "capacity-calendar",
            "batch_id": "synthetic-batch",
            "slot_index": 0,
        },
        last_execution_block_reason=None,
    )

    production_strategy.Alpha003TargetStrategy._capture_live_capacity_boundary(
        owner, object(), object(), engine_phase="prenext_ready"
    )

    assert owner._live_capacity_callback_failed is True
    assert getattr(owner, "_live_capacity_callback_count", 0) == 0
    assert owner.last_execution_block_reason is None


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
