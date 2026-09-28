"""Offline contracts for the unregistered 007 typed decision layer."""

from __future__ import annotations

import importlib
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
def decision_module():
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
        yield importlib.import_module("common.decision_engine")
    finally:
        for name in list(sys.modules):
            if name == "common" or name.startswith("common."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
        sys.path[:] = previous_path


class ContractAuthenticator:
    """Synthetic interface probe; never evidence of real provider behavior."""

    def __init__(self, module):
        self.module = module

    def authenticate(self, observation, scope):
        return self.module.AuthenticationReceipt(
            event_id=observation.event_id,
            evidence_sha256=observation.evidence_sha256,
            scope_sha256=scope.scope_sha256,
            trust_domain=observation.source_domain,
            verification_ref="test-only-contract-authenticator",
            account_identity_sha256=scope.account_identity_sha256,
        )


def _plan(module, case_id, *, account_identity_sha256=""):
    source = CASES_ROOT / case_id / f"{case_id}_strategy.py"
    case_engine = importlib.import_module("common.case_engine")
    plan = case_engine.load_descriptive_case_plan(source, expected_case_id=case_id)
    scope = module.DecisionScope.for_plan(
        plan, "f" * 64, account_identity_sha256=account_identity_sha256
    )
    return plan, scope


def _event(module, kind_name, sequence, fields, *, stream="provider"):
    kind = module.ObservationKind[kind_name]
    domain, callback, _ = module._POLICY[kind]
    is_provider = domain is module.EvidenceTrustDomain.CTP_CALLBACK
    is_auth = kind is module.ObservationKind.AUTH_SUCCESS
    is_login = kind is module.ObservationKind.LOGIN_SUCCESS
    is_payloadless_front = kind in {
        module.ObservationKind.FRONT_CONNECTED,
        module.ObservationKind.FRONT_DISCONNECTED,
    }
    callback_fields = dict(fields)
    if is_provider:
        callback_fields.setdefault("connection_generation", 1)
    if is_auth or is_login:
        callback_fields.setdefault("request_id", sequence)
        callback_fields.setdefault("request_generation", sequence)
        callback_fields.setdefault(
            "arrival_generation", callback_fields.get("connection_generation", 1)
        )
        callback_fields.setdefault("is_last", True)
        callback_fields.setdefault("error_id", 0)
        callback_fields.setdefault("success", True)
    if is_login:
        callback_fields.setdefault("provider_front_id", 3)
        callback_fields.setdefault("provider_session_id", "17")
        callback_fields.setdefault("trading_day", "20260928")
    local_time = (
        NOW + timedelta(seconds=sequence) if is_auth or is_login else NOW
    ).isoformat().replace("+00:00", "Z")
    return module.NativeObservation(
        kind=kind,
        source_domain=domain,
        event_id=f"event-{kind_name}-{sequence}",
        evidence_sha256=f"{sequence:064x}",
        occurred_at_utc=local_time,
        sequence=sequence,
        stream_id=stream,
        callback_name=callback,
        provider_session_id=("" if is_auth or is_payloadless_front else "17") if is_provider else "",
        trading_day="20260928" if is_provider and not is_auth and not is_payloadless_front else "",
        fields=callback_fields,
        provider_front_id=3 if is_login else None,
        client_instance_id="ctp-client-1" if is_provider else "",
        request_generation=sequence if is_auth or is_login else 0,
        request_id_origin="native_callback_argument" if is_auth or is_login else "",
        request_generation_origin=(
            "local_request_generation_binding" if is_auth or is_login else ""
        ),
        arrival_generation=callback_fields.get("connection_generation", 1) if is_provider else 0,
        session_identity_origin=(
            "unavailable_on_native_authentication_response"
            if is_auth
            else "native_login_response_fields"
            if is_login
            else "unavailable_on_native_front_connection_callback"
            if is_payloadless_front
            else "derived_from_same_client_generation_native_login"
            if is_provider
            else ""
        ),
        arrived_at_utc=local_time if is_provider else "",
        arrived_monotonic=float(sequence) if is_provider else 0.0,
        sequence_origin="local_sdk_callback_arrival" if is_provider else "",
        timestamp_origin="local_sdk_capture_clock" if is_provider else "",
        event_id_origin="local_sdk_callback_arrival" if is_provider else "",
        provider_issued_event_id=False,
        connection_generation_origin="local_connection_generation" if is_payloadless_front else "",
    )


def _record(module, engine, kind, seq, fields, *, stream="provider"):
    event = _event(module, kind, seq, fields, stream=stream)
    assert engine.record(event)


def test_m03_reconnect_requires_one_new_provider_session_and_correlated_control_receipt(
    decision_module,
):
    module = decision_module
    old_session, new_session = "1", "2"
    specs = (
        (
            "FRONT_DISCONNECTED",
            1,
            old_session,
            {"gateway_key": "g1", "reason": "link_lost", "connection_generation": 7},
        ),
        ("FRONT_CONNECTED", 2, new_session, {"gateway_key": "g1", "connection_generation": 8}),
        (
            "AUTH_SUCCESS",
            3,
            new_session,
            {"error_id": 0, "success": True, "connection_generation": 8},
        ),
        (
            "LOGIN_SUCCESS",
            4,
            new_session,
            {"error_id": 0, "success": True, "connection_generation": 8},
        ),
        (
            "MARKET_SUBSCRIPTION_ACK",
            5,
            new_session,
            {
                "instrument_id": "rb2710",
                "error_id": 0,
                "success": True,
                "connection_generation": 8,
            },
        ),
        (
            "EXTERNAL_CONDITION",
            1,
            "",
            {
                "condition_id": "external_reconnect",
                "state": "satisfied",
                "evidence_ref": "operator-reconnect-1",
                "gateway_key": "g1",
                "previous_session_id": old_session,
                "new_session_id": new_session,
                "previous_connection_generation": 7,
                "new_connection_generation": 8,
                "disconnect_event_ref": "m03-FRONT_DISCONNECTED-0",
                "reconnect_event_ref": "m03-FRONT_CONNECTED-1",
            },
        ),
    )

    def evaluate(mutated=None):
        plan, scope = _plan(module, "M03")
        engine = module.CaseIntentDecisionEngine(plan, scope, ContractAuthenticator(module))
        for index, (kind, sequence, session, fields) in enumerate(mutated or specs):
            local_stream = f"provider-generation-{fields.get('connection_generation', 0)}"
            event = _event(module, kind, sequence, fields, stream=local_stream)
            callback_fields = dict(event.fields)
            if kind == "LOGIN_SUCCESS":
                callback_fields.update(
                    {
                        "provider_front_id": 3,
                        "provider_session_id": session,
                        "trading_day": "20260928",
                    }
                )
            if kind in {"AUTH_SUCCESS", "LOGIN_SUCCESS"}:
                callback_fields["arrival_generation"] = fields.get(
                    "connection_generation", 1
                )
            local_time = (NOW + timedelta(seconds=index)).isoformat().replace("+00:00", "Z")
            event = replace(
                event,
                event_id=f"m03-{kind}-{index}",
                occurred_at_utc=local_time,
                arrived_at_utc=local_time if kind in {"AUTH_SUCCESS", "LOGIN_SUCCESS"} else "",
                provider_session_id=(
                    session if kind in {"LOGIN_SUCCESS", "MARKET_SUBSCRIPTION_ACK"} else ""
                ),
                provider_front_id=3 if kind == "LOGIN_SUCCESS" else None,
                trading_day=(
                    "20260928" if kind in {"LOGIN_SUCCESS", "MARKET_SUBSCRIPTION_ACK"} else ""
                ),
                arrival_generation=fields.get("connection_generation", 1)
                if kind in {"AUTH_SUCCESS", "LOGIN_SUCCESS"}
                else event.arrival_generation,
                fields=callback_fields,
            )
            try:
                assert engine.record(event)
            except module.DecisionError:
                break
        return engine.evaluate(now_utc=NOW + timedelta(seconds=10))

    result = evaluate()
    assert result.status is module.DecisionStatus.INCOMPLETE
    assert result.intent_candidate is None
    assert result.certification_pass is False
    assert result.dispatch_permitted is False

    for kind_to_misbind in ("LOGIN_SUCCESS", "MARKET_SUBSCRIPTION_ACK"):
        mixed = tuple(
            (kind, sequence, "3" if kind == kind_to_misbind else session, fields)
            for kind, sequence, session, fields in specs
        )
        result = evaluate(mixed)
        assert result.status is module.DecisionStatus.INCOMPLETE
        assert result.intent_candidate is None

    wrong_control = tuple(
        (
            kind,
            sequence,
            session,
            {**fields, "new_session_id": "3"} if kind == "EXTERNAL_CONDITION" else fields,
        )
        for kind, sequence, session, fields in specs
    )
    result = evaluate(wrong_control)
    assert result.status is module.DecisionStatus.INCOMPLETE
    assert result.intent_candidate is None

    same_generation = tuple(
        (
            kind,
            sequence,
            session,
            {**fields, "connection_generation": 7}
            if kind != "EXTERNAL_CONDITION" and session == new_session
            else {**fields, "new_connection_generation": 7}
            if kind == "EXTERNAL_CONDITION"
            else fields,
        )
        for kind, sequence, session, fields in specs
    )
    result = evaluate(same_generation)
    assert result.status is module.DecisionStatus.INCOMPLETE
    assert result.intent_candidate is None

    out_of_order = (
        specs[0],
        specs[1],
        specs[2],
        ("MARKET_SUBSCRIPTION_ACK", 3, new_session, specs[4][3]),
        ("LOGIN_SUCCESS", 4, new_session, specs[3][3]),
        specs[5],
    )
    result = evaluate(out_of_order)
    assert result.status is module.DecisionStatus.INCOMPLETE
    assert result.intent_candidate is None


def test_all_33_descriptive_plans_have_explicit_typed_specs_and_default_block(
    decision_module,
):
    module = decision_module
    case_ids = sorted(path.name for path in CASES_ROOT.iterdir() if path.is_dir())
    assert len(case_ids) == 33
    assert set(module.CASE_INTENT_SPECS) == set(case_ids)
    assert all(
        kind in module._POLICY
        for spec in module.CASE_INTENT_SPECS.values()
        for kind in spec.required_kinds
    )

    for case_id in case_ids:
        plan, scope = _plan(module, case_id)
        engine = module.CaseIntentDecisionEngine(plan, scope)
        result = engine.evaluate()
        assert result.status is module.DecisionStatus.BLOCKED
        assert result.certification_pass is False
        assert result.dispatch_permitted is False
        assert result.intent_candidate is None
        assert result.missing_conditions == ("trusted_authenticator_not_configured",)


def test_t01_candidate_requires_verified_native_session_tick_and_review_only_gate(
    decision_module,
):
    module = decision_module
    plan, scope = _plan(module, "T01")
    engine = module.CaseIntentDecisionEngine(plan, scope, ContractAuthenticator(module))
    _record(module, engine, "AUTH_SUCCESS", 1, {"error_id": 0, "success": True})
    _record(module, engine, "LOGIN_SUCCESS", 2, {"error_id": 0, "success": True})
    _record(module, engine, "FRONT_CONNECTED", 3, {"gateway_key": "g1"})
    _record(
        module,
        engine,
        "MARKET_SUBSCRIPTION_ACK",
        4,
        {"instrument_id": "rb2610", "success": True, "error_id": 0},
    )
    _record(
        module,
        engine,
        "MARKET_TICK",
        5,
        {"instrument_id": "rb2610", "bid": "100", "ask": "101", "last": "100.5", "price_tick": "1"},
    )
    _record(
        module,
        engine,
        "ORDER_ADMISSION",
        1,
        {
            "case_id": "T01",
            "intent_kind": "open",
            "approval_ref": "review-only-1",
            "maximum_quantity": 1,
            "approval_state": "REVIEW_ONLY",
            "dispatch_permitted": False,
        },
        stream="managed",
    )

    result = engine.evaluate(now_utc=NOW)
    assert result.status is module.DecisionStatus.REVIEW_REQUIRED
    assert result.intent_candidate.intent_kind is module.IntentKind.OPEN_ORDER_CANDIDATE
    assert result.intent_candidate.dispatch_permitted is False
    assert result.certification_pass is False
    assert result.dispatch_permitted is False
    assert not hasattr(engine, "submit")
    assert not hasattr(engine, "cancel")
    assert not hasattr(engine, "dispatch")


def test_callback_name_and_local_event_text_without_authenticator_stay_blocked(
    decision_module,
):
    module = decision_module
    plan, scope = _plan(module, "T01")
    engine = module.CaseIntentDecisionEngine(plan, scope)
    fake = _event(module, "LOGIN_SUCCESS", 1, {"error_id": 0, "success": True})
    assert engine.record(fake) is False
    result = engine.evaluate()
    assert result.status is module.DecisionStatus.BLOCKED
    assert result.intent_candidate is None
    assert result.rejected_observations == ("event-LOGIN_SUCCESS-1:authenticator_unavailable",)


def test_receipt_cannot_be_replayed_across_case_scope(decision_module):
    module = decision_module

    class WrongScopeAuthenticator:
        def authenticate(self, event, scope):
            return module.AuthenticationReceipt(
                event.event_id,
                event.evidence_sha256,
                "0" * 64,
                event.source_domain,
                "wrong-scope-receipt",
            )

    plan, scope = _plan(module, "C01")
    engine = module.CaseIntentDecisionEngine(plan, scope, WrongScopeAuthenticator())
    event = _event(module, "AUTH_SUCCESS", 1, {"error_id": 0, "success": True})
    assert engine.record(event) is False
    assert engine.evaluate().status is module.DecisionStatus.BLOCKED
    assert "verification_receipt_mismatch" in engine.evaluate().rejected_observations[0]


def test_c01_auth_keeps_native_scope_null_and_missing_login_is_incomplete(decision_module):
    module = decision_module
    plan, scope = _plan(module, "C01")
    engine = module.CaseIntentDecisionEngine(plan, scope, ContractAuthenticator(module))
    auth = _event(module, "AUTH_SUCCESS", 1, {"error_id": 0, "success": True})

    assert auth.provider_front_id is None
    assert auth.provider_session_id == ""
    assert auth.trading_day == ""
    assert auth.timestamp_origin == "local_sdk_capture_clock"
    assert auth.sequence_origin == "local_sdk_callback_arrival"
    assert engine.record(auth)
    result = engine.evaluate(now_utc=NOW)
    assert result.status is module.DecisionStatus.INCOMPLETE
    assert "login_success_required" in result.missing_conditions
    assert result.certification_pass is False
    assert result.dispatch_permitted is False


def test_c01_auth_and_login_must_remain_on_same_client_arrival_generation(decision_module):
    module = decision_module
    plan, scope = _plan(module, "C01")
    engine = module.CaseIntentDecisionEngine(plan, scope, ContractAuthenticator(module))
    auth = _event(module, "AUTH_SUCCESS", 1, {"error_id": 0, "success": True})
    login = _event(module, "LOGIN_SUCCESS", 2, {"error_id": 0, "success": True})
    login_fields = {**login.fields, "arrival_generation": 2}
    login = replace(login, arrival_generation=2, fields=login_fields)

    assert engine.record(auth)
    assert engine.record(login)
    result = engine.evaluate(now_utc=NOW)
    assert result.status is module.DecisionStatus.INCOMPLETE
    assert "auth_login_same_client_generation_and_distinct_requests_required" in result.missing_conditions
    assert result.certification_pass is False
    assert result.dispatch_permitted is False


def test_c01_rejects_legacy_auth_session_and_day_claims(decision_module):
    module = decision_module
    plan, scope = _plan(module, "C01")
    engine = module.CaseIntentDecisionEngine(plan, scope, ContractAuthenticator(module))
    auth = _event(module, "AUTH_SUCCESS", 1, {"error_id": 0, "success": True})
    legacy = replace(auth, provider_session_id="17", trading_day="20260928")

    with pytest.raises(module.DecisionError, match="OnRspAuthenticate cannot claim provider FrontID"):
        engine.record(legacy)


@pytest.mark.parametrize(
    "callback_kind",
    ("FRONT_CONNECTED", "FRONT_DISCONNECTED", "AUTH_SUCCESS"),
)
@pytest.mark.parametrize(
    "alias",
    (
        "front_id",
        "FrontID",
        "provider_front_id",
        "session_id",
        "SessionID",
        "provider_session_id",
        "trading_day",
        "TradingDay",
        "provider_trading_day",
        "account_id_masked",
        "masked_account_id",
        "provider_account_id",
        "account_identity_sha256",
        "opaque_session_ref",
        "local_session_id",
        "local_front_id",
        "local_provider_front_id",
        "local_provider_session_id",
        "local_trading_day",
        "local_account_id_masked",
    ),
)
def test_payloadless_front_and_auth_reject_login_identity_aliases(
    decision_module, callback_kind, alias
):
    module = decision_module
    plan, scope = _plan(module, "M02")
    engine = module.CaseIntentDecisionEngine(plan, scope, ContractAuthenticator(module))
    event = _event(module, callback_kind, 1, {alias: "forged-identity"})

    with pytest.raises(module.DecisionError, match="cannot carry login identity alias"):
        engine.record(event)


@pytest.mark.parametrize("callback_kind", ("FRONT_CONNECTED", "FRONT_DISCONNECTED", "AUTH_SUCCESS"))
def test_payloadless_front_and_auth_allow_only_scope_bound_local_metadata(
    decision_module, callback_kind
):
    module = decision_module
    plan, scope = _plan(
        module,
        "C01" if callback_kind == "AUTH_SUCCESS" else "M02",
        account_identity_sha256="f" * 64,
    )
    engine = module.CaseIntentDecisionEngine(plan, scope, ContractAuthenticator(module))
    event = _event(
        module,
        callback_kind,
        1,
        {
            "local_client_id": "ctp-client-1",
            "client_id": "ctp-client-1",
            "local_connection_generation": 1,
            "local_account_identity_sha256": scope.account_identity_sha256,
        },
    )

    engine._validate_no_login_identity_aliases(event)
    if callback_kind == "AUTH_SUCCESS":
        assert engine.record(event)


@pytest.mark.parametrize(
    "callback_kind",
    ("FRONT_CONNECTED", "FRONT_DISCONNECTED", "AUTH_SUCCESS"),
)
def test_payloadless_callback_rejects_unbound_local_scope_fingerprint(
    decision_module, callback_kind
):
    module = decision_module
    plan, scope = _plan(
        module,
        "C01" if callback_kind == "AUTH_SUCCESS" else "M02",
        account_identity_sha256="f" * 64,
    )
    engine = module.CaseIntentDecisionEngine(plan, scope, ContractAuthenticator(module))
    event = _event(
        module,
        callback_kind,
        1,
        {"local_account_identity_sha256": "a" * 64},
    )

    with pytest.raises(module.DecisionError, match="must exactly match the bound decision scope"):
        engine.record(event)


def test_authentication_allows_native_broker_and_user_echoes_without_session_identity(
    decision_module,
):
    module = decision_module
    plan, scope = _plan(module, "C01")
    engine = module.CaseIntentDecisionEngine(plan, scope, ContractAuthenticator(module))
    event = _event(
        module,
        "AUTH_SUCCESS",
        1,
        {
            "BrokerID": "broker-1",
            "UserID": "user-1",
            "UserProductInfo": "product-1",
            "AppID": "app-1",
            "AppType": "type-1",
            "error_id": 0,
            "success": True,
        },
    )

    assert engine.record(event)
    assert event.provider_front_id is None
    assert event.provider_session_id == ""
    assert event.trading_day == ""


def test_account_identity_fingerprint_is_bound_by_authentication_receipt(decision_module):
    module = decision_module

    class WrongAccountBindingAuthenticator(ContractAuthenticator):
        def authenticate(self, observation, scope):
            receipt = super().authenticate(observation, scope)
            return replace(receipt, account_identity_sha256="0" * 64)

    plan, scope = _plan(module, "T01")
    scope = module.DecisionScope.for_plan(
        plan, scope.scope_sha256, account_identity_sha256="a" * 64
    )
    engine = module.CaseIntentDecisionEngine(plan, scope, WrongAccountBindingAuthenticator(module))
    event = _event(module, "LOGIN_SUCCESS", 1, {"error_id": 0, "success": True})

    assert engine.record(event) is False
    snapshot = engine.evaluate(now_utc=NOW)
    assert snapshot.status is module.DecisionStatus.BLOCKED
    assert snapshot.intent_candidate is None
    assert "verification_receipt_mismatch" in snapshot.rejected_observations[0]


def test_b01_one_partial_order_does_not_make_batch_cancel_candidate(decision_module):
    module = decision_module
    plan, scope = _plan(module, "B01")
    engine = module.CaseIntentDecisionEngine(plan, scope, ContractAuthenticator(module))
    _record(module, engine, "AUTH_SUCCESS", 1, {"error_id": 0, "success": True})
    _record(module, engine, "LOGIN_SUCCESS", 2, {"error_id": 0, "success": True})
    _record(module, engine, "FRONT_CONNECTED", 3, {"gateway_key": "g1"})
    _record(
        module,
        engine,
        "MARKET_SUBSCRIPTION_ACK",
        4,
        {"instrument_id": "rb2610", "success": True, "error_id": 0},
    )
    _record(
        module,
        engine,
        "MARKET_TICK",
        5,
        {"instrument_id": "rb2610", "bid": "100", "ask": "101", "last": "100", "price_tick": "1"},
    )
    _record(
        module,
        engine,
        "ORDER_ADMISSION",
        1,
        {
            "case_id": "B01",
            "intent_kind": "batch_cancel",
            "approval_ref": "review-only-batch",
            "maximum_quantity": 2,
            "approval_state": "REVIEW_ONLY",
            "dispatch_permitted": False,
            "batch_cancel_supported": True,
        },
        stream="managed",
    )
    _record(
        module,
        engine,
        "ORDER_ACCEPTED",
        6,
        {
            "order_ref": "r1",
            "external_order_id": "e1",
            "instrument_id": "rb2610",
            "status": "working",
            "remaining_quantity": 2,
            "traded_quantity": 0,
        },
    )
    _record(
        module,
        engine,
        "ORDER_PARTIAL",
        7,
        {
            "order_ref": "r1",
            "external_order_id": "e1",
            "instrument_id": "rb2610",
            "status": "partial",
            "traded_quantity": 1,
            "remaining_quantity": 1,
        },
    )
    _record(
        module, engine, "TRADE_EXECUTION", 8, {"order_ref": "r1", "trade_id": "t1", "quantity": 1}
    )
    _record(
        module,
        engine,
        "ORDER_QUERY",
        9,
        {"query_id": "q1", "complete": True, "open_order_refs": ["r1"]},
    )

    result = engine.evaluate(now_utc=NOW)
    assert result.status is module.DecisionStatus.INCOMPLETE
    assert result.intent_candidate is None
    assert (
        "two_partial_orders_trade_reconciliation_and_batch_capability_required"
        in result.missing_conditions
    )
    assert result.certification_pass is False


def test_b02_requires_two_provider_orders_in_latest_complete_open_query(decision_module):
    module = decision_module
    plan, scope = _plan(module, "B02")
    engine = module.CaseIntentDecisionEngine(plan, scope, ContractAuthenticator(module))
    _record(module, engine, "AUTH_SUCCESS", 1, {"error_id": 0, "success": True})
    _record(module, engine, "LOGIN_SUCCESS", 2, {"error_id": 0, "success": True})
    _record(module, engine, "FRONT_CONNECTED", 3, {"gateway_key": "g1"})
    _record(
        module,
        engine,
        "MARKET_SUBSCRIPTION_ACK",
        4,
        {"instrument_id": "rb2610", "success": True, "error_id": 0},
    )
    _record(
        module,
        engine,
        "MARKET_TICK",
        5,
        {"instrument_id": "rb2610", "bid": 100, "ask": 101, "last": 100, "price_tick": 1},
    )
    _record(
        module,
        engine,
        "ORDER_ADMISSION",
        1,
        {
            "case_id": "B02",
            "intent_kind": "batch_cancel",
            "approval_ref": "review-only-batch",
            "maximum_quantity": 2,
            "approval_state": "REVIEW_ONLY",
            "dispatch_permitted": False,
            "batch_cancel_supported": True,
        },
        stream="managed",
    )
    for sequence, ref in ((6, "r1"), (7, "r2")):
        _record(
            module,
            engine,
            "ORDER_ACCEPTED",
            sequence,
            {
                "order_ref": ref,
                "external_order_id": f"e-{ref}",
                "instrument_id": "rb2610",
                "status": "working",
                "remaining_quantity": 1,
                "traded_quantity": 0,
            },
        )
    _record(
        module,
        engine,
        "ORDER_QUERY",
        8,
        {"query_id": "q1", "complete": True, "open_order_refs": ["r1"]},
    )

    result = engine.evaluate(now_utc=NOW)
    assert result.status is module.DecisionStatus.INCOMPLETE
    assert result.intent_candidate is None
    assert (
        "two_current_native_open_orders_and_batch_capability_required" in result.missing_conditions
    )


def test_e03_requires_external_condition_submit_receipt_and_native_rejection(
    decision_module,
):
    module = decision_module
    plan, scope = _plan(module, "E03")
    engine = module.CaseIntentDecisionEngine(plan, scope, ContractAuthenticator(module))
    _record(module, engine, "LOGIN_SUCCESS", 1, {"error_id": 0, "success": True})
    _record(module, engine, "FRONT_CONNECTED", 2, {"gateway_key": "g1"})
    _record(
        module,
        engine,
        "MARKET_TICK",
        3,
        {
            "instrument_id": "rb2610",
            "bid": "100",
            "ask": "101",
            "last": "100",
            "price_tick": "1",
            "market_state": "closed",
        },
    )
    result = engine.evaluate(now_utc=NOW)
    assert result.status is module.DecisionStatus.INCOMPLETE
    assert result.intent_candidate is None
    assert "external_condition" in result.missing_conditions
    assert "order_submit_receipt" in result.missing_conditions
    assert "order_rejected" in result.missing_conditions


def test_em03_requires_external_ack_disconnect_and_write_guard(decision_module):
    module = decision_module
    plan, scope = _plan(module, "EM03")
    engine = module.CaseIntentDecisionEngine(plan, scope, ContractAuthenticator(module))
    _record(
        module,
        engine,
        "FRONT_DISCONNECTED",
        1,
        {"gateway_key": "g1", "reason": "provider disconnect"},
    )
    result = engine.evaluate(now_utc=NOW)
    assert result.status is module.DecisionStatus.INCOMPLETE
    assert result.intent_candidate is None
    assert "gateway_logout_authorized" in result.missing_conditions
    assert "post_disconnect_write_blocked" in result.missing_conditions


def test_authenticated_unavailable_external_dependency_is_not_success(
    decision_module,
):
    module = decision_module
    plan, scope = _plan(module, "E01")
    engine = module.CaseIntentDecisionEngine(plan, scope, ContractAuthenticator(module))
    _record(
        module,
        engine,
        "EXTERNAL_CONDITION",
        1,
        {
            "condition_id": "insufficient_funds",
            "state": "unavailable",
            "evidence_ref": "external/ref-1",
            "reason": "account state not provided",
        },
        stream="control",
    )
    result = engine.evaluate(now_utc=NOW)
    assert result.status is module.DecisionStatus.EXTERNAL_CONDITION_UNAVAILABLE
    assert result.intent_candidate is None
    assert result.certification_pass is False


def test_c01_duplicate_native_request_ids_remain_incomplete(decision_module):
    module = decision_module
    plan, scope = _plan(module, "C01")
    engine = module.CaseIntentDecisionEngine(plan, scope, ContractAuthenticator(module))
    auth = _event(module, "AUTH_SUCCESS", 1, {"request_id": 7})
    login = _event(module, "LOGIN_SUCCESS", 2, {"request_id": 7})
    for event in (auth, login):
        assert engine.record(event)
    result = engine.evaluate(now_utc=NOW + timedelta(seconds=10))
    assert result.status is module.DecisionStatus.INCOMPLETE
    assert result.intent_candidate is None
