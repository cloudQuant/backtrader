"""Five-component Gateway fault matrix & secret redaction tests (T-036 / S-05).

Verifies every row of Design §9 (including user decisions D62S-02, D62S-03,
D62S-04, D62S-05, D62S-09b, D62S-09c):
1. Gateway unavailable / proof expired -> open/close/cancel all refused (no Direct fallback)
2. Risk unavailable / unreachable -> open & close refused, direct.delegated_cancel ALLOWED
3. Execution unavailable / unreachable -> open & close BOTH refused (D62S-09b), delegated_cancel ALLOWED
4. Monitor STOP_NEW active -> open refused, close & delegated_cancel ALLOWED; monitor_required=False refused
5. Runtime control disconnected -> running strategy open, close, and cancel ALL CONTINUE NORMALLY (D62S-09c)
6. Redaction check: finite error diagnostics and shutdown summaries leak zero secret/credential strings.
"""

from __future__ import annotations

import socket
import time
from pathlib import Path

import pytest
import yaml

from bt_api_base.gateway_direct_protocol import GatewayCommandBinding

from backtrader.live_state.gateway_pending import GatewayPendingHost
from backtrader.live_state.state_dir import StrategyStateDir
from backtrader.stores import (
    GatewayReadinessProof,
    LiveCompositionError,
    ProcessModeFence,
    create_gateway_store,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
SAMPLE_GATEWAY_YAML = REPO_ROOT / "examples/live/007_ctp_gateway/sa_dual_ma_gateway/config.yaml"


@pytest.fixture(autouse=True)
def _guard(monkeypatch):
    ProcessModeFence._reset_for_tests()

    def _forbid(*args, **kwargs):
        raise AssertionError("Fault matrix tests must never open sockets")

    monkeypatch.setattr(socket, "socket", _forbid)
    monkeypatch.setattr(socket, "create_connection", _forbid)
    yield
    ProcessModeFence._reset_for_tests()


def _setup_gateway(tmp_path: Path):
    state = StrategyStateDir.initialize(tmp_path, mode="gateway")
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
        "security": {"role": "client", "secret_key": "SUPER_SECRET_CURVE_KEY_DO_NOT_LEAK"},
        "risk-security": {"role": "client", "secret_key": "RISK_SECRET_KEY_DO_NOT_LEAK"},
        "execution-security": {"role": "client", "secret_key": "EXEC_SECRET_KEY_DO_NOT_LEAK"},
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
        last_acked_heartbeat_age_ms=100,
        monitor_stop_new_active=False,
        runtime_supervision_expected=True,
        runtime_service_ref="runtime-a",
        registered_run_id="run-fault-matrix",
    )
    store = create_gateway_store(
        config=cfg,
        gateway_host=host,
        gateway_security_profiles=profiles,
        gateway_readiness_proof=proof,
        expected_run_id="run-fault-matrix",
    )
    broker = store.getbroker(expected_run_id="run-fault-matrix", require_readiness_proof=True)
    return store, broker, proof, now_ns


def test_fault_row1_gateway_unavailable_blocks_open_close_cancel_without_direct_fallback(tmp_path):
    store, broker, proof, _ = _setup_gateway(tmp_path)
    expired_ns = proof.expires_at_ns + 1
    for action in ("open", "close", "cancel"):
        with pytest.raises(LiveCompositionError) as exc:
            broker.check_gateway_dispatch_preconditions(action=action, now_ns=expired_ns)
        assert exc.value.code == "GATEWAY_READINESS_UNREACHABLE"
    assert store.is_direct_mode is False


@pytest.mark.parametrize("risk_fault_state", ["UNAVAILABLE", "UNREACHABLE"])
def test_fault_row2_risk_unavailable_blocks_open_and_close_but_allows_delegated_cancel(
    tmp_path, risk_fault_state
):
    store, broker, proof, now_ns = _setup_gateway(tmp_path)
    fault_proof = GatewayReadinessProof(**{**proof.__dict__, "risk_state": risk_fault_state})
    store._gateway_readiness_proof = fault_proof

    for action in ("open", "close", "close_today", "close_yesterday"):
        with pytest.raises(LiveCompositionError) as exc:
            broker.check_gateway_dispatch_preconditions(action=action, now_ns=now_ns)
        assert exc.value.code in {
            "GATEWAY_READINESS_COMPONENT_NOT_READY",
            "GATEWAY_READINESS_UNREACHABLE",
        }

    # D62S-04: delegated_cancel remains allowed during Risk outage
    allowed = broker.check_gateway_dispatch_preconditions(action="cancel", now_ns=now_ns)
    assert allowed == fault_proof


