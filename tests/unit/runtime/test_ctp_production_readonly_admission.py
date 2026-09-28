"""Pure config-binding tests for the canonical CTP production read-only candidate."""

from __future__ import annotations

import builtins
import json
import socket
from pathlib import Path
from typing import Optional

import pytest

import backtrader_runtime.config as runtime_config
from backtrader_runtime import RegisteredRuntime, RuntimeRegistry
from backtrader_runtime.ctp_production_readonly_admission import (
    CtpProductionReadOnlyAdmissionError,
    CtpProductionReadOnlyConfigBinding,
    CtpProductionReadOnlyRegistration,
    production_account_binding_sha256,
    require_ctp_production_readonly_config_binding,
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


def _document(private_values: Optional[dict] = None) -> dict:
    return {
        "config_schema_version": 4,
        "strategy": {"id": "example.013_3.sa_midfreq_simnow"},
        "runtime": {"mode": "live", "preset": "managed_live_direct"},
        "parameters": {},
        "secrets_ref": "config_yaml",
        "ctp": dict(_PRIVATE_VALUES if private_values is None else private_values),
    }


def _legacy_document(private_values: Optional[dict] = None) -> dict:
    document = _document(private_values)
    document["ctp_production"] = document.pop("ctp")
    document["strategy"] = {"id": "example.007_ctp.production"}
    return document


def _canonical_live_document(private_values: Optional[dict] = None) -> dict:
    return _document(private_values)


def _bound_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    private_values: Optional[dict] = None,
    *,
    pin_fronts: bool = True,
):
    runtime_dir = tmp_path / "runtime-ctp-private"
    runtime_dir.mkdir()
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id="example.013_3.sa_midfreq_simnow",
        runtime_id="example.013_3.sa_midfreq_simnow.injected_production_readonly",
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
    )
    registry = RuntimeRegistry((registration,))
    config = runtime_config._validate_schema(
        _document(private_values),
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
        md_front=_PRIVATE_VALUES["md_front"] if pin_fronts else None,
        td_front=_PRIVATE_VALUES["td_front"] if pin_fronts else None,
        instrument_id=_PRIVATE_VALUES["instrument_id"],
        exchange_id=_PRIVATE_VALUES["exchange_id"],
        hedge_flag=_PRIVATE_VALUES["hedge_flag"],
    )
    return config, registry, pin


def test_synthetic_config_yields_only_a_redacted_non_authorizing_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)

    binding = require_ctp_production_readonly_config_binding(config, registry, pin)

    assert binding.md_front == _PRIVATE_VALUES["md_front"]
    assert binding.td_front == _PRIVATE_VALUES["td_front"]
    assert binding.environment == "production"
    assert binding.contract_verified is True
    assert binding.provider_read_authorized is False
    assert binding.sdk_import_authorized is False
    assert binding.network_access_authorized is False
    assert binding.credential_access_authorized is False
    assert binding.execution_authorized is False
    assert binding.external_writes_authorized is False
    assert binding.order_submission_authorized is False
    assert binding.cancellation_authorized is False
    assert binding.arming_authorized is False
    with pytest.raises(TypeError, match="non-authorizing"):
        bool(binding)

    public_text = json.dumps(binding.as_public_dict(), sort_keys=True)
    assert _PRIVATE_VALUES["md_front"] not in public_text
    assert _PRIVATE_VALUES["td_front"] not in public_text
    assert _PRIVATE_VALUES["user_id"] not in public_text
    assert _PRIVATE_VALUES["password"] not in public_text


def test_canonical_live_ctp_config_binds_at_same_private_runtime_directory(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "runtime-ctp-private"
    runtime_dir.mkdir()
    values = dict(_PRIVATE_VALUES)
    values.pop("md_front")
    values.pop("td_front")
    values["front_pairs"] = [
        {"md_front": "tcp://192.0.2.11:41211", "td_front": "tcp://192.0.2.10:41201"},
        {"md_front": "tcp://192.0.2.21:41211", "td_front": "tcp://192.0.2.20:41201"},
    ]
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id="example.013_3.sa_midfreq_simnow",
        runtime_id="example.013_3.sa_midfreq_simnow.injected_live_readonly",
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
    )
    registry = RuntimeRegistry((registration,))
    config = runtime_config._validate_schema(
        _canonical_live_document(values),
        runtime_dir,
        runtime_dir / "config.yaml",
    )
    runtime_config._seal_loaded_runtime_config(config, registry)
    pin = CtpProductionReadOnlyRegistration(
        runtime_registration=registration,
        environment="production",
        account_binding_sha256=production_account_binding_sha256(
            values["broker_id"], values["user_id"]
        ),
        md_front=None,
        td_front=None,
        instrument_id=values["instrument_id"],
        exchange_id=values["exchange_id"],
        hedge_flag=values["hedge_flag"],
    )

    assert config.ctp is not None
    assert config.ctp_production is None
    binding = require_ctp_production_readonly_config_binding(
        config,
        registry,
        pin,
        selected_front_pair=("tcp://192.0.2.21:41211", "tcp://192.0.2.20:41201"),
    )

    assert binding.runtime_id == registration.runtime_id
    assert binding.config_digest == config.config_digest
    assert binding.front_pair_set_sha256
    assert binding.md_front == "tcp://192.0.2.21:41211"
    assert binding.td_front == "tcp://192.0.2.20:41201"
    assert binding.execution_authorized is False
    assert binding.provider_read_authorized is False


