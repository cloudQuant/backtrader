"""Pure contract tests for bounded, non-authorizing CTP production scope."""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import os
import socket
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import backtrader_runtime.config as runtime_config
import backtrader_runtime.ctp_production_managed_composition as production_composition
from backtrader_runtime import RegisteredRuntime, RuntimeProfile, RuntimeRegistry
from backtrader_runtime.ctp_front_pair_probe import (
    CtpConfiguredFrontPair,
    CtpFrontEndpointEvidence,
    CtpFrontPairEvidence,
    CtpFrontPairSelection,
    CtpFrontProbeSample,
)
from backtrader_runtime.registry import resolve_runtime_config
from backtrader_runtime.ctp_production_execution_admission import (
    CtpProductionExecutionAdmissionError,
    CtpProductionExecutionConfigBinding,
    CtpProductionExecutionRegistration,
    require_ctp_production_execution_config_binding,
)
from backtrader_runtime.ctp_production_readonly_admission import (
    production_account_binding_sha256,
)
from backtrader_runtime.inventory import ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION
from backtrader_runtime.policy import MANAGED_WRITE_CAPABILITIES


_PRIVATE_VALUES = {
    "md_front": "tcp://192.0.2.11:41211",
    "td_front": "tcp://192.0.2.10:41201",
    "instrument_id": "IF2612",
    "exchange_id": "CFFEX",
    "hedge_flag": "1",
    "broker_id": "synthetic-production-broker",
    "user_id": "synthetic-production-account",
    "password": "synthetic-production-password-never-use",
    "app_id": "synthetic-production-app",
    "auth_code": "synthetic-production-auth",
}
_RECEIPT_ID = "ctp-production:receipt.review.001"
_RECEIPT_SHA256 = "a" * 64
_ARTIFACT_ID = "ctp-production:artifact.review.001"
_ARTIFACT_SHA256 = "b" * 64
_PROFILE_STRATEGY_ID = "example.synthetic.ctp_profile_production"
_PROFILE_RECEIPT_SHA256 = "c" * 64
_PROFILE_ARTIFACT_SHA256 = "d" * 64


def _document(
    private_values: dict[str, Any] | None = None, *, canonical: bool = False
) -> dict[str, Any]:
    private_block = dict(_PRIVATE_VALUES if private_values is None else private_values)
    return {
        "config_schema_version": 4,
        "strategy": {
            "id": "example.013_3.sa_midfreq_simnow" if canonical else "example.007_ctp.production"
        },
        "runtime": {"mode": "live", "preset": "managed_live_direct"},
        "parameters": {},
        "secrets_ref": "config_yaml",
        "ctp" if canonical else "ctp_production": private_block,
    }


def _bound_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    private_values: dict[str, Any] | None = None,
    *,
    canonical: bool = False,
):
    runtime_dir = tmp_path / "runtime-ctp-private" if canonical else tmp_path
    if canonical:
        runtime_dir.mkdir()
    monkeypatch.setattr(runtime_config, "CTP_PRODUCTION_RUNTIME_DIR", runtime_dir)
    runtime = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id=(
            "example.013_3.sa_midfreq_simnow" if canonical else "example.007_ctp.production"
        ),
        runtime_id=(
            "example.013_3.sa_midfreq_simnow.injected_production_contract"
            if canonical
            else "example.007_ctp.production"
        ),
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=MANAGED_WRITE_CAPABILITIES,
        approval_receipt_digest=_RECEIPT_SHA256,
    )
    registry = RuntimeRegistry((runtime,))
    config = runtime_config._validate_schema(
        _document(private_values, canonical=canonical),
        runtime_dir,
        runtime_dir / "config.yaml",
    )
    runtime_config._seal_loaded_runtime_config(config, registry)
    pin = CtpProductionExecutionRegistration(
        runtime_registration=runtime,
        environment="production",
        account_binding_sha256=(
            None
            if canonical
            else production_account_binding_sha256(
                _PRIVATE_VALUES["broker_id"], _PRIVATE_VALUES["user_id"]
            )
        ),
        md_front=None if canonical else _PRIVATE_VALUES["md_front"],
        td_front=None if canonical else _PRIVATE_VALUES["td_front"],
        instrument_id=None if canonical else _PRIVATE_VALUES["instrument_id"],
        exchange_id=None if canonical else _PRIVATE_VALUES["exchange_id"],
        hedge_flag=None if canonical else _PRIVATE_VALUES["hedge_flag"],
        approval_receipt_id=_RECEIPT_ID,
        approval_receipt_sha256=_RECEIPT_SHA256,
        artifact_id=_ARTIFACT_ID,
        artifact_sha256=_ARTIFACT_SHA256,
        allowed_sides=("BUY", "SELL"),
        allowed_offsets=("OPEN",),
        quantity_step=1,
        max_order_quantity=3,
        max_gross_position=6,
        min_price=Decimal("100.0"),
        max_price=Decimal("200.0"),
        price_tick=Decimal("0.2"),
        max_order_notional=Decimal("600.0"),
        scope_binding_mode="sealed_config" if canonical else "pinned",
    )
    return config, registry, pin


def _fake_production_front_selection(
    front_pairs,
    *,
    timeout_seconds: float,
    repeated_samples: int,
    fault: str | None = None,
) -> CtpFrontPairSelection:
    candidates = tuple(
        CtpConfiguredFrontPair(pair["md_front"], pair["td_front"]) for pair in front_pairs
    )
    evidence = []
    selected_index = len(candidates) - 1
    for index, pair in enumerate(candidates):
        reachable = index != selected_index or fault != "unreachable_selected"
        score = (
            None
            if not reachable
            else (3.0 if fault == "latency_mismatch" and index == selected_index else 2.0)
        )
        md = CtpFrontEndpointEvidence(
            pair.md_front,
            (CtpFrontProbeSample(connected=reachable, latency_ms=score),),
        )
        td = CtpFrontEndpointEvidence(
            pair.td_front,
            (CtpFrontProbeSample(connected=reachable, latency_ms=score),),
        )
        evidence.append(
            CtpFrontPairEvidence(
                config_index=index,
                pair=pair,
                md=md,
                td=td,
                reachable=reachable,
                latency_score_ms=score,
            )
        )
    if fault == "mismatched_index_pair":
        selected_pair = candidates[0]
    elif fault == "outside_config":
        selected_pair = CtpConfiguredFrontPair(
            "tcp://192.0.2.91:41211", "tcp://192.0.2.90:41201"
        )
    else:
        selected_pair = candidates[selected_index]
    return CtpFrontPairSelection(
        pair=selected_pair,
        config_index=selected_index,
        latency_score_ms=2.0,
        evidence=tuple(evidence),
        timeout_seconds=timeout_seconds,
        repeated_samples=repeated_samples,
    )


