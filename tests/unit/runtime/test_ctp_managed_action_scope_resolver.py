"""Real sealed-config tests for the opt-in CTP action scope resolver."""

from __future__ import annotations

import importlib.metadata
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

try:
    if importlib.metadata.version("bt_api_execution") != "0.2.0":
        pytest.skip("V17 execution source is an optional test dependency", allow_module_level=True)
    from bt_api_execution.contracts import ExecutionScope, payload_sha256
    from bt_api_execution.store import CtpCallbackSessionBindingV1, CtpDispatchCommand
except Exception:
    pytest.skip("V17 execution source is an optional test dependency", allow_module_level=True)

from backtrader_runtime.ctp_managed_action_scope_resolver import (
    CtpManagedActionScopeResolutionError,
    SealedCtpManagedActionScopeResolverV1,
    ctp_managed_account_ref_v1,
)
from backtrader_runtime.ctp_production_execution_admission import (
    CtpProductionExecutionRegistration,
)
from backtrader_runtime.ctp_simnow_managed_operator import (
    CtpSimNowManagedExecutionPolicy,
    CtpSimNowManagedOperatorError,
)
from backtrader_runtime.ctp_private_config_setup import (
    _create_private_file,
    _protect_target_directory,
    _verified_target_directory,
)
from backtrader_runtime.policy import MANAGED_WRITE_CAPABILITIES
from backtrader_runtime.registry import (
    RegisteredRuntime,
    RuntimeProfile,
    RuntimeRegistry,
    UnavailableModeProfile,
)


RUNTIME_ID = "synthetic.ctp.sealed-action-scope"
STRATEGY_ID = "synthetic.ctp.strategy"
SIM_RECEIPT = "a" * 64
LIVE_RECEIPT = "b" * 64
FRONT_A = ("tcp://127.0.0.1:11001", "tcp://127.0.0.1:12001")
FRONT_B = ("tcp://127.0.0.1:11002", "tcp://127.0.0.1:12002")
TRADING_DAY = "20260926"


def _config_document(
    *,
    mode: str = "simulation",
    preset: str = "sandbox",
    broker_id: str = "offline-broker",
    user_id: str = "offline-user",
    front_pairs=(FRONT_A, FRONT_B),
    instrument_id: str = "rb2701",
):
    return {
        "config_schema_version": 4,
        "strategy": {"id": STRATEGY_ID},
        "runtime": {"mode": mode, "preset": preset},
        "parameters": {},
        "secrets_ref": "config_yaml",
        "ctp": {
            "front_pairs": [
                {"md_front": md_front, "td_front": td_front} for md_front, td_front in front_pairs
            ],
            "instrument_id": instrument_id,
            "exchange_id": "SHFE",
            "hedge_flag": "1",
            "broker_id": broker_id,
            "user_id": user_id,
            "password": "offline-test-password",
            "app_id": "offline-test-app",
            "auth_code": "offline-test-auth",
        },
    }


def _protected_config(runtime_dir: Path, document) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    path = runtime_dir / "config.yaml"
    content = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with _verified_target_directory(runtime_dir) as descriptor:
        _protect_target_directory(descriptor)
        created = _create_private_file(descriptor, path, content)
    if created.retained_fd is not None:
        os.close(created.retained_fd)
    return path


def _rewrite_config(path: Path, document) -> None:
    content = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with path.open("r+b") as stream:
        stream.seek(0)
        stream.write(content)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == "posix":
        os.chmod(path, 0o600)


def _registry(runtime_dir: Path, *, unavailable_live: bool = False):
    runtime_dir.mkdir(parents=True, exist_ok=True)
    simulation = RuntimeProfile(
        mode="simulation",
        preset="sandbox",
        allowed_parameter_keys=(),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=("execution", "risk", "monitor"),
        approval_receipt_digest=SIM_RECEIPT,
        runner_module=None,
        runner_entrypoint="run_runtime",
        capability_modules=(),
        offline_managed_execution=False,
        sandbox_write_policy="receipt_required",
    )
    live = RuntimeProfile(
        mode="live",
        preset="managed_live_direct",
        allowed_parameter_keys=(),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=MANAGED_WRITE_CAPABILITIES,
        approval_receipt_digest=LIVE_RECEIPT,
        runner_module=None,
        runner_entrypoint="run_runtime",
        capability_modules=(),
        offline_managed_execution=False,
        sandbox_write_policy="deny",
    )
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id=STRATEGY_ID,
        runtime_id=RUNTIME_ID,
        allowed_presets=(),
        profiles=(simulation,) if unavailable_live else (simulation, live),
        unavailable_mode_profiles=(
            (UnavailableModeProfile("live", "managed_live_direct", "test_unavailable"),)
            if unavailable_live
            else ()
        ),
    )
    return RuntimeRegistry((registration,), registry_id="synthetic.scope.resolver"), registration


