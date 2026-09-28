"""Offline completion gates for the unregistered 007 case engine.

Contract-shaped inputs here are synthetic and intentionally cannot establish
provider authenticity, certification PASS, or dispatch authority. The 33-case
negative loop proves only that missing scenario evidence cannot reach review;
it is not 33-case positive or full per-case acceptance coverage.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITE_ROOT = REPO_ROOT / "examples" / "007_ctp" / "live_certification" / "simnow_penetration"
SESSION = "17"
TRADING_DAY = "20260928"
INSTRUMENT = "rb2710"
DIGEST = "a" * 64
QUERY_CALLBACKS = (
    "OnRspQryOrder",
    "OnRspQryInvestorPosition",
    "OnRspQryTradingAccount",
)


@pytest.fixture
def completion_module():
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
        yield importlib.import_module("common.completion_invariants")
    finally:
        for name in list(sys.modules):
            if name == "common" or name.startswith("common."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
        sys.path[:] = previous_path


def _snapshot(
    module, phase, sequence_start, timestamp, *, positions=None, funds=None, closeable_quantities=None, closeable_position_buckets=None, account_id_masked=None
):
    query_error_ids = dict.fromkeys(QUERY_CALLBACKS, 0)
    query_is_last = dict.fromkeys(QUERY_CALLBACKS, True)
    return module.AccountReconciliationSnapshot(
        phase=phase,
        session_id=SESSION,
        trading_day=TRADING_DAY,
        occurred_at_utc=timestamp,
        order_query_id=f"{phase.value}-order",
        position_query_id=f"{phase.value}-position",
        account_query_id=f"{phase.value}-account",
        order_query_sequence=sequence_start,
        position_query_sequence=sequence_start + 1,
        account_query_sequence=sequence_start + 2,
        open_order_refs=(),
        positions=positions or {INSTRUMENT: 0},
        funds=funds or {"cash": 10000, "available_funds": 9000, "equity": 10000},
        callback_names=QUERY_CALLBACKS,
        source="ctp_provider_callback",
        evidence_sha256=DIGEST,
        query_error_ids=query_error_ids,
        query_is_last=query_is_last,
        closeable_quantities=closeable_quantities or {},
        closeable_position_buckets=closeable_position_buckets or (),
        account_id_masked=account_id_masked,
        client_instance_id="ctp-client-1",
        arrival_generation=1,
        query_native_request_ids={
            "OnRspQryOrder": sequence_start + 101,
            "OnRspQryInvestorPosition": sequence_start + 102,
            "OnRspQryTradingAccount": sequence_start + 103,
        },
        query_round_id=f"{phase.value}-query-round",
        query_id_origin="local_query_coordinator",
        query_round_id_origin="local_query_coordinator",
        sequence_origin="local_sdk_callback_arrival",
        timestamp_origin="local_sdk_capture_clock",
        session_identity_origin="derived_from_same_client_generation_native_login",
    )


def _scenario_row(
    module, kind, event_id, fields, *, sequence=0, callback_names=(), occurred_at_utc="2026-09-28T09:02:00+00:00"
):
    case_engine = importlib.import_module("common.case_engine")
    source_by_kind = {
        "order_submit_request": case_engine.EvidenceSource.MANAGED_RUNTIME,
        "order_cancel_request": case_engine.EvidenceSource.MANAGED_RUNTIME,
        "batch_cancel_requested": case_engine.EvidenceSource.MANAGED_RUNTIME,
        "order_status_accepted": case_engine.EvidenceSource.PROVIDER_CALLBACK,
        "order_reject_remote": case_engine.EvidenceSource.PROVIDER_CALLBACK,
        "trade_execution": case_engine.EvidenceSource.PROVIDER_CALLBACK,
    }
    provider = source_by_kind[kind] is case_engine.EvidenceSource.PROVIDER_CALLBACK
    return module.CertificationEvidence(
        event_kind=kind,
        source=source_by_kind[kind],
        event_id=event_id,
        evidence_sha256=DIGEST,
        occurred_at_utc=occurred_at_utc,
        fields=fields,
        callback_names=callback_names,
        provider_session_id=SESSION if provider else "",
        trading_day=TRADING_DAY if provider else "",
        source_sequence=sequence,
    )


def _t01_evidence(module):
    submit = module.ManagedOrderRequest(
        request_id="submit-r1",
        action=module.RequestAction.SUBMIT,
        dispatch_state=module.DispatchState.DISPATCHED,
        order_refs=("r1",),
        occurred_at_utc="2026-09-28T09:01:00+00:00",
        sequence=1,
        evidence_sha256=DIGEST,
        quantity=1,
    )
    cancel = module.ManagedOrderRequest(
        request_id="cancel-r1",
        action=module.RequestAction.CANCEL,
        dispatch_state=module.DispatchState.DISPATCHED,
        order_refs=("r1",),
        occurred_at_utc="2026-09-28T09:03:00+00:00",
        sequence=2,
        evidence_sha256=DIGEST,
    )
    accepted = module.NativeOrderFact(
        event_id="order-accepted-r1",
        fact=module.NativeOrderFactKind.ACCEPTED,
        callback_name="OnRtnOrder",
        source="ctp_provider_callback",
        order_ref="r1",
        external_order_id="sys-r1",
        instrument_id=INSTRUMENT,
        status="accepted",
        traded_quantity=0,
        remaining_quantity=1,
        session_id=SESSION,
        trading_day=TRADING_DAY,
        source_sequence=4,
        occurred_at_utc="2026-09-28T09:02:00+00:00",
        evidence_sha256=DIGEST,
    )
    canceled = module.NativeOrderFact(
        event_id="order-canceled-r1",
        fact=module.NativeOrderFactKind.CANCELED,
        callback_name="OnRtnOrder",
        source="ctp_provider_callback",
        order_ref="r1",
        external_order_id="sys-r1",
        instrument_id=INSTRUMENT,
        status="canceled",
        traded_quantity=0,
        remaining_quantity=0,
        session_id=SESSION,
        trading_day=TRADING_DAY,
        source_sequence=5,
        occurred_at_utc="2026-09-28T09:04:00+00:00",
        evidence_sha256=DIGEST,
    )
    scenario = (
        _scenario_row(
            module,
            "order_submit_request",
            "managed-submit-r1",
            {
                "trace_id": "trace-r1",
                "invocation_id": "invoke-r1",
                "order_ref": "r1",
                "dispatch_state": "dispatched",
            },
        ),
        _scenario_row(
            module,
            "order_status_accepted",
            "provider-accepted-r1",
            {"order_ref": "r1", "external_order_id": "sys-r1", "provider_status": "accepted"},
            sequence=4,
            callback_names=("OnRtnOrder",),
        ),
    )
    snapshots = (
        _snapshot(
            module,
            module.SnapshotPhase.BASELINE,
            1,
            "2026-09-28T09:00:00+00:00",
        ),
        _snapshot(
            module,
            module.SnapshotPhase.FINAL,
            6,
            "2026-09-28T09:05:00+00:00",
        ),
    )
    return module.CompletionEvidence(
        case_id="T01",
        scenario_evidence=scenario,
        managed_requests=(submit, cancel),
        order_facts=(accepted, canceled),
        snapshots=snapshots,
    )


def _c01_login_evidence(module):
    case_engine = importlib.import_module("common.case_engine")
    auth = module.CertificationEvidence(
        event_kind="store_auth_success",
        source=case_engine.EvidenceSource.PROVIDER_CALLBACK,
        event_id="ctp-auth",
        evidence_sha256=DIGEST,
        occurred_at_utc="2026-09-28T09:00:00+00:00",
        fields={
            "request_id": 11,
            "request_generation": 11,
            "arrival_generation": 1,
            "is_last": True,
            "error_id": 0,
            "authentication_succeeded": True,
        },
        callback_names=("OnRspAuthenticate",),
        callback_arrival=case_engine.LocalCallbackArrival(
            client_instance_id="ctp-client-1",
            request_generation=11,
            arrival_generation=1,
            source_sequence=1,
            arrived_at_utc="2026-09-28T09:00:00+00:00",
            arrived_monotonic=100.0,
        ),
    )
    login = module.CertificationEvidence(
        event_kind="store_login_success",
        source=case_engine.EvidenceSource.PROVIDER_CALLBACK,
        event_id="ctp-login",
        evidence_sha256=DIGEST,
        occurred_at_utc="2026-09-28T09:00:01+00:00",
        fields={
            "request_id": 12,
            "request_generation": 12,
            "arrival_generation": 1,
            "is_last": True,
            "error_id": 0,
            "login_succeeded": True,
            "provider_front_id": 3,
            "provider_session_id": SESSION,
            "trading_day": TRADING_DAY,
        },
        callback_names=("OnRspUserLogin",),
        provider_session_id=SESSION,
        trading_day=TRADING_DAY,
        provider_front_id=3,
        callback_arrival=case_engine.LocalCallbackArrival(
            client_instance_id="ctp-client-1",
            request_generation=12,
            arrival_generation=1,
            source_sequence=2,
            arrived_at_utc="2026-09-28T09:00:01+00:00",
            arrived_monotonic=101.0,
        ),
    )
    return module.CompletionEvidence(
        case_id="C01",
        scenario_evidence=(auth, login),
        snapshots=(
            _snapshot(module, module.SnapshotPhase.BASELINE, 3, "2026-09-28T09:01:00+00:00"),
            _snapshot(module, module.SnapshotPhase.FINAL, 6, "2026-09-28T09:05:00+00:00"),
        ),
    )


def _validation_case_evidence(module, case_id, overrides=None):
    case_engine = importlib.import_module("common.case_engine")
    validation_rule = {
        "V01": "instrument",
        "V02": "price_tick",
        "V03": "max_order_size",
    }[case_id]
    fields = {
        "trace_id": f"trace-{case_id}",
        "validator_digest": DIGEST,
        "reference_data_digest": DIGEST,
        "validation_rule": validation_rule,
        "error_msg": "local validation rejected before dispatch",
        "dispatch_absent": True,
        "instrument": "UNKNOWN-RB",
        "instrument_id": "UNKNOWN-RB",
        "authoritative_lookup_instrument": "UNKNOWN-RB",
        "authoritative_lookup_result": "not_found",
        "authoritative_lookup_complete": True,
        "authoritative_lookup_authoritative": True,
        "authoritative_lookup_source": "sandbox-contract-master",
        "authoritative_lookup_id": "query-17",
        "authoritative_lookup_at_utc": "2026-09-28T09:00:00+00:00",
        "proposed_price": "100.03",
        "price": "100.03",
        "price_tick": "0.05",
        "requested_size": "11",
        "size": "11",
        "max_order_size": "10",
    }
    fields.update(overrides or {})
    if "proposed_price" in (overrides or {}) and "price" not in (overrides or {}):
        fields["price"] = fields["proposed_price"]
    if "requested_size" in (overrides or {}) and "size" not in (overrides or {}):
        fields["size"] = fields["requested_size"]
    row = module.CertificationEvidence(
        event_kind="order_validation_rejected",
        source=case_engine.EvidenceSource.LOCAL_VALIDATOR,
        event_id=f"validation-{case_id}",
        evidence_sha256=DIGEST,
        occurred_at_utc="2026-09-28T09:01:00+00:00",
        fields=fields,
    )
    return module.CompletionEvidence(
        case_id=case_id,
        scenario_evidence=(row,),
        snapshots=(
            _snapshot(module, module.SnapshotPhase.BASELINE, 1, "2026-09-28T09:00:00+00:00"),
            _snapshot(module, module.SnapshotPhase.FINAL, 4, "2026-09-28T09:02:00+00:00"),
        ),
    )


def _e01_remote_rejection(module):
    submit = module.ManagedOrderRequest(
        request_id="submit-r1",
        action=module.RequestAction.SUBMIT,
        dispatch_state=module.DispatchState.DISPATCHED,
        order_refs=("r1",),
        occurred_at_utc="2026-09-28T09:01:00+00:00",
        sequence=1,
        evidence_sha256=DIGEST,
        quantity=1,
    )
    rejected = module.NativeOrderFact(
        event_id="order-rejected-r1",
        fact=module.NativeOrderFactKind.REJECTED,
        callback_name="OnRspOrderInsert",
        source="ctp_provider_callback",
        order_ref="r1",
        external_order_id="",
        instrument_id=INSTRUMENT,
        status="rejected",
        traded_quantity=0,
        remaining_quantity=0,
        session_id=SESSION,
        trading_day=TRADING_DAY,
        source_sequence=4,
        occurred_at_utc="2026-09-28T09:02:00+00:00",
        evidence_sha256=DIGEST,
        error_id=5,
    )
    scenario = (
        _scenario_row(
            module,
            "order_submit_request",
            "managed-submit-r1",
            {
                "trace_id": "trace-r1",
                "invocation_id": "invoke-r1",
                "order_ref": "r1",
                "dispatch_state": "dispatched",
            },
        ),
        _scenario_row(
            module,
            "order_reject_remote",
            "provider-reject-r1",
            {
                "order_ref": "r1",
                "ErrorID": 5,
                "ErrorMsg": "insufficient funds",
                "StatusMsg": "insufficient funds",
                "verified_rejection_class": "insufficient_funds",
                "error_mapping_evidence_ref": "independent-error-map-review",
            },
            sequence=4,
            callback_names=("OnRspOrderInsert",),
        ),
    )
    dependency = module.ExternalDependency(
        dependency_id="insufficient_funds",
        state="satisfied",
        evidence_ref="provider-account-risk-record",
        evidence_sha256=DIGEST,
        fields={
            "available_funds": 10,
            "required_margin": 20,
            "instrument_id": INSTRUMENT,
            "order_ref": "r1",
        },
    )
    return module.CompletionEvidence(
        case_id="E01",
        scenario_evidence=scenario,
        managed_requests=(submit,),
        order_facts=(rejected,),
        snapshots=(
            _snapshot(module, module.SnapshotPhase.BASELINE, 1, "2026-09-28T09:00:00+00:00"),
            _snapshot(module, module.SnapshotPhase.FINAL, 5, "2026-09-28T09:05:00+00:00"),
        ),
        external_dependencies=(dependency,),
    )


def _b02_cancel_fill_race(module):
    requests = (
        module.ManagedOrderRequest(
            f"submit-{ref}",
            module.RequestAction.SUBMIT,
            module.DispatchState.DISPATCHED,
            (ref,),
            "2026-09-28T09:01:00+00:00",
            index,
            DIGEST,
            quantity=1,
        )
        for index, ref in enumerate(("r1", "r2"), start=1)
    )
    requests = tuple(requests) + (
        module.ManagedOrderRequest(
            "batch-cancel",
            module.RequestAction.BATCH_CANCEL,
            module.DispatchState.DISPATCHED,
            ("r1", "r2"),
            "2026-09-28T09:03:00+00:00",
            3,
            DIGEST,
        ),
    )

    def order_fact(ref, fact, sequence, time, *, traded=0, remaining=1):
        return module.NativeOrderFact(
            event_id=f"{fact.value}-{ref}",
            fact=fact,
            callback_name="OnRtnOrder",
            source="ctp_provider_callback",
            order_ref=ref,
            external_order_id=f"sys-{ref}",
            instrument_id=INSTRUMENT,
            status=fact.value,
            traded_quantity=traded,
            remaining_quantity=remaining,
            session_id=SESSION,
            trading_day=TRADING_DAY,
            source_sequence=sequence,
            occurred_at_utc=time,
            evidence_sha256=DIGEST,
        )

    facts = (
        order_fact("r1", module.NativeOrderFactKind.ACCEPTED, 4, "2026-09-28T09:02:00+00:00"),
        order_fact("r2", module.NativeOrderFactKind.ACCEPTED, 5, "2026-09-28T09:02:01+00:00"),
        order_fact(
            "r2",
            module.NativeOrderFactKind.FILLED,
            7,
            "2026-09-28T09:04:01+00:00",
            traded=1,
            remaining=0,
        ),
        order_fact(
            "r1", module.NativeOrderFactKind.CANCELED, 8, "2026-09-28T09:05:00+00:00", remaining=0
        ),
    )
    trade = module.NativeTradeFact(
        event_id="trade-r2",
        trade_id="trade-id-r2",
        order_ref="r2",
        instrument_id=INSTRUMENT,
        quantity=1,
        direction="buy",
        price=3500,
        callback_name="OnRtnTrade",
        source="ctp_provider_callback",
        session_id=SESSION,
        trading_day=TRADING_DAY,
        source_sequence=6,
        occurred_at_utc="2026-09-28T09:04:00+00:00",
        evidence_sha256=DIGEST,
        external_order_id="sys-r2",
    )
    submit_scenarios = tuple(
        _scenario_row(
            module,
            "order_submit_request",
            f"scenario-submit-{ref}",
            {
                "trace_id": f"trace-{ref}",
                "invocation_id": f"invoke-{ref}",
                "order_ref": ref,
                "dispatch_state": "dispatched",
            },
        )
        for ref in ("r1", "r2")
    )
    batch_scenario = _scenario_row(
        module,
        "batch_cancel_requested",
        "scenario-batch-cancel",
        {
            "trace_id": "trace-batch",
            "invocation_id": "invoke-batch",
            "order_refs": ["r1", "r2"],
            "dispatch_state": "dispatched",
            "open_order_count": 2,
        },
    )
    snapshots = (
        _snapshot(module, module.SnapshotPhase.BASELINE, 1, "2026-09-28T09:00:00+00:00"),
        _snapshot(
            module,
            module.SnapshotPhase.FINAL,
            9,
            "2026-09-28T09:06:00+00:00",
            positions={INSTRUMENT: 1},
            funds={"cash": 9999, "available_funds": 8999, "equity": 10000},
        ),
    )
    return module.CompletionEvidence(
        case_id="B02",
        scenario_evidence=(*submit_scenarios, batch_scenario),
        managed_requests=requests,
        order_facts=facts,
        trade_facts=(trade,),
        snapshots=snapshots,
    )


def test_all_33_cases_need_scenario_evidence_before_review(completion_module):
    """A broad fail-closed negative, not full completion coverage for 33 cases."""
    module = completion_module
    from common.certification import RECONCILIATION_EXPECTATIONS

    assert len(RECONCILIATION_EXPECTATIONS) == 33
    for case_id in RECONCILIATION_EXPECTATIONS:
        snapshots = (
            _snapshot(module, module.SnapshotPhase.BASELINE, 1, "2026-09-28T09:00:00+00:00"),
            _snapshot(module, module.SnapshotPhase.FINAL, 4, "2026-09-28T09:05:00+00:00"),
        )
        if case_id == "C01":
            snapshots = tuple(
                replace(
                    snapshot,
                    session_id="",
                    trading_day="",
                    session_identity_origin="",
                )
                for snapshot in snapshots
            )
        evidence = module.CompletionEvidence(case_id=case_id, snapshots=snapshots)
        report = module.evaluate_case_completion(evidence)
        assert report.status is not module.CompletionStatus.REVIEW_REQUIRED, case_id
        assert report.certification_pass is False
        assert report.dispatch_permitted is False
        assert report.source_authenticity_verified is False


def test_t01_terminal_order_account_reconciliation_only_reaches_review(completion_module):
    report = completion_module.evaluate_case_completion(_t01_evidence(completion_module))
    assert report.status is completion_module.CompletionStatus.REVIEW_REQUIRED
    assert report.certification_pass is False
    assert report.dispatch_permitted is False
    assert report.source_authenticity_verified is False
    assert report.review_reasons


def test_c01_requires_auth_then_login_then_account_queries(completion_module):
    module = completion_module
    evidence = _c01_login_evidence(module)
    report = module.evaluate_case_completion(evidence)
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert any("trusted issuer-side request ledger verifier" in item for item in report.missing_invariants)
    auth, login = evidence.scenario_evidence
    arrival_type = importlib.import_module("common.case_engine").LocalCallbackArrival
    reversed_auth = replace(
        auth,
        occurred_at_utc="2026-09-28T09:00:02+00:00",
        callback_arrival=arrival_type(
            client_instance_id="ctp-client-1",
            request_generation=11,
            arrival_generation=1,
            source_sequence=3,
            arrived_at_utc="2026-09-28T09:00:02+00:00",
            arrived_monotonic=102.0,
        ),
    )
    reversed_order = replace(evidence, scenario_evidence=(reversed_auth, login))
    with pytest.raises(module.CompletionEvidenceError, match="arrival sequence must strictly increase"):
        module.evaluate_case_completion(reversed_order)


def test_c01_missing_login_stays_incomplete(completion_module):
    module = completion_module
    evidence = _c01_login_evidence(module)
    unbound_snapshots = tuple(
        replace(
            snapshot,
            session_id="",
            trading_day="",
            session_identity_origin="",
        )
        for snapshot in evidence.snapshots
    )
    report = module.evaluate_case_completion(
        replace(
            evidence,
            scenario_evidence=evidence.scenario_evidence[:1],
            snapshots=unbound_snapshots,
        )
    )

    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "scenario_event:store_login_success" in report.missing_invariants
    assert report.certification_pass is False
    assert report.dispatch_permitted is False


def test_c01_disconnect_generation_change_between_auth_and_login_fails(completion_module):
    module = completion_module
    evidence = _c01_login_evidence(module)
    auth, login = evidence.scenario_evidence
    changed_login = replace(
        login,
        fields={**login.fields, "arrival_generation": 2},
        callback_arrival=replace(login.callback_arrival, arrival_generation=2),
    )
    report = module.evaluate_case_completion(
        replace(evidence, scenario_evidence=(auth, changed_login))
    )

    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "auth_and_login_must_share_client_and_arrival_generation" in report.contradictions
    assert report.certification_pass is False
    assert report.dispatch_permitted is False


def test_c01_auth_cannot_claim_login_only_native_identity(completion_module):
    module = completion_module
    evidence = _c01_login_evidence(module)
    auth, login = evidence.scenario_evidence
    claimed_auth = replace(
        auth,
        provider_session_id=SESSION,
        trading_day=TRADING_DAY,
        provider_front_id=3,
        fields={
            **auth.fields,
            "provider_front_id": 3,
            "provider_session_id": SESSION,
            "trading_day": TRADING_DAY,
        },
    )

    with pytest.raises(module.CompletionEvidenceError, match="OnRspAuthenticate has no provider session"):
        module.evaluate_case_completion(
            replace(evidence, scenario_evidence=(claimed_auth, login))
        )


def test_em02_pause_receipt_must_bind_the_same_strategy_and_event(completion_module):
    module = completion_module
    case_engine = importlib.import_module("common.case_engine")
    pause_row = module.CertificationEvidence(
        event_kind="strategy_trading_paused",
        source=case_engine.EvidenceSource.CONTROL_PLANE,
        event_id="pause-event-A",
        evidence_sha256=DIGEST,
        occurred_at_utc="2026-09-28T09:02:00+00:00",
        fields={
            "strategy_id": "strategy-A",
            "reason": "operator pause",
            "authorization_ref": "approval-A",
        },
        actor_id_hash="actor-A",
        signature_sha256=DIGEST,
    )
    dependency = module.ExternalDependency(
        dependency_id="strategy_pause_authorized",
        state="satisfied",
        evidence_ref="control-pause-A",
        evidence_sha256=DIGEST,
        fields={
            "state": "paused",
            "strategy_id": "strategy-A",
            "pause_event_ref": pause_row.event_id,
            "pending_orders_reconciled": True,
        },
    )
    evidence = module.CompletionEvidence(
        case_id="EM02",
        scenario_evidence=(pause_row,),
        snapshots=(
            _snapshot(module, module.SnapshotPhase.BASELINE, 1, "2026-09-28T09:00:00+00:00"),
            _snapshot(module, module.SnapshotPhase.FINAL, 4, "2026-09-28T09:05:00+00:00"),
        ),
        external_dependencies=(dependency,),
    )
    report = module.evaluate_case_completion(evidence)
    assert report.status is module.CompletionStatus.REVIEW_REQUIRED
    wrong_dependency = replace(
        dependency,
        fields={**dependency.fields, "strategy_id": "strategy-B", "pause_event_ref": "other"},
    )
    report = module.evaluate_case_completion(
        replace(evidence, external_dependencies=(wrong_dependency,))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "strategy_pause_receipt_does_not_match_pause_event" in report.contradictions


def _o02_close_evidence(
    module, *, direction="sell", offset="close_today", quantity=1, native_direction=None, native_offset=None
):
    case_engine = importlib.import_module("common.case_engine")
    native_direction = native_direction or direction
    native_offset = native_offset or offset
    request = module.ManagedOrderRequest(
        request_id="o02-submit-1",
        action=module.RequestAction.SUBMIT,
        dispatch_state=module.DispatchState.DISPATCHED,
        order_refs=("o02-r1",),
        occurred_at_utc="2026-09-28T09:01:00+00:00",
        sequence=1,
        evidence_sha256=DIGEST,
        quantity=quantity,
        instrument_id=INSTRUMENT,
        direction=direction,
        offset=offset,
        account_id_masked="account-A",
        provider_session_id=SESSION,
        request_generation=1,
        intent_key=f"close:{INSTRUMENT}:{direction}",
        trading_day=TRADING_DAY,
    )
    blocked_repeat = replace(
        request,
        request_id="o02-submit-repeat",
        dispatch_state=module.DispatchState.BLOCKED_PRE_DISPATCH,
        occurred_at_utc="2026-09-28T09:01:30+00:00",
        sequence=2,
        request_generation=2,
    )
    cancel = module.ManagedOrderRequest(
        request_id="o02-cancel-1",
        action=module.RequestAction.CANCEL,
        dispatch_state=module.DispatchState.DISPATCHED,
        order_refs=("o02-r1",),
        occurred_at_utc="2026-09-28T09:02:30+00:00",
        sequence=3,
        evidence_sha256=DIGEST,
    )
    accepted = module.NativeOrderFact(
        event_id="o02-accepted",
        fact=module.NativeOrderFactKind.ACCEPTED,
        callback_name="OnRtnOrder",
        source="ctp_provider_callback",
        order_ref="o02-r1",
        external_order_id="sys-o02-r1",
        instrument_id=INSTRUMENT,
        status="accepted",
        traded_quantity=0,
        remaining_quantity=quantity,
        session_id=SESSION,
        trading_day=TRADING_DAY,
        source_sequence=4,
        occurred_at_utc="2026-09-28T09:02:00+00:00",
        evidence_sha256=DIGEST,
        direction=native_direction,
        offset=native_offset,
        account_id_masked="account-A",
    )
    canceled = replace(
        accepted,
        event_id="o02-canceled",
        fact=module.NativeOrderFactKind.CANCELED,
        status="canceled",
        remaining_quantity=0,
        source_sequence=5,
        occurred_at_utc="2026-09-28T09:03:00+00:00",
    )
    repeat_event = module.CertificationEvidence(
        event_kind="risk_repeat_order_detected",
        source=case_engine.EvidenceSource.RUNTIME_MONITOR,
        event_id="o02-repeat-monitor",
        evidence_sha256=DIGEST,
        occurred_at_utc="2026-09-28T09:01:45+00:00",
        fields={
            "trace_id": "o02-trace",
            "repeat_key": f"close:{INSTRUMENT}:{direction}",
            "repeat_count": 2,
            "monitor_digest": DIGEST,
            "account_id_masked": "account-A",
            "provider_session_id": SESSION,
            "trading_day": TRADING_DAY,
        },
    )
    return module.CompletionEvidence(
        case_id="O02",
        scenario_evidence=(repeat_event,),
        managed_requests=(request, blocked_repeat, cancel),
        order_facts=(accepted, canceled),
        snapshots=(
            _snapshot(
                module,
                module.SnapshotPhase.BASELINE,
                1,
                "2026-09-28T09:00:00+00:00",
                positions={INSTRUMENT: 2},
                closeable_quantities={INSTRUMENT: 1},
                closeable_position_buckets=(
                    module.CloseablePositionBucket(INSTRUMENT, "long", offset, 1),
                )
                if offset in {"close_today", "close_yesterday"}
                else (),
                account_id_masked="account-A",
            ),
            _snapshot(
                module,
                module.SnapshotPhase.FINAL,
                6,
                "2026-09-28T09:05:00+00:00",
                positions={INSTRUMENT: 2},
                account_id_masked="account-A",
            ),
        ),
    )


def _em01_permission_evidence(module, *, submit_time, reject_time):
    case_engine = importlib.import_module("common.case_engine")
    disabled_time = "2026-09-28T09:02:00+00:00"
    restored_time = "2026-09-28T09:04:00+00:00"
    disabled_row = module.CertificationEvidence(
        event_kind="account_trading_disabled",
        source=case_engine.EvidenceSource.CONTROL_PLANE,
        event_id="permission-disabled-event",
        evidence_sha256=DIGEST,
        occurred_at_utc=disabled_time,
        fields={
            "account_id_masked": "account-A",
            "reason": "permission review",
            "authorization_ref": "auth-A",
            "independent_account_permission_evidence_ref": "provider-permission-A",
            "blocked_order_ref": "em01-r1",
            "ErrorID": 5,
            "ErrorMsg": "account permission denied",
            "permission_restored_ref": "restore-audit-A",
        },
        callback_names=("OnRspOrderInsert",),
        provider_session_id=SESSION,
        trading_day=TRADING_DAY,
        source_sequence=4,
        actor_id_hash="actor-A",
        signature_sha256=DIGEST,
    )
    submit_row = _scenario_row(
        module,
        "order_submit_request",
        "em01-submit-event",
        {
            "trace_id": "em01-trace",
            "invocation_id": "em01-invocation",
            "order_ref": "em01-r1",
            "dispatch_state": "dispatched",
            "request_id": "em01-submit-r1",
            "request_generation": 1,
            "account_id_masked": "account-A",
            "provider_session_id": SESSION,
            "trading_day": TRADING_DAY,
        },
        sequence=5,
        occurred_at_utc=submit_time,
    )
    reject_row = _scenario_row(
        module,
        "order_reject_remote",
        "em01-reject-event",
        {
            "order_ref": "em01-r1",
            "ErrorID": 5,
            "ErrorMsg": "account permission denied",
            "StatusMsg": "account permission denied",
            "verified_rejection_class": "account_permission_denied",
            "error_mapping_evidence_ref": "reviewed-error-map-A",
        },
        sequence=6,
        callback_names=("OnRspOrderInsert",),
        occurred_at_utc=reject_time,
    )
    request = module.ManagedOrderRequest(
        request_id="em01-submit-r1",
        action=module.RequestAction.SUBMIT,
        dispatch_state=module.DispatchState.DISPATCHED,
        order_refs=("em01-r1",),
        occurred_at_utc=submit_time,
        sequence=5,
        evidence_sha256=DIGEST,
        quantity=1,
        account_id_masked="account-A",
        provider_session_id=SESSION,
        request_generation=1,
        trading_day=TRADING_DAY,
    )
    rejected = module.NativeOrderFact(
        event_id="em01-native-reject",
        fact=module.NativeOrderFactKind.REJECTED,
        callback_name="OnRspOrderInsert",
        source="ctp_provider_callback",
        order_ref="em01-r1",
        external_order_id="",
        instrument_id=INSTRUMENT,
        status="rejected",
        traded_quantity=0,
        remaining_quantity=0,
        session_id=SESSION,
        trading_day=TRADING_DAY,
        source_sequence=6,
        occurred_at_utc=reject_time,
        evidence_sha256=DIGEST,
        error_id=5,
        account_id_masked="account-A",
    )
    disabled = module.ExternalDependency(
        dependency_id="account_permission_disabled",
        state="satisfied",
        evidence_ref="disable-audit-A",
        evidence_sha256=DIGEST,
        fields={
            "state": "disabled",
            "account_id_masked": "account-A",
            "change_id": "change-A",
            "provider_audit_ref": "disable-audit-A",
            "occurred_at_utc": disabled_time,
            "source_event_ref": disabled_row.event_id,
            "provider_session_id": SESSION,
            "trading_day": TRADING_DAY,
        },
    )
    restored = replace(
        disabled,
        dependency_id="account_permission_restored",
        evidence_ref="restore-audit-A",
        fields={
            **disabled.fields,
            "state": "restored",
            "provider_audit_ref": "restore-audit-A",
            "occurred_at_utc": restored_time,
        },
    )
    return module.CompletionEvidence(
        case_id="EM01",
        scenario_evidence=(disabled_row, submit_row, reject_row),
        managed_requests=(request,),
        order_facts=(rejected,),
        snapshots=(
            _snapshot(
                module, module.SnapshotPhase.BASELINE, 1, "2026-09-28T09:00:00+00:00", account_id_masked="account-A"
            ),
            _snapshot(
                module, module.SnapshotPhase.FINAL, 7, "2026-09-28T09:05:00+00:00", account_id_masked="account-A"
            ),
        ),
        external_dependencies=(disabled, restored),
    )


def test_em01_rejection_inside_permission_window_stays_review_only(completion_module):
    module = completion_module
    report = module.evaluate_case_completion(
        _em01_permission_evidence(
            module,
            submit_time="2026-09-28T09:02:30+00:00",
            reject_time="2026-09-28T09:03:00+00:00",
        )
    )
    assert report.status is module.CompletionStatus.REVIEW_REQUIRED
    assert report.certification_pass is False
    assert report.dispatch_permitted is False
    assert report.source_authenticity_verified is False


@pytest.mark.parametrize(
    ("submit_time", "reject_time"),
    (
        ("2026-09-28T09:01:30+00:00", "2026-09-28T09:02:30+00:00"),
        ("2026-09-28T09:04:30+00:00", "2026-09-28T09:04:45+00:00"),
    ),
)
def test_em01_submit_and_rejection_must_fall_inside_permission_window(
    completion_module, submit_time, reject_time
):
    module = completion_module
    report = module.evaluate_case_completion(
        _em01_permission_evidence(module, submit_time=submit_time, reject_time=reject_time)
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "permission_submit_and_rejection_must_occur_while_disabled" in report.contradictions
    assert report.certification_pass is False


def test_o02_repeat_plan_requires_a_real_close_intent_against_closeable_position(
    completion_module,
):
    module = completion_module
    positive = module.evaluate_case_completion(_o02_close_evidence(module))
    assert positive.status is module.CompletionStatus.REVIEW_REQUIRED
    assert positive.certification_pass is False
    assert positive.dispatch_permitted is False
    assert positive.source_authenticity_verified is False

    open_intent = module.evaluate_case_completion(_o02_close_evidence(module, offset="open"))
    assert open_intent.status is module.CompletionStatus.INCOMPLETE
    assert "o02_requires_typed_close_today_or_close_yesterday_bucket" in open_intent.missing_invariants

    generic_close = module.evaluate_case_completion(_o02_close_evidence(module, offset="close"))
    assert generic_close.status is module.CompletionStatus.INCOMPLETE
    assert "o02_requires_typed_close_today_or_close_yesterday_bucket" in generic_close.missing_invariants

    same_side = module.evaluate_case_completion(_o02_close_evidence(module, direction="buy"))
    assert same_side.status is module.CompletionStatus.INCOMPLETE
    assert "o02_close_direction_does_not_match_available_position_side" in same_side.contradictions

    over_close = module.evaluate_case_completion(_o02_close_evidence(module, quantity=2))
    assert over_close.status is module.CompletionStatus.INCOMPLETE
    assert "o02_requested_close_quantity_exceeds_baseline_bucket" in over_close.contradictions


def test_o02_rejects_multiple_dispatched_submit_refs(completion_module):
    module = completion_module
    evidence = _o02_close_evidence(module, quantity="0.4")
    first = evidence.managed_requests[0]
    extra = replace(first, request_id="o02-submit-2", order_refs=("o02-r2",), quantity="0.4", request_generation=2, sequence=2)
    report = module.evaluate_case_completion(
        replace(
            evidence,
            managed_requests=(first, extra, evidence.managed_requests[1], evidence.managed_requests[2]),
        )
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "o02_requires_exactly_one_dispatched_and_one_blocked_submit" in report.contradictions


def test_o02_request_session_must_match_provider_snapshots(completion_module):
    module = completion_module
    evidence = _o02_close_evidence(module)
    request = replace(evidence.managed_requests[0], provider_session_id="previous-provider-session")
    repeat = replace(evidence.managed_requests[1], provider_session_id="previous-provider-session")
    repeat_row = replace(
        evidence.scenario_evidence[0],
        fields={**evidence.scenario_evidence[0].fields, "provider_session_id": "previous-provider-session"},
    )
    report = module.evaluate_case_completion(
        replace(
            evidence,
            managed_requests=(request, repeat, evidence.managed_requests[2]),
            scenario_evidence=(repeat_row,),
        )
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "o02_request_provider_session_must_match_account_snapshots" in report.contradictions


def test_o02_attempts_and_monitor_cannot_relabel_snapshot_account(completion_module):
    module = completion_module
    evidence = _o02_close_evidence(module)
    requests = tuple(
        replace(request, account_id_masked="account-B")
        if request.action is module.RequestAction.SUBMIT
        else request
        for request in evidence.managed_requests
    )
    monitor = replace(
        evidence.scenario_evidence[0],
        fields={**evidence.scenario_evidence[0].fields, "account_id_masked": "account-B"},
    )
    report = module.evaluate_case_completion(
        replace(evidence, managed_requests=requests, scenario_evidence=(monitor,))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "o02_request_account_must_match_account_snapshots" in report.contradictions


def test_o02_native_order_account_must_match_snapshots(completion_module):
    module = completion_module
    evidence = _o02_close_evidence(module)
    order_fact = replace(evidence.order_facts[0], account_id_masked="account-B")
    report = module.evaluate_case_completion(
        replace(evidence, order_facts=(order_fact, evidence.order_facts[1]))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "o02_native_order_account_must_match_account_snapshots" in report.contradictions


def test_o02_native_trade_account_must_match_snapshots(completion_module):
    module = completion_module
    evidence = _o02_close_evidence(module)
    accepted, canceled = evidence.order_facts
    canceled = replace(canceled, source_sequence=6)
    trade = module.NativeTradeFact(
        event_id="o02-trade-account",
        trade_id="o02-trade-account-id",
        order_ref="o02-r1",
        instrument_id=INSTRUMENT,
        quantity=1,
        direction="sell",
        price=3500,
        callback_name="OnRtnTrade",
        source="ctp_provider_callback",
        session_id=SESSION,
        trading_day=TRADING_DAY,
        source_sequence=5,
        occurred_at_utc="2026-09-28T09:02:30+00:00",
        evidence_sha256=DIGEST,
        offset="close_today",
        external_order_id="sys-o02-r1",
        account_id_masked="account-B",
    )
    final = replace(
        evidence.snapshots[1],
        order_query_sequence=7,
        position_query_sequence=8,
        account_query_sequence=9,
    )
    report = module.evaluate_case_completion(
        replace(
            evidence,
            order_facts=(accepted, canceled),
            trade_facts=(trade,),
            snapshots=(evidence.snapshots[0], final),
        )
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "o02_native_trade_account_must_match_account_snapshots" in report.contradictions


def test_o02_attempt_day_must_match_snapshot_day(completion_module):
    module = completion_module
    evidence = _o02_close_evidence(module)
    requests = tuple(
        replace(request, trading_day="20260927")
        if request.action is module.RequestAction.SUBMIT
        else request
        for request in evidence.managed_requests
    )
    monitor = replace(
        evidence.scenario_evidence[0],
        fields={**evidence.scenario_evidence[0].fields, "trading_day": "20260927"},
    )
    report = module.evaluate_case_completion(
        replace(evidence, managed_requests=requests, scenario_evidence=(monitor,))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "o02_request_trading_day_must_match_account_snapshots" in report.contradictions


def test_o02_native_trade_offset_must_match_close_intent(completion_module):
    module = completion_module
    evidence = _o02_close_evidence(module)
    accepted, canceled = evidence.order_facts
    canceled = replace(canceled, source_sequence=6)
    trade = module.NativeTradeFact(
        event_id="o02-trade",
        trade_id="o02-trade-id",
        order_ref="o02-r1",
        instrument_id=INSTRUMENT,
        quantity=1,
        direction="sell",
        price=3500,
        callback_name="OnRtnTrade",
        source="ctp_provider_callback",
        session_id=SESSION,
        trading_day=TRADING_DAY,
        source_sequence=5,
        occurred_at_utc="2026-09-28T09:02:30+00:00",
        evidence_sha256=DIGEST,
        offset="close_yesterday",
        external_order_id="sys-o02-r1",
        account_id_masked="account-A",
    )
    final = replace(
        evidence.snapshots[1],
        order_query_sequence=7,
        position_query_sequence=8,
        account_query_sequence=9,
    )
    report = module.evaluate_case_completion(
        replace(
            evidence,
            order_facts=(accepted, canceled),
            trade_facts=(trade,),
            snapshots=(evidence.snapshots[0], final),
        )
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "o02_trade_offset_must_match_submit" in report.contradictions


def test_o02_scalar_maps_do_not_replace_typed_bucket(completion_module):
    module = completion_module
    evidence = _o02_close_evidence(module)
    baseline = replace(evidence.snapshots[0], closeable_position_buckets=())
    report = module.evaluate_case_completion(
        replace(evidence, snapshots=(baseline, evidence.snapshots[1]))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "o02_requires_matching_baseline_side_and_offset_closeable_bucket" in report.missing_invariants


def test_em01_permission_receipt_must_bind_control_event(completion_module):
    module = completion_module
    row = module.CertificationEvidence(
        event_kind="account_trading_disabled",
        source=importlib.import_module("common.case_engine").EvidenceSource.CONTROL_PLANE,
        event_id="permission-event-A",
        evidence_sha256=DIGEST,
        occurred_at_utc="2026-09-28T09:02:00+00:00",
        fields={"account_id_masked": "account-A"},
    )
    disabled = module.ExternalDependency(
        dependency_id="account_permission_disabled",
        state="satisfied",
        evidence_ref="disable-A",
        evidence_sha256=DIGEST,
        fields={
            "state": "disabled",
            "account_id_masked": "account-A",
            "change_id": "change-A",
            "provider_audit_ref": "provider-A",
            "occurred_at_utc": "2026-09-28T09:02:00+00:00",
            "source_event_ref": row.event_id,
        },
    )
    restored = replace(
        disabled,
        dependency_id="account_permission_restored",
        fields={
            **disabled.fields,
            "state": "restored",
            "occurred_at_utc": "2026-09-28T09:03:00+00:00",
        },
    )
    evidence = module.CompletionEvidence(
        case_id="EM01",
        scenario_evidence=(row,),
        external_dependencies=(disabled, restored),
    )
    missing, contradictions = [], []
    module._check_external_dependencies(evidence, missing, contradictions)
    assert not contradictions
    wrong_disabled = replace(
        disabled, fields={**disabled.fields, "source_event_ref": "unrelated-event"}
    )
    missing, contradictions = [], []
    module._check_external_dependencies(
        replace(evidence, external_dependencies=(wrong_disabled, restored)),
        missing,
        contradictions,
    )
    assert "permission_disable_receipt_does_not_match_control_event" in contradictions


def test_em01_submit_scenario_row_must_match_receipt_time_and_generation(completion_module):
    module = completion_module
    evidence = _em01_permission_evidence(
        module,
        submit_time="2026-09-28T09:02:30+00:00",
        reject_time="2026-09-28T09:03:00+00:00",
    )
    rows = list(evidence.scenario_evidence)
    submit_index = next(i for i, row in enumerate(rows) if row.event_kind == "order_submit_request")
    rows[submit_index] = replace(rows[submit_index], occurred_at_utc="2026-09-28T09:01:30+00:00")
    report = module.evaluate_case_completion(replace(evidence, scenario_evidence=tuple(rows)))
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "permission_submit_scenario_row_does_not_match_managed_receipt" in report.contradictions


def test_em01_rejects_relabelled_submit_account_or_day(completion_module):
    module = completion_module
    evidence = _em01_permission_evidence(
        module,
        submit_time="2026-09-28T09:02:30+00:00",
        reject_time="2026-09-28T09:03:00+00:00",
    )
    request = replace(evidence.managed_requests[0], account_id_masked="account-B")
    rows = tuple(
        replace(row, fields={**row.fields, "account_id_masked": "account-B"})
        for row in evidence.scenario_evidence
    )
    dependencies = tuple(
        replace(dependency, fields={**dependency.fields, "account_id_masked": "account-B"})
        for dependency in evidence.external_dependencies
    )
    fact = replace(evidence.order_facts[0], account_id_masked="account-B")
    report = module.evaluate_case_completion(
        replace(
            evidence,
            managed_requests=(request,),
            scenario_evidence=rows,
            external_dependencies=dependencies,
            order_facts=(fact,),
        )
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "permission_submit_account_identity_mismatch" in report.contradictions

    request = replace(evidence.managed_requests[0], trading_day="20260927")
    rows = tuple(
        replace(row, fields={**row.fields, "trading_day": "20260927"})
        if row.event_kind == "order_submit_request"
        else row
        for row in evidence.scenario_evidence
    )
    report = module.evaluate_case_completion(
        replace(evidence, managed_requests=(request,), scenario_evidence=rows)
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "permission_submit_trading_day_mismatch" in report.contradictions


def test_em01_control_error_id_must_match_rejection(completion_module):
    module = completion_module
    evidence = _em01_permission_evidence(
        module,
        submit_time="2026-09-28T09:02:30+00:00",
        reject_time="2026-09-28T09:03:00+00:00",
    )
    rows = tuple(
        replace(row, fields={**row.fields, "ErrorID": 6})
        if row.event_kind == "account_trading_disabled"
        else row
        for row in evidence.scenario_evidence
    )
    report = module.evaluate_case_completion(replace(evidence, scenario_evidence=rows))
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "permission_control_error_and_blocked_ref_must_match_native_rejection" in report.contradictions


def test_em03_logout_receipt_must_bind_disconnect_event(completion_module):
    module = completion_module
    row = module.CertificationEvidence(
        event_kind="gateway_force_logout_requested",
        source=importlib.import_module("common.case_engine").EvidenceSource.CONTROL_PLANE,
        event_id="logout-event-A",
        evidence_sha256=DIGEST,
        occurred_at_utc="2026-09-28T09:02:00+00:00",
        fields={"gateway_key": "gateway-A"},
        provider_session_id=SESSION,
        trading_day=TRADING_DAY,
    )
    logout = module.ExternalDependency(
        dependency_id="gateway_force_logout_ack",
        state="satisfied",
        evidence_ref="operator-ack-A",
        evidence_sha256=DIGEST,
        fields={
            "acknowledged": True,
            "gateway_key": "gateway-A",
            "session_id": SESSION,
            "operator_audit_ref": "operator-A",
            "source_event_ref": row.event_id,
        },
    )
    evidence = module.CompletionEvidence(
        case_id="EM03", scenario_evidence=(row,), external_dependencies=(logout,)
    )
    missing, contradictions = [], []
    module._check_external_dependencies(evidence, missing, contradictions)
    assert not contradictions
    wrong_logout = replace(logout, fields={**logout.fields, "session_id": "other-session"})
    missing, contradictions = [], []
    module._check_external_dependencies(
        replace(evidence, external_dependencies=(wrong_logout,)), missing, contradictions
    )
    assert "force_logout_receipt_does_not_match_disconnect_event" in contradictions


@pytest.mark.parametrize(
    ("case_id", "overrides", "expected"),
    (
        (
            "V01",
            {"authoritative_lookup_result": "found"},
            "authoritative_contract_lookup_did_not_report_not_found",
        ),
        ("V02", {"proposed_price": "100.05"}, "reported_price_is_aligned_to_contract_tick"),
        ("V03", {"requested_size": "10"}, "reported_size_does_not_exceed_contract_maximum"),
    ),
)
def test_validation_cases_need_an_actual_rule_violation(
    completion_module, case_id, overrides, expected
):
    module = completion_module
    report = module.evaluate_case_completion(_validation_case_evidence(module, case_id))
    assert report.status is module.CompletionStatus.REVIEW_REQUIRED
    assert report.certification_pass is False
    bad_report = module.evaluate_case_completion(
        _validation_case_evidence(module, case_id, overrides)
    )
    assert bad_report.status is module.CompletionStatus.INCOMPLETE
    assert expected in bad_report.contradictions


@pytest.mark.parametrize(
    "overrides",
    ({"proposed_price": "1E+1000000"}, {"price_tick": "1E-1000000"}),
)
def test_tick_validation_rejects_unbounded_exact_arithmetic(completion_module, overrides):
    module = completion_module
    report = module.evaluate_case_completion(_validation_case_evidence(module, "V02", overrides))
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "tick_validation_requires_bounded_contract_decimals" in report.missing_invariants
    assert report.certification_pass is False


@pytest.mark.parametrize(
    ("overrides", "expected"),
    (
        ({"requested_size": "1E+1000000"}, "maximum_size_validation_requires_bounded_size"),
        ({"max_order_size": "1E+1000000"}, "maximum_size_validation_requires_bounded_limit"),
    ),
)
def test_maximum_size_validation_rejects_unbounded_numbers(completion_module, overrides, expected):
    module = completion_module
    report = module.evaluate_case_completion(_validation_case_evidence(module, "V03", overrides))
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert expected in report.missing_invariants
    assert report.certification_pass is False


@pytest.mark.parametrize("case_id", ("T01", "B02"))
def test_managed_dispatch_cannot_follow_final_account_queries(completion_module, case_id):
    module = completion_module
    evidence = _t01_evidence(module) if case_id == "T01" else _b02_cancel_fill_race(module)
    last_request = replace(
        evidence.managed_requests[-1],
        occurred_at_utc="2026-09-28T09:10:00+00:00",
        sequence=999,
    )
    report = module.evaluate_case_completion(
        replace(evidence, managed_requests=(*evidence.managed_requests[:-1], last_request))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert (
        f"managed_request_outside_account_snapshot_window:{last_request.request_id}"
        in report.contradictions
    )


def test_submit_receipt_must_precede_native_order_callback(completion_module):
    module = completion_module
    evidence = _t01_evidence(module)
    late_submit = replace(evidence.managed_requests[0], occurred_at_utc="2026-09-28T09:02:30+00:00")
    report = module.evaluate_case_completion(
        replace(evidence, managed_requests=(late_submit, evidence.managed_requests[1]))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "managed_submit_after_native_order_callback:submit-r1" in report.contradictions


def test_trade_log_fields_must_match_native_trade_fact(completion_module):
    module = completion_module
    evidence = replace(_b02_cancel_fill_race(module), case_id="L01")
    trade = evidence.trade_facts[0]
    trade_row = _scenario_row(
        module,
        "trade_execution",
        "logged-trade-r2",
        {
            "trade_id": trade.trade_id,
            "order_ref": trade.order_ref,
            "external_order_id": trade.external_order_id,
            "instrument_id": "forged-instrument",
            "quantity": 99,
            "direction": "sell",
            "price": 1,
        },
        sequence=trade.source_sequence,
        callback_names=("OnRtnTrade",),
    )
    report = module.evaluate_case_completion(
        replace(evidence, scenario_evidence=(evidence.scenario_evidence[0], trade_row))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "trade_event_fields_do_not_match_native_trade_fact" in report.contradictions


def test_expected_success_orders_reject_terminal_rejection_but_e01_allows_it(
    completion_module,
):
    module = completion_module
    evidence = _t01_evidence(module)
    rejected = replace(
        evidence.order_facts[-1],
        fact=module.NativeOrderFactKind.REJECTED,
        callback_name="OnRspOrderInsert",
        status="rejected",
        error_id=5,
    )
    evidence = replace(evidence, order_facts=(evidence.order_facts[0], rejected))
    report = module.evaluate_case_completion(evidence)
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "unexpected_provider_rejection_for_order_scenario:r1" in report.contradictions

    certification = importlib.import_module("common.certification")
    for case_id in ("T01", "T02", "T03", "B01", "B02"):
        candidate = replace(evidence, case_id=case_id)
        _, contradictions = module._derive_invariants(
            candidate, certification.RECONCILIATION_EXPECTATIONS[case_id]
        )
        assert "unexpected_provider_rejection_for_order_scenario:r1" in contradictions

    remote_rejection = module.evaluate_case_completion(_e01_remote_rejection(module))
    assert remote_rejection.status is module.CompletionStatus.REVIEW_REQUIRED
    assert remote_rejection.certification_pass is False
    assert remote_rejection.dispatch_permitted is False
    assert remote_rejection.source_authenticity_verified is False


def test_partial_then_canceled_with_trade_and_net_position_match_requires_review(
    completion_module,
):
    module = completion_module
    evidence = _t01_evidence(module)
    partial = replace(
        evidence.order_facts[0],
        event_id="order-partial-r1",
        fact=module.NativeOrderFactKind.PARTIAL,
        status="partial",
        traded_quantity="0.25",
        remaining_quantity="0.75",
        source_sequence=6,
        occurred_at_utc="2026-09-28T09:03:20+00:00",
    )
    canceled = replace(
        evidence.order_facts[1],
        source_sequence=7,
        occurred_at_utc="2026-09-28T09:04:00+00:00",
        traded_quantity="0.25",
    )
    trade = module.NativeTradeFact(
        event_id="trade-r1-partial",
        trade_id="trade-r1-partial-id",
        order_ref="r1",
        instrument_id=INSTRUMENT,
        quantity="0.25",
        direction="buy",
        price=3500,
        callback_name="OnRtnTrade",
        source="ctp_provider_callback",
        session_id=SESSION,
        trading_day=TRADING_DAY,
        source_sequence=5,
        occurred_at_utc="2026-09-28T09:03:10+00:00",
        evidence_sha256=DIGEST,
        external_order_id="sys-r1",
    )
    final = replace(
        evidence.snapshots[1],
        order_query_sequence=8,
        position_query_sequence=9,
        account_query_sequence=10,
        occurred_at_utc="2026-09-28T09:05:00+00:00",
        positions={INSTRUMENT: "0.25"},
        funds={"cash": 9999, "available_funds": 8999, "equity": 10000},
    )
    report = module.evaluate_case_completion(
        replace(
            evidence,
            order_facts=(evidence.order_facts[0], partial, canceled),
            trade_facts=(trade,),
            snapshots=(evidence.snapshots[0], final),
        )
    )
    assert report.status is module.CompletionStatus.REVIEW_REQUIRED
    assert report.certification_pass is False
    assert report.dispatch_permitted is False
    assert report.source_authenticity_verified is False


def test_t01_missing_terminal_fact_and_stale_query_are_incomplete(completion_module):
    module = completion_module
    evidence = _t01_evidence(module)
    missing_terminal = replace(evidence, order_facts=evidence.order_facts[:1])
    report = module.evaluate_case_completion(missing_terminal)
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert any("terminal_order_state" in item for item in report.missing_invariants)

    final = replace(evidence.snapshots[1], order_query_sequence=5)
    stale = replace(evidence, snapshots=(evidence.snapshots[0], final))
    report = module.evaluate_case_completion(stale)
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert (
        "final_order_query_must_follow_all_native_order_and_trade_events"
        in report.missing_invariants
    )


def test_order_quantity_conservation_and_trade_order_id_are_mandatory(completion_module):
    module = completion_module
    t01 = _t01_evidence(module)

    bad_accepted = replace(t01.order_facts[0], remaining_quantity="0.5")
    report = module.evaluate_case_completion(
        replace(t01, order_facts=(bad_accepted, t01.order_facts[1]))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "provider_open_quantity_conservation_mismatch:r1" in report.contradictions

    bad_partial = replace(
        t01.order_facts[0],
        fact=module.NativeOrderFactKind.PARTIAL,
        status="partial",
        traded_quantity="0.25",
        remaining_quantity="0.5",
    )
    report = module.evaluate_case_completion(
        replace(t01, order_facts=(bad_partial, t01.order_facts[1]))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "provider_open_quantity_conservation_mismatch:r1" in report.contradictions

    b02 = _b02_cancel_fill_race(module)
    bad_fill = replace(b02.order_facts[2], traded_quantity="0.5")
    report = module.evaluate_case_completion(
        replace(b02, order_facts=(*b02.order_facts[:2], bad_fill, b02.order_facts[3]))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "provider_filled_quantity_does_not_match_request:r2" in report.contradictions

    bad_trade = replace(b02.trade_facts[0], external_order_id="different-sys-id")
    report = module.evaluate_case_completion(replace(b02, trade_facts=(bad_trade,)))
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "trade_external_order_id_mismatch:r2" in report.contradictions


def test_no_trade_case_cannot_hide_position_or_funds_delta(completion_module):
    module = completion_module
    evidence = _t01_evidence(module)
    changed_final = replace(
        evidence.snapshots[1],
        positions={INSTRUMENT: 1},
        funds={"cash": 10000, "available_funds": 9000, "equity": 10000},
    )
    report = module.evaluate_case_completion(
        replace(evidence, snapshots=(evidence.snapshots[0], changed_final))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "positions_or_funds_changed_without_trade_callback" in report.contradictions


def test_b02_allows_cancel_fill_race_only_with_trade_and_position_reconciliation(
    completion_module,
):
    module = completion_module
    evidence = _b02_cancel_fill_race(module)
    report = module.evaluate_case_completion(evidence)
    assert report.status is module.CompletionStatus.REVIEW_REQUIRED
    assert report.certification_pass is False
    assert report.dispatch_permitted is False

    bad_batch = replace(evidence.managed_requests[-1], order_refs=("r1", "ghost"))
    mismatched = replace(evidence, managed_requests=(*evidence.managed_requests[:-1], bad_batch))
    report = module.evaluate_case_completion(mismatched)
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "batch_cancel_refs_must_exactly_match_submitted_orders" in report.contradictions

    no_trade = replace(evidence, trade_facts=())
    report = module.evaluate_case_completion(no_trade)
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert any("terminal_trade_quantity_mismatch" in item for item in report.contradictions)


def test_b01_requires_two_partial_order_lifecycles_and_trade_reconciliation(completion_module):
    module = completion_module
    evidence = replace(_b02_cancel_fill_race(module), case_id="B01")
    report = module.evaluate_case_completion(evidence)
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "required_native_trade_activity" not in report.missing_invariants
    assert "partial_fill_required:r1" in report.missing_invariants
    assert "partial_fill_required:r2" in report.missing_invariants


@pytest.mark.parametrize(
    ("case_id", "required_invariant"),
    [
        ("O01", "repeat_scenario_requires_second_submit_blocked_pre_dispatch"),
        ("O02", "repeat_scenario_requires_second_submit_blocked_pre_dispatch"),
        ("O03", "repeat_cancel_requires_second_attempt_blocked_pre_dispatch"),
        ("TH04", "managed_dispatched_cancel_receipt"),
    ],
)
def test_repeat_and_threshold_cancel_plans_need_explicit_attempt_receipts(
    completion_module, case_id, required_invariant
):
    module = completion_module
    evidence = module.CompletionEvidence(
        case_id=case_id,
        snapshots=(
            _snapshot(module, module.SnapshotPhase.BASELINE, 1, "2026-09-28T09:00:00+00:00"),
            _snapshot(module, module.SnapshotPhase.FINAL, 4, "2026-09-28T09:05:00+00:00"),
        ),
    )
    report = module.evaluate_case_completion(evidence)
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert required_invariant in report.missing_invariants


def test_external_reject_and_emergency_cases_require_sourced_physical_conditions(completion_module):
    module = completion_module
    for case_id, dependency_id in (
        ("E03", "market_state"),
        ("EM01", "account_permission_disabled"),
        ("EM03", "gateway_force_logout_ack"),
    ):
        snapshots = (
            _snapshot(module, module.SnapshotPhase.BASELINE, 1, "2026-09-28T09:00:00+00:00"),
            _snapshot(module, module.SnapshotPhase.FINAL, 4, "2026-09-28T09:05:00+00:00"),
        )
        if case_id == "C01":
            snapshots = tuple(
                replace(
                    snapshot,
                    session_id="",
                    trading_day="",
                    session_identity_origin="",
                )
                for snapshot in snapshots
            )
        evidence = module.CompletionEvidence(case_id=case_id, snapshots=snapshots)
        report = module.evaluate_case_completion(evidence)
        assert report.status is module.CompletionStatus.INCOMPLETE
        assert f"external_dependency:{dependency_id}" in report.missing_invariants


def test_queries_require_native_error_free_final_markers(completion_module):
    module = completion_module
    evidence = _t01_evidence(module)
    bad_query = replace(
        evidence.snapshots[1],
        query_is_last=dict.fromkeys(QUERY_CALLBACKS[:-1], True),
    )
    with pytest.raises(module.CompletionEvidenceError, match="final callback marker"):
        module.evaluate_case_completion(
            replace(evidence, snapshots=(evidence.snapshots[0], bad_query))
        )


def _m03_reconnect_evidence(module):
    case_engine = importlib.import_module("common.case_engine")
    new_session = "session-007-reconnected"
    baseline = _snapshot(module, module.SnapshotPhase.BASELINE, 1, "2026-09-28T09:00:00+00:00")
    final = replace(
        _snapshot(module, module.SnapshotPhase.FINAL, 2, "2026-09-28T09:05:00+00:00"),
        session_id=new_session,
        order_query_id=baseline.order_query_id,
        position_query_id=baseline.position_query_id,
        account_query_id=baseline.account_query_id,
    )
    disconnected = module.CertificationEvidence(
        event_kind="store_disconnected",
        source=case_engine.EvidenceSource.PROVIDER_CALLBACK,
        event_id="disconnect-before-reconnect-007",
        evidence_sha256=DIGEST,
        occurred_at_utc="2026-09-28T09:01:00+00:00",
        fields={
            "gateway_key": "ctp-gateway",
            "timestamp": "2026-09-28T09:01:00+00:00",
            "connection_generation": 7,
        },
        callback_names=("OnFrontDisconnected",),
        provider_session_id=SESSION,
        trading_day=TRADING_DAY,
        source_sequence=4,
    )
    row = module.CertificationEvidence(
        event_kind="store_reconnect_success",
        source=case_engine.EvidenceSource.PROVIDER_CALLBACK,
        event_id="reconnect-session-007",
        evidence_sha256=DIGEST,
        occurred_at_utc="2026-09-28T09:03:00+00:00",
        fields={
            "gateway_key": "ctp-gateway",
            "timestamp": "2026-09-28T09:03:00+00:00",
            "previous_session_id": SESSION,
            "new_session_id": new_session,
            "connection_generation": 8,
            "previous_connection_generation": 7,
            "new_connection_generation": 8,
            "auth_error_id": 0,
            "login_error_id": 0,
            "subscription_error_id": 0,
            "authentication_succeeded": True,
            "login_succeeded": True,
            "subscription_succeeded": True,
        },
        callback_names=(
            "OnFrontConnected",
            "OnRspAuthenticate",
            "OnRspUserLogin",
            "OnRspSubMarketData",
        ),
        provider_session_id=new_session,
        trading_day=TRADING_DAY,
        source_sequence=1,
    )
    dependency = module.ExternalDependency(
        dependency_id="external_reconnect",
        state="satisfied",
        evidence_ref="control-reconnect-session-007",
        evidence_sha256=DIGEST,
        fields={
            "gateway_key": "ctp-gateway",
            "previous_session_id": SESSION,
            "new_session_id": new_session,
            "disconnect_event_ref": disconnected.event_id,
            "reconnect_event_ref": row.event_id,
            "previous_connection_generation": 7,
            "new_connection_generation": 8,
        },
    )
    return module.CompletionEvidence(
        case_id="M03",
        scenario_evidence=(disconnected, row),
        snapshots=(baseline, final),
        external_dependencies=(dependency,),
    )


def _m02_disconnect_evidence(module):
    case_engine = importlib.import_module("common.case_engine")
    new_session = "session-007-restored"
    baseline = _snapshot(module, module.SnapshotPhase.BASELINE, 1, "2026-09-28T09:00:00+00:00")
    final = replace(
        _snapshot(module, module.SnapshotPhase.FINAL, 2, "2026-09-28T09:05:00+00:00"),
        session_id=new_session,
        order_query_id=baseline.order_query_id,
        position_query_id=baseline.position_query_id,
        account_query_id=baseline.account_query_id,
    )
    disconnected = module.CertificationEvidence(
        event_kind="store_disconnected",
        source=case_engine.EvidenceSource.PROVIDER_CALLBACK,
        event_id="disconnect-session-007",
        evidence_sha256=DIGEST,
        occurred_at_utc="2026-09-28T09:01:00+00:00",
        fields={
            "gateway_key": "ctp-gateway",
            "timestamp": "2026-09-28T09:01:00+00:00",
            "connection_generation": 7,
        },
        callback_names=("OnFrontDisconnected",),
        provider_session_id=SESSION,
        trading_day=TRADING_DAY,
        source_sequence=4,
    )
    reconnected = module.CertificationEvidence(
        event_kind="store_reconnect_success",
        source=case_engine.EvidenceSource.PROVIDER_CALLBACK,
        event_id="restore-session-007",
        evidence_sha256=DIGEST,
        occurred_at_utc="2026-09-28T09:03:00+00:00",
        fields={
            "gateway_key": "ctp-gateway",
            "timestamp": "2026-09-28T09:03:00+00:00",
            "previous_session_id": SESSION,
            "new_session_id": new_session,
            "connection_generation": 8,
            "previous_connection_generation": 7,
            "new_connection_generation": 8,
            "auth_error_id": 0,
            "login_error_id": 0,
            "subscription_error_id": 0,
            "authentication_succeeded": True,
            "login_succeeded": True,
            "subscription_succeeded": True,
        },
        callback_names=(
            "OnFrontConnected",
            "OnRspAuthenticate",
            "OnRspUserLogin",
            "OnRspSubMarketData",
        ),
        provider_session_id=new_session,
        trading_day=TRADING_DAY,
        source_sequence=1,
    )
    dependency = module.ExternalDependency(
        dependency_id="external_disconnect",
        state="satisfied",
        evidence_ref="control-disconnect-session-007",
        evidence_sha256=DIGEST,
        fields={
            "gateway_key": "ctp-gateway",
            "session_id": SESSION,
            "provider_event_ref": disconnected.event_id,
            "connection_generation": 7,
        },
    )
    return module.CompletionEvidence(
        case_id="M02",
        scenario_evidence=(disconnected, reconnected),
        snapshots=(baseline, final),
        external_dependencies=(dependency,),
    )


def test_m02_disconnection_requires_restored_provider_session_before_final_queries(
    completion_module,
):
    module = completion_module
    evidence = _m02_disconnect_evidence(module)
    report = module.evaluate_case_completion(evidence)
    assert report.status is module.CompletionStatus.REVIEW_REQUIRED
    assert report.certification_pass is False
    assert report.dispatch_permitted is False
    assert report.source_authenticity_verified is False

    missing_restore = replace(evidence, scenario_evidence=evidence.scenario_evidence[:1])
    report = module.evaluate_case_completion(missing_restore)
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "scenario_event:store_reconnect_success" in report.missing_invariants

    wrong_restore = replace(
        evidence.scenario_evidence[1],
        fields={**evidence.scenario_evidence[1].fields, "new_session_id": "other-session"},
    )
    with pytest.raises(module.CompletionEvidenceError, match="restoration"):
        module.evaluate_case_completion(
            replace(evidence, scenario_evidence=(evidence.scenario_evidence[0], wrong_restore))
        )

    wrong_control = replace(
        evidence.external_dependencies[0],
        fields={
            **evidence.external_dependencies[0].fields,
            "provider_event_ref": "other-disconnect",
        },
    )
    report = module.evaluate_case_completion(
        replace(evidence, external_dependencies=(wrong_control,))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "disconnect_control_receipt_does_not_match_provider_event" in report.contradictions


@pytest.mark.parametrize("case_id", ("M02", "M03"))
def test_restoration_failure_cannot_reach_review(completion_module, case_id):
    module = completion_module
    evidence = (
        _m02_disconnect_evidence(module) if case_id == "M02" else _m03_reconnect_evidence(module)
    )
    failed_restore = replace(
        evidence.scenario_evidence[1],
        fields={
            **evidence.scenario_evidence[1].fields,
            "auth_error_id": 17,
            "login_succeeded": False,
            "subscription_succeeded": False,
        },
    )
    with pytest.raises(module.CompletionEvidenceError, match="must succeed"):
        module.evaluate_case_completion(
            replace(
                evidence,
                scenario_evidence=(evidence.scenario_evidence[0], failed_restore),
            )
        )

    contradictory_error = replace(
        evidence.scenario_evidence[1],
        fields={**evidence.scenario_evidence[1].fields, "ErrorID": 17},
    )
    with pytest.raises(module.CompletionEvidenceError, match="must succeed"):
        module.evaluate_case_completion(
            replace(
                evidence,
                scenario_evidence=(evidence.scenario_evidence[0], contradictory_error),
            )
        )


@pytest.mark.parametrize("case_id", ("M02", "M03"))
def test_baseline_query_sequence_must_precede_disconnect_in_same_session(
    completion_module, case_id
):
    module = completion_module
    evidence = (
        _m02_disconnect_evidence(module) if case_id == "M02" else _m03_reconnect_evidence(module)
    )
    baseline = replace(
        evidence.snapshots[0],
        order_query_sequence=10,
        position_query_sequence=11,
        account_query_sequence=12,
    )
    report = module.evaluate_case_completion(
        replace(evidence, snapshots=(baseline, evidence.snapshots[1]))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "baseline_account_queries_must_precede_disconnect_callback" in report.contradictions


@pytest.mark.parametrize("case_id", ("M02", "M03"))
def test_restoration_requires_new_connection_generation(completion_module, case_id):
    module = completion_module
    evidence = (
        _m02_disconnect_evidence(module) if case_id == "M02" else _m03_reconnect_evidence(module)
    )
    restored = replace(
        evidence.scenario_evidence[1],
        fields={
            **evidence.scenario_evidence[1].fields,
            "connection_generation": 7,
            "new_connection_generation": 7,
        },
    )
    report = module.evaluate_case_completion(
        replace(evidence, scenario_evidence=(evidence.scenario_evidence[0], restored))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    expected = (
        "disconnect_restoration_requires_new_connection_generation"
        if case_id == "M02"
        else "reconnect_requires_new_connection_generation"
    )
    assert expected in report.contradictions


def test_m03_reconnect_accepts_reset_query_sequences_only_with_correlated_sessions(
    completion_module,
):
    module = completion_module
    evidence = _m03_reconnect_evidence(module)
    report = module.evaluate_case_completion(evidence)
    assert report.status is module.CompletionStatus.REVIEW_REQUIRED
    assert report.certification_pass is False
    assert report.dispatch_permitted is False
    assert report.source_authenticity_verified is False

    bad_row = replace(
        evidence.scenario_evidence[1],
        fields={**evidence.scenario_evidence[1].fields, "new_session_id": "other-session"},
    )
    with pytest.raises(module.CompletionEvidenceError, match="restoration"):
        module.evaluate_case_completion(
            replace(evidence, scenario_evidence=(evidence.scenario_evidence[0], bad_row))
        )

    wrong_control = replace(
        evidence.external_dependencies[0],
        fields={**evidence.external_dependencies[0].fields, "gateway_key": "other-gateway"},
    )
    report = module.evaluate_case_completion(
        replace(evidence, external_dependencies=(wrong_control,))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "reconnect_control_receipt_does_not_match_snapshot_sessions" in report.contradictions

    same_session = replace(
        evidence.snapshots[1],
        session_id=SESSION,
        order_query_id="final-order",
        position_query_id="final-position",
        account_query_id="final-account",
        order_query_sequence=4,
        position_query_sequence=5,
        account_query_sequence=6,
    )
    report = module.evaluate_case_completion(
        replace(evidence, snapshots=(evidence.snapshots[0], same_session))
    )
    assert report.status is module.CompletionStatus.INCOMPLETE
    assert "reconnect_snapshots_require_distinct_provider_sessions" in report.missing_invariants

    next_day = replace(evidence.snapshots[1], trading_day="20260929")
    with pytest.raises(module.CompletionEvidenceError, match="one trading day"):
        module.evaluate_case_completion(
            replace(evidence, snapshots=(evidence.snapshots[0], next_day))
        )
