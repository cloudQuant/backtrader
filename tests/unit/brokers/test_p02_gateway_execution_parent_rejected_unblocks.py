"""P0-2 regression tests: GatewayBtApiBroker finalizes definitively rejected
EXECUTION_PARENT orders and unblocks subsequent strategy submissions while keeping
UNKNOWN / pending / mismatched parent statuses strictly fail-closed."""
from __future__ import annotations

import os
import threading
from types import SimpleNamespace

from bt_api_py.execution_routing import ExecutionRoutingOutcome, ExecutionRoutingStatus

from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamBrokerMixin, _bt_terminal
from backtrader.order import BuyOrder


class _DummyOrder:
    Submitted = BuyOrder.Submitted
    Rejected = BuyOrder.Rejected
    Completed = BuyOrder.Completed
    Canceled = BuyOrder.Canceled
    Expired = BuyOrder.Expired
    Margin = BuyOrder.Margin

    def __init__(self, ref: int, data) -> None:
        self.ref = ref
        self.data = data
        self.status = self.Submitted
        self.executed = SimpleNamespace(size=0)
        self.info: dict = {}

    def alive(self) -> bool:
        return not _bt_terminal(self)

    def reject(self, _broker=None) -> None:
        self.status = self.Rejected

    def addinfo(self, **kwargs) -> None:
        self.info.update(kwargs)


class _DummyFeed:
    def __len__(self) -> int:
        return 1


class _DummyHost:
    def __init__(self, route, intent) -> None:
        self._route = route
        self._intent = intent
        self._binding = SimpleNamespace(account_scope="acct-1", principal="strat-p")
        self._local_notices: dict[str, dict] = {}
        self.saved_rejections: list[tuple] = []

    def load_execution_checkpoint(self):
        return SimpleNamespace(
            consumer_ref="c-1",
            epoch="ep-1",
            stored_sequence=0,
            applied_sequence=0,
            acknowledged_sequence=0,
            revision=1,
        )

    def local_order_notifications(self):
        return dict(self._local_notices)

    def load_execution_route(self, key):
        return self._route if key == self._route.request_key else None

    def load_intent(self, key):
        return self._intent if key == self._route.request_key else None

    def save_rejected_order_notification(self, key, *, bt_ref, snapshot, code):
        self.saved_rejections.append((key, bt_ref, code))
        self._local_notices["reject:" + key] = {"status": "delivered", "code": code}
        return {"notification_id": f"notif-{key}"}

    def read_execution_events(self, limit=1):
        return []

    def ingest_execution_result(self, result, *, expected_revision):
        return self.load_execution_checkpoint()


class _DummyBroker(GatewayExecutionStreamBrokerMixin):
    def __init__(self, binding, notice) -> None:
        self._gateway_stream_binding = binding
        self._notice = notice
        self.store = SimpleNamespace(_gateway_mode=False, is_connected=True)
        self.notifs: list = []
        self.finalized: list[tuple] = []

    def _is_market_data_only(self) -> bool:
        return False

    def _gateway_stream_check(self, binding, *, connected_required=True):
        return None

    def _gateway_binding(self, strategy, *, required=True):
        return self._notice

    def _gateway_host_pass_snapshot(self, host):
        return None

    def _gateway_finalize_rejection(self, binding, order, key, code, info=None):
        order.reject(self)
        order.addinfo(gateway_request_denied=code)
        binding.host.save_rejected_order_notification(key, bt_ref=order.ref, snapshot={}, code=code)
        self.finalized.append((key, code))


def _make_rig(status_reply: ExecutionRoutingStatus):
    feed = _DummyFeed()
    order = _DummyOrder(ref=101, data=feed)
    key = "bt-strat-1"
    route = SimpleNamespace(
        kind="EXECUTION_PARENT",
        request_key=key,
        configuration_id="cfg-1",
        request_id="req-1",
        request_sha256="a" * 64,
        parent_ref="parent-1",
    )
    host = _DummyHost(route=route, intent=SimpleNamespace(request_key=key))
    api = SimpleNamespace(
        execution_selected=True,
        execution_configuration_id="cfg-1",
        execution_order_status=lambda _r, _i: status_reply,
    )
    stream = SimpleNamespace(
        read_after=lambda *_a, **_kw: SimpleNamespace(outcome="OBSERVED", page=None),
    )
    binding = SimpleNamespace(
        pid=os.getpid(),
        thread=threading.current_thread(),
        state="ACTIVE",
        next_idle_read=0.0,
        strategy=object(),
        host=host,
        api=api,
        stream=stream,
        policy=SimpleNamespace(route="CTP___FUTURE"),
        feeds={"f1": feed},
        local_deferred=[],
        timeout=5.0,
        limit=10,
    )
    notice = SimpleNamespace(
        restored=None,
        fault=None,
        armed=None,
        receipt=None,
        orders={key: order},
    )
    broker = _DummyBroker(binding, notice)
    return broker, binding, order, host, key