def _sim_policy(registration: RegisteredRuntime):
    return CtpSimNowManagedExecutionPolicy(
        runtime_registration=registration,
        allowed_sides=("BUY", "SELL"),
        quantity_step=1,
        max_quantity=2,
        max_gross_position=2,
        min_price=Decimal("100"),
        max_price=Decimal("200"),
        price_tick=Decimal("1"),
        approval_key_id="offline-test-key",
    )


def _live_admission(registration: RegisteredRuntime):
    return CtpProductionExecutionRegistration(
        runtime_registration=registration,
        environment="production",
        account_binding_sha256=None,
        md_front=None,
        td_front=None,
        instrument_id=None,
        exchange_id=None,
        hedge_flag=None,
        approval_receipt_id="ctp-production:receipt.synthetic",
        approval_receipt_sha256=LIVE_RECEIPT,
        artifact_id="ctp-production:artifact.synthetic",
        artifact_sha256="d" * 64,
        allowed_sides=("BUY", "SELL"),
        allowed_offsets=("OPEN",),
        quantity_step=1,
        max_order_quantity=2,
        max_gross_position=2,
        min_price=Decimal("100"),
        max_price=Decimal("200"),
        price_tick=Decimal("1"),
        max_order_notional=Decimal("1000"),
        scope_binding_mode="sealed_config",
    )


def _execution_scope(private: dict, environment: str):
    return ExecutionScope(
        provider="ctp",
        environment=environment,
        account_ref=ctp_managed_account_ref_v1(private["broker_id"], private["user_id"]),
        strategy_id=STRATEGY_ID,
        trading_day=TRADING_DAY,
    )


def _command(scope):
    return CtpDispatchCommand(
        account_key=scope.account_key,
        scope_key=scope.key,
        trading_day=TRADING_DAY,
        operation="SUBMIT",
        command_id="command.synthetic.1",
        request_payload={},
        request_payload_sha256=payload_sha256({}),
        reservation_managed_intent_id="intent.synthetic.1",
        order_ref="1",
        cancel_target_order_ref=None,
        cancel_target_exchange_id=None,
        cancel_target_order_sys_id=None,
        cancel_target_front_id=None,
        cancel_target_session_id=None,
        approval_use_id="permit.synthetic.1",
        approval_digest="e" * 64,
        session_binding={},
        session_binding_sha256="f" * 64,
        status="READY",
        created_at_ns=1,
        updated_at_ns=1,
        claimed_at_ns=None,
        claimed_owner_id=None,
        claimed_fencing_token=None,
        completed_at_ns=None,
        unknown_at_ns=None,
        unknown_reason=None,
        native_receipt_payload=None,
        native_receipt_sha256=None,
        completion_echo_sha256=None,
    )


def _action_session_binding(scope):
    return CtpCallbackSessionBindingV1(
        owner_intent_id="owner.synthetic.1",
        account_key=scope.account_key,
        scope_key=scope.key,
        trading_day=scope.trading_day,
        session_generation_id="session.synthetic.1",
        dispatch_front_id=11,
        dispatch_session_id=12,
        source_instance_id="instance.synthetic.1",
        native_client_epoch="epoch.synthetic.1",
        native_api_source_id="api.synthetic.1",
        native_spi_source_id="spi.synthetic.1",
        native_api_generation=1,
        source_connection_generation=1,
        connection_generation=1,
        source_high_watermark=1,
        session_binding_sha256="f" * 64,
    )


def _action_request(private: dict) -> dict[str, str]:
    return {
        "BrokerID": private["broker_id"],
        "InvestorID": private["user_id"],
        "UserID": private["user_id"],
        "InstrumentID": private["instrument_id"],
        "ExchangeID": private["exchange_id"],
        "CombHedgeFlag": private["hedge_flag"],
    }


def _resolver(runtime_dir: Path, mode: str):
    registry, registration = _registry(runtime_dir)
    if mode == "simulation":
        admission = _sim_policy(registration)
        environment = "simnow"
        preset = "sandbox"
    else:
        admission = _live_admission(registration)
        environment = "production"
        preset = "managed_live_direct"
    private = _config_document()["ctp"]
    scope = _execution_scope(private, environment)
    resolver = SealedCtpManagedActionScopeResolverV1(
        registry, registration, admission, FRONT_A, scope
    )
    return resolver, scope, registry, registration, admission, private, preset


