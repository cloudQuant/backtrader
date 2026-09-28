"""Offline tests for the fail-closed Iteration 41 credential resolver.

The Windows Credential Manager cases use a synthetic ``CredReadW`` result.
They never enumerate or read a credential from the host user's store.
"""

from __future__ import annotations

import ctypes
import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

import backtrader_runtime.credential_resolver as credential_resolver
import backtrader_runtime.config as runtime_config
from backtrader_runtime.config import load_runtime_config
from backtrader_runtime.errors import RuntimeConfigError
from backtrader_runtime.credential_resolver import (
    CTP_AUTHENTICATION_CREDENTIAL_KEYS,
    CredentialResolutionError,
    ResolvedRuntimeCredentials,
    RuntimeCredentialScope,
    require_resolved_runtime_credentials_seal,
    resolve_runtime_credentials,
)
from backtrader_runtime.registry import RegisteredRuntime, RuntimeRegistry, resolve_runtime_config


SECRET_REF = "os_secret_store:iteration41.ctp.simnow"
SECRET_VALUES = {
    "broker_id": "9999",
    "user_id": "test-user-001",
    "password": "sentinel-raw-password-never-log",
    "app_id": "simnow-app",
    "auth_code": "sentinel-raw-auth-code-never-log",
}


@pytest.fixture(autouse=True)
def _use_acl_seam_for_synthetic_ctp_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    # Parser/resolver tests use synthetic credentials and do not rewrite the
    # host's inherited Windows ACL.  ACL policy and denial paths have separate
    # explicit seam coverage below.
    if os.name == "nt":
        monkeypatch.setattr(
            runtime_config, "_require_private_config_security", lambda *a, **k: None
        )


def _write_config(runtime_dir: Path, secrets_ref: str = SECRET_REF) -> None:
    lines = [
        "config_schema_version: 4",
        "strategy:",
        "  id: iteration41.ctp.strategy",
        "runtime:",
        "  mode: simulation",
        "  preset: sandbox",
        "parameters: {}",
        "secrets_ref: {0}".format(secrets_ref),
    ]
    if secrets_ref == "config_yaml":
        lines.extend(
            (
                "ctp_simnow:",
                "  md_front: tcp://180.168.146.187:10211",
                "  td_front: tcp://180.168.146.187:10201",
                "  instrument_id: IF2612",
                "  exchange_id: CFFEX",
                "  hedge_flag: '1'",
                "  broker_id: '" + SECRET_VALUES["broker_id"] + "'",
                "  user_id: " + SECRET_VALUES["user_id"],
                "  password: '" + SECRET_VALUES["password"] + "'",
                "  app_id: " + SECRET_VALUES["app_id"],
                "  auth_code: '" + SECRET_VALUES["auth_code"] + "'",
            )
        )
    (runtime_dir / "config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _effective(runtime_dir: Path, secrets_ref: str = SECRET_REF):
    _write_config(runtime_dir, secrets_ref)
    if os.name == "posix" and secrets_ref == "config_yaml":
        runtime_dir.chmod(0o700)
        (runtime_dir / "config.yaml").chmod(0o600)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id="iteration41.ctp.runtime",
        strategy_id="iteration41.ctp.strategy",
        allowed_presets=("sandbox",),
        allowed_secrets_refs=(secrets_ref,),
    )
    registry = RuntimeRegistry((registration,), registry_id="test.credential-resolver")
    config = load_runtime_config(runtime_dir, registry=registry)
    return registry, resolve_runtime_config(config, registry)


def _scope(effective, **changes) -> RuntimeCredentialScope:
    values = {
        "runtime_id": effective.registration.runtime_id,
        "strategy_id": effective.strategy_id,
        "provider": "ctp",
        "provider_environment": "simnow",
        "policy_environment": effective.policy.environment,
        "mode": effective.mode,
        "preset": effective.preset,
        "account_access": effective.account_access,
        "account_fingerprint_sha256": "a" * 64,
        "secrets_ref": effective.config.secrets_ref,
        "credential_keys": CTP_AUTHENTICATION_CREDENTIAL_KEYS,
        "effective_config_digest": effective.effective_digest,
        "registration_digest": effective.registration.digest,
    }
    values.update(changes)
    return RuntimeCredentialScope(**values)


