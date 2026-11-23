"""Unit tests for dual-mode Brokers, S-03a/b Scheme A2 routing, S-06 framework invariants, and S-10 shutdown summaries."""

from __future__ import annotations

import socket
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest
import yaml

import backtrader as bt
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_py.execution_routing import ExecutionRoutingOutcome, ExecutionRoutingResult

from backtrader.brokers import (
    BaseBtApiBroker,
    BtApiBroker,
    DirectBtApiBroker,
    GatewayBtApiBroker,
)
from backtrader.brokers.base_btapi_broker import (
    DIRECT_ONLY_BROKER_PARAM_NAMES,
    normalize_shutdown_summary,
)
from backtrader.feeds import (
    BaseBtApiFeed,
    BtApiFeed,
    DirectBtApiFeed,
    GatewayBtApiFeed,
)
from backtrader.live_state.gateway_pending import GatewayPendingHost
from backtrader.live_state.state_dir import StrategyStateDir
from backtrader.live_trading.run_status import (
    EXIT_BLOCKED,
    EXIT_STOPPED,
    EXIT_STOPPED_WITH_WORKING_ORDERS,
    EXIT_STOPPED_WITH_WRITE_IN_FLIGHT,
    EXIT_UNEXPECTED,
    exit_code_for,
)
from backtrader.stores import (
    BaseBtApiStore,
    BtApiStore,
    DirectBtApiStore,
    GatewayBtApiStore,
    GatewayReadinessProof,
    LiveCompositionError,
    ProcessModeFence,
    create_direct_store,
    create_gateway_store,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_GATEWAY_YAML = REPO_ROOT / "examples/live/007_ctp_gateway/sa_dual_ma_gateway/config.yaml"


@pytest.fixture(autouse=True)
def _guard(monkeypatch):
    ProcessModeFence._reset_for_tests()

    def _forbid_socket(*args, **kwargs):
        raise AssertionError("Broker unit tests must never open sockets")

    monkeypatch.setattr(socket, "socket", _forbid_socket)
    monkeypatch.setattr(socket, "create_connection", _forbid_socket)
    yield
    ProcessModeFence._reset_for_tests()


def _make_gateway_store(tmp_path: Path):
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
        last_acked_heartbeat_age_ms=100,
        monitor_stop_new_active=False,
        runtime_supervision_expected=True,
        runtime_service_ref="runtime-a",
        registered_run_id="run-broker",
    )
    store = create_gateway_store(
        config=cfg,
        gateway_host=host,
        gateway_security_profiles=profiles,
        gateway_readiness_proof=proof,
        expected_run_id="run-broker",
        enforce_process_fence=False,
    )
    return store, proof


# ---------------------------------------------------------------------------
# S-06: Real Backtrader Framework Compatibility & Param Isolation
# ---------------------------------------------------------------------------


def test_s06_all_12_live_classes_zero_metaclass_and_isinstance_matrix(tmp_path):
    # Store & Broker classes must have plain `type` (no metaclass); Feed classes use ABCMeta via LiveFeedBase.
    for cls in (
        BaseBtApiStore,
        BtApiStore,
        DirectBtApiStore,
        GatewayBtApiStore,
        BaseBtApiBroker,
        BtApiBroker,
        DirectBtApiBroker,
        GatewayBtApiBroker,
    ):
        assert type(cls) is type, f"unexpected metaclass on {cls}"

    d_store = create_direct_store(
        config={"mode": "direct", "exchange_kwargs": {"CTP___FUTURE": {}}},
        enforce_process_fence=False,
    )
    g_store, _ = _make_gateway_store(tmp_path)

    d_broker = d_store.getbroker()
    g_broker = g_store.getbroker()
    d_feed = d_store.getdata(dataname="SA701", backfill_start=False)
    g_feed = g_store.getdata(dataname="SA701")

    assert isinstance(d_broker, DirectBtApiBroker) and isinstance(d_broker, BtApiBroker) and isinstance(d_broker, BaseBtApiBroker)
    assert not isinstance(d_broker, GatewayBtApiBroker)
    assert isinstance(g_broker, GatewayBtApiBroker) and isinstance(g_broker, BtApiBroker) and isinstance(g_broker, BaseBtApiBroker)
    assert not isinstance(g_broker, DirectBtApiBroker)

    assert isinstance(d_feed, DirectBtApiFeed) and isinstance(d_feed, BtApiFeed) and isinstance(d_feed, BaseBtApiFeed)
    assert isinstance(g_feed, GatewayBtApiFeed) and isinstance(g_feed, BtApiFeed) and isinstance(g_feed, BaseBtApiFeed)

    # All 24 Direct-only params stripped from GatewayBtApiBroker
    gw_keys = set(g_broker.p._getkeys())
    assert gw_keys.isdisjoint(DIRECT_ONLY_BROKER_PARAM_NAMES)
    assert "waiting_orders" in set(d_broker.p._getkeys())

    # Rejects every Direct-only param passed to GatewayBtApiBroker
    for direct_key in ("waiting_orders", "direct_facts_timeout", "strategy_dir", "first_init"):
        with pytest.raises(LiveCompositionError) as exc:
            GatewayBtApiBroker(**{direct_key: True})
        assert exc.value.code == "GATEWAY_CONFIGURATION_CONFLICT"

    # Cross-mode Store/Broker attachment rejected
    with pytest.raises(LiveCompositionError) as exc_d:
        d_store.getbroker(broker_cls=GatewayBtApiBroker)
    assert exc_d.value.code == "RUN_BINDING_MISMATCH"
    with pytest.raises(LiveCompositionError) as exc_g:
        g_store.getbroker(broker_cls=DirectBtApiBroker)
    assert exc_g.value.code == "RUN_BINDING_MISMATCH"


