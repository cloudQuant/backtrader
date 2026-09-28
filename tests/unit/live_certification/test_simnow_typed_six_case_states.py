"""Offline contracts for the unregistered six-case typed-state candidates."""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITE_ROOT = REPO_ROOT / "examples" / "007_ctp" / "live_certification" / "simnow_penetration"
CASES_ROOT = SUITE_ROOT / "cases"
NOW = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)
CONFIG_DIGEST = "a" * 64
MONITOR_DIGEST = "b" * 64
ACCOUNT_IDENTITY_SHA256 = "c" * 64

_STRATEGY_CLASS = {
    "O01": "O01TypedScenarioState",
    "O02": "O02TypedScenarioState",
    "O03": "O03TypedScenarioState",
    "TH02": "TH02TypedScenarioState",
    "TH04": "TH04TypedScenarioState",
    "TH06": "TH06TypedScenarioState",
}


@dataclass(frozen=True)
class ManagedProof:
    request_id: str
    evidence_sha256: str
    scope_sha256: str
    source: str
    verification_ref: str
    account_identity_sha256: str


class SyntheticAuthenticator:
    """Interface-only fake. This does not authenticate real evidence."""

    def __init__(self, module):
        self.module = module

    def authenticate(self, event, scope):
        return self.module.AuthenticationReceipt(
            event_id=event.event_id,
            evidence_sha256=event.evidence_sha256,
            scope_sha256=scope.scope_sha256,
            trust_domain=event.source_domain,
            verification_ref="test-only-synthetic-verifier",
            account_identity_sha256=scope.account_identity_sha256,
        )

    def authenticate_managed_receipt(self, receipt, scope):
        return ManagedProof(
            request_id=receipt.request_id,
            evidence_sha256=receipt.evidence_sha256,
            scope_sha256=scope.scope_sha256,
            source=receipt.source,
            verification_ref="test-only-synthetic-managed-verifier",
            account_identity_sha256=scope.account_identity_sha256,
        )


@pytest.fixture
def loaded_case_modules():
    names = {
        name: module
        for name, module in sys.modules.items()
        if name == "common"
        or name.startswith("common.")
        or name == "_typed_scenario_state_candidate"
    }
    old_path = sys.path[:]
    old_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    for name in names:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(CASES_ROOT))
    sys.path.insert(0, str(SUITE_ROOT))
    try:
        decision = importlib.import_module("common.decision_engine")
        case_engine = importlib.import_module("common.case_engine")
        strategies = {}
        for case_id in _STRATEGY_CLASS:
            path = CASES_ROOT / case_id / f"{case_id}_strategy.py"
            spec = importlib.util.spec_from_file_location(f"candidate_{case_id}", path)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            strategies[case_id] = module
        yield decision, case_engine, strategies
    finally:
        for name in list(sys.modules):
            if (
                name == "common"
                or name.startswith("common.")
                or name == "_typed_scenario_state_candidate"
            ):
                sys.modules.pop(name, None)
        sys.modules.update(names)
        sys.path[:] = old_path
        sys.dont_write_bytecode = old_dont_write_bytecode


def _context(
    decision, case_engine, strategies, case_id, *, account_identity_sha256=ACCOUNT_IDENTITY_SHA256
):
    plan_path = CASES_ROOT / case_id / f"{case_id}_strategy.py"
    plan = case_engine.load_descriptive_case_plan(plan_path, expected_case_id=case_id)
    scope = decision.DecisionScope.for_plan(plan, "f" * 64, account_identity_sha256)
    auth = SyntheticAuthenticator(decision)
    engine = decision.CaseIntentDecisionEngine(plan, scope, auth)
    strategy = strategies[case_id]
    state_class = getattr(strategy, _STRATEGY_CLASS[case_id])
    return state_class(engine, auth), auth, scope


def _make_event(decision, kind_name, sequence, fields, *, stream=None, when=None):
    kind = decision.ObservationKind[kind_name]
    domain, callback, _ = decision._POLICY[kind]
    provider = domain is decision.EvidenceTrustDomain.CTP_CALLBACK
    fields = dict(fields)
    arrived_at = when or NOW - timedelta(seconds=4)
    arrived_at_utc = arrived_at.isoformat().replace("+00:00", "Z")
    is_auth = kind is decision.ObservationKind.AUTH_SUCCESS
    is_login = kind is decision.ObservationKind.LOGIN_SUCCESS
    is_payloadless_front = kind in {
        decision.ObservationKind.FRONT_CONNECTED,
        decision.ObservationKind.FRONT_DISCONNECTED,
    }
    if provider and (is_auth or is_payloadless_front) and "account_identity_sha256" in fields:
        fields["local_account_identity_sha256"] = fields.pop("account_identity_sha256")

    # Front connectivity carries no native FrontID/SessionID/TradingDay. Those
    # identity values belong to the later OnRspUserLogin response fixture.
    if provider and (is_auth or is_login):
        fields.setdefault("request_id", 1 if is_auth else 2)
        fields.setdefault("request_generation", 1)
        fields.setdefault("arrival_generation", 1)
        fields.setdefault("is_last", True)
        fields.setdefault("success", True)
        fields.setdefault("error_id", 0)
    if is_login:
        fields.setdefault("provider_front_id", 7)
        fields.setdefault("provider_session_id", "10007")
        fields.setdefault("trading_day", "20260928")

    provider_session_id = "10007" if provider and not (is_auth or is_payloadless_front) else ""
    trading_day = "20260928" if provider and not (is_auth or is_payloadless_front) else ""
    provider_front_id = fields.get("provider_front_id") if is_login else None
    callback_metadata = {}
    if provider:
        callback_metadata.update(
            client_instance_id="test-native-client",
            arrival_generation=1,
            sequence_origin="local_sdk_callback_arrival",
            timestamp_origin="local_sdk_capture_clock",
            event_id_origin="local_sdk_callback_arrival",
            provider_issued_event_id=False,
            arrived_at_utc=arrived_at_utc,
            arrived_monotonic=float(sequence),
            connection_generation_origin="local_connection_generation",
        )
        if is_auth or is_login:
            callback_metadata.update(
                request_generation=1,
                request_id_origin="native_callback_argument",
                request_generation_origin="local_request_generation_binding",
                session_identity_origin=(
                    "unavailable_on_native_authentication_response"
                    if is_auth
                    else "native_login_response_fields"
                ),
            )
    return decision.NativeObservation(
        kind=kind,
        source_domain=domain,
        event_id=f"{kind_name.lower()}-{sequence}",
        evidence_sha256=f"{sequence:064x}",
        occurred_at_utc=arrived_at_utc,
        sequence=sequence,
        stream_id=stream or ("provider" if provider else domain.value),
        callback_name=callback,
        provider_session_id=provider_session_id,
        trading_day=trading_day,
        provider_front_id=provider_front_id,
        fields=fields,
        **callback_metadata,
    )


