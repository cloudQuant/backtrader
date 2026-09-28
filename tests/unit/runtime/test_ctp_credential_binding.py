"""Offline tests for pathless, non-authorizing private CTP binding tags."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Optional

import pytest

import backtrader_runtime._ctp_credential_binding as credential_binding
import backtrader_runtime.config as runtime_config
import backtrader_runtime.ctp_front_pair_probe as front_pair_probe
from backtrader_runtime._ctp_credential_binding import (
    CtpCredentialBindingKeyMaterial,
    CtpCredentialBindingKeySource,
    CtpCredentialBindingError,
    create_reviewed_ctp_credential_binding_refresh_adapter,
    refresh_ctp_credential_binding_tag,
    refresh_reviewed_ctp_credential_binding_tag,
    require_current_ctp_credential_binding_tag,
    require_current_reviewed_ctp_credential_binding_tag,
)
from backtrader_runtime.ctp_sandbox_readonly_admission import CtpSandboxReadOnlyRegistration
from backtrader_runtime.ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding
from backtrader_runtime.registry import RegisteredRuntime, RuntimeRegistry, validate_runtime_config


_KEY_ID = "local-test-v1"
_KEY = b"a" * 32
_SET1_TD_FRONT = "tcp://180.168.146.187:10201"
_SET1_MD_FRONT = "tcp://180.168.146.187:10211"
_ALTERNATE_TD_FRONT = "tcp://ctp-td.example.net:41201"
_ALTERNATE_MD_FRONT = "tcp://ctp-md.example.net:41202"
_PRIVATE = {
    "md_front": _SET1_MD_FRONT,
    "td_front": _SET1_TD_FRONT,
    "instrument_id": "SA610",
    "exchange_id": "CZCE",
    "hedge_flag": "1",
    "broker_id": "9999",
    "user_id": "binding-test-user",
    "password": "binding-test-password-do-not-print",
    "app_id": "binding-test-app",
    "auth_code": "binding-test-auth-do-not-print",
}


@pytest.fixture(autouse=True)
def _isolate_windows_private_config_acl(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name == "nt":
        monkeypatch.setattr(
            runtime_config, "_require_private_config_security", lambda *a, **k: None
        )


def _write_private_config(runtime_dir: Path, values: Dict[str, str]) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        "config_schema_version: 4",
        "strategy:",
        "  id: binding.test.strategy",
        "runtime:",
        "  mode: simulation",
        "  preset: sandbox",
        "parameters: {}",
        "secrets_ref: config_yaml",
        "ctp_simnow:",
    ]
    for key, value in values.items():
        rows.append("  {0}: '{1}'".format(key, value))
    (runtime_dir / "config.yaml").write_text("\n".join(rows) + "\n", encoding="utf-8")
    if os.name == "posix":
        runtime_dir.chmod(0o700)
        (runtime_dir / "config.yaml").chmod(0o600)


def _write_multi_pair_private_config(
    runtime_dir: Path,
    values: Dict[str, str],
    pairs: tuple[tuple[str, str], ...],
) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        "config_schema_version: 4",
        "strategy:",
        "  id: binding.test.strategy",
        "runtime:",
        "  mode: simulation",
        "  preset: sandbox",
        "parameters: {}",
        "secrets_ref: config_yaml",
        "ctp_simnow:",
        "  front_pairs:",
    ]
    for md_front, td_front in pairs:
        rows.extend(
            (
                "    - md_front: '{0}'".format(md_front),
                "      td_front: '{0}'".format(td_front),
            )
        )
    for key, value in values.items():
        if key not in {"md_front", "td_front"}:
            rows.append("  {0}: '{1}'".format(key, value))
    (runtime_dir / "config.yaml").write_text("\n".join(rows) + "\n", encoding="utf-8")
    if os.name == "posix":
        runtime_dir.chmod(0o700)
        (runtime_dir / "config.yaml").chmod(0o600)


def _admission(
    registration: RegisteredRuntime,
    private_values: Dict[str, str],
    **overrides: str,
) -> CtpSandboxReadOnlyRegistration:
    values = {
        "runtime_registration": registration,
        "environment": "simnow",
        "sdk_profile": "config_front_pair",
        "account_fingerprint_sha256": hashlib.sha256(
            (private_values["broker_id"] + ":" + private_values["user_id"]).encode("utf-8")
        ).hexdigest(),
        "allowed_secrets_ref": "config_yaml",
        "instrument_id": private_values["instrument_id"],
        "exchange_id": private_values["exchange_id"],
        "hedge_flag": private_values["hedge_flag"],
        "td_front": private_values["td_front"],
        "md_front": private_values["md_front"],
    }
    values.update(overrides)
    return CtpSandboxReadOnlyRegistration(**values)


def _inputs(
    tmp_path: Path,
    values: Optional[Dict[str, str]] = None,
    runtime_id: str = "binding.test.runtime",
    admission_overrides: Optional[Dict[str, str]] = None,
    reviewed_route: bool = False,
):
    runtime_dir = tmp_path / "runtime"
    private_values = dict(_PRIVATE)
    if values:
        private_values.update(values)
    _write_private_config(runtime_dir, private_values)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id=runtime_id,
        strategy_id="binding.test.strategy",
        allowed_presets=("sandbox",),
        allowed_parameter_keys=(),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=(),
        offline_managed_execution=False,
        sandbox_write_policy="deny",
        approval_receipt_digest=None,
        runner_module=None,
        capability_modules=(),
    )
    if reviewed_route:
        reviewed_binding = CtpSimNowConfigReadOnlyBinding(
            runtime_id=runtime_id,
        )
        registry = RuntimeRegistry(
            (registration,),
            ctp_simnow_readonly_bindings=(reviewed_binding,),
            registry_id="test.ctp.binding.reviewed",
        )
    else:
        registry = RuntimeRegistry((registration,), registry_id="test.ctp.binding")
    effective = validate_runtime_config(runtime_dir, registry)
    admission = _admission(registration, private_values, **(admission_overrides or {}))
    return runtime_dir, registry, effective, admission, private_values


def _key_provider(key_id: str = _KEY_ID, key: bytes = _KEY):
    return lambda: (key_id, key)


def _sdk_scope_module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    account_fingerprint: str,
    account_fingerprint_sha256: Optional[str] = None,
    td_front: str,
    md_front: str,
    runtime_sha256: Optional[str] = None,
):
    class CtpCredentialBindingScope:
        def __init__(self) -> None:
            self.scope_sha256 = hashlib.sha256(b"sdk-scope").hexdigest()
            self.account_fingerprint = account_fingerprint
            if account_fingerprint_sha256 is not None:
                self.account_fingerprint_sha256 = account_fingerprint_sha256
            self.td_front = td_front
            self.md_front = md_front
            self.backtrader_runtime_sha256 = (
                runtime_sha256 or credential_binding._runtime_package_sha256()
            )
            self.configuration_sha256 = hashlib.sha256(b"sdk-configuration").hexdigest()

    monkeypatch.setitem(
        sys.modules,
        "bt_api_py._ctp_credential_binding",
        SimpleNamespace(CtpCredentialBindingScope=CtpCredentialBindingScope),
    )
    return CtpCredentialBindingScope


_DEFAULT_PROVIDER = object()


def _tag(effective, registry, admission, provider=_DEFAULT_PROVIDER):
    selected_provider = _key_provider() if provider is _DEFAULT_PROVIDER else provider
    return refresh_ctp_credential_binding_tag(effective, registry, admission, selected_provider)


def test_context_fields_are_exact_and_repr_redacts_hmac_and_private_values(tmp_path: Path) -> None:
    _runtime_dir, registry, effective, admission, _ = _inputs(tmp_path)
    tag = _tag(effective, registry, admission)
    fields = dict(tag.as_context_fields())

    assert set(fields) == {
        "credential_binding_key_id",
        "credential_binding_hmac_sha256",
    }
    assert fields["credential_binding_key_id"] == _KEY_ID
    assert len(fields["credential_binding_hmac_sha256"]) == 64
    assert (
        fields["credential_binding_hmac_sha256"]
        != hashlib.sha256(effective.config.ctp_simnow.password.encode("utf-8")).hexdigest()
    )
    rendered = (
        repr(tag) + repr(effective.config.ctp_simnow) + repr(effective.config.as_public_dict())
    )
    for secret in (_PRIVATE["password"], _PRIVATE["auth_code"], _PRIVATE["user_id"]):
        assert secret not in rendered
        assert secret not in repr(fields)
    assert fields["credential_binding_hmac_sha256"] not in repr(tag)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("instrument_id", "SA611"),
        ("exchange_id", "DCE"),
        ("hedge_flag", "2"),
        ("broker_id", "9998"),
        ("user_id", "binding-test-user-rotated"),
        ("password", "binding-test-password-rotated"),
        ("app_id", "binding-test-app-rotated"),
        ("auth_code", "binding-test-auth-rotated"),
    ),
)
def test_private_field_rotation_invalidates_old_binding(
    tmp_path: Path, field: str, value: str
) -> None:
    runtime_dir, registry, effective, admission, private_values = _inputs(tmp_path)
    original_tag = _tag(effective, registry, admission)

    private_values[field] = value
    _write_private_config(runtime_dir, private_values)
    with pytest.raises(CtpCredentialBindingError) as stale:
        _tag(effective, registry, admission)
    assert stale.value.reason == "stale_effective_config"

    current = validate_runtime_config(runtime_dir, registry)
    matching_admission = _admission(registry.require_runtime_dir(runtime_dir), private_values)
    current_tag = _tag(current, registry, matching_admission)
    assert current_tag.key_id == original_tag.key_id
    assert current_tag.hmac_sha256 != original_tag.hmac_sha256


def test_noncanonical_front_pair_is_rejected_by_validated_loader(tmp_path: Path) -> None:
    runtime_dir, registry, effective, admission, private_values = _inputs(tmp_path)
    private_values["td_front"] = "tcp://ctp-td.example.net:41201/path"
    _write_private_config(runtime_dir, private_values)

    with pytest.raises(CtpCredentialBindingError) as caught:
        _tag(effective, registry, admission)
    assert caught.value.reason == "runtime_or_private_config_unavailable"


@pytest.mark.parametrize(
    "admission_overrides",
    (
        {
            "environment": "simnow_set1",
            "sdk_profile": "set1_group1",
        },
        {"td_front": _ALTERNATE_TD_FRONT, "md_front": _ALTERNATE_MD_FRONT},
        {"instrument_id": "SA611"},
        {"exchange_id": "DCE"},
        {"hedge_flag": "2"},
        {"account_fingerprint_sha256": "b" * 64},
    ),
)
def test_admission_mismatch_with_private_config_fails_closed(
    tmp_path: Path, admission_overrides: Dict[str, str]
) -> None:
    _runtime_dir, registry, effective, admission, _ = _inputs(
        tmp_path, admission_overrides=admission_overrides
    )

    with pytest.raises(CtpCredentialBindingError) as caught:
        _tag(effective, registry, admission)
    assert caught.value.reason == "admission_private_config_mismatch"


def test_arbitrary_configured_front_pair_is_accepted_and_bound_exactly(tmp_path: Path) -> None:
    _runtime_dir, registry, effective, admission, private_values = _inputs(tmp_path)
    original_tag = _tag(effective, registry, admission)
    private_values["td_front"] = _ALTERNATE_TD_FRONT
    private_values["md_front"] = _ALTERNATE_MD_FRONT
    _write_private_config(effective.registration.runtime_dir, private_values)
    current = validate_runtime_config(effective.registration.runtime_dir, registry)
    configured_pair_admission = _admission(
        current.registration,
        private_values,
    )

    configured_pair_tag = _tag(current, registry, configured_pair_admission)

    assert current.config.ctp_simnow.td_front == _ALTERNATE_TD_FRONT
    assert current.config.ctp_simnow.md_front == _ALTERNATE_MD_FRONT
    assert configured_pair_admission.environment == "simnow"
    assert configured_pair_admission.sdk_profile == "config_front_pair"
    assert configured_pair_tag.hmac_sha256 != original_tag.hmac_sha256


def test_front_pair_role_swap_invalidates_hmac(tmp_path: Path) -> None:
    runtime_dir, registry, effective, admission, private_values = _inputs(tmp_path)
    original_tag = _tag(effective, registry, admission)
    private_values["td_front"], private_values["md_front"] = (
        private_values["md_front"],
        private_values["td_front"],
    )
    _write_private_config(runtime_dir, private_values)
    current = validate_runtime_config(runtime_dir, registry)
    swapped_admission = _admission(current.registration, private_values)

    swapped_tag = _tag(current, registry, swapped_admission)

    assert swapped_tag.hmac_sha256 != original_tag.hmac_sha256


def test_selected_pair_must_be_from_sealed_multi_pair_configuration(tmp_path: Path) -> None:
    runtime_dir, registry, _effective, _admission_value, private_values = _inputs(tmp_path)
    pairs = (
        (_PRIVATE["md_front"], _PRIVATE["td_front"]),
        (_ALTERNATE_MD_FRONT, _ALTERNATE_TD_FRONT),
    )
    _write_multi_pair_private_config(runtime_dir, private_values, pairs)
    effective = validate_runtime_config(runtime_dir, registry)

    alternate_values = dict(private_values)
    alternate_values["md_front"] = _ALTERNATE_MD_FRONT
    alternate_values["td_front"] = _ALTERNATE_TD_FRONT
    selected_admission = _admission(effective.registration, alternate_values)
    selected_tag = _tag(effective, registry, selected_admission)

    unconfigured_values = dict(alternate_values)
    unconfigured_values["md_front"] = "tcp://unlisted-md.example.net:41302"
    unconfigured_values["td_front"] = "tcp://unlisted-td.example.net:41301"
    unconfigured_admission = _admission(effective.registration, unconfigured_values)
    key_calls = []
    with pytest.raises(CtpCredentialBindingError) as caught:
        refresh_ctp_credential_binding_tag(
            effective,
            registry,
            unconfigured_admission,
            lambda: key_calls.append(True) or (_KEY_ID, _KEY),
        )

    assert caught.value.reason == "admission_private_config_mismatch"
    assert key_calls == []
    assert selected_tag.hmac_sha256


def test_unselected_candidate_change_invalidates_selected_pair_binding(tmp_path: Path) -> None:
    runtime_dir, registry, _single_effective, _single_admission, private_values = _inputs(
        tmp_path, reviewed_route=True
    )
    first_pairs = (
        (_PRIVATE["md_front"], _PRIVATE["td_front"]),
        (_ALTERNATE_MD_FRONT, _ALTERNATE_TD_FRONT),
    )
    _write_multi_pair_private_config(runtime_dir, private_values, first_pairs)
    effective = validate_runtime_config(runtime_dir, registry)
    selected_admission = _admission(effective.registration, private_values)
    original_tag = _tag(effective, registry, selected_admission)

    rotated_candidates = (
        first_pairs[0],
        ("tcp://ctp-md-next.example.net:41212", "tcp://ctp-td-next.example.net:41211"),
    )
    _write_multi_pair_private_config(runtime_dir, private_values, rotated_candidates)
    key_calls = []
    with pytest.raises(CtpCredentialBindingError) as stale:
        refresh_ctp_credential_binding_tag(
            effective,
            registry,
            selected_admission,
            lambda: key_calls.append(True) or (_KEY_ID, _KEY),
        )
    assert stale.value.reason == "stale_effective_config"
    assert key_calls == []

    current = validate_runtime_config(runtime_dir, registry)
    refreshed_tag = _tag(current, registry, selected_admission)
    assert refreshed_tag.hmac_sha256 != original_tag.hmac_sha256


def test_current_tag_check_rejects_key_rotation_without_a_local_journal(tmp_path: Path) -> None:
    _runtime_dir, registry, effective, admission, _ = _inputs(tmp_path)
    approved = _tag(effective, registry, admission, _key_provider("protected-key-v1", b"a" * 32))

    require_current_ctp_credential_binding_tag(
        approved, effective, registry, admission, _key_provider("protected-key-v1", b"a" * 32)
    )
    with pytest.raises(CtpCredentialBindingError) as caught:
        require_current_ctp_credential_binding_tag(
            approved,
            effective,
            registry,
            admission,
            _key_provider("protected-key-v2", b"b" * 32),
        )
    assert caught.value.reason == "credential_binding_mismatch"


def test_runtime_identity_is_part_of_the_canonical_binding(tmp_path: Path) -> None:
    _runtime_dir, registry, effective, admission, _ = _inputs(tmp_path / "first")
    first = _tag(effective, registry, admission)
    _runtime_dir2, registry2, effective2, admission2, _ = _inputs(
        tmp_path / "second", runtime_id="binding.test.other-runtime"
    )
    second = _tag(effective2, registry2, admission2)

    assert first.hmac_sha256 != second.hmac_sha256


def test_auth_rotation_keeps_public_digest_stable_but_changes_private_tag(tmp_path: Path) -> None:
    runtime_dir, registry, effective, admission, private_values = _inputs(tmp_path)
    first = _tag(effective, registry, admission)
    private_values["password"] = "binding-test-password-rotated"
    _write_private_config(runtime_dir, private_values)
    current = validate_runtime_config(runtime_dir, registry)
    second = _tag(current, registry, admission)

    assert current.config.config_digest == effective.config.config_digest
    assert current.effective_digest == effective.effective_digest
    assert first.hmac_sha256 != second.hmac_sha256


def test_private_schema_expansion_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _runtime_dir, registry, effective, admission, _ = _inputs(tmp_path)
    monkeypatch.setattr(
        credential_binding,
        "_PRIVATE_FIELD_NAMES",
        credential_binding._PRIVATE_FIELD_NAMES[:-1],
    )

    with pytest.raises(CtpCredentialBindingError) as caught:
        _tag(effective, registry, admission)
    assert caught.value.reason == "private_config_schema_changed"


@pytest.mark.parametrize("provider", (None, lambda: None, lambda: ("bad key id", b"k" * 32)))
def test_missing_or_invalid_key_provider_fails_closed(tmp_path: Path, provider) -> None:
    _runtime_dir, registry, effective, admission, _ = _inputs(tmp_path)

    with pytest.raises(CtpCredentialBindingError) as caught:
        _tag(effective, registry, admission, provider)
    assert caught.value.reason in {"protected_key_unavailable", "protected_key_invalid"}


def test_current_tag_check_rejects_stale_effective_after_private_config_rotation(
    tmp_path: Path,
) -> None:
    runtime_dir, registry, effective, admission, private_values = _inputs(tmp_path)
    approved = _tag(effective, registry, admission)
    private_values["password"] = "binding-test-password-restart-rotation"
    _write_private_config(runtime_dir, private_values)

    with pytest.raises(CtpCredentialBindingError) as caught:
        require_current_ctp_credential_binding_tag(
            approved, effective, registry, admission, _key_provider()
        )
    assert caught.value.reason == "stale_effective_config"


def test_front_pair_rotation_changes_hmac_and_preserves_exact_configured_pair(
    tmp_path: Path,
) -> None:
    runtime_dir, registry, effective, admission, private_values = _inputs(tmp_path)
    first = _tag(effective, registry, admission)
    private_values["td_front"] = _ALTERNATE_TD_FRONT
    private_values["md_front"] = _ALTERNATE_MD_FRONT
    _write_private_config(runtime_dir, private_values)
    current = validate_runtime_config(runtime_dir, registry)
    current_admission = _admission(current.registration, private_values)
    second = _tag(current, registry, current_admission)

    assert current.config.ctp_simnow.td_front == _ALTERNATE_TD_FRONT
    assert current.config.ctp_simnow.md_front == _ALTERNATE_MD_FRONT
    assert first.hmac_sha256 != second.hmac_sha256


def test_reviewed_route_tag_revalidates_exact_binding_and_full_admission(
    tmp_path: Path,
) -> None:
    _runtime_dir, registry, effective, admission, _ = _inputs(tmp_path, reviewed_route=True)
    key_calls = []

    def provider():
        key_calls.append(True)
        return _KEY_ID, _KEY

    reviewed_tag = refresh_reviewed_ctp_credential_binding_tag(
        effective, registry, admission, provider
    )
    assert key_calls == [True]
    require_current_reviewed_ctp_credential_binding_tag(
        reviewed_tag, effective, registry, admission, provider
    )
    assert len(key_calls) == 2

    bad_ttl_admission = _admission(
        effective.registration,
        {
            **_PRIVATE,
            "md_front": effective.config.ctp_simnow.md_front,
            "td_front": effective.config.ctp_simnow.td_front,
        },
        session_ttl_seconds=120.0,
    )
    key_calls.clear()
    with pytest.raises(CtpCredentialBindingError) as caught:
        refresh_reviewed_ctp_credential_binding_tag(
            effective, registry, bad_ttl_admission, provider
        )
    assert caught.value.reason == "reviewed_route_mismatch"
    assert key_calls == []

    binding = registry.ctp_simnow_readonly_bindings[0]
    object.__setattr__(binding, "session_ttl_seconds", 301.0)
    key_calls.clear()
    with pytest.raises(CtpCredentialBindingError):
        refresh_reviewed_ctp_credential_binding_tag(effective, registry, admission, provider)
    assert key_calls == []


def test_typed_sdk_refresh_adapter_revalidates_route_before_versioned_key_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _runtime_dir, registry, effective, admission, private_values = _inputs(
        tmp_path, reviewed_route=True
    )
    expected_account = hashlib.sha256(
        (private_values["broker_id"] + ":" + private_values["user_id"]).encode("utf-8")
    ).hexdigest()
    scope_type = _sdk_scope_module(
        monkeypatch,
        account_fingerprint="acct_" + expected_account[:16],
        account_fingerprint_sha256=expected_account,
        td_front=private_values["td_front"],
        md_front=private_values["md_front"],
    )
    key_calls = []
    event_order = []
    key_versions = [
        CtpCredentialBindingKeyMaterial("protected-v1", b"a" * 32),
        CtpCredentialBindingKeyMaterial("protected-v2", b"b" * 32),
    ]

    def read_current():
        key_calls.append(True)
        event_order.append("key")
        return key_versions[len(key_calls) - 1]

    key_source = CtpCredentialBindingKeySource(read_current)
    adapter = create_reviewed_ctp_credential_binding_refresh_adapter(
        effective, registry, admission, key_source
    )
    assert key_calls == []

    scope = scope_type()
    first = adapter.refresh(scope)
    second = adapter.refresh(scope)

    assert first.key_id == "protected-v1"
    assert second.key_id == "protected-v2"
    assert first.hmac_sha256 != second.hmac_sha256
    assert first.scope_sha256 == scope.scope_sha256
    assert first.account_fingerprint == "acct_" + expected_account[:16]
    assert first.account_fingerprint_sha256 == expected_account
    assert first.account_fingerprint == scope.account_fingerprint
    assert first.account_fingerprint_sha256 == scope.account_fingerprint_sha256
    assert first.td_front == private_values["td_front"]
    assert first.md_front == private_values["md_front"]
    assert first.runtime_config_sha256 == effective.config.config_digest
    assert first.registration_sha256 == effective.registration.digest
    assert first.backtrader_runtime_sha256 == scope.backtrader_runtime_sha256
    assert "hmac_sha256" not in repr(first)
    assert "protected-v1" not in repr(key_source)
    assert len(key_calls) == 2
    assert event_order == ["key", "key"]


def test_reviewed_refresh_reuses_selected_pair_from_multi_pair_config_without_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir, registry, _single_effective, _single_admission, private_values = _inputs(
        tmp_path, reviewed_route=True
    )
    pairs = (
        (_PRIVATE["md_front"], _PRIVATE["td_front"]),
        (_ALTERNATE_MD_FRONT, _ALTERNATE_TD_FRONT),
    )
    _write_multi_pair_private_config(runtime_dir, private_values, pairs)
    effective = validate_runtime_config(runtime_dir, registry)
    selected_values = dict(private_values)
    selected_values["md_front"] = _ALTERNATE_MD_FRONT
    selected_values["td_front"] = _ALTERNATE_TD_FRONT
    admission = _admission(effective.registration, selected_values)
    expected_account = hashlib.sha256(
        (private_values["broker_id"] + ":" + private_values["user_id"]).encode("utf-8")
    ).hexdigest()
    scope_type = _sdk_scope_module(
        monkeypatch,
        account_fingerprint="acct_" + expected_account[:16],
        account_fingerprint_sha256=expected_account,
        td_front=_ALTERNATE_TD_FRONT,
        md_front=_ALTERNATE_MD_FRONT,
    )
    monkeypatch.setattr(
        front_pair_probe,
        "select_ctp_front_pair",
        lambda *args, **kwargs: pytest.fail("credential refresh must reuse admitted pair"),
    )
    key_source = CtpCredentialBindingKeySource(
        lambda: CtpCredentialBindingKeyMaterial(_KEY_ID, _KEY)
    )

    adapter = create_reviewed_ctp_credential_binding_refresh_adapter(
        effective, registry, admission, key_source
    )
    refreshed = adapter.refresh(scope_type())

    assert refreshed.td_front == _ALTERNATE_TD_FRONT
    assert refreshed.md_front == _ALTERNATE_MD_FRONT
    assert refreshed.account_fingerprint == "acct_" + expected_account[:16]
    assert refreshed.account_fingerprint_sha256 == expected_account


@pytest.mark.parametrize(
    "scope_override, expected_reason",
    (
        ({"account_fingerprint": "acct_ffffffffffffffff"}, "sdk_scope_invalid"),
        ({"td_front": _ALTERNATE_TD_FRONT}, "sdk_scope_runtime_mismatch"),
        ({"md_front": _ALTERNATE_MD_FRONT}, "sdk_scope_runtime_mismatch"),
        ({"backtrader_runtime_sha256": "c" * 64}, "sdk_scope_runtime_mismatch"),
    ),
)
def test_typed_sdk_refresh_adapter_rejects_forged_scope_before_key_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope_override: Dict[str, str],
    expected_reason: str,
) -> None:
    _runtime_dir, registry, effective, admission, private_values = _inputs(
        tmp_path, reviewed_route=True
    )
    expected_account = hashlib.sha256(
        (private_values["broker_id"] + ":" + private_values["user_id"]).encode("utf-8")
    ).hexdigest()
    scope_type = _sdk_scope_module(
        monkeypatch,
        account_fingerprint="acct_" + expected_account[:16],
        account_fingerprint_sha256=expected_account,
        td_front=private_values["td_front"],
        md_front=private_values["md_front"],
    )
    key_calls = []
    source = CtpCredentialBindingKeySource(
        lambda: key_calls.append(True) or CtpCredentialBindingKeyMaterial(_KEY_ID, _KEY)
    )
    adapter = create_reviewed_ctp_credential_binding_refresh_adapter(
        effective, registry, admission, source
    )
    scope = scope_type()
    for name, value in scope_override.items():
        setattr(scope, name, value)

    with pytest.raises(CtpCredentialBindingError) as caught:
        adapter.refresh(scope)

    assert caught.value.reason == expected_reason
    assert key_calls == []


def test_typed_sdk_refresh_adapter_rejects_full_digest_drift_before_key_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _runtime_dir, registry, effective, admission, private_values = _inputs(
        tmp_path, reviewed_route=True
    )
    expected_account = hashlib.sha256(
        (private_values["broker_id"] + ":" + private_values["user_id"]).encode("utf-8")
    ).hexdigest()
    scope_type = _sdk_scope_module(
        monkeypatch,
        account_fingerprint="acct_" + expected_account[:16],
        account_fingerprint_sha256=expected_account,
        td_front=private_values["td_front"],
        md_front=private_values["md_front"],
    )
    key_calls = []
    source = CtpCredentialBindingKeySource(
        lambda: key_calls.append(True) or CtpCredentialBindingKeyMaterial(_KEY_ID, _KEY)
    )
    adapter = create_reviewed_ctp_credential_binding_refresh_adapter(
        effective, registry, admission, source
    )
    scope = scope_type()
    scope.account_fingerprint_sha256 = expected_account[:-1] + (
        "0" if expected_account[-1] != "0" else "1"
    )

    with pytest.raises(CtpCredentialBindingError) as caught:
        adapter.refresh(scope)

    assert caught.value.reason == "sdk_scope_runtime_mismatch"
    assert key_calls == []


def test_typed_sdk_refresh_adapter_rejects_legacy_short_only_scope_before_key_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _runtime_dir, registry, effective, admission, private_values = _inputs(
        tmp_path, reviewed_route=True
    )
    expected_account = hashlib.sha256(
        (private_values["broker_id"] + ":" + private_values["user_id"]).encode("utf-8")
    ).hexdigest()
    scope_type = _sdk_scope_module(
        monkeypatch,
        account_fingerprint="acct_" + expected_account[:16],
        td_front=private_values["td_front"],
        md_front=private_values["md_front"],
    )
    key_calls = []
    source = CtpCredentialBindingKeySource(
        lambda: key_calls.append(True) or CtpCredentialBindingKeyMaterial(_KEY_ID, _KEY)
    )
    adapter = create_reviewed_ctp_credential_binding_refresh_adapter(
        effective, registry, admission, source
    )

    with pytest.raises(CtpCredentialBindingError) as caught:
        adapter.refresh(scope_type())

    assert caught.value.reason == "sdk_scope_invalid"
    assert key_calls == []


def test_typed_sdk_refresh_adapter_rejects_stale_config_and_route_before_key_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir, registry, effective, admission, private_values = _inputs(
        tmp_path, reviewed_route=True
    )
    expected_account = hashlib.sha256(
        (private_values["broker_id"] + ":" + private_values["user_id"]).encode("utf-8")
    ).hexdigest()
    scope_type = _sdk_scope_module(
        monkeypatch,
        account_fingerprint="acct_" + expected_account[:16],
        account_fingerprint_sha256=expected_account,
        td_front=private_values["td_front"],
        md_front=private_values["md_front"],
    )
    key_calls = []
    source = CtpCredentialBindingKeySource(
        lambda: key_calls.append(True) or CtpCredentialBindingKeyMaterial(_KEY_ID, _KEY)
    )
    adapter = create_reviewed_ctp_credential_binding_refresh_adapter(
        effective, registry, admission, source
    )

    private_values["user_id"] = "rotated-account-after-adapter-creation"
    _write_private_config(runtime_dir, private_values)
    with pytest.raises(CtpCredentialBindingError) as stale_config:
        adapter.refresh(scope_type())
    assert stale_config.value.reason == "stale_effective_config"
    assert key_calls == []

    current = validate_runtime_config(runtime_dir, registry)
    current_admission = _admission(registry.require_runtime_dir(runtime_dir), private_values)
    adapter = create_reviewed_ctp_credential_binding_refresh_adapter(
        current, registry, current_admission, source
    )
    binding = registry.ctp_simnow_readonly_bindings[0]
    object.__setattr__(binding, "session_ttl_seconds", 301.0)
    with pytest.raises(CtpCredentialBindingError) as forged_route:
        adapter.refresh(scope_type())
    assert forged_route.value.reason == "reviewed_route_unavailable"
    assert key_calls == []


def test_reviewed_refresh_adapter_rejects_unregistered_route_and_untyped_key_source(
    tmp_path: Path,
) -> None:
    _runtime_dir, registry, effective, admission, _ = _inputs(tmp_path)
    key_calls = []
    source = CtpCredentialBindingKeySource(
        lambda: key_calls.append(True) or CtpCredentialBindingKeyMaterial(_KEY_ID, _KEY)
    )

    with pytest.raises(CtpCredentialBindingError) as no_route:
        create_reviewed_ctp_credential_binding_refresh_adapter(
            effective, registry, admission, source
        )
    assert no_route.value.reason == "reviewed_route_unavailable"
    assert key_calls == []

    with pytest.raises(CtpCredentialBindingError) as untyped:
        create_reviewed_ctp_credential_binding_refresh_adapter(
            effective, registry, admission, _key_provider()
        )
    assert untyped.value.reason == "typed_key_source_required"
    assert key_calls == []
