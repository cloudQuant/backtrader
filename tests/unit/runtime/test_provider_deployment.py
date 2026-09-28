"""Offline provider-deployment receipt binding contract coverage."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

import backtrader_runtime.provider_deployment as provider_deployment
from backtrader_runtime.provider_deployment import (
    ACTIVE_RECEIPT_STATUS,
    MAX_PROVIDER_DEPLOYMENT_CAPABILITY_MODULE_NAME_LENGTH,
    MAX_PROVIDER_DEPLOYMENT_RECEIPT_BYTES,
    PROVIDER_DEPLOYMENT_RECEIPT_SCHEMA_VERSION,
    ProviderDeploymentReceipt,
    ProviderDeploymentReceiptError,
    ProviderDeploymentRegistration,
    canonical_provider_deployment_receipt,
    parse_provider_deployment_receipt,
    validate_provider_deployment_receipt,
)


NOW = 1_700_000_100.0


@pytest.fixture(autouse=True)
def receipt_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep public validation on its real clock path in fixed-time tests."""

    monkeypatch.setattr(provider_deployment.time, "time", lambda: NOW)


class _AcceptingOfflineVerifier:
    """A test-only pure verifier; it has no trust material or provider access."""

    def __init__(self) -> None:
        self.calls = 0

    def verify(self, receipt, canonical_payload: bytes) -> bool:
        self.calls += 1
        assert canonical_payload == canonical_provider_deployment_receipt(receipt)
        return True


class _MutatingOfflineVerifier:
    """A hostile verifier used to ensure its input cannot corrupt validation."""

    def verify(self, receipt, canonical_payload: bytes) -> bool:
        del canonical_payload
        object.__setattr__(receipt, "artifact_sha256", "e" * 64)
        object.__setattr__(receipt, "required_capability_modules", ("bt_api_unreviewed",))
        return True


class _InvalidMutatingOfflineVerifier:
    """A hostile verifier that makes its receipt impossible to canonicalize."""

    def verify(self, receipt, canonical_payload: bytes) -> bool:
        del canonical_payload
        object.__setattr__(receipt, "artifact_sha256", object())
        return True


class _StatefulMapping(Mapping):
    """A mapping whose iteration would be an unacceptable parser side effect."""

    def __init__(self) -> None:
        self.iterated = False

    def __getitem__(self, key):
        del key
        raise AssertionError("the parser must not read a custom Mapping")

    def __iter__(self):
        self.iterated = True
        raise AssertionError("the parser must not iterate a custom Mapping")

    def __len__(self) -> int:
        return 0


class _StatefulList(list):
    """A list subclass whose iteration would be an unacceptable parser side effect."""

    def __init__(self, values) -> None:
        super().__init__(values)
        self.iterated = False

    def __iter__(self):
        self.iterated = True
        raise AssertionError("the parser must not iterate a list subclass")


class _StatefulText(str):
    """A text subclass whose length access would be a parser side effect."""

    def __new__(cls, value: str):
        instance = super().__new__(cls, value)
        instance.touched = False
        return instance

    def __len__(self) -> int:
        self.touched = True
        raise AssertionError("the parser must not inspect a str subclass")


class _StatefulBytes(bytes):
    """A bytes subclass whose length access would be a parser side effect."""

    def __new__(cls, value: bytes):
        instance = super().__new__(cls, value)
        instance.touched = False
        return instance

    def __len__(self) -> int:
        self.touched = True
        raise AssertionError("the parser must not inspect a bytes subclass")


class _SideEffectReceipt(ProviderDeploymentReceipt):
    """A receipt subclass whose virtual serializer must never be dispatched."""

    serializer_called = False

    def as_wire(self):
        type(self).serializer_called = True
        raise AssertionError("the canonicalizer must not dispatch receipt subclasses")


class _SideEffectRegistration(ProviderDeploymentRegistration):
    """A registration subclass whose attributes must not be read by validation."""

    attributes_read = False
    armed = False

    def __getattribute__(self, name):
        if name == "runtime_id" and type(self).armed:
            type(self).attributes_read = True
            raise AssertionError("validation must not read registration subclasses")
        return super().__getattribute__(name)