def _record(state, event, *, supporting=False, configuration=False):
    if configuration:
        assert state.record_monitor_configuration(event)
    elif supporting:
        assert state.record_supporting_observation(event)
    else:
        assert state.record(event), state._rejected


def _record_provider_login_binding(decision, state):
    """Seed provider session scope from its native login callback."""
    if state.CASE_ID == "O01":
        for kind, sequence, fields, offset in (
            ("FRONT_CONNECTED", 1, {"gateway_key": "g1"}, 12),
            ("AUTH_SUCCESS", 2, {"error_id": 0, "success": True}, 11),
        ):
            event = _make_event(
                decision,
                kind,
                sequence,
                {
                    **fields,
                    "account_identity_sha256": ACCOUNT_IDENTITY_SHA256,
                    "connection_generation": 1,
                },
                when=NOW - timedelta(seconds=offset),
            )
            _record(state, event)
    event = _make_event(
        decision,
        "LOGIN_SUCCESS",
        3 if state.CASE_ID == "O01" else 1,
        {
            "account_identity_sha256": ACCOUNT_IDENTITY_SHA256,
            "connection_generation": 1,
            "error_id": 0,
            "success": True,
            "provider_front_id": 7,
            "provider_session_id": "10007",
            "trading_day": "20260928",
        },
        when=NOW - timedelta(seconds=10),
    )
    _record(state, event)