def _blob(values=SECRET_VALUES, **extra) -> bytes:
    document = {"credentials": dict(values)}
    document.update(extra)
    return json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _assert_no_secret(value: object) -> None:
    rendered = str(value)
    assert SECRET_VALUES["password"] not in rendered
    assert SECRET_VALUES["auth_code"] not in rendered


def test_windows_store_resolution_is_sealed_and_explicitly_non_authoritative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry, effective = _effective(runtime_dir)
    scope = _scope(effective)
    requested_targets = []

    def read_blob(target: str) -> bytes:
        requested_targets.append(target)
        return _blob()

    monkeypatch.setattr(credential_resolver, "_platform_name", lambda: "nt")
    monkeypatch.setattr(credential_resolver, "_read_windows_credential_blob", read_blob)

    resolved = resolve_runtime_credentials(effective, registry, scope)

    assert requested_targets == ["iteration41.ctp.simnow"]
    assert resolved.credential_names == CTP_AUTHENTICATION_CREDENTIAL_KEYS
    assert resolved.require_credential("broker_id") == SECRET_VALUES["broker_id"]
    assert resolved.require_credential("password") == SECRET_VALUES["password"]
    assert resolved.credentials_resolved is True
    assert resolved.provider_connected is False
    assert resolved.account_identity_verified is False
    assert resolved.preflight_authorized is False
    assert resolved.execution_authorized is False
    assert resolved.external_writes_authorized is False
    require_resolved_runtime_credentials_seal(resolved, effective, registry, scope)
    _assert_no_secret(repr(resolved))
    _assert_no_secret(resolved.as_public_dict())
    assert SECRET_REF not in repr(scope)
    assert SECRET_REF not in json.dumps(resolved.as_public_dict())
    with pytest.raises(TypeError, match="not an account"):
        bool(resolved)


def test_config_yaml_private_credentials_resolve_from_the_sealed_config_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry, effective = _effective(runtime_dir, "config_yaml")
    scope = _scope(effective)
    monkeypatch.setattr(credential_resolver, "_platform_name", lambda: "posix")
    if os.name != "posix":
        monkeypatch.setattr(
            credential_resolver, "_require_posix_private_config_acl", lambda *a: None
        )
    monkeypatch.setenv("CTP_PASSWORD", "environment-must-not-override-config")
    monkeypatch.setenv("CTP_USER_ID", "environment-account-must-not-override-config")

    def unexpected_read(*args, **kwargs):
        raise AssertionError("config_yaml credential resolution must not reread config.yaml")

    monkeypatch.setattr(credential_resolver, "_read_runtime_secrets_text", unexpected_read)
    monkeypatch.setattr(credential_resolver, "_read_windows_credential_blob", unexpected_read)
    resolved = resolve_runtime_credentials(effective, registry, scope)

    assert resolved.source == "config_yaml"
    assert resolved.credential_names == CTP_AUTHENTICATION_CREDENTIAL_KEYS
    assert resolved.require_credential("broker_id") == SECRET_VALUES["broker_id"]
    assert resolved.require_credential("user_id") == SECRET_VALUES["user_id"]
    assert resolved.require_credential("password") == SECRET_VALUES["password"]
    assert resolved.require_credential("app_id") == SECRET_VALUES["app_id"]
    assert resolved.require_credential("auth_code") == SECRET_VALUES["auth_code"]
    require_resolved_runtime_credentials_seal(resolved, effective, registry, scope)
    _assert_no_secret(repr(resolved))
    assert SECRET_VALUES["user_id"] not in repr(effective.config)
    assert SECRET_VALUES["broker_id"] not in str(effective.config.as_public_dict())


