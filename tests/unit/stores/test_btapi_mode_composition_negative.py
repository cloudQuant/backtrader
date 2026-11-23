"""Unit tests for the Direct/Gateway single composition root (SPLIT-01a / T-020).

Covers all frozen positive fixtures (P-01 through P-05) and negative fixtures
(N-01 through N-14) from contracts/negative_fixtures_v1.md with a hard socket
blocker proving zero network I/O occurs during composition or rejection.
"""

from __future__ import annotations

import copy
import socket
import time
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from bt_api_base.gateway_direct_protocol import GatewayCommandBinding

from backtrader.live_state.gateway_pending import GatewayPendingHost
from backtrader.live_state.state_dir import StrategyStateDir
from backtrader.stores import (
    BaseBtApiStore,
    BtApiStore,
    DirectBtApiStore,
    GatewayBtApiStore,
    GatewayReadinessProof,
    LiveCompositionError,
    LiveRunBinding,
    ProcessModeFence,
    create_direct_store,
    create_gateway_store,
    create_live_store,
    validate_live_config,
)
from backtrader.stores._btapi_errors import LegacyGatewayMigrationRequiredError
from backtrader.stores.btapi_composition import (
    detect_forbidden_live_modules,
    validate_gateway_readiness_proof,
    verify_run_binding,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_GATEWAY_YAML = REPO_ROOT / "examples/live/007_ctp/sa_dual_ma_gateway/config.yaml"


class _FakeUnifiedFacade:
    """Minimal public UnifiedBtApiFacade shape for offline P-02 tests."""

    def __init__(self, routes=("CTP___FUTURE",)) -> None:
        self._routes = tuple(routes)

    def list_exchanges(self):
        return list(self._routes)

    async def async_make_order(self, *args, **kwargs):
        raise AssertionError("network/write not allowed in composition test")

    async def async_cancel_order(self, *args, **kwargs):
        raise AssertionError("network/write not allowed in composition test")

    async def async_query_order(self, *args, **kwargs):
        raise AssertionError("network/write not allowed in composition test")

    def poll_events(self, exchange_name, **kwargs):
        return ()

    def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_process_fence_and_block_sockets(monkeypatch):
    """Enforce zero network I/O and clean ProcessModeFence around every test."""
    ProcessModeFence._reset_for_tests()

    def _forbid_socket(*args, **kwargs):
        raise AssertionError("Composition tests must never open sockets")

    monkeypatch.setattr(socket, "socket", _forbid_socket)
    monkeypatch.setattr(socket, "create_connection", _forbid_socket)
    yield
    ProcessModeFence._reset_for_tests()


def _load_gateway_template_dict(strategy_uuid: str) -> Dict[str, Any]:
    raw = yaml.safe_load(SAMPLE_GATEWAY_YAML.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    text = yaml.safe_dump(raw, sort_keys=False).replace(
        "replace-with-registered-strategy-uuid", strategy_uuid
    )
    loaded = yaml.safe_load(text)
    loaded["mode"] = "gateway"
    return loaded


def _make_gateway_env(tmp_path: Path):
    state = StrategyStateDir.initialize(tmp_path)
    cfg = _load_gateway_template_dict(state.strategy_uuid)
    gw_binding_dict = cfg["gateway_strategy"]["binding"]
    binding = GatewayCommandBinding(
        journal_id=gw_binding_dict["journal_id"],
        account_scope=gw_binding_dict["account_scope"],
        strategy_scope=gw_binding_dict["strategy_scope"],
        principal=gw_binding_dict["principal"],
    )
    host = GatewayPendingHost.upgrade_for_gateway(
        state.strategy_dir, state.strategy_uuid, binding
    )
    profiles = {
        "security": {"role": "client"},
        "risk-security": {"role": "client"},
        "execution-security": {"role": "client"},
    }
    now_ns = time.time_ns()
    proof = GatewayReadinessProof(
        schema_version=1,
        proof_generation=1,
        issued_at_ns=now_ns - 1_000_000,
        expires_at_ns=now_ns + 60_000_000_000,
        gateway_service_id="gateway",
        gateway_instance_id="instance",
        gateway_scope_ref="scope",
        account_scope=binding.account_scope,
        strategy_scope=binding.strategy_scope,
        route="CTP___FUTURE",
        strategy_principal_has_submit=False,
        strategy_principal_has_reserve=False,
        delegated_cancel_enabled=True,
        risk_required=True,
        risk_service_ref="risk-a",
        risk_protocol_version="v1",
        risk_state="READY",
        execution_required=True,
        execution_service_ref="execution-a",
        execution_protocol_version="v2",
        execution_state="READY",
        execution_direct_path_disabled=True,
        monitor_required=True,
        monitor_service_ref="monitor-a",
        monitor_protocol_version="v1",
        last_acked_heartbeat_age_ms=250,
        monitor_stop_new_active=False,
        runtime_supervision_expected=True,
        runtime_service_ref="runtime-a",
        registered_run_id="run-001",
    )
    return cfg, host, profiles, proof


# ---------------------------------------------------------------------------
# Positive Fixtures P-01 .. P-05
# ---------------------------------------------------------------------------


def test_p01_direct_normal_composition_zero_network():
    cfg = {
        "mode": "direct",
        "exchange_kwargs": {"CTP___FUTURE": {"broker_id": "9999"}},
        "write_admission": {"CTP___FUTURE": True},
    }
    store = create_live_store(config=cfg)
    assert isinstance(store, DirectBtApiStore)
    assert isinstance(store, BtApiStore)
    assert isinstance(store, BaseBtApiStore)
    assert not isinstance(store, GatewayBtApiStore)
    assert store.run_binding is not None
    assert store.run_binding.mode == "direct"
    assert store.run_binding.market_data_only is False
    assert store.run_binding.route == "CTP___FUTURE"
    assert store.is_direct_mode is True
    assert store.is_gateway_mode is False
    assert store._direct_write_mode is True


def test_p02_direct_controlled_fake_facade_and_factory():
    facade = _FakeUnifiedFacade(("CTP___FUTURE",))
    store1 = create_direct_store(config={"mode": "direct"}, api=facade)
    assert isinstance(store1, DirectBtApiStore)
    assert store1.run_binding is not None
    assert store1.run_binding.mode == "direct"

    store2 = create_direct_store(
        config={"mode": "direct", "exchange_kwargs": {"OKX___SWAP": {}}},
        direct_api_factory=lambda **kw: _FakeUnifiedFacade(("OKX___SWAP",)),
    )
    assert isinstance(store2, DirectBtApiStore)
    assert store2.run_binding is not None
    assert store2.run_binding.mode == "direct"
    assert store2.run_binding.route == "OKX___SWAP"


def test_p03_direct_readonly_rehearsal_fail_closed():
    store_adm_off = create_live_store(
        config={
            "mode": "direct",
            "exchange_kwargs": {"CTP___FUTURE": {"broker_id": "9999"}},
            "write_admission": {"CTP___FUTURE": False},
        }
    )
    assert isinstance(store_adm_off, DirectBtApiStore)
    assert store_adm_off._direct_write_mode is False

    store_mdo = create_live_store(
        config={
            "mode": "direct",
            "exchange_kwargs": {"CTP___FUTURE": {"broker_id": "9999"}},
            "write_admission": {"CTP___FUTURE": True},
            "broker": {"market_data_only": True, "position_mode": "net"},
        }
    )
    assert isinstance(store_mdo, DirectBtApiStore)
    assert store_mdo.run_binding is not None
    assert store_mdo.run_binding.market_data_only is True
    assert store_mdo._direct_write_mode is False


def test_p04_gateway_normal_composition_zero_network(tmp_path):
    cfg, host, profiles, proof = _make_gateway_env(tmp_path)
    store = create_live_store(
        config=cfg,
        gateway_host=host,
        gateway_security_profiles=profiles,
        gateway_readiness_proof=proof,
        expected_run_id="run-001",
    )
    assert isinstance(store, GatewayBtApiStore)
    assert isinstance(store, BtApiStore)
    assert isinstance(store, BaseBtApiStore)
    assert not isinstance(store, DirectBtApiStore)
    assert store.run_binding is not None
    assert store.run_binding.mode == "gateway"
    assert store.run_binding.market_data_only is False
    assert store.run_binding.route == "CTP___FUTURE"
    assert store.gateway_readiness_proof == proof
    assert store.is_gateway_mode is True
    assert store.is_direct_mode is False


def test_p05_gateway_readonly_rehearsal(tmp_path):
    cfg, host, profiles, proof = _make_gateway_env(tmp_path)
    cfg["broker"]["market_data_only"] = True
    degraded_proof = GatewayReadinessProof(**{**proof.__dict__, "risk_state": "DEGRADED"})
    store = create_gateway_store(
        config=cfg,
        gateway_host=host,
        gateway_security_profiles=profiles,
        gateway_readiness_proof=degraded_proof,
        expected_run_id="run-001",
    )
    assert isinstance(store, GatewayBtApiStore)
    assert store.run_binding is not None
    assert store.run_binding.mode == "gateway"
    assert store.run_binding.market_data_only is True


# ---------------------------------------------------------------------------
# Negative Fixtures N-01 .. N-14
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_cfg,expected_code",
    [
        ({"exchange_kwargs": {"CTP___FUTURE": {}}}, "MODE_REQUIRED"),
        ({"mode": None, "exchange_kwargs": {"CTP___FUTURE": {}}}, "MODE_REQUIRED"),
        ({"mode": "hybrid"}, "MODE_INVALID"),
        ({"mode": "paper"}, "MODE_INVALID"),
        ({"mode": "DIRECT"}, "MODE_INVALID"),
        ({"mode": 1}, "MODE_INVALID"),
        ({"mode": True}, "MODE_INVALID"),
    ],
)
def test_n01_missing_or_invalid_mode_rejected(bad_cfg, expected_code):
    with pytest.raises(LiveCompositionError) as exc:
        create_live_store(config=bad_cfg)
    assert exc.value.code == expected_code


@pytest.mark.parametrize(
    "forbidden_key,value",
    [
        ("gateway_strategy", {"schema_version": 1}),
        ("gateway", {"url": "tcp://127.0.0.1:12345"}),
        ("gateway_host", object()),
        ("gateway_security_profiles", {"security": {}}),
        ("gateway_resource_provider", "local_files"),
        ("gateway_resource_files", {"security": {}}),
        ("gateway_run_lock", object()),
        ("gateway_readiness_proof", {"schema_version": 1}),
    ],
)
def test_n02_direct_rejects_gateway_keys(forbidden_key, value):
    cfg = {"mode": "direct", "exchange_kwargs": {"CTP___FUTURE": {}}, forbidden_key: value}
    with pytest.raises(LiveCompositionError) as exc:
        validate_live_config(cfg)
    assert exc.value.code == "MODE_CONFLICT"


@pytest.mark.parametrize(
    "hybrid_key",
    [
        "service_client_config",
        "gateway_client_config",
        "execution_parent_port",
        "execution_order_routing",
    ],
)
def test_n03_direct_rejects_retired_hybrid_routing_keys(hybrid_key):
    cfg = {"mode": "direct", "exchange_kwargs": {"CTP___FUTURE": {}}, hybrid_key: object()}
    with pytest.raises(LiveCompositionError) as exc:
        create_direct_store(config=cfg)
    assert exc.value.code == "LEGACY_HYBRID_ROUTING_RETIRED"


@pytest.mark.parametrize(
    "service_key",
    ["market_runtime_factory", "forwarding_config", "transport_mode"],
)
def test_n04_direct_rejects_service_passthrough_keys(service_key):
    cfg = {"mode": "direct", "exchange_kwargs": {"CTP___FUTURE": {}}, service_key: "x"}
    with pytest.raises(LiveCompositionError) as exc:
        create_direct_store(config=cfg)
    assert exc.value.code == "DIRECT_SERVICE_KEY_FORBIDDEN"

    # Also rejected via DirectBtApiStore directly and inside api_kwargs
    with pytest.raises(LiveCompositionError) as exc2:
        DirectBtApiStore(
            config={"exchange_kwargs": {"CTP___FUTURE": {}}},
            api_kwargs={service_key: "x"},
        )
    assert exc2.value.code == "DIRECT_SERVICE_KEY_FORBIDDEN"


def test_n05_direct_rejects_risk_and_legacy_execution_keys():
    with pytest.raises(LiveCompositionError) as exc_risk:
        validate_live_config({"mode": "direct", "risk": {"client_config": {}}})
    assert exc_risk.value.code == "risk_requires_gateway"

    for legacy_key in (
        "execution_config",
        "order_journal",
        "require_order_journal",
        "order_poll_interval",
        "managed_execution_adapter",
        "execution_authorization",
        "settlement_authorization",
        "account_currency",
        "account_currencies",
        "account_ids",
        "required_environments",
        "strategy_id",
        "strategy_identity_sha256",
        "account_maximum_loss_bps",
        "account_risk_max_age_seconds",
        "event_batch_handoff",
    ):
        with pytest.raises(LiveCompositionError) as exc:
            validate_live_config({"mode": "direct", legacy_key: True})
        assert exc.value.code == "LEGACY_EXECUTION_PATH_RETIRED", legacy_key


@pytest.mark.parametrize(
    "direct_key,value",
    [
        ("exchange_kwargs", {"CTP___FUTURE": {}}),
        ("write_admission", {"CTP___FUTURE": True}),
        ("direct", {"write_admission": True}),
        ("ctp", {"broker_id": "9999"}),
        ("api", object()),
        ("api_cls", object),
        ("api_kwargs", {"x": 1}),
        ("waiting_orders", True),
        ("direct_facts_timeout", 30),
        ("market_runtime_factory", object()),
        ("forwarding_config", {}),
        ("transport_mode", "zmq"),
        ("risk", {"x": 1}),
        ("execution", {"x": 1}),
    ],
)
def test_n06_gateway_rejects_direct_and_hybrid_keys(tmp_path, direct_key, value):
    cfg, _, _, _ = _make_gateway_env(tmp_path)
    cfg[direct_key] = value
    with pytest.raises(LiveCompositionError) as exc:
        validate_live_config(cfg)
    assert exc.value.code == "GATEWAY_CONFIGURATION_CONFLICT"


def test_n06_legacy_backend_and_forwarding_provider_raise_migration_error(tmp_path):
    cfg, _, _, _ = _make_gateway_env(tmp_path)
    cfg["backend"] = "gateway"
    with pytest.raises(LegacyGatewayMigrationRequiredError):
        validate_live_config(cfg)

    with pytest.raises(LegacyGatewayMigrationRequiredError):
        create_direct_store(config={"mode": "direct"}, provider="forwarding")


def test_n07_gateway_rejects_none_or_missing_risk(tmp_path):
    cfg_none, _, _, _ = _make_gateway_env(tmp_path)
    cfg_none["gateway_strategy"]["risk"] = "none"
    with pytest.raises(LiveCompositionError) as exc1:
        validate_live_config(cfg_none)
    assert exc1.value.code == "GATEWAY_RISK_REQUIRED"

    cfg_missing = copy.deepcopy(cfg_none)
    del cfg_missing["gateway_strategy"]["risk"]
    with pytest.raises(LiveCompositionError) as exc2:
        validate_live_config(cfg_missing)
    assert exc2.value.code == "GATEWAY_RISK_REQUIRED"


def test_n08_gateway_rejects_none_or_missing_execution(tmp_path):
    cfg_none, _, _, _ = _make_gateway_env(tmp_path)
    cfg_none["gateway_strategy"]["execution"] = "none"
    with pytest.raises(LiveCompositionError) as exc1:
        validate_live_config(cfg_none)
    assert exc1.value.code == "GATEWAY_EXECUTION_REQUIRED"

    cfg_missing = copy.deepcopy(cfg_none)
    del cfg_missing["gateway_strategy"]["execution"]
    with pytest.raises(LiveCompositionError) as exc2:
        validate_live_config(cfg_missing)
    assert exc2.value.code == "GATEWAY_EXECUTION_REQUIRED"


def test_n09_gateway_rejects_local_calendar_feed_scope(tmp_path):
    cfg, _, _, _ = _make_gateway_env(tmp_path)
    # calendars.root alone is valid
    validate_live_config(cfg)

    bad_scope = copy.deepcopy(cfg)
    bad_scope["calendars"]["feed_scope"] = {"SA701": {"route": "CTP___FUTURE"}}
    with pytest.raises(LiveCompositionError) as exc1:
        validate_live_config(bad_scope)
    assert exc1.value.code == "CALENDAR_SCOPE_CONFLICT"

    bad_feed = copy.deepcopy(cfg)
    bad_feed["feed"]["calendar_route"] = "CTP___FUTURE"
    with pytest.raises(LiveCompositionError) as exc2:
        validate_live_config(bad_feed)
    assert exc2.value.code == "CALENDAR_SCOPE_CONFLICT"

    bad_contract = copy.deepcopy(cfg)
    bad_contract["contracts"]["SA701"]["calendar_venue"] = "CZCE"
    with pytest.raises(LiveCompositionError) as exc3:
        validate_live_config(bad_contract)
    assert exc3.value.code == "CALENDAR_SCOPE_CONFLICT"


def test_n10_run_binding_cross_mode_and_forged_token_rejected():
    direct_binding_a = LiveRunBinding(mode="direct", route="CTP___FUTURE")
    direct_binding_forged = LiveRunBinding(mode="direct", route="CTP___FUTURE")
    gateway_binding = LiveRunBinding(mode="gateway", route="CTP___FUTURE")

    verify_run_binding(direct_binding_a, direct_binding_a)
    for bad in (direct_binding_forged, gateway_binding, None, "direct"):
        with pytest.raises(LiveCompositionError) as exc:
            verify_run_binding(direct_binding_a, bad)
        assert exc.value.code == "RUN_BINDING_MISMATCH"

    store = DirectBtApiStore(
        config={"exchange_kwargs": {"CTP___FUTURE": {}}},
        run_binding=direct_binding_a,
    )
    with pytest.raises(LiveCompositionError) as exc_data:
        store.getdata(dataname="SA701", run_binding=gateway_binding)
    assert exc_data.value.code == "RUN_BINDING_MISMATCH"

    with pytest.raises(LiveCompositionError) as exc_broker:
        store.getbroker(run_binding=direct_binding_forged)
    assert exc_broker.value.code == "RUN_BINDING_MISMATCH"

    with pytest.raises(LiveCompositionError) as exc_ctor:
        DirectBtApiStore(
            config={"exchange_kwargs": {"CTP___FUTURE": {}}},
            run_binding=gateway_binding,
        )
    assert exc_ctor.value.code == "RUN_BINDING_MISMATCH"


def test_n11_gateway_legitimate_direct_mount_and_operation_names_not_false_positive(tmp_path):
    """D62S anti-false-positive boundary: broker.direct_write / direct.delegated_cancel MUST PASS."""
    cfg, _, _, _ = _make_gateway_env(tmp_path)
    # Explicitly ensure legitimate Gateway protocol identifiers containing 'direct' pass
    bindings = cfg["gateway_strategy"]["client_config"]["clients"]["gateway"]["settings"]["bindings"]
    assert any(b["mount"] == "broker.direct_write" for b in bindings)
    assert "direct.delegated_cancel" in cfg["gateway_strategy"]["requested_operations"]

    # Also test application.direct_write mount name in validation
    cfg_app = copy.deepcopy(cfg)
    cfg_app["gateway_strategy"]["client_config"]["clients"]["gateway"]["settings"]["bindings"][0][
        "mount"
    ] = "application.direct_write"
    validated = validate_live_config(cfg_app)
    assert validated["mode"] == "gateway"


def test_n12_readiness_proof_finite_error_classification(tmp_path):
    _, _, _, valid_proof = _make_gateway_env(tmp_path)
    base = dict(valid_proof.__dict__)
    now_ns = valid_proof.issued_at_ns + 500_000

    # Valid proof passes
    assert validate_gateway_readiness_proof(valid_proof, now_ns=now_ns) == valid_proof

    cases = [
        ({"expires_at_ns": now_ns - 1}, "GATEWAY_READINESS_UNREACHABLE"),
        ({"risk_state": "UNREACHABLE"}, "GATEWAY_READINESS_UNREACHABLE"),
        ({"execution_state": "UNREACHABLE"}, "GATEWAY_READINESS_UNREACHABLE"),
        ({"risk_state": "AUTH_FAILED"}, "GATEWAY_READINESS_AUTH_FAILED"),
        ({"execution_state": "AUTH_FAILED"}, "GATEWAY_READINESS_AUTH_FAILED"),
        ({"schema_version": 2}, "GATEWAY_READINESS_VERSION_INCOMPATIBLE"),
        ({"risk_state": "INCOMPATIBLE"}, "GATEWAY_READINESS_VERSION_INCOMPATIBLE"),
        ({"execution_state": "INCOMPATIBLE"}, "GATEWAY_READINESS_VERSION_INCOMPATIBLE"),
        ({"strategy_principal_has_submit": True}, "GATEWAY_PRINCIPAL_BYPASS_UNSAFE"),
        ({"strategy_principal_has_reserve": True}, "GATEWAY_PRINCIPAL_BYPASS_UNSAFE"),
        ({"delegated_cancel_enabled": False}, "GATEWAY_READINESS_COMPONENT_NOT_READY"),
        ({"risk_required": False}, "GATEWAY_RISK_REQUIRED"),
        ({"execution_required": False}, "GATEWAY_EXECUTION_REQUIRED"),
        ({"execution_direct_path_disabled": False}, "GATEWAY_DIRECT_PATH_BYPASS_FORBIDDEN"),
        ({"monitor_required": False}, "GATEWAY_READINESS_COMPONENT_NOT_READY"),
        ({"runtime_supervision_expected": False}, "GATEWAY_READINESS_COMPONENT_NOT_READY"),
        ({"risk_state": "UNAVAILABLE"}, "GATEWAY_READINESS_COMPONENT_NOT_READY"),
        ({"execution_state": "DEGRADED"}, "GATEWAY_READINESS_COMPONENT_NOT_READY"),
        ({"route": "OKX___SWAP"}, "GATEWAY_VENUE_UNSUPPORTED"),
    ]
    for overrides, expected_code in cases:
        mutated = {**base, **overrides}
        with pytest.raises(LiveCompositionError) as exc:
            validate_gateway_readiness_proof(mutated, now_ns=now_ns)
        assert exc.value.code == expected_code, (overrides, exc.value.code)

    # expected_run_id mismatch
    with pytest.raises(LiveCompositionError) as exc_run:
        validate_gateway_readiness_proof(valid_proof, expected_run_id="other-run", now_ns=now_ns)
    assert exc_run.value.code == "GATEWAY_READINESS_COMPONENT_NOT_READY"


def test_n13_process_mode_fence_single_process_single_mode(tmp_path):
    assert ProcessModeFence.current() is None
    create_direct_store(
        config={"mode": "direct", "exchange_kwargs": {"CTP___FUTURE": {}}},
    )
    assert ProcessModeFence.current() == "direct"
    # Second Direct in same process succeeds
    create_direct_store(
        config={"mode": "direct", "exchange_kwargs": {"CTP___FUTURE": {}}},
    )
    # Gateway in same process MUST fail with PROCESS_MODE_CONFLICT
    cfg, host, profiles, proof = _make_gateway_env(tmp_path)
    with pytest.raises(LiveCompositionError) as exc:
        create_gateway_store(
            config=cfg,
            gateway_host=host,
            gateway_security_profiles=profiles,
            gateway_readiness_proof=proof,
        )
    assert exc.value.code == "PROCESS_MODE_CONFLICT"

    # Reverse direction: Gateway first, then Direct fails
    ProcessModeFence._reset_for_tests()
    create_gateway_store(
        config=cfg,
        gateway_host=host,
        gateway_security_profiles=profiles,
        gateway_readiness_proof=proof,
    )
    assert ProcessModeFence.current() == "gateway"
    with pytest.raises(LiveCompositionError) as exc_rev:
        create_direct_store(
            config={"mode": "direct", "exchange_kwargs": {"CTP___FUTURE": {}}},
        )
    assert exc_rev.value.code == "PROCESS_MODE_CONFLICT"


def test_n14_gateway_rejects_direct_path_bypass_non_ctp_venue_and_direct_submit_ops(tmp_path):
    cfg, _, _, _ = _make_gateway_env(tmp_path)

    bad_allow = copy.deepcopy(cfg)
    bad_allow["gateway_strategy"]["execution"]["routing"]["allow_direct_path"] = True
    with pytest.raises(LiveCompositionError) as exc1:
        validate_live_config(bad_allow)
    assert exc1.value.code == "GATEWAY_DIRECT_PATH_BYPASS_FORBIDDEN"

    bad_unmatched = copy.deepcopy(cfg)
    bad_unmatched["gateway_strategy"]["execution"]["routing"]["unmatched_policy"] = "DIRECT_PATH"
    with pytest.raises(LiveCompositionError) as exc2:
        validate_live_config(bad_unmatched)
    assert exc2.value.code == "GATEWAY_DIRECT_PATH_BYPASS_FORBIDDEN"

    bad_venue = copy.deepcopy(cfg)
    bad_venue["gateway_strategy"]["exchange_name"] = "OKX___SWAP"
    with pytest.raises(LiveCompositionError) as exc3:
        validate_live_config(bad_venue)
    assert exc3.value.code == "GATEWAY_VENUE_UNSUPPORTED"

    bad_ops = copy.deepcopy(cfg)
    bad_ops["gateway_strategy"]["requested_operations"].append("direct.reserve")
    with pytest.raises(LiveCompositionError) as exc4:
        validate_live_config(bad_ops)
    assert exc4.value.code == "GATEWAY_PRINCIPAL_BYPASS_UNSAFE"


# ---------------------------------------------------------------------------
# Non-live Tool Isolation, StoreParams Safety, and Module Probes
# ---------------------------------------------------------------------------


def test_non_live_tools_rejected_by_live_composition_root():
    with pytest.raises(LiveCompositionError) as exc_replay:
        create_direct_store(config={"mode": "direct"}, provider="local_replay")
    assert exc_replay.value.code == "NON_LIVE_TOOL_CONFLICT"

    class ServiceReadProxy:
        pass

    ServiceReadProxy.__module__ = "backtrader.service.service_read_proxy"
    with pytest.raises(LiveCompositionError) as exc_proxy:
        create_direct_store(config={"mode": "direct"}, api=ServiceReadProxy())
    assert exc_proxy.value.code == "NON_LIVE_TOOL_CONFLICT"


def test_store_hierarchy_has_no_class_level_params_and_zero_metaclass():
    for cls in (BaseBtApiStore, BtApiStore, DirectBtApiStore, GatewayBtApiStore):
        assert "params" not in cls.__dict__, f"{cls.__name__} must not define class-level params"
        assert type(cls) is type


def test_detect_forbidden_live_modules():
    assert detect_forbidden_live_modules(
        "direct",
        loaded_modules=["backtrader.stores", "bt_api_py.bt_api", "bt_api_gateway.server", "bt_api_risk"],
    ) == ("bt_api_gateway.server", "bt_api_risk")
    assert detect_forbidden_live_modules(
        "direct",
        loaded_modules=["backtrader.stores", "bt_api_py.bt_api", "bt_api_ctp"],
    ) == ()
    assert detect_forbidden_live_modules(
        "gateway",
        loaded_modules=["bt_api_py.gateway_api", "bt_api_ctp.direct_write_provider"],
    ) == ("bt_api_ctp.direct_write_provider",)