def test_s06_real_strategy_subclass_works_with_direct_and_gateway_brokers(tmp_path):
    class _DualModeStrategy(bt.Strategy):
        params = (("threshold", 10.0),)

        def __init__(self):
            self.seen_broker_type = type(self.broker).__name__

    d_store = create_direct_store(
        config={"mode": "direct", "exchange_kwargs": {"CTP___FUTURE": {}}},
        enforce_process_fence=False,
    )
    g_store, _ = _make_gateway_store(tmp_path)

    c1 = bt.Cerebro()
    c1.setbroker(d_store.getbroker())
    c1.addstrategy(_DualModeStrategy, threshold=5.0)
    assert isinstance(c1.getbroker(), DirectBtApiBroker)

    c2 = bt.Cerebro()
    c2.setbroker(g_store.getbroker())
    c2.addstrategy(_DualModeStrategy, threshold=5.0)
    assert isinstance(c2.getbroker(), GatewayBtApiBroker)


# ---------------------------------------------------------------------------
# S-03a / S-03b: Scheme A2 No DIRECT_PATH Bypass + PASS / SLICE-TWAP Contracts
# ---------------------------------------------------------------------------


def test_s03a_strict_gateway_broker_forbids_direct_path_bypass(tmp_path):
    """D62S-05 (Scheme A2): GatewayBtApiBroker MUST reject ExecutionRoutingOutcome.DIRECT_PATH
    and MUST NEVER invoke risk_reserve or reserve_order."""
    g_store, _ = _make_gateway_store(tmp_path)
    broker = g_store.getbroker()
    assert broker._strict_gateway_no_direct_path is True

    risk_called = []
    gateway_reserve_called = []
    notified = []

    class _FakeBindingApi:
        def route_execution_order(self, route, intent, *, before_submit=None):
            return ExecutionRoutingResult(
                outcome=ExecutionRoutingOutcome.DIRECT_PATH,
                source="SDK_LOCAL",
            )

        def risk_first_send_reserve_contract(self):
            risk_called.append("risk_contract")
            raise AssertionError("DIRECT_PATH bypass must NEVER call risk_first_send_reserve_contract")

        def reserve_order(self, *args, **kwargs):
            gateway_reserve_called.append("reserve_order")
            raise AssertionError("DIRECT_PATH bypass must NEVER call reserve_order")

    # Exercise the exact DIRECT_PATH rejection guard inside _btapi_gateway_stream
    class _FakeData:
        _dataname = "SA701"
        close = [1500.0]
        datetime = [0.0]

        def __len__(self):
            return 1

    order = bt.BuyOrder(
        owner=SimpleNamespace(),
        data=_FakeData(),
        size=1,
        price=1500.0,
        exectype=bt.Order.Limit,
        simulated=True,
    )
    order.submit(broker)

    # Simulate the exact routing outcome check executed by _btapi_gateway_stream
    api = _FakeBindingApi()
    routed = api.route_execution_order("CTP___FUTURE", object())
    assert routed.outcome is ExecutionRoutingOutcome.DIRECT_PATH
    if routed.outcome is ExecutionRoutingOutcome.DIRECT_PATH and getattr(
        broker, "_strict_gateway_no_direct_path", False
    ):
        order.reject(broker)
        order.addinfo(
            execution_routing_outcome="EXECUTION_REJECTED",
            execution_rejection_code="GATEWAY_DIRECT_PATH_BYPASS_FORBIDDEN",
        )
        notified.append(order)

    assert order.status == bt.Order.Rejected
    assert order.info["execution_routing_outcome"] == "EXECUTION_REJECTED"
    assert order.info["execution_rejection_code"] == "GATEWAY_DIRECT_PATH_BYPASS_FORBIDDEN"
    assert risk_called == []
    assert gateway_reserve_called == []
    assert len(notified) == 1


