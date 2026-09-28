"""Focused contracts for TH04's combined managed submit/cancel threshold."""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITE_ROOT = REPO_ROOT / "examples" / "007_ctp" / "live_certification" / "simnow_penetration"
CASE_PATH = SUITE_ROOT / "cases" / "TH04" / "TH04_strategy.py"
NOW = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)
CONFIG_DIGEST = "a" * 64
MONITOR_DIGEST = "b" * 64


class SyntheticAuthenticator:
    """Test-only interface fake; it is not source-authenticity evidence."""

    def __init__(self, module):
        self.module = module

    def authenticate(self, event, scope):
        return self.module.AuthenticationReceipt(
            event_id=event.event_id,
            evidence_sha256=event.evidence_sha256,
            scope_sha256=scope.scope_sha256,
            trust_domain=event.source_domain,
            verification_ref="test-only-synthetic-authenticator",
        )


@pytest.fixture
def decision_module():
    previous = {
        name: module
        for name, module in sys.modules.items()
        if name == "common" or name.startswith("common.")
    }
    old_path = sys.path[:]
    old_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    for name in previous:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(SUITE_ROOT))
    try:
        yield importlib.import_module("common.decision_engine")
    finally:
        for name in list(sys.modules):
            if name == "common" or name.startswith("common."):
                sys.modules.pop(name, None)
        sys.modules.update(previous)
        sys.path[:] = old_path
        sys.dont_write_bytecode = old_bytecode


def _plan_and_engine(module):
    case_engine = importlib.import_module("common.case_engine")
    plan = case_engine.load_descriptive_case_plan(CASE_PATH, expected_case_id="TH04")
    scope = module.DecisionScope.for_plan(plan, "f" * 64)
    engine = module.CaseIntentDecisionEngine(plan, scope, SyntheticAuthenticator(module))
    return engine


def _event(module, kind_name, sequence, fields, *, stream, provider=False):
    kind = module.ObservationKind[kind_name]
    domain, callback, _ = module._POLICY[kind]
    fields = dict(fields)
    callback_metadata = {}
    provider_session_id = "10001" if provider else ""
    trading_day = "20260928" if provider else ""
    provider_front_id = None
    if kind is module.ObservationKind.LOGIN_SUCCESS:
        # OnRspUserLogin is the source of FrontID/SessionID/TradingDay. Local
        # request, arrival, sequence, and clock fields stay explicitly local.
        fields.update(
            request_id=1,
            request_generation=1,
            arrival_generation=1,
            is_last=True,
            error_id=0,
            success=True,
            provider_front_id=1,
            provider_session_id=provider_session_id,
            trading_day=trading_day,
        )
        provider_front_id = 1
        callback_metadata.update(
            client_instance_id="test-native-client",
            request_id_origin="native_callback_argument",
            request_generation=1,
            request_generation_origin="local_request_generation_binding",
            arrival_generation=1,
            sequence_origin="local_sdk_callback_arrival",
            timestamp_origin="local_sdk_capture_clock",
            event_id_origin="local_sdk_callback_arrival",
            provider_issued_event_id=False,
            arrived_at_utc=(NOW - timedelta(seconds=10 - sequence))
            .isoformat()
            .replace("+00:00", "Z"),
            arrived_monotonic=float(sequence),
            connection_generation_origin="local_connection_generation",
            session_identity_origin="native_login_response_fields",
        )
    return module.NativeObservation(
        kind=kind,
        source_domain=domain,
        event_id=f"{kind_name.lower()}-{sequence}",
        evidence_sha256=f"{sequence:064x}",
        occurred_at_utc=(NOW - timedelta(seconds=10 - sequence)).isoformat().replace("+00:00", "Z"),
        sequence=sequence,
        stream_id=stream,
        callback_name=callback,
        provider_session_id=provider_session_id,
        trading_day=trading_day,
        provider_front_id=provider_front_id,
        fields=fields,
        **callback_metadata,
    )


