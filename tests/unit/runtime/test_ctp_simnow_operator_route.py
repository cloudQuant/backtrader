"""Config-first CTP SimNow operator dispatch contracts.

All credential-store and native SDK behavior is faked here.  These tests do
not connect to SimNow or issue any CTP request.
"""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import socket
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import backtrader_runtime.cli as runtime_cli
import backtrader_runtime.config as runtime_config
import backtrader_runtime.credential_resolver as credential_resolver
import backtrader_runtime.ctp_simnow_operator as simnow_operator
import backtrader_runtime.ctp_simnow_readonly_runtime as readonly_runtime
import backtrader_runtime.registry as runtime_registry_module
import backtrader_runtime.inventory as runtime_inventory
import backtrader_runtime.ctp_front_pair_probe as front_pair_probe
from backtrader_runtime.cli import build_parser, main
from backtrader_runtime.ctp_simnow_operator import (
    CtpSimNowConfigReadOnlyBinding,
    CtpSimNowReadOnlyBinding,
)
from backtrader_runtime.errors import RuntimeConfigError
from backtrader_runtime.inventory import iteration41_runtime_registry
from backtrader_runtime.policy import MANAGED_WRITE_CAPABILITIES
from backtrader_runtime.registry import (
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    bootstrap_runtime_config,
    resolve_runtime_config,
    validate_runtime_config,
)


RUNTIME_ID = "iteration41.ctp.simnow.readonly.operator-test"
STRATEGY_ID = "iteration41.ctp.sandbox_readonly.operator_test"
SECRET_REF = "os_secret_store:iteration41.ctp.simnow.readonly.operator-test"
ACCOUNT_FINGERPRINT = hashlib.sha256(b"9999:operator-test").hexdigest()
SECRETS = {
    "broker_id": "9999",
    "user_id": "operator-test",
    "password": "sentinel-raw-password-must-not-appear",
    "app_id": "reviewed-app",
    "auth_code": "sentinel-raw-auth-code-must-not-appear",
}
WRITE_KEYS = ("settlement_confirm", "order_insert", "order_action")
QUERY_NAMES = (
    "account",
    "positions",
    "orders",
    "trades",
    "instruments",
    "margin_rate",
    "commission_rate",
)


def _write_config(runtime_dir: Path) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "config.yaml").write_text(
        """config_schema_version: 4
strategy:
  id: {strategy_id}
runtime:
  mode: simulation
  preset: sandbox
parameters: {{}}
secrets_ref: {secrets_ref}
""".format(
            strategy_id=STRATEGY_ID, secrets_ref=SECRET_REF
        ),
        encoding="utf-8",
    )


def _registered_runtime(runtime_dir: Path, **changes) -> RegisteredRuntime:
    fields = {
        "runtime_dir": runtime_dir,
        "runtime_id": RUNTIME_ID,
        "strategy_id": STRATEGY_ID,
        "allowed_presets": ("sandbox",),
        "allowed_parameter_keys": (),
        "allowed_secrets_refs": (SECRET_REF,),
        "available_capabilities": (),
        "offline_managed_execution": False,
        "sandbox_write_policy": "deny",
        "approval_receipt_digest": None,
        "runner_module": None,
        "capability_modules": (),
    }
    fields.update(changes)
    return RegisteredRuntime(**fields)


def _binding(**changes) -> CtpSimNowReadOnlyBinding:
    fields = {
        "runtime_id": RUNTIME_ID,
        "environment": "simnow_set2",
        "sdk_profile": "set2_7x24",
        "account_fingerprint_sha256": ACCOUNT_FINGERPRINT,
        "secrets_ref": SECRET_REF,
        "instrument_id": "IF2612",
        "exchange_id": "CFFEX",
        "hedge_flag": "1",
        "session_ttl_seconds": 30,
    }
    fields.update(changes)
    return CtpSimNowReadOnlyBinding(**fields)


