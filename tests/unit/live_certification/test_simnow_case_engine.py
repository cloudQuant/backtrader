"""Offline contract checks for static plans and provider evidence provenance.

These tests use local contract-shaped records only.  They perform no provider
I/O and assert no certification PASS.
"""

from __future__ import annotations

import importlib
import hashlib
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SUITE_ROOT = REPO_ROOT / "examples" / "007_ctp" / "live_certification" / "simnow_penetration"


@pytest.fixture
def case_engine_module():
    previous_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "common" or name.startswith("common.")
    }
    previous_path = sys.path[:]
    for name in previous_modules:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(SUITE_ROOT))
    try:
        yield importlib.import_module("common.case_engine")
    finally:
        for name in list(sys.modules):
            if name == "common" or name.startswith("common."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
        sys.path[:] = previous_path


def _generic_evidence(module, event_kind, source, **fields):
    return module.CertificationEvidence(
        event_kind=event_kind,
        source=source,
        event_id=f"event-{event_kind}",
        evidence_sha256="a" * 64,
        occurred_at_utc="2026-09-28T00:00:00Z",
        fields=fields,
        callback_names=(),
    )


def _provider_event(module, *, fact, callback, sequence, **fields):
    values = {
        "fact": fact,
        "callback_name": callback,
        "source": "ctp_provider_callback",
        "event_id": f"callback-{sequence}",
        "session_id": "offline-contract-session",
        "trading_day": "20260928",
        "sequence": sequence,
        "observed_at_utc": f"2026-09-28T00:00:{sequence:02d}Z",
        "evidence_sha256": "b" * 64,
    }
    values.update(fields)
    return module.ProviderCallbackEvidence(**values)


def test_all_33_case_plans_are_static_and_match_historical_scenario_mapping(
    case_engine_module,
):
    module = case_engine_module
    case_dirs = sorted(path for path in (SUITE_ROOT / "cases").iterdir() if path.is_dir())

    assert len(case_dirs) == 33
    for case_dir in case_dirs:
        case_id = case_dir.name
        strategy = case_dir / f"{case_id}_strategy.py"
        scenario = module.SCENARIOS_BY_CASE_ID[case_id]
        plan = module.load_descriptive_case_plan(
            strategy,
            expected_case_id=case_id,
            expected_scenario_id=scenario.scenario_id,
        )
        assert plan.case_id == case_id
        assert plan.source_sha256 == hashlib.sha256(strategy.read_bytes()).hexdigest()
        assert plan.values.get("actions")
        assert plan.values.get("evidence") or plan.values.get("completion_criteria")


def test_every_historical_required_event_has_an_explicit_provenance_policy(
    case_engine_module,
):
    assert case_engine_module.unmapped_required_events() == []


@pytest.mark.parametrize(
    "case_id,event_kind",
    [
        ("C01", "store_auth_success"),
        ("M01", "store_connected"),
        ("M03", "store_reconnect_success"),
        ("E01", "order_reject_remote"),
        ("E03", "order_reject_remote"),
        ("EM01", "account_trading_disabled"),
        ("EM03", "gateway_force_logout_requested"),
        ("L01", "trade_execution"),
        ("O01", "risk_repeat_order_detected"),
    ],
)
def test_case_event_names_cannot_substitute_for_required_provenance(
    case_engine_module, case_id, event_kind
):
    module = case_engine_module
    tracker = module.CertificationEvidenceTracker(case_id)
    policy = module.EVENT_PROVENANCE_POLICIES[event_kind]
    wrong_source = (
        module.EvidenceSource.MANAGED_RUNTIME
        if policy.source is not module.EvidenceSource.MANAGED_RUNTIME
        else module.EvidenceSource.PROVIDER_CALLBACK
    )
    with pytest.raises(module.EvidenceContractError, match="requires source"):
        tracker.record(_generic_evidence(module, event_kind, wrong_source))


def test_native_login_evidence_requires_the_actual_callback_bundle_and_scope(
    case_engine_module,
):
    module = case_engine_module
    tracker = module.CertificationEvidenceTracker("C01")
    bad = module.CertificationEvidence(
        event_kind="store_auth_success",
        source=module.EvidenceSource.PROVIDER_CALLBACK,
        event_id="auth-event",
        evidence_sha256="c" * 64,
        occurred_at_utc="2026-09-28T00:00:00Z",
        fields={
            "request_id": 11,
            "request_generation": 11,
            "arrival_generation": 1,
            "is_last": True,
            "error_id": 0,
            "authentication_succeeded": True,
        },
        callback_names=("local_store_auth_success",),
        callback_arrival=module.LocalCallbackArrival(
            client_instance_id="client-1",
            request_generation=11,
            arrival_generation=1,
            source_sequence=1,
            arrived_at_utc="2026-09-28T00:00:00Z",
            arrived_monotonic=1.0,
        ),
    )

    with pytest.raises(module.EvidenceContractError, match="lacks native callbacks"):
        tracker.record(bad)


def test_c01_issued_receipt_allows_equal_monotonic_tick_but_rejects_earlier_arrival(
    case_engine_module,
):
    module = case_engine_module
    receipt = module.IssuedRequestReceipt(
        request_kind="authenticate",
        phase="",
        request_id=11,
        request_generation=7,
        client_instance_id="client-1",
        arrival_generation=3,
        issued_at_utc="2026-09-28T00:00:00.100Z",
        issued_monotonic=100.0,
        receipt_id="auth-receipt-11",
        ledger_entry_sha256="a" * 64,
    )
    correlation = {
        "request_kind": "authenticate",
        "phase": "",
        "request_id": 11,
        "request_generation": 7,
        "client_instance_id": "client-1",
        "arrival_generation": 3,
    }

    # A coarse Windows monotonic timer may give issue and inline callback the
    # same tick. Local callback sequence still supplies strict event ordering.
    assert module.validate_issued_request_receipt(
        receipt,
        **correlation,
        arrived_at_utc="2026-09-28T00:00:00.100Z",
        arrived_monotonic=100.0,
    )
    assert not module.validate_issued_request_receipt(
        receipt,
        **correlation,
        arrived_at_utc="2026-09-28T00:00:00.100Z",
        arrived_monotonic=99.999,
    )
    assert not module.validate_issued_request_receipt(
        receipt,
        **correlation,
        arrived_at_utc="2026-09-28T00:00:00.099Z",
        arrived_monotonic=100.001,
    )


def test_emergency_and_error_cases_require_external_effect_evidence(case_engine_module):
    module = case_engine_module
    emergency = module.CertificationEvidenceTracker("EM01")
    with pytest.raises(module.EvidenceContractError, match="lacks source fields"):
        emergency.record(
            _generic_evidence(
                module,
                "account_trading_disabled",
                module.EvidenceSource.CONTROL_PLANE,
                account_id_masked="***1234",
                reason="approved maintenance",
                authorization_ref="review-1",
            )
        )

    e03 = module.CertificationEvidenceTracker("E03")
    with pytest.raises(module.EvidenceContractError, match="lacks native callbacks"):
        e03.record(
            module.CertificationEvidence(
                event_kind="order_reject_remote",
                source=module.EvidenceSource.PROVIDER_CALLBACK,
                event_id="reject-event",
                evidence_sha256="d" * 64,
                occurred_at_utc="2026-09-28T00:00:00Z",
                fields={
                    "order_ref": "r1",
                    "ErrorID": 1,
                    "ErrorMsg": "rejected",
                    "StatusMsg": "rejected",
                    "market_state_evidence_ref": "evidence/market.json",
                    "market_state_source_event_id": "provider-market-1",
                },
                callback_names=("local_order_reject_remote",),
                provider_session_id="session-1",
                trading_day="20260928",
                source_sequence=1,
            )
        )


def test_batch_cancel_intent_alone_is_incomplete_for_b02(case_engine_module):
    module = case_engine_module
    tracker = module.CertificationEvidenceTracker("B02")
    tracker.record(
        _generic_evidence(
            module,
            "batch_cancel_requested",
            module.EvidenceSource.MANAGED_RUNTIME,
            trace_id="trace-1",
            invocation_id="invoke-1",
            order_refs=["r1", "r2"],
            dispatch_state="requested",
        )
    )

    result = tracker.snapshot()
    assert result["state"] == module.CertificationState.INCOMPLETE.value
    assert result["missing_order_callback_facts"]
    assert result["certification_pass"] is False


def test_selected_case_engine_requires_native_callback_and_reconciliation(
    case_engine_module,
):
    module = case_engine_module
    engine = module.CaseEvidenceEngine("T01")
    engine.record_dependency(
        "reviewed_order_admission",
        module.DependencyState.SATISFIED,
        source="reviewed_operator_evidence",
        evidence_ref="review/approval-1",
    )
    with pytest.raises(module.EvidenceContractError, match="CTP callback adapter"):
        engine.record_callback(
            _provider_event(
                module,
                fact=module.ProviderFact.ORDER_ACCEPTED,
                callback="OnRtnOrder",
                sequence=1,
                source="local_order_log",
                order_ref="r1",
                external_order_id="e1",
                instrument_id="rb2610",
                status="working",
            )
        )

    engine.record_callback(
        _provider_event(
            module,
            fact=module.ProviderFact.ORDER_ACCEPTED,
            callback="OnRtnOrder",
            sequence=1,
            order_ref="r1",
            external_order_id="e1",
            instrument_id="rb2610",
            status="working",
            remaining_quantity=1,
        )
    )
    result = engine.snapshot()
    assert result["state"] == module.EngineState.COLLECTING.value
    assert result["certification_pass"] is False
    assert "final_provider_order_query" in result["missing_facts"]


def test_t01_local_status_label_and_missing_terminal_query_cannot_reach_review(
    case_engine_module,
):
    module = case_engine_module
    tracker = module.CertificationEvidenceTracker("T01")
    tracker.record(
        _generic_evidence(
            module,
            "order_submit_request",
            module.EvidenceSource.MANAGED_RUNTIME,
            trace_id="trace-1",
            invocation_id="invoke-1",
            order_ref="r1",
            dispatch_state="requested",
        )
    )
    with pytest.raises(module.EvidenceContractError, match="requires source provider_callback"):
        tracker.record(
            _generic_evidence(
                module,
                "order_status_accepted",
                module.EvidenceSource.MANAGED_RUNTIME,
                order_ref="r1",
                external_order_id="e1",
                provider_status="accepted",
            )
        )
    tracker.record_provider_callback(
        _provider_event(
            module,
            fact=module.ProviderFact.ORDER_ACCEPTED,
            callback="OnRtnOrder",
            sequence=1,
            order_ref="r1",
            external_order_id="e1",
            instrument_id="rb2610",
            status="working",
            remaining_quantity=1,
        )
    )

    result = tracker.snapshot()
    assert result["state"] != module.CertificationState.REVIEW_REQUIRED.value
    assert "order_status_accepted" in result["missing_events"]
    assert "order_canceled_or_filled" in result["missing_order_callback_facts"]
    assert "final_provider_order_query" in result["missing_order_callback_facts"]
    assert result["certification_pass"] is False


def test_unavailable_provider_condition_is_separate_from_missing_evidence(
    case_engine_module,
):
    module = case_engine_module
    engine = module.CaseEvidenceEngine("B01")
    engine.record_dependency(
        "provider_partial_fill_opportunity",
        module.DependencyState.UNAVAILABLE,
        source="provider_query",
        evidence_ref="query/eod-1",
        reason="No order reached partial fill before the approved session ended.",
    )

    result = engine.snapshot()
    assert result["state"] == module.EngineState.EXTERNAL_CONDITION_UNAVAILABLE.value
    assert result["certification_pass"] is False
    assert "provider_partial_fill_opportunity" in {
        item["dependency_id"] for item in result["unavailable_external_dependencies"]
    }


def test_cancel_race_fill_in_b02_requires_query_reconciliation(case_engine_module):
    module = case_engine_module
    engine = module.CaseEvidenceEngine("B02")
    for dependency in engine.plan.dependencies:
        engine.record_dependency(
            dependency,
            module.DependencyState.SATISFIED,
            source="reviewed_operator_evidence",
            evidence_ref=f"review/{dependency}",
        )

    events = [
        _provider_event(
            module,
            fact=module.ProviderFact.ORDER_ACCEPTED,
            callback="OnRtnOrder",
            sequence=1,
            order_ref="r1",
            external_order_id="e1",
            instrument_id="rb2610",
            status="working",
            remaining_quantity=1,
        ),
        _provider_event(
            module,
            fact=module.ProviderFact.ORDER_ACCEPTED,
            callback="OnRtnOrder",
            sequence=2,
            order_ref="r2",
            external_order_id="e2",
            instrument_id="rb2610",
            status="working",
            remaining_quantity=1,
        ),
        _provider_event(
            module,
            fact=module.ProviderFact.TRADE_EXECUTION,
            callback="OnRtnTrade",
            sequence=3,
            order_ref="r1",
            external_order_id="e1",
            trade_id="t1",
            traded_quantity=1,
        ),
        _provider_event(
            module,
            fact=module.ProviderFact.ORDER_CANCELED,
            callback="OnRtnOrder",
            sequence=4,
            order_ref="r1",
            external_order_id="e1",
            instrument_id="rb2610",
            status="canceled",
            remaining_quantity=0,
            traded_quantity=1,
        ),
        _provider_event(
            module,
            fact=module.ProviderFact.ORDER_CANCELED,
            callback="OnRtnOrder",
            sequence=5,
            order_ref="r2",
            external_order_id="e2",
            instrument_id="rb2610",
            status="canceled",
            remaining_quantity=0,
        ),
        _provider_event(
            module,
            fact=module.ProviderFact.POSITION_SNAPSHOT,
            callback="OnRspQryInvestorPosition",
            sequence=6,
            instrument_id="rb2610",
            query_id="positions-final",
            query_complete=True,
            position_phase="final",
            closeable_quantity=1,
        ),
        _provider_event(
            module,
            fact=module.ProviderFact.ORDER_SNAPSHOT,
            callback="OnRspQryOrder",
            sequence=7,
            query_id="orders-final",
            query_complete=True,
            open_order_refs=(),
        ),
    ]
    for event in events:
        engine.record_callback(event)

    result = engine.snapshot()
    assert result["state"] == module.EngineState.EVIDENCE_COMPLETE_REQUIRES_REVIEW.value
    assert result["certification_pass"] is False


def test_b01_one_partial_order_cannot_reach_review(case_engine_module):
    module = case_engine_module
    engine = module.CaseEvidenceEngine("B01")
    for dependency in engine.plan.dependencies:
        engine.record_dependency(
            dependency,
            module.DependencyState.SATISFIED,
            source="reviewed_operator_evidence",
            evidence_ref=f"review/{dependency}",
        )
    events = [
        _provider_event(
            module,
            fact=module.ProviderFact.ORDER_ACCEPTED,
            callback="OnRtnOrder",
            sequence=1,
            order_ref="r1",
            external_order_id="e1",
            instrument_id="rb2610",
            status="working",
            remaining_quantity=2,
        ),
        _provider_event(
            module,
            fact=module.ProviderFact.ORDER_PARTIAL,
            callback="OnRtnOrder",
            sequence=2,
            order_ref="r1",
            external_order_id="e1",
            instrument_id="rb2610",
            status="partial",
            traded_quantity=1,
            remaining_quantity=1,
        ),
        _provider_event(
            module,
            fact=module.ProviderFact.TRADE_EXECUTION,
            callback="OnRtnTrade",
            sequence=3,
            order_ref="r1",
            external_order_id="e1",
            trade_id="t1",
            traded_quantity=1,
        ),
        _provider_event(
            module,
            fact=module.ProviderFact.ORDER_CANCELED,
            callback="OnRtnOrder",
            sequence=4,
            order_ref="r1",
            external_order_id="e1",
            instrument_id="rb2610",
            status="canceled",
            traded_quantity=1,
            remaining_quantity=0,
        ),
        _provider_event(
            module,
            fact=module.ProviderFact.POSITION_SNAPSHOT,
            callback="OnRspQryInvestorPosition",
            sequence=5,
            instrument_id="rb2610",
            query_id="positions-final",
            query_complete=True,
            position_phase="final",
            closeable_quantity=1,
        ),
        _provider_event(
            module,
            fact=module.ProviderFact.ORDER_SNAPSHOT,
            callback="OnRspQryOrder",
            sequence=6,
            query_id="orders-final",
            query_complete=True,
            open_order_refs=(),
        ),
    ]
    for event in events:
        engine.record_callback(event)

    result = engine.snapshot()
    assert result["state"] == module.EngineState.COLLECTING.value
    assert "every_test_order_must_be_partially_filled_then_canceled" in result["missing_facts"]
    assert result["certification_pass"] is False


def test_filled_cancel_window_for_t03_is_an_external_unavailable_condition(
    case_engine_module,
):
    module = case_engine_module
    engine = module.CaseEvidenceEngine("T03")
    engine.record_callback(
        _provider_event(
            module,
            fact=module.ProviderFact.ORDER_ACCEPTED,
            callback="OnRtnOrder",
            sequence=1,
            order_ref="r1",
            external_order_id="e1",
            instrument_id="rb2610",
            status="working",
            remaining_quantity=1,
        )
    )
    engine.record_callback(
        _provider_event(
            module,
            fact=module.ProviderFact.ORDER_FILLED,
            callback="OnRtnOrder",
            sequence=2,
            order_ref="r1",
            external_order_id="e1",
            instrument_id="rb2610",
            status="filled",
            remaining_quantity=0,
            traded_quantity=1,
        )
    )

    result = engine.snapshot()
    assert result["state"] == module.EngineState.EXTERNAL_CONDITION_UNAVAILABLE.value
    assert "cancel_window_unavailable" in result["missing_facts"]
    assert result["certification_pass"] is False


def test_em03_local_logout_name_without_front_disconnect_is_rejected(case_engine_module):
    module = case_engine_module
    tracker = module.CertificationEvidenceTracker("EM03")
    evidence = module.CertificationEvidence(
        event_kind="gateway_force_logout_requested",
        source=module.EvidenceSource.CONTROL_PLANE,
        event_id="logout-event",
        evidence_sha256="e" * 64,
        occurred_at_utc="2026-09-28T00:00:00Z",
        fields={
            "gateway_key": "simnow-1",
            "reason": "operator test",
            "authorization_ref": "approval-1",
            "gateway_released": True,
            "operator_termination_evidence_ref": "operations/termination-1",
            "post_disconnect_write_guard_evidence_ref": "audit/write-guard-1",
        },
        callback_names=(),
        provider_session_id="session-1",
        trading_day="20260928",
        source_sequence=1,
        actor_id_hash="f" * 64,
        signature_sha256="a" * 64,
    )

    with pytest.raises(module.EvidenceContractError, match="lacks native callbacks"):
        tracker.record(evidence)
    assert tracker.snapshot()["state"] == module.CertificationState.BLOCKED.value