def _profile_scope_inputs(
    runtime_dir: Path,
    *,
    live_profile_changes: dict[str, Any] | None = None,
):
    """Build one profile-scoped runtime used by pure admission tests."""

    runtime_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(runtime_dir, 0o700)
    sandbox_profile = RuntimeProfile(
        mode="simulation",
        preset="sandbox",
        allowed_parameter_keys=(),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=(),
        approval_receipt_digest=None,
        runner_module=None,
        runner_entrypoint="run_runtime",
        capability_modules=(),
        offline_managed_execution=False,
        sandbox_write_policy="deny",
    )
    live_profile_fields = {
        "mode": "live",
        "preset": "managed_live_direct",
        "allowed_parameter_keys": (),
        "allowed_secrets_refs": ("config_yaml",),
        "available_capabilities": MANAGED_WRITE_CAPABILITIES,
        "approval_receipt_digest": _PROFILE_RECEIPT_SHA256,
        "runner_module": None,
        "runner_entrypoint": "run_runtime",
        "capability_modules": (),
        "offline_managed_execution": False,
        "sandbox_write_policy": "deny",
    }
    if live_profile_changes:
        live_profile_fields.update(live_profile_changes)
    live_profile = RuntimeProfile(**live_profile_fields)
    registered = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id=_PROFILE_STRATEGY_ID,
        runtime_id="synthetic.ctp.profile.scope",
        allowed_presets=(),
        profiles=(sandbox_profile, live_profile),
    )
    registry = RuntimeRegistry((registered,), registry_id="test.ctp.profile.scope")
    admission = CtpProductionExecutionRegistration(
        runtime_registration=registered,
        environment="production",
        account_binding_sha256=None,
        md_front=None,
        td_front=None,
        instrument_id=None,
        exchange_id=None,
        hedge_flag=None,
        approval_receipt_id="ctp-production:receipt.profile.synthetic",
        approval_receipt_sha256=_PROFILE_RECEIPT_SHA256,
        artifact_id="ctp-production:artifact.profile.synthetic",
        artifact_sha256=_PROFILE_ARTIFACT_SHA256,
        allowed_sides=("BUY", "SELL"),
        allowed_offsets=("OPEN",),
        quantity_step=1,
        max_order_quantity=3,
        max_gross_position=6,
        min_price=Decimal("100"),
        max_price=Decimal("200"),
        price_tick=Decimal("1"),
        max_order_notional=Decimal("600"),
        scope_binding_mode="sealed_config",
    )
    return registry, registered, admission


def _write_profile_scope_config(
    runtime_dir: Path,
    *,
    mode: str,
    preset: str,
    private_values: dict[str, Any] | None = None,
) -> None:
    document = {
        "config_schema_version": 4,
        "strategy": {"id": _PROFILE_STRATEGY_ID},
        "runtime": {"mode": mode, "preset": preset},
        "parameters": {},
        "secrets_ref": "config_yaml",
        "ctp": dict(_PRIVATE_VALUES if private_values is None else private_values),
    }
    path = runtime_dir / "config.yaml"
    path.write_text(json.dumps(document), encoding="utf-8")
    if os.name == "posix":
        os.chmod(path, 0o600)


def _stub_private_config_security_for_synthetic_test(monkeypatch: pytest.MonkeyPatch):
    """Keep these tests platform independent while exercising the private gate."""

    private_security_flags = []
    security_checks = []
    original_read_config_text = runtime_config._read_config_text

    def capture_private_config_security(*args, **kwargs):
        private_security_flags.append(kwargs.get("require_private_config_security"))
        return original_read_config_text(*args, **kwargs)

    monkeypatch.setattr(runtime_config, "_read_config_text", capture_private_config_security)
    monkeypatch.setattr(
        runtime_config,
        "_require_private_config_security",
        lambda *args, **kwargs: security_checks.append(kwargs),
    )
    return private_security_flags, security_checks


def _install_provider_access_guards(monkeypatch: pytest.MonkeyPatch):
    """Fail if config-only composition reaches provider, network, or write paths."""

    import_attempts = []
    socket_attempts = []
    write_attempts = []
    original_import = builtins.__import__
    original_open = builtins.open
    original_os_open = os.open

    def reject_provider_import(name, *args, **kwargs):
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in (
                "bt_api_ctp",
                "bt_api_py",
                "bt_api_base",
                "backtrader_runtime.credential_resolver",
                "backtrader_runtime.ctp_production_credentials",
            )
        ):
            import_attempts.append(name)
            raise AssertionError("config-only scope selector attempted credential or SDK import")
        return original_import(name, *args, **kwargs)

    def reject_socket(*args, **kwargs):
        socket_attempts.append((args, kwargs))
        raise AssertionError("config-only scope selector attempted provider network access")

    def observe_open(path, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            write_attempts.append((path, mode))
            raise AssertionError("config-only scope selector attempted a filesystem write")
        return original_open(path, mode, *args, **kwargs)

    def observe_os_open(path, flags, *args, **kwargs):
        write_mask = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        if flags & write_mask:
            write_attempts.append((path, flags))
            raise AssertionError("config-only scope selector attempted a low-level filesystem write")
        return original_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_provider_import)
    monkeypatch.setattr(builtins, "open", observe_open)
    monkeypatch.setattr(io, "open", observe_open)
    monkeypatch.setattr(os, "open", observe_os_open)
    monkeypatch.setattr(socket, "socket", reject_socket)
    return import_attempts, socket_attempts, write_attempts


def test_exact_production_scope_yields_only_non_authorizing_contract_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)

    binding = require_ctp_production_execution_config_binding(config, registry, pin)

    assert isinstance(binding, CtpProductionExecutionConfigBinding)
    assert binding.environment == "production"
    assert binding.md_front == _PRIVATE_VALUES["md_front"]
    assert binding.td_front == _PRIVATE_VALUES["td_front"]
    assert binding.instrument_id == "IF2612"
    assert binding.exchange_id == "CFFEX"
    assert binding.hedge_flag == "1"
    assert binding.account_binding_sha256 == production_account_binding_sha256(
        _PRIVATE_VALUES["broker_id"], _PRIVATE_VALUES["user_id"]
    )
    assert binding.approval_receipt_id == _RECEIPT_ID
    assert binding.approval_receipt_sha256 == _RECEIPT_SHA256
    assert binding.artifact_id == _ARTIFACT_ID
    assert binding.artifact_sha256 == _ARTIFACT_SHA256
    assert binding.allowed_sides == ("BUY", "SELL")
    assert binding.allowed_offsets == ("OPEN",)
    assert binding.quantity_step == 1
    assert binding.max_order_quantity == 3
    assert binding.max_gross_position == 6
    assert binding.min_price == Decimal("100.0")
    assert binding.max_price == Decimal("200.0")
    assert binding.price_tick == Decimal("0.2")
    assert binding.max_order_notional == Decimal("600.0")
    assert binding.contract_verified is True
    assert binding.scope_identity_sha256
    assert binding.effective_digest is None
    assert binding.provider_access_authorized is False
    assert binding.credential_access_authorized is False
    assert binding.execution_authorized is False
    assert binding.external_writes_authorized is False
    assert binding.order_submission_authorized is False
    assert binding.cancellation_authorized is False
    assert binding.arming_authorized is False
    with pytest.raises(TypeError, match="non-authorizing"):
        bool(binding)

    public_text = json.dumps(binding.as_public_dict(), sort_keys=True)
    for private_value in (
        _PRIVATE_VALUES["md_front"],
        _PRIVATE_VALUES["td_front"],
        _PRIVATE_VALUES["broker_id"],
        _PRIVATE_VALUES["user_id"],
        _PRIVATE_VALUES["password"],
        _PRIVATE_VALUES["app_id"],
        _PRIVATE_VALUES["auth_code"],
    ):
        assert private_value not in public_text


