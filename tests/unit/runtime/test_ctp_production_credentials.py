"""Fake ACL-gate tests for production CTP credentials; no provider or OS ACL access."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Optional

import pytest

import backtrader_runtime.config as runtime_config
import backtrader_runtime.ctp_production_credentials as production_credentials
from backtrader_runtime import RegisteredRuntime, RuntimeRegistry
from backtrader_runtime.credential_resolver import CredentialResolutionError
from backtrader_runtime.ctp_production_readonly_admission import (
    CtpProductionReadOnlyRegistration,
    production_account_binding_sha256,
)
from backtrader_runtime.ctp_production_credentials import (
    CtpProductionCredentialResolutionError,
    require_ctp_production_credentials_seal,
    resolve_ctp_production_credentials,
)


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


def _document(private_values: Optional[dict] = None, *, canonical: bool = True) -> dict:
    private_block = dict(_PRIVATE_VALUES if private_values is None else private_values)
    return {
        "config_schema_version": 4,
        "strategy": {
            "id": "example.013_3.sa_midfreq_simnow"
            if canonical
            else "example.007_ctp.production"
        },
        "runtime": {"mode": "live", "preset": "managed_live_direct"},
        "parameters": {},
        "secrets_ref": "config_yaml",
        "ctp" if canonical else "ctp_production": private_block,
    }


def _bound_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    private_values: Optional[dict] = None,
    *,
    canonical: bool = True,
):
    runtime_dir = tmp_path / "runtime-ctp-private" if canonical else tmp_path
    if canonical:
        runtime_dir.mkdir()
    monkeypatch.setattr(runtime_config, "CTP_PRODUCTION_RUNTIME_DIR", runtime_dir)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id=(
            "example.013_3.sa_midfreq_simnow"
            if canonical
            else "example.007_ctp.production"
        ),
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
    )
    registry = RuntimeRegistry((registration,))
    config = runtime_config._validate_schema(
        _document(private_values, canonical=canonical),
        runtime_dir,
        runtime_dir / "config.yaml",
    )
    runtime_config._seal_loaded_runtime_config(config, registry)
    pin = CtpProductionReadOnlyRegistration(
        runtime_registration=registration,
        environment="production",
        account_binding_sha256=production_account_binding_sha256(
            _PRIVATE_VALUES["broker_id"], _PRIVATE_VALUES["user_id"]
        ),
        md_front=_PRIVATE_VALUES["md_front"],
        td_front=_PRIVATE_VALUES["td_front"],
        instrument_id=_PRIVATE_VALUES["instrument_id"],
        exchange_id=_PRIVATE_VALUES["exchange_id"],
        hedge_flag=_PRIVATE_VALUES["hedge_flag"],
    )
    return config, registry, pin


def _install_fake_acl_gate(monkeypatch: pytest.MonkeyPatch, *, reject: bool = False) -> list:
    calls = []

    def fake_windows_acl(_view, _registry):
        calls.append("windows_acl")
        if reject:
            raise CredentialResolutionError(
                "config_yaml_windows_acl_unavailable", "synthetic ACL rejection"
            )

    monkeypatch.setattr(production_credentials, "_platform_name", lambda: "nt")
    monkeypatch.setattr(
        production_credentials, "_require_windows_private_config_acl", fake_windows_acl
    )
    return calls


def test_credentials_follow_exact_production_pin_and_recheck_acl_before_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    acl_calls = _install_fake_acl_gate(monkeypatch)

    credentials = resolve_ctp_production_credentials(config, registry, pin)

    assert credentials.source == "config_yaml"
    assert credentials.scope.provider_environment == "production"
    assert credentials.scope.policy_environment == "production"
    assert credentials.scope.mode == "live"
    assert credentials.scope.preset == "managed_live_direct"
    assert credentials.scope.secrets_ref == "config_yaml"
    assert credentials.credential_names == (
        "broker_id",
        "user_id",
        "password",
        "app_id",
        "auth_code",
    )
    assert acl_calls == ["windows_acl"]
    assert credentials.require_credential("password") == _PRIVATE_VALUES["password"]
    assert acl_calls == ["windows_acl", "windows_acl"]
    require_ctp_production_credentials_seal(
        credentials,
        config=config,
        registry=registry,
        admission_registration=pin,
    )
    assert acl_calls == ["windows_acl", "windows_acl", "windows_acl"]
    assert credentials.provider_connected is False
    assert credentials.provider_session_verified is False
    assert credentials.execution_authorized is False
    assert credentials.external_writes_authorized is False
    with pytest.raises(TypeError, match="not provider or execution authorization"):
        bool(credentials)

    public_text = json.dumps(credentials.as_public_dict(), sort_keys=True)
    assert _PRIVATE_VALUES["md_front"] not in public_text
    assert _PRIVATE_VALUES["td_front"] not in public_text
    assert _PRIVATE_VALUES["user_id"] not in public_text
    assert _PRIVATE_VALUES["password"] not in public_text
    assert _PRIVATE_VALUES["auth_code"] not in repr(credentials)


def test_credentials_can_resolve_from_canonical_live_ctp_schema_in_simnow_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch, canonical=True)
    acl_calls = _install_fake_acl_gate(monkeypatch)

    credentials = resolve_ctp_production_credentials(config, registry, pin)

    assert config.ctp is not None
    assert config.ctp_production is None
    assert credentials.require_credential("password") == _PRIVATE_VALUES["password"]
    assert credentials.scope.runtime_id == pin.runtime_registration.runtime_id
    assert credentials.execution_authorized is False
    assert credentials.external_writes_authorized is False
    assert acl_calls == ["windows_acl", "windows_acl"]


def test_legacy_production_block_is_rejected_before_acl_or_secret_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch, canonical=False)
    acl_calls = _install_fake_acl_gate(monkeypatch)
    assert config.ctp is None
    assert config.ctp_production is not None

    with pytest.raises(CtpProductionCredentialResolutionError) as caught:
        resolve_ctp_production_credentials(config, registry, pin)

    assert caught.value.reason == "production_credential_binding_rejected"
    assert acl_calls == []
    assert _PRIVATE_VALUES["password"] not in str(caught.value)


def test_bad_config_pin_is_rejected_before_acl_or_secret_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    acl_calls = _install_fake_acl_gate(monkeypatch)
    object.__setattr__(config.ctp, "td_front", "tcp://192.0.2.90:41201")

    with pytest.raises(CtpProductionCredentialResolutionError) as caught:
        resolve_ctp_production_credentials(config, registry, pin)

    assert caught.value.reason == "production_credential_binding_rejected"
    assert acl_calls == []
    assert _PRIVATE_VALUES["password"] not in str(caught.value)


def test_acl_rejection_prevents_resolving_private_config_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    acl_calls = _install_fake_acl_gate(monkeypatch, reject=True)

    with pytest.raises(CredentialResolutionError) as caught:
        resolve_ctp_production_credentials(config, registry, pin)

    assert caught.value.reason == "config_yaml_windows_acl_unavailable"
    assert acl_calls == ["windows_acl"]
    assert _PRIVATE_VALUES["password"] not in str(caught.value)


def test_config_mutation_and_forged_credential_object_invalidate_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    _install_fake_acl_gate(monkeypatch)
    credentials = resolve_ctp_production_credentials(config, registry, pin)
    forged = replace(credentials)

    with pytest.raises(CtpProductionCredentialResolutionError) as forged_error:
        forged.require_credential("password")
    assert forged_error.value.reason == "credential_resolution_provenance_invalid"

    object.__setattr__(config.ctp, "md_front", "tcp://192.0.2.99:41211")
    with pytest.raises(CtpProductionCredentialResolutionError) as changed_error:
        credentials.require_credential("password")
    assert changed_error.value.reason == "production_credential_binding_rejected"
    assert _PRIVATE_VALUES["password"] not in str(changed_error.value)