def test_config_yaml_resolution_fails_closed_on_windows_without_acl_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry, effective = _effective(runtime_dir, "config_yaml")
    scope = _scope(effective)
    monkeypatch.setattr(credential_resolver, "_platform_name", lambda: "nt")
    monkeypatch.setattr(
        credential_resolver,
        "_windows_acl_for_handle",
        lambda handle: credential_resolver._reject(
            "config_yaml_windows_acl_invalid", "synthetic wide ACL"
        ),
    )

    with pytest.raises(CredentialResolutionError) as caught:
        resolve_runtime_credentials(effective, registry, scope)

    assert caught.value.reason == "config_yaml_windows_acl_invalid"
    _assert_no_secret(caught.value)


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL handle inspection")
def test_windows_acl_gate_checks_runtime_directory_and_loaded_config_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry, effective = _effective(runtime_dir, "config_yaml")
    scope = _scope(effective)
    monkeypatch.setattr(credential_resolver, "_platform_name", lambda: "nt")
    inspected_handles = []
    monkeypatch.setattr(
        credential_resolver,
        "_windows_acl_for_handle",
        lambda handle: inspected_handles.append(handle),
    )

    resolved = resolve_runtime_credentials(effective, registry, scope)

    assert resolved.source == "config_yaml"
    assert len(inspected_handles) == 2
    require_resolved_runtime_credentials_seal(resolved, effective, registry, scope)


def test_windows_acl_policy_rejects_unknown_inherited_and_complex_aces() -> None:
    owner = "S-1-5-21-1-2-3-1001"
    credential_resolver._validate_windows_acl_owner(owner, owner)
    for invalid_owner in ("S-1-1-0", "S-1-5-32-544", "S-1-5-32-545", "S-1-5-21-9-8-7-2"):
        with pytest.raises(CredentialResolutionError) as caught:
            credential_resolver._validate_windows_acl_owner(invalid_owner, owner)
        assert caught.value.reason == "config_yaml_windows_acl_invalid"

    credential_resolver._validate_windows_dacl_control(True)
    with pytest.raises(CredentialResolutionError) as caught:
        credential_resolver._validate_windows_dacl_control(False)
    assert caught.value.reason == "config_yaml_windows_acl_invalid"

    allowed = (
        (0, 0, owner),
        (0, 0, "S-1-5-18"),
        (0, 0, "S-1-5-32-544"),
        (1, 0, owner),
    )
    credential_resolver._validate_windows_acl_entries(owner, allowed)

    with pytest.raises(CredentialResolutionError) as caught:
        credential_resolver._validate_windows_acl_entries("S-1-1-0", ())
    assert caught.value.reason == "config_yaml_windows_acl_invalid"

    for entry in (
        (0, 0, "S-1-1-0"),  # Everyone
        (0, 0, "S-1-5-32-545"),  # Builtin Users
        (0, 0, "S-1-5-11"),  # Authenticated Users
        (0, 0x10, owner),  # inherited ACE
        (5, 0, owner),  # object ACE, not a simple allow/deny ACE
    ):
        with pytest.raises(CredentialResolutionError) as caught:
            credential_resolver._validate_windows_acl_entries(owner, (entry,))
        assert caught.value.reason == "config_yaml_windows_acl_invalid"