def test_canonical_live_config_in_shared_simnow_directory_remains_non_authorizing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch, canonical=True)

    binding = require_ctp_production_execution_config_binding(config, registry, pin)

    assert config.strategy_dir == pin.runtime_registration.runtime_dir
    assert config.ctp is not None
    assert config.ctp_production is None
    assert binding.environment == "production"
    assert pin.account_binding_sha256 is None
    assert binding.account_binding_sha256 == production_account_binding_sha256(
        _PRIVATE_VALUES["broker_id"], _PRIVATE_VALUES["user_id"]
    )
    assert binding.approval_receipt_id.startswith("ctp-production:")
    assert binding.artifact_id.startswith("ctp-production:")
    assert binding.provider_access_authorized is False
    assert binding.credential_access_authorized is False
    assert binding.execution_authorized is False
    assert binding.external_writes_authorized is False
    # SimNow's ``acct_`` fingerprint and production's domain-separated
    # account binding intentionally differ even when selectors are identical.
    simnow_fingerprint = hashlib.sha256(
        f"{_PRIVATE_VALUES['broker_id']}:{_PRIVATE_VALUES['user_id']}".encode("utf-8")
    ).hexdigest()[:16]
    simnow_account_digest = hashlib.sha256(
        ("acct_" + simnow_fingerprint).encode("ascii")
    ).hexdigest()
    assert binding.account_binding_sha256 != simnow_account_digest


def test_dynamic_canonical_scope_tracks_effective_config_and_selected_front(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = dict(_PRIVATE_VALUES)
    values.pop("md_front")
    values.pop("td_front")
    values["front_pairs"] = [
        {"md_front": "tcp://192.0.2.11:41211", "td_front": "tcp://192.0.2.10:41201"},
        {"md_front": "tcp://192.0.2.21:41211", "td_front": "tcp://192.0.2.20:41201"},
    ]
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch, values, canonical=True)
    effective = resolve_runtime_config(config, registry)

    unresolved = require_ctp_production_execution_config_binding(
        config, registry, pin, effective_runtime=effective
    )
    selected = require_ctp_production_execution_config_binding(
        config,
        registry,
        pin,
        selected_front_pair=("tcp://192.0.2.21:41211", "tcp://192.0.2.20:41201"),
        effective_runtime=effective,
    )

    assert pin.scope_binding_mode == "sealed_config"
    assert pin.account_binding_sha256 is None
    assert pin.md_front is None and pin.td_front is None
    assert pin.instrument_id is None and pin.exchange_id is None and pin.hedge_flag is None
    assert unresolved.front_pairs == tuple(
        (pair["md_front"], pair["td_front"]) for pair in config.ctp.front_pairs
    )
    assert unresolved.selected_front_index is None
    assert unresolved.effective_digest == effective.effective_digest
    assert selected.selected_front_index == 1
    assert selected.md_front == "tcp://192.0.2.21:41211"
    assert selected.td_front == "tcp://192.0.2.20:41201"
    assert selected.front_pair_set_sha256 == unresolved.front_pair_set_sha256
    assert selected.scope_identity_sha256 != unresolved.scope_identity_sha256
    assert selected.provider_access_authorized is False
    assert selected.execution_authorized is False

    changed_values = dict(values)
    changed_values["instrument_id"] = "IH2612"
    changed_values["front_pairs"] = [
        values["front_pairs"][1],
        {"md_front": "tcp://192.0.2.31:41211", "td_front": "tcp://192.0.2.30:41201"},
    ]
    resealed = runtime_config._validate_schema(
        _document(changed_values, canonical=True),
        config.strategy_dir,
        config.source_path,
    )
    runtime_config._seal_loaded_runtime_config(resealed, registry)
    changed_effective = resolve_runtime_config(resealed, registry)
    changed = require_ctp_production_execution_config_binding(
        resealed, registry, pin, effective_runtime=changed_effective
    )

    assert changed.instrument_id == "IH2612"
    assert changed.front_pairs[1] == (
        "tcp://192.0.2.31:41211",
        "tcp://192.0.2.30:41201",
    )
    assert changed.effective_digest == changed_effective.effective_digest
    assert changed.scope_identity_sha256 != unresolved.scope_identity_sha256
    # This pure identity contract does not verify receipts. A separate trusted
    # verifier must bind a receipt to scope_identity_sha256 to reject it as stale.
    assert changed.approval_receipt_sha256 == unresolved.approval_receipt_sha256

    with pytest.raises(CtpProductionExecutionAdmissionError) as caught:
        require_ctp_production_execution_config_binding(
            resealed, registry, pin, effective_runtime=effective
        )
    assert caught.value.reason == "effective_config_mismatch"