def _registration() -> ProviderDeploymentRegistration:
    return ProviderDeploymentRegistration(
        registration_id="iteration41.ctp.sandbox.demo-1",
        runtime_id="example.iteration41.runtime",
        strategy_id="example.iteration41.strategy",
        provider="ctp",
        environment="sandbox",
        allowed_secrets_refs=("os_secret_store:iteration41.ctp.sandbox",),
        account_fingerprint_sha256="a" * 64,
        approval_receipt_digest="e" * 64,
        artifact_sha256="b" * 64,
        effective_config_digest="c" * 64,
        capability_receipt_digest="d" * 64,
        required_capability_modules=("bt_api_py", "bt_api_ctp"),
    )


def _wire(registration: ProviderDeploymentRegistration) -> dict:
    return {
        "account_fingerprint_sha256": registration.account_fingerprint_sha256,
        "approval_receipt_digest": registration.approval_receipt_digest,
        "artifact_sha256": registration.artifact_sha256,
        "capability_receipt_digest": registration.capability_receipt_digest,
        "created_at": NOW - 10.0,
        "effective_config_digest": registration.effective_config_digest,
        "environment": registration.environment,
        "expires_at": NOW + 60.0,
        "provider": registration.provider,
        "receipt_id": "iteration41-receipt-1",
        "registration_id": registration.registration_id,
        "required_capability_modules": list(registration.required_capability_modules),
        "revoked_at": None,
        "runtime_id": registration.runtime_id,
        "schema_version": PROVIDER_DEPLOYMENT_RECEIPT_SCHEMA_VERSION,
        "secrets_ref": registration.allowed_secrets_refs[0],
        "status": ACTIVE_RECEIPT_STATUS,
        "strategy_id": registration.strategy_id,
    }


def test_matching_receipt_is_only_a_non_authoritative_offline_observation() -> None:
    registration = _registration()
    verifier = _AcceptingOfflineVerifier()

    validation = validate_provider_deployment_receipt(
        _wire(registration), registration=registration, verifier=verifier
    )

    assert verifier.calls == 1
    assert validation.status == "RECEIPT_BINDING_VALIDATED"
    assert validation.receipt_binding_valid is True
    assert validation.deployment_authorized is False
    assert validation.execution_authorized is False
    assert validation.secrets_resolved is False
    assert validation.provider_preflight_started is False
    assert validation.valid_until == NOW + 60.0
    assert validation.approval_receipt_digest == registration.approval_receipt_digest
    assert validation.required_capability_modules == ("bt_api_ctp", "bt_api_py")
    canonical = canonical_provider_deployment_receipt(
        parse_provider_deployment_receipt(_wire(registration))
    )
    assert json.loads(canonical) == _wire(registration)
    assert PROVIDER_DEPLOYMENT_RECEIPT_SCHEMA_VERSION == "bt-provider-deployment-receipt/v2"
    public = validation.as_public_dict()
    assert "secrets_ref" not in public
    assert registration.allowed_secrets_refs[0] not in json.dumps(public)
    assert registration.allowed_secrets_refs[0] not in repr(registration)
    assert registration.allowed_secrets_refs[0] not in repr(
        parse_provider_deployment_receipt(_wire(registration))
    )
    with pytest.raises(ValueError, match="cannot grant admission"):
        replace(validation, deployment_authorized=True)
    with pytest.raises(TypeError, match="not an admission decision"):
        bool(validation)


def test_default_verifier_fails_closed_without_claiming_provider_trust() -> None:
    registration = _registration()

    with pytest.raises(ProviderDeploymentReceiptError) as caught:
        validate_provider_deployment_receipt(_wire(registration), registration=registration)

    assert caught.value.reason == "receipt_untrusted"


def test_caller_cannot_revive_receipt_with_historical_time() -> None:
    registration = _registration()
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(TypeError, match="unexpected keyword argument 'now'"):
        validate_provider_deployment_receipt(
            _wire(registration),
            registration=registration,
            verifier=verifier,
            now=NOW - 1_000.0,  # type: ignore[call-arg]
        )

    assert verifier.calls == 0