def _registry(runtime_dir: Path, *, binding: bool = True, **registration_changes):
    _write_config(runtime_dir)
    registration = _registered_runtime(runtime_dir, **registration_changes)
    bindings = (_binding(),) if binding else ()
    return RuntimeRegistry(
        (registration,),
        ctp_simnow_readonly_bindings=bindings,
        registry_id="test.ctp.simnow.operator",
    )


class _FakeClient:
    instances = []

    def __init__(
        self,
        front,
        broker_id,
        user_id,
        password,
        *,
        app_id,
        auth_code,
        auto_settlement_confirm,
    ) -> None:
        assert (broker_id, user_id) == (SECRETS["broker_id"], SECRETS["user_id"])
        assert password == SECRETS["password"]
        assert app_id == SECRETS["app_id"]
        assert auth_code == SECRETS["auth_code"]
        assert auto_settlement_confirm is False
        self.front = front
        self.stopped = 0
        self.calls = []
        self.counts = dict.fromkeys(WRITE_KEYS, 0)
        type(self).instances.append(self)

    def start(self, *, block: bool) -> None:
        assert block is False

    def wait_ready(self, *, timeout: float) -> bool:
        assert 0 < timeout <= 15
        return True

    def stop(self) -> None:
        self.stopped += 1

    def get_session_state(self):
        return {"auto_settlement_confirm": False}

    def get_query_session_scope(self):
        return SimpleNamespace(
            read_only_ready=True,
            broker_id=SECRETS["broker_id"],
            investor_id=SECRETS["user_id"],
            trading_day="20260923",
            connection_generation=4,
        )

    def get_front_binding_state(self):
        return {
            "configured_front": self.front,
            "registered_front": self.front,
            "connection_confirmed_front": self.front,
            "connected": True,
            "native_api_current": True,
            "bound_identity_current": True,
            "connection_generation": 4,
        }

    def get_request_counts(self):
        return dict(self.counts)

    def _query(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return name

    def query_account_result(self, **kwargs):
        return self._query("account", **kwargs)

    def query_positions_result(self, **kwargs):
        return self._query("positions", **kwargs)

    def query_orders_result(self, **kwargs):
        return self._query("orders", **kwargs)

    def query_trades_result(self, **kwargs):
        return self._query("trades", **kwargs)

    def query_instruments_result(self, **kwargs):
        return self._query("instruments", **kwargs)

    def query_instrument_margin_rate_result(self, instrument_id, **kwargs):
        return self._query("margin_rate", instrument_id=instrument_id, **kwargs)

    def query_instrument_commission_rate_result(self, instrument_id, **kwargs):
        return self._query("commission_rate", instrument_id=instrument_id, **kwargs)


class _FakeCertificateBuilder:
    def __init__(self, client, *, instrument_id, exchange_id, hedge_flag) -> None:
        assert isinstance(client, _FakeClient)
        assert (instrument_id, exchange_id, hedge_flag) == ("IF2612", "CFFEX", "1")
        self.names = []

    def add(self, result) -> None:
        self.names.append(result)

    def finish(self):
        assert tuple(self.names) == QUERY_NAMES
        return SimpleNamespace(
            query_digests=tuple(
                (name, hashlib.sha256(name.encode("ascii")).hexdigest()) for name in self.names
            ),
            certificate_sha256=hashlib.sha256(b"simnow-operator-fake-certificate").hexdigest(),
        )


def _components():
    return _FakeClient, _FakeCertificateBuilder


@pytest.fixture(autouse=True)
def _fake_native_composition(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readonly_runtime, "_default_sdk_components", _components)

    def fake_front_selection(front_pairs):
        pair = front_pairs[0]
        return SimpleNamespace(
            pair=front_pair_probe.CtpConfiguredFrontPair(
                md_front=pair["md_front"],
                td_front=pair["td_front"],
            )
        )

    monkeypatch.setattr(simnow_operator, "_select_configured_front_pair", fake_front_selection)

    def reject_socket(*args, **kwargs):
        del args, kwargs
        raise AssertionError("operator route tests must never open a real socket")

    monkeypatch.setattr(socket, "socket", reject_socket)

    def accept_synthetic_test_artifact_pin(*, td_front: str, md_front: str) -> None:
        # A private test-only seam: the deployed verifier remains fail-closed
        # with an empty production pin catalog.  This fake does not establish
        # artifact provenance or enable a real CTP account route.
        assert type(td_front) is str and td_front.startswith("tcp://")
        assert type(md_front) is str and md_front.startswith("tcp://")

    monkeypatch.setattr(
        readonly_runtime,
        "verify_ctp_sdk_artifact_provenance_for_fronts",
        accept_synthetic_test_artifact_pin,
    )

    @contextmanager
    def installed_context(capability_modules):
        assert capability_modules == ("bt_api_base", "bt_api_ctp")
        yield

    monkeypatch.setattr(
        readonly_runtime, "trusted_installed_capability_import_context", installed_context
    )
    monkeypatch.setattr(credential_resolver, "_platform_name", lambda: "nt")
    monkeypatch.setattr(
        credential_resolver,
        "_read_windows_credential_blob",
        lambda target: json.dumps({"credentials": SECRETS}).encode("utf-8"),
    )
    _FakeClient.instances.clear()


def _payload(stream: io.StringIO) -> dict:
    return json.loads(stream.getvalue())


def test_parser_exposes_only_strategy_dir_for_preflight() -> None:
    parser = build_parser()
    parsed = parser.parse_args(["preflight", "--strategy-dir", "runtime"])
    assert parsed.command == "preflight"
    assert parsed.strategy_dir == Path("runtime")
    assert not hasattr(parsed, "sdk_profile")
    assert not hasattr(parsed, "account_fingerprint")
    assert not hasattr(parsed, "secrets_ref")


def test_help_centers_shared_ctp_config_without_a_second_production_config_command() -> None:
    help_text = " ".join(build_parser().format_help().split())

    assert "prepare-ctp-config" in help_text
    assert "prepare-ctp-simnow-config legacy alias for prepare-ctp-config" in help_text
    assert "prepare-ctp-production-config" not in help_text


def test_default_inventory_registers_only_config_bound_private_read_scope() -> None:
    registry = iteration41_runtime_registry()
    registration = registry.require_runtime_dir(
        runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
    )
    assert registration is runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION
    simnow_007 = registry.require_runtime_dir(
        runtime_inventory.ITERATION41_007_CTP_PRIVATE_RUNTIME_DIR
    )
    assert simnow_007 is runtime_inventory.ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION
    assert registry.ctp_simnow_readonly_bindings == (
        runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_READONLY_BINDING,
        runtime_inventory.ITERATION41_007_CTP_PRIVATE_READONLY_BINDING,
    )
    assert registration.allowed_presets == ()
    assert registration.allowed_secrets_refs == ("none",)
    assert tuple((profile.mode, profile.preset) for profile in registration.profiles) == (
        ("simulation", "sandbox"),
    )
    assert registration.profiles[0].allowed_secrets_refs == ("config_yaml",)
    assert registration.available_capabilities == ()
    assert registration.sandbox_write_policy == "deny"
    assert registration.runner_module is None
    assert registration.capability_modules == ()
    assert simnow_007.allowed_presets == ()
    assert simnow_007.allowed_secrets_refs == ("none",)
    assert tuple((profile.mode, profile.preset) for profile in simnow_007.profiles) == (
        ("simulation", "sandbox"),
    )
    assert simnow_007.profiles[0].allowed_secrets_refs == ("config_yaml",)
    assert simnow_007.profiles[0].available_capabilities == ()
    assert simnow_007.profiles[0].runner_module is None
    assert simnow_007.profiles[0].sandbox_write_policy == "deny"
    assert simnow_007.available_capabilities == ()
    assert simnow_007.sandbox_write_policy == "deny"
    assert simnow_007.runner_module is None
    assert simnow_007.capability_modules == ()
    assert all(
        "sandbox" not in entry.allowed_presets
        for entry in registry.registrations
        if entry not in (registration, simnow_007)
    )


def test_profile_registry_dispatch_rejects_before_binding_lookup_or_front_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path)
    profile = RuntimeProfile(
        mode="simulation",
        preset="sandbox",
        allowed_parameter_keys=(),
        allowed_secrets_refs=(SECRET_REF,),
        available_capabilities=(),
        approval_receipt_digest=None,
        runner_module=None,
        runner_entrypoint="run_runtime",
        capability_modules=(),
        offline_managed_execution=False,
        sandbox_write_policy="deny",
    )
    registration = RegisteredRuntime(
        runtime_dir=tmp_path,
        runtime_id=RUNTIME_ID,
        strategy_id=STRATEGY_ID,
        allowed_presets=(),
        profiles=(profile,),
    )
    registry = RuntimeRegistry((registration,), registry_id="test.ctp.profile.operator")
    effective = resolve_runtime_config(
        runtime_config.load_runtime_config(tmp_path, registry=registry), registry
    )
    injected_binding = CtpSimNowConfigReadOnlyBinding(runtime_id=RUNTIME_ID)
    binding_lookups = []
    front_probes = []

    def return_injected_binding(runtime_id: str):
        binding_lookups.append(runtime_id)
        return injected_binding

    def forbidden_front_probe(front_pairs):
        front_probes.append(front_pairs)
        pytest.fail("profile-backed CTP dispatch reached front selection")

    monkeypatch.setattr(registry, "require_ctp_simnow_readonly_binding", return_injected_binding)
    monkeypatch.setattr(simnow_operator, "_select_configured_front_pair", forbidden_front_probe)

    with pytest.raises(RuntimeConfigError) as caught:
        simnow_operator.dispatch_registered_ctp_simnow_readonly_preflight(effective, registry)

    assert caught.value.reason == "ctp_simnow_preflight_profile_dispatch_unavailable"
    assert binding_lookups == []
    assert front_probes == []