def test_profile_scoped_live_scope_uses_sealed_profile_and_tracks_config_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_security_flags, security_checks = _stub_private_config_security_for_synthetic_test(
        monkeypatch
    )
    registry, registered, admission = _profile_scope_inputs(tmp_path)

    _write_profile_scope_config(tmp_path, mode="simulation", preset="sandbox")
    sandbox_config = runtime_config.load_runtime_config(tmp_path, registry=registry)
    sandbox_effective = resolve_runtime_config(sandbox_config, registry)
    assert sandbox_effective.profile is registered.profile_for("simulation", "sandbox")
    with pytest.raises(CtpProductionExecutionAdmissionError) as sandbox_rejected:
        require_ctp_production_execution_config_binding(
            sandbox_config,
            registry,
            admission,
            effective_runtime=sandbox_effective,
        )
    assert sandbox_rejected.value.reason == "runtime_contract_mismatch"

    live_values = dict(_PRIVATE_VALUES)
    live_values.update(
        md_front="tcp://192.0.2.31:41211",
        td_front="tcp://192.0.2.30:41201",
        instrument_id="IH2612",
        broker_id="synthetic-changed-production-broker",
        user_id="synthetic-changed-production-account",
    )
    _write_profile_scope_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        private_values=live_values,
    )
    live_config = runtime_config.load_runtime_config(tmp_path, registry=registry)
    live_effective = resolve_runtime_config(live_config, registry)
    assert live_effective.profile is registered.profile_for("live", "managed_live_direct")

    with pytest.raises(CtpProductionExecutionAdmissionError) as missing_effective:
        require_ctp_production_execution_config_binding(live_config, registry, admission)
    assert missing_effective.value.reason == "effective_config_required"

    with pytest.raises(CtpProductionExecutionAdmissionError) as stale_effective:
        require_ctp_production_execution_config_binding(
            live_config,
            registry,
            admission,
            effective_runtime=sandbox_effective,
        )
    assert stale_effective.value.reason == "effective_config_mismatch"

    binding = require_ctp_production_execution_config_binding(
        live_config, registry, admission, effective_runtime=live_effective
    )
    assert binding.md_front == live_values["md_front"]
    assert binding.td_front == live_values["td_front"]
    assert binding.instrument_id == "IH2612"
    assert binding.effective_digest == live_effective.effective_digest
    assert binding.provider_access_authorized is False
    assert binding.credential_access_authorized is False
    assert binding.execution_authorized is False
    assert binding.external_writes_authorized is False
    assert binding.order_submission_authorized is False
    assert binding.cancellation_authorized is False
    assert binding.arming_authorized is False

    prior_scope_identity = binding.scope_identity_sha256
    changed_values = dict(live_values)
    changed_values.update(
        md_front="tcp://192.0.2.41:41211",
        td_front="tcp://192.0.2.40:41201",
        broker_id="synthetic-later-production-broker",
        user_id="synthetic-later-production-account",
    )
    _write_profile_scope_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        private_values=changed_values,
    )
    changed_config = runtime_config.load_runtime_config(tmp_path, registry=registry)
    changed_effective = resolve_runtime_config(changed_config, registry)
    with pytest.raises(CtpProductionExecutionAdmissionError) as stale_config:
        require_ctp_production_execution_config_binding(
            changed_config,
            registry,
            admission,
            effective_runtime=live_effective,
        )
    assert stale_config.value.reason == "effective_config_mismatch"

    changed_binding = require_ctp_production_execution_config_binding(
        changed_config,
        registry,
        admission,
        effective_runtime=changed_effective,
    )
    assert changed_binding.scope_identity_sha256 != prior_scope_identity
    assert changed_binding.account_binding_sha256 != binding.account_binding_sha256
    assert changed_binding.front_pair_sha256 != binding.front_pair_sha256
    assert private_security_flags == [True, True, True]
    assert len(security_checks) == 2 * len(private_security_flags)

    with pytest.raises(CtpProductionExecutionAdmissionError) as stale_front:
        require_ctp_production_execution_config_binding(
            changed_config,
            registry,
            admission,
            selected_front_pair=(live_values["md_front"], live_values["td_front"]),
            effective_runtime=changed_effective,
        )
    assert stale_front.value.reason == "production_front_selection_mismatch"


@pytest.mark.parametrize(
    "profile_changes",
    (
        {"available_capabilities": MANAGED_WRITE_CAPABILITIES + ("gateway",)},
        {"allowed_secrets_refs": ("config_yaml", "none")},
        {"allowed_parameter_keys": ("strategy_tuning",)},
        {"approval_receipt_digest": "e" * 64},
    ),
    ids=("capabilities", "secrets", "parameter-keys", "receipt"),
)
def test_profile_scoped_production_rejects_nonexact_live_profile_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile_changes: dict[str, Any],
) -> None:
    private_security_flags, security_checks = _stub_private_config_security_for_synthetic_test(
        monkeypatch
    )
    registry, _, admission = _profile_scope_inputs(tmp_path, live_profile_changes=profile_changes)
    _write_profile_scope_config(tmp_path, mode="live", preset="managed_live_direct")
    config = runtime_config.load_runtime_config(tmp_path, registry=registry)
    effective = resolve_runtime_config(config, registry)

    with pytest.raises(CtpProductionExecutionAdmissionError) as rejected:
        require_ctp_production_execution_config_binding(
            config, registry, admission, effective_runtime=effective
        )

    assert rejected.value.reason == "runtime_contract_mismatch"
    assert private_security_flags == [True]
    assert len(security_checks) == 2


def test_profile_scoped_production_rejects_sealed_effective_policy_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_private_config_security_for_synthetic_test(monkeypatch)
    registry, _, admission = _profile_scope_inputs(tmp_path)
    _write_profile_scope_config(tmp_path, mode="live", preset="managed_live_direct")
    config = runtime_config.load_runtime_config(tmp_path, registry=registry)
    effective = resolve_runtime_config(config, registry)

    # Issue a test-only resolver seal for an inconsistent result so the
    # admission's explicit policy contract is exercised after seal validation.
    from backtrader_runtime.registry import _seal_effective_runtime_config

    drifted_effective = replace(
        effective,
        policy=replace(effective.policy, environment="sandbox"),
        order_route="read_only",
        account_access="public_read",
        allows_production_writes=False,
    )
    _seal_effective_runtime_config(drifted_effective, registry)

    with pytest.raises(CtpProductionExecutionAdmissionError) as rejected:
        require_ctp_production_execution_config_binding(
            config, registry, admission, effective_runtime=drifted_effective
        )

    assert rejected.value.reason == "runtime_contract_mismatch"


def test_live_profile_shape_rejects_offline_execution_and_receipt_required_sandbox() -> None:
    with pytest.raises(ValueError, match="restricted to simulation/replay"):
        RuntimeProfile(
            mode="live",
            preset="managed_live_direct",
            allowed_parameter_keys=(),
            allowed_secrets_refs=("config_yaml",),
            available_capabilities=MANAGED_WRITE_CAPABILITIES,
            approval_receipt_digest=_PROFILE_RECEIPT_SHA256,
            runner_module=None,
            runner_entrypoint="run_runtime",
            capability_modules=(),
            offline_managed_execution=True,
            sandbox_write_policy="deny",
        )

    with pytest.raises(ValueError, match="receipt-required profile policy needs the sandbox"):
        RuntimeProfile(
            mode="live",
            preset="managed_live_direct",
            allowed_parameter_keys=(),
            allowed_secrets_refs=("config_yaml",),
            available_capabilities=MANAGED_WRITE_CAPABILITIES,
            approval_receipt_digest=_PROFILE_RECEIPT_SHA256,
            runner_module=None,
            runner_entrypoint="run_runtime",
            capability_modules=(),
            offline_managed_execution=False,
            sandbox_write_policy="receipt_required",
        )