def test_canonicalizer_rejects_receipt_subclasses_without_virtual_dispatch() -> None:
    registration = _registration()
    base_receipt = parse_provider_deployment_receipt(_wire(registration))
    receipt = _SideEffectReceipt(**base_receipt.__dict__)
    _SideEffectReceipt.serializer_called = False

    with pytest.raises(TypeError, match="receipt must be a ProviderDeploymentReceipt"):
        canonical_provider_deployment_receipt(receipt)

    assert _SideEffectReceipt.serializer_called is False


def test_validation_rejects_registration_subclasses_before_attribute_access() -> None:
    base_registration = _registration()
    registration = _SideEffectRegistration(**base_registration.__dict__)
    _SideEffectRegistration.attributes_read = False
    _SideEffectRegistration.armed = True
    try:
        with pytest.raises(
            TypeError, match="registration must be a ProviderDeploymentRegistration"
        ):
            validate_provider_deployment_receipt(
                _wire(base_registration), registration=registration
            )
    finally:
        _SideEffectRegistration.armed = False

    assert _SideEffectRegistration.attributes_read is False


@pytest.mark.parametrize(
    "mutate,reason",
    (
        (
            lambda wire: wire.update({"registration_id": "other.registration"}),
            "registration_mismatch",
        ),
        (lambda wire: wire.update({"runtime_id": "other.runtime"}), "runtime_mismatch"),
        (lambda wire: wire.update({"strategy_id": "other.strategy"}), "strategy_mismatch"),
        (lambda wire: wire.update({"provider": "other-provider"}), "provider_mismatch"),
        (lambda wire: wire.update({"environment": "production"}), "environment_mismatch"),
        (
            lambda wire: wire.update({"secrets_ref": "os_secret_store:other-provider"}),
            "secrets_ref_not_registered",
        ),
        (
            lambda wire: wire.update({"account_fingerprint_sha256": "e" * 64}),
            "account_fingerprint_mismatch",
        ),
        (
            lambda wire: wire.update({"approval_receipt_digest": "f" * 64}),
            "approval_receipt_digest_mismatch",
        ),
        (lambda wire: wire.update({"artifact_sha256": "e" * 64}), "artifact_mismatch"),
        (
            lambda wire: wire.update({"effective_config_digest": "e" * 64}),
            "effective_config_digest_mismatch",
        ),
        (
            lambda wire: wire.update({"capability_receipt_digest": "e" * 64}),
            "capability_receipt_digest_mismatch",
        ),
        (
            lambda wire: wire.update({"required_capability_modules": ["bt_api_py"]}),
            "required_capability_modules_mismatch",
        ),
    ),
)
def test_receipt_must_bind_every_registered_provider_deployment_value(mutate, reason: str) -> None:
    registration = _registration()
    wire = _wire(registration)
    mutate(wire)
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(ProviderDeploymentReceiptError) as caught:
        validate_provider_deployment_receipt(wire, registration=registration, verifier=verifier)

    assert caught.value.reason == reason
    assert verifier.calls == 0


@pytest.mark.parametrize(
    "mutate,reason",
    (
        (lambda wire: wire.update({"created_at": NOW + 1.0}), "receipt_not_yet_valid"),
        (lambda wire: wire.update({"expires_at": NOW}), "receipt_expired"),
        (lambda wire: wire.update({"status": "revoked"}), "receipt_revoked"),
        (lambda wire: wire.update({"revoked_at": NOW - 1.0}), "receipt_revoked"),
        (lambda wire: wire.update({"status": "suspended"}), "unsupported_receipt_status"),
        (
            lambda wire: wire.update({"schema_version": "bt-provider-deployment-receipt/v1"}),
            "unsupported_schema",
        ),
        (lambda wire: wire.update({"unexpected": "field"}), "invalid_wire"),
        (
            lambda wire: wire.update({"secrets_ref": "runtime_secrets"}),
            "invalid_secrets_ref",
        ),
        (
            lambda wire: wire.update({"required_capability_modules": ["bt_api_py", "bt_api_py"]}),
            "invalid_capability_modules",
        ),
        (
            lambda wire: wire.update({"required_capability_modules": [[]]}),
            "invalid_capability_modules",
        ),
        (lambda wire: wire.update({"approval_receipt_digest": "invalid"}), "invalid_digest"),
    ),
)
def test_malformed_lifecycle_or_revoked_receipts_fail_before_the_verifier(
    mutate, reason: str
) -> None:
    registration = _registration()
    wire = _wire(registration)
    mutate(wire)
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(ProviderDeploymentReceiptError) as caught:
        validate_provider_deployment_receipt(wire, registration=registration, verifier=verifier)

    assert caught.value.reason == reason
    assert verifier.calls == 0