@pytest.mark.parametrize(
    "field_name,attempted_value",
    (
        ("contract_verified", False),
        ("provider_read_authorized", True),
        ("sdk_import_authorized", True),
        ("network_access_authorized", True),
        ("credential_access_authorized", True),
        ("execution_authorized", True),
        ("external_writes_authorized", True),
        ("order_submission_authorized", True),
        ("cancellation_authorized", True),
        ("arming_authorized", True),
    ),
)
def test_binding_constructor_cannot_set_contract_or_authority_flags(
    field_name: str, attempted_value: bool
) -> None:
    arguments = {
        "runtime_id": "example.007_ctp.production",
        "strategy_id": "example.007_ctp.production",
        "config_digest": "a" * 64,
        "registration_digest": "b" * 64,
        "environment": "production",
        "md_front": "tcp://192.0.2.11:41211",
        "td_front": "tcp://192.0.2.10:41201",
        "instrument_id": "IF2612",
        "exchange_id": "CFFEX",
        "hedge_flag": "1",
        "account_binding_sha256": "c" * 64,
        "front_pair_sha256": "d" * 64,
        "front_pair_set_sha256": "e" * 64,
        field_name: attempted_value,
    }

    with pytest.raises(TypeError, match=field_name):
        CtpProductionReadOnlyConfigBinding(**arguments)


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
def test_changed_private_selector_fails_exact_production_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    changed_value: str,
) -> None:
    private_values = dict(_PRIVATE_VALUES)
    private_values[field_name] = changed_value
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch, private_values)

    with pytest.raises(CtpProductionReadOnlyAdmissionError) as caught:
        require_ctp_production_readonly_config_binding(config, registry, pin)

    assert caught.value.reason == "production_pin_mismatch"
    assert changed_value not in str(caught.value)


def test_changed_sealed_config_is_rejected_before_provider_or_network_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    assert config.ctp is not None
    object.__setattr__(config.ctp, "md_front", "tcp://192.0.2.99:41211")

    import_attempts = []
    socket_attempts = []
    original_import = builtins.__import__

    def reject_provider_import(name, *args, **kwargs):
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in ("bt_api_ctp", "bt_api_py", "bt_api_base", "backtrader")
        ):
            import_attempts.append(name)
            raise AssertionError("production binding attempted provider import")
        return original_import(name, *args, **kwargs)

    def reject_socket(*args, **kwargs):
        socket_attempts.append((args, kwargs))
        raise AssertionError("production binding attempted network I/O")

    monkeypatch.setattr(builtins, "__import__", reject_provider_import)
    monkeypatch.setattr(socket, "socket", reject_socket)

    with pytest.raises(CtpProductionReadOnlyAdmissionError) as caught:
        require_ctp_production_readonly_config_binding(config, registry, pin)

    assert caught.value.reason == "config_provenance_invalid"
    assert not import_attempts
    assert not socket_attempts