def test_managed_composition_uses_one_sealed_scope_across_fake_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = dict(_PRIVATE_VALUES)
    values.pop("md_front")
    values.pop("td_front")
    values["front_pairs"] = [
        {"md_front": "tcp://192.0.2.11:41211", "td_front": "tcp://192.0.2.10:41201"},
        {"md_front": "tcp://192.0.2.21:41211", "td_front": "tcp://192.0.2.20:41201"},
    ]
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch, values, canonical=True)
    effective = resolve_runtime_config(config, registry)
    binding_calls = []
    original_binding = production_composition.require_ctp_production_execution_config_binding

    def observe_binding(*args, **kwargs):
        binding_calls.append((args[0], args[1], args[2], kwargs.get("effective_runtime")))
        return original_binding(*args, **kwargs)

    selector_calls = []

    def fake_selector(front_pairs, **kwargs):
        selector_calls.append(tuple(front_pairs))
        return _fake_production_front_selection(
            front_pairs,
            timeout_seconds=kwargs["timeout_seconds"],
            repeated_samples=kwargs["repeated_samples"],
        )

    monkeypatch.setattr(
        production_composition,
        "require_ctp_production_execution_config_binding",
        observe_binding,
    )
    monkeypatch.setattr(production_composition, "select_ctp_front_pair", fake_selector)
    import_attempts = []
    socket_attempts = []
    write_attempts = []
    original_import = builtins.__import__
    original_open = builtins.open
    original_os_open = os.open

    def reject_provider_import(name, *args, **kwargs):
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in (
                "bt_api_ctp",
                "bt_api_py",
                "bt_api_base",
                "backtrader_runtime.credential_resolver",
                "backtrader_runtime.ctp_production_credentials",
            )
        ):
            import_attempts.append(name)
            raise AssertionError("scope selector attempted credential or SDK import")
        return original_import(name, *args, **kwargs)

    def reject_socket(*args, **kwargs):
        socket_attempts.append((args, kwargs))
        raise AssertionError("fake-selector scope test attempted network I/O")

    def observe_open(path, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            write_attempts.append((path, mode))
            raise AssertionError("scope selector attempted a filesystem write")
        return original_open(path, mode, *args, **kwargs)

    def observe_os_open(path, flags, *args, **kwargs):
        write_mask = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        if flags & write_mask:
            write_attempts.append((path, flags))
            raise AssertionError("scope selector attempted a low-level filesystem write")
        return original_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_provider_import)
    monkeypatch.setattr(builtins, "open", observe_open)
    monkeypatch.setattr(io, "open", observe_open)
    monkeypatch.setattr(os, "open", observe_os_open)
    monkeypatch.setattr(socket, "socket", reject_socket)

    selection = production_composition.select_ctp_production_managed_config_scope(
        config=config,
        registry=registry,
        admission_registration=pin,
        effective_runtime=effective,
    )
    initial_scope_identity = selection.binding.scope_identity_sha256

    assert selector_calls == [
        tuple(
            {"md_front": pair["md_front"], "td_front": pair["td_front"]}
            for pair in values["front_pairs"]
        )
    ]
    assert len(binding_calls) == 2
    for binding_call in binding_calls:
        assert binding_call[0] is config
        assert binding_call[1] is registry
        assert binding_call[2] is pin
        assert binding_call[3] is effective
    assert selection.selected_front_index == 1
    assert selection.binding.selected_front_index == 1
    assert selection.binding.effective_digest == effective.effective_digest
    assert selection.binding.instrument_id == "IF2612"
    assert selection.approval_receipt_verified is False
    assert selection.artifact_verified is False
    assert selection.credentials_resolved is False
    assert selection.provider_access_authorized is False
    assert selection.execution_authorized is False
    assert selection.external_writes_authorized is False
    assert selection.order_submission_authorized is False
    assert selection.cancellation_authorized is False
    assert selection.arming_authorized is False
    public_text = json.dumps(selection.as_public_dict(), sort_keys=True)
    assert selection.as_public_dict()["effective_digest"] == effective.effective_digest
    assert selection.as_public_dict()["scope_identity_sha256"] == initial_scope_identity
    for private_value in (
        values["front_pairs"][0]["md_front"],
        values["front_pairs"][0]["td_front"],
        values["front_pairs"][1]["md_front"],
        values["front_pairs"][1]["td_front"],
        values["broker_id"],
        values["user_id"],
        values["password"],
        values["app_id"],
        values["auth_code"],
    ):
        assert private_value not in public_text

    changed_values = dict(values)
    changed_values["instrument_id"] = "IH2612"
    changed_values["front_pairs"] = [
        values["front_pairs"][0],
        {"md_front": "tcp://192.0.2.31:41211", "td_front": "tcp://192.0.2.30:41201"},
    ]
    changed_config = runtime_config._validate_schema(
        _document(changed_values, canonical=True),
        config.strategy_dir,
        config.source_path,
    )
    runtime_config._seal_loaded_runtime_config(changed_config, registry)
    changed_effective = resolve_runtime_config(changed_config, registry)
    changed_selection = production_composition.select_ctp_production_managed_config_scope(
        config=changed_config,
        registry=registry,
        admission_registration=pin,
        effective_runtime=changed_effective,
    )

    assert changed_selection.binding.instrument_id == "IH2612"
    assert changed_selection.binding.front_pairs[1] == (
        "tcp://192.0.2.31:41211",
        "tcp://192.0.2.30:41201",
    )
    assert changed_selection.binding.scope_identity_sha256 != initial_scope_identity
    assert not import_attempts
    assert not socket_attempts
    assert not write_attempts


def test_dynamic_managed_composition_requires_effective_runtime_before_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch, canonical=True)
    selector_calls = []
    monkeypatch.setattr(
        production_composition,
        "select_ctp_front_pair",
        lambda *args, **kwargs: selector_calls.append((args, kwargs)),
    )

    with pytest.raises(production_composition.CtpProductionManagedCompositionError) as caught:
        production_composition.select_ctp_production_managed_config_scope(
            config=config,
            registry=registry,
            admission_registration=pin,
        )

    assert caught.value.reason == "sealed_effective_runtime_required"
    assert not selector_calls


