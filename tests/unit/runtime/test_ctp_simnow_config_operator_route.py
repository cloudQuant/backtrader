"""Config-driven SimNow routing is local, read-only, and fail-closed."""

from __future__ import annotations

import hashlib
import builtins
import io
import json
import socket
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import backtrader_runtime.credential_resolver as credential_resolver
import backtrader_runtime.cli as cli
import backtrader_runtime.config as runtime_config
import backtrader_runtime.ctp_simnow_operator as operator
import backtrader_runtime.ctp_simnow_readonly_runtime as readonly_runtime
import backtrader_runtime.ctp_artifact_provenance as artifact_provenance
import backtrader_runtime.ctp_front_pair_probe as front_pair_probe
import backtrader_runtime.inventory as runtime_inventory
from backtrader_runtime.errors import RuntimeConfigError
from backtrader_runtime.registry import (
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    UnavailableModeProfile,
    bootstrap_runtime_config,
    validate_runtime_config,
)


RUNTIME_ID = "iteration41.ctp.simnow.config-route-test"
STRATEGY_ID = "iteration41.ctp.simnow.config_route_test"
PASSWORD = "sentinel-test-password-never-render"
AUTH_CODE = "sentinel-test-auth-never-render"
SET1_GROUP1_TD_FRONT = "tcp://180.168.146.187:10201"
SET1_GROUP1_MD_FRONT = "tcp://180.168.146.187:10211"
SET1_TD_FRONT = "tcp://180.168.146.187:10202"
SET1_MD_FRONT = "tcp://180.168.146.187:10212"
SET2_TD_FRONT = "tcp://180.168.146.187:10130"
SET2_MD_FRONT = "tcp://180.168.146.187:10131"


def _binding():
    return operator.CtpSimNowConfigReadOnlyBinding(runtime_id=RUNTIME_ID)


@pytest.fixture(autouse=True)
def _isolate_private_file_security(monkeypatch):
    # These tests exercise front-routing contracts with synthetic config
    # files. File owner, ACL, mode and hardlink denial have dedicated config
    # and credential-resolver tests; inherited host permissions are not a
    # meaningful input to the routing assertions.
    monkeypatch.setattr(runtime_config, "_require_private_config_security", lambda *a, **k: None)


def _registration(runtime_dir: Path, **changes) -> RegisteredRuntime:
    values = {
        "runtime_dir": runtime_dir,
        "strategy_id": STRATEGY_ID,
        "runtime_id": RUNTIME_ID,
        "allowed_presets": ("sandbox",),
        "allowed_parameter_keys": (),
        "allowed_secrets_refs": ("config_yaml",),
        "available_capabilities": (),
        "offline_managed_execution": False,
        "sandbox_write_policy": "deny",
        "approval_receipt_digest": None,
        "runner_module": None,
        "capability_modules": (),
    }
    values.update(changes)
    return RegisteredRuntime(**values)


def _make_runtime(
    runtime_dir: Path,
    *,
    runtime_id: str = RUNTIME_ID,
    strategy_id: str = STRATEGY_ID,
    binding: bool = True,
    td_front: str = SET1_TD_FRONT,
    md_front: str = SET1_MD_FRONT,
    instrument_id: str = "SA610",
    exchange_id: str = "CZCE",
    hedge_flag: str = "1",
    front_pairs: tuple[tuple[str, str], ...] | None = None,
    ctp_block: str = "ctp_simnow",
    registration_changes: dict | None = None,
) -> RuntimeRegistry:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    if front_pairs is None:
        front_lines = [
            "  md_front: " + md_front,
            "  td_front: " + td_front,
        ]
    else:
        front_lines = ["  front_pairs:"]
        for configured_md, configured_td in front_pairs:
            front_lines.extend(
                (
                    "    - md_front: " + configured_md,
                    "      td_front: " + configured_td,
                )
            )
    (runtime_dir / "config.yaml").write_text(
        "\n".join(
            [
                "config_schema_version: 4",
                "strategy:",
                "  id: " + strategy_id,
                "runtime:",
                "  mode: simulation",
                "  preset: sandbox",
                "parameters: {}",
                "secrets_ref: config_yaml",
                ctp_block + ":",
                *front_lines,
                "  instrument_id: " + instrument_id,
                "  exchange_id: " + exchange_id,
                "  hedge_flag: '" + hedge_flag + "'",
                "  broker_id: '9999'",
                "  user_id: operator-test",
                "  password: " + PASSWORD,
                "  app_id: operator-app",
                "  auth_code: " + AUTH_CODE,
                "",
            ]
        ),
        encoding="utf-8",
    )
    registration = _registration(
        runtime_dir,
        runtime_id=runtime_id,
        strategy_id=strategy_id,
        **(registration_changes or {}),
    )
    bindings = (operator.CtpSimNowConfigReadOnlyBinding(runtime_id=runtime_id),) if binding else ()
    return RuntimeRegistry(
        (registration,),
        ctp_simnow_readonly_bindings=bindings,
        registry_id="test.ctp.simnow.config-route",
    )