def test_config_yaml_resolution_detects_private_credential_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry, effective = _effective(runtime_dir, "config_yaml")
    scope = _scope(effective)
    monkeypatch.setattr(credential_resolver, "_platform_name", lambda: "posix")
    if os.name != "posix":
        monkeypatch.setattr(
            credential_resolver, "_require_posix_private_config_acl", lambda *a: None
        )
    resolved = resolve_runtime_credentials(effective, registry, scope)

    object.__setattr__(effective.config.ctp_simnow, "password", "mutated-secret")
    with pytest.raises(RuntimeConfigError) as caught:
        require_resolved_runtime_credentials_seal(resolved, effective, registry, scope)
    assert caught.value.reason == "config_provenance_invalid"
    assert "mutated-secret" not in str(caught.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX private config permission recheck")
@pytest.mark.parametrize(
    ("unsafe_target", "unsafe_mode", "expected_reason"),
    (
        ("file", 0o644, "config_yaml_file_unsafe"),
        ("directory", 0o755, "config_yaml_directory_unsafe"),
    ),
)
def test_config_yaml_resolver_rejects_permissions_changed_after_load(
    tmp_path: Path,
    unsafe_target: str,
    unsafe_mode: int,
    expected_reason: str,
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry, effective = _effective(runtime_dir, "config_yaml")
    scope = _scope(effective)
    target = effective.config.source_path if unsafe_target == "file" else runtime_dir
    target.chmod(unsafe_mode)

    with pytest.raises(CredentialResolutionError) as caught:
        resolve_runtime_credentials(effective, registry, scope)

    assert caught.value.reason == expected_reason
    _assert_no_secret(caught.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX private config hard-link recheck")
def test_config_yaml_resolver_rejects_hard_link_added_after_load(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry, effective = _effective(runtime_dir, "config_yaml")
    scope = _scope(effective)
    os.link(effective.config.source_path, tmp_path / "unignored-copy.yaml")

    with pytest.raises(CredentialResolutionError) as caught:
        resolve_runtime_credentials(effective, registry, scope)

    assert caught.value.reason == "config_yaml_identity_invalid"
    _assert_no_secret(caught.value)


def test_scope_mismatch_cannot_reuse_a_sealed_credential_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry, effective = _effective(runtime_dir)
    scope = _scope(effective)
    monkeypatch.setattr(credential_resolver, "_platform_name", lambda: "nt")
    monkeypatch.setattr(
        credential_resolver, "_read_windows_credential_blob", lambda target: _blob()
    )
    resolved = resolve_runtime_credentials(effective, registry, scope)
    different_account = replace(scope, account_fingerprint_sha256="b" * 64)

    with pytest.raises(CredentialResolutionError) as caught:
        require_resolved_runtime_credentials_seal(resolved, effective, registry, different_account)

    assert caught.value.reason == "credential_resolution_provenance_invalid"
    _assert_no_secret(caught.value)


def test_per_access_seal_rejects_registration_changed_after_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry, effective = _effective(runtime_dir)
    scope = _scope(effective)
    monkeypatch.setattr(credential_resolver, "_platform_name", lambda: "nt")
    monkeypatch.setattr(
        credential_resolver, "_read_windows_credential_blob", lambda target: _blob()
    )
    resolved = resolve_runtime_credentials(effective, registry, scope)

    # A frozen registration can still be altered by hostile in-process code.
    # The later factory-facing seal must rebind the current registration
    # digest, rather than trusting only the resolver's original snapshot.
    object.__setattr__(
        effective.registration,
        "allowed_secrets_refs",
        ("os_secret_store:changed-after-resolution",),
    )

    with pytest.raises(CredentialResolutionError) as caught:
        require_resolved_runtime_credentials_seal(resolved, effective, registry, scope)

    assert caught.value.reason == "credential_scope_registration_mismatch"
    _assert_no_secret(caught.value)


@pytest.mark.parametrize(
    "changes,reason",
    (
        ({"runtime_id": "other.runtime"}, "credential_scope_runtime_mismatch"),
        ({"account_access": "direct_provider"}, "credential_scope_runtime_mismatch"),
        ({"effective_config_digest": "b" * 64}, "credential_scope_config_mismatch"),
        ({"registration_digest": "b" * 64}, "credential_scope_registration_mismatch"),
        ({"secrets_ref": "os_secret_store:another.ctp"}, "credential_scope_secret_ref_mismatch"),
    ),
)
def test_scope_mismatch_fails_before_secret_store_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changes, reason: str
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry, effective = _effective(runtime_dir)
    scope = _scope(effective, **changes)
    called = False

    def unexpected_read(target: str) -> bytes:
        del target
        nonlocal called
        called = True
        return _blob()

    monkeypatch.setattr(credential_resolver, "_platform_name", lambda: "nt")
    monkeypatch.setattr(credential_resolver, "_read_windows_credential_blob", unexpected_read)

    with pytest.raises(CredentialResolutionError) as caught:
        resolve_runtime_credentials(effective, registry, scope)

    assert caught.value.reason == reason
    assert called is False
    _assert_no_secret(caught.value)


def test_secret_payload_cannot_override_environment_or_leak_raw_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry, effective = _effective(runtime_dir)
    scope = _scope(effective)
    monkeypatch.setattr(credential_resolver, "_platform_name", lambda: "nt")
    monkeypatch.setattr(
        credential_resolver,
        "_read_windows_credential_blob",
        lambda target: _blob(environment="production"),
    )

    with pytest.raises(CredentialResolutionError) as caught:
        resolve_runtime_credentials(effective, registry, scope)

    assert caught.value.reason == "credential_document_controls_forbidden"
    _assert_no_secret(caught.value)


def test_credential_schema_rejects_control_key_and_missing_key() -> None:
    scope = RuntimeCredentialScope(
        runtime_id="runtime",
        strategy_id="strategy",
        provider="ctp",
        provider_environment="simnow",
        policy_environment="sandbox",
        mode="simulation",
        preset="sandbox",
        account_access="sandbox_private_read",
        account_fingerprint_sha256="a" * 64,
        secrets_ref=SECRET_REF,
        credential_keys=CTP_AUTHENTICATION_CREDENTIAL_KEYS,
        effective_config_digest="b" * 64,
        registration_digest="c" * 64,
    )
    control = {"credentials": dict(SECRET_VALUES, environment="production")}

    with pytest.raises(CredentialResolutionError) as caught:
        credential_resolver._credential_document_values(control, scope)
    assert caught.value.reason == "credential_document_controls_forbidden"
    _assert_no_secret(caught.value)

    missing = {"credentials": {"broker_id": "9999", "user_id": "u", "password": "p"}}
    with pytest.raises(CredentialResolutionError) as caught:
        credential_resolver._credential_document_values(missing, scope)
    assert caught.value.reason == "credential_schema_mismatch"


def test_ctp_scope_requires_neutral_simnow_and_rejects_profiled_sandbox_labels(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _registry, effective = _effective(runtime_dir)

    assert _scope(effective).provider_environment == "simnow"

    with pytest.raises(ValueError, match="SimNow"):
        _scope(effective, provider_environment="production")

    with pytest.raises(ValueError, match="SimNow"):
        _scope(effective, provider_environment="simnow_set0")

    with pytest.raises(ValueError, match="SimNow"):
        _scope(effective, provider_environment="simnow_set2")

    with pytest.raises(ValueError, match="exact production"):
        RuntimeCredentialScope(
            runtime_id="runtime",
            strategy_id="strategy",
            provider="ctp",
            provider_environment="simnow_set2",
            policy_environment="production",
            mode="live",
            preset="managed_live_direct",
            account_access="direct_provider",
            account_fingerprint_sha256="a" * 64,
            secrets_ref=SECRET_REF,
            credential_keys=CTP_AUTHENTICATION_CREDENTIAL_KEYS,
            effective_config_digest="b" * 64,
            registration_digest="c" * 64,
        )


def test_ctp_scope_requires_the_full_fixed_authentication_schema(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    _registry, effective = _effective(runtime_dir)

    with pytest.raises(ValueError, match="full fixed CTP schema"):
        _scope(effective, credential_keys=("broker_id", "password"))


def test_secret_store_json_rejects_duplicate_or_non_utf8_blob_without_echoing_content() -> None:
    duplicate = (
        b'{"credentials":{"broker_id":"9999","user_id":"u","password":"'
        + SECRET_VALUES["password"].encode("utf-8")
        + b'","password":"replacement"}}'
    )
    with pytest.raises(CredentialResolutionError) as caught:
        credential_resolver._load_secret_store_json(duplicate)
    assert caught.value.reason == "os_secret_store_blob_invalid"
    _assert_no_secret(caught.value)

    with pytest.raises(CredentialResolutionError) as caught:
        credential_resolver._load_secret_store_json(b"\xff")
    assert caught.value.reason == "os_secret_store_blob_invalid"


class _FakeCredentialManager:
    """Synthetic WinAPI result; it does not touch the user's credential store."""

    def __init__(self, target: str, blob: bytes, *, credential_type: int = 1) -> None:
        self.target = target
        self.blob = ctypes.create_string_buffer(blob)
        self.target_buffer = ctypes.create_unicode_buffer(target)
        self.credential = credential_resolver._WindowsCredentialW()
        self.credential.Type = credential_type
        self.credential.TargetName = ctypes.cast(
            self.target_buffer, credential_resolver.wintypes.LPWSTR
        )
        self.credential.CredentialBlobSize = len(blob)
        self.credential.CredentialBlob = ctypes.cast(self.blob, ctypes.POINTER(ctypes.c_ubyte))
        self.pointer = ctypes.pointer(self.credential)
        self.read_calls = []
        self.free_calls = 0

    def cred_read(self, target, credential_type, flags, result) -> bool:
        self.read_calls.append((target, credential_type, flags))
        output = ctypes.cast(
            result,
            ctypes.POINTER(ctypes.POINTER(credential_resolver._WindowsCredentialW)),
        )
        output[0] = self.pointer
        return True

    def cred_free(self, pointer) -> None:
        assert bool(pointer)
        self.free_calls += 1


def test_credreadw_generic_target_and_cred_free_are_used_with_a_mock_api() -> None:
    target = "iteration41.ctp.simnow"
    blob = _blob()
    fake = _FakeCredentialManager(target, blob)
    api = credential_resolver._WindowsCredentialApi(fake.cred_read, fake.cred_free)

    observed = credential_resolver._read_windows_credential_blob(target, api)

    assert observed == blob
    assert fake.read_calls == [(target, 1, 0)]
    assert fake.free_calls == 1


def test_credreadw_scope_rejection_still_frees_mock_allocation() -> None:
    fake = _FakeCredentialManager("wrong-target", _blob())
    api = credential_resolver._WindowsCredentialApi(fake.cred_read, fake.cred_free)

    with pytest.raises(CredentialResolutionError) as caught:
        credential_resolver._read_windows_credential_blob("expected-target", api)

    assert caught.value.reason == "os_secret_store_credential_scope_mismatch"
    assert fake.free_calls == 1
    _assert_no_secret(caught.value)


def test_credreadw_rejects_untrusted_metadata_and_still_frees_mock_allocation() -> None:
    target = "iteration41.ctp.simnow"
    fake = _FakeCredentialManager(target, _blob())
    fake.credential.Comment = "not-a-payload"
    api = credential_resolver._WindowsCredentialApi(fake.cred_read, fake.cred_free)

    with pytest.raises(CredentialResolutionError) as caught:
        credential_resolver._read_windows_credential_blob(target, api)

    assert caught.value.reason == "os_secret_store_credential_metadata_invalid"
    assert fake.free_calls == 1
    _assert_no_secret(caught.value)


def test_credreadw_unexpected_exception_is_redacted_and_frees_output_pointer() -> None:
    target = "iteration41.ctp.simnow"
    fake = _FakeCredentialManager(target, _blob())

    def raises_after_assigning_output(target_name, credential_type, flags, result) -> bool:
        assert (target_name, credential_type, flags) == (target, 1, 0)
        output = ctypes.cast(
            result,
            ctypes.POINTER(ctypes.POINTER(credential_resolver._WindowsCredentialW)),
        )
        output[0] = fake.pointer
        raise RuntimeError(SECRET_VALUES["password"])

    api = credential_resolver._WindowsCredentialApi(
        raises_after_assigning_output,
        fake.cred_free,
    )

    with pytest.raises(CredentialResolutionError) as caught:
        credential_resolver._read_windows_credential_blob(target, api)

    assert caught.value.reason == "os_secret_store_credential_invalid"
    assert fake.free_calls == 1
    _assert_no_secret(caught.value)


def test_runtime_secrets_has_no_windows_cwd_or_environment_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry, effective = _effective(runtime_dir, "runtime_secrets")
    scope = _scope(effective)
    (tmp_path / "secrets.yaml").write_text(
        "credentials:\n  password: sentinel-raw-password-never-log\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CTP_PASSWORD", SECRET_VALUES["password"])
    monkeypatch.setattr(credential_resolver, "_platform_name", lambda: "nt")

    with pytest.raises(CredentialResolutionError) as caught:
        resolve_runtime_credentials(effective, registry, scope)

    assert caught.value.reason == "runtime_secrets_platform_acl_unavailable"
    _assert_no_secret(caught.value)


@pytest.mark.skipif(
    os.name != "posix", reason="runtime_secrets requires POSIX owner/permission checks"
)
def test_posix_runtime_secrets_is_bound_to_the_registered_directory(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(mode=0o700)
    os.chmod(runtime_dir, 0o700)
    registry, effective = _effective(runtime_dir, "runtime_secrets")
    scope = _scope(effective)
    secret_file = runtime_dir / "secrets.yaml"
    secret_file.write_text(
        "credentials:\n"
        "  broker_id: '9999'\n"
        "  user_id: 'test-user-001'\n"
        "  password: 'sentinel-raw-password-never-log'\n"
        "  app_id: 'simnow-app'\n"
        "  auth_code: 'sentinel-raw-auth-code-never-log'\n",
        encoding="utf-8",
    )
    os.chmod(secret_file, stat.S_IRUSR | stat.S_IWUSR)

    resolved = resolve_runtime_credentials(effective, registry, scope)

    assert resolved.require_credential("user_id") == SECRET_VALUES["user_id"]
    require_resolved_runtime_credentials_seal(resolved, effective, registry, scope)
    _assert_no_secret(repr(resolved))


@pytest.mark.skipif(
    os.name != "posix", reason="runtime_secrets requires POSIX descriptor operations"
)
def test_posix_runtime_secrets_rejects_symlink_and_unsafe_permissions(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(mode=0o700)
    os.chmod(runtime_dir, 0o700)
    registry, effective = _effective(runtime_dir, "runtime_secrets")
    scope = _scope(effective)
    outside = tmp_path / "outside.yaml"
    outside.write_text("credentials: {}\n", encoding="utf-8")
    secret_file = runtime_dir / "secrets.yaml"
    secret_file.symlink_to(outside)

    with pytest.raises(CredentialResolutionError) as caught:
        resolve_runtime_credentials(effective, registry, scope)
    assert caught.value.reason == "runtime_secrets_symlink_not_allowed"

    secret_file.unlink()
    secret_file.write_text("credentials: {}\n", encoding="utf-8")
    os.chmod(secret_file, 0o644)
    with pytest.raises(CredentialResolutionError) as caught:
        resolve_runtime_credentials(effective, registry, scope)
    assert caught.value.reason == "runtime_secrets_file_unsafe"


@pytest.mark.skipif(
    os.name != "posix", reason="runtime_secrets requires POSIX descriptor operations"
)
def test_posix_runtime_secrets_requires_non_following_leaf_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(mode=0o700)
    os.chmod(runtime_dir, 0o700)
    registry, effective = _effective(runtime_dir, "runtime_secrets")
    scope = _scope(effective)
    secret_file = runtime_dir / "secrets.yaml"
    secret_file.write_text("credentials: {}\n", encoding="utf-8")
    os.chmod(secret_file, stat.S_IRUSR | stat.S_IWUSR)

    monkeypatch.delattr(credential_resolver.os, "O_NOFOLLOW", raising=False)

    with pytest.raises(CredentialResolutionError) as caught:
        resolve_runtime_credentials(effective, registry, scope)

    assert caught.value.reason == "runtime_secrets_platform_acl_unavailable"


def test_directly_constructed_result_is_not_accepted_as_resolver_output(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry, effective = _effective(runtime_dir)
    scope = _scope(effective)
    forged = ResolvedRuntimeCredentials(
        scope=scope,
        source="os_secret_store",
        _values=dict(SECRET_VALUES),
    )

    with pytest.raises(CredentialResolutionError) as caught:
        require_resolved_runtime_credentials_seal(forged, effective, registry, scope)

    assert caught.value.reason == "credential_resolution_provenance_invalid"
    _assert_no_secret(caught.value)