def _base_native(decision, state, case_id, *, mutation=None):
    provider_seq = 0
    monitor_seq = 0
    managed_seq = 0

    def add(kind, fields, *, when=None, stream=None, supporting=False, configuration=False):
        nonlocal provider_seq, monitor_seq, managed_seq
        enum_kind = decision.ObservationKind[kind]
        domain = decision._POLICY[enum_kind][0]
        if domain is decision.EvidenceTrustDomain.CTP_CALLBACK:
            provider_seq += 1
            sequence = provider_seq
        elif domain is decision.EvidenceTrustDomain.MONITOR:
            monitor_seq += 1
            sequence = monitor_seq
        else:
            managed_seq += 1
            sequence = managed_seq
        fields = dict(fields)
        if domain is decision.EvidenceTrustDomain.CTP_CALLBACK:
            # This is local case-scope binding metadata, not a CTP callback field.
            fields.setdefault("account_identity_sha256", ACCOUNT_IDENTITY_SHA256)
            fields.setdefault("connection_generation", 1)
            if mutation == "generation_mismatch" and kind == "ORDER_ACCEPTED":
                fields["connection_generation"] = 2
            if mutation == "native_instrument_mismatch" and kind == "ORDER_ACCEPTED":
                fields["instrument_id"] = "cu2710"
            if mutation == "stale_native_event" and kind == "ORDER_ACCEPTED":
                when = NOW - timedelta(days=3650)
        event = _make_event(
            decision,
            kind,
            sequence,
            fields,
            stream=stream,
            when=when or NOW - timedelta(seconds=3),
        )
        _record(state, event, supporting=supporting, configuration=configuration)
        return event

    def add_session_and_tick():
        front = add(
            "FRONT_CONNECTED", {"gateway_key": "g1"}, when=NOW - timedelta(seconds=12)
        )
        assert front.provider_front_id is None
        assert front.provider_session_id == ""
        assert front.trading_day == ""
        assert not any(
            front.fields.get(name) not in (None, "")
            for name in ("provider_front_id", "provider_session_id", "trading_day")
        )
        add("AUTH_SUCCESS", {"error_id": 0, "success": True}, when=NOW - timedelta(seconds=11))
        add(
            "LOGIN_SUCCESS",
            {
                "error_id": 0,
                "success": True,
                "provider_front_id": 7,
                "provider_session_id": "10007",
                "trading_day": "20260928",
            },
            when=NOW - timedelta(seconds=10),
        )
        add(
            "MARKET_SUBSCRIPTION_ACK",
            {"instrument_id": "rb2710", "error_id": 0, "success": True},
            when=NOW - timedelta(seconds=8),
        )
        add(
            "MARKET_TICK",
            {
                "instrument_id": "rb2710",
                "bid": "100",
                "ask": "101",
                "last": "100.5",
                "price_tick": "1",
            },
            when=NOW - timedelta(seconds=1.5),
        )

    if case_id in {"TH04", "TH06"}:
        # These specs admit login only as a read-only identity prerequisite;
        # front/auth callbacks do not substitute for native login identity.
        add(
            "LOGIN_SUCCESS",
            {
                "error_id": 0,
                "success": True,
                "provider_front_id": 7,
                "provider_session_id": "10007",
                "trading_day": "20260928",
            },
            when=NOW - timedelta(seconds=12),
        )

    if case_id in {"O01", "O02", "TH02"}:
        add_session_and_tick()
    if case_id == "O02":
        add(
            "POSITION_QUERY",
            {
                "query_id": "q-pos",
                "complete": True,
                "instrument_id": "rb2710",
                "phase": "baseline",
                "closeable_quantity": "1",
            },
            when=NOW - timedelta(seconds=1.8),
        )
    if case_id in {"O01", "O02", "TH06"}:
        accepted_fields = {
            "order_ref": "ref-1",
            "external_order_id": "sys-1",
            "instrument_id": "rb2710",
            "status": "working",
            "remaining_quantity": "1",
            "traded_quantity": "0",
        }
        add(
            "ORDER_ACCEPTED",
            accepted_fields,
            when=NOW - timedelta(seconds=1),
            supporting=True,
        )
    if case_id == "O03":
        add(
            "ORDER_ACCEPTED",
            {
                "order_ref": "ref-1",
                "external_order_id": "sys-1",
                "instrument_id": "rb2710",
                "status": "working",
                "remaining_quantity": "1",
                "traded_quantity": "0",
            },
            when=NOW - timedelta(seconds=3),
        )
        add(
            "ORDER_QUERY",
            {"query_id": "q-order", "complete": True, "open_order_refs": ("ref-1",)},
            when=NOW - timedelta(seconds=2.5),
        )
    if case_id == "TH02":
        add(
            "ORDER_ACCEPTED",
            {
                "order_ref": "ref-1",
                "external_order_id": "sys-1",
                "instrument_id": "rb2710",
                "status": "working",
                "remaining_quantity": "1",
                "traded_quantity": "0",
            },
            when=NOW - timedelta(seconds=1),
        )
        add(
            "ORDER_ACCEPTED",
            {
                "order_ref": "ref-2",
                "external_order_id": "sys-2",
                "instrument_id": "rb2710",
                "status": "working",
                "remaining_quantity": "1",
                "traded_quantity": "0",
            },
            when=NOW - timedelta(seconds=0.3),
        )
    if case_id == "TH04":
        add(
            "ORDER_ACCEPTED",
            {
                "order_ref": "ref-1",
                "external_order_id": "sys-1",
                "instrument_id": "rb2710",
                "status": "working",
                "remaining_quantity": "1",
                "traded_quantity": "0",
            },
            when=NOW - timedelta(seconds=7),
            supporting=True,
        )
        add(
            "ORDER_ACCEPTED",
            {
                "order_ref": "ref-2",
                "external_order_id": "sys-2",
                "instrument_id": "rb2710",
                "status": "working",
                "remaining_quantity": "1",
                "traded_quantity": "0",
            },
            when=NOW - timedelta(seconds=5.5),
            supporting=True,
        )
        add(
            "ORDER_CANCELED",
            {
                "order_ref": "ref-1",
                "external_order_id": "sys-1",
                "instrument_id": "rb2710",
                "status": "canceled",
                "remaining_quantity": "0",
                "traded_quantity": "0",
            },
            when=NOW - timedelta(seconds=3),
        )
    return add


def _receipt(
    state,
    receipt_type,
    *,
    request_id,
    intent_id,
    action,
    dispatch_state,
    order_ref,
    sequence,
    mutation=None,
):
    if state.CASE_ID == "TH04":
        occurred_at = NOW - timedelta(seconds=10 - sequence * 2)
    else:
        occurred_at = NOW - timedelta(seconds=1.4 if sequence == 1 else 0.6)
    row = receipt_type(
        request_id=request_id,
        intent_id=intent_id,
        action=action,
        dispatch_state=dispatch_state,
        order_ref=order_ref,
        instrument_id="cu2710" if mutation == "receipt_instrument_mismatch" else "rb2710",
        repeat_key=f"repeat-{intent_id}-{order_ref}",
        account_identity_sha256=(
            "d" * 64 if mutation == "receipt_account_mismatch" else ACCOUNT_IDENTITY_SHA256
        ),
        configuration_digest=CONFIG_DIGEST,
        threshold=3
        if action == "cancel" and request_id.startswith("th04")
        else (3 if state.CASE_ID == "TH04" else 2),
        window_seconds=10.0,
        occurred_at_utc=occurred_at.isoformat().replace("+00:00", "Z"),
        sequence=sequence,
        evidence_sha256=f"{sequence + 100:064x}",
    )
    assert state.record_managed_receipt(row)
    return row