@pytest.mark.parametrize("exec_fault_state", ["UNAVAILABLE", "UNREACHABLE"])
def test_fault_row3_execution_unavailable_blocks_open_and_close_d62s09b_allows_delegated_cancel(
    tmp_path, exec_fault_state
):
    """D62S-09b: Execution unavailable fails closed on BOTH open AND close/reduce (no bypass);
    working child orders remain cancelable via direct.delegated_cancel."""
    store, broker, proof, now_ns = _setup_gateway(tmp_path)
    fault_proof = GatewayReadinessProof(**{**proof.__dict__, "execution_state": exec_fault_state})
    store._gateway_readiness_proof = fault_proof

    for action in ("open", "close", "close_today", "reduce_only"):
        with pytest.raises(LiveCompositionError) as exc:
            broker.check_gateway_dispatch_preconditions(action=action, now_ns=now_ns)
        assert exc.value.code in {
            "GATEWAY_READINESS_COMPONENT_NOT_READY",
            "GATEWAY_READINESS_UNREACHABLE",
        }

    allowed = broker.check_gateway_dispatch_preconditions(action="cancel", now_ns=now_ns)
    assert allowed == fault_proof


def test_fault_row4_monitor_stop_new_blocks_open_allows_close_and_cancel(tmp_path):
    store, broker, proof, now_ns = _setup_gateway(tmp_path)
    stop_new_proof = GatewayReadinessProof(**{**proof.__dict__, "monitor_stop_new_active": True})
    store.update_gateway_readiness_proof(
        stop_new_proof, expected_run_id="run-fault-matrix", now_ns=now_ns
    )

    with pytest.raises(LiveCompositionError) as exc_open:
        broker.check_gateway_dispatch_preconditions(action="open", now_ns=now_ns)
    assert exc_open.value.code == "GATEWAY_READINESS_COMPONENT_NOT_READY"

    assert broker.check_gateway_dispatch_preconditions(action="close", now_ns=now_ns) == stop_new_proof
    assert broker.check_gateway_dispatch_preconditions(action="cancel", now_ns=now_ns) == stop_new_proof

    # monitor_required=False is always refused
    no_monitor = GatewayReadinessProof(**{**proof.__dict__, "monitor_required": False})
    with pytest.raises(LiveCompositionError) as exc_mon:
        store.update_gateway_readiness_proof(
            no_monitor, expected_run_id="run-fault-matrix", now_ns=now_ns
        )
    assert exc_mon.value.code == "GATEWAY_READINESS_COMPONENT_NOT_READY"


def test_fault_row5_runtime_disconnected_running_strategy_continues_d62s09c(tmp_path):
    """D62S-09c: Runtime supervisor control disconnection does NOT block an already-running
    strategy's open, close, or cancel."""
    _, broker, proof, now_ns = _setup_gateway(tmp_path)
    broker.set_runtime_control_connected(False)
    assert broker.runtime_control_connected is False

    for action in ("open", "close", "cancel"):
        assert broker.check_gateway_dispatch_preconditions(action=action, now_ns=now_ns) == proof


def test_fault_diagnostics_and_shutdown_summary_never_leak_secrets(tmp_path):
    store, broker, proof, _ = _setup_gateway(tmp_path)
    bad_proof = GatewayReadinessProof(**{**proof.__dict__, "strategy_principal_has_submit": True})
    store._gateway_readiness_proof = bad_proof
    with pytest.raises(LiveCompositionError) as exc:
        broker.check_gateway_dispatch_preconditions(action="open")

    rendered = f"{exc.value} {broker.get_shutdown_summary()}"
    for secret in (
        "SUPER_SECRET_CURVE_KEY_DO_NOT_LEAK",
        "RISK_SECRET_KEY_DO_NOT_LEAK",
        "EXEC_SECRET_KEY_DO_NOT_LEAK",
    ):
        assert secret not in rendered