def test_pending_or_unknown_execution_parent_stays_fail_closed():
    status = ExecutionRoutingStatus(
        routed=True,
        outcome=ExecutionRoutingOutcome.EXECUTION_LOCAL_RECEIPT,
        request_id="req-1",
        request_sha256="a" * 64,
        parent_ref="parent-1",
        configuration_id="cfg-1",
        execution_state=None,
    )
    broker, binding, order, host, key = _make_rig(status)
    broker._gateway_stream_next()
    assert order.status == order.Submitted
    assert not _bt_terminal(order)
    assert broker.finalized == []
    assert "reject:" + key not in host.local_order_notifications()
    assert binding.state == "EXECUTION_RECOVERY_PENDING"


def test_mismatched_rejected_execution_parent_stays_fail_closed():
    status = ExecutionRoutingStatus(
        routed=True,
        outcome=ExecutionRoutingOutcome.EXECUTION_LOCAL_RECEIPT,
        request_id="req-WRONG",
        request_sha256="a" * 64,
        parent_ref="parent-1",
        configuration_id="cfg-1",
        execution_state="REJECTED",
    )
    broker, binding, order, host, key = _make_rig(status)
    broker._gateway_stream_next()
    assert order.status == order.Submitted
    assert broker.finalized == []
    assert "reject:" + key not in host.local_order_notifications()
    assert binding.state == "EXECUTION_RECOVERY_PENDING"


def test_definitively_rejected_execution_parent_finalizes_and_unblocks():
    status = ExecutionRoutingStatus(
        routed=True,
        outcome=ExecutionRoutingOutcome.EXECUTION_LOCAL_RECEIPT,
        request_id="req-1",
        request_sha256="a" * 64,
        parent_ref="parent-1",
        configuration_id="cfg-1",
        execution_state="REJECTED",
    )
    broker, binding, order, host, key = _make_rig(status)

    # First pass detects authoritative REJECTED status and finalizes the order locally
    broker._gateway_stream_next()
    assert order.status == order.Rejected
    assert _bt_terminal(order)
    assert broker.finalized == [(key, "EXECUTION_PARENT_REJECTED")]
    assert "reject:" + key in host.local_order_notifications()
    assert binding.state == "WAITING_NOTIFICATIONS"

    # Next pass sees terminal order + local reject notice and returns binding to ACTIVE
    binding.next_idle_read = 0.0
    broker._gateway_stream_next()
    assert binding.state == "ACTIVE"