def _complete_case(decision, case_engine, strategies, case_id, *, mutation=None):
    state, _, _ = _context(decision, case_engine, strategies, case_id)
    add = _base_native(decision, state, case_id, mutation=mutation)
    receipt_type = importlib.import_module("_typed_scenario_state_candidate").ManagedIntentReceipt
    metric = {
        "O01": "repeat_order_count",
        "O02": "repeat_order_count",
        "O03": "repeat_cancel_count",
        "TH02": "submitted_order_count",
        "TH04": "combined_order_cancel_count",
        "TH06": "repeat_order_count",
    }[case_id]
    threshold = 3 if case_id == "TH04" else 2
    add(
        "MONITOR_CONFIGURATION",
        {
            "metric": metric,
            "threshold": threshold,
            "window_seconds": 10.0,
            "configuration_digest": CONFIG_DIGEST,
            "monitor_digest": MONITOR_DIGEST,
        },
        configuration=True,
        when=NOW - timedelta(seconds=15),
    )

    if case_id in {"O01", "O02", "O03", "TH06"}:
        action = {"O01": "open", "O02": "close", "O03": "cancel", "TH06": "open"}[case_id]
        if case_id in {"O01", "O02", "O03"}:
            add(
                "ORDER_ADMISSION",
                {
                    "case_id": case_id,
                    "intent_kind": action,
                    "intent_id": "intent-1",
                    "approval_ref": "approval-test",
                    "approval_state": "REVIEW_ONLY",
                    "maximum_quantity": "1",
                    "dispatch_permitted": False,
                },
                when=NOW - timedelta(seconds=1.8),
            )
        ref = "ref-1"
        _receipt(
            state,
            receipt_type,
            request_id=f"{case_id.lower()}-req-1",
            intent_id="intent-1",
            action=action,
            dispatch_state="dispatched",
            order_ref=ref,
            sequence=1,
            mutation=mutation,
        )
        second_ref = "other-ref" if mutation == "receipt_ref" else ref
        _receipt(
            state,
            receipt_type,
            request_id=f"{case_id.lower()}-req-2",
            intent_id="intent-1",
            action=action,
            dispatch_state="blocked_pre_dispatch",
            order_ref=second_ref,
            sequence=2,
            mutation=mutation,
        )
        repeat_key = (
            "unrelated-intent-key" if mutation == "repeat_key" else f"repeat-intent-1-{ref}"
        )
        source_request_ids = (
            ("unrelated-request",)
            if mutation == "repeat_source"
            else (f"{case_id.lower()}-req-1", f"{case_id.lower()}-req-2")
        )
        repeat_window = 11.0 if mutation == "repeat_window" else 10.0
        add(
            "REPEAT_GUARD",
            {
                "action_kind": action,
                "intent_id": "intent-1",
                "repeat_key": repeat_key,
                "repeat_count": 2,
                "order_refs": (ref,),
                "source_request_ids": source_request_ids,
                "threshold": threshold,
                "window_seconds": repeat_window,
                "configuration_digest": CONFIG_DIGEST,
                "monitor_digest": MONITOR_DIGEST,
            },
            when=NOW - timedelta(seconds=0.4),
        )
        if case_id == "TH06":
            add(
                "MONITOR_TRIGGER",
                {
                    "metric": metric,
                    "threshold": threshold,
                    "observed_value": 2,
                    "configuration_digest": "c" * 64
                    if mutation == "config_digest"
                    else CONFIG_DIGEST,
                    "monitor_digest": MONITOR_DIGEST,
                    "source_request_ids": ("th06-req-1", "th06-req-2"),
                "source_event_ids": ("order_accepted-2",),
                },
                when=NOW - timedelta(seconds=0.2),
            )
    elif case_id == "TH02":
        _receipt(
            state,
            receipt_type,
            request_id="th02-req-1",
            intent_id="intent-1",
            action="open",
            dispatch_state="dispatched",
            order_ref="ref-1",
            sequence=1,
            mutation=mutation,
        )
        _receipt(
            state,
            receipt_type,
            request_id="th02-req-2",
            intent_id="intent-2",
            action="open",
            dispatch_state="dispatched",
            order_ref="ref-2",
            sequence=2,
            mutation=mutation,
        )
        add(
            "MONITOR_TRIGGER",
            {
                "metric": metric,
                "threshold": threshold,
                "observed_value": 2,
                "configuration_digest": "c" * 64 if mutation == "config_digest" else CONFIG_DIGEST,
                "monitor_digest": MONITOR_DIGEST,
                "source_request_ids": ("th02-req-1", "th02-req-2"),
                "source_event_ids": ("order_accepted-6", "order_accepted-7"),
            },
            when=NOW - timedelta(seconds=0.1),
        )
    elif case_id == "TH04":
        _receipt(
            state,
            receipt_type,
            request_id="th04-req-1",
            intent_id="intent-1",
            action="open",
            dispatch_state="dispatched",
            order_ref="ref-1",
            sequence=1,
            mutation=mutation,
        )
        _receipt(
            state,
            receipt_type,
            request_id="th04-req-2",
            intent_id="intent-2",
            action="open",
            dispatch_state="dispatched",
            order_ref="ref-2",
            sequence=2,
            mutation=mutation,
        )
        _receipt(
            state,
            receipt_type,
            request_id="th04-req-3",
            intent_id="intent-3",
            action="cancel",
            dispatch_state="dispatched",
            order_ref="ref-1",
            sequence=3,
            mutation=mutation,
        )
        _receipt(
            state,
            receipt_type,
            request_id="th04-req-4",
            intent_id="intent-4",
            action="cancel",
            dispatch_state="blocked_pre_dispatch",
            order_ref="ref-1",
            sequence=4,
            mutation=mutation,
        )
        for request_id, action, order_ref, dispatch_state in (
            ("th04-req-1", "submit", "ref-1", "dispatched"),
            ("th04-req-2", "submit", "ref-2", "dispatched"),
            ("th04-req-3", "cancel", "ref-1", "dispatched"),
            ("th04-req-4", "cancel", "ref-1", "blocked_pre_dispatch"),
        ):
            event_kind = "ORDER_SUBMIT_RECEIPT" if action == "submit" else "ORDER_CANCEL_RECEIPT"
            event_when = {
                "th04-req-1": NOW - timedelta(seconds=8),
                "th04-req-2": NOW - timedelta(seconds=6),
                "th04-req-3": NOW - timedelta(seconds=4),
                "th04-req-4": NOW - timedelta(seconds=2),
            }[request_id]
            add(
                event_kind,
                {
                    "request_id": request_id,
                    "action": action,
                    "order_ref": order_ref,
                    "trace_id": f"trace-{request_id}",
                    "dispatch_state": dispatch_state,
                },
                when=event_when,
            )
        add(
            "MONITOR_TRIGGER",
            {
                "metric": metric,
                "threshold": threshold,
                "observed_value": 2 if mutation == "observed_count" else 3,
                "configuration_digest": CONFIG_DIGEST,
                "monitor_digest": MONITOR_DIGEST,
                "source_request_ids": ("th04-req-1", "th04-req-2", "th04-req-3"),
                "source_native_event_ids": (
                    "order_accepted-2",
                    "order_accepted-3",
                    "order_canceled-4",
                ),
            },
            when=NOW - timedelta(seconds=0.1),
        )
    result = state.evaluate(now_utc=NOW)
    return state, result