def test_shared_private_runtime_parses_live_config_but_default_cli_stops_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mirror the real user's canonical config location without opening or
    # changing the protected runtime directory under examples/.
    runtime_dir = tmp_path / "examples" / "013_3_sa_midfreq_simnow" / "runtime-ctp-private"
    runtime_dir.mkdir(parents=True)
    registration = replace(
        runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION,
        runtime_dir=runtime_dir,
    )
    monkeypatch.setattr(
        runtime_inventory,
        "ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION",
        registration,
    )
    registry = iteration41_runtime_registry()

    config_path = runtime_dir / "config.yaml"
    config_path.write_text(
        """config_schema_version: 4
strategy:
  id: example.013_3.sa_midfreq_simnow
runtime:
  mode: live
  preset: managed_live_direct
parameters: {}
secrets_ref: config_yaml
ctp:
  front_pairs:
    - md_front: tcp://192.0.2.31:41211
      td_front: tcp://192.0.2.30:41201
    - md_front: tcp://192.0.2.41:41211
      td_front: tcp://192.0.2.40:41201
  instrument_id: SA701
  exchange_id: CZCE
  hedge_flag: "1"
  broker_id: "9999"
  user_id: synthetic-production-placeholder
  password: synthetic-password-placeholder
  app_id: synthetic-app-placeholder
  auth_code: synthetic-auth-placeholder
""",
        encoding="utf-8",
    )
    if runtime_config.os.name == "posix":
        runtime_dir.chmod(0o700)
        config_path.chmod(0o600)
    elif runtime_config.os.name == "nt":
        # This test verifies parser/seal and route policy using synthetic
        # placeholder credentials; real Windows ACL behavior has its own tests.
        monkeypatch.setattr(
            runtime_config, "_require_private_config_security", lambda *a, **k: None
        )

    parsed = runtime_config.load_runtime_config(runtime_dir, registry=registry)
    runtime_config.require_loaded_runtime_config_seal(parsed, registry)
    assert parsed.source_path == config_path
    assert parsed.strategy_dir == runtime_dir.resolve()
    assert parsed.mode == "live"
    assert parsed.preset == "managed_live_direct"
    assert parsed.ctp is not None
    assert parsed.ctp.front_pairs[0]["md_front"] == "tcp://192.0.2.31:41211"
    assert parsed.ctp.front_pairs[1]["td_front"] == "tcp://192.0.2.40:41201"
    assert parsed.ctp_production is None
    assert parsed.ctp_simnow is None

    touched = []
    original_import = builtins.__import__

    def reject_provider_or_runner_import(name, *args, **kwargs):
        if name.split(".", 1)[0].startswith("bt_api_") or name.endswith(
            "examples.013_3_sa_midfreq_simnow.run_runtime"
        ):
            touched.append(("import", name))
            raise AssertionError("unregistered live config crossed into provider/runner code")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_provider_or_runner_import)
    credential_calls = []
    monkeypatch.setattr(
        credential_resolver,
        "resolve_runtime_credentials",
        lambda *args, **kwargs: credential_calls.append((args, kwargs)),
    )
    socket_attempts = []

    def reject_socket(*args, **kwargs):
        socket_attempts.append((args, kwargs))
        raise AssertionError("unregistered live config crossed into network code")

    monkeypatch.setattr(socket, "socket", reject_socket)
    dispatches = []

    def reject_dispatch(*args, **kwargs):
        dispatches.append((args, kwargs))
        raise AssertionError("unregistered live config crossed into a runtime dispatcher")

    monkeypatch.setattr(runtime_cli, "dispatch_registered_runtime", reject_dispatch)
    monkeypatch.setattr(
        runtime_cli, "dispatch_registered_ctp_simnow_readonly_preflight", reject_dispatch
    )

    for command in ("validate", "doctor", "preflight", "run"):
        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(
            [command, "--strategy-dir", str(runtime_dir)],
            registry=registry,
            environ={},
            stdout=stdout,
            stderr=stderr,
        )

        assert status == 2
        assert stdout.getvalue() == ""
        rejection = _payload(stderr)
        expected_reason = (
            "ctp_simnow_preflight_supervisor_required"
            if command == "preflight"
            else "managed_live_direct_profile_unavailable"
        )
        assert rejection["reason"] == expected_reason
        action = rejection["diagnostic"]["next_actions"][0]
        if command == "preflight":
            assert action["action"] == "preflight_requires_process_supervisor"
            assert "hard process supervisor" in action["note"]
        else:
            assert action["action"] == "review_live_enablement"
            assert "same protected config.yaml" in action["note"]
            assert "shared CTP execution runner" in action["note"]
            assert "live dispatch" in action["note"]
            assert "production-specific admission" in action["note"]
            assert "editing mode or parameters alone does not enable trading" in action["note"]
        assert "command" not in action
        assert rejection["diagnostic"]["provider_preflight_started"] is False
        assert "synthetic-password-placeholder" not in stderr.getvalue()
        assert "synthetic-production-placeholder" not in stderr.getvalue()

    assert credential_calls == []
    assert socket_attempts == []
    assert dispatches == []
    assert touched == []


