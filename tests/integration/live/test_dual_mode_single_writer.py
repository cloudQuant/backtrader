"""Integration simulation tests for single-writer guarantees, ProcessModeFence, and generation handoff (T-034 / S-04).

Evidence level: INTEGRATION_SIM (offline filesystem locks + in-process dual-mode composition,
zero sockets, zero real accounts).
"""

from __future__ import annotations

import socket
import time
from pathlib import Path

import pytest
import yaml

from bt_api_base.gateway_direct_protocol import GatewayCommandBinding

from backtrader.live_state import (
    LiveStateLocked,
    LiveStateModeMismatch,
    StrategyStateDir,
)
from backtrader.live_state.gateway_pending import GatewayPendingHost
from backtrader.stores import (
    GatewayReadinessProof,
    LiveCompositionError,
    LiveRunBinding,
    ProcessModeFence,
    create_direct_store,
    create_gateway_store,
)
from backtrader.stores.btapi_composition import verify_run_binding

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_GATEWAY_YAML = REPO_ROOT / "examples/live/007_ctp/sa_dual_ma_gateway/config.yaml"


@pytest.fixture(autouse=True)
def _guard(monkeypatch):
    ProcessModeFence._reset_for_tests()

    def _forbid_socket(*args, **kwargs):
        raise AssertionError("Single-writer sim tests must never open sockets")

    monkeypatch.setattr(socket, "socket", _forbid_socket)
    monkeypatch.setattr(socket, "create_connection", _forbid_socket)
    yield
    ProcessModeFence._reset_for_tests()


def _build_gateway_strategy(base_dir: Path, name: str, *, proof_generation: int = 1):
    sdir = base_dir / name
    sdir.mkdir()
    state = StrategyStateDir.initialize(sdir, mode="gateway")
    raw = yaml.safe_load(SAMPLE_GATEWAY_YAML.read_text(encoding="utf-8"))
    text = yaml.safe_dump(raw, sort_keys=False).replace(
        "replace-with-registered-strategy-uuid", state.strategy_uuid
    )
    cfg = yaml.safe_load(text)
    cfg["mode"] = "gateway"
    gw_b = cfg["gateway_strategy"]["binding"]
    binding = GatewayCommandBinding(
        journal_id=gw_b["journal_id"],
        account_scope=gw_b["account_scope"],
        strategy_scope=gw_b["strategy_scope"],
        principal=gw_b["principal"],
    )
    host = GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    profiles = {
        "security": {"role": "client"},
        "risk-security": {"role": "client"},
        "execution-security": {"role": "client"},
    }
    now_ns = time.time_ns()
    proof = GatewayReadinessProof(
        schema_version=1,
        proof_generation=proof_generation,
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
        last_acked_heartbeat_age_ms=80,
        monitor_stop_new_active=False,
        runtime_supervision_expected=True,
        runtime_service_ref="runtime-a",
        registered_run_id=f"run-{name}",
    )
    return cfg, state, host, profiles, proof


def test_single_writer_run_lock_blocks_second_writer_and_preserves_state(tmp_path):
    sdir = tmp_path / "direct_strat"
    sdir.mkdir()
    state1 = StrategyStateDir.initialize(sdir, mode="direct")
    state2 = StrategyStateDir(sdir, expected_mode="direct")

    with state1.acquire_run_lock() as lock1:
        assert lock1.held is True
        with pytest.raises(LiveStateLocked):
            state2.acquire_run_lock()
        # Cross-mode open is also blocked
        with pytest.raises(LiveStateModeMismatch):
            StrategyStateDir(sdir, expected_mode="gateway")

    # After release, generation 2 can cleanly acquire lock
    with state2.acquire_run_lock() as lock2:
        assert lock2.held is True


def test_multi_strategy_shared_gateway_owner_isolation(tmp_path):
    """Two strategies sharing one Gateway account scope get isolated state dirs & unforgeable bindings."""
    cfg1, state1, host1, prof1, proof1 = _build_gateway_strategy(tmp_path, "strat_a")
    cfg2, state2, host2, prof2, proof2 = _build_gateway_strategy(tmp_path, "strat_b")

    store1 = create_gateway_store(
        config=cfg1,
        gateway_host=host1,
        gateway_security_profiles=prof1,
        gateway_readiness_proof=proof1,
        expected_run_id="run-strat_a",
    )
    # Second Gateway strategy in same process is allowed (same mode='gateway'),
    # while Direct in this same process is blocked by ProcessModeFence (D62S-09a).
    store2 = create_gateway_store(
        config=cfg2,
        gateway_host=host2,
        gateway_security_profiles=prof2,
        gateway_readiness_proof=proof2,
        expected_run_id="run-strat_b",
    )
    assert store1.run_binding != store2.run_binding
    assert store1.run_binding.strategy_scope == state1.strategy_uuid
    assert store2.run_binding.strategy_scope == state2.strategy_uuid

    # Cross-strategy binding injection fails closed
    with pytest.raises(LiveCompositionError) as exc_cross:
        store1.getdata(dataname="SA701", run_binding=store2.run_binding)
    assert exc_cross.value.code == "RUN_BINDING_MISMATCH"

    with pytest.raises(LiveCompositionError) as exc_proc:
        create_direct_store(config={"mode": "direct", "exchange_kwargs": {"CTP___FUTURE": {}}})
    assert exc_proc.value.code == "PROCESS_MODE_CONFLICT"


def test_generation_handoff_rejects_stale_session_generation(tmp_path):
    """Generation handoff 1 -> 2 rejects stale binding and updates proof generation monotonically."""
    gen1 = LiveRunBinding(mode="direct", route="CTP___FUTURE", session_generation=1)
    gen2 = LiveRunBinding(mode="direct", route="CTP___FUTURE", session_generation=2)
    with pytest.raises(LiveCompositionError) as exc:
        verify_run_binding(gen2, gen1)
    assert exc.value.code == "RUN_BINDING_MISMATCH"

    cfg, _, host, prof, proof_g1 = _build_gateway_strategy(tmp_path, "handoff", proof_generation=1)
    store = create_gateway_store(
        config=cfg,
        gateway_host=host,
        gateway_security_profiles=prof,
        gateway_readiness_proof=proof_g1,
        expected_run_id="run-handoff",
    )
    assert store.gateway_readiness_proof is not None
    assert store.gateway_readiness_proof.proof_generation == 1

    proof_g2 = GatewayReadinessProof(**{**proof_g1.__dict__, "proof_generation": 2})
    updated = store.update_gateway_readiness_proof(proof_g2, expected_run_id="run-handoff")
    assert updated.proof_generation == 2
    assert store.gateway_readiness_proof.proof_generation == 2
