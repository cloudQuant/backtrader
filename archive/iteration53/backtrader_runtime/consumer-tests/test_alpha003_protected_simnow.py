"""Public synthetic config tests: no real config, SDK client, or provider use."""

import importlib.util
import json
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from types import ModuleType

import pytest

import backtrader_runtime.config as config_module
import backtrader_runtime.credential_resolver as credentials_module


@pytest.fixture
def bridge():
    path = (
        Path(__file__).parents[2]
        / "examples/unified/028_alpha003_simnow_minute/protected_simnow.py"
    )
    spec = importlib.util.spec_from_file_location("test_alpha003_protected_bridge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def synthetic(bridge, monkeypatch, tmp_path):
    example = tmp_path / "examples/unified/028_alpha003_simnow_minute"
    example.mkdir(parents=True)
    runtime = example.parent / "013_3_sa_midfreq_simnow/runtime-ctp-private"
    runtime.mkdir(parents=True)
    monkeypatch.setattr(bridge, "__file__", str(example / "protected_simnow.py"))
    registration, registry = bridge._registered_runtime()
    # Every value here is synthetic. The file-security leaves alone are fake;
    # parsing, registration, effective/admission/credential seals remain real.
    private = {
        "front_pairs": [
            {"td_front": "tcp://127.0.0.1:10001", "md_front": "tcp://127.0.0.1:10002"},
            {"td_front": "tcp://127.0.0.1:10003", "md_front": "tcp://127.0.0.1:10004"},
        ],
        "instrument_id": "TEST2611",
        "exchange_id": "DCE",
        "hedge_flag": "1",
        "broker_id": "9999",
        "user_id": "synthetic-test",
        "password": "synthetic-password",
        "app_id": "synthetic-app",
        "auth_code": "synthetic-auth",
    }
    document = {
        "config_schema_version": 4,
        "strategy": {"id": registration.strategy_id},
        "runtime": {"mode": "simulation", "preset": "sandbox"},
        "parameters": {},
        "secrets_ref": "config_yaml",
        "ctp_simnow": private,
    }
    (runtime / "config.yaml").write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(config_module, "_require_private_config_security", lambda *a, **k: None)
    monkeypatch.setattr(credentials_module, "_require_windows_private_config_acl", lambda *a: None)
    monkeypatch.setattr(credentials_module, "_require_posix_private_config_acl", lambda *a: None)
    monkeypatch.setattr(bridge, "_registered_runtime", lambda: (registration, registry))
    events = []

    @contextmanager
    def fence(names):
        assert names == ("bt_api_base", "bt_api_ctp")
        events.append("fence_enter")
        try:
            yield
        finally:
            events.append("fence_exit")

    def artifacts(names, *, pins):
        assert names == ("bt_api_base", "bt_api_ctp")
        assert pins is bridge._SDK_PINS
        events.append("artifacts")

    def profile(td, md):
        assert (td, md) == (
            private["front_pairs"][1]["td_front"],
            private["front_pairs"][1]["md_front"],
        )
        events.append("profile")
        return "set2_7x24"

    real_resolve = bridge.resolve_runtime_credentials
    captured = {}

    def resolve(effective, registry, scope):
        events.append("credentials")
        captured["effective"] = effective
        return real_resolve(effective, registry, scope)

    monkeypatch.setattr(bridge, "trusted_installed_capability_import_context", fence)
    monkeypatch.setattr(bridge, "_verify_pinned_sdk_distributions", artifacts)
    monkeypatch.setattr(bridge, "_official_profile", profile)
    monkeypatch.setattr(bridge, "resolve_runtime_credentials", resolve)
    return events, captured, private


def test_handoff_uses_real_seals_and_closes_private_mapping(bridge, synthetic):
    events, _, private = synthetic
    with bridge.protected_simnow_store_config(selected_config_index=1) as handoff:
        mapping = handoff.for_runner()
        assert events == ["fence_enter", "artifacts", "profile", "credentials"]
        assert repr(handoff) == "ProtectedSimNowConfig(<redacted>)"
        assert repr(mapping) == "PrivateSimNowMapping(<redacted>)"
        assert repr(mapping["config"]) == "PrivateSimNowMapping(<redacted>)"
        assert mapping["api_kwargs"] == {}
        assert mapping["config"]["td_address"] == private["front_pairs"][1]["td_front"]
        assert mapping["config"]["password"] == private["password"]
        assert set(mapping["config"]) == set(bridge.CTP_AUTHENTICATION_CREDENTIAL_KEYS) | {
            "td_address",
            "md_address",
            "ctp_env_profile",
            "environment",
        }
        with pytest.raises(TypeError):
            mapping["config"]["password"] = "changed"
    assert events[-1] == "fence_exit"
    assert mapping["config"] == {}
    with pytest.raises(bridge.ProtectedSimNowConfigError, match="CONFIG_CONTEXT_CLOSED"):
        handoff.for_runner()


@pytest.mark.parametrize("gate", ["_verify_pinned_sdk_distributions", "_official_profile"])
def test_precredential_rejection_has_fixed_reason(bridge, synthetic, monkeypatch, gate):
    events, _, _ = synthetic

    def reject(*a, **k):
        raise RuntimeError("synthetic-password-must-not-escape")

    monkeypatch.setattr(bridge, gate, reject)
    reason = (
        "SDK_ARTIFACT_REJECTED" if gate.startswith("_verify") else "OFFICIAL_SIMNOW_PAIR_REQUIRED"
    )
    with pytest.raises(bridge.ProtectedSimNowConfigError, match=f"^{reason}$"):
        with bridge.protected_simnow_store_config(selected_config_index=1):
            pytest.fail("yielded rejected config")
    assert "credentials" not in events
    assert events[-1] == "fence_exit"


@pytest.mark.parametrize("index", [True, -1, 8, "0", None])
def test_bad_index_rejected_before_config_io(bridge, monkeypatch, index):
    monkeypatch.setattr(bridge, "_registered_runtime", lambda: pytest.fail("config I/O reached"))
    with pytest.raises(bridge.ProtectedSimNowConfigError, match="^CONFIG_INDEX_INVALID$"):
        with bridge.protected_simnow_store_config(selected_config_index=index):
            pytest.fail("yielded invalid index")


def test_unconfigured_index_never_reaches_artifact_or_credentials(bridge, synthetic):
    events, _, _ = synthetic
    with pytest.raises(bridge.ProtectedSimNowConfigError, match="^CONFIG_INDEX_INVALID$"):
        with bridge.protected_simnow_store_config(selected_config_index=2):
            pytest.fail("yielded unconfigured index")
    assert events == []


def test_each_handoff_rechecks_real_config_seal(bridge, synthetic):
    _, captured, _ = synthetic
    with bridge.protected_simnow_store_config(selected_config_index=1) as handoff:
        handoff.for_runner()
        object.__setattr__(captured["effective"].config.ctp_simnow, "password", "tampered")
        with pytest.raises(Exception):
            handoff.for_runner()


def test_consumer_exception_preserved_and_context_closed(bridge, synthetic):
    events, _, _ = synthetic
    error = ValueError("synthetic consumer error")
    with pytest.raises(ValueError) as caught:
        with bridge.protected_simnow_store_config(selected_config_index=1) as handoff:
            mapping = handoff.for_runner()
            raise error
    assert caught.value is error
    assert mapping["config"] == {}
    assert events[-1] == "fence_exit"


def test_relocated_registration_preserves_existing_readonly_policy(bridge, tmp_path, monkeypatch):
    example = tmp_path / "examples/unified/028_alpha003_simnow_minute"
    example.mkdir(parents=True)
    runtime = example.parent / "013_3_sa_midfreq_simnow/runtime-ctp-private"
    runtime.mkdir(parents=True)
    monkeypatch.setattr(bridge, "__file__", str(example / "protected_simnow.py"))
    registration, registry = bridge._registered_runtime()
    original = bridge.ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION
    for field in fields(original):
        if field.name not in {"runtime_dir", "directory_identity", "runtime_dir_lookup_key"}:
            assert getattr(registration, field.name) == getattr(original, field.name)
    assert registration.runtime_dir == runtime.resolve()
    assert (
        registry.require_ctp_simnow_readonly_binding(registration.runtime_id)
        is bridge.ITERATION41_013_3_CTP_PRIVATE_READONLY_BINDING
    )


def test_official_pair_check_uses_both_sdk_addresses(bridge, monkeypatch):
    import sys

    module = ModuleType("bt_api_ctp.ctp_env_selector")
    calls = []
    module.official_simnow_profile_for_td_front = lambda td: "set2_7x24"
    module.verify_official_simnow_profile = (
        lambda td, md, profile: calls.append((td, md, profile)) or False
    )
    monkeypatch.setitem(sys.modules, "bt_api_ctp.ctp_env_selector", module)
    with pytest.raises(bridge.ProtectedSimNowConfigError, match="OFFICIAL_SIMNOW_PAIR_REQUIRED"):
        bridge._official_profile("synthetic-td", "synthetic-md")
    assert calls == [("synthetic-td", "synthetic-md", "set2_7x24")]