def test_profile_scoped_live_composition_selects_only_non_authorizing_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_security_flags, security_checks = _stub_private_config_security_for_synthetic_test(
        monkeypatch
    )
    values = dict(_PRIVATE_VALUES)
    values.pop("md_front")
    values.pop("td_front")
    values["front_pairs"] = [
        {"md_front": "tcp://192.0.2.11:41211", "td_front": "tcp://192.0.2.10:41201"},
        {"md_front": "tcp://192.0.2.21:41211", "td_front": "tcp://192.0.2.20:41201"},
    ]
    registry, registered, admission = _profile_scope_inputs(tmp_path)
    _write_profile_scope_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        private_values=values,
    )
    config = runtime_config.load_runtime_config(tmp_path, registry=registry)
    effective = resolve_runtime_config(config, registry)
    assert effective.profile is registered.profile_for("live", "managed_live_direct")
    assert config.strategy_dir.resolve() == registered.runtime_dir.resolve()
    assert config.source_path.resolve() == (registered.runtime_dir / "config.yaml").resolve()

    selector_calls = []
    def fake_selector(front_pairs, **kwargs):
        selector_calls.append(tuple(front_pairs))
        return _fake_production_front_selection(
            front_pairs,
            timeout_seconds=kwargs["timeout_seconds"],
            repeated_samples=kwargs["repeated_samples"],
        )

    monkeypatch.setattr(production_composition, "select_ctp_front_pair", fake_selector)
    import_attempts, socket_attempts, write_attempts = _install_provider_access_guards(monkeypatch)
    security_check_count = len(security_checks)

    selection = production_composition.select_ctp_production_managed_config_scope(
        config=config,
        registry=registry,
        admission_registration=admission,
        effective_runtime=effective,
    )

    assert selector_calls == [
        tuple(
            {"md_front": pair["md_front"], "td_front": pair["td_front"]}
            for pair in values["front_pairs"]
        )
    ]
    assert selection.selected_front_index == 1
    assert selection.binding.selected_front_index == 1
    assert selection.binding.effective_digest == effective.effective_digest
    assert selection.binding.md_front == values["front_pairs"][1]["md_front"]
    assert selection.binding.td_front == values["front_pairs"][1]["td_front"]
    assert selection.approval_receipt_verified is False
    assert selection.artifact_verified is False
    assert selection.credentials_resolved is False
    assert selection.provider_access_authorized is False
    assert selection.execution_authorized is False
    assert selection.external_writes_authorized is False
    assert selection.order_submission_authorized is False
    assert selection.cancellation_authorized is False
    assert selection.arming_authorized is False
    assert not import_attempts
    assert not socket_attempts
    assert not write_attempts
    assert len(security_checks) == security_check_count
    assert private_security_flags == [True]


@pytest.mark.parametrize("stale_kind", ("effective", "approval"))
def test_profile_scoped_composition_rejects_stale_effective_or_approval_before_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stale_kind: str,
) -> None:
    _stub_private_config_security_for_synthetic_test(monkeypatch)
    values = dict(_PRIVATE_VALUES)
    registry, registered, admission = _profile_scope_inputs(tmp_path)
    _write_profile_scope_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        private_values=values,
    )
    original_config = runtime_config.load_runtime_config(tmp_path, registry=registry)
    original_effective = resolve_runtime_config(original_config, registry)

    config = original_config
    effective = original_effective
    current_admission = admission
    if stale_kind == "effective":
        changed_values = dict(values)
        changed_values["instrument_id"] = "IH2612"
        _write_profile_scope_config(
            tmp_path,
            mode="live",
            preset="managed_live_direct",
            private_values=changed_values,
        )
        config = runtime_config.load_runtime_config(tmp_path, registry=registry)
        assert config.source_path.resolve() == original_config.source_path.resolve()
        effective = original_effective
    else:
        current_admission = replace(admission, approval_receipt_sha256="e" * 64)

    selector_calls = []
    monkeypatch.setattr(
        production_composition,
        "select_ctp_front_pair",
        lambda *args, **kwargs: selector_calls.append((args, kwargs)),
    )
    import_attempts, socket_attempts, write_attempts = _install_provider_access_guards(monkeypatch)

    with pytest.raises(production_composition.CtpProductionManagedCompositionError) as caught:
        production_composition.select_ctp_production_managed_config_scope(
            config=config,
            registry=registry,
            admission_registration=current_admission,
            effective_runtime=effective,
        )

    assert caught.value.reason == "production_execution_config_rejected"
    assert not selector_calls
    assert not import_attempts
    assert not socket_attempts
    assert not write_attempts


def test_default_unavailable_live_profile_rejects_before_private_config_or_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION
    assert registered.profile_for("live", "managed_live_direct") is None
    assert any(
        (item.mode, item.preset, item.reason)
        == ("live", "managed_live_direct", "managed_live_direct_profile_unavailable")
        for item in registered.unavailable_mode_profiles
    )
    registry = RuntimeRegistry((registered,), registry_id="test.default.ctp.live.unavailable")
    _synthetic_registry, _synthetic_runtime, synthetic_admission = _profile_scope_inputs(tmp_path)
    admission = replace(synthetic_admission, runtime_registration=registered)

    monkeypatch.setattr(runtime_config, "CTP_PRODUCTION_RUNTIME_DIR", registered.runtime_dir)
    config = runtime_config._validate_schema(
        _document(canonical=True),
        registered.runtime_dir,
        registered.runtime_dir / "config.yaml",
    )
    runtime_config._seal_loaded_runtime_config(config, registry)

    selector_calls = []
    monkeypatch.setattr(
        production_composition,
        "select_ctp_front_pair",
        lambda *args, **kwargs: selector_calls.append((args, kwargs)),
    )
    import_attempts, socket_attempts, write_attempts = _install_provider_access_guards(monkeypatch)

    with pytest.raises(production_composition.CtpProductionManagedCompositionError) as caught:
        production_composition.select_ctp_production_managed_config_scope(
            config=config,
            registry=registry,
            admission_registration=admission,
        )

    assert caught.value.reason == "profile_dispatch_unavailable"
    assert not selector_calls
    assert not import_attempts
    assert not socket_attempts
    assert not write_attempts


def test_profile_scoped_composition_rejects_fake_pair_outside_sealed_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_private_config_security_for_synthetic_test(monkeypatch)
    values = dict(_PRIVATE_VALUES)
    values.pop("md_front")
    values.pop("td_front")
    values["front_pairs"] = [
        {"md_front": "tcp://192.0.2.11:41211", "td_front": "tcp://192.0.2.10:41201"},
        {"md_front": "tcp://192.0.2.21:41211", "td_front": "tcp://192.0.2.20:41201"},
    ]
    registry, _registered, admission = _profile_scope_inputs(tmp_path)
    _write_profile_scope_config(
        tmp_path,
        mode="live",
        preset="managed_live_direct",
        private_values=values,
    )
    config = runtime_config.load_runtime_config(tmp_path, registry=registry)
    effective = resolve_runtime_config(config, registry)
    selector_calls = []

    def outside_selector(front_pairs, **kwargs):
        selector_calls.append(tuple(front_pairs))
        return _fake_production_front_selection(
            front_pairs,
            timeout_seconds=kwargs["timeout_seconds"],
            repeated_samples=kwargs["repeated_samples"],
            fault="outside_config",
        )

    monkeypatch.setattr(production_composition, "select_ctp_front_pair", outside_selector)
    import_attempts, socket_attempts, write_attempts = _install_provider_access_guards(monkeypatch)

    with pytest.raises(production_composition.CtpProductionManagedCompositionError) as caught:
        production_composition.select_ctp_production_managed_config_scope(
            config=config,
            registry=registry,
            admission_registration=admission,
            effective_runtime=effective,
        )

    assert caught.value.reason == "front_selection_outside_config"
    assert len(selector_calls) == 1
    assert not import_attempts
    assert not socket_attempts
    assert not write_attempts