@pytest.mark.parametrize("case_id", tuple(_STRATEGY_CLASS))
def test_six_case_states_reach_review_only_with_correlated_typed_sources(
    loaded_case_modules, case_id
):
    decision, case_engine, strategies = loaded_case_modules
    state, result = _complete_case(decision, case_engine, strategies, case_id)
    assert result.status == "REVIEW_REQUIRED", result.missing_conditions
    assert result.certification_pass is False
    assert result.dispatch_permitted is False
    assert result.source_authenticity_verified is False
    assert not result.missing_conditions
    assert len(state._events) > 0


@pytest.mark.parametrize(
    "case_id,mutator",
    (
        ("O01", "repeat_source"),
        ("O02", "receipt_ref"),
        ("O03", "repeat_key"),
        ("TH02", "config_digest"),
        ("TH04", "observed_count"),
        ("TH06", "repeat_window"),
    ),
)
def test_each_case_rejects_a_cross_source_or_threshold_mismatch(
    loaded_case_modules, case_id, mutator
):
    decision, case_engine, strategies = loaded_case_modules
    state, _ = _complete_case(decision, case_engine, strategies, case_id, mutation=mutator)
    result = state.evaluate(now_utc=NOW)
    assert result.status == "INCOMPLETE"
    assert result.certification_pass is False
    assert result.dispatch_permitted is False
    assert result.missing_conditions


@pytest.mark.parametrize(
    "case_id,mutation,expected_condition",
    (
        (
            "O01",
            "native_instrument_mismatch",
            "native_order_must_match_current_subscribed_tick_instrument",
        ),
        (
            "O02",
            "native_instrument_mismatch",
            "native_order_must_match_current_subscribed_tick_instrument",
        ),
        (
            "TH02",
            "native_instrument_mismatch",
            "native_order_must_match_current_subscribed_tick_instrument",
        ),
        ("O01", "stale_native_event", "provider_event_stale_at_evaluation"),
        ("O03", "stale_native_event", "provider_event_stale_at_evaluation"),
        ("TH04", "stale_native_event", "provider_event_stale_at_evaluation"),
        ("TH06", "stale_native_event", "provider_event_stale_at_evaluation"),
        (
            "O03",
            "generation_mismatch",
            "provider_evidence_must_share_one_connection_generation",
        ),
    ),
)
def test_provider_instrument_session_generation_and_freshness_are_coherent(
    loaded_case_modules, case_id, mutation, expected_condition
):
    decision, case_engine, strategies = loaded_case_modules
    _, result = _complete_case(decision, case_engine, strategies, case_id, mutation=mutation)
    assert result.status == "INCOMPLETE"
    assert expected_condition in result.missing_conditions
    assert result.certification_pass is False
    assert result.dispatch_permitted is False


@pytest.mark.parametrize("case_id", tuple(_STRATEGY_CLASS))
def test_each_order_candidate_requires_a_scope_account_identity_binding(
    loaded_case_modules, case_id
):
    decision, case_engine, strategies = loaded_case_modules
    state, _, _ = _context(decision, case_engine, strategies, case_id, account_identity_sha256="")
    result = state.evaluate(now_utc=NOW)
    assert result.status == "INCOMPLETE"
    assert "account_identity_scope_binding_required" in result.missing_conditions
    assert result.dispatch_permitted is False


@pytest.mark.parametrize("case_id", tuple(_STRATEGY_CLASS))
def test_managed_receipt_instrument_must_match_native_order(loaded_case_modules, case_id):
    decision, case_engine, strategies = loaded_case_modules
    _, result = _complete_case(
        decision,
        case_engine,
        strategies,
        case_id,
        mutation="receipt_instrument_mismatch",
    )
    assert result.status == "INCOMPLETE"
    assert any(
        condition.startswith("managed_receipt_instrument")
        for condition in result.missing_conditions
    )