def test_default_doctor_and_preflight_report_missing_reserved_config_without_sdk_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use a disposable test route. Never inspect the user's ignored private
    # runtime config: its presence is a local operator choice, not test state.
    runtime_dir = tmp_path / "runtime-without-config"
    runtime_dir.mkdir()
    registration = _registered_runtime(
        runtime_dir,
        allowed_secrets_refs=("config_yaml",),
    )
    registry = RuntimeRegistry(
        (registration,),
        ctp_simnow_readonly_bindings=(CtpSimNowConfigReadOnlyBinding(runtime_id=RUNTIME_ID),),
        registry_id="test.ctp.simnow.missing-private-config",
    )
    imports = []
    original_import = builtins.__import__

    def reject_provider_import(name, *args, **kwargs):
        if name.endswith("ctp_simnow_readonly_runtime") or name.split(".", 1)[0].startswith(
            "bt_api_"
        ):
            imports.append(name)
            raise AssertionError("missing private config must reject before provider imports")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_provider_import)
    credential_calls = []
    monkeypatch.setattr(
        credential_resolver,
        "resolve_runtime_credentials",
        lambda *args, **kwargs: credential_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *args, **kwargs: pytest.fail("missing private config must reject before sockets"),
    )

    for command in ("doctor", "preflight"):
        stdout, stderr = io.StringIO(), io.StringIO()
        status = main(
            [command, "--strategy-dir", str(runtime_dir)],
            registry=registry,
            environ={},
            stdout=stdout,
            stderr=stderr,
        )

        assert status == 2
        assert stdout.getvalue() == ""
        rejection = _payload(stderr)
        assert rejection["reason"] == "missing_config"
        assert rejection["diagnostic"]["provider_preflight_started"] is False
        assert rejection["diagnostic"]["next_actions"][0]["action"] == (
            "prepare_ctp_private_config"
        )
        action = rejection["diagnostic"]["next_actions"][0]
        assert "runtime-ctp-private/config.yaml" in action["note"]
        assert "canonical top-level ctp mapping" in action["note"]
        assert "changing mode/preset alone does not register a production route" in action["note"]
        assert all(example[1] == "prepare-ctp-config" for example in action["command_examples"])
        assert "password" not in stderr.getvalue().lower()
        assert "auth_code" not in stderr.getvalue().lower()
        assert "operator-test" not in stderr.getvalue()

    assert credential_calls == []
    assert imports == []


