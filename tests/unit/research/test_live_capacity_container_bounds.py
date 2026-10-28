"""Synthetic fixed-container checks for live capacity reports.

These checks exercise the production sampler with real LineBuffer and
RegisteredSimStore objects. They do not run a live account or evaluate AC51.
"""

from collections import deque
import copy
import os
from types import SimpleNamespace

from backtrader.linebuffer import LineBuffer
from backtrader.research.live_capacity import (
    LiveCapacityRunCapture,
    evaluate_live_capacity_container_bounds,
)
from backtrader.stores.registered_sim import RegisteredSimStore, RegisteredSimWrapper


class _SyntheticCohort:
    cohort_id = "capacity-test-cohort"
    epoch_id = 11
    calendar_id = "capacity-test-calendar"

    def __init__(self):
        self.slot = 0
        self._batch = None

    def current_batch(self):
        return self._batch

    def capacity_facts(self):
        pending = self.slot
        receipts = 8 + self.slot
        return {
            "schema": "backtrader.live_cohort_capacity.v1",
            "status": "OBSERVED",
            "member_count": 1,
            "pending_slot_count": pending,
            "pending_bar_count": pending * 2,
            "max_pending_slots": 4,
            "max_pending_bars": 8,
            "window_receipt_count": receipts,
            "window_receipt_limit": 32,
            "window_receipt_member_limit": 32,
            "window_receipt_member_limits_match": True,
            "recent_signature_count": receipts,
            "recent_signature_order_count": receipts,
            "recent_signature_limit": 32,
            "diagnostic_gap_count": pending,
            "diagnostic_gap_limit": 64,
            "limits_respected": True,
        }


class _SyntheticFactor:
    def __init__(self, line):
        self.lines = SimpleNamespace(lines=[line])
        self.children = []
        self.outputs = {"A": {"value": line}}
        self.tick = 0

    def getindicators(self):
        return self.children

    @property
    def lifecycle_capacity_facts(self):
        # The work counter grows, while the bounded retained diagnostic sample
        # remains at its real configured cap. Work counts are not memory counts.
        return {
            "schema": "backtrader.factor_lifecycle_capacity.v1",
            "status": "OBSERVED",
            "call_count": 100 + self.tick * 10_000,
            "once_range_count": 0,
            "call_sample_count": 64,
            "once_range_sample_count": 0,
            "sample_limit": 64,
            "call_samples_bounded": True,
            "once_range_samples_bounded": True,
        }


class _SyntheticData:
    def __init__(self, line):
        self.lines = SimpleNamespace(lines=[line])
        self.children = ()

    def getindicators(self):
        return self.children


class _SyntheticStrategy:
    def __init__(self, cohort, factor, data):
        self.datas = (data,)
        self.live_factors = SimpleNamespace(
            cohort=cohort,
            factor_instances={"alpha": {"A": factor}},
        )
        self.order_events = deque(maxlen=3)
        self.trade_events = deque(maxlen=4)
        self.children = (factor, data)
        self._target_ids = ("A",)
        self.p = SimpleNamespace(
            logical_run_id="capacity-test-run",
            replay_mode=False,
            cohort=cohort,
        )

    def getindicators(self):
        return self.children


