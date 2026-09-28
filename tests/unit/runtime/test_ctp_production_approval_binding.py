"""Pure tests for external CTP production receipt-to-scope mapping."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Optional, Tuple

import pytest

import backtrader_runtime.config as runtime_config
from backtrader_runtime.ctp_production_approval_binding import (
    CtpProductionApprovalBindingError,
    CtpProductionApprovalReceiptMetadata,
    require_ctp_production_approval_binding,
)
from backtrader_runtime.ctp_production_execution_admission import (
    require_ctp_production_execution_config_binding,
)
from backtrader_runtime.registry import RuntimeRegistry, resolve_runtime_config

from test_ctp_production_execution_admission import (
    _PRIVATE_VALUES,
    _RECEIPT_SHA256,
    _bound_inputs,
    _document,
)


_FRONT_PAIRS = [
    {"md_front": "tcp://192.0.2.11:41211", "td_front": "tcp://192.0.2.10:41201"},
    {"md_front": "tcp://192.0.2.21:41211", "td_front": "tcp://192.0.2.20:41201"},
]
_SELECTED_PAIR = (_FRONT_PAIRS[1]["md_front"], _FRONT_PAIRS[1]["td_front"])


class _FakeTrustedMapping:
    """Synthetic external map keyed by the exact receipt/scope tuple."""

    def __init__(
        self,
        mapping: dict[Tuple[str, str], CtpProductionApprovalReceiptMetadata],
    ) -> None:
        self.mapping = dict(mapping)
        self.calls = []

    def verify(
        self, receipt_sha256: str, scope_identity_sha256: str
    ) -> Optional[CtpProductionApprovalReceiptMetadata]:
        key = (receipt_sha256, scope_identity_sha256)
        self.calls.append(key)
        return self.mapping.get(key)


class _RaisingVerifier:
    def verify(self, receipt_sha256: str, scope_identity_sha256: str):
        del receipt_sha256, scope_identity_sha256
        raise RuntimeError("synthetic verifier failure details")


def _sealed_canonical_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    private_values: Optional[dict] = None,
):
    values = dict(_PRIVATE_VALUES)
    values.pop("md_front")
    values.pop("td_front")
    values["front_pairs"] = [dict(pair) for pair in _FRONT_PAIRS]
    if private_values:
        values.update(private_values)
    config, registry, registration = _bound_inputs(
        tmp_path, monkeypatch, values, canonical=True
    )
    effective = resolve_runtime_config(config, registry)
    return values, config, registry, registration, effective


def _mapping_for_current_scope(config, registry, registration, effective, pair=_SELECTED_PAIR):
    binding = require_ctp_production_execution_config_binding(
        config,
        registry,
        registration,
        selected_front_pair=pair,
        effective_runtime=effective,
    )
    metadata = CtpProductionApprovalReceiptMetadata(
        receipt_sha256=registration.approval_receipt_sha256,
        environment="production",
        expires_at=500.0,
    )
    verifier = _FakeTrustedMapping(
        {(metadata.receipt_sha256, binding.scope_identity_sha256): metadata}
    )
    return binding, verifier


def test_current_external_mapping_binds_metadata_without_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, config, registry, registration, effective = _sealed_canonical_config(
        tmp_path, monkeypatch
    )
    binding, verifier = _mapping_for_current_scope(
        config, registry, registration, effective
    )

    observation = require_ctp_production_approval_binding(
        config,
        registry,
        registration,
        selected_front_pair=_SELECTED_PAIR,
        effective_runtime=effective,
        checked_at=100.0,
        verifier=verifier,
    )

    assert verifier.calls == [(_RECEIPT_SHA256, binding.scope_identity_sha256)]
    assert observation.scope_identity_sha256 == binding.scope_identity_sha256
    assert not hasattr(
        CtpProductionApprovalReceiptMetadata, "scope_identity_sha256"
    )
    assert observation.receipt_sha256 == _RECEIPT_SHA256
    assert observation.effective_digest == effective.effective_digest
    assert observation.selected_front_index == 1
    assert observation.valid_until == 500.0
    assert observation.injected_verifier_accepted is True
    assert observation.provider_access_authorized is False
    assert observation.credential_access_authorized is False
    assert observation.execution_authorized is False
    assert observation.external_writes_authorized is False
    assert observation.order_submission_authorized is False
    assert observation.cancellation_authorized is False
    assert observation.arming_authorized is False
    public = observation.as_public_dict()
    assert "account_binding_sha256" not in public
    assert "md_front" not in public and "td_front" not in public
    assert "synthetic-production-account" not in repr(public)
    with pytest.raises(TypeError, match="non-authorizing"):
        bool(observation)


@pytest.mark.parametrize("change", ("account", "front_set", "selected_front", "contract"))
def test_old_mapping_rejects_stale_config_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    values, config, registry, registration, effective = _sealed_canonical_config(
        tmp_path, monkeypatch
    )
    original_binding, verifier = _mapping_for_current_scope(
        config, registry, registration, effective
    )

    selected_pair = _SELECTED_PAIR
    if change == "account":
        values["user_id"] = "synthetic-production-account-replaced"
    elif change == "front_set":
        values["front_pairs"][0] = {
            "md_front": "tcp://192.0.2.31:41211",
            "td_front": "tcp://192.0.2.30:41201",
        }
    elif change == "selected_front":
        selected_pair = (_FRONT_PAIRS[0]["md_front"], _FRONT_PAIRS[0]["td_front"])
    elif change == "contract":
        values["instrument_id"] = "IH2612"

    changed_config = runtime_config._validate_schema(
        _document(values, canonical=True), config.strategy_dir, config.source_path
    )
    runtime_config._seal_loaded_runtime_config(changed_config, registry)
    changed_effective = resolve_runtime_config(changed_config, registry)
    changed_binding = require_ctp_production_execution_config_binding(
        changed_config,
        registry,
        registration,
        selected_front_pair=selected_pair,
        effective_runtime=changed_effective,
    )
    assert changed_binding.scope_identity_sha256 != original_binding.scope_identity_sha256

    with pytest.raises(CtpProductionApprovalBindingError) as caught:
        require_ctp_production_approval_binding(
            changed_config,
            registry,
            registration,
            selected_front_pair=selected_pair,
            effective_runtime=changed_effective,
            checked_at=100.0,
            verifier=verifier,
        )
    assert caught.value.reason == "approval_mapping_untrusted"
    assert len(verifier.calls) == 1


def test_default_verifier_rejects_without_external_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, config, registry, registration, effective = _sealed_canonical_config(
        tmp_path, monkeypatch
    )

    with pytest.raises(CtpProductionApprovalBindingError) as caught:
        require_ctp_production_approval_binding(
            config,
            registry,
            registration,
            selected_front_pair=_SELECTED_PAIR,
            effective_runtime=effective,
            checked_at=100.0,
        )
    assert caught.value.reason == "approval_mapping_untrusted"


def test_verifier_exception_is_redacted_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, config, registry, registration, effective = _sealed_canonical_config(
        tmp_path, monkeypatch
    )

    with pytest.raises(CtpProductionApprovalBindingError) as caught:
        require_ctp_production_approval_binding(
            config,
            registry,
            registration,
            selected_front_pair=_SELECTED_PAIR,
            effective_runtime=effective,
            checked_at=100.0,
            verifier=_RaisingVerifier(),
        )
    assert caught.value.reason == "approval_verifier_failed"
    assert str(caught.value) == "production approval mapping verifier failed"
    assert "synthetic verifier failure details" not in str(caught.value)


def test_receipt_rotation_rejects_old_external_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values, config, registry, registration, effective = _sealed_canonical_config(
        tmp_path, monkeypatch
    )
    old_binding, old_verifier = _mapping_for_current_scope(
        config, registry, registration, effective
    )
    old_observation = require_ctp_production_approval_binding(
        config,
        registry,
        registration,
        selected_front_pair=_SELECTED_PAIR,
        effective_runtime=effective,
        checked_at=100.0,
        verifier=old_verifier,
    )
    assert old_observation.scope_identity_sha256 == old_binding.scope_identity_sha256
    assert old_observation.execution_authorized is False

    rotated_receipt_sha256 = "d" * 64
    rotated_runtime = replace(
        registration.runtime_registration,
        approval_receipt_digest=rotated_receipt_sha256,
    )
    rotated_registry = RuntimeRegistry((rotated_runtime,))
    rotated_registration = replace(
        registration,
        runtime_registration=rotated_runtime,
        approval_receipt_sha256=rotated_receipt_sha256,
    )
    rotated_config = runtime_config._validate_schema(
        _document(values, canonical=True), config.strategy_dir, config.source_path
    )
    runtime_config._seal_loaded_runtime_config(rotated_config, rotated_registry)
    rotated_effective = resolve_runtime_config(rotated_config, rotated_registry)
    rotated_binding = require_ctp_production_execution_config_binding(
        rotated_config,
        rotated_registry,
        rotated_registration,
        selected_front_pair=_SELECTED_PAIR,
        effective_runtime=rotated_effective,
    )
    assert rotated_registration.approval_receipt_sha256 == rotated_receipt_sha256
    assert rotated_binding.scope_identity_sha256 != old_binding.scope_identity_sha256

    with pytest.raises(CtpProductionApprovalBindingError) as caught:
        require_ctp_production_approval_binding(
            rotated_config,
            rotated_registry,
            rotated_registration,
            selected_front_pair=_SELECTED_PAIR,
            effective_runtime=rotated_effective,
            checked_at=100.0,
            verifier=old_verifier,
        )
    assert caught.value.reason == "approval_mapping_untrusted"
    assert old_verifier.calls == [
        (_RECEIPT_SHA256, old_binding.scope_identity_sha256),
        (rotated_receipt_sha256, rotated_binding.scope_identity_sha256),
    ]


@pytest.mark.parametrize(
    ("metadata", "reason"),
    (
        (
            CtpProductionApprovalReceiptMetadata(
                receipt_sha256="c" * 64, environment="production", expires_at=500.0
            ),
            "receipt_digest_mismatch",
        ),
        (
            CtpProductionApprovalReceiptMetadata(
                receipt_sha256=_RECEIPT_SHA256, environment="sandbox", expires_at=500.0
            ),
            "environment_mismatch",
        ),
        (
            CtpProductionApprovalReceiptMetadata(
                receipt_sha256=_RECEIPT_SHA256, environment="production", expires_at=99.0
            ),
            "receipt_expired",
        ),
    ),
)
def test_receipt_digest_environment_and_expiry_are_checked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    metadata: CtpProductionApprovalReceiptMetadata,
    reason: str,
) -> None:
    _, config, registry, registration, effective = _sealed_canonical_config(
        tmp_path, monkeypatch
    )
    binding = require_ctp_production_execution_config_binding(
        config,
        registry,
        registration,
        selected_front_pair=_SELECTED_PAIR,
        effective_runtime=effective,
    )
    verifier = _FakeTrustedMapping(
        {(_RECEIPT_SHA256, binding.scope_identity_sha256): metadata}
    )

    with pytest.raises(CtpProductionApprovalBindingError) as caught:
        require_ctp_production_approval_binding(
            config,
            registry,
            registration,
            selected_front_pair=_SELECTED_PAIR,
            effective_runtime=effective,
            checked_at=100.0,
            verifier=verifier,
        )
    assert caught.value.reason == reason


def test_binding_requires_explicit_selected_pair_and_effective_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, config, registry, registration, effective = _sealed_canonical_config(
        tmp_path, monkeypatch
    )
    _, verifier = _mapping_for_current_scope(config, registry, registration, effective)

    with pytest.raises(CtpProductionApprovalBindingError) as missing_pair:
        require_ctp_production_approval_binding(
            config,
            registry,
            registration,
            selected_front_pair=None,  # type: ignore[arg-type]
            effective_runtime=effective,
            checked_at=100.0,
            verifier=verifier,
        )
    assert missing_pair.value.reason == "selected_front_required"

    with pytest.raises(CtpProductionApprovalBindingError) as missing_effective:
        require_ctp_production_approval_binding(
            config,
            registry,
            registration,
            selected_front_pair=_SELECTED_PAIR,
            effective_runtime=None,  # type: ignore[arg-type]
            checked_at=100.0,
            verifier=verifier,
        )
    assert missing_effective.value.reason == "effective_config_required"
    assert verifier.calls == []