@pytest.mark.parametrize(
    "case_id,api,account_digest",
    (
        ("O01", "supporting", ""),
        ("O01", "supporting", "d" * 64),
        ("TH02", "required", ""),
        ("TH02", "required", "d" * 64),
    ),
)
def test_native_provider_observation_rejects_missing_or_wrong_scope_account_digest(
    loaded_case_modules, case_id, api, account_digest
):
    decision, case_engine, strategies = loaded_case_modules
    state, _, _ = _context(decision, case_engine, strategies, case_id)
    if api == "supporting":
        _record_provider_login_binding(decision, state)
    event = _make_event(
        decision,
        "ORDER_ACCEPTED",
        4 if api == "supporting" else 1,
        {
            "order_ref": "ref-1",
            "external_order_id": "sys-1",
            "instrument_id": "rb2710",
            "status": "working",
            "remaining_quantity": "1",
            "connection_generation": 1,
            "account_identity_sha256": account_digest,
        },
        when=NOW - timedelta(seconds=1),
    )
    if api == "supporting":
        assert state.record_supporting_observation(event) is False
    else:
        assert state.record(event) is False
    assert event not in state._events
    expected = (
        "local_account_scope_fingerprint_required"
        if not account_digest
        else "local_account_scope_fingerprint_mismatch"
    )
    assert any(expected in item for item in state._rejected)
    assert state.evaluate(now_utc=NOW).status != "REVIEW_REQUIRED"


def test_cross_account_native_fact_blocks_a_previously_reviewable_candidate(
    loaded_case_modules,
):
    decision, case_engine, strategies = loaded_case_modules
    state, result = _complete_case(decision, case_engine, strategies, "O01")
    assert result.status == "REVIEW_REQUIRED"

    wrong_account = _make_event(
        decision,
        "ORDER_ACCEPTED",
        7,
        {
            "order_ref": "ref-cross-account",
            "external_order_id": "sys-cross-account",
            "instrument_id": "rb2710",
            "status": "working",
            "remaining_quantity": "1",
            "traded_quantity": "0",
            "connection_generation": 1,
            "account_identity_sha256": "d" * 64,
        },
        when=NOW - timedelta(seconds=0.5),
    )
    assert state.record_supporting_observation(wrong_account) is False
    result = state.evaluate(now_utc=NOW)
    assert result.status == "INCOMPLETE"
    assert result.certification_pass is False
    assert result.dispatch_permitted is False


def test_rejected_monitor_event_poisons_a_previously_reviewable_candidate(
    loaded_case_modules,
):
    decision, case_engine, strategies = loaded_case_modules
    state, result = _complete_case(decision, case_engine, strategies, "O01")
    assert result.status == "REVIEW_REQUIRED"

    invalid_configuration = _make_event(
        decision,
        "MONITOR_CONFIGURATION",
        1000,
        {"metric": "repeat_order_count"},
    )
    with pytest.raises(ValueError, match="monitor configuration is missing typed"):
        state.record_monitor_configuration(invalid_configuration)
    result = state.evaluate(now_utc=NOW)
    assert result.status == "INCOMPLETE"
    assert "rejected_evidence_present" in result.missing_conditions


@pytest.mark.parametrize(
    "api_name,exception_type,expected_message",
    (
        ("record", ValueError, "event kind is not a native decision-engine observation"),
        ("record_supporting_observation", ValueError, "case does not permit"),
        ("record_monitor_configuration", ValueError, "only monitor_configuration"),
        ("record_managed_receipt", TypeError, "must use ManagedIntentReceipt"),
    ),
)
def test_rejection_latch_survives_unreadable_evidence_ids(
    loaded_case_modules, api_name, exception_type, expected_message
):
    decision, case_engine, strategies = loaded_case_modules
    state, result = _complete_case(decision, case_engine, strategies, "O01")
    assert result.status == "REVIEW_REQUIRED"

    class PoisonEvent:
        kind = "not_a_native_event"

        @property
        def event_id(self):
            raise RuntimeError("event_id must not replace the validation error")

        @property
        def request_id(self):
            raise RuntimeError("request_id must not replace the validation error")

    with pytest.raises(exception_type, match=expected_message):
        getattr(state, api_name)(PoisonEvent())
    result = state.evaluate(now_utc=NOW)
    assert result.status == "INCOMPLETE"
    assert "rejected_evidence_present" in result.missing_conditions
    assert any(item.startswith("unknown-evidence:rejected_") for item in state._rejected)


def test_cross_generation_supporting_fact_is_rejected_and_poisons_review(
    loaded_case_modules,
):
    decision, case_engine, strategies = loaded_case_modules
    state, result = _complete_case(decision, case_engine, strategies, "O01")
    assert result.status == "REVIEW_REQUIRED"

    event = _make_event(
        decision,
        "ORDER_ACCEPTED",
        1000,
        {
            "order_ref": "ref-foreign-generation",
            "external_order_id": "sys-foreign-generation",
            "instrument_id": "rb2710",
            "status": "working",
            "remaining_quantity": "1",
            "traded_quantity": "0",
            "account_identity_sha256": ACCOUNT_IDENTITY_SHA256,
            "connection_generation": 2,
        },
    )

    assert state.record_supporting_observation(event) is False
    assert event not in state._events
    result = state.evaluate(now_utc=NOW)
    assert result.status == "INCOMPLETE"
    assert "rejected_evidence_present" in result.missing_conditions
    assert any(
        "provider_evidence_must_share_one_connection_generation" in item
        for item in state._rejected
    )