def _record_positive_evidence(module, engine, *, duplicate_cancel_callback=False):
    facts = (
        (
            "ORDER_ACCEPTED",
            {
                "order_ref": "R1",
                "external_order_id": "sys-1",
                "instrument_id": "rb2710",
                "status": "working",
                "remaining_quantity": "1",
                "traded_quantity": "0",
            },
        ),
        (
            "ORDER_ACCEPTED",
            {
                "order_ref": "R2",
                "external_order_id": "sys-2",
                "instrument_id": "rb2710",
                "status": "working",
                "remaining_quantity": "1",
                "traded_quantity": "0",
            },
        ),
        (
            "ORDER_CANCELED",
            {
                "order_ref": "R1",
                "external_order_id": "sys-1",
                "instrument_id": "rb2710",
                "status": "canceled",
                "remaining_quantity": "0",
                "traded_quantity": "0",
            },
        ),
    )
    # The login response alone introduces native provider identity. It is an
    # offline fixture, not provider authentication or issuer-ledger evidence.
    provider_events = [
        _event(module, "LOGIN_SUCCESS", 1, {}, stream="provider", provider=True)
    ]
    for sequence, (kind, fields) in enumerate(facts, 2):
        provider_events.append(
            _event(module, kind, sequence, fields, stream="provider", provider=True)
        )
    if duplicate_cancel_callback:
        provider_events.append(
            _event(
                module,
                "ORDER_CANCELED",
                5,
                {
                    "order_ref": "R1",
                    "external_order_id": "sys-1",
                    "instrument_id": "rb2710",
                    "status": "canceled",
                    "remaining_quantity": "0",
                    "traded_quantity": "0",
                },
                stream="provider",
                provider=True,
            )
        )

    managed = (
        ("ORDER_SUBMIT_RECEIPT", "submit-1", "submit", "R1", "dispatched"),
        ("ORDER_SUBMIT_RECEIPT", "submit-2", "submit", "R2", "dispatched"),
        ("ORDER_CANCEL_RECEIPT", "cancel-1", "cancel", "R1", "dispatched"),
        ("ORDER_CANCEL_RECEIPT", "blocked-cancel", "cancel", "R1", "blocked_pre_dispatch"),
    )
    managed_events = []
    for sequence, (kind, request_id, action, order_ref, dispatch_state) in enumerate(managed, 1):
        managed_events.append(
            _event(
                module,
                kind,
                sequence,
                {
                    "request_id": request_id,
                    "action": action,
                    "order_ref": order_ref,
                    "trace_id": f"trace-{request_id}",
                    "dispatch_state": dispatch_state,
                },
                stream="managed",
            )
        )

    config = _event(
        module,
        "MONITOR_CONFIGURATION",
        1,
        {
            "metric": "combined_order_cancel_count",
            "threshold": 3,
            "configuration_digest": CONFIG_DIGEST,
            "monitor_digest": MONITOR_DIGEST,
        },
        stream="monitor",
    )
    native_source_ids = tuple(
        sorted(
            event.event_id
            for event in provider_events
            if event.kind
            in {
                module.ObservationKind.ORDER_ACCEPTED,
                module.ObservationKind.ORDER_CANCELED,
            }
        )
    )
    trigger = _event(
        module,
        "MONITOR_TRIGGER",
        2,
        {
            "metric": "combined_order_cancel_count",
            "threshold": 3,
            "observed_value": 3,
            "configuration_digest": CONFIG_DIGEST,
            "monitor_digest": MONITOR_DIGEST,
            "source_request_ids": ("cancel-1", "submit-1", "submit-2"),
            "source_native_event_ids": native_source_ids,
        },
        stream="monitor",
    )
    for event in (*provider_events, *managed_events, config, trigger):
        assert engine.record(event)
    return engine


def test_th04_counts_dispatched_submit_plus_cancel_requests_not_cancel_callback_refs(
    decision_module,
):
    engine = _record_positive_evidence(decision_module, _plan_and_engine(decision_module))
    result = engine.evaluate(now_utc=NOW)
    assert result.status is decision_module.DecisionStatus.REVIEW_REQUIRED
    assert result.certification_pass is False
    assert result.dispatch_permitted is False
    assert result.intent_candidate is not None
    # Three dispatched requests include two submits and one cancel. The extra
    # blocked retry and native callback cardinality do not raise that count.
    assert result.intent_candidate.correlation_refs == ("R1", "R2")


def test_th04_native_cancel_callback_count_does_not_replace_managed_request_count(
    decision_module,
):
    engine = _record_positive_evidence(
        decision_module,
        _plan_and_engine(decision_module),
        duplicate_cancel_callback=True,
    )
    result = engine.evaluate(now_utc=NOW)
    assert result.status is decision_module.DecisionStatus.REVIEW_REQUIRED
    assert result.certification_pass is False
    assert result.dispatch_permitted is False


