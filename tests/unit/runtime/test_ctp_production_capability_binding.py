"""Offline CTP production execution/risk/monitor scope binding contracts."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from backtrader_runtime.ctp_production_capability_binding import (
    CtpProductionCapabilityBinding,
    CtpProductionCapabilityBindingError,
    CtpProductionCapabilityPin,
    validate_ctp_production_capability_bundle_binding,
)
from backtrader_runtime.ctp_production_execution_admission import (
    CtpProductionExecutionConfigBinding,
)


def _scope(**overrides):
    values = {
        "runtime_id": "synthetic.ctp.production",
        "strategy_id": "example.synthetic.ctp.production",
        "config_digest": "1" * 64,
        "effective_digest": "2" * 64,
        "runtime_registration_digest": "3" * 64,
        "registration_digest": "4" * 64,
        "scope_identity_sha256": "5" * 64,
        "environment": "production",
        "md_front": "tcp://192.0.2.21:41211",
        "td_front": "tcp://192.0.2.20:41201",
        "instrument_id": "IF2612",
        "exchange_id": "CFFEX",
        "hedge_flag": "1",
        "account_binding_sha256": "6" * 64,
        "approval_receipt_id": "ctp-production:receipt.synthetic",
        "approval_receipt_sha256": "7" * 64,
        "artifact_id": "ctp-production:artifact.synthetic",
        "artifact_sha256": "8" * 64,
        "allowed_sides": ("BUY", "SELL"),
        "allowed_offsets": ("OPEN",),
        "quantity_step": 1,
        "max_order_quantity": 2,
        "max_gross_position": 4,
        "min_price": Decimal("100"),
        "max_price": Decimal("200"),
        "price_tick": Decimal("1"),
        "max_order_notional": Decimal("400"),
        "front_pair_sha256": "9" * 64,
        "front_pair_set_sha256": "a" * 64,
        "front_pairs": (("tcp://192.0.2.21:41211", "tcp://192.0.2.20:41201"),),
        "selected_front_index": 0,
    }
    values.update(overrides)
    return CtpProductionExecutionConfigBinding(**values)


def _pins():
    roles = (
        ("execution", "bt_api_execution"),
        ("risk", "bt_api_risk"),
        ("monitor", "bt_api_monitor"),
    )
    return tuple(
        CtpProductionCapabilityPin(
            capability=capability,
            package_module=module,
            package_version="1.2.3",
            package_artifact_sha256=hex_digit * 64,
            capability_contract_sha256=contract_digit * 64,
        )
        for (capability, module), hex_digit, contract_digit in zip(
            roles, ("b", "c", "d"), ("e", "f", "0")
        )
    )


def _bindings(scope, pins=None):
    pins = _pins() if pins is None else pins
    return tuple(
        CtpProductionCapabilityBinding(
            pin=pin,
            binding_sha256=binding_digit * 64,
            account_binding_sha256=scope.account_binding_sha256,
            scope_identity_sha256=scope.scope_identity_sha256,
            runtime_registration_digest=scope.runtime_registration_digest,
            execution_registration_digest=scope.registration_digest,
            config_digest=scope.config_digest,
            effective_digest=scope.effective_digest,
        )
        for pin, binding_digit in zip(pins, ("1", "2", "3"))
    )


def _check(scope=None, pins=None, bindings=None):
    scope = _scope() if scope is None else scope
    pins = _pins() if pins is None else pins
    bindings = _bindings(scope, pins) if bindings is None else bindings
    return validate_ctp_production_capability_bundle_binding(scope, pins, bindings)


def test_exact_pinned_capability_triple_is_bound_to_one_resolved_ctp_scope():
    scope = _scope()

    checked = _check(scope)

    public = checked.as_public_dict()
    assert checked.scope_identity_sha256 == scope.scope_identity_sha256
    assert public["required_capabilities"] == ("execution", "risk", "monitor")
    assert public["provider"] == "ctp"
    assert public["external_writes_authorized"] is False
    assert public["execution_authorized"] is False
    assert public["order_submission_authorized"] is False
    assert "account_binding_sha256" not in public
    with pytest.raises(TypeError, match="non-authorizing"):
        bool(checked)


@pytest.mark.parametrize(
    "field,value",
    (
        ("account_binding_sha256", "f" * 64),
        ("scope_identity_sha256", "f" * 64),
        ("runtime_registration_digest", "f" * 64),
        ("execution_registration_digest", "f" * 64),
        ("config_digest", "f" * 64),
        ("effective_digest", "f" * 64),
    ),
)
def test_each_capability_must_match_exact_account_and_runtime_scope(field, value):
    scope = _scope()
    bindings = list(_bindings(scope))
    bindings[1] = replace(bindings[1], **{field: value})

    with pytest.raises(CtpProductionCapabilityBindingError) as caught:
        _check(scope, bindings=tuple(bindings))

    assert caught.value.reason == "capability_scope_mismatch"


def test_pins_and_binding_records_must_be_exactly_execution_risk_monitor():
    scope = _scope()
    pins = _pins()

    with pytest.raises(CtpProductionCapabilityBindingError) as caught:
        _check(scope, pins=(pins[0], pins[2], pins[1]))
    assert caught.value.reason == "capability_pin_set_mismatch"

    changed_pin = replace(pins[1], package_version="1.2.4")
    with pytest.raises(CtpProductionCapabilityBindingError) as caught:
        _check(
            scope,
            pins=(pins[0], changed_pin, pins[2]),
            bindings=_bindings(scope, pins),
        )
    assert caught.value.reason == "capability_binding_pin_mismatch"

    with pytest.raises(CtpProductionCapabilityBindingError) as caught:
        _check(scope, bindings=_bindings(scope)[:2])
    assert caught.value.reason == "exact_capability_bindings_required"


def test_unresolved_or_authorizing_production_scope_is_rejected():
    unresolved = _scope(selected_front_index=None, md_front=None, td_front=None)
    with pytest.raises(CtpProductionCapabilityBindingError) as caught:
        _check(unresolved)
    assert caught.value.reason == "production_execution_scope_unresolved"

    altered = _scope()
    object.__setattr__(altered, "external_writes_authorized", True)
    with pytest.raises(CtpProductionCapabilityBindingError) as caught:
        _check(altered)
    assert caught.value.reason == "authorizing_scope_evidence_forbidden"


def test_missing_effective_runtime_seal_and_mutated_records_fail_closed():
    no_effective_seal = _scope(effective_digest=None)
    with pytest.raises(CtpProductionCapabilityBindingError) as caught:
        _check(no_effective_seal)
    assert caught.value.reason == "invalid_effective_digest"

    scope = _scope()
    bindings = _bindings(scope)
    object.__setattr__(bindings[2], "account_binding_sha256", "not-a-digest")
    with pytest.raises(CtpProductionCapabilityBindingError) as caught:
        _check(scope, bindings=bindings)
    assert caught.value.reason == "invalid_account_binding_sha256"