def _reject_provider_imports(monkeypatch):
    original_import = builtins.__import__
    provider_roots = {"bt_api_py", "thostmduserapi", "thosttraderapi"}

    def guarded_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in provider_roots:
            raise AssertionError("doctor must not import the CTP SDK")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


def _profile_registration_changes():
    profile = RuntimeProfile(
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
    return {
        "allowed_presets": (),
        "allowed_secrets_refs": ("none",),
        "profiles": (profile,),
        "unavailable_mode_profiles": (
            UnavailableModeProfile(
                mode="live",
                preset="managed_live_direct",
                reason="managed_live_direct_profile_unavailable",
            ),
        ),
    }


def _fake_front_selection(front_pairs, *, index=0):
    pair = front_pairs[index]
    return SimpleNamespace(
        pair=front_pair_probe.CtpConfiguredFrontPair(
            md_front=pair["md_front"],
            td_front=pair["td_front"],
        ),
        config_index=index,
    )


def _install_fake_front_selector(monkeypatch, *, selected_index=0, calls=None):
    def fake_select(front_pairs, **kwargs):
        if calls is not None:
            calls.append((front_pairs, kwargs))
        return _fake_front_selection(front_pairs, index=selected_index)

    monkeypatch.setattr(front_pair_probe, "select_ctp_front_pair", fake_select)


def test_exact_zero_write_profile_dispatches_only_to_config_bound_preflight(tmp_path, monkeypatch):
    registry = _make_runtime(
        tmp_path,
        registration_changes=_profile_registration_changes(),
    )
    effective = validate_runtime_config(tmp_path, registry)
    selection_calls = []
    _install_fake_front_selector(monkeypatch, calls=selection_calls)
    captured = {}
    expected = object()

    def capture_preflight(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(readonly_runtime, "open_ctp_simnow_readonly_runtime", capture_preflight)

    result = operator.dispatch_registered_ctp_simnow_readonly_preflight(effective, registry)

    assert result is expected
    assert len(selection_calls) == 1
    admission = captured["admission_registration"]
    assert (admission.environment, admission.sdk_profile) == ("simnow", "config_front_pair")
    assert (admission.md_front, admission.td_front) == (SET1_MD_FRONT, SET1_TD_FRONT)
    assert captured["credential_scope"].account_access == "sandbox_private_read"
    assert captured["effective"].profile is effective.profile


def test_stale_profile_rejects_before_front_probe_credentials_or_composition(tmp_path, monkeypatch):
    registry = _make_runtime(
        tmp_path,
        registration_changes=_profile_registration_changes(),
    )
    effective = validate_runtime_config(tmp_path, registry)
    registration = registry.require_runtime_dir(tmp_path)
    object.__setattr__(registration.profiles[0], "approval_receipt_digest", "a" * 64)
    front_probes = []
    credential_calls = []
    socket_attempts = []

    def forbidden(*args, **kwargs):
        del args, kwargs
        pytest.fail("stale profile reached a later preflight boundary")

    monkeypatch.setattr(
        operator,
        "_select_configured_front_pair",
        lambda pairs: front_probes.append(pairs),
    )
    monkeypatch.setattr(readonly_runtime, "open_ctp_simnow_readonly_runtime", forbidden)
    monkeypatch.setattr(
        readonly_runtime,
        "resolve_runtime_credentials",
        lambda *a, **k: credential_calls.append((a, k)),
    )
    monkeypatch.setattr(socket, "socket", lambda *a, **k: socket_attempts.append((a, k)))

    with pytest.raises(RuntimeConfigError):
        operator.dispatch_registered_ctp_simnow_readonly_preflight(effective, registry)

    assert front_probes == []
    assert credential_calls == []
    assert socket_attempts == []


def test_doctor_separates_profile_preflight_from_strategy_dispatch(tmp_path):
    registry = _make_runtime(
        tmp_path,
        registration_changes=_profile_registration_changes(),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = cli.main(
        ["doctor", "--strategy-dir", str(tmp_path)],
        registry=registry,
        environ={},
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 0, stderr.getvalue()
    diagnostic = json.loads(stdout.getvalue())["diagnostic"]
    assert diagnostic["profile_dispatch_available"] is False
    assert diagnostic["read_only_preflight_dispatch_available"] is True
    assert diagnostic["next_actions"][0]["action"] == "preflight"

    run_status = cli.main(
        ["run", "--strategy-dir", str(tmp_path)],
        registry=registry,
        environ={},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert run_status == 2


@pytest.mark.parametrize(
    ("td_front", "md_front"),
    (
        (SET1_GROUP1_TD_FRONT, SET1_GROUP1_MD_FRONT),
        (SET1_TD_FRONT, SET1_MD_FRONT),
        (SET2_TD_FRONT, SET2_MD_FRONT),
    ),
)
def test_explicit_front_pair_is_preserved_as_readonly_route(
    tmp_path, monkeypatch, td_front, md_front
):
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(runtime_dir, td_front=td_front, md_front=md_front)
    effective = validate_runtime_config(runtime_dir, registry)
    _install_fake_front_selector(monkeypatch)

    captured = []

    def fake_composition(
        *, effective, registry, admission_registration, credential_scope, selected_config_index=None
    ):
        captured.append(
            (effective, registry, admission_registration, credential_scope, selected_config_index)
        )
        return object()

    monkeypatch.setattr(readonly_runtime, "open_ctp_simnow_readonly_runtime", fake_composition)
    monkeypatch.setattr(
        credential_resolver,
        "resolve_runtime_credentials",
        lambda *args, **kwargs: pytest.fail("operator must not read credentials"),
    )
    monkeypatch.setattr(
        socket, "socket", lambda *args, **kwargs: pytest.fail("operator must not open sockets")
    )

    operator.dispatch_registered_ctp_simnow_readonly_preflight(effective, registry)

    assert len(captured) == 1
    _, _, admission, scope, selected_config_index = captured[0]
    assert selected_config_index == 0
    assert admission.sdk_profile == "config_front_pair"
    assert admission.environment == "simnow"
    assert admission.allowed_secrets_ref == "config_yaml"
    assert admission.instrument_id == "SA610"
    assert admission.exchange_id == "CZCE"
    assert admission.hedge_flag == "1"
    assert admission.td_front == td_front
    assert admission.md_front == md_front
    assert scope.provider_environment == "simnow"
    assert scope.account_fingerprint_sha256 == hashlib.sha256(b"9999:operator-test").hexdigest()
    assert effective.allows_external_writes is False
    assert effective.required_capabilities == ()
    rendered = repr(admission) + repr(scope) + repr(effective.config)
    assert PASSWORD not in rendered
    assert AUTH_CODE not in rendered


@pytest.mark.parametrize(
    ("td_front", "md_front"),
    (
        ("tcp://127.0.0.1:10001", "tcp://127.0.0.1:10002"),
        (SET1_TD_FRONT, SET2_MD_FRONT),
    ),
)
def test_custom_or_mixed_configured_pair_is_preserved_without_profile_lookup(
    tmp_path, monkeypatch, td_front, md_front
):
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(runtime_dir, td_front=td_front, md_front=md_front)
    effective = validate_runtime_config(runtime_dir, registry)
    _install_fake_front_selector(monkeypatch)
    captured = []
    monkeypatch.setattr(
        readonly_runtime,
        "open_ctp_simnow_readonly_runtime",
        lambda **kwargs: captured.append(kwargs),
    )
    monkeypatch.setattr(
        credential_resolver,
        "resolve_runtime_credentials",
        lambda *args, **kwargs: pytest.fail("operator must not read credentials"),
    )
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *args, **kwargs: pytest.fail("front selection must use fake probe in this test"),
    )

    operator.dispatch_registered_ctp_simnow_readonly_preflight(effective, registry)
    admission = captured[0]["admission_registration"]
    assert admission.td_front == td_front
    assert admission.md_front == md_front
    assert admission.environment == "simnow"
    assert admission.sdk_profile == "config_front_pair"


def test_configured_query_scope_is_used_without_a_code_selected_contract(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(
        runtime_dir,
        instrument_id="rb2610",
        exchange_id="SHFE",
        hedge_flag="2",
    )
    effective = validate_runtime_config(runtime_dir, registry)
    _install_fake_front_selector(monkeypatch)

    captured = []
    monkeypatch.setattr(
        readonly_runtime,
        "open_ctp_simnow_readonly_runtime",
        lambda **kwargs: captured.append(kwargs) or object(),
    )
    operator.dispatch_registered_ctp_simnow_readonly_preflight(effective, registry)

    assert len(captured) == 1
    admission = captured[0]["admission_registration"]
    assert (admission.instrument_id, admission.exchange_id, admission.hedge_flag) == (
        "rb2610",
        "SHFE",
        "2",
    )
    assert admission.td_front == SET1_TD_FRONT
    assert admission.md_front == SET1_MD_FRONT


def test_cli_preflight_uses_registered_config_route_without_time_source(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(runtime_dir, td_front=SET2_TD_FRONT, md_front=SET2_MD_FRONT)
    observed = SimpleNamespace(
        as_public_dict=lambda: {
            "execution_authorized": False,
            "external_writes_authorized": False,
            "external_write_requests": 0,
        }
    )
    dispatched = []
    monkeypatch.setattr(
        cli,
        "dispatch_registered_ctp_simnow_readonly_preflight",
        lambda effective, selected_registry: (
            dispatched.append((effective, selected_registry)) or observed
        ),
    )
    output, errors = io.StringIO(), io.StringIO()

    exit_code = cli.main(
        ["preflight", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 0, errors.getvalue()
    assert len(dispatched) == 1
    assert dispatched[0][1] is registry
    payload = json.loads(output.getvalue())
    assert payload["status"] == "read_only_observation"
    assert payload["result"]["execution_authorized"] is False
    assert payload["result"]["external_write_requests"] == 0


def test_config_rejects_a_set_selector_even_when_explicit_fronts_are_present(tmp_path):
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(runtime_dir)
    config_path = runtime_dir / "config.yaml"
    with config_path.open("a", encoding="utf-8") as stream:
        stream.write("  set: set2\n")

    with pytest.raises(RuntimeConfigError) as rejected:
        validate_runtime_config(runtime_dir, registry)
    assert rejected.value.reason == "field_not_allowed"


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (("session_ttl_seconds", 120.0),),
)
def test_registered_binding_mutation_rejects_before_composition(
    tmp_path, monkeypatch, field_name, replacement
):
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(runtime_dir)
    effective = validate_runtime_config(runtime_dir, registry)
    binding = registry.ctp_simnow_readonly_bindings[0]
    object.__setattr__(binding, field_name, replacement)
    monkeypatch.setattr(
        readonly_runtime,
        "open_ctp_simnow_readonly_runtime",
        lambda **kwargs: pytest.fail("mutated registered binding must not compose runtime"),
    )

    with pytest.raises(RuntimeConfigError) as rejected:
        operator.dispatch_registered_ctp_simnow_readonly_preflight(effective, registry)
    assert rejected.value.reason == "ctp_simnow_preflight_binding_invalid"


def test_explicit_set2_front_pair_stays_selected_and_provider_failure_stays_closed(
    tmp_path, monkeypatch
):
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(runtime_dir, td_front=SET2_TD_FRONT, md_front=SET2_MD_FRONT)
    effective = validate_runtime_config(runtime_dir, registry)
    _install_fake_front_selector(monkeypatch)
    seen_profiles = []

    def unavailable_provider(*, admission_registration, **_kwargs):
        seen_profiles.append(admission_registration.sdk_profile)
        raise readonly_runtime.CtpSimNowReadOnlyRuntimeError(
            "provider_unavailable", "synthetic provider unavailable"
        )

    monkeypatch.setattr(readonly_runtime, "open_ctp_simnow_readonly_runtime", unavailable_provider)

    with pytest.raises(RuntimeConfigError) as rejected:
        operator.dispatch_registered_ctp_simnow_readonly_preflight(effective, registry)
    assert seen_profiles == ["config_front_pair"]
    assert rejected.value.reason == "ctp_simnow_preflight_provider_unavailable"


def test_unregistered_route_rejects_before_composition_or_credentials(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(runtime_dir, binding=False)
    effective = validate_runtime_config(runtime_dir, registry)
    monkeypatch.setattr(
        readonly_runtime,
        "open_ctp_simnow_readonly_runtime",
        lambda **kwargs: pytest.fail("unregistered route must not compose runtime"),
    )

    with pytest.raises(RuntimeConfigError) as rejected:
        operator.dispatch_registered_ctp_simnow_readonly_preflight(effective, registry)
    assert rejected.value.reason == "ctp_simnow_preflight_route_unregistered"


def test_preflight_rejects_empty_sdk_pin_before_credentials_or_network(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_provenance, "CTP_SDK_ARTIFACT_PINS", {})
    default_registry = runtime_inventory.iteration41_runtime_registry()
    default_registration = runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION
    runtime_dir = tmp_path / "runtime-ctp-private"
    runtime_dir.mkdir()
    (runtime_dir / "config.yaml").write_text(
        "\n".join(
            (
                "config_schema_version: 4",
                "strategy:",
                "  id: " + default_registration.strategy_id,
                "runtime:",
                "  mode: simulation",
                "  preset: sandbox",
                "parameters: {}",
                "secrets_ref: config_yaml",
                "ctp_simnow:",
                "  md_front: tcp://180.168.146.187:10212",
                "  td_front: tcp://180.168.146.187:10202",
                "  instrument_id: SA610",
                "  exchange_id: CZCE",
                "  hedge_flag: '1'",
                "  broker_id: '9999'",
                "  user_id: synthetic-user",
                "  password: synthetic-password-never-resolved",
                "  app_id: synthetic-app",
                "  auth_code: synthetic-auth-never-resolved",
                "",
            )
        ),
        encoding="utf-8",
    )
    synthetic_registration = replace(default_registration, runtime_dir=runtime_dir)
    registry = RuntimeRegistry(
        tuple(
            synthetic_registration if entry is default_registration else entry
            for entry in default_registry.registrations
        ),
        runtime_sets=default_registry.runtime_sets,
        ctp_simnow_readonly_bindings=default_registry.ctp_simnow_readonly_bindings,
        registry_id=default_registry.registry_id,
    )
    effective = validate_runtime_config(runtime_dir, registry)
    _install_fake_front_selector(monkeypatch)

    credential_calls = []
    socket_attempts = []
    monkeypatch.setattr(
        readonly_runtime,
        "trusted_installed_capability_import_context",
        lambda _modules: nullcontext(),
    )
    monkeypatch.setattr(
        readonly_runtime,
        "resolve_runtime_credentials",
        lambda *args, **kwargs: credential_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *args, **kwargs: socket_attempts.append((args, kwargs)),
    )

    with pytest.raises(RuntimeConfigError) as rejected:
        operator.dispatch_registered_ctp_simnow_readonly_preflight(effective, registry)

    assert rejected.value.reason == "ctp_simnow_preflight_capability_provenance_rejected"
    assert credential_calls == []
    assert socket_attempts == []

    output, errors = io.StringIO(), io.StringIO()
    status = cli.main(
        ["run", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=output,
        stderr=errors,
    )
    assert status == 2
    rejection = json.loads(errors.getvalue())
    assert rejection["reason"] == "profile_dispatch_unavailable"
    next_action = rejection["diagnostic"]["next_actions"][0]
    assert next_action["action"] == "preflight"
    assert next_action["command"] == [
        "bt-runtime",
        "preflight",
        "--strategy-dir",
        str(runtime_dir),
    ]
    assert "has no run entrypoint" in next_action["note"]
    assert "read-only" in next_action["note"]
    assert output.getvalue() == ""
    assert credential_calls == []
    assert socket_attempts == []


def test_private_config_mutation_rejects_before_composition(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(runtime_dir)
    effective = validate_runtime_config(runtime_dir, registry)
    object.__setattr__(effective.config.ctp_simnow, "td_front", SET2_TD_FRONT)
    monkeypatch.setattr(
        readonly_runtime,
        "open_ctp_simnow_readonly_runtime",
        lambda **kwargs: pytest.fail("tampered config must not compose runtime"),
    )
    with pytest.raises(RuntimeConfigError) as rejected:
        operator.dispatch_registered_ctp_simnow_readonly_preflight(effective, registry)
    assert rejected.value.reason == "config_provenance_invalid"


def test_bootstrap_refuses_to_write_incomplete_private_config(tmp_path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registration = _registration(runtime_dir)
    registry = RuntimeRegistry(
        (registration,),
        ctp_simnow_readonly_bindings=(_binding(),),
    )
    with pytest.raises(RuntimeConfigError) as rejected:
        bootstrap_runtime_config(runtime_dir, registry, "sandbox")
    assert rejected.value.reason == "ctp_simnow_private_config_required"
    assert not (runtime_dir / "config.yaml").exists()


def test_missing_private_config_guides_to_shared_ctp_setup_instead_of_bootstrap(tmp_path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    registry = RuntimeRegistry(
        (_registration(runtime_dir),),
        ctp_simnow_readonly_bindings=(_binding(),),
    )
    output, errors = io.StringIO(), io.StringIO()

    exit_code = cli.main(
        ["doctor", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=output,
        stderr=errors,
    )

    assert exit_code != 0
    diagnostic = json.loads(errors.getvalue())["diagnostic"]
    actions = diagnostic["next_actions"]
    assert len(actions) == 1
    assert actions[0]["action"] == "prepare_ctp_private_config"
    assert "Bootstrap cannot" in actions[0]["note"]
    assert "canonical top-level ctp mapping" in actions[0]["note"]
    assert "production route" in actions[0]["note"]
    assert "one or two explicit owner-only local sources" in actions[0]["note"]
    assert "direct md_front/td_front pair or an explicit front_pairs list" in actions[0]["note"]
    assert all(command[1] == "prepare-ctp-config" for command in actions[0]["command_examples"])
    assert any(
        "--source-collector-yaml" in command and "--source-yaml" in command
        for command in actions[0]["command_examples"]
    )
    assert "bootstrap" not in json.dumps(actions)


def test_doctor_shows_configured_simnow_fronts_without_secrets(tmp_path):
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(runtime_dir)
    output, errors = io.StringIO(), io.StringIO()

    exit_code = cli.main(
        ["doctor", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 0, errors.getvalue()
    diagnostic = json.loads(output.getvalue())["diagnostic"]
    assert diagnostic["offline"] is True
    assert diagnostic["provider_preflight_started"] is False
    assert diagnostic["configured_simnow_fronts"] == {
        "md_front": SET1_MD_FRONT,
        "td_front": SET1_TD_FRONT,
    }
    assert diagnostic["next_actions"][0]["action"] == "preflight"
    assert diagnostic["next_actions"][0]["note"] == (
        "probes only configured MD/TD pairs, then opens bounded TD account "
        "and MD market-data read-only checks; grants no write authority"
    )
    assert PASSWORD not in output.getvalue()
    assert AUTH_CODE not in output.getvalue()
    assert "operator-test" not in output.getvalue()


def test_013_3_doctor_adds_redacted_operator_actions_for_sandbox_without_io(tmp_path, monkeypatch):
    runtime_id = runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID
    strategy_id = runtime_inventory.ITERATION41_013_3_STRATEGY_ID
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(
        runtime_dir,
        runtime_id=runtime_id,
        strategy_id=strategy_id,
        ctp_block="ctp",
        registration_changes=_profile_registration_changes(),
    )
    _reject_provider_imports(monkeypatch)
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("doctor must stay offline"))
    monkeypatch.setattr(
        credential_resolver,
        "resolve_runtime_credentials",
        lambda *a, **k: pytest.fail("doctor must not resolve credentials"),
    )
    monkeypatch.setattr(
        cli,
        "dispatch_registered_ctp_simnow_readonly_preflight",
        lambda *a, **k: pytest.fail("doctor must not start preflight"),
    )
    monkeypatch.setattr(
        cli,
        "dispatch_registered_ctp_front_check",
        lambda *a, **k: pytest.fail("doctor must not probe fronts"),
    )
    monkeypatch.setattr(
        cli,
        "dispatch_registered_runtime",
        lambda *a, **k: pytest.fail("doctor must not dispatch run"),
    )
    output, errors = io.StringIO(), io.StringIO()

    status = cli.main(
        ["doctor", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=output,
        stderr=errors,
    )

    assert status == 0, errors.getvalue()
    diagnostic = json.loads(output.getvalue())["diagnostic"]
    actions = diagnostic["operator_actions"]
    assert actions["mode"] == "simulation"
    assert actions["preset"] == "sandbox"
    assert actions["doctor"] == {"status": "offline"}
    assert actions["check-ctp-fronts"] == {
        "status": "tcp_only",
        "command": [
            "bt-runtime",
            "check-ctp-fronts",
            "--strategy-dir",
            str(runtime_dir),
        ],
        "note": "credential-free TCP reachability only; it does not test login or authorize trading",
    }
    assert actions["preflight"] == {
        "status": "disabled",
        "reason": "ctp_simnow_preflight_supervisor_required",
    }
    assert actions["run"] == {
        "status": "unavailable",
        "reason": "profile_dispatch_unavailable",
    }
    assert actions["live"]["status"] == "unavailable"
    assert actions["live"]["reason"] == "managed_live_direct_profile_unavailable"
    assert actions["live"]["authorization"] == "not_granted"
    rendered_actions = json.dumps(actions)
    for private_value in (
        PASSWORD,
        AUTH_CODE,
        "operator-test",
        SET1_MD_FRONT,
        SET1_TD_FRONT,
    ):
        assert private_value not in rendered_actions
    for private_value in (PASSWORD, AUTH_CODE, "operator-test"):
        assert private_value not in output.getvalue()


def test_013_3_doctor_labels_live_config_as_request_not_authorization_without_io(
    tmp_path, monkeypatch
):
    runtime_id = runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID
    strategy_id = runtime_inventory.ITERATION41_013_3_STRATEGY_ID
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(
        runtime_dir,
        runtime_id=runtime_id,
        strategy_id=strategy_id,
        ctp_block="ctp",
        registration_changes=_profile_registration_changes(),
    )
    config_path = runtime_dir / "config.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        .replace("mode: simulation", "mode: live")
        .replace("preset: sandbox", "preset: managed_live_direct"),
        encoding="utf-8",
    )
    _reject_provider_imports(monkeypatch)
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("doctor must stay offline"))
    monkeypatch.setattr(
        credential_resolver,
        "resolve_runtime_credentials",
        lambda *a, **k: pytest.fail("doctor must not resolve credentials"),
    )
    monkeypatch.setattr(
        cli,
        "dispatch_registered_ctp_simnow_readonly_preflight",
        lambda *a, **k: pytest.fail("doctor must not start preflight"),
    )
    monkeypatch.setattr(
        cli,
        "dispatch_registered_ctp_front_check",
        lambda *a, **k: pytest.fail("doctor must not probe fronts"),
    )
    monkeypatch.setattr(
        cli,
        "dispatch_registered_runtime",
        lambda *a, **k: pytest.fail("doctor must not dispatch run"),
    )
    output, errors = io.StringIO(), io.StringIO()

    status = cli.main(
        ["doctor", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=output,
        stderr=errors,
    )

    assert status == 2
    assert output.getvalue() == ""
    payload = json.loads(errors.getvalue())
    assert payload["reason"] == "managed_live_direct_profile_unavailable"
    diagnostic = payload["diagnostic"]
    actions = diagnostic["operator_actions"]
    assert diagnostic["offline"] is True
    assert diagnostic["provider_preflight_started"] is False
    assert diagnostic["profile_dispatch_available"] is False
    existing_action = diagnostic["next_actions"][0]
    assert existing_action["action"] == "review_live_enablement"
    assert "same protected config.yaml" in existing_action["note"]
    assert "shared CTP execution runner" in existing_action["note"]
    assert "production-specific admission" in existing_action["note"]
    assert "editing mode or parameters alone does not enable trading" in existing_action["note"]
    assert actions["mode"] == "live"
    assert actions["preset"] == "managed_live_direct"
    assert actions["check-ctp-fronts"]["status"] == "unavailable"
    assert "command" not in actions["check-ctp-fronts"]
    assert actions["preflight"] == {
        "status": "disabled",
        "reason": "managed_live_direct_profile_unavailable",
    }
    assert actions["run"] == {
        "status": "unavailable",
        "reason": "managed_live_direct_profile_unavailable",
    }
    assert actions["live"]["status"] == "unavailable"
    assert actions["live"]["reason"] == "managed_live_direct_profile_unavailable"
    assert actions["live"]["requested"] is True
    assert actions["live"]["authorization"] == "not_granted"
    assert "requests live/managed_live_direct" in actions["live"]["note"]
    assert "does not authorize production trading" in actions["live"]["note"]
    rendered_actions = json.dumps(actions)
    for private_value in (
        PASSWORD,
        AUTH_CODE,
        "operator-test",
        SET1_MD_FRONT,
        SET1_TD_FRONT,
    ):
        assert private_value not in rendered_actions
    for private_value in (PASSWORD, AUTH_CODE, "operator-test"):
        assert private_value not in errors.getvalue()


def test_doctor_shows_canonical_ctp_front_pairs_without_secrets_or_probe(tmp_path, monkeypatch):
    configured_pairs = (
        ("tcp://127.0.0.1:11001", "tcp://127.0.0.1:12001"),
        ("tcp://127.0.0.1:11002", "tcp://127.0.0.1:12002"),
    )
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(runtime_dir, front_pairs=configured_pairs, ctp_block="ctp")
    monkeypatch.setattr(
        front_pair_probe,
        "select_ctp_front_pair",
        lambda *args, **kwargs: pytest.fail("doctor must not probe configured fronts"),
    )
    output, errors = io.StringIO(), io.StringIO()

    exit_code = cli.main(
        ["doctor", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 0, errors.getvalue()
    diagnostic = json.loads(output.getvalue())["diagnostic"]
    assert diagnostic["offline"] is True
    assert diagnostic["configured_simnow_fronts"] == {
        "front_pairs": [
            {"md_front": md_front, "td_front": td_front} for md_front, td_front in configured_pairs
        ]
    }
    assert PASSWORD not in output.getvalue()
    assert AUTH_CODE not in output.getvalue()
    assert "operator-test" not in output.getvalue()


def test_doctor_accepts_any_explicit_configured_pair_without_network(tmp_path):
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(runtime_dir, td_front=SET1_TD_FRONT, md_front=SET2_MD_FRONT)
    output, errors = io.StringIO(), io.StringIO()

    exit_code = cli.main(
        ["doctor", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 0, errors.getvalue()
    diagnostic = json.loads(output.getvalue())["diagnostic"]
    assert diagnostic["offline"] is True
    assert diagnostic["configured_simnow_fronts"] == {
        "md_front": SET2_MD_FRONT,
        "td_front": SET1_TD_FRONT,
    }
    assert diagnostic["next_actions"][0]["action"] == "preflight"
    assert PASSWORD not in output.getvalue()
    assert AUTH_CODE not in output.getvalue()
    assert "operator-test" not in output.getvalue()


def test_preflight_front_rejection_is_nonzero_and_stays_before_provider_io(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(runtime_dir, td_front=SET1_TD_FRONT, md_front=SET2_MD_FRONT)

    def rejected_probe(_pairs, **_kwargs):
        raise front_pair_probe.CtpFrontPairProbeError("synthetic_unreachable")

    monkeypatch.setattr(front_pair_probe, "select_ctp_front_pair", rejected_probe)

    def forbidden_provider_access(*_args, **_kwargs):
        raise AssertionError("front rejection must precede credentials and provider setup")

    monkeypatch.setattr(
        credential_resolver, "resolve_runtime_credentials", forbidden_provider_access
    )
    monkeypatch.setattr(
        readonly_runtime,
        "open_ctp_simnow_readonly_runtime",
        forbidden_provider_access,
    )
    output, errors = io.StringIO(), io.StringIO()

    exit_code = cli.main(
        ["preflight", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 2
    assert output.getvalue() == ""
    rejection = json.loads(errors.getvalue())
    assert rejection["error_code"] == "PRESET_POLICY_VIOLATION"
    assert rejection["reason"] == "ctp_simnow_preflight_front_probe_rejected"
    assert rejection["diagnostic"]["offline"] is False
    assert rejection["diagnostic"]["provider_preflight_started"] is True
    assert rejection["diagnostic"]["provider_io_may_have_started"] is True
    assert "SDK" in rejection["message"]
    assert "account queries were not started" in rejection["message"]
    assert PASSWORD not in errors.getvalue()
    assert AUTH_CODE not in errors.getvalue()


def test_multi_pair_preflight_selects_lowest_latency_candidate_and_binds_exact_pair(
    tmp_path, monkeypatch
):
    configured_pairs = (
        ("tcp://127.0.0.1:11001", "tcp://127.0.0.1:12001"),
        ("tcp://127.0.0.1:11002", "tcp://127.0.0.1:12002"),
    )
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(runtime_dir, front_pairs=configured_pairs)
    effective = validate_runtime_config(runtime_dir, registry)
    captured = []

    def fake_selector(front_pairs, *, timeout_seconds, max_pairs, repeated_samples):
        captured.append((front_pairs, timeout_seconds, max_pairs, repeated_samples))
        latency_by_pair = {
            (configured_pairs[0][0], configured_pairs[0][1]): 87.0,
            (configured_pairs[1][0], configured_pairs[1][1]): 12.0,
        }
        selected = min(
            front_pairs,
            key=lambda pair: latency_by_pair[(pair["md_front"], pair["td_front"])],
        )
        selected_index = next(
            index
            for index, pair in enumerate(front_pairs)
            if pair["md_front"] == selected["md_front"] and pair["td_front"] == selected["td_front"]
        )
        return SimpleNamespace(
            pair=front_pair_probe.CtpConfiguredFrontPair(
                md_front=selected["md_front"],
                td_front=selected["td_front"],
            ),
            config_index=selected_index,
        )

    monkeypatch.setattr(front_pair_probe, "select_ctp_front_pair", fake_selector)
    composition_calls = []
    monkeypatch.setattr(
        readonly_runtime,
        "open_ctp_simnow_readonly_runtime",
        lambda **kwargs: composition_calls.append(kwargs) or object(),
    )
    monkeypatch.setattr(
        socket, "socket", lambda *args, **kwargs: pytest.fail("fake selector must avoid sockets")
    )

    operator.dispatch_registered_ctp_simnow_readonly_preflight(effective, registry)

    assert len(captured) == 1
    pairs_seen, timeout_seconds, max_pairs, repeated_samples = captured[0]
    assert [(item["md_front"], item["td_front"]) for item in pairs_seen] == list(configured_pairs)
    assert (timeout_seconds, max_pairs, repeated_samples) == (3.0, 8, 3)
    admission = composition_calls[0]["admission_registration"]
    assert (admission.md_front, admission.td_front) == configured_pairs[1]
    assert admission.sdk_profile == "config_front_pair"
    assert admission.environment == "simnow"
    assert composition_calls[0]["credential_scope"].provider_environment == "simnow"
    assert composition_calls[0]["selected_config_index"] == 1


def test_multi_pair_doctor_is_offline_and_reports_all_configured_candidates(tmp_path, monkeypatch):
    configured_pairs = (
        ("tcp://127.0.0.1:11001", "tcp://127.0.0.1:12001"),
        ("tcp://127.0.0.1:11002", "tcp://127.0.0.1:12002"),
    )
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(runtime_dir, front_pairs=configured_pairs)
    monkeypatch.setattr(
        front_pair_probe,
        "select_ctp_front_pair",
        lambda *args, **kwargs: pytest.fail("doctor must not probe configured fronts"),
    )
    monkeypatch.setattr(
        socket, "socket", lambda *args, **kwargs: pytest.fail("doctor must remain offline")
    )
    output, errors = io.StringIO(), io.StringIO()

    exit_code = cli.main(
        ["doctor", "--strategy-dir", str(runtime_dir)],
        registry=registry,
        environ={},
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 0, errors.getvalue()
    diagnostic = json.loads(output.getvalue())["diagnostic"]
    assert diagnostic["offline"] is True
    assert diagnostic["provider_preflight_started"] is False
    assert diagnostic["configured_simnow_fronts"] == {
        "front_pairs": [
            {"md_front": md_front, "td_front": td_front} for md_front, td_front in configured_pairs
        ]
    }


@pytest.mark.parametrize("ttl", (0, -1, 301, float("inf"), True))
def test_config_binding_requires_bounded_session_ttl(ttl):
    with pytest.raises(ValueError, match="invalid code-owned"):
        operator.CtpSimNowConfigReadOnlyBinding(
            runtime_id=RUNTIME_ID,
            session_ttl_seconds=ttl,
        )


def test_registry_revalidates_previously_mutated_binding(tmp_path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    binding = _binding()
    object.__setattr__(binding, "session_ttl_seconds", 0)
    with pytest.raises(ValueError, match="invalid code-owned"):
        RuntimeRegistry((_registration(runtime_dir),), ctp_simnow_readonly_bindings=(binding,))


def test_unsupported_configured_exchange_rejects_before_composition(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    registry = _make_runtime(runtime_dir, exchange_id="UNKNOWN")
    effective = validate_runtime_config(runtime_dir, registry)
    monkeypatch.setattr(
        readonly_runtime,
        "open_ctp_simnow_readonly_runtime",
        lambda **kwargs: pytest.fail("unsupported query scope must reject before composition"),
    )

    with pytest.raises(RuntimeConfigError) as rejected:
        operator.dispatch_registered_ctp_simnow_readonly_preflight(effective, registry)
    assert rejected.value.reason == "ctp_simnow_preflight_query_scope_rejected"


@pytest.mark.parametrize(
    "change",
    (
        {"allowed_presets": ("sandbox", "replay")},
        {"allowed_secrets_refs": ("config_yaml", "runtime_secrets")},
        {"available_capabilities": ("ctp_order_insert",)},
        {"sandbox_write_policy": "receipt_required"},
        {"approval_receipt_digest": "a" * 64},
        {"runner_module": "backtrader_runtime.fake_runner"},
    ),
)
def test_registry_rejects_config_route_with_wider_authority(tmp_path, change):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    with pytest.raises(ValueError, match="exact sandbox-only runtime"):
        RuntimeRegistry(
            (_registration(runtime_dir, **change),),
            ctp_simnow_readonly_bindings=(_binding(),),
        )
