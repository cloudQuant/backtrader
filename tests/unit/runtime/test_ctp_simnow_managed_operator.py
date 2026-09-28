"""Offline tests for the managed SimNow candidate selector and scope pin."""

from __future__ import annotations

import hashlib
import inspect
import time
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import backtrader_runtime.config as runtime_config
from backtrader_runtime.ctp_simnow_managed_operator import (
    CtpSimNowManagedExecutionPolicy,
    CtpSimNowManagedOperatorError,
    CtpSimNowManagedScopeSelection,
    ctp_simnow_front_pair_set_sha256,
    select_ctp_simnow_managed_scope,
)
from backtrader_runtime.ctp_simulation_execution import (
    CtpSimulationExecutionError,
    CtpSimulationExecutionSession,
    CtpSimulationWriteApproval,
    CtpSimulationWriteRequest,
)
from backtrader_runtime.registry import (
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    validate_runtime_config,
)


RUNTIME_ID = "iteration41.ctp.simnow.managed-selector-test"
STRATEGY_ID = "iteration41.ctp.simnow.managed_selector_test"
RECEIPT_DIGEST = "a" * 64
PAIRS = (
    ("tcp://127.0.0.1:11001", "tcp://127.0.0.1:12001"),
    ("tcp://127.0.0.1:11002", "tcp://127.0.0.1:12002"),
    ("tcp://127.0.0.1:11003", "tcp://127.0.0.1:12003"),
    ("tcp://127.0.0.1:11004", "tcp://127.0.0.1:12004"),
)


@pytest.fixture(autouse=True)
def _allow_synthetic_private_file(monkeypatch: pytest.MonkeyPatch) -> None:
    # ACL and private-file identity are covered by the config-loader tests;
    # this module tests only sealed-scope policy and front selection.
    monkeypatch.setattr(runtime_config, "_require_private_config_security", lambda *a, **k: None)


