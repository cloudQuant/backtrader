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