def test_account_ref_is_domain_separated_canonical_and_opaque() -> None:
    first = ctp_managed_account_ref_v1("broker", "id")
    second = ctp_managed_account_ref_v1("bro", "kerid")
    assert first.startswith("ctp-account-ref.v1:")
    assert len(first.rsplit(":", 1)[1]) == 64
    assert first != second
    assert "broker" not in first and "id" not in first


def test_simulation_and_live_profiles_resolve_from_real_protected_config(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "runtime"
    path = _protected_config(runtime_dir, _config_document())
    registry, registration = _registry(runtime_dir)

    sim_scope = _execution_scope(_config_document()["ctp"], "simnow")
    sim_resolver = SealedCtpManagedActionScopeResolverV1(
        registry, registration, _sim_policy(registration), FRONT_A, sim_scope
    )
    simulation = sim_resolver.resolve(_command(sim_scope), sim_scope)
    assert simulation.mode == "simulation"
    assert simulation.preset == "sandbox"
    assert simulation.account_fingerprint_sha256 == sim_scope.account_key.partition(":")[2]

    live_doc = _config_document(mode="live", preset="managed_live_direct")
    _rewrite_config(path, live_doc)
    live_scope = _execution_scope(live_doc["ctp"], "production")
    live_resolver = SealedCtpManagedActionScopeResolverV1(
        registry, registration, _live_admission(registration), FRONT_A, live_scope
    )
    live = live_resolver.resolve(_command(live_scope), live_scope)
    assert live.mode == "live"
    assert live.preset == "managed_live_direct"
    assert live.account_fingerprint_sha256 == live_scope.account_key.partition(":")[2]


def test_action_context_binds_request_login_and_cancel_to_real_sealed_config(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    runtime_dir = tmp_path / "runtime"
    _protected_config(runtime_dir, _config_document())
    registry, registration = _registry(runtime_dir)
    private = _config_document()["ctp"]
    scope = _execution_scope(private, "simnow")
    resolver = SealedCtpManagedActionScopeResolverV1(
        registry, registration, _sim_policy(registration), FRONT_A, scope
    )
    session = _action_session_binding(scope)
    request = _action_request(private)
    submit = replace(
        _command(scope),
        request_payload=request,
        request_payload_sha256=payload_sha256(request),
    )

    resolved = resolver.validate_action_context(
        submit,
        scope,
        session_binding=session,
        session_broker_id=private["broker_id"],
        session_user_id=private["user_id"],
    )
    assert resolved.mode == "simulation"

    for field, value in (
        ("BrokerID", "other-broker"),
        ("InvestorID", "other-user"),
        ("UserID", "other-user"),
        ("InstrumentID", "cu9999"),
        ("ExchangeID", "DCE"),
        ("CombHedgeFlag", "2"),
    ):
        changed = dict(request)
        changed[field] = value
        tampered = replace(
            submit,
            request_payload=changed,
            request_payload_sha256=payload_sha256(changed),
        )
        with pytest.raises(CtpManagedActionScopeResolutionError):
            resolver.validate_action_context(
                tampered,
                scope,
                session_binding=session,
                session_broker_id=private["broker_id"],
                session_user_id=private["user_id"],
            )

    for broker_id, user_id in (
        ("wrong-broker", private["user_id"]),
        (private["broker_id"], "wrong-user"),
    ):
        with pytest.raises(CtpManagedActionScopeResolutionError):
            resolver.validate_action_context(
                submit,
                scope,
                session_binding=session,
                session_broker_id=broker_id,
                session_user_id=user_id,
            )

    cancel = replace(submit, operation="CANCEL")
    assert (
        resolver.validate_action_context(
            cancel,
            scope,
            session_binding=session,
            session_broker_id=private["broker_id"],
            session_user_id=private["user_id"],
        ).mode
        == "simulation"
    )

    changed_cancel = dict(request)
    changed_cancel["ExchangeID"] = "DCE"
    tampered_cancel = replace(
        cancel,
        request_payload=changed_cancel,
        request_payload_sha256=payload_sha256(changed_cancel),
    )
    with pytest.raises(CtpManagedActionScopeResolutionError):
        resolver.validate_action_context(
            tampered_cancel,
            scope,
            session_binding=session,
            session_broker_id=private["broker_id"],
            session_user_id=private["user_id"],
        )


@pytest.mark.parametrize(
    "change",
    [
        {"broker_id": "changed-broker"},
        {"user_id": "changed-user"},
        {"front_pairs": (FRONT_B,)},
        {"instrument_id": "cu2701"},
    ],
)
def test_simulation_rejects_current_account_front_or_config_change(tmp_path: Path, change) -> None:
    runtime_dir = tmp_path / "runtime"
    path = _protected_config(runtime_dir, _config_document())
    registry, registration = _registry(runtime_dir)
    original = _config_document()
    scope = _execution_scope(original["ctp"], "simnow")
    resolver = SealedCtpManagedActionScopeResolverV1(
        registry, registration, _sim_policy(registration), FRONT_A, scope
    )
    resolver.resolve(_command(scope), scope)

    changed = dict(original)
    changed_ctp = dict(original["ctp"])
    changed_ctp.update(change)
    changed["ctp"] = changed_ctp
    _rewrite_config(path, changed)
    with pytest.raises(CtpManagedActionScopeResolutionError):
        resolver.resolve(_command(scope), scope)


@pytest.mark.parametrize(
    "change",
    [
        {"broker_id": "changed-live-broker"},
        {"front_pairs": (FRONT_B,)},
        {"instrument_id": "cu2701"},
    ],
)
def test_live_rejects_current_account_front_or_config_change(tmp_path: Path, change) -> None:
    runtime_dir = tmp_path / "runtime"
    original = _config_document(mode="live", preset="managed_live_direct")
    path = _protected_config(runtime_dir, original)
    registry, registration = _registry(runtime_dir)
    scope = _execution_scope(original["ctp"], "production")
    resolver = SealedCtpManagedActionScopeResolverV1(
        registry, registration, _live_admission(registration), FRONT_A, scope
    )
    resolver.resolve(_command(scope), scope)

    changed = dict(original)
    changed_ctp = dict(original["ctp"])
    changed_ctp.update(change)
    changed["ctp"] = changed_ctp
    _rewrite_config(path, changed)
    with pytest.raises(CtpManagedActionScopeResolutionError):
        resolver.resolve(_command(scope), scope)


def test_mode_change_and_command_day_mismatch_reject(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    path = _protected_config(runtime_dir, _config_document())
    registry, registration = _registry(runtime_dir)
    scope = _execution_scope(_config_document()["ctp"], "simnow")
    resolver = SealedCtpManagedActionScopeResolverV1(
        registry, registration, _sim_policy(registration), FRONT_A, scope
    )
    from dataclasses import replace

    with pytest.raises(CtpManagedActionScopeResolutionError):
        resolver.resolve(replace(_command(scope), trading_day="20260925"), scope)

    _rewrite_config(
        path,
        _config_document(mode="live", preset="managed_live_direct"),
    )
    with pytest.raises(CtpManagedActionScopeResolutionError):
        resolver.resolve(_command(scope), scope)


def test_mutated_pinned_scope_day_rejects_even_with_matching_new_command(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "runtime"
    _protected_config(runtime_dir, _config_document())
    registry, registration = _registry(runtime_dir)
    scope = _execution_scope(_config_document()["ctp"], "simnow")
    resolver = SealedCtpManagedActionScopeResolverV1(
        registry, registration, _sim_policy(registration), FRONT_A, scope
    )
    object.__setattr__(scope, "trading_day", "20260925")
    from dataclasses import replace

    changed_command = replace(_command(scope), trading_day="20260925")
    with pytest.raises(CtpManagedActionScopeResolutionError):
        resolver.resolve(changed_command, scope)


def test_resolver_rejects_a_scope_not_derived_from_sealed_account(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    _protected_config(runtime_dir, _config_document())
    registry, registration = _registry(runtime_dir)
    wrong_scope = ExecutionScope(
        "ctp",
        "simnow",
        ctp_managed_account_ref_v1("other-broker", "other-user"),
        STRATEGY_ID,
        TRADING_DAY,
    )
    with pytest.raises(CtpManagedActionScopeResolutionError):
        SealedCtpManagedActionScopeResolverV1(
            registry, registration, _sim_policy(registration), FRONT_A, wrong_scope
        )


def test_unavailable_default_style_profiles_reject_before_config_read(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "unavailable"
    runtime_dir.mkdir()
    registry, registration = _registry(runtime_dir, unavailable_live=True)
    live_scope = ExecutionScope(
        "ctp",
        "production",
        ctp_managed_account_ref_v1("offline-broker", "offline-user"),
        STRATEGY_ID,
        TRADING_DAY,
    )
    with pytest.raises(CtpManagedActionScopeResolutionError):
        SealedCtpManagedActionScopeResolverV1(
            registry,
            registration,
            _live_admission(registration),
            FRONT_A,
            live_scope,
        )


def test_default_inventory_write_denials_are_not_promoted() -> None:
    from backtrader_runtime.inventory import (
        ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION,
    )

    registration = ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION
    assert registration.profile_for("simulation", "sandbox").sandbox_write_policy == "deny"
    with pytest.raises(CtpSimNowManagedOperatorError):
        _sim_policy(registration)
    assert any(
        item.mode == "live" and item.preset == "managed_live_direct"
        for item in registration.unavailable_mode_profiles
    )