def _write_config(
    runtime_dir: Path,
    *,
    pairs=PAIRS,
    instrument_id="rb2701",
    exchange_id="SHFE",
    hedge_flag="1",
    broker_id="9999",
    user_id="offline-test",
) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    pair_lines = ["  front_pairs:"]
    for md_front, td_front in pairs:
        pair_lines.extend(("    - md_front: " + md_front, "      td_front: " + td_front))
    (runtime_dir / "config.yaml").write_text(
        "\n".join(
            [
                "config_schema_version: 4",
                "strategy:",
                "  id: " + STRATEGY_ID,
                "runtime:",
                "  mode: simulation",
                "  preset: sandbox",
                "parameters: {}",
                "secrets_ref: config_yaml",
                "ctp:",
                *pair_lines,
                "  instrument_id: " + instrument_id,
                "  exchange_id: " + exchange_id,
                "  hedge_flag: '" + hedge_flag + "'",
                "  broker_id: '" + broker_id + "'",
                "  user_id: " + user_id,
                "  password: fake-password-for-test-only",
                "  app_id: fake-app-for-test-only",
                "  auth_code: fake-auth-for-test-only",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _registry(runtime_dir: Path, **config_values) -> RuntimeRegistry:
    _write_config(runtime_dir, **config_values)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id=RUNTIME_ID,
        strategy_id=STRATEGY_ID,
        allowed_presets=("sandbox",),
        allowed_parameter_keys=(),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=("execution", "risk", "monitor"),
        sandbox_write_policy="receipt_required",
        approval_receipt_digest=RECEIPT_DIGEST,
    )
    return RuntimeRegistry((registration,), registry_id="test.simnow.managed-selector")


def _profile_registry(
    runtime_dir: Path, *, sandbox_write_policy: str = "receipt_required"
) -> RuntimeRegistry:
    _write_config(runtime_dir)
    writable = sandbox_write_policy == "receipt_required"
    profile = RuntimeProfile(
        mode="simulation",
        preset="sandbox",
        allowed_parameter_keys=(),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=("execution", "risk", "monitor") if writable else (),
        approval_receipt_digest=RECEIPT_DIGEST if writable else None,
        runner_module=None,
        runner_entrypoint="run_runtime",
        capability_modules=(),
        offline_managed_execution=False,
        sandbox_write_policy=sandbox_write_policy,
    )
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id=RUNTIME_ID,
        strategy_id=STRATEGY_ID,
        allowed_presets=(),
        profiles=(profile,),
    )
    return RuntimeRegistry((registration,), registry_id="test.simnow.profile-selector")


def _policy(registry: RuntimeRegistry, runtime_dir: Path, **changes):
    values = {
        "runtime_registration": registry.require_runtime_dir(runtime_dir),
        "allowed_sides": ("BUY", "SELL"),
        "quantity_step": 1,
        "max_quantity": 2,
        "max_gross_position": 2,
        "min_price": Decimal("100"),
        "max_price": Decimal("200"),
        "price_tick": Decimal("1"),
        "approval_key_id": "test-key-1",
        "approval_ttl_seconds": 20,
    }
    values.update(changes)
    return CtpSimNowManagedExecutionPolicy(**values)


def _account_digest(broker_id: str, user_id: str) -> str:
    fingerprint = hashlib.sha256(f"{broker_id}:{user_id}".encode()).hexdigest()[:16]
    return hashlib.sha256(("acct_" + fingerprint).encode("ascii")).hexdigest()


def _connector(latencies, unreachable=(), calls=None):
    unreachable = set(unreachable)

    def connect(host: str, port: int, timeout: float):
        if calls is not None:
            calls.append((host, port, timeout))
        if port in unreachable:
            raise OSError("synthetic unreachable endpoint")
        latency = latencies[port]
        return SimpleNamespace(
            latency_ms=latency,
            dns_resolution_ms=0.0,
            tcp_connect_ms=latency,
            close=lambda: None,
        )

    return connect


def _select(runtime_dir, registry, policy, connector, **kwargs):
    effective = validate_runtime_config(runtime_dir, registry)
    return select_ctp_simnow_managed_scope(
        effective,
        registry,
        policy,
        connector=connector,
        repeated_samples=1,
        **kwargs,
    )


def test_four_configured_pairs_fail_over_then_pin_fastest_reachable_pair(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    registry = _registry(runtime_dir)
    policy = _policy(registry, runtime_dir)
    calls = []
    connector = _connector(
        {11002: 30.0, 12002: 50.0, 11003: 18.0, 12003: 20.0, 11004: 18.0, 12004: 20.0},
        unreachable=(11001, 12001),
        calls=calls,
    )

    selected = _select(runtime_dir, registry, policy, connector)

    assert len(selected.front_pair_selection.evidence) == 4
    assert selected.front_pair_selection.config_index == 2
    assert selected.front_pair_selection.pair.md_front == PAIRS[2][0]
    assert selected.front_pair_selection.pair.td_front == PAIRS[2][1]
    assert (selected.execution_registration.md_front, selected.execution_registration.td_front) == (
        PAIRS[2][0],
        PAIRS[2][1],
    )
    assert len(calls) == 8  # every configured MD/TD endpoint is probed once
    assert (
        selected.execution_registration.front_pair_set_sha256
        == ctp_simnow_front_pair_set_sha256(
            tuple({"md_front": md, "td_front": td} for md, td in PAIRS)
        )
    )
    assert selected.execution_registration.config_digest == selected.config_digest
    assert selected.execution_registration.effective_digest == selected.effective_digest
    with pytest.raises(FrozenInstanceError):
        selected.front_pair_selection = None  # type: ignore[misc]


def test_all_unreachable_candidates_reject_without_selecting_a_pair(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    registry = _registry(runtime_dir)
    calls = []

    with pytest.raises(CtpSimNowManagedOperatorError) as rejected:
        _select(
            runtime_dir,
            registry,
            _policy(registry, runtime_dir),
            _connector({}, unreachable=range(11001, 12005), calls=calls),
        )

    assert rejected.value.reason == "front_pair_probe_no_configured_front_pair_reachable"
    assert len(calls) == 8


def test_canonical_ctp_block_uses_the_same_simnow_selector(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    registry = _registry(runtime_dir)
    latencies = dict.fromkeys(range(11001, 11005), 15.0)
    latencies.update(dict.fromkeys(range(12001, 12005), 15.0))

    selected = _select(
        runtime_dir,
        registry,
        _policy(registry, runtime_dir),
        _connector(latencies),
    )

    assert selected.execution_registration.md_front == PAIRS[0][0]
    assert selected.execution_registration.td_front == PAIRS[0][1]


def test_profile_backed_selector_binds_selected_profile_and_receipt(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "profile-runtime"
    registry = _profile_registry(runtime_dir)
    policy = _policy(registry, runtime_dir)
    effective = validate_runtime_config(runtime_dir, registry)
    profile = effective.profile
    assert profile is not None
    latency = dict.fromkeys(range(11001, 11005), 10.0)
    latency.update(dict.fromkeys(range(12001, 12005), 12.0))

    selected = select_ctp_simnow_managed_scope(
        effective,
        registry,
        policy,
        connector=_connector(latency),
        repeated_samples=1,
    )

    registration = selected.execution_registration
    assert selected.profile_digest == profile.digest
    assert registration.profile_digest == profile.digest
    assert registration.profile_approval_receipt_digest == profile.approval_receipt_digest
    assert registration.runtime_registration.approval_receipt_digest is None
    assert registration.digest != replace(registration, profile_digest="f" * 64).digest
    assert registration.digest != replace(
        registration, profile_approval_receipt_digest="b" * 64
    ).digest

    with pytest.raises(CtpSimNowManagedOperatorError) as rejected:
        CtpSimNowManagedScopeSelection(
            execution_registration=replace(registration, profile_digest="f" * 64),
            front_pair_selection=selected.front_pair_selection,
            front_pair_set_sha256=selected.front_pair_set_sha256,
            config_digest=selected.config_digest,
            effective_digest=selected.effective_digest,
            profile_digest=selected.profile_digest,
        )
    assert rejected.value.reason == "selected_scope_binding_mismatch"


def test_default_deny_profile_cannot_create_managed_policy(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "deny-profile-runtime"
    registry = _profile_registry(runtime_dir, sandbox_write_policy="deny")

    with pytest.raises(CtpSimNowManagedOperatorError) as rejected:
        _policy(registry, runtime_dir)

    assert rejected.value.reason == "runtime_profile_policy_mismatch"


def test_profile_selector_rejects_config_changed_since_resolution_before_probe(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "profile-runtime"
    registry = _profile_registry(runtime_dir)
    policy = _policy(registry, runtime_dir)
    effective = validate_runtime_config(runtime_dir, registry)
    _write_config(runtime_dir, instrument_id="rb2702")
    calls = []

    with pytest.raises(CtpSimNowManagedOperatorError) as rejected:
        select_ctp_simnow_managed_scope(
            effective,
            registry,
            policy,
            connector=_connector({}, calls=calls),
            repeated_samples=1,
        )

    assert rejected.value.reason == "sealed_runtime_config_changed"
    assert calls == []


def test_managed_policy_has_no_config_specific_account_front_or_contract_scope(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "runtime"
    registry = _registry(runtime_dir)
    fields = set(CtpSimNowManagedExecutionPolicy.__dataclass_fields__)

    assert "runtime_registration" in fields
    assert "approval_key_id" in fields
    assert "max_quantity" in fields
    assert "max_gross_position" in fields
    assert not fields.intersection(
        {
            "account_fingerprint_sha256",
            "front_pair_set_sha256",
            "md_front",
            "td_front",
            "front_pairs",
            "instrument_id",
            "exchange_id",
            "hedge_flag",
        }
    )
    _policy(registry, runtime_dir)


def test_config_can_change_account_fronts_and_contract_without_policy_change(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "runtime"
    registry = _registry(runtime_dir)
    policy = _policy(registry, runtime_dir)
    first_latency = dict.fromkeys(range(11001, 11005), 10.0)
    first_latency.update(dict.fromkeys(range(12001, 12005), 12.0))
    first = _select(runtime_dir, registry, policy, _connector(first_latency))

    updated_pairs = (
        ("tcp://127.0.0.1:11005", "tcp://127.0.0.1:12005"),
        ("tcp://127.0.0.1:11006", "tcp://127.0.0.1:12006"),
    )
    _write_config(
        runtime_dir,
        pairs=updated_pairs,
        instrument_id="rb2702",
        exchange_id="DCE",
        hedge_flag="2",
        broker_id="8888",
        user_id="changed-account",
    )
    updated_latency = {11005: 40.0, 12005: 42.0, 11006: 8.0, 12006: 9.0}
    second = _select(runtime_dir, registry, policy, _connector(updated_latency))

    assert (
        second.execution_registration.runtime_registration
        is first.execution_registration.runtime_registration
    )
    assert second.execution_registration.instrument_id == "rb2702"
    assert second.execution_registration.exchange_id == "DCE"
    assert second.execution_registration.hedge_flag == "2"
    assert second.execution_registration.account_fingerprint_sha256 == _account_digest(
        "8888", "changed-account"
    )
    assert second.front_pair_selection.config_index == 1
    assert (
        second.execution_registration.md_front,
        second.execution_registration.td_front,
    ) == updated_pairs[1]
    assert second.front_pair_set_sha256 == ctp_simnow_front_pair_set_sha256(
        tuple({"md_front": md, "td_front": td} for md, td in updated_pairs)
    )
    assert second.config_digest != first.config_digest
    assert second.effective_digest != first.effective_digest
    assert second.execution_registration.digest != first.execution_registration.digest
    assert second.execution_registration.config_digest == second.config_digest
    assert second.execution_registration.effective_digest == second.effective_digest
    assert second.execution_registration.max_quantity == policy.max_quantity
    assert second.execution_registration.max_gross_position == policy.max_gross_position


def test_previous_scope_approval_cannot_authorize_updated_config(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    registry = _registry(runtime_dir)
    policy = _policy(registry, runtime_dir)
    latency = dict.fromkeys(range(11001, 11005), 10.0)
    latency.update(dict.fromkeys(range(12001, 12005), 12.0))
    previous = _select(runtime_dir, registry, policy, _connector(latency))

    _write_config(
        runtime_dir,
        pairs=PAIRS,
        instrument_id="rb2702",
        exchange_id="SHFE",
        hedge_flag="1",
        broker_id="8888",
        user_id="changed-account",
    )
    current = _select(runtime_dir, registry, policy, _connector(latency))
    old_registration = previous.execution_registration
    old_request = CtpSimulationWriteRequest(
        action="SUBMIT",
        client_order_id="old-config-order",
        instrument_id=old_registration.instrument_id,
        exchange_id=old_registration.exchange_id,
        side="BUY",
        quantity=1,
        limit_price=Decimal("100"),
        hedge_flag=old_registration.hedge_flag,
    )
    now = time.time()
    old_approval = CtpSimulationWriteApproval(
        approval_id="old-config-approval",
        key_id=old_registration.approval_key_id,
        registration_digest=old_registration.digest,
        receipt_digest=RECEIPT_DIGEST,
        account_fingerprint_sha256=old_registration.account_fingerprint_sha256,
        environment=old_registration.environment,
        td_front=old_registration.td_front,
        md_front=old_registration.md_front,
        request_digest=old_request.digest,
        issued_at=now,
        expires_at=now + 10,
        signature_hex="0" * 64,
    )
    session_stub = SimpleNamespace(
        registration=current.execution_registration,
        _verifier=SimpleNamespace(verify=lambda _approval: True),
    )

    with pytest.raises(CtpSimulationExecutionError) as rejected:
        CtpSimulationExecutionSession._verify_approval(session_stub, old_request, old_approval)

    assert rejected.value.reason == "approval_scope_or_expiry_mismatch"


def test_candidate_digest_rejects_set_label_fields() -> None:
    with pytest.raises(CtpSimNowManagedOperatorError) as rejected:
        ctp_simnow_front_pair_set_sha256(
            ({"md_front": PAIRS[0][0], "td_front": PAIRS[0][1], "set": "set1"},)
        )
    assert rejected.value.reason == "front_pair_set_invalid"


def test_scope_has_no_set_label_or_calendar_selection_input() -> None:
    fields = set(CtpSimNowManagedExecutionPolicy.__dataclass_fields__)
    parameters = set(inspect.signature(select_ctp_simnow_managed_scope).parameters)
    forbidden = ("set_name", "simnow_set", "profile", "calendar", "trading_day")
    assert not any(any(token in name.lower() for token in forbidden) for name in fields)
    assert not any(any(token in name.lower() for token in forbidden) for name in parameters)
    assert "front_pairs" not in parameters  # candidates come only from the sealed config


def test_changed_sealed_config_is_rejected_before_front_probe(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    registry = _registry(runtime_dir)
    policy = _policy(registry, runtime_dir)
    effective = validate_runtime_config(runtime_dir, registry)
    (runtime_dir / "config.yaml").write_text(
        (runtime_dir / "config.yaml")
        .read_text(encoding="utf-8")
        .replace("instrument_id: rb2701", "instrument_id: rb2702"),
        encoding="utf-8",
    )
    calls = []

    with pytest.raises(CtpSimNowManagedOperatorError) as rejected:
        select_ctp_simnow_managed_scope(
            effective, registry, policy, connector=_connector({}, calls=calls)
        )

    assert rejected.value.reason == "sealed_runtime_config_changed"
    assert calls == []