def test_registered_013_3_preflight_fails_closed_before_config_or_provider_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_dir = runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
    registry = runtime_registry_module.default_runtime_registry()
    touched = []

    def reject_config_load(*args, **kwargs):
        touched.append("config")
        raise AssertionError("ordinary preflight gate must run before config loading")

    monkeypatch.setattr(runtime_cli, "validate_runtime_config", reject_config_load)
    monkeypatch.setattr(
        credential_resolver,
        "resolve_runtime_credentials",
        lambda *args, **kwargs: touched.append("credentials"),
    )
    monkeypatch.setattr(
        runtime_cli,
        "dispatch_registered_ctp_simnow_readonly_preflight",
        lambda *args, **kwargs: touched.append("preflight_dispatch"),
    )
    monkeypatch.setattr(
        runtime_cli,
        "dispatch_registered_runtime",
        lambda *args, **kwargs: touched.append("runner_dispatch"),
    )
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *args, **kwargs: touched.append("socket"),
    )
    original_import = builtins.__import__

    def reject_provider_import(name, *args, **kwargs):
        if name.split(".", 1)[0].startswith("bt_api_") or name.endswith(
            "ctp_simnow_readonly_runtime"
        ):
            touched.append("sdk_import")
            raise AssertionError("ordinary preflight gate must precede SDK imports")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_provider_import)
    stdout, stderr = io.StringIO(), io.StringIO()

    status = runtime_cli.main(
        ["preflight", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=stdout,
        stderr=stderr,
    )

    rejection = _payload(stderr)
    assert status == 2
    assert stdout.getvalue() == ""
    assert rejection["reason"] == "ctp_simnow_preflight_supervisor_required"
    assert rejection["diagnostic"]["offline"] is True
    assert rejection["diagnostic"]["provider_preflight_started"] is False
    action = rejection["diagnostic"]["next_actions"][0]
    assert action["action"] == "preflight_requires_process_supervisor"
    assert "hard process supervisor" in action["note"]
    assert "before credentials, SDK import, or provider/network I/O" in action["note"]
    assert touched == []


def test_bootstrap_rejects_incomplete_private_sandbox_config(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registration = _registered_runtime(runtime_dir)
    registry = RuntimeRegistry(
        (registration,),
        ctp_simnow_readonly_bindings=(_binding(),),
        registry_id="test.ctp.simnow.bootstrap",
    )

    with pytest.raises(RuntimeConfigError) as caught:
        bootstrap_runtime_config(runtime_dir, registry, "sandbox")

    assert caught.value.reason == "ctp_simnow_private_config_required"
    assert not (runtime_dir / "config.yaml").exists()

    stdout, stderr = io.StringIO(), io.StringIO()
    status = main(
        ["bootstrap", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=stdout,
        stderr=stderr,
    )
    assert status == 2
    guidance = _payload(stderr)["diagnostic"]["next_actions"][0]["note"]
    assert "runtime-ctp-private/README.md" in guidance
    assert "bt-runtime prepare-ctp-config" in guidance
    assert "private template" not in guidance
    assert not (runtime_dir / "config.yaml").exists()


def test_doctor_requires_config_driven_front_binding_for_preflight(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "runtime"
    registry = _registry(runtime_dir)
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = main(
        ["doctor", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 0, stderr.getvalue()
    diagnostic = _payload(stdout)["diagnostic"]
    assert diagnostic["offline"] is True
    assert diagnostic["provider_preflight_started"] is False
    assert diagnostic["operator_summary"]["destination"] == "sandbox_private_account_read"
    action = diagnostic["next_actions"][0]
    assert action["action"] == "review_registration"
    assert "config-driven CTP front-pair policy" in action["note"]
    assert "preflight" not in action
    assert _FakeClient.instances == []


def test_preflight_rejects_policy_override(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    registry = _registry(runtime_dir)
    stderr = io.StringIO()

    status = main(
        ["preflight", "--strategy-dir", str(runtime_dir), "--preset", "replay"],
        registry=registry,
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejection = _payload(stderr)
    assert rejection["reason"] == "cli_override_not_allowed"
    assert rejection["diagnostic"]["next_actions"][0]["rejected_arguments"] == ["--preset"]


def test_preflight_rejects_attempt_to_supply_scope_on_command_line(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    registry = _registry(runtime_dir)
    stderr = io.StringIO()

    status = main(
        ["preflight", "--strategy-dir", str(runtime_dir), "--sdk-profile", "set1_test"],
        registry=registry,
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejection = _payload(stderr)
    assert rejection["reason"] == "cli_argument_not_allowed"
    assert "set1_test" not in stderr.getvalue()


def test_preflight_without_code_owned_binding_rejects_before_credentials_or_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime"
    registry = _registry(runtime_dir, binding=False)
    credential_calls = []
    monkeypatch.setattr(
        credential_resolver,
        "resolve_runtime_credentials",
        lambda *args, **kwargs: credential_calls.append((args, kwargs)),
    )
    config_load_calls = []

    def reject_config_load(*args, **kwargs):
        config_load_calls.append((args, kwargs))
        raise AssertionError("a missing read-only binding must fail before config loading")

    monkeypatch.setattr(runtime_cli, "load_runtime_config", reject_config_load)
    monkeypatch.setattr(runtime_config, "load_runtime_config", reject_config_load)
    monkeypatch.setattr(runtime_registry_module, "load_runtime_config", reject_config_load)
    config_byte_reads = []
    original_os_read = runtime_config.os.read

    def track_config_byte_reads(fd, size):
        config_byte_reads.append((fd, size))
        return original_os_read(fd, size)

    monkeypatch.setattr(runtime_config.os, "read", track_config_byte_reads)
    socket_attempts = []

    def reject_socket(*args, **kwargs):
        socket_attempts.append((args, kwargs))
        raise AssertionError("a missing route must fail before socket creation")

    monkeypatch.setattr(socket, "socket", reject_socket)
    imports = []
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.endswith("ctp_simnow_readonly_runtime") or name.split(".", 1)[0].startswith(
            "bt_api_"
        ):
            imports.append(name)
            raise AssertionError("a missing route must fail before CTP composition import")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = main(
        ["preflight", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 2
    rejection = _payload(stderr)
    assert rejection["reason"] == "ctp_simnow_preflight_route_unregistered"
    assert rejection["diagnostic"]["next_actions"][0]["action"] == "review_registration"
    assert config_load_calls == []
    assert config_byte_reads == []
    assert credential_calls == []
    assert socket_attempts == []
    assert imports == []


def test_preflight_rejects_static_binding_before_loading_config(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry = RuntimeRegistry(
        (_registered_runtime(runtime_dir),),
        ctp_simnow_readonly_bindings=(_binding(),),
        registry_id="test.ctp.simnow.missing-config",
    )
    stderr = io.StringIO()

    status = main(
        ["preflight", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    rejection = _payload(stderr)
    assert rejection["reason"] == "ctp_simnow_preflight_front_policy_required"
    assert rejection["diagnostic"]["provider_preflight_started"] is False


def test_preflight_rejects_static_binding_before_credentials_or_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime"
    registry = _registry(runtime_dir)
    stderr = io.StringIO()
    credential_calls = []

    monkeypatch.setattr(
        credential_resolver,
        "resolve_runtime_credentials",
        lambda *args, **kwargs: credential_calls.append((args, kwargs)),
    )

    status = main(
        ["preflight", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 2
    assert _payload(stderr)["reason"] == "ctp_simnow_preflight_front_policy_required"
    assert credential_calls == []
    assert _FakeClient.instances == []


def test_operator_dispatch_rejects_static_binding_before_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir = tmp_path / "runtime"
    registry = _registry(runtime_dir)
    effective = validate_runtime_config(runtime_dir, registry)
    monkeypatch.setattr(
        readonly_runtime,
        "open_ctp_simnow_readonly_runtime",
        lambda **kwargs: pytest.fail("static binding must fail before provider composition"),
    )

    with pytest.raises(RuntimeConfigError) as rejected:
        simnow_operator.dispatch_registered_ctp_simnow_readonly_preflight(effective, registry)

    assert rejected.value.reason == "ctp_simnow_preflight_front_policy_required"


@pytest.mark.parametrize(
    "registration_changes",
    (
        {"allowed_presets": ("sandbox", "replay")},
        {"allowed_parameter_keys": ("instrument_id",)},
        {"available_capabilities": MANAGED_WRITE_CAPABILITIES},
        {"sandbox_write_policy": "receipt_required"},
        {"approval_receipt_digest": "a" * 64},
        {"runner_module": "examples.013_3_sa_midfreq_simnow.run_runtime"},
        {"capability_modules": ("bt_api_ctp",)},
    ),
)
def test_registry_rejects_route_that_is_not_exact_private_read_only(
    tmp_path: Path, registration_changes: dict
) -> None:
    runtime_dir = tmp_path / "runtime"
    _write_config(runtime_dir)
    registration = _registered_runtime(runtime_dir, **registration_changes)
    with pytest.raises(ValueError, match="exact sandbox-only runtime"):
        RuntimeRegistry(
            (registration,),
            ctp_simnow_readonly_bindings=(_binding(),),
            registry_id="test.ctp.simnow.invalid",
        )


def test_registry_rejects_binding_for_other_runtime(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    _write_config(runtime_dir)
    registration = _registered_runtime(runtime_dir)
    with pytest.raises(ValueError, match="unregistered runtime"):
        RuntimeRegistry(
            (registration,),
            ctp_simnow_readonly_bindings=(_binding(runtime_id="other.runtime"),),
            registry_id="test.ctp.simnow.invalid",
        )


@pytest.mark.parametrize(
    ("environment", "profile"),
    (
        ("simnow_set1", "set1_7x24"),
        ("simnow_set2", "set2_custom"),
        ("simnow_set1", "set2_7x24"),
    ),
)
def test_static_binding_accepts_only_matching_official_simnow_profiles(
    environment: str, profile: str
) -> None:
    with pytest.raises(ValueError, match="invalid code-owned"):
        _binding(environment=environment, sdk_profile=profile)


def test_preflight_rejects_untrusted_registry_before_native_composition(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "runtime"
    _write_config(runtime_dir)
    registration = _registered_runtime(runtime_dir)
    registry = RuntimeRegistry(
        (registration,),
        ctp_simnow_readonly_bindings=(_binding(),),
        registry_id="test.ctp.simnow.untrusted",
        trusted=False,
    )
    stderr = io.StringIO()
    status = main(
        ["preflight", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert status == 2
    assert _payload(stderr)["reason"] == "registry_not_trusted"