def test_real_v8_host_persists_and_reloads_execution_parent_rejection_with_risk_codes(tmp_path):
    """Real GatewayPendingHost v8 must persist & reload EXECUTION_PARENT rejections
    (including lowercase Risk codes like risk_self_trade), while still rejecting
    PENDING routes and malformed codes fail-closed."""
    from decimal import Decimal

    import pytest
    from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_py._contracts.models import OrderRequest, OrderType, Side
    from bt_api_py.execution_routing import ExecutionPreparedRoute
    from bt_api_py.gateway_direct_client import GatewayClientRoute, build_gateway_order_intent

    from backtrader.live_state import StrategyStateDir
    from backtrader.live_state.gateway_pending import GatewayPendingHost

    strat_dir = tmp_path / "strat"
    strat_dir.mkdir()
    state = StrategyStateDir.initialize(strat_dir)
    binding = GatewayCommandBinding("journal-1", "account-1", "strategy-1", "principal-1")
    route = GatewayClientRoute(
        "broker.direct_write",
        "service-1",
        "instance-1",
        "scope-1",
        WireScope("simnow:sim", account_ref="account-1", strategy_ref="strategy-1", run_id="run-1"),
        WireIdentity(WireRole.STRATEGY_CLIENT, "principal-1", "strategy-1"),
    )

    host = GatewayPendingHost.upgrade_for_gateway(strat_dir, state.strategy_uuid, binding)
    host = GatewayPendingHost.upgrade_for_cancellation(strat_dir, state.strategy_uuid, binding)
    host = GatewayPendingHost.upgrade_for_execution(
        strat_dir, state.strategy_uuid, binding, consumer_ref="gexec:" + "a" * 64
    )
    host = GatewayPendingHost.upgrade_for_order_state(
        strat_dir, state.strategy_uuid, binding, max_order_snapshot_bytes=1024 * 1024, lock_timeout=5.0
    )
    host.upgrade_for_local_notifications()
    host.upgrade_for_risk_routing()
    host.upgrade_for_execution_routing()

    def make_snapshot(req_key: str, bt_ref: int, status: int) -> dict:
        return {
            "schema_version": 1,
            "state": {
                "codec": 1,
                "feeds": {},
                "orders": {req_key: {"ref": bt_ref, "status": status}},
                "positions": {},
                "trades": {},
                "groups": {},
            },
        }

    def save_bound_parent(req_key: str, local_seq: int, bt_ref: int):
        req = OrderRequest(
            symbol="rb2701",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            account_id="account-1",
            client_order_id=req_key,
            price=Decimal("3050"),
            idempotency_key=req_key,
        )
        intent = build_gateway_order_intent(binding, route, req, ttl_seconds=30)
        host.save_execution_routing_intent(
            intent,
            local_seq=local_seq,
            bt_ref=bt_ref,
            snapshot=make_snapshot(req_key, bt_ref, 1),
            configuration_id="cfg-exec-1",
        )
        prepared = ExecutionPreparedRoute(
            account=intent.binding.account_scope,
            strategy=intent.binding.strategy_scope,
            request_key=req_key,
            intent_digest=intent.digest,
            request_id=f"req-{local_seq}",
            request_sha256="b" * 64,
            configuration_id="cfg-exec-1",
            execution_domain_ref=intent.route.scope.execution_domain_ref,
            parent_ref=f"parent-{local_seq}",
        )
        assert host.bind_execution_parent_route(req_key, prepared) is True
        return intent

    # 1. Lowercase Risk refusal code ("risk_self_trade") persists and reloads cleanly
    save_bound_parent("bt-k-1", local_seq=1, bt_ref=11)
    notice1 = host.save_rejected_order_notification(
        "bt-k-1", bt_ref=11, snapshot=make_snapshot("bt-k-1", 11, 8), code="risk_self_trade"
    )
    assert notice1["status"] == "pending"
    assert notice1["code"] == "risk_self_trade"

    # 2. Uppercase Execution refusal code ("EXECUTION_PARENT_REJECTED") also persists cleanly
    save_bound_parent("bt-k-2", local_seq=2, bt_ref=12)
    notice2 = host.save_rejected_order_notification(
        "bt-k-2", bt_ref=12, snapshot=make_snapshot("bt-k-2", 12, 8), code="EXECUTION_PARENT_REJECTED"
    )
    assert notice2["code"] == "EXECUTION_PARENT_REJECTED"

    # 3. Malformed rejection codes remain strictly rejected
    save_bound_parent("bt-k-3", local_seq=3, bt_ref=13)
    with pytest.raises(ValueError, match="GATEWAY_LOCAL_NOTIFICATION_INVALID"):
        host.save_rejected_order_notification(
            "bt-k-3", bt_ref=13, snapshot=make_snapshot("bt-k-3", 13, 8), code="bad code!"
        )

    # 4. Unbound PENDING route still fails closed (must use reject_execution_before_submit)
    req4 = OrderRequest(
        symbol="rb2701",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        account_id="account-1",
        client_order_id="bt-k-4",
        price=Decimal("3050"),
        idempotency_key="bt-k-4",
    )
    intent4 = build_gateway_order_intent(binding, route, req4, ttl_seconds=30)
    host.save_execution_routing_intent(
        intent4,
        local_seq=4,
        bt_ref=14,
        snapshot=make_snapshot("bt-k-4", 14, 1),
        configuration_id="cfg-exec-1",
    )
    with pytest.raises(ValueError, match="GATEWAY_EXECUTION_ROUTE_NOT_ALLOWED"):
        host.save_rejected_order_notification(
            "bt-k-4", bt_ref=14, snapshot=make_snapshot("bt-k-4", 14, 8), code="risk_self_trade"
        )

    # 5. Fresh host reload from disk validates v8 order_state + execution_routes cleanly
    reloaded = GatewayPendingHost(strat_dir, state.strategy_uuid, binding)
    notices = reloaded.local_order_notifications()
    assert notices["reject:bt-k-1"]["code"] == "risk_self_trade"
    assert notices["reject:bt-k-2"]["code"] == "EXECUTION_PARENT_REJECTED"
    assert reloaded.load_execution_route("bt-k-1").kind == "EXECUTION_PARENT"
    assert reloaded.load_execution_route("bt-k-2").kind == "EXECUTION_PARENT"

    # 6. Cross-process restart: restored order gets a new bt_ref (e.g. 1 != original 13),
    #    and finalizing its EXECUTION_PARENT rejection must still persist & reload cleanly.
    notice3 = reloaded.save_rejected_order_notification(
        "bt-k-3", bt_ref=1, snapshot=make_snapshot("bt-k-3", 1, 8), code="EXECUTION_PARENT_REJECTED"
    )
    assert notice3["bt_ref"] == 1
    reloaded2 = GatewayPendingHost(strat_dir, state.strategy_uuid, binding)
    assert reloaded2.local_order_notifications()["reject:bt-k-3"]["bt_ref"] == 1
    assert reloaded2.load_execution_route("bt-k-3").kind == "EXECUTION_PARENT"

