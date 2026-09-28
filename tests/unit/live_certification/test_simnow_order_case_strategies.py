"""Synthetic offline contracts for T01/T02/T03/B01/B02/L01 observers.

The contract authenticator below is deliberately synthetic. Complete examples
can reach only REVIEW_REQUIRED, and none of these tests claims provider
authenticity, SimNow acceptance, or a certification PASS.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITE_ROOT = REPO_ROOT / "examples" / "007_ctp" / "live_certification" / "simnow_penetration"
CASES_ROOT = SUITE_ROOT / "cases"
CASE_IDS = ("T01", "T02", "T03", "B01", "B02", "L01")
BASE_TIME = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)
SCOPE_SHA256 = "d" * 64
ACCOUNT_IDENTITY_SHA256 = hashlib.sha256(b"synthetic-contract-test-account").hexdigest()
EVALUATION_TIME = BASE_TIME + timedelta(seconds=30)


@pytest.fixture
def strategy_context():
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
        case_engine = importlib.import_module("common.case_engine")
        decision = importlib.import_module("common.decision_engine")
        strategies = {}
        for case_id in CASE_IDS:
            path = CASES_ROOT / case_id / f"{case_id}_strategy.py"
            spec = importlib.util.spec_from_file_location(f"order_strategy_{case_id}", path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            strategies[case_id] = module
        yield case_engine, decision, strategies
    finally:
        for name in list(sys.modules):
            if name == "common" or name.startswith("common."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
        sys.path[:] = previous_path


class ContractAuthenticator:
    """Synthetic shape verifier, never a provider or managed-runtime verifier."""

    def __init__(self, decision):
        self.decision = decision

    def authenticate(self, observation, scope):
        return self.decision.AuthenticationReceipt(
            event_id=observation.event_id,
            evidence_sha256=observation.evidence_sha256,
            scope_sha256=scope.scope_sha256,
            trust_domain=observation.source_domain,
            verification_ref="synthetic-test-contract-only",
            account_identity_sha256=scope.account_identity_sha256,
        )


def _strategy(strategy_context, case_id, *, account_identity_sha256=ACCOUNT_IDENTITY_SHA256):
    case_engine, decision, strategies = strategy_context
    path = CASES_ROOT / case_id / f"{case_id}_strategy.py"
    plan = case_engine.load_descriptive_case_plan(path, expected_case_id=case_id)
    scope = decision.DecisionScope.for_plan(
        plan, SCOPE_SHA256, account_identity_sha256=account_identity_sha256
    )
    strategy = strategies[case_id].create_strategy(plan, scope, ContractAuthenticator(decision))
    return decision, strategy


def _envelope(
    decision,
    case_id,
    kind_name,
    sequence,
    offset,
    fields,
    *,
    source_domain=None,
    callback=None,
    stream="native",
    session="session-1",
    trading_day="20260928",
):
    kind = decision.ObservationKind[kind_name]
    default_domains = {
        "FRONT_CONNECTED": decision.EvidenceTrustDomain.CTP_CALLBACK,
        "AUTH_SUCCESS": decision.EvidenceTrustDomain.CTP_CALLBACK,
        "LOGIN_SUCCESS": decision.EvidenceTrustDomain.CTP_CALLBACK,
        "MARKET_SUBSCRIPTION_ACK": decision.EvidenceTrustDomain.CTP_CALLBACK,
        "MARKET_TICK": decision.EvidenceTrustDomain.CTP_CALLBACK,
        "ORDER_ADMISSION": decision.EvidenceTrustDomain.MANAGED_RUNTIME,
        "ORDER_SUBMIT_RECEIPT": decision.EvidenceTrustDomain.MANAGED_RUNTIME,
        "ORDER_ACCEPTED": decision.EvidenceTrustDomain.CTP_CALLBACK,
        "ORDER_PARTIAL": decision.EvidenceTrustDomain.CTP_CALLBACK,
        "ORDER_CANCELED": decision.EvidenceTrustDomain.CTP_CALLBACK,
        "ORDER_FILLED": decision.EvidenceTrustDomain.CTP_CALLBACK,
        "ORDER_REJECTED": decision.EvidenceTrustDomain.CTP_CALLBACK,
        "TRADE_EXECUTION": decision.EvidenceTrustDomain.CTP_CALLBACK,
        "ORDER_QUERY": decision.EvidenceTrustDomain.CTP_CALLBACK,
        "POSITION_QUERY": decision.EvidenceTrustDomain.CTP_CALLBACK,
        "EXTERNAL_CONDITION": decision.EvidenceTrustDomain.CONTROL_PLANE,
        "SYSTEM_LOG": decision.EvidenceTrustDomain.MANAGED_RUNTIME,
    }
    callbacks = {
        "FRONT_CONNECTED": "OnFrontConnected",
        "AUTH_SUCCESS": "OnRspAuthenticate",
        "LOGIN_SUCCESS": "OnRspUserLogin",
        "MARKET_SUBSCRIPTION_ACK": "OnRspSubMarketData",
        "MARKET_TICK": "OnRtnDepthMarketData",
        "ORDER_ADMISSION": "",
        "ORDER_SUBMIT_RECEIPT": "",
        "ORDER_ACCEPTED": "OnRtnOrder",
        "ORDER_PARTIAL": "OnRtnOrder",
        "ORDER_CANCELED": "OnRtnOrder",
        "ORDER_FILLED": "OnRtnOrder",
        "ORDER_REJECTED": "OnRspOrderInsert",
        "TRADE_EXECUTION": "OnRtnTrade",
        "ORDER_QUERY": "OnRspQryOrder",
        "POSITION_QUERY": (
            "OnRspQryTradingAccount"
            if fields.get("query_family") == "funds"
            else "OnRspQryInvestorPosition"
        ),
        "EXTERNAL_CONDITION": "",
        "SYSTEM_LOG": "",
    }
    source_domain = source_domain or default_domains[kind_name]
    callback = callbacks[kind_name] if callback is None else callback
    provider = source_domain is decision.EvidenceTrustDomain.CTP_CALLBACK
    is_auth = kind_name == "AUTH_SUCCESS"
    is_login = kind_name == "LOGIN_SUCCESS"
    is_payloadless_front = kind_name in {"FRONT_CONNECTED", "FRONT_DISCONNECTED"}
    fields = dict(fields)
    if kind_name == "FRONT_CONNECTED":
        fields.setdefault("connection_generation", 1)
    if is_auth or is_login:
        # Synthetic native callback IDs stay independent of local arrival sequence.
        fields.setdefault("request_id", 1 if is_auth else 2)
        fields.setdefault("request_generation", 1)
        fields.setdefault("arrival_generation", 1)
        fields.setdefault("is_last", True)
        fields.setdefault("error_id", 0)
        if is_login:
            fields.setdefault("provider_front_id", 1)
            fields.setdefault("provider_session_id", session)
            fields.setdefault("trading_day", trading_day)
    event_id = f"{case_id}-{kind_name}-{sequence}-{stream}"
    occurred_at = BASE_TIME + timedelta(seconds=offset)
    occurred_at_utc = occurred_at.isoformat().replace("+00:00", "Z")
    if is_auth:
        session_identity_origin = "unavailable_on_native_authentication_response"
    elif is_login:
        session_identity_origin = "native_login_response_fields"
    elif is_payloadless_front:
        session_identity_origin = "unavailable_on_native_front_connection_callback"
    elif provider:
        session_identity_origin = "derived_from_same_client_generation_native_login"
    else:
        session_identity_origin = ""
    native_login_identity = is_login
    native_session_id = session if provider and not (is_auth or is_payloadless_front) else ""
    native_trading_day = trading_day if provider and not (is_auth or is_payloadless_front) else ""
    return decision.NativeObservation(
        kind=kind,
        source_domain=source_domain,
        event_id=event_id,
        evidence_sha256=hashlib.sha256(event_id.encode()).hexdigest(),
        occurred_at_utc=occurred_at_utc,
        sequence=sequence,
        stream_id=stream,
        callback_name=callback,
        provider_session_id=native_session_id,
        trading_day=native_trading_day,
        fields=fields,
        provider_front_id=1 if native_login_identity else None,
        client_instance_id="synthetic-ctp-client" if provider else "",
        request_generation=1 if is_auth or is_login else 0,
        request_id_origin="native_callback_argument" if is_auth or is_login else "",
        request_generation_origin=("local_request_generation_binding" if is_auth or is_login else ""),
        arrival_generation=1 if provider else 0,
        session_identity_origin=session_identity_origin,
        event_id_origin="local_sdk_callback_arrival" if provider else "",
        provider_issued_event_id=False,
        arrived_at_utc=occurred_at_utc if provider else "",
        arrived_monotonic=float(sequence) if provider else 0.0,
        sequence_origin="local_sdk_callback_arrival" if provider else "",
        timestamp_origin="local_sdk_capture_clock" if provider else "",
        connection_generation_origin="local_connection_generation" if provider else "",
    )


def _system(decision, case_id, name, sequence, offset, **fields):
    event_id = f"{case_id}-SYSTEM_LOG-{name}-{sequence}"
    base = {
        "trace_id": f"trace-{event_id}",
        "gateway_key": "gateway-1",
        "log_digest": hashlib.sha256(event_id.encode()).hexdigest(),
        "event_name": name,
        "session_id": "session-1",
        **fields,
    }
    return _envelope(
        decision,
        case_id,
        "SYSTEM_LOG",
        sequence,
        offset,
        base,
        stream="runtime",
    )


def _query(decision, case_id, family, phase, sequence, offset, data, *, snapshot_id):
    kind_name = "ORDER_QUERY" if family == "orders" else "POSITION_QUERY"
    query_id = f"{case_id}-{phase}-{family}-query"
    fields = {
        "query_family": family,
        "phase": phase,
        "snapshot_id": snapshot_id,
        "query_id": query_id,
        "complete": True,
        "is_last": True,
        "error_id": 0,
        "account_identity_sha256": ACCOUNT_IDENTITY_SHA256,
        **data,
    }
    return _envelope(decision, case_id, kind_name, sequence, offset, fields)


def _snapshot_events(
    decision,
    case_id,
    phase,
    sequence,
    offset,
    positions,
    closeable,
    funds,
    open_refs=(),
):
    snapshot_id = f"{case_id}-{phase}-snapshot"
    return [
        _query(
            decision,
            case_id,
            "orders",
            phase,
            sequence,
            offset,
            {"open_order_refs_json": json.dumps(list(open_refs))},
            snapshot_id=snapshot_id,
        ),
        _query(
            decision,
            case_id,
            "positions",
            phase,
            sequence + 1,
            offset + 1,
            {
                "positions_json": json.dumps(positions, sort_keys=True),
                "closeable_quantities_json": json.dumps(closeable, sort_keys=True),
            },
            snapshot_id=snapshot_id,
        ),
        _query(
            decision,
            case_id,
            "funds",
            phase,
            sequence + 2,
            offset + 2,
            {"funds_json": json.dumps(funds, sort_keys=True)},
            snapshot_id=snapshot_id,
        ),
    ]


def _order_status(
    decision, case_id, kind, sequence, offset, order_ref, quantity, *, traded, remaining
):
    statuses = {
        "ORDER_ACCEPTED": "accepted",
        "ORDER_PARTIAL": "partial",
        "ORDER_CANCELED": "canceled",
        "ORDER_FILLED": "filled",
    }
    return _envelope(
        decision,
        case_id,
        kind,
        sequence,
        offset,
        {
            "order_ref": order_ref,
            "external_order_id": f"exchange-{order_ref}",
            "instrument_id": "rb2610",
            "status": statuses[kind],
            "traded_quantity": str(traded),
            "remaining_quantity": str(remaining),
        },
    )


def _trade(decision, case_id, sequence, offset, order_ref, quantity):
    return _envelope(
        decision,
        case_id,
        "TRADE_EXECUTION",
        sequence,
        offset,
        {
            "trade_id": f"trade-{order_ref}",
            "order_ref": order_ref,
            "external_order_id": f"exchange-{order_ref}",
            "instrument_id": "rb2610",
            "direction": "buy",
            "quantity": str(quantity),
            "price": "3500",
        },
    )


def _complete_observations(decision, case_id):
    quantity = 2 if case_id in {"B01", "B02"} else 1
    order_refs = ["order-1", "order-2"] if case_id in {"B01", "B02"} else ["order-1"]
    baseline_positions = {"rb2610": "3"} if case_id == "T02" else {}
    baseline_closeable = {"rb2610": "2"} if case_id == "T02" else {}
    initial_funds = {"cash": "100000", "available_funds": "90000", "equity": "100000"}
    events = [
        _system(decision, case_id, "session_started", 1, -60),
        _envelope(decision, case_id, "FRONT_CONNECTED", 1, 0, {"gateway_key": "gateway-1"}),
        _envelope(
            decision,
            case_id,
            "LOGIN_SUCCESS",
            2,
            1,
            {"success": True, "error_id": 0},
        ),
        _envelope(
            decision,
            case_id,
            "MARKET_SUBSCRIPTION_ACK",
            3,
            2,
            {"success": True, "instrument_id": "rb2610"},
        ),
        _envelope(
            decision,
            case_id,
            "MARKET_TICK",
            4,
            3,
            {
                "instrument_id": "rb2610",
                "bid": "3500",
                "ask": "3501",
                "last": "3500.5",
                "price_tick": "1",
            },
        ),
        _system(
            decision,
            case_id,
            "store_connected",
            2,
            6.2,
            market_connection=True,
            trade_connection=True,
        ),
        _system(
            decision, case_id, "store_ready", 3, 6.4, market_connection=True, trade_connection=True
        ),
        _envelope(
            decision,
            case_id,
            "ORDER_ADMISSION",
            1,
            6.5,
            {
                "case_id": case_id,
                "intent_kind": "close" if case_id == "T02" else "open",
                "approval_ref": f"review-{case_id}",
                "maximum_quantity": "2",
            },
            stream="admission",
        ),
    ]
    events.extend(
        _snapshot_events(
            decision,
            case_id,
            "baseline",
            5,
            4,
            baseline_positions,
            baseline_closeable,
            initial_funds,
        )
    )
    for index, order_ref in enumerate(order_refs, 1):
        events.append(
            _envelope(
                decision,
                case_id,
                "ORDER_SUBMIT_RECEIPT",
                index,
                7 + index / 10,
                {
                    "action": "submit",
                    "request_id": f"submit-{order_ref}",
                    "order_ref": order_ref,
                    "dispatch_state": "dispatched",
                    "quantity": str(quantity),
                    "instrument_id": "rb2610",
                    "account_identity_sha256": ACCOUNT_IDENTITY_SHA256,
                    "direction": "sell" if case_id == "T02" else "buy",
                    "offset": "close" if case_id == "T02" else "open",
                    "trace_id": f"trace-submit-{order_ref}",
                    "invocation_id": f"invoke-submit-{order_ref}",
                },
                stream="managed-submit",
            )
        )

    provider_sequence = 8
    cancel_event = None
    cancel_log_data = None
    if case_id in {"T01", "T02", "T03"}:
        events.append(
            _order_status(
                decision,
                case_id,
                "ORDER_ACCEPTED",
                provider_sequence,
                10,
                "order-1",
                quantity,
                traded=0,
                remaining=quantity,
            )
        )
        provider_sequence += 1
        cancel_log_data = {
            "request_id": "cancel-order-1",
            "invocation_id": "invoke-cancel-order-1",
            "order_ref": "order-1",
            "dispatch_state": "dispatched",
        }
        cancel_event = _system(decision, case_id, "order_cancel_request", 4, 11, **cancel_log_data)
        events.append(cancel_event)
        events.append(
            _order_status(
                decision,
                case_id,
                "ORDER_CANCELED",
                provider_sequence,
                12,
                "order-1",
                quantity,
                traded=0,
                remaining=0,
            )
        )
        provider_sequence += 1
        final_positions = baseline_positions
        final_funds = initial_funds
    elif case_id == "B01":
        for index, order_ref in enumerate(order_refs):
            events.append(
                _order_status(
                    decision,
                    case_id,
                    "ORDER_ACCEPTED",
                    provider_sequence,
                    10 + index,
                    order_ref,
                    quantity,
                    traded=0,
                    remaining=quantity,
                )
            )
            provider_sequence += 1
        for index, order_ref in enumerate(order_refs):
            events.append(
                _order_status(
                    decision,
                    case_id,
                    "ORDER_PARTIAL",
                    provider_sequence,
                    12 + index,
                    order_ref,
                    quantity,
                    traded=1,
                    remaining=1,
                )
            )
            provider_sequence += 1
            events.append(_trade(decision, case_id, provider_sequence, 13 + index, order_ref, 1))
            provider_sequence += 1
        batch_fields = {
            "request_id": "batch-cancel-1",
            "invocation_id": "invoke-batch-cancel-1",
            "dispatch_state": "dispatched",
            "order_refs_json": json.dumps(order_refs),
            "partial_count": 2,
        }
        cancel_event = _system(decision, case_id, "batch_cancel_requested", 4, 16, **batch_fields)
        events.append(cancel_event)
        for index, order_ref in enumerate(order_refs):
            events.append(
                _order_status(
                    decision,
                    case_id,
                    "ORDER_CANCELED",
                    provider_sequence,
                    18 + index,
                    order_ref,
                    quantity,
                    traded=1,
                    remaining=0,
                )
            )
            provider_sequence += 1
        final_positions = {"rb2610": "2"}
        final_funds = {"cash": "99990", "available_funds": "89990", "equity": "100000"}
    elif case_id == "B02":
        for index, order_ref in enumerate(order_refs):
            events.append(
                _order_status(
                    decision,
                    case_id,
                    "ORDER_ACCEPTED",
                    provider_sequence,
                    10 + index,
                    order_ref,
                    quantity,
                    traded=0,
                    remaining=quantity,
                )
            )
            provider_sequence += 1
        batch_fields = {
            "request_id": "batch-cancel-1",
            "invocation_id": "invoke-batch-cancel-1",
            "dispatch_state": "dispatched",
            "order_refs_json": json.dumps(order_refs),
            "open_order_count": 2,
        }
        cancel_event = _system(decision, case_id, "batch_cancel_requested", 4, 12, **batch_fields)
        events.append(cancel_event)
        events.append(
            _order_status(
                decision,
                case_id,
                "ORDER_CANCELED",
                provider_sequence,
                13,
                "order-2",
                quantity,
                traded=0,
                remaining=0,
            )
        )
        provider_sequence += 1
        events.append(_trade(decision, case_id, provider_sequence, 14, "order-1", quantity))
        provider_sequence += 1
        events.append(
            _order_status(
                decision,
                case_id,
                "ORDER_FILLED",
                provider_sequence,
                15,
                "order-1",
                quantity,
                traded=quantity,
                remaining=0,
            )
        )
        provider_sequence += 1
        final_positions = {"rb2610": "2"}
        final_funds = {"cash": "99990", "available_funds": "89990", "equity": "100000"}
    else:
        events.append(
            _order_status(
                decision,
                case_id,
                "ORDER_ACCEPTED",
                provider_sequence,
                10,
                "order-1",
                quantity,
                traded=0,
                remaining=quantity,
            )
        )
        provider_sequence += 1
        events.append(_trade(decision, case_id, provider_sequence, 11, "order-1", quantity))
        provider_sequence += 1
        events.append(
            _order_status(
                decision,
                case_id,
                "ORDER_FILLED",
                provider_sequence,
                12,
                "order-1",
                quantity,
                traded=quantity,
                remaining=0,
            )
        )
        provider_sequence += 1
        final_positions = {"rb2610": "1"}
        final_funds = {"cash": "99995", "available_funds": "89995", "equity": "100000"}

    events.extend(
        _snapshot_events(
            decision,
            case_id,
            "final",
            provider_sequence,
            20,
            final_positions,
            {},
            final_funds,
        )
    )
    cancel_count = int(cancel_event is not None)
    submit_count = len(order_refs)
    runtime_sequence = 5 if cancel_event else 4
    events.extend(
        [
            _system(
                decision,
                case_id,
                "session_stopped",
                runtime_sequence,
                26,
                clean_shutdown=True,
                gateway_released=True,
                exit_code=0,
            ),
            _system(
                decision,
                case_id,
                "write_activity_summary",
                runtime_sequence + 1,
                27,
                snapshot_complete=True,
                snapshot_digest="e" * 64,
                order_submit_count=submit_count,
                order_cancel_count=cancel_count,
                broker_write_count=submit_count + cancel_count,
            ),
        ]
    )
    return events


def _feed(strategy, events):
    for event in sorted(
        events, key=lambda item: datetime.fromisoformat(item.occurred_at_utc.replace("Z", "+00:00"))
    ):
        assert strategy.on_envelope(event)


def _replace_event_fields(event, **updates):
    return replace(event, fields={**event.fields, **updates})


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_complete_order_observation_contract_stops_at_review_required(strategy_context, case_id):
    decision, strategy = _strategy(strategy_context, case_id)
    _feed(strategy, _complete_observations(decision, case_id))

    result = strategy.evaluate(now_utc=EVALUATION_TIME)
    assert (
        result.state
        is importlib.import_module("common.read_only_case_strategy").ReadOnlyState.REVIEW_REQUIRED
    )
    assert result.certification_pass is False
    assert result.dispatch_permitted is False
    assert result.source_authenticity_verified is False
    assert not result.missing_conditions


@pytest.mark.parametrize("case_id", ("T01", "B01"))
def test_managed_submit_contract_must_match_subscribed_market_contract(strategy_context, case_id):
    decision, strategy = _strategy(strategy_context, case_id)
    events = _complete_observations(decision, case_id)
    events = [
        _replace_event_fields(event, instrument_id="UNRELATED-CONTRACT")
        if event.kind is decision.ObservationKind.ORDER_SUBMIT_RECEIPT
        else event
        for event in events
    ]
    _feed(strategy, events)

    result = strategy.evaluate(now_utc=EVALUATION_TIME)
    assert result.state.value == "INCOMPLETE"
    assert "managed_submit_instrument_must_match_market_tick" in result.missing_conditions


def test_native_order_contract_must_match_managed_submit(strategy_context):
    decision, strategy = _strategy(strategy_context, "T01")
    events = _complete_observations(decision, "T01")
    events = [
        _replace_event_fields(event, instrument_id="UNRELATED-CONTRACT")
        if event.kind is decision.ObservationKind.ORDER_ACCEPTED
        else event
        for event in events
    ]
    _feed(strategy, events)

    result = strategy.evaluate(now_utc=EVALUATION_TIME)
    assert result.state.value == "INCOMPLETE"
    assert "native_order_fact_instrument_must_match_managed_submit" in result.missing_conditions


def test_order_candidate_without_scope_account_fingerprint_stays_incomplete(strategy_context):
    decision, strategy = _strategy(strategy_context, "T01", account_identity_sha256="")
    _feed(strategy, _complete_observations(decision, "T01"))

    result = strategy.evaluate(now_utc=EVALUATION_TIME)
    assert result.state.value == "INCOMPLETE"
    assert "sealed_account_identity_fingerprint_required" in result.missing_conditions
    assert result.certification_pass is False
    assert result.dispatch_permitted is False


def test_all_order_queries_and_submit_receipt_share_scope_account_fingerprint(strategy_context):
    decision, strategy = _strategy(strategy_context, "T01")
    events = _complete_observations(decision, "T01")
    events = [
        _replace_event_fields(event, account_identity_sha256="e" * 64)
        if event.kind is decision.ObservationKind.POSITION_QUERY
        and event.fields.get("phase") == "final"
        and event.fields.get("query_family") == "funds"
        else event
        for event in events
    ]
    _feed(strategy, events)

    result = strategy.evaluate(now_utc=EVALUATION_TIME)
    assert result.state.value == "INCOMPLETE"
    assert "account_identity_scope_mismatch" in result.missing_conditions


def test_raw_account_identifier_cannot_replace_scope_fingerprint(strategy_context):
    decision, strategy = _strategy(strategy_context, "T01", account_identity_sha256="")
    events = _complete_observations(decision, "T01")
    provider_order = next(
        event
        for event in events
        if event.kind is decision.ObservationKind.ORDER_ACCEPTED
    )
    events[events.index(provider_order)] = _replace_event_fields(
        provider_order, account_identity="arbitrary-account-name"
    )
    _feed(strategy, events)

    result = strategy.evaluate(now_utc=EVALUATION_TIME)
    assert result.state.value == "INCOMPLETE"
    assert "sealed_account_identity_fingerprint_required" in result.missing_conditions


def test_event_timeline_shifted_ten_years_into_past_is_incomplete(strategy_context):
    decision, strategy = _strategy(strategy_context, "T01")
    events = []
    for event in _complete_observations(decision, "T01"):
        shifted = datetime.fromisoformat(event.occurred_at_utc.replace("Z", "+00:00"))
        shifted -= timedelta(days=3650)
        events.append(replace(event, occurred_at_utc=shifted.isoformat().replace("+00:00", "Z")))
    _feed(strategy, events)

    result = strategy.evaluate(now_utc=EVALUATION_TIME)
    assert result.state.value == "INCOMPLETE"
    assert result.missing_conditions == ("evidence_outside_candidate_freshness_window",)


def test_order_candidate_requires_explicit_aware_utc_evaluation_clock(strategy_context):
    decision, strategy = _strategy(strategy_context, "T01")
    _feed(strategy, _complete_observations(decision, "T01"))

    with pytest.raises(
        importlib.import_module("common.read_only_case_strategy").ReadOnlyStrategyError,
        match="aware UTC datetime",
    ):
        strategy.evaluate(now_utc=datetime(2026, 9, 28, 9, 0))


def test_l01_trade_log_projects_complete_native_trade_facts(strategy_context):
    decision, strategy = _strategy(strategy_context, "L01")
    _feed(strategy, _complete_observations(decision, "L01"))

    completion = strategy._build_completion_evidence()
    trade_row = next(
        row for row in completion.scenario_evidence if row.event_kind == "trade_execution"
    )
    trade_fact = completion.trade_facts[0]
    assert trade_row.fields["instrument_id"] == trade_fact.instrument_id
    assert trade_row.fields["quantity"] == trade_fact.quantity
    assert trade_row.fields["direction"] == trade_fact.direction
    assert trade_row.fields["price"] == trade_fact.price


def test_l01_trade_log_field_mismatch_stays_incomplete(strategy_context):
    decision, strategy = _strategy(strategy_context, "L01")
    _feed(strategy, _complete_observations(decision, "L01"))

    completion = strategy._build_completion_evidence()
    trade_row = next(
        row for row in completion.scenario_evidence if row.event_kind == "trade_execution"
    )
    mismatched_fields = dict(trade_row.fields, quantity="999")
    mismatched_row = replace(trade_row, fields=mismatched_fields)
    evidence = replace(
        completion,
        scenario_evidence=tuple(
            mismatched_row if row is trade_row else row for row in completion.scenario_evidence
        ),
    )
    report = importlib.import_module("common.completion_invariants").evaluate_case_completion(
        evidence
    )

    assert report.status.value == "INCOMPLETE"
    assert "trade_event_fields_do_not_match_native_trade_fact" in report.contradictions


def test_final_funds_query_is_required_for_terminal_order_review(strategy_context):
    decision, strategy = _strategy(strategy_context, "T01")
    events = _complete_observations(decision, "T01")
    events = [
        event
        for event in events
        if not (
            event.kind is decision.ObservationKind.POSITION_QUERY
            and event.fields.get("phase") == "final"
            and event.fields.get("query_family") == "funds"
        )
    ]
    _feed(strategy, events)

    result = strategy.evaluate(now_utc=EVALUATION_TIME)
    assert result.state.value == "INCOMPLETE"
    assert "final_requires_one_order_position_and_funds_query" in result.missing_conditions


def test_cancel_request_without_provider_terminal_callback_stays_incomplete(strategy_context):
    decision, strategy = _strategy(strategy_context, "T01")
    events = [
        event
        for event in _complete_observations(decision, "T01")
        if event.kind is not decision.ObservationKind.ORDER_CANCELED
    ]
    _feed(strategy, events)

    result = strategy.evaluate(now_utc=EVALUATION_TIME)
    assert result.state.value == "INCOMPLETE"
    assert "open_order_case_requires_cancel_terminal:order-1" in result.missing_conditions


def test_close_case_requires_opposite_side_confirmed_closeable_position(strategy_context):
    decision, strategy = _strategy(strategy_context, "T02")
    events = _complete_observations(decision, "T02")
    baseline = next(
        event
        for event in events
        if event.kind is decision.ObservationKind.POSITION_QUERY
        and event.fields.get("phase") == "baseline"
        and event.fields.get("query_family") == "positions"
    )
    fields = dict(baseline.fields)
    fields["closeable_quantities_json"] = json.dumps({"rb2610": "0"})
    events[events.index(baseline)] = decision.NativeObservation(
        **{**baseline.__dict__, "fields": fields}
    )
    _feed(strategy, events)

    result = strategy.evaluate(now_utc=EVALUATION_TIME)
    assert result.state.value == "INCOMPLETE"
    assert (
        "close_submit_must_be_within_opposite_side_closeable_position" in result.missing_conditions
    )


def test_b01_needs_partial_fills_for_every_order_before_batch_cancel(strategy_context):
    decision, strategy = _strategy(strategy_context, "B01")
    events = _complete_observations(decision, "B01")
    events = [
        event
        for event in events
        if not (
            event.kind is decision.ObservationKind.ORDER_PARTIAL
            and event.fields.get("order_ref") == "order-2"
        )
    ]
    _feed(strategy, events)

    result = strategy.evaluate(now_utc=EVALUATION_TIME)
    assert result.state.value == "INCOMPLETE"
    assert "every_batch_partial_order_requires_partial_callback" in result.missing_conditions


def test_b02_fill_race_requires_trade_and_position_reconciliation(strategy_context):
    decision, strategy = _strategy(strategy_context, "B02")
    events = _complete_observations(decision, "B02")
    events = [
        event
        for event in events
        if not (
            event.kind is decision.ObservationKind.TRADE_EXECUTION
            and event.fields.get("order_ref") == "order-1"
        )
    ]
    _feed(strategy, events)

    result = strategy.evaluate(now_utc=EVALUATION_TIME)
    assert result.state.value == "INCOMPLETE"
    assert any("trade" in condition for condition in result.missing_conditions)


def test_explicit_external_unavailability_does_not_become_pass(strategy_context):
    decision, strategy = _strategy(strategy_context, "T02")
    event = _envelope(
        decision,
        "T02",
        "EXTERNAL_CONDITION",
        1,
        0,
        {
            "condition_id": "closeable_position_confirmed",
            "state": "unavailable",
            "evidence_ref": "control-plane-evidence-1",
            "reason": "provider account has no closeable position",
        },
        stream="control-plane",
    )
    assert strategy.on_envelope(event)

    result = strategy.evaluate(now_utc=EVALUATION_TIME)
    assert result.state.value == "EXTERNAL_CONDITION_UNAVAILABLE"
    assert result.certification_pass is False
    assert result.dispatch_permitted is False
    assert result.unavailable_conditions == (
        "closeable_position_confirmed:provider account has no closeable position",
    )