def test_parser_rejects_duplicate_json_fields_before_any_verifier_can_run() -> None:
    registration = _registration()
    encoded = json.dumps(_wire(registration), sort_keys=True)
    duplicate = encoded[:-1] + ',"receipt_id":"duplicate"}'
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(ProviderDeploymentReceiptError) as caught:
        validate_provider_deployment_receipt(
            duplicate, registration=registration, verifier=verifier
        )

    assert caught.value.reason == "invalid_json"
    assert verifier.calls == 0


def test_parser_rejects_receipts_missing_the_preissued_approval_digest() -> None:
    registration = _registration()
    wire = _wire(registration)
    del wire["approval_receipt_digest"]

    with pytest.raises(ProviderDeploymentReceiptError) as caught:
        parse_provider_deployment_receipt(wire)

    assert caught.value.reason == "invalid_wire"


@pytest.mark.parametrize(
    "serialized,expected_reasons",
    (
        ("[" * 2_000 + "]" * 2_000, ("invalid_json", "invalid_wire")),
        (b"{" + b" " * MAX_PROVIDER_DEPLOYMENT_RECEIPT_BYTES + b"}", ("receipt_too_large",)),
    ),
    ids=("deeply_nested_json", "oversized_bytes"),
)
def test_parser_rejects_nested_or_oversized_receipts_before_the_verifier(
    serialized: object, expected_reasons
) -> None:
    registration = _registration()
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(ProviderDeploymentReceiptError) as caught:
        validate_provider_deployment_receipt(
            serialized, registration=registration, verifier=verifier
        )

    assert caught.value.reason in expected_reasons
    assert verifier.calls == 0


def test_parser_rejects_stateful_mappings_without_executing_them() -> None:
    mapping = _StatefulMapping()

    with pytest.raises(ProviderDeploymentReceiptError) as caught:
        parse_provider_deployment_receipt(mapping)

    assert caught.value.reason == "invalid_wire"
    assert mapping.iterated is False


def test_parser_rejects_stateful_json_container_subclasses_without_executing_them() -> None:
    registration = _registration()
    wire = _wire(registration)
    modules = _StatefulList(wire["required_capability_modules"])
    wire["required_capability_modules"] = modules

    with pytest.raises(ProviderDeploymentReceiptError) as caught:
        parse_provider_deployment_receipt(wire)

    assert caught.value.reason == "invalid_capability_modules"
    assert modules.iterated is False


@pytest.mark.parametrize(
    "factory",
    (lambda: _StatefulText("{}"), lambda: _StatefulBytes(b"{}")),
    ids=("str_subclass", "bytes_subclass"),
)
def test_parser_rejects_stateful_serialized_subclasses_without_executing_them(factory) -> None:
    serialized = factory()
    with pytest.raises(ProviderDeploymentReceiptError) as caught:
        parse_provider_deployment_receipt(serialized)

    assert caught.value.reason == "invalid_wire"
    assert serialized.touched is False


def test_plain_dict_receipts_cannot_bypass_the_canonical_size_limit() -> None:
    registration = _registration()
    wire = _wire(registration)
    wire["required_capability_modules"] = [
        "bt_api_" + "a" * (MAX_PROVIDER_DEPLOYMENT_CAPABILITY_MODULE_NAME_LENGTH + 1)
    ]
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(ProviderDeploymentReceiptError) as caught:
        validate_provider_deployment_receipt(wire, registration=registration, verifier=verifier)

    assert caught.value.reason == "receipt_too_large"
    assert verifier.calls == 0