@pytest.mark.parametrize(
    "fault",
    ("mismatched_index_pair", "unreachable_selected", "latency_mismatch"),
)
def test_managed_composition_rejects_malformed_fake_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    values = dict(_PRIVATE_VALUES)
    values.pop("md_front")
    values.pop("td_front")
    values["front_pairs"] = [
        {"md_front": "tcp://192.0.2.11:41211", "td_front": "tcp://192.0.2.10:41201"},
        {"md_front": "tcp://192.0.2.21:41211", "td_front": "tcp://192.0.2.20:41201"},
    ]
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch, values, canonical=True)
    effective = resolve_runtime_config(config, registry)
    selector_calls = []

    def malformed_selector(front_pairs, **kwargs):
        selector_calls.append(tuple(front_pairs))
        return _fake_production_front_selection(
            front_pairs,
            timeout_seconds=kwargs["timeout_seconds"],
            repeated_samples=kwargs["repeated_samples"],
            fault=fault,
        )

    monkeypatch.setattr(production_composition, "select_ctp_front_pair", malformed_selector)

    with pytest.raises(production_composition.CtpProductionManagedCompositionError) as caught:
        production_composition.select_ctp_production_managed_config_scope(
            config=config,
            registry=registry,
            admission_registration=pin,
            effective_runtime=effective,
        )

    assert caught.value.reason == "front_selection_outside_config"
    assert len(selector_calls) == 1


@pytest.mark.parametrize(
    "field_name,changed_value",
    (
        ("md_front", "tcp://192.0.2.21:41211"),
        ("td_front", "tcp://192.0.2.20:41201"),
        ("broker_id", "another-production-broker"),
        ("user_id", "another-production-account"),
        ("instrument_id", "IH2612"),
        ("exchange_id", "SHFE"),
        ("hedge_flag", "2"),
    ),
)
def test_resealed_canonical_config_at_same_path_derives_fresh_scope_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    changed_value: str,
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch, canonical=True)
    values = dict(_PRIVATE_VALUES)
    values[field_name] = changed_value
    resealed = runtime_config._validate_schema(
        _document(values, canonical=True),
        config.strategy_dir,
        config.source_path,
    )
    runtime_config._seal_loaded_runtime_config(resealed, registry)

    assert resealed.strategy_dir == config.strategy_dir
    assert resealed.source_path == config.source_path
    assert resealed is not config
    if field_name in ("broker_id", "user_id"):
        # Account selectors stay out of the public config digest; their fresh
        # private-loader seal and derived scope identity still change.
        assert resealed.config_digest == config.config_digest
    else:
        assert resealed.config_digest != config.config_digest
    baseline = require_ctp_production_execution_config_binding(config, registry, pin)
    changed = require_ctp_production_execution_config_binding(resealed, registry, pin)
    assert changed.scope_identity_sha256 != baseline.scope_identity_sha256
    assert changed.config_digest == resealed.config_digest
    assert changed.instrument_id == values["instrument_id"]
    assert changed.exchange_id == values["exchange_id"]
    assert changed.hedge_flag == values["hedge_flag"]
    assert changed.account_binding_sha256 == production_account_binding_sha256(
        values["broker_id"], values["user_id"]
    )
    assert (changed.md_front, changed.td_front) == (values["md_front"], values["td_front"])
    assert len(changed.scope_identity_sha256) == 64
    assert set(changed.scope_identity_sha256) <= set("0123456789abcdef")


def test_resealed_runtime_with_replaced_approval_digest_rejects_old_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch, canonical=True)
    updated_runtime = replace(
        pin.runtime_registration,
        approval_receipt_digest="c" * 64,
    )
    updated_registry = RuntimeRegistry((updated_runtime,))
    resealed = runtime_config._validate_schema(
        _document(canonical=True), config.strategy_dir, config.source_path
    )
    runtime_config._seal_loaded_runtime_config(resealed, updated_registry)
    stale_receipt_registration = replace(pin, runtime_registration=updated_runtime)

    with pytest.raises(CtpProductionExecutionAdmissionError) as caught:
        require_ctp_production_execution_config_binding(
            resealed, updated_registry, stale_receipt_registration
        )

    assert caught.value.reason == "runtime_contract_mismatch"
    assert stale_receipt_registration.approval_receipt_sha256 == _RECEIPT_SHA256


def test_contract_does_not_import_sdk_or_open_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    import_attempts = []
    socket_attempts = []
    original_import = builtins.__import__

    def reject_sdk_import(name, *args, **kwargs):
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in ("bt_api_ctp", "bt_api_py", "bt_api_base")
        ):
            import_attempts.append(name)
            raise AssertionError("production scope contract attempted SDK import")
        return original_import(name, *args, **kwargs)

    def reject_socket(*args, **kwargs):
        socket_attempts.append((args, kwargs))
        raise AssertionError("production scope contract attempted network I/O")

    monkeypatch.setattr(builtins, "__import__", reject_sdk_import)
    monkeypatch.setattr(socket, "socket", reject_socket)

    require_ctp_production_execution_config_binding(config, registry, pin)

    assert not import_attempts
    assert not socket_attempts


@pytest.mark.parametrize(
    "field_name,value,reason",
    (
        ("environment", "simnow_set1", "environment_mismatch"),
        ("approval_receipt_id", "simnow:receipt.001", "invalid_registration"),
        ("artifact_id", "simnow:artifact.001", "invalid_registration"),
        ("approval_receipt_id", _ARTIFACT_ID, "invalid_registration"),
        ("approval_receipt_sha256", _ARTIFACT_SHA256, "invalid_registration"),
        ("allowed_offsets", ("CLOSE",), "unsupported_order_offsets"),
        ("quantity_step", 0, "invalid_order_limits"),
        ("max_order_quantity", 0, "invalid_order_limits"),
        ("max_gross_position", 2, "invalid_order_limits"),
        ("max_price", Decimal("200.1"), "invalid_order_limits"),
        ("max_order_notional", Decimal("1"), "invalid_order_limits"),
    ),
)
def test_invalid_production_identities_or_order_envelope_are_rejected(
    tmp_path: Path,
    field_name: str,
    value: Any,
    reason: str,
) -> None:
    runtime = RegisteredRuntime(
        runtime_dir=tmp_path,
        strategy_id="example.007_ctp.production",
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=MANAGED_WRITE_CAPABILITIES,
        approval_receipt_digest=_RECEIPT_SHA256,
    )
    arguments = {
        "runtime_registration": runtime,
        "environment": "production",
        "account_binding_sha256": "c" * 64,
        "md_front": "tcp://192.0.2.11:41211",
        "td_front": "tcp://192.0.2.10:41201",
        "instrument_id": "IF2612",
        "exchange_id": "CFFEX",
        "hedge_flag": "1",
        "approval_receipt_id": _RECEIPT_ID,
        "approval_receipt_sha256": _RECEIPT_SHA256,
        "artifact_id": _ARTIFACT_ID,
        "artifact_sha256": _ARTIFACT_SHA256,
        "allowed_sides": ("BUY", "SELL"),
        "allowed_offsets": ("OPEN",),
        "quantity_step": 1,
        "max_order_quantity": 3,
        "max_gross_position": 6,
        "min_price": Decimal("100"),
        "max_price": Decimal("200"),
        "price_tick": Decimal("0.2"),
        "max_order_notional": Decimal("600"),
    }
    arguments[field_name] = value

    with pytest.raises(CtpProductionExecutionAdmissionError) as caught:
        CtpProductionExecutionRegistration(**arguments)

    assert caught.value.reason == reason
    assert "simnow" not in str(caught.value).lower()