def _synthetic_run_report(*, bounded_line=True, capture_all=True):
    line = LineBuffer()
    if bounded_line:
        line.qbuffer()
    line.forward()
    line[0] = 1.0
    factor = _SyntheticFactor(line)
    data = _SyntheticData(line)
    factor.children.append(data)
    strategy = _SyntheticStrategy(None, factor, data)
    cohort = _SyntheticCohort()
    strategy.live_factors.cohort = cohort
    strategy.p.cohort = cohort

    api = RegisteredSimWrapper(registered_sim_terminal_order_limit=4)
    store = RegisteredSimStore(api=api, terminal_order_limit=4, autostart=False)
    capture = LiveCapacityRunCapture(
        "capacity-test-run",
        epoch_id=cohort.epoch_id,
        calendar_id=cohort.calendar_id,
        calendar_slot_count=2,
        process_id=os.getpid(),
        process_create_time=1_800_000_000.5,
        max_samples=2,
    )

    ordinals = (0, 1) if capture_all else (0,)
    for slot in ordinals:
        cohort.slot = slot
        factor.tick = slot
        strategy.order_events.append(object())
        strategy.trade_events.append(object())
        api._order_state.clear()
        api._order_state.update(
            {
                "active-{}".format(slot): "active",
                "unknown-{}".format(slot): "unknown",
                "terminal-{}".format(slot): "terminal",
            }
        )
        batch_id = "capacity-batch-{}".format(slot)
        cohort._batch = SimpleNamespace(
            status="COMPLETE",
            batch_id=batch_id,
            cohort_id=cohort.cohort_id,
            epoch_id=cohort.epoch_id,
            calendar_id=cohort.calendar_id,
            slot_index=slot,
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
        capture.observe(
            strategy,
            {
                "readiness": "LIVE_READY",
                "replay_mode": False,
                "run_id": "capacity-test-run",
                "cohort_id": cohort.cohort_id,
                "epoch_id": cohort.epoch_id,
                "calendar_id": cohort.calendar_id,
                "batch_id": batch_id,
                "slot_index": slot,
                "grid_ordinal": slot,
                "engine_phase": "prenext_ready" if slot == 0 else "grid_recorded",
            },
            store=store,
        )
    return capture.report()


def test_full_bound_capture_reports_only_fixed_capacity_evidence():
    report = _synthetic_run_report()
    assert report["status"] == "RECORDED_NOT_EVALUATED"

    result = evaluate_live_capacity_container_bounds(report)

    assert result["schema"] == "backtrader.live_capacity_container_bounds.v1"
    assert result["observation_status"] == "COMPLETE"
    assert result["bounded_component_status"] == "OBSERVED_WITHIN_FIXED_LIMITS"
    assert result["status"] == "NOT_EVALUATED"
    assert result["acceptance_evaluated"] is False
    assert result["growth_evaluation"] == "NOT_EVALUATED"
    assert result["rss_stability_evaluation"] == "NOT_EVALUATED"
    assert result["formal_acceptance_status"] == "NOT_EVALUATED"
    assert result["active_unknown_order_retention"]["status"] == "NOT_EVALUATED"
    assert result["components"]["lines"]["fixed_limits"]["aggregate_line_capacity"] > 0
    assert result["components"]["cohort"]["status"] == "BOUNDED_BY_FIXED_LIMITS"
    assert result["components"]["factor_diagnostic_samples"]["status"] == (
        "BOUNDED_BY_FIXED_LIMITS"
    )
    assert result["components"]["strategy_event_rings"]["status"] == (
        "BOUNDED_BY_FIXED_LIMITS"
    )
    assert result["components"]["terminal_order_cache"]["status"] == (
        "BOUNDED_BY_FIXED_LIMITS"
    )
    diagnostics = result["components"]["factor_diagnostic_samples"]
    assert diagnostics["counts_by_ordinal"][1]["call_sample_count"] == 64
    assert "call_count" not in repr(diagnostics)
    assert result["active_unknown_order_retention"]["counts_by_ordinal"] == (
        {"ordinal": 0, "active_order_count": 1, "unknown_order_count": 1},
        {"ordinal": 1, "active_order_count": 1, "unknown_order_count": 1},
    )


def test_unbounded_line_and_missing_checkpoint_never_become_bounded():
    unbounded = evaluate_live_capacity_container_bounds(
        _synthetic_run_report(bounded_line=False)
    )
    assert unbounded["observation_status"] == "COMPLETE"
    assert unbounded["components"]["lines"]["status"] == "UNBOUNDED"
    assert unbounded["bounded_component_status"] == "UNBOUNDED"
    assert unbounded["status"] == "NOT_EVALUATED"
    assert unbounded["formal_acceptance_status"] == "NOT_EVALUATED"

    missing = evaluate_live_capacity_container_bounds(
        _synthetic_run_report(capture_all=False)
    )
    assert missing["observation_status"] == "INCOMPLETE"
    assert missing["reason_code"] == "run_sample_sequence_incomplete"
    assert all(
        item["status"] == "INCOMPLETE" for item in missing["components"].values()
    )
    assert missing["formal_acceptance_status"] == "NOT_EVALUATED"


def test_identity_capacity_drift_and_over_limit_counterexamples_fail_closed():
    original = _synthetic_run_report()

    wrong_identity = copy.deepcopy(dict(original))
    wrong_identity["samples"][1]["run_binding"]["process_id"] += 1
    identity_result = evaluate_live_capacity_container_bounds(wrong_identity)
    assert identity_result["observation_status"] == "INCOMPLETE"
    assert identity_result["reason_code"] == "sample_run_identity_mismatch"

    changed_limit = copy.deepcopy(dict(original))
    changed_limit["samples"][1]["cohort"]["max_pending_slots"] += 1
    drift_result = evaluate_live_capacity_container_bounds(changed_limit)
    assert drift_result["observation_status"] == "COMPLETE"
    assert drift_result["components"]["cohort"]["status"] == "INCOMPLETE"
    assert (
        drift_result["components"]["cohort"]["reason_code"]
        == "cohort_fixed_capacity_profile_changed"
    )
    assert drift_result["status"] == "INCOMPLETE"

    over_limit = copy.deepcopy(dict(original))
    over_limit["samples"][1]["cohort"]["pending_slot_count"] = 5
    over_limit_result = evaluate_live_capacity_container_bounds(over_limit)
    assert over_limit_result["components"]["cohort"]["status"] == "INCOMPLETE"
    assert (
        over_limit_result["components"]["cohort"]["reason_code"]
        == "cohort_capacity_invalid"
    )
