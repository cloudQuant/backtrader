"""Offline contracts for the first six unregistered read-only case strategies.

The synthetic authenticator below exercises the interface only. These tests
prove that absent or malformed evidence cannot advance the candidates; they do
not prove real provider behavior, source authenticity, or certification PASS.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITE_ROOT = REPO_ROOT / "examples" / "007_ctp" / "live_certification" / "simnow_penetration"
CASES_ROOT = SUITE_ROOT / "cases"
CASE_IDS = ("C01", "M01", "L02", "TH01", "TH03", "TH05")
BASE_TIME = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)
SCOPE_SHA256 = "f" * 64


@pytest.fixture
def strategy_modules():
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
            spec = importlib.util.spec_from_file_location(f"strategy_{case_id}", path)
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
    """Synthetic interface probe; never evidence of real provider behavior."""

    def __init__(self, decision):
        self.decision = decision

    def authenticate(self, observation, scope):
        return self.decision.AuthenticationReceipt(
            event_id=observation.event_id,
            evidence_sha256=observation.evidence_sha256,
            scope_sha256=scope.scope_sha256,
            trust_domain=observation.source_domain,
            verification_ref="test-only-contract-authenticator",
        )


def _strategy(strategy_modules, case_id, authenticator=True):
    case_engine, decision, strategies = strategy_modules
    source = CASES_ROOT / case_id / f"{case_id}_strategy.py"
    plan = case_engine.load_descriptive_case_plan(source, expected_case_id=case_id)
    scope = decision.DecisionScope.for_plan(plan, SCOPE_SHA256)
    verifier = ContractAuthenticator(decision) if authenticator else None
    strategy = strategies[case_id].create_strategy(plan, scope, verifier)
    return decision, strategy


def _observation(
    decision,
    case_id,
    kind,
    sequence,
    offset_seconds,
    fields,
    *,
    stream="provider",
    session="provider-session-1",
    trading_day="20260928",
    callback=None,
    domain=None,
):
    kind_value = decision.ObservationKind[kind]
    if domain is None:
        domain = {
            "AUTH_SUCCESS": decision.EvidenceTrustDomain.CTP_CALLBACK,
            "LOGIN_SUCCESS": decision.EvidenceTrustDomain.CTP_CALLBACK,
            "FRONT_CONNECTED": decision.EvidenceTrustDomain.CTP_CALLBACK,
            "MARKET_SUBSCRIPTION_ACK": decision.EvidenceTrustDomain.CTP_CALLBACK,
            "MARKET_TICK": decision.EvidenceTrustDomain.CTP_CALLBACK,
            "SYSTEM_LOG": decision.EvidenceTrustDomain.MANAGED_RUNTIME,
            "MONITOR_CONFIGURATION": decision.EvidenceTrustDomain.MONITOR,
            "MONITOR_LOG": decision.EvidenceTrustDomain.MONITOR,
        }[kind]
    callbacks = {
        "AUTH_SUCCESS": "OnRspAuthenticate",
        "LOGIN_SUCCESS": "OnRspUserLogin",
        "FRONT_CONNECTED": "OnFrontConnected",
        "MARKET_SUBSCRIPTION_ACK": "OnRspSubMarketData",
        "MARKET_TICK": "OnRtnDepthMarketData",
        "SYSTEM_LOG": "",
        "MONITOR_CONFIGURATION": "",
        "MONITOR_LOG": "",
    }
    if callback is None:
        callback = callbacks[kind]
    is_provider = domain is decision.EvidenceTrustDomain.CTP_CALLBACK
    when = BASE_TIME + timedelta(seconds=offset_seconds)
    observation_fields = dict(fields)
    c01_auth_login = case_id == "C01" and kind in {"AUTH_SUCCESS", "LOGIN_SUCCESS"}
    payloadless_front = kind == "FRONT_CONNECTED"
    c01_session = (
        "17"
        if case_id == "C01" and kind == "LOGIN_SUCCESS" and session == "provider-session-1"
        else session
    )
    if payloadless_front:
        observation_fields.setdefault("connection_generation", 1)
    if c01_auth_login:
        observation_fields.setdefault("request_id", 100 + sequence)
        observation_fields.setdefault("request_generation", 1000 + sequence)
        observation_fields.setdefault("arrival_generation", 1)
        observation_fields.setdefault("is_last", True)
        observation_fields.setdefault("error_id", 0)
        observation_fields.setdefault("success", True)
        if kind == "LOGIN_SUCCESS":
            observation_fields.setdefault("provider_front_id", 3)
            observation_fields.setdefault("provider_session_id", c01_session)
            observation_fields.setdefault("trading_day", trading_day)
    return decision.NativeObservation(
        kind=kind_value,
        source_domain=domain,
        event_id=f"{case_id}-{kind}-{sequence}-{stream}",
        evidence_sha256=f"{sequence:064x}",
        occurred_at_utc=when.isoformat().replace("+00:00", "Z"),
        sequence=sequence,
        stream_id=stream,
        callback_name=callback,
        provider_session_id=(
            c01_session
            if is_provider and kind not in {"AUTH_SUCCESS", "FRONT_CONNECTED"}
            else ""
        ),
        trading_day=(
            trading_day
            if is_provider and kind not in {"AUTH_SUCCESS", "FRONT_CONNECTED"}
            else ""
        ),
        fields=observation_fields,
        provider_front_id=(3 if c01_auth_login and kind == "LOGIN_SUCCESS" else None),
        client_instance_id=("ctp-client-1" if c01_auth_login or payloadless_front else ""),
        request_generation=(1000 + sequence if c01_auth_login else 0),
        request_id_origin=("native_callback_argument" if c01_auth_login else ""),
        request_generation_origin=(
            "local_request_generation_binding" if c01_auth_login else ""
        ),
        arrival_generation=(1 if c01_auth_login or payloadless_front else 0),
        session_identity_origin=(
            "unavailable_on_native_authentication_response"
            if c01_auth_login and kind == "AUTH_SUCCESS"
            else "native_login_response_fields"
            if c01_auth_login
            else ""
        ),
        arrived_at_utc=(when.isoformat().replace("+00:00", "Z") if c01_auth_login else ""),
        arrived_monotonic=(when.timestamp() if c01_auth_login else 0.0),
        sequence_origin=("local_sdk_callback_arrival" if c01_auth_login else ""),
        timestamp_origin=("local_sdk_capture_clock" if c01_auth_login else ""),
        event_id_origin=("local_sdk_callback_arrival" if c01_auth_login else ""),
        connection_generation_origin=(
            "local_connection_generation" if payloadless_front else ""
        ),
        provider_issued_event_id=False,
    )


def _system_event(decision, case_id, event_name, sequence, offset_seconds, **extra):
    return _observation(
        decision,
        case_id,
        "SYSTEM_LOG",
        sequence,
        offset_seconds,
        {
            "trace_id": f"trace-{case_id}-{event_name}",
            "gateway_key": "gateway-1",
            "log_digest": f"{sequence:064x}",
            "event_name": event_name,
            "session_id": "runtime-session-1" if case_id == "C01" else "provider-session-1",
            **extra,
        },
        stream="runtime",
    )


def _complete_observations(decision, case_id):
    events = []
    if case_id == "C01":
        events.extend(
            [
                _observation(
                    decision,
                    case_id,
                    "AUTH_SUCCESS",
                    1,
                    0,
                    {"success": True, "error_id": 0},
                ),
                _observation(
                    decision,
                    case_id,
                    "LOGIN_SUCCESS",
                    2,
                    60,
                    {"success": True, "error_id": 0},
                ),
            ]
        )
        events.extend(
            [
                _system_event(
                    decision,
                    case_id,
                    "store_auth_success",
                    1,
                    10,
                    callback_event_id="C01-AUTH_SUCCESS-1-provider",
                    callback_received_at_utc=BASE_TIME.isoformat().replace("+00:00", "Z"),
                    client_instance_id="ctp-client-1",
                    arrival_generation=1,
                    provider_issued_event_id=False,
                ),
                _system_event(
                    decision,
                    case_id,
                    "store_login_success",
                    2,
                    70,
                    callback_event_id="C01-LOGIN_SUCCESS-2-provider",
                    callback_received_at_utc=(BASE_TIME + timedelta(seconds=60))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    client_instance_id="ctp-client-1",
                    arrival_generation=1,
                    trading_day="20260928",
                    provider_front_id=3,
                    provider_session_id="17",
                    provider_issued_event_id=False,
                ),
            ]
        )
    else:
        events.extend(
            [
                _observation(
                    decision,
                    case_id,
                    "FRONT_CONNECTED",
                    1,
                    0,
                    {"gateway_key": "gateway-1"},
                ),
                _observation(
                    decision,
                    case_id,
                    "LOGIN_SUCCESS",
                    2,
                    60,
                    {"success": True, "error_id": 0},
                ),
                _observation(
                    decision,
                    case_id,
                    "MARKET_SUBSCRIPTION_ACK",
                    3,
                    120,
                    {"success": True, "instrument_id": "rb2610"},
                ),
            ]
        )

    is_logged_case = case_id in {"L02", "TH01", "TH03", "TH05"}
    if is_logged_case:
        events.append(
            _system_event(
                decision,
                case_id,
                "session_started",
                1,
                -60,
                **({"process_id": "process-1"} if case_id == "L02" else {}),
            )
        )
    monitor_case = case_id in {"TH01", "TH03", "TH05"}
    if monitor_case:
        events.append(
            _observation(
                decision,
                case_id,
                "MARKET_TICK",
                4,
                150,
                {
                    "instrument_id": "rb2610",
                    "bid": "3500",
                    "ask": "3501",
                    "last": "3500.5",
                    "price_tick": "1",
                },
            )
        )
        spec = importlib.import_module("common.read_only_case_strategy").READ_ONLY_CASE_SPECS[
            case_id
        ]
        config_fields = {
            "metric": spec.expected_metric,
            "threshold": spec.expected_threshold,
            "configuration_digest": "a" * 64,
            "monitor_digest": "b" * 64,
        }
        if case_id == "TH05":
            config_fields["window_seconds"] = "60"
        events.extend(
            [
                _observation(
                    decision,
                    case_id,
                    "MONITOR_CONFIGURATION",
                    1,
                    -40,
                    config_fields,
                    stream="monitor",
                ),
                _observation(
                    decision,
                    case_id,
                    "MONITOR_LOG",
                    2,
                    -39,
                    {
                        "trace_id": f"trace-{case_id}-threshold",
                        "metric": spec.expected_metric,
                        "monitor_digest": "b" * 64,
                        "event_name": "risk_threshold_configured",
                        "threshold": spec.expected_threshold,
                        "configuration_digest": "a" * 64,
                        **({"window_seconds": "60"} if case_id == "TH05" else {}),
                    },
                    stream="monitor",
                ),
            ]
        )

    runtime_sequence = 2 if case_id == "C01" else (1 if is_logged_case else 0)
    if case_id in {"M01", "L02", "TH01", "TH03", "TH05"}:
        runtime_sequence += 1
        events.append(
            _system_event(
                decision,
                case_id,
                "store_connected",
                runtime_sequence,
                180,
                market_connection=True,
                trade_connection=True,
            )
        )
    if case_id in {"M01", "L02", "TH01", "TH03", "TH05"}:
        runtime_sequence += 1
        events.append(
            _system_event(
                decision,
                case_id,
                "store_ready",
                runtime_sequence,
                190,
                market_connection=True,
                trade_connection=True,
            )
        )
    runtime_sequence += 1
    events.append(
        _system_event(
            decision,
            case_id,
            "session_stopped",
            runtime_sequence,
            240,
            clean_shutdown=True,
            gateway_released=True,
            exit_code=0,
            **({"process_id": "process-1"} if case_id == "L02" else {}),
        )
    )
    runtime_sequence += 1
    events.append(
        _system_event(
            decision,
            case_id,
            "write_activity_summary",
            runtime_sequence,
            300,
            snapshot_complete=True,
            snapshot_digest="c" * 64,
            order_submit_count=0,
            order_cancel_count=0,
            broker_write_count=0,
        )
    )
    return events


def _feed(strategy, events):
    for event in events:
        assert strategy.on_envelope(event)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_complete_typed_read_only_plan_stops_at_review_required(strategy_modules, case_id):
    decision, strategy = _strategy(strategy_modules, case_id)
    _feed(strategy, _complete_observations(decision, case_id))

    result = strategy.evaluate()
    assert result.case_id == case_id
    expected_state = (
        importlib.import_module("common.read_only_case_strategy").ReadOnlyState.INCOMPLETE
        if case_id == "C01"
        else importlib.import_module("common.read_only_case_strategy").ReadOnlyState.REVIEW_REQUIRED
    )
    assert result.state is expected_state
    if case_id == "C01":
        assert "trusted_c01_issued_request_ledger_verifier_required" in result.missing_conditions
        assert "c01_requires_baseline_and_final_native_order_position_account_queries" in result.missing_conditions
    assert result.certification_pass is False
    assert result.dispatch_permitted is False
    assert result.source_authenticity_verified is False
    if case_id == "C01":
        assert result.missing_conditions
    else:
        assert not result.missing_conditions


def test_no_authenticator_rejects_callback_strings_and_stays_blocked(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "C01", authenticator=False)
    event = _observation(decision, "C01", "AUTH_SUCCESS", 1, 0, {"success": True, "error_id": 0})

    assert strategy.on_envelope(event) is False
    result = strategy.evaluate()
    assert result.state.value == "BLOCKED"
    assert result.certification_pass is False
    assert result.dispatch_permitted is False
    assert result.source_authenticity_verified is False
    assert result.evidence_event_ids == ()
    assert result.rejected_events == (
        "C01-AUTH_SUCCESS-1-provider:trusted_authenticator_unavailable",
    )


def test_missing_clean_shutdown_and_zero_write_snapshot_is_incomplete(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "M01")
    events = [
        event
        for event in _complete_observations(decision, "M01")
        if event.fields.get("event_name") != "write_activity_summary"
    ]
    _feed(strategy, events)

    result = strategy.evaluate()
    assert result.state.value == "INCOMPLETE"
    assert "system_log:write_activity_summary" in result.missing_conditions
    assert result.certification_pass is False


def test_nonzero_write_counter_cannot_complete_read_only_case(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "C01")
    events = _complete_observations(decision, "C01")
    summary = next(
        event
        for event in events
        if event.kind is decision.ObservationKind.SYSTEM_LOG
        and event.fields["event_name"] == "write_activity_summary"
    )
    altered = dict(summary.fields)
    altered["order_submit_count"] = 1
    events[events.index(summary)] = decision.NativeObservation(
        **{**summary.__dict__, "fields": altered}
    )
    _feed(strategy, events)

    result = strategy.evaluate()
    assert result.state.value == "INCOMPLETE"
    assert (
        "complete_zero_order_cancel_and_broker_write_summary_required" in result.missing_conditions
    )


def test_c01_log_must_correlate_to_native_authentication_callback(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "C01")
    events = _complete_observations(decision, "C01")
    auth_log = next(
        event
        for event in events
        if event.kind is decision.ObservationKind.SYSTEM_LOG
        and event.fields["event_name"] == "store_auth_success"
    )
    altered = dict(auth_log.fields)
    altered["callback_event_id"] = "unrelated-local-event"
    events[events.index(auth_log)] = decision.NativeObservation(
        **{**auth_log.__dict__, "fields": altered}
    )
    _feed(strategy, events)

    result = strategy.evaluate()
    assert result.state.value == "INCOMPLETE"
    assert "authentication_log_must_reference_native_callback" in result.missing_conditions


@pytest.mark.parametrize(
    "forged_field",
    (
        "local_session_id",
        "local_front_id",
        "local_provider_session_id",
        "local_trading_day",
        "local_account_identity_sha256",
    ),
)
def test_c01_read_only_auth_rejects_unbound_local_identity_aliases(
    strategy_modules, forged_field
):
    decision, strategy = _strategy(strategy_modules, "C01")
    event = _observation(
        decision,
        "C01",
        "AUTH_SUCCESS",
        1,
        0,
        {"success": True, "error_id": 0, forged_field: "forged-identity"},
    )
    readonly_module = importlib.import_module("common.read_only_case_strategy")

    with pytest.raises(readonly_module.ReadOnlyStrategyError):
        strategy.on_envelope(event)
    assert strategy.evaluate().state is readonly_module.ReadOnlyState.BLOCKED


def test_accepted_callback_fields_are_snapshotted(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "C01")
    events = _complete_observations(decision, "C01")
    auth = events.pop(0)
    assert strategy.on_envelope(auth)
    auth.fields["success"] = False
    _feed(strategy, events)

    result = strategy.evaluate()
    assert result.state.value == "INCOMPLETE"


def test_market_tick_must_be_typed_and_use_positive_tick_size(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "TH01")
    event = _observation(
        decision,
        "TH01",
        "MARKET_TICK",
        1,
        0,
        {
            "instrument_id": "rb2610",
            "bid": "10",
            "ask": "11",
            "last": "10.5",
            "price_tick": "0",
        },
    )

    with pytest.raises(
        importlib.import_module("common.read_only_case_strategy").ReadOnlyStrategyError
    ):
        strategy.on_envelope(event)


def test_local_event_name_with_wrong_trust_domain_is_rejected(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "C01")
    event = _observation(
        decision,
        "C01",
        "AUTH_SUCCESS",
        1,
        0,
        {"success": True, "error_id": 0},
        domain=decision.EvidenceTrustDomain.LOCAL_VALIDATOR,
        callback="OnRspAuthenticate",
    )

    with pytest.raises(
        importlib.import_module("common.read_only_case_strategy").ReadOnlyStrategyError
    ):
        strategy.on_envelope(event)


def test_authentication_is_unscoped_and_login_identity_is_native(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "C01")
    auth = _observation(decision, "C01", "AUTH_SUCCESS", 1, 0, {"success": True, "error_id": 0})
    login = _observation(
        decision,
        "C01",
        "LOGIN_SUCCESS",
        2,
        60,
        {"success": True, "error_id": 0},
        session="18",
    )
    assert strategy.on_envelope(auth)
    assert auth.provider_front_id is None
    assert auth.provider_session_id == ""
    assert auth.trading_day == ""
    assert strategy.on_envelope(login)
    assert login.provider_session_id == "18"
    assert login.provider_front_id == 3


def test_c01_missing_login_does_not_complete(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "C01")
    auth = _observation(decision, "C01", "AUTH_SUCCESS", 1, 0, {"success": True, "error_id": 0})
    strategy.on_envelope(auth)
    result = strategy.evaluate(now_utc=BASE_TIME + timedelta(seconds=120))
    assert result.state.value == "INCOMPLETE"
    assert decision.ObservationKind.LOGIN_SUCCESS.value in result.missing_conditions


def test_c01_disconnect_generation_change_between_auth_and_login_fails(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "C01")
    events = _complete_observations(decision, "C01")
    login = next(event for event in events if event.kind is decision.ObservationKind.LOGIN_SUCCESS)
    login_fields = {**login.fields, "arrival_generation": 2}
    login = decision.NativeObservation(
        **{**login.__dict__, "arrival_generation": 2, "fields": login_fields}
    )
    events[events.index(next(event for event in events if event.kind is decision.ObservationKind.LOGIN_SUCCESS))] = login
    _feed(strategy, events)
    result = strategy.evaluate(now_utc=BASE_TIME + timedelta(seconds=120))
    assert result.state.value == "INCOMPLETE"
    assert "authentication_and_login_must_share_connection_generation" in result.missing_conditions


def test_c01_rejects_legacy_auth_provider_identity_and_time_claims(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "C01")
    auth = _observation(decision, "C01", "AUTH_SUCCESS", 1, 0, {"success": True, "error_id": 0})
    legacy = decision.NativeObservation(
        **{
            **auth.__dict__,
            "provider_session_id": "17",
            "trading_day": "20260928",
            "provider_front_id": 3,
        }
    )
    with pytest.raises(
        importlib.import_module("common.read_only_case_strategy").ReadOnlyStrategyError,
        match="cannot claim provider front/session/day/time/sequence",
    ):
        strategy.on_envelope(legacy)


def test_system_connection_requires_both_native_fronts_and_is_unique(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "L02")
    events = _complete_observations(decision, "L02")
    connected = next(
        event
        for event in events
        if event.kind is decision.ObservationKind.SYSTEM_LOG
        and event.fields["event_name"] == "store_connected"
    )
    altered = dict(connected.fields)
    altered["trade_connection"] = False
    events[events.index(connected)] = decision.NativeObservation(
        **{**connected.__dict__, "fields": altered}
    )
    _feed(strategy, events)

    result = strategy.evaluate()
    assert result.state.value == "INCOMPLETE"
    assert "store_connected_log_must_confirm_both_provider_fronts" in result.missing_conditions


@pytest.mark.parametrize(
    "case_id,field,value,condition",
    [
        ("TH01", "threshold", 6, "runtime_threshold_does_not_match_case_plan"),
        ("TH03", "monitor_digest", "d" * 64, "matching_timestamped_monitor_log_required"),
        ("TH05", "window_seconds", "0", "positive_repeat_window_required"),
    ],
)
def test_monitor_threshold_or_window_must_match_managed_plan(
    strategy_modules, case_id, field, value, condition
):
    decision, strategy = _strategy(strategy_modules, case_id)
    events = _complete_observations(decision, case_id)
    config = next(event for event in events if event.kind.value == "monitor_configuration")
    altered = dict(config.fields)
    altered[field] = value
    events[events.index(config)] = decision.NativeObservation(
        **{**config.__dict__, "fields": altered}
    )
    _feed(strategy, events)

    result = strategy.evaluate()
    assert result.state.value == "INCOMPLETE"
    assert condition in result.missing_conditions
    assert result.certification_pass is False
    assert result.dispatch_permitted is False


def test_c01_duplicate_native_request_id_cannot_reach_review(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "C01")
    events = _complete_observations(decision, "C01")
    auth = next(event for event in events if event.kind is decision.ObservationKind.AUTH_SUCCESS)
    login = next(event for event in events if event.kind is decision.ObservationKind.LOGIN_SUCCESS)
    login_fields = {**login.fields, "request_id": auth.fields["request_id"]}
    events[events.index(login)] = decision.NativeObservation(
        **{**login.__dict__, "fields": login_fields}
    )
    _feed(strategy, events)
    result = strategy.evaluate()
    assert result.state.value == "INCOMPLETE"
    assert "authentication_and_login_native_request_ids_must_differ" in result.missing_conditions


def test_public_factory_rejects_caller_issued_request_verifier(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "C01")
    common_strategy = importlib.import_module("common.read_only_case_strategy")

    class AlwaysTrueVerifier:
        def verify(self, receipt, event, scope):
            return True

    with pytest.raises(TypeError, match="unexpected keyword argument 'request_ledger_verifier'"):
        common_strategy.create_read_only_strategy(
            "C01",
            strategy.plan,
            strategy.scope,
            ContractAuthenticator(decision),
            request_ledger_verifier=AlwaysTrueVerifier(),
        )

    _feed(strategy, _complete_observations(decision, "C01"))
    result = strategy.evaluate(now_utc=BASE_TIME + timedelta(seconds=120))
    assert result.state.value == "INCOMPLETE"
    assert "trusted_c01_issued_request_ledger_verifier_required" in result.missing_conditions
    assert result.certification_pass is False
    assert result.dispatch_permitted is False


def test_authentication_shape_is_sessionless_outside_c01(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "M01")
    event = _observation(
        decision, "M01", "AUTH_SUCCESS", 1, 0, {"success": True, "error_id": 0}
    )
    event = decision.NativeObservation(**{**event.__dict__, "provider_session_id": "17"})
    with pytest.raises(
        importlib.import_module("common.read_only_case_strategy").ReadOnlyStrategyError,
        match="OnRspAuthenticate cannot claim",
    ):
        strategy.on_envelope(event)


@pytest.mark.parametrize(
    "field, value",
    [
        ("provider_timestamp_utc", "2026-09-28T09:00:00Z"),
        ("provider_sequence", 12),
        ("provider_event_id", "native-login-event"),
    ],
)
def test_login_callback_cannot_claim_provider_time_sequence_or_event_id(
    strategy_modules, field, value
):
    decision, strategy = _strategy(strategy_modules, "C01")
    login = _observation(
        decision,
        "C01",
        "LOGIN_SUCCESS",
        2,
        1,
        {"success": True, "error_id": 0, "request_id": 102},
        session="17",
    )
    altered = decision.NativeObservation(
        **{**login.__dict__, "fields": {**login.fields, field: value}}
    )
    with pytest.raises(
        importlib.import_module("common.read_only_case_strategy").ReadOnlyStrategyError,
        match="auth/login callback cannot claim provider time, sequence, or event ID",
    ):
        strategy.on_envelope(altered)


def test_auth_receipt_must_match_native_request_id(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "C01")
    auth = _observation(
        decision,
        "C01",
        "AUTH_SUCCESS",
        1,
        0,
        {"success": True, "error_id": 0, "request_id": 101},
    )
    case_engine = importlib.import_module("common.case_engine")
    receipt = case_engine.IssuedRequestReceipt(
        request_kind="authenticate",
        phase="",
        request_id=999,
        request_generation=auth.request_generation,
        client_instance_id=auth.client_instance_id,
        arrival_generation=auth.arrival_generation,
        issued_at_utc=(BASE_TIME - timedelta(seconds=1)).isoformat(),
        issued_monotonic=auth.arrived_monotonic - 1,
        receipt_id="auth-issued-receipt-1",
        ledger_entry_sha256="a" * 64,
    )
    altered = decision.NativeObservation(**{**auth.__dict__, "issued_request_receipt": receipt})
    with pytest.raises(
        importlib.import_module("common.read_only_case_strategy").ReadOnlyStrategyError,
        match="C01 auth/login receipt does not match native callback",
    ):
        strategy.on_envelope(altered)


def test_front_connected_cannot_claim_login_identity(strategy_modules):
    decision, strategy = _strategy(strategy_modules, "M01")
    event = _observation(
        decision, "M01", "FRONT_CONNECTED", 1, 0, {"gateway_key": "gateway-1"}
    )
    event = decision.NativeObservation(
        **{**event.__dict__, "provider_session_id": "17", "trading_day": "20260928"}
    )
    with pytest.raises(
        importlib.import_module("common.read_only_case_strategy").ReadOnlyStrategyError,
        match="OnFrontConnected has no native provider",
    ):
        strategy.on_envelope(event)