def test_legacy_second_production_block_is_rejected_as_readonly_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy_dir = tmp_path / "runtime-production"
    legacy_dir.mkdir()
    monkeypatch.setattr(runtime_config, "CTP_PRODUCTION_RUNTIME_DIR", legacy_dir)
    registration = RegisteredRuntime(
        runtime_dir=legacy_dir,
        strategy_id="example.007_ctp.production",
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
    )
    registry = RuntimeRegistry((registration,))
    config = runtime_config._validate_schema(
        _legacy_document(), legacy_dir, legacy_dir / "config.yaml"
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

    with pytest.raises(CtpProductionReadOnlyAdmissionError) as caught:
        require_ctp_production_readonly_config_binding(config, registry, pin)

    assert caught.value.reason == "canonical_ctp_config_required"
    assert "canonical ctp" in str(caught.value)


def test_configured_front_pairs_need_no_static_production_address_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pairs = [
        {"md_front": "tcp://md-a.example.net:42001", "td_front": "tcp://td-a.example.net:43001"},
        {"md_front": "tcp://md-b.example.net:42002", "td_front": "tcp://td-b.example.net:43002"},
    ]
    private_values = {
        key: value for key, value in _PRIVATE_VALUES.items() if key not in {"md_front", "td_front"}
    }
    private_values["front_pairs"] = pairs
    config, registry, pin = _bound_inputs(
        tmp_path, monkeypatch, private_values, pin_fronts=False
    )

    unresolved = require_ctp_production_readonly_config_binding(config, registry, pin)
    assert unresolved.md_front is None
    assert unresolved.td_front is None
    assert unresolved.front_pairs == tuple(
        (pair["md_front"], pair["td_front"]) for pair in pairs
    )
    assert unresolved.network_access_authorized is False
    assert unresolved.credential_access_authorized is False

    selected = require_ctp_production_readonly_config_binding(
        config,
        registry,
        pin,
        selected_front_pair=(pairs[1]["md_front"], pairs[1]["td_front"]),
    )
    assert selected.md_front == pairs[1]["md_front"]
    assert selected.td_front == pairs[1]["td_front"]
    assert selected.front_pair_sha256 != "0" * 64
    assert selected.front_pair_set_sha256 == unresolved.front_pair_set_sha256
    assert selected.account_binding_sha256 == pin.account_binding_sha256
    assert selected.registration_digest == unresolved.registration_digest


def test_config_driven_production_selection_rejects_unconfigured_address(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pairs = [
        {"md_front": "tcp://md-a.example.net:42001", "td_front": "tcp://td-a.example.net:43001"},
        {"md_front": "tcp://md-b.example.net:42002", "td_front": "tcp://td-b.example.net:43002"},
    ]
    private_values = {
        key: value for key, value in _PRIVATE_VALUES.items() if key not in {"md_front", "td_front"}
    }
    private_values["front_pairs"] = pairs
    config, registry, pin = _bound_inputs(
        tmp_path, monkeypatch, private_values, pin_fronts=False
    )

    with pytest.raises(CtpProductionReadOnlyAdmissionError) as caught:
        require_ctp_production_readonly_config_binding(
            config,
            registry,
            pin,
            selected_front_pair=("tcp://unconfigured.example.net:44001", "tcp://td-a.example.net:43001"),
        )

    assert caught.value.reason == "production_front_selection_mismatch"


def test_multi_pair_production_config_rejects_legacy_front_pin_before_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pairs = [
        {"md_front": "tcp://md-a.example.net:42001", "td_front": "tcp://td-a.example.net:43001"},
        {"md_front": "tcp://md-b.example.net:42002", "td_front": "tcp://td-b.example.net:43002"},
    ]
    private_values = {
        key: value for key, value in _PRIVATE_VALUES.items() if key not in {"md_front", "td_front"}
    }
    private_values["front_pairs"] = pairs
    config, registry, pin = _bound_inputs(
        tmp_path, monkeypatch, private_values, pin_fronts=True
    )

    with pytest.raises(CtpProductionReadOnlyAdmissionError) as caught:
        require_ctp_production_readonly_config_binding(config, registry, pin)

    assert caught.value.reason == "legacy_front_pin_incompatible_with_multi_pair_config"


def test_cross_registry_config_reuse_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as first_dir:
        first_path = Path(first_dir) / "runtime-ctp-private"
        first_path.mkdir()
        first_registration = RegisteredRuntime(
            runtime_dir=first_path,
            strategy_id="example.013_3.sa_midfreq_simnow",
            allowed_presets=("managed_live_direct",),
            allowed_secrets_refs=("config_yaml",),
        )
        first_registry = RuntimeRegistry((first_registration,))
        second_registration = RegisteredRuntime(
            runtime_dir=first_path,
            strategy_id="example.013_3.sa_midfreq_simnow",
            allowed_presets=("managed_live_direct",),
            allowed_secrets_refs=("config_yaml",),
        )
        second_registry = RuntimeRegistry((second_registration,))
        config = runtime_config._validate_schema(
            _document(), first_path, first_path / "config.yaml"
        )
        runtime_config._seal_loaded_runtime_config(config, first_registry)
        pin = CtpProductionReadOnlyRegistration(
            runtime_registration=first_registration,
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

        with pytest.raises(CtpProductionReadOnlyAdmissionError) as caught:
            require_ctp_production_readonly_config_binding(config, second_registry, pin)

        assert caught.value.reason == "config_provenance_invalid"


def test_simnow_environment_label_cannot_be_used_for_production_pin(
    tmp_path: Path,
) -> None:
    registration = RegisteredRuntime(
        runtime_dir=tmp_path,
        strategy_id="example.013_3.sa_midfreq_simnow",
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
    )

    with pytest.raises(CtpProductionReadOnlyAdmissionError) as caught:
        CtpProductionReadOnlyRegistration(
            runtime_registration=registration,
            environment="simnow_set1",
            account_binding_sha256=production_account_binding_sha256(
                _PRIVATE_VALUES["broker_id"], _PRIVATE_VALUES["user_id"]
            ),
            md_front=_PRIVATE_VALUES["md_front"],
            td_front=_PRIVATE_VALUES["td_front"],
            instrument_id=_PRIVATE_VALUES["instrument_id"],
            exchange_id=_PRIVATE_VALUES["exchange_id"],
            hedge_flag=_PRIVATE_VALUES["hedge_flag"],
        )

    assert caught.value.reason == "environment_mismatch"
    assert "simnow_set1" not in str(caught.value)


def test_read_only_binding_contract_has_no_provider_capabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    assert registry.require_runtime_dir(config.strategy_dir) is pin.runtime_registration
    assert pin.runtime_registration.available_capabilities == ()
    assert pin.runtime_registration.capability_modules == ()