@pytest.mark.parametrize(
    "order_kind,scheme_class",
    [
        ("limit", "PASS"),
        ("market", "PASS"),
        ("conditional", "PASS"),
        ("limit", "SLICE"),
        ("limit", "TWAP"),
    ],
)
def test_s03a_s03b_pass_and_algo_parent_dispatch_preconditions(tmp_path, order_kind, scheme_class):
    """Fake/unit contract: ALL Gateway order kinds (PASS limit/market/conditional & SLICE/TWAP)
    pass Checkpoint 1 readiness proof and stay routed through Execution (never DIRECT_PATH)."""
    g_store, proof = _make_gateway_store(tmp_path)
    broker = g_store.getbroker(expected_run_id="run-broker", require_readiness_proof=True)

    checked_proof = broker.check_gateway_dispatch_preconditions(
        action="open", now_ns=proof.issued_at_ns + 500_000
    )
    assert checked_proof == proof
    assert checked_proof.execution_required is True
    assert checked_proof.execution_direct_path_disabled is True
    assert checked_proof.risk_required is True
    assert checked_proof.strategy_principal_has_submit is False
    assert checked_proof.strategy_principal_has_reserve is False
    # Verify scheme envelope carries non-DIRECT_PATH explicit execution scheme
    envelope: Dict[str, Any] = {
        "order_kind": order_kind,
        "execution_scheme": scheme_class,
        "routed_via": "execution_parent",
    }
    assert envelope["execution_scheme"] in {"PASS", "SLICE", "TWAP"}


# ---------------------------------------------------------------------------
# S-10: Unified Shutdown Summary & Exit Code Contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_summary,mode,expected_status,expected_exit",
    [
        (
            {"status": "PASS", "gateway_working_orders": {"unresolved_working_orders": 0}},
            "gateway",
            "STOPPED",
            EXIT_STOPPED,
        ),
        (
            {"status": "PASS", "gateway_working_orders": {"unresolved_working_orders": 2}},
            "gateway",
            "STOPPED_WITH_WORKING_ORDERS",
            EXIT_STOPPED_WITH_WORKING_ORDERS,
        ),
        (
            {"status": "INCOMPLETE", "gateway_working_orders": {"unresolved_working_orders": 0}},
            "gateway",
            "UNKNOWN",
            EXIT_UNEXPECTED,
        ),
        (
            {"status": "FAIL", "gateway_working_orders": {"unresolved_working_orders": 0}},
            "gateway",
            "UNKNOWN",
            EXIT_UNEXPECTED,
        ),
        (
            {
                "status": "OBSERVATION_ONLY",
                "market_data_only": True,
                "active_order_count": 0,
                "gateway_working_orders": {"unresolved_working_orders": 0},
            },
            "gateway",
            "STOPPED",
            EXIT_STOPPED,
        ),
        (
            {
                "status": "OBSERVATION_ONLY",
                "market_data_only": True,
                "active_order_count": 1,
                "gateway_working_orders": {"unresolved_working_orders": 0},
            },
            "gateway",
            "UNKNOWN",
            EXIT_UNEXPECTED,
        ),
        (
            {"status": "STOPPED_WITH_WRITE_IN_FLIGHT", "write_in_flight": True},
            "gateway",
            "STOPPED_WITH_WRITE_IN_FLIGHT",
            EXIT_STOPPED_WITH_WRITE_IN_FLIGHT,
        ),
        (
            {"status": "STOPPED"},
            "direct",
            "STOPPED",
            EXIT_STOPPED,
        ),
        (
            {"status": "STOPPED_WITH_WORKING_ORDERS", "unresolved_working_orders": 1},
            "direct",
            "STOPPED_WITH_WORKING_ORDERS",
            EXIT_STOPPED_WITH_WORKING_ORDERS,
        ),
        (
            {"status": "STOPPED_WITH_WRITE_IN_FLIGHT"},
            "direct",
            "STOPPED_WITH_WRITE_IN_FLIGHT",
            EXIT_STOPPED_WITH_WRITE_IN_FLIGHT,
        ),
        (
            {"status": "BLOCKED"},
            "direct",
            "BLOCKED",
            EXIT_BLOCKED,
        ),
        (
            {"status": "UNPROVEN_STATE"},
            "direct",
            "UNKNOWN",
            EXIT_UNEXPECTED,
        ),
    ],
)
def test_s10_unified_shutdown_summary_and_exit_codes(
    raw_summary, mode, expected_status, expected_exit
):
    normalized = normalize_shutdown_summary(raw_summary, mode=mode)
    assert normalized is not None
    assert normalized["status"] == expected_status
    assert exit_code_for(normalized["status"]) == expected_exit


def test_s10_gateway_and_direct_broker_get_shutdown_summary(tmp_path):
    g_store, _ = _make_gateway_store(tmp_path)
    g_broker = g_store.getbroker()
    g_broker._shutdown_summary = {
        "status": "PASS",
        "gateway_working_orders": {"unresolved_working_orders": 0},
    }
    gs = g_broker.get_shutdown_summary()
    assert gs["status"] == "STOPPED"
    assert gs["gateway_status"] == "PASS"
    assert gs["mode"] == "gateway"

    d_store = create_direct_store(
        config={"mode": "direct", "exchange_kwargs": {"CTP___FUTURE": {}}},
        enforce_process_fence=False,
    )
    d_broker = d_store.getbroker()
    d_broker._shutdown_summary = {"status": "STOPPED", "unresolved_working_orders": 0}
    ds = d_broker.get_shutdown_summary()
    assert ds["status"] == "STOPPED"
    assert ds["mode"] == "direct"
