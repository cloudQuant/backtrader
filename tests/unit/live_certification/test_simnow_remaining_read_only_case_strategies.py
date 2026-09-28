"""Synthetic contracts for the remaining unregistered typed 007 strategies.

The authenticator and receipts here are deliberately fake interface probes.
These tests make no claim about CTP, SimNow, source authenticity, or certification.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITE_ROOT = REPO_ROOT / "examples" / "007_ctp" / "live_certification" / "simnow_penetration"
CASES_ROOT = SUITE_ROOT / "cases"
NOW = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def case_modules():
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
        decision = importlib.import_module("common.decision_engine")
        case_engine = importlib.import_module("common.case_engine")
        strategies = {}
        for case_id in ("M02", "M03", "M04", "M05", "L03"):
            path = CASES_ROOT / case_id / f"{case_id}_strategy.py"
            spec = importlib.util.spec_from_file_location(f"strategy_{case_id}_test", path)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            strategies[case_id] = module
        yield decision, case_engine, strategies
    finally:
        for name in list(sys.modules):
            if name == "common" or name.startswith("common."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
        sys.path[:] = previous_path


class SyntheticAuthenticator:
    """Not a production verifier; it only exercises the injection contract."""

    def __init__(self, module):
        self.module = module

    def authenticate(self, event, scope):
        return self.module.AuthenticationReceipt(
            event_id=event.event_id,
            evidence_sha256=event.evidence_sha256,
            scope_sha256=scope.scope_sha256,
            trust_domain=event.source_domain,
            verification_ref="synthetic-test-only",
        )


def _make_engine(decision, case_engine, strategies, case_id):
    plan = case_engine.load_descriptive_case_plan(
        CASES_ROOT / case_id / f"{case_id}_strategy.py", expected_case_id=case_id
    )
    scope = decision.DecisionScope.for_plan(plan, "f" * 64)
    return plan, strategies[case_id].create_strategy(plan, scope, SyntheticAuthenticator(decision))


def _event(
    module,
    kind_name,
    event_id,
    sequence,
    seconds,
    fields,
    *,
    session="",
    day="",
    stream=None,
    front_id=None,
):
    kind = module.ObservationKind[kind_name]
    domain, callback, _ = module._POLICY[kind]
    is_provider = domain is module.EvidenceTrustDomain.CTP_CALLBACK
    is_auth = kind is module.ObservationKind.AUTH_SUCCESS
    is_login = kind is module.ObservationKind.LOGIN_SUCCESS
    is_payloadless_front = kind in {
        module.ObservationKind.FRONT_CONNECTED,
        module.ObservationKind.FRONT_DISCONNECTED,
    }
    event_fields = dict(fields)
    if is_provider:
        event_fields.setdefault("connection_generation", 1)
    occurred_at = (NOW + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
    provider_front_id = None
    provider_session_id = session if is_provider and not (is_auth or is_payloadless_front) else ""
    trading_day = day if is_provider and not (is_auth or is_payloadless_front) else ""
    client_instance_id = ""
    arrival_generation = 0
    session_identity_origin = ""
    request_generation = 0
    request_id_origin = ""
    request_generation_origin = ""
    event_id_origin = ""
    arrived_at_utc = ""
    arrived_monotonic = 0.0
    sequence_origin = ""
    timestamp_origin = ""
    connection_generation_origin = ""

    if is_login:
        if type(front_id) is not int or front_id < 1:
            raise AssertionError("login fixtures require an explicit positive native FrontID")
        event_fields.setdefault("provider_front_id", front_id)
        event_fields.setdefault("provider_session_id", session)
        event_fields.setdefault("trading_day", day)
        provider_front_id = event_fields["provider_front_id"]
        provider_session_id = event_fields["provider_session_id"]
        trading_day = event_fields["trading_day"]
        session_identity_origin = "native_login_response_fields"
    elif is_auth:
        session_identity_origin = "unavailable_on_native_authentication_response"

    if is_auth or is_login:
        connection_generation = event_fields.setdefault("connection_generation", 1)
        arrival_generation = event_fields.setdefault("arrival_generation", connection_generation)
        event_fields.setdefault("request_id", sequence)
        request_generation = event_fields.setdefault("request_generation", sequence)
        event_fields.setdefault("is_last", True)
        request_id_origin = "native_callback_argument"
        request_generation_origin = "local_request_generation_binding"
        client_instance_id = "synthetic-client-1"
        event_id_origin = "local_sdk_callback_arrival"
        arrived_at_utc = occurred_at
        arrived_monotonic = float(sequence)
        sequence_origin = "local_sdk_callback_arrival"
        timestamp_origin = "local_sdk_capture_clock"
    elif is_payloadless_front:
        arrival_generation = event_fields["connection_generation"]
        client_instance_id = "synthetic-client-1"
        session_identity_origin = "unavailable_on_native_front_connection_callback"
        connection_generation_origin = "local_connection_generation"
    elif is_provider:
        arrival_generation = event_fields["connection_generation"]
        client_instance_id = "synthetic-client-1"
        session_identity_origin = "derived_from_same_client_generation_native_login"

    return module.NativeObservation(
        kind=kind,
        source_domain=domain,
        event_id=event_id,
        evidence_sha256=f"{sequence + 1:064x}",
        occurred_at_utc=occurred_at,
        sequence=sequence,
        stream_id=stream or domain.value,
        callback_name=callback,
        provider_front_id=provider_front_id,
        provider_session_id=provider_session_id,
        trading_day=trading_day,
        fields=event_fields,
        client_instance_id=client_instance_id,
        request_generation=request_generation,
        request_id_origin=request_id_origin,
        request_generation_origin=request_generation_origin,
        arrival_generation=arrival_generation,
        session_identity_origin=session_identity_origin,
        event_id_origin="local_sdk_callback_arrival" if is_provider else event_id_origin,
        provider_issued_event_id=False,
        arrived_at_utc=occurred_at if is_provider else arrived_at_utc,
        arrived_monotonic=float(sequence) if is_provider else arrived_monotonic,
        sequence_origin="local_sdk_callback_arrival" if is_provider else sequence_origin,
        timestamp_origin="local_sdk_capture_clock" if is_provider else timestamp_origin,
        connection_generation_origin=connection_generation_origin,
    )

def _record(engine, event):
    assert engine.record(event)


def _recovery_events(module, *, bad_summary=False):
    old, new, day, gateway = "79", "80", "20260928", "gateway-a"
    generation_old, generation_new = 8, 9
    pre_disconnect_login = _event(
        module,
        "LOGIN_SUCCESS",
        "old-login",
        1,
        0,
        {"error_id": 0, "success": True, "connection_generation": generation_old},
        session=old,
        day=day,
        front_id=7,
        stream="ctp",
    )
    callbacks = [
        _event(
            module,
            "FRONT_DISCONNECTED",
            "old-disconnect",
            2,
            1,
            {
                "gateway_key": gateway,
                "reason": "controlled_transport_fault",
                "connection_generation": generation_old,
            },
            session=old,
            day=day,
            stream="ctp",
        ),
        _event(
            module,
            "FRONT_CONNECTED",
            "new-front",
            3,
            4,
            {"gateway_key": gateway, "connection_generation": generation_new},
            session=new,
            day=day,
            stream="ctp",
        ),
        _event(
            module,
            "AUTH_SUCCESS",
            "new-auth",
            4,
            5,
            {"error_id": 0, "success": True, "connection_generation": generation_new},
            session=new,
            day=day,
            stream="ctp",
        ),
        _event(
            module,
            "LOGIN_SUCCESS",
            "new-login",
            5,
            6,
            {"error_id": 0, "success": True, "connection_generation": generation_new},
            session=new,
            day=day,
            front_id=7,
            stream="ctp",
        ),
        _event(
            module,
            "MARKET_SUBSCRIPTION_ACK",
            "new-subscription",
            6,
            7,
            {
                "instrument_id": "rb2710",
                "error_id": 0,
                "success": True,
                "connection_generation": generation_new,
            },
            session=new,
            day=day,
            stream="ctp",
        ),
    ]
    control_disconnect = _event(
        module,
        "EXTERNAL_CONDITION",
        "external-disconnect",
        1,
        2,
        {
            "condition_id": "external_disconnect",
            "state": "satisfied",
            "evidence_ref": "controlled-fault-ref",
            "provider_event_ref": "old-disconnect",
            "session_id": old,
            "connection_generation": generation_old,
            "gateway_key": gateway,
            "snapshot_event_id": "disconnect-snapshot-1",
            "snapshot_sha256": "a" * 64,
        },
        stream="control",
    )
    control_reconnect = _event(
        module,
        "EXTERNAL_CONDITION",
        "external-reconnect",
        2,
        8,
        {
            "condition_id": "external_reconnect",
            "state": "satisfied",
            "evidence_ref": "controlled-recovery-ref",
            "disconnect_event_ref": "old-disconnect",
            "reconnect_event_ref": "new-front",
            "previous_session_id": old,
            "new_session_id": new,
            "previous_connection_generation": generation_old,
            "new_connection_generation": generation_new,
            "gateway_key": gateway,
            "snapshot_event_id": "reconnect-snapshot-1",
            "snapshot_sha256": "b" * 64,
        },
        stream="control",
    )
    disconnect_log = _event(
        module,
        "SYSTEM_LOG",
        "runtime-disconnected",
        1,
        3,
        {
            "trace_id": "trace-disconnect",
            "gateway_key": gateway,
            "log_digest": "c" * 64,
            "event_name": "store_disconnected",
            "session_id": old,
            "connection_generation": generation_old,
            "provider_event_id": "old-disconnect",
        },
        stream="runtime",
    )
    summary = _event(
        module,
        "SYSTEM_LOG",
        "runtime-reconnected",
        2,
        9,
        {
            "trace_id": "trace-reconnect",
            "gateway_key": gateway,
            "log_digest": "d" * 64,
            "event_name": "store_reconnect_success",
            "session_id": new,
            "connection_generation": generation_new,
            "callback_names": (
                "OnFrontConnected",
                "OnRspAuthenticate",
                "OnRspUserLogin",
                "OnRspSubMarketData",
            ),
            "provider_event_ids": tuple(item.event_id for item in callbacks[1:]),
            "auth_error_id": 0 if not bad_summary else 1,
            "login_error_id": 0,
            "subscription_error_id": 0,
            "authentication_succeeded": True,
            "login_succeeded": True,
            "subscription_succeeded": True,
            "external_event_id": "external-reconnect",
            "snapshot_event_id": "reconnect-snapshot-1",
            "snapshot_sha256": "b" * 64,
            "previous_session_id": old,
            "new_session_id": new,
            "previous_connection_generation": generation_old,
            "new_connection_generation": generation_new,
        },
        stream="runtime",
    )
    return [
        pre_disconnect_login,
        callbacks[0],
        disconnect_log,
        control_disconnect,
        *callbacks[1:],
        control_reconnect,
        summary,
    ]


@pytest.mark.parametrize("case_id", ["M02", "M03"])
def test_disconnect_cases_require_new_generation_callbacks_and_bound_recovery_summary(
    case_modules, case_id
):
    decision, case_engine, strategies = case_modules
    _, engine = _make_engine(decision, case_engine, strategies, case_id)
    for event in _recovery_events(decision):
        _record(engine, event)
    result = engine.evaluate(now_utc=NOW + timedelta(seconds=12))
    assert result.status is decision.DecisionStatus.REVIEW_REQUIRED
    assert result.certification_pass is False
    assert result.dispatch_permitted is False
    assert result.intent_candidate is not None
    assert result.intent_candidate.dispatch_permitted is False


@pytest.mark.parametrize("case_id", ["M02", "M03"])
def test_disconnect_recovery_without_pre_disconnect_native_login_stays_incomplete(
    case_modules, case_id
):
    decision, case_engine, strategies = case_modules
    _, engine = _make_engine(decision, case_engine, strategies, case_id)
    for event in _recovery_events(decision)[1:]:
        _record(engine, event)

    result = engine.evaluate(now_utc=NOW + timedelta(seconds=12))
    assert result.status is decision.DecisionStatus.INCOMPLETE
    assert "one_pre_disconnect_native_login_binding_required" in result.missing_conditions
    assert result.intent_candidate is None
    assert result.certification_pass is False
    assert result.dispatch_permitted is False


@pytest.mark.parametrize("case_id", ["M02", "M03"])
def test_disconnect_recovery_rejects_same_generation_provider_identity_change(
    case_modules, case_id
):
    decision, case_engine, strategies = case_modules
    plan, engine = _make_engine(decision, case_engine, strategies, case_id)
    old_login = _event(
        decision,
        "LOGIN_SUCCESS",
        "old-login",
        1,
        0,
        {"error_id": 0, "success": True, "connection_generation": 8},
        session="79",
        day="20260928",
        front_id=7,
        stream="ctp",
    )
    changed_login = _event(
        decision,
        "LOGIN_SUCCESS",
        "same-generation-changed-login",
        2,
        1,
        {"error_id": 0, "success": True, "connection_generation": 8},
        session="80",
        day="20260928",
        front_id=7,
        stream="ctp",
    )
    _record(engine, old_login)
    with pytest.raises(decision.DecisionError, match="same-generation login"):
        engine.record(changed_login)

    result = engine.evaluate(now_utc=NOW + timedelta(seconds=12))
    assert result.status is decision.DecisionStatus.INCOMPLETE
    assert result.intent_candidate is None
    assert result.certification_pass is False
    assert result.dispatch_permitted is False
    assert result.rejected_observations


@pytest.mark.parametrize("case_id", ["M02", "M03"])
def test_disconnect_recovery_rejects_cross_account_new_login_receipt(case_modules, case_id):
    decision, case_engine, strategies = case_modules
    plan, baseline = _make_engine(decision, case_engine, strategies, case_id)

    class CrossAccountOnReconnect(SyntheticAuthenticator):
        def authenticate(self, event, scope):
            receipt = super().authenticate(event, scope)
            if event.event_id == "new-login":
                return replace(receipt, account_identity_sha256="a" * 64)
            return receipt

    engine = strategies[case_id].create_strategy(
        plan, baseline.scope, CrossAccountOnReconnect(decision)
    )
    events = _recovery_events(decision)
    for event in events:
        if event.event_id == "new-login":
            assert engine.record(event) is False
            break
        _record(engine, event)

    result = engine.evaluate(now_utc=NOW + timedelta(seconds=12))
    assert result.status is decision.DecisionStatus.INCOMPLETE
    assert result.intent_candidate is None
    assert result.certification_pass is False
    assert result.dispatch_permitted is False
    assert any("verification_receipt_mismatch" in row for row in result.rejected_observations)


@pytest.mark.parametrize("case_id", ["M02", "M03"])
@pytest.mark.parametrize("kind", ["FRONT_CONNECTED", "FRONT_DISCONNECTED"])
def test_payloadless_front_callback_cannot_claim_provider_session(case_modules, case_id, kind):
    decision, case_engine, strategies = case_modules
    _, engine = _make_engine(decision, case_engine, strategies, case_id)
    front = _event(
        decision,
        kind,
        f"{kind.lower()}-with-invented-session",
        1,
        0,
        {"gateway_key": "gateway-a", "connection_generation": 1},
        stream="ctp",
    )
    forged = replace(front, provider_session_id="79", trading_day="20260928")

    with pytest.raises(decision.DecisionError, match="cannot claim provider FrontID"):
        engine.record(forged)
    result = engine.evaluate(now_utc=NOW + timedelta(seconds=2))
    assert result.status is decision.DecisionStatus.BLOCKED
    assert result.intent_candidate is None
    assert result.certification_pass is False
    assert result.dispatch_permitted is False


@pytest.mark.parametrize("case_id", ["M02", "M03"])
@pytest.mark.parametrize("kind", ["FRONT_DISCONNECTED", "AUTH_SUCCESS"])
@pytest.mark.parametrize(
    "alias",
    ["local_session_id", "local_front_id", "local_provider_session_id", "local_trading_day"],
)
def test_disconnect_recovery_rejects_local_login_identity_aliases(
    case_modules, case_id, kind, alias
):
    decision, case_engine, strategies = case_modules
    _, engine = _make_engine(decision, case_engine, strategies, case_id)
    events = _recovery_events(decision)
    target_index = next(
        index for index, event in enumerate(events) if event.kind.name == kind
    )

    for event in events[:target_index]:
        _record(engine, event)
    target = events[target_index]
    forged = replace(target, fields={**target.fields, alias: "forged-provider-identity"})
    with pytest.raises(decision.DecisionError, match="cannot carry login identity alias"):
        engine.record(forged)

    result = engine.evaluate(now_utc=NOW + timedelta(seconds=12))
    assert result.status is decision.DecisionStatus.INCOMPLETE
    assert result.intent_candidate is None
    assert result.certification_pass is False
    assert result.dispatch_permitted is False


@pytest.mark.parametrize("case_id", ["M02", "M03"])
def test_disconnect_cases_reject_failed_recovery_summary_and_failed_native_login(
    case_modules, case_id
):
    decision, case_engine, strategies = case_modules
    _, engine = _make_engine(decision, case_engine, strategies, case_id)
    for event in _recovery_events(decision, bad_summary=True)[:-1]:
        _record(engine, event)
    with pytest.raises(decision.DecisionError, match="three zero provider error ids"):
        engine.record(_recovery_events(decision, bad_summary=True)[-1])
    result = engine.evaluate(now_utc=NOW + timedelta(seconds=12))
    assert result.status is decision.DecisionStatus.INCOMPLETE
    assert result.intent_candidate is None

    _, failed_engine = _make_engine(decision, case_engine, strategies, case_id)
    failed_login = _event(
        decision,
        "LOGIN_SUCCESS",
        "failed-login",
        1,
        1,
        {"error_id": 9, "success": False, "connection_generation": 9},
        session="80",
        day="20260928",
        front_id=7,
        stream="failed-provider",
    )
    with pytest.raises(decision.DecisionError):
        failed_engine.record(failed_login)
    assert (
        failed_engine.evaluate(now_utc=NOW + timedelta(seconds=2)).status
        is decision.DecisionStatus.BLOCKED
    )


def _ready_provider_events(module, *, include_tick, order_start):
    session, day = "42", "20260928"
    events = [
        _event(
            module,
            "AUTH_SUCCESS",
            "auth",
            1,
            1,
            {"error_id": 0, "success": True},
            session=session,
            day=day,
            stream="ctp",
        ),
        _event(
            module,
            "FRONT_CONNECTED",
            "front",
            2,
            2,
            {"gateway_key": "gateway-a"},
            session=session,
            day=day,
            stream="ctp",
        ),
        _event(
            module,
            "LOGIN_SUCCESS",
            "login",
            3,
            3,
            {"error_id": 0, "success": True},
            session=session,
            day=day,
            front_id=7,
            stream="ctp",
        ),
        _event(
            module,
            "MARKET_SUBSCRIPTION_ACK",
            "sub",
            4,
            4,
            {"instrument_id": "rb2710", "error_id": 0, "success": True},
            session=session,
            day=day,
            stream="ctp",
        ),
    ]
    sequence = 5
    if include_tick:
        events.append(
            _event(
                module,
                "MARKET_TICK",
                "tick",
                sequence,
                5,
                {
                    "instrument_id": "rb2710",
                    "bid": "100",
                    "ask": "101",
                    "last": "100.5",
                    "price_tick": "1",
                },
                session=session,
                day=day,
                stream="ctp",
            )
        )
        sequence += 1
    return events, sequence


def _admission(module, case_id, intent):
    return _event(
        module,
        "ORDER_ADMISSION",
        f"admission-{case_id}",
        1,
        5,
        {
            "case_id": case_id,
            "intent_kind": intent,
            "approval_ref": f"review-only-{case_id}",
            "maximum_quantity": 1,
            "approval_state": "REVIEW_ONLY",
            "dispatch_permitted": False,
        },
        stream=f"admission-{case_id}",
    )


def _submit_receipt(module, *, event_id="submit-receipt", order_ref="order-1"):
    return _event(
        module,
        "ORDER_SUBMIT_RECEIPT",
        event_id,
        1,
        5,
        {
            "order_ref": order_ref,
            "request_id": "submit-request-1",
            "trace_id": "trace-submit-1",
            "dispatch_state": "submitted",
        },
        stream="submit-runtime",
    )


def _order_callback(module, kind, event_id, sequence, seconds, *, order_ref="order-1", extra=None):
    fields = {
        "order_ref": order_ref,
        "external_order_id": "external-order-1",
        "instrument_id": "rb2710",
        "status": "accepted" if kind == "ORDER_ACCEPTED" else "canceled",
        "remaining_quantity": "1" if kind == "ORDER_ACCEPTED" else "0",
        "traded_quantity": "0",
    }
    if extra:
        fields.update(extra)
    return _event(
        module,
        kind,
        event_id,
        sequence,
        seconds,
        fields,
        session="42",
        day="20260928",
        stream="ctp",
    )


def test_m04_count_receipt_is_bound_to_runtime_request_native_ack_and_cleanup(case_modules):
    decision, case_engine, strategies = case_modules
    _, engine = _make_engine(decision, case_engine, strategies, "M04")
    ready, sequence = _ready_provider_events(decision, include_tick=True, order_start=1)
    for event in ready:
        _record(engine, event)
    _record(engine, _admission(decision, "M04", "open"))
    _record(engine, _submit_receipt(decision))
    _record(
        engine,
        _event(
            decision,
            "MONITOR_LOG",
            "submit-monitor",
            1,
            6,
            {
                "event_name": "order_submit_request",
                "metric": "submit_count",
                "count": 1,
                "request_id": "submit-request-1",
                "order_ref": "order-1",
                "trace_id": "trace-submit-1",
                "request_receipt_event_id": "submit-receipt",
                "monitor_digest": "a" * 64,
            },
            stream="monitor",
        ),
    )
    _record(engine, _order_callback(decision, "ORDER_ACCEPTED", "accepted", sequence, 7))
    _record(engine, _order_callback(decision, "ORDER_CANCELED", "canceled", sequence + 1, 8))
    _record(
        engine,
        _event(
            decision,
            "ORDER_QUERY",
            "final-order-query",
            sequence + 2,
            9,
            {"query_id": "query-final", "complete": True, "open_order_refs": ()},
            session="42",
            day="20260928",
            stream="ctp",
        ),
    )
    _record(
        engine,
        _event(
            decision,
            "POSITION_QUERY",
            "final-position-query",
            sequence + 3,
            10,
            {
                "query_id": "position-final",
                "complete": True,
                "phase": "final",
                "instrument_id": "rb2710",
                "closeable_quantity": 0,
            },
            session="42",
            day="20260928",
            stream="ctp",
        ),
    )
    result = engine.evaluate(now_utc=NOW + timedelta(seconds=6))
    assert result.status is decision.DecisionStatus.REVIEW_REQUIRED
    assert result.certification_pass is False and result.dispatch_permitted is False


def test_m04_mismatched_monitor_count_cannot_produce_candidate(case_modules):
    decision, case_engine, strategies = case_modules
    _, engine = _make_engine(decision, case_engine, strategies, "M04")
    ready, sequence = _ready_provider_events(decision, include_tick=True, order_start=1)
    for event in ready:
        _record(engine, event)
    _record(engine, _admission(decision, "M04", "open"))
    _record(engine, _submit_receipt(decision))
    _record(
        engine,
        _event(
            decision,
            "MONITOR_LOG",
            "bad-monitor",
            1,
            6,
            {
                "event_name": "order_submit_request",
                "metric": "submit_count",
                "count": 2,
                "request_id": "submit-request-1",
                "order_ref": "order-1",
                "trace_id": "trace-submit-1",
                "request_receipt_event_id": "submit-receipt",
                "monitor_digest": "a" * 64,
            },
            stream="monitor",
        ),
    )
    _record(engine, _order_callback(decision, "ORDER_ACCEPTED", "accepted", sequence, 7))
    _record(engine, _order_callback(decision, "ORDER_CANCELED", "canceled", sequence + 1, 8))
    _record(
        engine,
        _event(
            decision,
            "ORDER_QUERY",
            "orders-final",
            sequence + 2,
            9,
            {"query_id": "q", "complete": True, "open_order_refs": ()},
            session="42",
            day="20260928",
            stream="ctp",
        ),
    )
    _record(
        engine,
        _event(
            decision,
            "POSITION_QUERY",
            "positions-final",
            sequence + 3,
            10,
            {
                "query_id": "p",
                "complete": True,
                "phase": "final",
                "instrument_id": "rb2710",
                "closeable_quantity": 0,
            },
            session="42",
            day="20260928",
            stream="ctp",
        ),
    )
    result = engine.evaluate(now_utc=NOW + timedelta(seconds=6))
    assert result.status is decision.DecisionStatus.INCOMPLETE
    assert result.intent_candidate is None


def test_m05_cancel_monitor_receipt_is_tied_to_open_ref_ack_and_empty_final_query(case_modules):
    decision, case_engine, strategies = case_modules
    _, engine = _make_engine(decision, case_engine, strategies, "M05")
    ready, sequence = _ready_provider_events(decision, include_tick=False, order_start=1)
    for event in ready:
        _record(engine, event)
    _record(engine, _admission(decision, "M05", "cancel"))
    _record(engine, _submit_receipt(decision, event_id="origin-submit"))
    _record(engine, _order_callback(decision, "ORDER_ACCEPTED", "accepted", sequence, 5))
    baseline = _event(
        decision,
        "ORDER_QUERY",
        "baseline-query",
        sequence + 1,
        6,
        {"query_id": "query-before-cancel", "complete": True, "open_order_refs": ("order-1",)},
        session="42",
        day="20260928",
        stream="ctp",
    )
    _record(engine, baseline)
    _record(
        engine,
        _event(
            decision,
            "MONITOR_LOG",
            "cancel-monitor",
            1,
            7,
            {
                "event_name": "order_cancel_request",
                "metric": "cancel_count",
                "count": 1,
                "request_id": "cancel-request-1",
                "order_ref": "order-1",
                "trace_id": "trace-cancel-1",
                "origin_trace_id": "trace-submit-1",
                "request_receipt_ref": "cancel-request-receipt-1",
                "source_query_event_id": "baseline-query",
                "monitor_digest": "e" * 64,
            },
            stream="monitor",
        ),
    )
    _record(
        engine,
        _order_callback(
            decision,
            "ORDER_CANCELED",
            "canceled",
            sequence + 2,
            8,
            extra={"cancel_request_id": "cancel-request-1"},
        ),
    )
    _record(
        engine,
        _event(
            decision,
            "ORDER_QUERY",
            "final-query",
            sequence + 3,
            9,
            {"query_id": "query-final", "complete": True, "open_order_refs": ()},
            session="42",
            day="20260928",
            stream="ctp",
        ),
    )
    _record(
        engine,
        _event(
            decision,
            "POSITION_QUERY",
            "final-position",
            sequence + 4,
            10,
            {
                "query_id": "position-final",
                "complete": True,
                "phase": "final",
                "instrument_id": "rb2710",
                "closeable_quantity": 0,
            },
            session="42",
            day="20260928",
            stream="ctp",
        ),
    )
    result = engine.evaluate(now_utc=NOW + timedelta(seconds=11))
    assert result.status is decision.DecisionStatus.REVIEW_REQUIRED
    assert result.certification_pass is False and result.dispatch_permitted is False


def test_l03_monitor_event_binds_request_receipt_provider_ack_and_runtime_log(case_modules):
    decision, case_engine, strategies = case_modules
    _, engine = _make_engine(decision, case_engine, strategies, "L03")
    ready, sequence = _ready_provider_events(decision, include_tick=False, order_start=1)
    for event in ready:
        _record(engine, event)
    _record(engine, _admission(decision, "L03", "open"))
    _record(engine, _submit_receipt(decision))
    accepted = _order_callback(decision, "ORDER_ACCEPTED", "accepted", sequence, 6)
    accepted = replace(
        accepted,
        fields={**accepted.fields, "gateway_key": "gateway-a", "connection_generation": 9},
    )
    _record(engine, accepted)
    monitor = _event(
        decision,
        "MONITOR_LOG",
        "monitor-event",
        1,
        7,
        {
            "event_name": "order_submit_request",
            "metric": "submit_count",
            "count": 1,
            "request_id": "submit-request-1",
            "order_ref": "order-1",
            "trace_id": "trace-submit-1",
            "request_receipt_event_id": "submit-receipt",
            "monitor_digest": "a" * 64,
            "session_id": "42",
            "gateway_key": "gateway-a",
            "trading_day": "20260928",
            "connection_generation": 9,
        },
        stream="monitor",
    )
    _record(engine, monitor)
    _record(
        engine,
        _event(
            decision,
            "SYSTEM_LOG",
            "runtime-monitor-log",
            1,
            8,
            {
                "event_name": "monitor_observation",
                "trace_id": "trace-submit-1",
                "gateway_key": "gateway-a",
                "log_digest": "d" * 64,
                "monitor_event_id": "monitor-event",
                "request_id": "submit-request-1",
                "order_ref": "order-1",
                "session_id": "42",
                "trading_day": "20260928",
                "connection_generation": 9,
            },
            stream="runtime",
        ),
    )
    result = engine.evaluate(now_utc=NOW + timedelta(seconds=9))
    assert result.status is decision.DecisionStatus.REVIEW_REQUIRED
    assert result.certification_pass is False and result.dispatch_permitted is False