@pytest.mark.parametrize(
    "mutate, expected_missing",
    (
        (
            lambda fields: fields.update(configuration_digest="c" * 64),
            "threshold_trigger_not_correlated_to_native_activity",
        ),
        (
            lambda fields: fields.update(source_request_ids=("cancel-1", "submit-1")),
            "threshold_trigger_not_correlated_to_native_activity",
        ),
        (
            lambda fields: fields.update(source_native_event_ids=("unrelated-event",)),
            "threshold_trigger_not_correlated_to_native_activity",
        ),
        (
            lambda fields: fields.update(
                observed_value=4,
                source_request_ids=("blocked-cancel", "cancel-1", "submit-1", "submit-2"),
            ),
            "threshold_trigger_not_correlated_to_native_activity",
        ),
    ),
)
def test_th04_requires_bound_config_and_exact_managed_and_native_source_ids(
    decision_module, mutate, expected_missing
):
    engine = _plan_and_engine(decision_module)
    _record_positive_evidence(decision_module, engine)
    trigger = engine._last(decision_module.ObservationKind.MONITOR_TRIGGER)
    fields = dict(trigger.fields)
    mutate(fields)
    engine._events[engine._events.index(trigger)] = trigger.__class__(
        **{**trigger.__dict__, "fields": fields}
    )
    result = engine.evaluate(now_utc=NOW)
    assert result.status is decision_module.DecisionStatus.INCOMPLETE
    assert expected_missing in result.missing_conditions
    assert result.certification_pass is False
    assert result.dispatch_permitted is False


def test_th04_cancel_receipt_must_match_native_open_order_reference(decision_module):
    engine = _plan_and_engine(decision_module)
    _record_positive_evidence(decision_module, engine)
    receipt = engine._all(decision_module.ObservationKind.ORDER_CANCEL_RECEIPT)[0]
    fields = dict(receipt.fields)
    fields["order_ref"] = "UNKNOWN"
    engine._events[engine._events.index(receipt)] = receipt.__class__(
        **{**receipt.__dict__, "fields": fields}
    )
    result = engine.evaluate(now_utc=NOW)
    assert result.status is decision_module.DecisionStatus.INCOMPLETE
    assert "threshold_trigger_not_correlated_to_native_activity" in result.missing_conditions


def test_th04_two_submit_requests_cannot_share_one_provider_order_ref(decision_module):
    engine = _plan_and_engine(decision_module)
    _record_positive_evidence(decision_module, engine)
    receipt = engine._all(decision_module.ObservationKind.ORDER_SUBMIT_RECEIPT)[1]
    fields = dict(receipt.fields)
    fields["order_ref"] = "R1"
    engine._events[engine._events.index(receipt)] = receipt.__class__(
        **{**receipt.__dict__, "fields": fields}
    )
    result = engine.evaluate(now_utc=NOW)
    assert result.status is decision_module.DecisionStatus.INCOMPLETE
    assert "threshold_trigger_not_correlated_to_native_activity" in result.missing_conditions


def test_th04_missing_cancel_receipt_fields_are_rejected_and_case_stays_incomplete(
    decision_module,
):
    engine = _plan_and_engine(decision_module)
    assert engine.record(
        _event(
            decision_module,
            "MONITOR_CONFIGURATION",
            1,
            {
                "metric": "combined_order_cancel_count",
                "threshold": 3,
                "configuration_digest": CONFIG_DIGEST,
                "monitor_digest": MONITOR_DIGEST,
            },
            stream="monitor",
        )
    )
    malformed = _event(
        decision_module,
        "ORDER_CANCEL_RECEIPT",
        1,
        {"order_ref": "R1", "trace_id": "trace-1", "dispatch_state": "dispatched"},
        stream="managed",
    )
    with pytest.raises(decision_module.DecisionError, match="request_id, action"):
        engine.record(malformed)
    result = engine.evaluate(now_utc=NOW)
    assert result.status is decision_module.DecisionStatus.INCOMPLETE
    assert decision_module.ObservationKind.ORDER_CANCEL_RECEIPT.value in result.missing_conditions


def test_th04_missing_cancel_receipt_remains_incomplete(decision_module):
    engine = _plan_and_engine(decision_module)
    _record_positive_evidence(decision_module, engine)
    engine._events = [
        event
        for event in engine._events
        if event.kind is not decision_module.ObservationKind.ORDER_CANCEL_RECEIPT
    ]
    result = engine.evaluate(now_utc=NOW)
    assert result.status is decision_module.DecisionStatus.INCOMPLETE
    assert decision_module.ObservationKind.ORDER_CANCEL_RECEIPT.value in result.missing_conditions