def test_parser_converts_a_json_recursion_error_to_a_redacted_rejection(monkeypatch) -> None:
    def raise_recursion_error(*args, **kwargs):
        del args, kwargs
        raise RecursionError("synthetic parser depth failure")

    monkeypatch.setattr(provider_deployment.json, "loads", raise_recursion_error)

    with pytest.raises(ProviderDeploymentReceiptError) as caught:
        parse_provider_deployment_receipt("{}")

    assert caught.value.reason == "invalid_json"


def test_verifier_cannot_mutate_the_canonical_receipt_it_claims_to_trust() -> None:
    registration = _registration()

    with pytest.raises(ProviderDeploymentReceiptError) as caught:
        validate_provider_deployment_receipt(
            _wire(registration),
            registration=registration,
            verifier=_MutatingOfflineVerifier(),
        )

    assert caught.value.reason == "receipt_mutated_by_verifier"


def test_verifier_invalid_type_mutation_fails_closed_with_a_redacted_reason() -> None:
    registration = _registration()

    with pytest.raises(ProviderDeploymentReceiptError) as caught:
        validate_provider_deployment_receipt(
            _wire(registration),
            registration=registration,
            verifier=_InvalidMutatingOfflineVerifier(),
        )

    assert caught.value.reason == "receipt_mutated_by_verifier"


def test_validation_rechecks_expiry_after_the_verifier_returns(monkeypatch) -> None:
    registration = _registration()
    clock_values = iter((NOW, NOW + 60.0))
    monkeypatch.setattr(provider_deployment.time, "time", lambda: next(clock_values))
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(ProviderDeploymentReceiptError) as caught:
        validate_provider_deployment_receipt(
            _wire(registration), registration=registration, verifier=verifier
        )

    assert caught.value.reason == "receipt_expired"
    assert verifier.calls == 1


def test_registration_requires_only_opaque_secret_references_and_capability_modules() -> None:
    values = dict(_registration().__dict__)
    values["allowed_secrets_refs"] = ("runtime_secrets",)
    with pytest.raises(ValueError, match="invalid allowed_secrets_refs"):
        ProviderDeploymentRegistration(**values)

    values = dict(_registration().__dict__)
    values["required_capability_modules"] = ()
    with pytest.raises(ValueError, match="invalid required_capability_modules"):
        ProviderDeploymentRegistration(**values)


def test_registration_requires_a_preissued_approval_receipt_digest() -> None:
    values = dict(_registration().__dict__)
    values["approval_receipt_digest"] = None

    with pytest.raises(ValueError, match="invalid approval_receipt_digest"):
        ProviderDeploymentRegistration(**values)


def test_validation_rechecks_mutated_code_owned_registration_digest() -> None:
    registration = _registration()
    object.__setattr__(registration, "approval_receipt_digest", "invalid")
    verifier = _AcceptingOfflineVerifier()

    with pytest.raises(ValueError, match="invalid approval_receipt_digest"):
        validate_provider_deployment_receipt(
            _wire(_registration()), registration=registration, verifier=verifier
        )

    assert verifier.calls == 0


def test_receipt_parser_normalizes_capability_module_order_for_exact_scope_matching() -> None:
    registration = _registration()
    wire = _wire(registration)
    wire["required_capability_modules"] = ["bt_api_py", "bt_api_ctp"]

    receipt = parse_provider_deployment_receipt(copy.deepcopy(wire))

    assert receipt.required_capability_modules == ("bt_api_ctp", "bt_api_py")


def test_provider_deployment_module_imports_no_framework_or_provider_sdk() -> None:
    script = (
        "import sys; import backtrader_runtime.provider_deployment; "
        "blocked = ('backtrader', 'bt_api', 'bt_api_py', 'backtrader_agent', "
        "'backtrader_skills', 'backtrader_mcp'); "
        "assert not any(name == item or name.startswith(item + '.') "
        "for item in blocked for name in sys.modules)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).resolve().parents[3]),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