@pytest.mark.parametrize("case_id", ("TH04", "TH06"))
def test_threshold_identity_requires_native_login_not_front_or_auth(
    loaded_case_modules, case_id
):
    decision, case_engine, strategies = loaded_case_modules
    state, _, _ = _context(decision, case_engine, strategies, case_id)
    front = _make_event(
        decision,
        "FRONT_CONNECTED",
        1,
        {
            "gateway_key": "g1",
            "account_identity_sha256": ACCOUNT_IDENTITY_SHA256,
            "connection_generation": 1,
        },
        when=NOW - timedelta(seconds=3),
    )
    auth = _make_event(
        decision,
        "AUTH_SUCCESS",
        2,
        {
            "error_id": 0,
            "success": True,
            "account_identity_sha256": ACCOUNT_IDENTITY_SHA256,
            "connection_generation": 1,
        },
        when=NOW - timedelta(seconds=2),
    )
    for event in (front, auth):
        with pytest.raises(decision.DecisionError, match="not required by case"):
            state.record(event)
        assert event not in state._events

    order = _make_event(
        decision,
        "ORDER_ACCEPTED",
        3,
        {
            "order_ref": "ref-unbound-login",
            "external_order_id": "sys-unbound-login",
            "instrument_id": "rb2710",
            "status": "working",
            "remaining_quantity": "1",
            "traded_quantity": "0",
            "account_identity_sha256": ACCOUNT_IDENTITY_SHA256,
            "connection_generation": 1,
        },
    )
    assert state.record_supporting_observation(order) is False
    result = state.evaluate(now_utc=NOW)
    assert result.status == "INCOMPLETE"
    assert "native_provider_evidence_required" in result.missing_conditions
    assert not any(event.kind.name == "LOGIN_SUCCESS" for event in state._events)
    assert any(
        "provider_evidence_must_share_one_connection_generation" in item
        for item in state._rejected
    )


def test_front_auth_and_login_fixtures_use_their_native_identity_sources(loaded_case_modules):
    decision, case_engine, strategies = loaded_case_modules
    state, _, _ = _context(decision, case_engine, strategies, "O01")
    provider_scope = {
        "account_identity_sha256": ACCOUNT_IDENTITY_SHA256,
        "connection_generation": 1,
    }

    front = _make_event(
        decision,
        "FRONT_CONNECTED",
        1,
        {"gateway_key": "g1", **provider_scope},
        when=NOW - timedelta(seconds=12),
    )
    assert state.record(front)
    assert front.provider_front_id is None
    assert front.provider_session_id == ""
    assert front.trading_day == ""

    auth = _make_event(
        decision,
        "AUTH_SUCCESS",
        2,
        {"error_id": 0, "success": True, **provider_scope},
        when=NOW - timedelta(seconds=11),
    )
    assert state.record(auth)
    assert auth.provider_front_id is None
    assert auth.provider_session_id == ""
    assert auth.trading_day == ""

    login = _make_event(
        decision,
        "LOGIN_SUCCESS",
        3,
        {
            "error_id": 0,
            "success": True,
            "provider_front_id": 7,
            "provider_session_id": "10007",
            "trading_day": "20260928",
            **provider_scope,
        },
        when=NOW - timedelta(seconds=10),
    )
    assert state.record(login)
    assert login.provider_front_id == 7
    assert login.provider_session_id == "10007"
    assert login.trading_day == "20260928"
    assert login.session_identity_origin == "native_login_response_fields"


def test_auth_callback_rejects_fabricated_login_identity(loaded_case_modules):
    decision, case_engine, strategies = loaded_case_modules
    state, result = _complete_case(decision, case_engine, strategies, "O01")
    assert result.status == "REVIEW_REQUIRED"

    auth = _make_event(
        decision,
        "AUTH_SUCCESS",
        7,
        {
            "error_id": 0,
            "success": True,
            "account_identity_sha256": ACCOUNT_IDENTITY_SHA256,
            "connection_generation": 1,
        },
        when=NOW - timedelta(seconds=0.5),
    )
    forged = replace(
        auth,
        event_id="auth-with-fabricated-login-identity",
        provider_front_id=7,
        provider_session_id="10007",
        trading_day="20260928",
        fields={
            **auth.fields,
            "provider_front_id": 7,
            "provider_session_id": "10007",
            "trading_day": "20260928",
        },
    )
    with pytest.raises(ValueError, match="OnRspAuthenticate cannot claim native login identity"):
        state.record(forged)
    result = state.evaluate(now_utc=NOW)
    assert result.status == "INCOMPLETE"
    assert "rejected_evidence_present" in result.missing_conditions


@pytest.mark.parametrize(
    "session_id,trading_day,expected_message",
    (
        ("", "20260928", "native callback requires provider session and trading day"),
        ("10008", "20260928", "must match native login identity"),
        ("10007", "20260929", "must match native login identity"),
    ),
)
def test_followup_callback_requires_the_native_login_scope(
    loaded_case_modules, session_id, trading_day, expected_message
):
    decision, case_engine, strategies = loaded_case_modules
    state, result = _complete_case(decision, case_engine, strategies, "O01")
    assert result.status == "REVIEW_REQUIRED"

    followup = _make_event(
        decision,
        "MARKET_TICK",
        7,
        {
            "instrument_id": "rb2710",
            "bid": "100",
            "ask": "101",
            "last": "100.5",
            "price_tick": "1",
            "account_identity_sha256": ACCOUNT_IDENTITY_SHA256,
            "connection_generation": 1,
        },
        when=NOW - timedelta(seconds=0.5),
    )
    wrong_scope = replace(
        followup,
        event_id=f"wrong-login-scope-{session_id or 'missing'}-{trading_day}",
        sequence=7,
        provider_session_id=session_id,
        trading_day=trading_day,
    )
    with pytest.raises(ValueError, match=expected_message):
        state.record(wrong_scope)
    result = state.evaluate(now_utc=NOW)
    assert result.status == "INCOMPLETE"
    assert "rejected_evidence_present" in result.missing_conditions


