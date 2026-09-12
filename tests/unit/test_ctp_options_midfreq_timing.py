"""Contract tests for the local MF-T1 timing projection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "014_2_ctp_options_midfreq"
CONDA_PYTHON = "/Users/yunjinqi/opt/anaconda3/bin/python"
execution_timing = __import__("examples.014_2_ctp_options_midfreq.execution_timing", fromlist=["*"])
ClockMapping = execution_timing.ClockMapping
ClockObservation = execution_timing.ClockObservation
ExecutionEvent = execution_timing.ExecutionEvent
ExecutionFacts = execution_timing.ExecutionFacts
MinuteInput = execution_timing.MinuteInput
ScopeIdentity = execution_timing.ScopeIdentity
TimingPolicy = execution_timing.TimingPolicy
TimingProjector = execution_timing.TimingProjector
TimingContractError = execution_timing.TimingContractError
deadline = execution_timing.deadline

UTC = timezone.utc


def _scope(*, session: str = "day", generation: int = 7, domain: str = "d1"):
    return ScopeIdentity(
        candidate_id="candidate",
        basket_id="basket",
        account_fingerprint="account",
        trading_day="20260911",
        session_segment=session,
        generation=generation,
        rules_hash="rules-v1",
        clock_domain=domain,
        mapping_id=f"mapping-{domain}",
        source="synthetic-mf-t1",
        synthetic=True,
    )


def _mapping(scope):
    return ClockMapping(
        mapping_id=scope.mapping_id,
        anchor_wall_utc=datetime(2026, 9, 11, 9, tzinfo=UTC),
        anchor_monotonic_ns=0,
        clock_domain=scope.clock_domain,
        generation=scope.generation,
        source="synthetic-mf-t1-anchor",
        error_bound_ns=1_000,
        valid_until_ns=10**15,
        rules_hash=scope.rules_hash,
        synthetic=True,
    )


def _clock(scope, mapping, mono, *, lower=None, upper=None, trusted=True):
    return ClockObservation(
        monotonic_ns=mono,
        wall_utc=mapping.anchor_wall_utc + timedelta(microseconds=mono / 1000),
        clock_domain=scope.clock_domain,
        mapping=mapping,
        scope=scope,
        source="synthetic-mf-t1-clock",
        trusted=trusted,
        synthetic=True,
        lower_ns=lower,
        upper_ns=upper,
    )


def _facts(scope, *, phase="FLAT_VERIFIED", basket=False, exposure=0, fill=None):
    return ExecutionFacts(
        scope=scope,
        source="synthetic-mf-t1-facts",
        source_kind="synthetic",
        trusted=True,
        reported_phase=phase,
        first_leg_intent_ns=0,
        first_basket_intent_ns=0 if basket else None,
        cancel_intent_ns=None,
        earliest_exposure_lower_ns=exposure if exposure else None,
        latest_complete_fill_upper_ns=fill,
        complete_basket=basket,
        authoritative_flat_verified=phase == "FLAT_VERIFIED",
        possible_exposure_qty=0,
        confirmed_qty=0,
        event_ids=(),
        collection_version="fixture-v1",
    )


def _minute(scope, *, minute_id="m1", now=0, signal=False, z=0.0):
    return MinuteInput(
        minute_id=minute_id,
        bucket_start_ns=now,
        bucket_end_ns=now + 60_000_000_000,
        scope=scope,
        bar_ids=(f"{minute_id}-f", f"{minute_id}-c", f"{minute_id}-p"),
        quote_cutoffs=(("F", 1), ("C", 2), ("P", 3)),
        direction="conversion",
        max_quantity=1,
        invocation_id=f"next-{minute_id}",
        next_boundary_ns=now + 60_000_000_000,
        decision_deadline_ns=now + 30_000_000_000,
        entry_candidate=signal,
        z_score=z,
        legal_barrier=True,
    )


def test_deadline_boundaries_are_exact_and_do_not_use_one_second_default():
    assert deadline(100_000_000_000, 5) == 105_000_000_000
    policy = TimingPolicy(decision_deadline_seconds=30)
    assert policy.leg_timeout_ns == 5_000_000_000
    assert policy.basket_timeout_ns == 15_000_000_000
    assert policy.cancel_timeout_ns == 5_000_000_000
    assert policy.recovery_timeout_ns == 60_000_000_000


def test_execution_projection_preserves_origins_and_unknown_risk():
    scope = _scope()
    mapping = _mapping(scope)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    facts = _facts(scope, phase="UNKNOWN", exposure=0)
    result = projector.project(facts, _clock(scope, mapping, 65_000_000_000))
    assert result.deadlines["leg"].deadline_ns == 5_000_000_000
    assert result.deadlines["basket"].deadline_ns is None
    assert result.required_phase == "HALTED_MONITORING"
    assert result.risk_action == "HANDOVER"
    assert result.execution_permission == "NOT_PROVEN"
    assert result.possible_exposure_unknown is True


def test_min_hold_uses_fill_upper_and_max_hold_uses_exposure_lower():
    scope = _scope()
    mapping = _mapping(scope)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    facts = _facts(scope, basket=True, exposure=1_000_000_000, fill=4_000_000_000)
    before = projector.project(facts, _clock(scope, mapping, 63_999_999_999))
    after = projector.project(facts, _clock(scope, mapping, 64_000_000_000))
    assert before.minimum_hold_deadline_ns == 64_000_000_000
    assert before.normal_exit_allowed is False
    assert after.normal_exit_allowed is True
    assert after.maximum_hold_deadline_ns == 901_000_000_000


def test_risk_deadline_overrides_ordinary_exit_and_foreign_minute_is_rejected():
    scope = _scope()
    mapping = _mapping(scope)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    facts = _facts(scope, phase="EXPOSED", basket=True, exposure=1_000_000_000, fill=4_000_000_000)
    facts = replace(facts, first_leg_intent_ns=None, first_basket_intent_ns=None)
    max_hold = projector.project(
        facts,
        _clock(scope, mapping, 901_000_000_000),
        minute=_minute(scope, minute_id="max-hold"),
    )
    assert max_hold.reason == "MAX_HOLD_EXPIRED"
    assert max_hold.risk_action == "RISK_REDUCING"
    assert max_hold.normal_exit_allowed is False

    foreign_scope = _scope(session="next-session")
    foreign_minute = _minute(foreign_scope, minute_id="foreign")
    ready_clock = _clock(scope, mapping, 0)
    rejected = projector.project(facts, ready_clock, minute=foreign_minute)
    assert rejected.reason == "SCOPE_MISMATCH"
    assert rejected.normal_exit_allowed is False


def test_minute_is_one_shot_and_token_is_bound_to_same_next():
    scope = _scope()
    mapping = _mapping(scope)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    facts = _facts(scope)
    first = projector.consume_minute(
        _minute(scope, signal=True), facts, _clock(scope, mapping, 1_000_000_000)
    )
    second = projector.consume_minute(
        _minute(scope, signal=True), facts, _clock(scope, mapping, 2_000_000_000)
    )
    assert first.minute_consumed is True
    assert first.token is not None
    assert first.execution_permission == "NOT_PROVEN"
    assert second.minute_consumed is False
    assert second.reason == "MINUTE_ALREADY_CONSUMED"


def test_clock_regression_latches_and_cross_scope_reset_is_explicit():
    scope = _scope()
    mapping = _mapping(scope)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    projector.project(_facts(scope), _clock(scope, mapping, 100))
    fault = projector.project(_facts(scope), _clock(scope, mapping, 99))
    assert fault.reason == "CLOCK_REGRESSION"
    assert projector.clock_fault is True
    with pytest.raises(TimingContractError):
        projector.reset_scope(scope, mapping)


def test_missing_scope_or_authentication_evidence_fails_closed():
    with pytest.raises((TypeError, ValueError, TimingContractError)):
        ScopeIdentity(
            candidate_id="candidate",
            basket_id="basket",
            account_fingerprint="account",
            trading_day="20260911",
            session_segment="day",
            generation=7,
            rules_hash="rules-v1",
            clock_domain="d1",
            mapping_id="m",
            source="",
            synthetic=True,
        )
    scope = _scope()
    with pytest.raises(TimingContractError):
        TimingProjector(
            scope=scope,
            mapping=replace(_mapping(scope), synthetic=False),
            policy=TimingPolicy(30),
        )
    with pytest.raises(TimingContractError):
        ExecutionFacts(
            scope=scope,
            source="",
            source_kind="synthetic",
            trusted=True,
            reported_phase="FLAT_VERIFIED",
            first_leg_intent_ns=None,
            first_basket_intent_ns=None,
            cancel_intent_ns=None,
            earliest_exposure_lower_ns=None,
            latest_complete_fill_upper_ns=None,
            complete_basket=False,
            authoritative_flat_verified=True,
            possible_exposure_qty=0,
            confirmed_qty=0,
            event_ids=(),
            collection_version="fixture-v1",
        )


@pytest.mark.parametrize(
    ("kind", "origin", "timeout", "now", "expected"),
    [
        ("leg", 100_000_000_000, 5, 105_000_000_000, True),
        ("basket", 100_000_000_000, 15, 114_999_999_999, False),
        ("cancel", 105_000_000_000, 5, 110_000_000_000, True),
        ("recovery", 115_000_000_000, 60, 175_000_000_000, True),
    ],
)
def test_root_deadline_boundaries(kind, origin, timeout, now, expected):
    del kind
    assert (now >= deadline(origin, timeout)) is expected


def test_basket_and_leg_recovery_origins_are_not_recreated_from_callback_time():
    scope = _scope()
    mapping = _mapping(scope)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    basket_facts = _facts(scope, phase="UNKNOWN", basket=False)
    basket_facts = ExecutionFacts(
        **{**basket_facts.__dict__, "first_leg_intent_ns": None, "first_basket_intent_ns": 0}
    )
    basket = projector.project(basket_facts, _clock(scope, mapping, 16_000_000_000))
    assert basket.deadlines["recovery"].deadline_ns == 75_000_000_000

    scope2 = _scope(session="day-2")
    mapping2 = _mapping(scope2)
    # An unresolved basket may not be cleared to enter a new scope.  Use a
    # separately verified flat snapshot for the lifecycle-transition setup.
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    projector.project(_facts(scope), _clock(scope, mapping, 16_000_000_000))
    projector.reset_scope(scope2, mapping2)
    leg_facts = _facts(scope2, phase="UNKNOWN", basket=False)
    leg = projector.project(leg_facts, _clock(scope2, mapping2, 6_000_000_000))
    assert leg.deadlines["recovery"].deadline_ns == 65_000_000_000


def test_calendar_is_explicit_and_common_cutoffs_are_intersected():
    CalendarEvidence = execution_timing.CalendarEvidence
    evaluate_calendar = execution_timing.evaluate_calendar

    for seconds, entry, risk, handover in (
        (1801, True, False, False),
        (1800, False, False, False),
        (600, False, True, False),
        (180, False, True, True),
    ):
        result = evaluate_calendar(
            CalendarEvidence("day", "rules-v1", "synthetic-calendar", seconds, 5),
            expected_rules_hash="rules-v1",
        )
        assert (result.entry_allowed, result.risk_exit_due, result.handover_due) == (
            entry,
            risk,
            handover,
        )
    assert not evaluate_calendar(None, expected_rules_hash="rules-v1").entry_allowed
    assert not evaluate_calendar(
        CalendarEvidence("day", "other", "synthetic-calendar", 3600, 5),
        expected_rules_hash="rules-v1",
    ).entry_allowed


def test_actual_cerebro_timing_runner_consumes_none_feed_and_never_writes():
    result = subprocess.run(
        [CONDA_PYTHON, str(EXAMPLE / "run.py"), "--timing"],
        cwd=EXAMPLE,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "LOCAL_TIMING_REPLAY_PASS"
    assert report["cerebro"]["actual_next_callback"] is True
    assert report["cerebro"]["actual_notify_idle_callback"] is True
    assert report["cerebro"]["feed_returned_none"] is True
    assert report["timing"]["idle_callback_count"] == 2
    assert report["timing"]["results"][-1]["max_hold_due"] is True
    assert report["timing"]["results"][-1]["risk_action"] == "RISK_REDUCING"
    assert report["execution_permission"] == "NOT_PROVEN"
    assert report["orders_submitted"] == 0
    assert report["external_trade_writes"] == 0


def test_token_expiry_uses_explicit_minute_boundary_and_decision_deadline():
    scope = _scope()
    mapping = _mapping(scope)
    facts = replace(_facts(scope), first_leg_intent_ns=None)
    early = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    token = early.consume_minute(
        _minute(scope, signal=True), facts, _clock(scope, mapping, 29_999_999_999)
    )
    assert token.token is not None
    exact = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    expired = exact.consume_minute(
        _minute(scope, signal=True), facts, _clock(scope, mapping, 30_000_000_000)
    )
    assert expired.token is None
    assert expired.reason == "DECISION_TOKEN_EXPIRED"
    missing = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    no_boundary = replace(_minute(scope, signal=True), next_boundary_ns=None)
    blocked = missing.consume_minute(no_boundary, facts, _clock(scope, mapping, 1))
    assert blocked.reason == "MINUTE_BOUNDARY_MISSING"


def test_normal_exit_requires_a_later_legal_bar_and_z_or_continuation_failure():
    scope = _scope()
    mapping = _mapping(scope)
    facts = _facts(scope, basket=True, exposure=1_000_000_000, fill=4_000_000_000)
    same_bucket = replace(_minute(scope, z=0.0), bucket_end_ns=4_000_000_000)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    assert not projector.project(
        facts, _clock(scope, mapping, 64_000_000_000), minute=same_bucket
    ).normal_exit_allowed
    later = replace(_minute(scope, z=0.5), bucket_end_ns=65_000_000_000)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    assert projector.project(
        facts, _clock(scope, mapping, 64_000_000_000), minute=later
    ).normal_exit_allowed
    adverse = replace(later, z_score=0.500001, continuation_cost_failed=False)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    assert not projector.project(
        facts, _clock(scope, mapping, 64_000_000_000), minute=adverse
    ).normal_exit_allowed
    continuation = replace(adverse, continuation_cost_failed=True)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    assert projector.project(
        facts, _clock(scope, mapping, 64_000_000_000), minute=continuation
    ).normal_exit_allowed


def test_idle_gap_is_recorded_without_moving_original_deadlines():
    scope = _scope()
    mapping = _mapping(scope)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    facts = _facts(scope, phase="UNKNOWN", basket=False)
    first = projector.notify_idle(facts, _clock(scope, mapping, 0))
    on_time = projector.notify_idle(facts, _clock(scope, mapping, 249_999_999))
    late = projector.notify_idle(facts, _clock(scope, mapping, 500_000_000))
    assert first.cadence_ok is True
    assert on_time.cadence_ok is True
    assert late.cadence_ok is False
    assert late.deadlines["leg"].deadline_ns == 5_000_000_000
    assert projector.clock_fault is False


def test_duplicate_event_delivery_is_detached_and_conflicting_revisions_reject():
    scope = _scope()
    event = ExecutionEvent(
        event_id="fill-1",
        kind="partial_fill",
        leg="F",
        quantity=1,
        occurred_lower_ns=10,
        occurred_upper_ns=10,
        received_ns=20,
        terminal=False,
        source="synthetic-event",
    )
    facts = ExecutionFacts(
        scope=scope,
        source="synthetic-facts",
        source_kind="synthetic",
        trusted=True,
        reported_phase="UNKNOWN",
        first_leg_intent_ns=0,
        first_basket_intent_ns=None,
        cancel_intent_ns=None,
        earliest_exposure_lower_ns=10,
        latest_complete_fill_upper_ns=None,
        complete_basket=False,
        authoritative_flat_verified=False,
        possible_exposure_qty=None,
        confirmed_qty=1,
        event_ids=("fill-1", "fill-1"),
        collection_version="v1",
        events=(event, event),
    )
    assert facts.event_ids == ("fill-1",)
    assert facts.possible_exposure_unknown is True
    with pytest.raises(TimingContractError):
        ExecutionFacts(**{**facts.__dict__, "events": (event, replace(event, quantity=2))})


def test_minute_input_detaches_mutable_caller_sequences():
    scope = _scope()
    bars = ["f", "c", "p"]
    cutoffs = [["F", 1], ["C", 2], ["P", 3]]
    minute = MinuteInput(
        minute_id="m-detach",
        bucket_start_ns=0,
        bucket_end_ns=60,
        scope=scope,
        bar_ids=bars,
        quote_cutoffs=cutoffs,
        direction="conversion",
        max_quantity=1,
        invocation_id="next",
        next_boundary_ns=60,
        decision_deadline_ns=30,
        entry_candidate=False,
        z_score=0.0,
        legal_barrier=True,
    )
    bars[0] = "changed"
    cutoffs[0][1] = 999
    assert minute.bar_ids[0] == "f"
    assert minute.quote_cutoffs[0] == ("F", 1)


def test_new_clock_domain_requires_explicit_scope_and_cannot_replay_retired_scope():
    scope = _scope()
    mapping = _mapping(scope)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    new_scope = _scope(domain="d2")
    new_mapping = _mapping(new_scope)
    projector.reset_scope(new_scope, new_mapping)
    with pytest.raises(TimingContractError):
        projector.reset_scope(scope, mapping)


def test_fixture_provider_is_finite_and_feed_exposes_a_real_none_poll():
    fixture_module = __import__(
        "examples.014_2_ctp_options_midfreq.execution_fixture", fromlist=["*"]
    )
    TimingFixtureFeed = fixture_module.TimingFixtureFeed
    build_timing_fixture = fixture_module.build_timing_fixture

    provider = build_timing_fixture()
    assert provider.next_minute().minute_id == "MFT1-0931"
    assert provider.clock_for_next().monotonic_ns == 60_000_000_000
    assert provider.clock_for_idle().monotonic_ns == 75_000_000_000
    assert provider.clock_for_idle().monotonic_ns == 901_000_000_000
    with pytest.raises(RuntimeError):
        provider.clock_for_idle()
    feed = TimingFixtureFeed(idle_polls=1)
    assert feed._load() is True
    assert feed._load() is None
    assert feed._load() is False


def test_rejected_minute_admission_never_issues_a_token():
    scope = _scope()
    mapping = _mapping(scope)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    rejected = replace(_minute(scope, signal=True), legal_barrier=False)
    result = projector.consume_minute(
        rejected, _facts(scope), _clock(scope, mapping, 1_000_000_000)
    )
    assert result.minute_consumed is True
    assert result.token is None
    assert result.reason == "MINUTE_BARRIER_REJECTED"

    admitted = replace(
        _minute(scope, minute_id="m2", signal=True),
        bucket_start_ns=60_000_000_000,
        bucket_end_ns=120_000_000_000,
        next_boundary_ns=120_000_000_000,
        decision_deadline_ns=90_000_000_000,
    )
    token_result = projector.consume_minute(
        admitted, _facts(scope), _clock(scope, mapping, 1_000_000_000)
    )
    assert token_result.token is not None
    assert token_result.token.minute_id == admitted.minute_id
    assert token_result.token.invocation_id == admitted.invocation_id

    untrusted = replace(_facts(scope), trusted=False)
    rejected_facts = replace(
        admitted, minute_id="m3", bucket_start_ns=120_000_000_000, bucket_end_ns=180_000_000_000
    )
    blocked = projector.consume_minute(
        rejected_facts, untrusted, _clock(scope, mapping, 1_000_000_000)
    )
    assert blocked.reason == "EXECUTION_FACTS_UNTRUSTED"
    assert blocked.token is None


def test_unresolved_facts_block_scope_reset_but_terminal_basket_does_not():
    scope = _scope()
    mapping = _mapping(scope)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    unknown = _facts(scope, phase="UNKNOWN", exposure=1)
    projector.project(unknown, _clock(scope, mapping, 10))
    with pytest.raises(TimingContractError, match="UNRESOLVED_EXECUTION_OBLIGATION"):
        projector.reset_scope(_scope(session="next"), _mapping(_scope(session="next")))

    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    terminal = _facts(scope, phase="EXPOSED", basket=True, exposure=1, fill=4)
    projector.project(terminal, _clock(scope, mapping, 64_000_000_000))
    next_scope = _scope(session="next")
    projector.reset_scope(next_scope, _mapping(next_scope))
    assert projector.scope == next_scope


def test_clock_bounds_are_conservative_and_untrusted_observations_fail_closed():
    scope = _scope()
    mapping = _mapping(scope)
    facts = _facts(scope, basket=True, exposure=1_000_000_000, fill=4_000_000_000)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    uncertain = projector.project(
        facts,
        _clock(scope, mapping, 64_000_000_000, lower=63_999_999_999, upper=64_000_000_001),
    )
    assert uncertain.normal_exit_allowed is False
    assert uncertain.max_hold_due is False
    due = projector.project(
        facts,
        _clock(scope, mapping, 901_000_000_001, lower=901_000_000_000, upper=901_000_000_001),
    )
    assert due.max_hold_due is True

    untrusted = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30)).project(
        facts, _clock(scope, mapping, 64_000_000_000, trusted=False)
    )
    assert untrusted.reason == "CLOCK_UNTRUSTED"
    assert untrusted.normal_exit_allowed is False


def test_idle_is_risk_only_while_a_later_legal_minute_can_exit_normally():
    scope = _scope()
    mapping = _mapping(scope)
    facts = _facts(scope, basket=True, exposure=1_000_000_000, fill=4_000_000_000)
    projector = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30))
    idle = projector.notify_idle(facts, _clock(scope, mapping, 64_000_000_000))
    assert idle.normal_exit_allowed is False
    later = replace(_minute(scope, minute_id="later", z=0.0), bucket_end_ns=65_000_000_000)
    normal = projector.project(facts, _clock(scope, mapping, 64_000_000_000), minute=later)
    assert normal.normal_exit_allowed is True


def test_calendar_is_revalidated_at_now_and_earlier_delivery_cutoff_wins():
    CalendarEvidence = execution_timing.CalendarEvidence
    evaluate_calendar = execution_timing.evaluate_calendar

    evidence = CalendarEvidence(
        "day",
        "rules-v1",
        "synthetic-calendar",
        3600,
        5,
        as_of_ns=0,
        valid_until_ns=100,
        exercise_or_delivery_at_ns=80,
    )
    assert evaluate_calendar(evidence, expected_rules_hash="rules-v1", now_ns=50).entry_allowed
    stale = evaluate_calendar(evidence, expected_rules_hash="rules-v1", now_ns=101)
    assert stale.reason == "CALENDAR_EVIDENCE_STALE"
    cutoff = evaluate_calendar(evidence, expected_rules_hash="rules-v1", now_ns=80)
    assert cutoff.reason == "EXERCISE_OR_DELIVERY_CUTOFF"
    missing_time = evaluate_calendar(
        CalendarEvidence("day", "rules-v1", "synthetic-calendar", 3600, 5),
        expected_rules_hash="rules-v1",
        now_ns=1,
    )
    assert missing_time.reason == "CALENDAR_TIME_FACTS_MISSING"


def test_projection_contains_execution_basis_and_complete_time_trace():
    scope = _scope()
    mapping = _mapping(scope)
    result = TimingProjector(scope=scope, mapping=mapping, policy=TimingPolicy(30)).project(
        _facts(scope), _clock(scope, mapping, 1_000_000_000)
    )
    payload = result.to_dict()
    assert payload["execution_basis"]["scope_key"] == list(scope.key)
    assert payload["execution_basis"]["execution_permission"] == "NOT_PROVEN"
    assert payload["time_facts"]["now_lower_ns"] == 1_000_000_000
    assert payload["time_facts"]["now_upper_ns"] == 1_000_000_000


def test_actual_cerebro_two_minute_fixture_reaches_normal_exit_and_idle_stays_risk_only():
    result = subprocess.run(
        [CONDA_PYTHON, str(EXAMPLE / "run.py"), "--timing-normal-exit"],
        cwd=EXAMPLE,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    results = report["timing"]["results"]
    assert any(item["reason"] == "NORMAL_EXIT_PROPOSAL" for item in results)
    idle_results = [item for item in results if item["origin"] == "notify_idle"]
    assert idle_results and all(not item["normal_exit_allowed"] for item in idle_results)
    assert report["timing"]["projector"]["clock_fault"] is None
    assert all(item["timing_fault"] is None for item in results)
    assert idle_results[0]["time_facts"]["now_lower_ns"] == 120_200_000_000
    assert report["external_trade_writes"] == 0
