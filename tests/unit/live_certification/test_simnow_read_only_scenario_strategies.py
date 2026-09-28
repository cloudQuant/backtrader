"""Offline typed-state contracts for selected 007 SimNow strategy bindings.

The test authenticator is synthetic and only checks the decision interface.
None of these events is real provider, account-control, or certification evidence.
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
CASE_IDS = ("V01", "V02", "V03", "E01", "E02", "E03", "EM01", "EM02", "EM03", "L04")
NOW = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def scenario_context():
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
        decision_module = importlib.import_module("common.decision_engine")
        case_engine = importlib.import_module("common.case_engine")
        strategies = {}
        for case_id in CASE_IDS:
            path = CASES_ROOT / case_id / f"{case_id}_strategy.py"
            spec = importlib.util.spec_from_file_location(
                f"_simnow_{case_id.lower()}_readonly_strategy_test", path
            )
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            strategies[case_id] = module
        yield decision_module, case_engine, strategies
    finally:
        for name in list(sys.modules):
            if name == "common" or name.startswith("common."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
        sys.path[:] = previous_path


class SyntheticContractAuthenticator:
    """Test-only receipt generator; it does not verify a real source."""

    def __init__(self, decision_module):
        self.module = decision_module

    def authenticate(self, observation, scope):
        return self.module.AuthenticationReceipt(
            event_id=observation.event_id,
            evidence_sha256=observation.evidence_sha256,
            scope_sha256=scope.scope_sha256,
            trust_domain=observation.source_domain,
            verification_ref="synthetic-contract-test-only",
        )


def _engine(context, case_id, *, authenticated=True):
    decision_module, case_engine, strategies = context
    source = CASES_ROOT / case_id / f"{case_id}_strategy.py"
    plan = case_engine.load_descriptive_case_plan(source, expected_case_id=case_id)
    scope = decision_module.DecisionScope.for_plan(plan, "f" * 64)
    strategy_type = getattr(strategies[case_id], f"{case_id}ReadOnlyStrategy")
    authenticator = SyntheticContractAuthenticator(decision_module) if authenticated else None
    return decision_module, strategy_type(plan, scope, authenticator)


def _event(decision_module, kind_name, sequence, fields, *, stream="source", occurred_at=NOW):
    kind = decision_module.ObservationKind[kind_name]
    domain, callback, _ = decision_module._POLICY[kind]
    is_provider = domain is decision_module.EvidenceTrustDomain.CTP_CALLBACK
    return decision_module.NativeObservation(
        kind=kind,
        source_domain=domain,
        event_id=f"synthetic-{kind_name}-{sequence}-{stream}",
        evidence_sha256=f"{sequence:064x}",
        occurred_at_utc=occurred_at.isoformat().replace("+00:00", "Z"),
        sequence=sequence,
        stream_id=stream,
        callback_name=callback,
        provider_session_id="synthetic-session" if is_provider else "",
        trading_day="20260928" if is_provider else "",
        fields=fields,
    )


def _record(decision_module, strategy, kind, sequence, fields, **kwargs):
    assert strategy.record(_event(decision_module, kind, sequence, fields, **kwargs))


def test_all_selected_bindings_keep_static_plan_and_default_blocked(scenario_context):
    decision_module, _, strategies = scenario_context

    for case_id in CASE_IDS:
        strategy_module = strategies[case_id]
        assert case_id == strategy_module.CASE_ID
        assert hasattr(strategy_module, "CASE_PLAN") or hasattr(strategy_module, "PLAN")
        module, strategy = _engine(scenario_context, case_id, authenticated=False)
        snapshot = strategy.evaluate(now_utc=NOW)
        assert snapshot.case_id == case_id
        assert snapshot.status is module.DecisionStatus.BLOCKED
        assert snapshot.certification_pass is False
        assert snapshot.dispatch_permitted is False
        assert snapshot.intent_candidate is None
        assert not any(hasattr(strategy, name) for name in ("submit", "cancel", "dispatch"))

    assert "bt_api_ctp" not in sys.modules


def test_local_validation_cases_require_local_validator_and_zero_dispatch(scenario_context):
    module, strategy = _engine(scenario_context, "V01")
    _record(
        module,
        strategy,
        "VALIDATION_REJECTION",
        1,
        {
            "order_ref": "local-v01",
            "rule": "instrument",
            "error_message": "instrument lookup miss",
            "validator_digest": "a" * 64,
            "reference_data_digest": "b" * 64,
            "instrument_id": "invalid-test-id",
            "instrument_lookup_found": False,
        },
    )
    _record(
        module,
        strategy,
        "DISPATCH_ABSENCE",
        1,
        {"order_ref": "local-v01", "dispatch_count": 0, "audit_digest": "c" * 64},
        stream="managed",
    )

    snapshot = strategy.evaluate(now_utc=NOW)
    assert snapshot.status is module.DecisionStatus.REVIEW_REQUIRED
    assert snapshot.intent_candidate is not None
    assert snapshot.intent_candidate.dispatch_permitted is False
    assert snapshot.certification_pass is False
    assert module._POLICY[module.ObservationKind.VALIDATION_REJECTION][0] is (
        module.EvidenceTrustDomain.LOCAL_VALIDATOR
    )
    assert module._POLICY[module.ObservationKind.ORDER_REJECTED][0] is (
        module.EvidenceTrustDomain.CTP_CALLBACK
    )

    wrong_origin = replace(
        _event(
            module,
            "VALIDATION_REJECTION",
            2,
            {
                "order_ref": "bad-origin",
                "rule": "instrument",
                "error_message": "claimed provider reject",
                "validator_digest": "d" * 64,
                "reference_data_digest": "e" * 64,
                "instrument_id": "invalid-test-id",
                "instrument_lookup_found": False,
            },
        ),
        source_domain=module.EvidenceTrustDomain.CTP_CALLBACK,
        callback_name="OnRspOrderInsert",
    )
    with pytest.raises(module.DecisionError, match="incorrect source domain/callback"):
        strategy.record(wrong_origin)


@pytest.mark.parametrize(
    ("case_id", "condition_id"),
    (
        ("E01", "insufficient_funds"),
        ("E02", "insufficient_position"),
        ("E03", "market_state"),
    ),
)
def test_remote_rejection_cases_require_external_condition_and_provider_error_id(
    scenario_context, case_id, condition_id
):
    module, strategy = _engine(scenario_context, case_id)
    _record(
        module,
        strategy,
        "EXTERNAL_CONDITION",
        1,
        {
            "condition_id": condition_id,
            "state": "unavailable",
            "evidence_ref": "synthetic-test-only-unavailable",
            "reason": "no real external condition evidence supplied",
        },
        stream="control",
    )
    snapshot = strategy.evaluate(now_utc=NOW)
    assert snapshot.status is module.DecisionStatus.EXTERNAL_CONDITION_UNAVAILABLE
    assert snapshot.external_unavailability
    assert snapshot.intent_candidate is None
    assert snapshot.certification_pass is False
    assert snapshot.dispatch_permitted is False

    local = _event(
        module,
        "VALIDATION_REJECTION",
        1,
        {
            "order_ref": "local-only",
            "rule": "instrument",
            "error_message": "local validator result",
            "validator_digest": "a" * 64,
            "reference_data_digest": "b" * 64,
        },
        stream="validator",
    )
    with pytest.raises(module.DecisionError, match="not required by case"):
        strategy.record(local)

    wrong_error_id = replace(
        _event(
            module,
            "ORDER_REJECTED",
            1,
            {
                "order_ref": "provider-reject",
                "instrument_id": "rb2710",
                "error_id": 0,
                "error_message": "zero is not a remote rejection",
                "rejection_class": condition_id,
            },
        ),
        sequence=2,
    )
    with pytest.raises(module.DecisionError, match="positive provider error id"):
        strategy.record(wrong_error_id)


@pytest.mark.parametrize(
    ("case_id", "required_kinds", "control_kinds"),
    (
        (
            "EM01",
            {
                "LOGIN_SUCCESS",
                "FRONT_CONNECTED",
                "MARKET_TICK",
                "ORDER_ADMISSION",
                "ACCOUNT_PERMISSION_DISABLED",
                "ORDER_SUBMIT_RECEIPT",
                "ORDER_REJECTED",
                "ACCOUNT_PERMISSION_RESTORED",
                "ORDER_QUERY",
            },
            {"ACCOUNT_PERMISSION_DISABLED", "ACCOUNT_PERMISSION_RESTORED"},
        ),
        (
            "EM02",
            {"STRATEGY_PAUSED", "ORDER_QUERY"},
            {"STRATEGY_PAUSED"},
        ),
        (
            "EM03",
            {
                "GATEWAY_LOGOUT_AUTHORIZED",
                "FRONT_DISCONNECTED",
                "POST_DISCONNECT_WRITE_BLOCKED",
            },
            {"GATEWAY_LOGOUT_AUTHORIZED"},
        ),
    ),
)
def test_emergency_cases_block_without_real_control_plane_evidence(
    scenario_context, case_id, required_kinds, control_kinds
):
    module, strategy = _engine(scenario_context, case_id, authenticated=False)
    snapshot = strategy.evaluate(now_utc=NOW)
    assert snapshot.status is module.DecisionStatus.BLOCKED
    assert {kind.name for kind in strategy.spec.required_kinds} == required_kinds
    assert snapshot.intent_candidate is None
    assert snapshot.certification_pass is False
    assert snapshot.dispatch_permitted is False
    for kind_name in control_kinds:
        assert module._POLICY[module.ObservationKind[kind_name]][0] is (
            module.EvidenceTrustDomain.CONTROL_PLANE
        )


def test_v02_v03_and_l04_keep_tick_size_admission_and_log_source_typed(scenario_context):
    module, v02 = _engine(scenario_context, "V02")
    _record(
        module,
        v02,
        "MARKET_TICK",
        1,
        {"instrument_id": "rb2710", "bid": "100", "ask": "101", "last": "100.5", "price_tick": "1"},
        occurred_at=NOW - timedelta(seconds=1),
    )
    _record(
        module,
        v02,
        "VALIDATION_REJECTION",
        1,
        {
            "order_ref": "local-v02",
            "rule": "price_tick",
            "error_message": "price does not align to tick",
            "validator_digest": "a" * 64,
            "reference_data_digest": "b" * 64,
            "proposed_price": "100.5",
        },
        stream="validator",
    )
    _record(
        module,
        v02,
        "DISPATCH_ABSENCE",
        1,
        {"order_ref": "local-v02", "dispatch_count": 0, "audit_digest": "c" * 64},
        stream="managed",
    )
    result = v02.evaluate(now_utc=NOW)
    assert result.status is module.DecisionStatus.REVIEW_REQUIRED
    assert result.certification_pass is False

    module, v03 = _engine(scenario_context, "V03")
    _record(
        module,
        v03,
        "ORDER_ADMISSION",
        1,
        {
            "case_id": "V03",
            "intent_kind": "validation",
            "approval_ref": "synthetic-review-only",
            "approval_state": "REVIEW_ONLY",
            "dispatch_permitted": False,
            "maximum_quantity": 1,
            "maximum_order_size": "5",
        },
        stream="managed",
    )
    _record(
        module,
        v03,
        "VALIDATION_REJECTION",
        1,
        {
            "order_ref": "local-v03",
            "rule": "max_order_size",
            "error_message": "request exceeds local maximum",
            "validator_digest": "d" * 64,
            "reference_data_digest": "e" * 64,
            "requested_size": "6",
            "maximum_order_size": "5",
        },
        stream="validator",
    )
    _record(
        module,
        v03,
        "DISPATCH_ABSENCE",
        2,
        {"order_ref": "local-v03", "dispatch_count": 0, "audit_digest": "f" * 64},
        stream="managed",
    )
    result = v03.evaluate(now_utc=NOW)
    assert result.status is module.DecisionStatus.REVIEW_REQUIRED
    assert result.certification_pass is False

    module, l04 = _engine(scenario_context, "L04")
    _record(
        module,
        l04,
        "VALIDATION_REJECTION",
        1,
        {
            "order_ref": "local-log-v04",
            "rule": "price_tick",
            "error_message": "local price-step validation failed",
            "validator_digest": "1" * 64,
            "reference_data_digest": "2" * 64,
            "trace_id": "synthetic-local-error-log",
            "error_code": "LOCAL_PRICE_STEP",
        },
        stream="validator",
    )
    _record(
        module,
        l04,
        "DISPATCH_ABSENCE",
        1,
        {"order_ref": "local-log-v04", "dispatch_count": 0, "audit_digest": "3" * 64},
        stream="managed",
    )
    result = l04.evaluate(now_utc=NOW)
    assert result.status is module.DecisionStatus.REVIEW_REQUIRED
    assert result.certification_pass is False
    assert module._POLICY[module.ObservationKind.VALIDATION_REJECTION][0] is (
        module.EvidenceTrustDomain.LOCAL_VALIDATOR
    )