def test_gross_position_limit_must_align_to_quantity_step(tmp_path: Path) -> None:
    runtime = RegisteredRuntime(
        runtime_dir=tmp_path,
        strategy_id="example.007_ctp.production",
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=MANAGED_WRITE_CAPABILITIES,
        approval_receipt_digest=_RECEIPT_SHA256,
    )
    arguments = {
        "runtime_registration": runtime,
        "environment": "production",
        "account_binding_sha256": "c" * 64,
        "md_front": "tcp://192.0.2.11:41211",
        "td_front": "tcp://192.0.2.10:41201",
        "instrument_id": "IF2612",
        "exchange_id": "CFFEX",
        "hedge_flag": "1",
        "approval_receipt_id": _RECEIPT_ID,
        "approval_receipt_sha256": _RECEIPT_SHA256,
        "artifact_id": _ARTIFACT_ID,
        "artifact_sha256": _ARTIFACT_SHA256,
        "allowed_sides": ("BUY",),
        "allowed_offsets": ("OPEN",),
        "quantity_step": 2,
        "max_order_quantity": 4,
        "max_gross_position": 5,
        "min_price": Decimal("100"),
        "max_price": Decimal("200"),
        "price_tick": Decimal("0.2"),
        "max_order_notional": Decimal("400"),
    }

    with pytest.raises(CtpProductionExecutionAdmissionError) as caught:
        CtpProductionExecutionRegistration(**arguments)

    assert caught.value.reason == "invalid_order_limits"


@pytest.mark.parametrize(
    "field_name,changed_value",
    (
        ("md_front", "tcp://192.0.2.21:41211"),
        ("td_front", "tcp://192.0.2.20:41201"),
        ("broker_id", "another-production-broker"),
        ("user_id", "another-production-account"),
        ("instrument_id", "IH2612"),
        ("exchange_id", "SHFE"),
        ("hedge_flag", "2"),
    ),
)
def test_config_selectors_must_match_the_code_owned_execution_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    changed_value: str,
) -> None:
    private_values = dict(_PRIVATE_VALUES)
    private_values[field_name] = changed_value
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch, private_values)

    with pytest.raises(CtpProductionExecutionAdmissionError) as caught:
        require_ctp_production_execution_config_binding(config, registry, pin)

    assert caught.value.reason == "production_pin_mismatch"
    assert changed_value not in str(caught.value)


def test_unsealed_config_and_cross_registry_reuse_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    unsealed = runtime_config._validate_schema(_document(), tmp_path, tmp_path / "config.yaml")
    with pytest.raises(CtpProductionExecutionAdmissionError) as unsealed_error:
        require_ctp_production_execution_config_binding(unsealed, registry, pin)
    assert unsealed_error.value.reason == "config_provenance_invalid"

    other_registry = RuntimeRegistry((pin.runtime_registration,))
    with pytest.raises(CtpProductionExecutionAdmissionError) as cross_registry_error:
        require_ctp_production_execution_config_binding(config, other_registry, pin)
    assert cross_registry_error.value.reason == "config_provenance_invalid"


def test_mutated_registration_and_runtime_registration_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    object.__setattr__(pin, "md_front", "tcp://192.0.2.90:41211")
    with pytest.raises(CtpProductionExecutionAdmissionError) as changed_pin:
        require_ctp_production_execution_config_binding(config, registry, pin)
    assert changed_pin.value.reason == "registration_provenance_invalid"
    with pytest.raises(CtpProductionExecutionAdmissionError) as repeated_changed_pin:
        require_ctp_production_execution_config_binding(config, registry, pin)
    assert repeated_changed_pin.value.reason == "registration_provenance_invalid"

    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    object.__setattr__(pin.runtime_registration, "strategy_id", "another.strategy")
    with pytest.raises(CtpProductionExecutionAdmissionError) as changed_runtime:
        require_ctp_production_execution_config_binding(config, registry, pin)
    assert changed_runtime.value.reason == "registration_provenance_invalid"
    with pytest.raises(CtpProductionExecutionAdmissionError) as repeated_changed_runtime:
        require_ctp_production_execution_config_binding(config, registry, pin)
    assert repeated_changed_runtime.value.reason == "registration_provenance_invalid"


def test_current_read_only_runtime_cannot_satisfy_production_execution_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime_config, "CTP_PRODUCTION_RUNTIME_DIR", tmp_path)
    runtime = RegisteredRuntime(
        runtime_dir=tmp_path,
        strategy_id="example.007_ctp.production",
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
    )
    registry = RuntimeRegistry((runtime,))
    config = runtime_config._validate_schema(_document(), tmp_path, tmp_path / "config.yaml")
    runtime_config._seal_loaded_runtime_config(config, registry)
    pin = CtpProductionExecutionRegistration(
        runtime_registration=runtime,
        environment="production",
        account_binding_sha256=production_account_binding_sha256(
            _PRIVATE_VALUES["broker_id"], _PRIVATE_VALUES["user_id"]
        ),
        md_front=_PRIVATE_VALUES["md_front"],
        td_front=_PRIVATE_VALUES["td_front"],
        instrument_id=_PRIVATE_VALUES["instrument_id"],
        exchange_id=_PRIVATE_VALUES["exchange_id"],
        hedge_flag=_PRIVATE_VALUES["hedge_flag"],
        approval_receipt_id=_RECEIPT_ID,
        approval_receipt_sha256=_RECEIPT_SHA256,
        artifact_id=_ARTIFACT_ID,
        artifact_sha256=_ARTIFACT_SHA256,
        allowed_sides=("BUY",),
        allowed_offsets=("OPEN",),
        quantity_step=1,
        max_order_quantity=1,
        max_gross_position=1,
        min_price=Decimal("100"),
        max_price=Decimal("200"),
        price_tick=Decimal("0.2"),
        max_order_notional=Decimal("100"),
    )

    with pytest.raises(CtpProductionExecutionAdmissionError) as caught:
        require_ctp_production_execution_config_binding(config, registry, pin)

    assert caught.value.reason == "runtime_contract_mismatch"