@pytest.mark.parametrize("account_digest", ("", "d" * 64))
def test_managed_receipt_rejects_missing_or_different_scope_account_digest(
    loaded_case_modules, account_digest
):
    decision, case_engine, strategies = loaded_case_modules
    state, _, _ = _context(decision, case_engine, strategies, "O01")
    receipt_type = importlib.import_module("_typed_scenario_state_candidate").ManagedIntentReceipt
    receipt = receipt_type(
        request_id="account-bound-request",
        intent_id="intent-1",
        action="open",
        dispatch_state="dispatched",
        order_ref="ref-1",
        instrument_id="rb2710",
        repeat_key="key-1",
        account_identity_sha256=account_digest,
        configuration_digest=CONFIG_DIGEST,
        threshold=2,
        window_seconds=10.0,
        occurred_at_utc=NOW.isoformat().replace("+00:00", "Z"),
        sequence=1,
        evidence_sha256="d" * 64,
    )
    assert state.record_managed_receipt(receipt) is False
    expected = (
        "managed_receipt_account_identity_sha256_required"
        if not account_digest
        else "managed_receipt_account_identity_scope_mismatch"
    )
    assert any(expected in item for item in state._rejected)


@pytest.mark.parametrize(
    "case_id,api,status,remaining,expected_condition",
    (
        ("O01", "supporting", "rejected", "1", "native_order_accepted_status_invalid"),
        (
            "O01",
            "supporting",
            "working",
            "-1",
            "native_order_accepted_remaining_quantity_must_be_positive",
        ),
        (
            "O01",
            "supporting",
            "working",
            "0",
            "native_order_accepted_remaining_quantity_must_be_positive",
        ),
        (
            "O01",
            "supporting",
            "working",
            "NaN",
            "native_order_remaining_quantity_must_be_finite_decimal",
        ),
        (
            "TH02",
            "required",
            "working",
            "Infinity",
            "native_order_remaining_quantity_must_be_finite_decimal",
        ),
    ),
)
def test_order_accepted_semantics_reject_invalid_status_or_quantity(
    loaded_case_modules, case_id, api, status, remaining, expected_condition
):
    decision, case_engine, strategies = loaded_case_modules
    state, _, _ = _context(decision, case_engine, strategies, case_id)
    if api == "supporting":
        _record_provider_login_binding(decision, state)
    event = _make_event(
        decision,
        "ORDER_ACCEPTED",
        4 if api == "supporting" else 1,
        {
            "order_ref": "ref-1",
            "external_order_id": "sys-1",
            "instrument_id": "rb2710",
            "status": status,
            "remaining_quantity": remaining,
            "connection_generation": 1,
            "account_identity_sha256": ACCOUNT_IDENTITY_SHA256,
        },
        when=NOW - timedelta(seconds=1),
    )
    if api == "supporting":
        assert state.record_supporting_observation(event) is False
    else:
        assert state.record(event) is False
    assert event not in state._events
    assert any(expected_condition in item for item in state._rejected)


def test_managed_receipt_requires_explicit_verifier_and_rejects_wrong_scope(
    loaded_case_modules,
):
    decision, case_engine, strategies = loaded_case_modules
    state, _auth, _scope = _context(decision, case_engine, strategies, "O01")
    receipt_type = importlib.import_module("_typed_scenario_state_candidate").ManagedIntentReceipt
    receipt = receipt_type(
        request_id="unverified",
        intent_id="intent-1",
        action="open",
        dispatch_state="dispatched",
        order_ref="ref-1",
        instrument_id="rb2710",
        repeat_key="key-1",
        account_identity_sha256=ACCOUNT_IDENTITY_SHA256,
        configuration_digest=CONFIG_DIGEST,
        threshold=2,
        window_seconds=10.0,
        occurred_at_utc=NOW.isoformat().replace("+00:00", "Z"),
        sequence=1,
        evidence_sha256="c" * 64,
    )
    state.authenticator = object()
    assert state.record_managed_receipt(receipt) is False

    class WrongScopeAuthenticator(SyntheticAuthenticator):
        def authenticate_managed_receipt(self, managed_receipt, managed_scope):
            proof = super().authenticate_managed_receipt(managed_receipt, managed_scope)
            return replace(proof, scope_sha256="e" * 64)

    state.authenticator = WrongScopeAuthenticator(decision)
    assert state.record_managed_receipt(receipt) is False

    class WrongAccountAuthenticator(SyntheticAuthenticator):
        def authenticate_managed_receipt(self, managed_receipt, managed_scope):
            proof = super().authenticate_managed_receipt(managed_receipt, managed_scope)
            return replace(proof, account_identity_sha256="e" * 64)

    state.authenticator = WrongAccountAuthenticator(decision)
    assert state.record_managed_receipt(receipt) is False


def test_native_authentication_proof_must_bind_scope_account_identity(loaded_case_modules):
    decision, case_engine, strategies = loaded_case_modules
    state, _, _ = _context(decision, case_engine, strategies, "O01")
    _record_provider_login_binding(decision, state)
    event = _make_event(
        decision,
        "ORDER_ACCEPTED",
        4,
        {
            "order_ref": "ref-1",
            "external_order_id": "sys-1",
            "instrument_id": "rb2710",
            "status": "working",
            "remaining_quantity": "1",
            "connection_generation": 1,
            "account_identity_sha256": ACCOUNT_IDENTITY_SHA256,
        },
        when=NOW - timedelta(seconds=1),
    )

    class WrongAccountAuthenticator(SyntheticAuthenticator):
        def authenticate(self, native_event, scope):
            proof = super().authenticate(native_event, scope)
            return replace(proof, account_identity_sha256="e" * 64)

    state.authenticator = WrongAccountAuthenticator(decision)
    assert state.record_supporting_observation(event) is False
    assert event not in state._events
    assert any("supporting_native_auth_denied" in item for item in state._rejected)
