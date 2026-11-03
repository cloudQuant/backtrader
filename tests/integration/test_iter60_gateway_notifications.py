"""Iteration 60 R2-C: Gateway-mode standard notifications from execution events.

The Gateway account owner's producer publishes typed terminal-order and fill
observations into the Gateway account journal; the SDK execution consumer
reads them; ``BtApiBroker`` projects them through its direct-mode order/fill
path. Checked here (INTEGRATION_SIM, local SQLite, in-process co-located
service): direct/Gateway parity of ``notify_order``/``notify_trade`` and the
ledger, fact-id dedupe, the commit-before-ACK order, deferred fills and
in-process restarts. Real subprocess crash windows are in
``test_iter60_gateway_notifications_crash.py``.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("bt_api_py.service_execution_event_consumer")
pytest.importorskip("bt_api_gateway.execution_event_publisher")

_HERE = Path(__file__).resolve().parent


def _support():
    import sys

    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    import iter60_gateway_execution_support as support

    return support


def _run_direct(directory, *, per_event=True, script=None):
    t = _support()
    s = t.stack(directory, "direct")
    order = t.place(s)
    t.cycle(s)
    rows = t.direct_rows(order, script or t.SCRIPT)
    if per_event:
        for row in rows:
            s.store.rows.append(row)
            s.broker.next()  # the Store drain
            t.cycle(s)
    else:
        s.store.rows.extend(rows)
        s.broker.next()
        t.cycle(s)
    return s


def _run_gateway(directory, *, per_event=True, script=None):
    t = _support()
    s = t.stack(directory, "gateway")
    t.place(s)
    t.cycle(s)
    items = t.observations(script or t.SCRIPT)
    if per_event:
        for item in items:
            t.publish(directory / "gateway.sqlite3", [item])
            s.broker.next()  # the R2-C hook polls the execution stream
            t.cycle(s)
    else:
        t.publish(directory / "gateway.sqlite3", items)
        s.broker.poll_gateway_execution_events()
        t.cycle(s)
    return s


def _ids_free(received):
    return [(kind, status, replayed) for kind, status, _id, replayed in received]


@pytest.mark.parametrize("per_event", [True, False])
def test_direct_and_gateway_give_identical_notifications_and_ledger(tmp_path, per_event):
    t = _support()
    direct = _run_direct(tmp_path / "direct", per_event=per_event)
    gateway = _run_gateway(tmp_path / "gateway", per_event=per_event)
    try:
        assert direct.received, "the direct reference produced notifications"
        assert ("order", "Completed") in t.shapes(direct.received)
        assert any(kind == "trade" for kind, *_ in direct.received)
        assert _ids_free(gateway.received) == _ids_free(direct.received)
        assert t.position(gateway) == t.position(direct) == Decimal("0")
        assert gateway.ledger.intent_state("intent-sa-1") == "FILLED"
        assert direct.ledger.intent_state("intent-sa-1") == "FILLED"
        state = gateway.broker.gateway_execution_events_state(gateway.a)
        assert state["state"] == "ACTIVE" and state["applied"] == 5
        checkpoint = gateway.broker._gateway_execution_bindings[id(gateway.a)].consumer.checkpoint()
        assert checkpoint.cursor == 5 and not checkpoint.pending_ack
    finally:
        for s in (direct, gateway):
            s.broker.close_gateway_execution_events()
            s.broker.close_strategy_notification_recovery()
            s.ledger.close()


def test_a_fill_reported_before_its_order_is_deferred_durably_with_parity(tmp_path):
    t = _support()
    script = (t.SCRIPT[1], t.SCRIPT[0], *t.SCRIPT[2:])  # first fill before any order row
    direct = _run_direct(tmp_path / "direct", per_event=False, script=script)
    gateway = _run_gateway(tmp_path / "gateway", per_event=False, script=script)
    try:
        assert _ids_free(gateway.received) == _ids_free(direct.received)
        assert t.position(gateway) == t.position(direct) == Decimal("0")
        state = gateway.broker.gateway_execution_events_state(gateway.a)
        assert state["deferred"] == 1 and state["applied"] == 5
    finally:
        for s in (direct, gateway):
            s.broker.close_gateway_execution_events()
            s.broker.close_strategy_notification_recovery()
            s.ledger.close()


def test_republished_and_redelivered_facts_have_no_second_effect(tmp_path):
    t = _support()
    s = _run_gateway(tmp_path, per_event=False)
    try:
        before = list(s.received)
        # The provider redelivers every fact (new observation times are irrelevant).
        result = t.publish(tmp_path / "gateway.sqlite3", t.observations())
        assert result.appended == 0 and result.duplicates == 5
        assert s.broker.poll_gateway_execution_events() == 0
        t.cycle(s)
        assert s.received == before and t.position(s) == Decimal("0")
    finally:
        s.broker.close_gateway_execution_events()
        s.broker.close_strategy_notification_recovery()
        s.ledger.close()


def test_restart_rebuilds_the_open_order_and_keeps_projecting(tmp_path):
    t = _support()
    s = t.stack(tmp_path, "gateway")
    t.place(s)
    t.cycle(s)
    items = t.observations()
    t.publish(tmp_path / "gateway.sqlite3", items[:2])  # open + first fill
    s.broker.poll_gateway_execution_events()
    t.cycle(s)
    first = list(s.received)
    s.broker.close_gateway_execution_events()
    s.broker.close_strategy_notification_recovery()
    s.ledger.close()

    t.publish(tmp_path / "gateway.sqlite3", items[2:])
    again = t.stack(tmp_path, "gateway")
    try:
        assert again.replayed == 0  # everything was acknowledged
        assert again.rebuilt == 1  # the partially filled order
        rebuilt = next(iter(again.broker.orders.values()))
        assert rebuilt.executed.size == -1.0 and rebuilt.info["gateway_rehydrated"] is True
        again.broker.poll_gateway_execution_events()
        t.cycle(again)
        statuses = [status for kind, status, *_ in again.received if kind == "order"]
        # The re-reported Partial (same state, journaled by the earlier
        # instance and acknowledged) is not delivered again; Completed is live.
        assert "Partial" not in statuses and statuses[0] == "Completed"
        assert again.received[0][3] is False
        assert t.position(again) == Decimal("0")
        assert again.ledger.intent_state("intent-sa-1") == "FILLED"
        assert ("order", "Partial") in t.shapes(first)
    finally:
        again.broker.close_gateway_execution_events()
        again.broker.close_strategy_notification_recovery()
        again.ledger.close()


def test_events_of_unknown_orders_and_other_strategies_are_not_projected(tmp_path):
    t = _support()
    s = t.stack(tmp_path, "gateway")
    try:
        t.publish(
            tmp_path / "gateway.sqlite3",
            [
                t.order_obs("o-9", "sa-unknown", "open", "0", "1"),
                t.trade_obs("t-9", "o-9", "1"),
                t.order_obs("o-8", "sb-1", "filled", "1", "1"),  # strategy B's stream
            ],
        )
        assert s.broker.poll_gateway_execution_events() == 0
        t.cycle(s)
        assert s.received == []
        state = s.broker.gateway_execution_events_state(s.a)
        assert state["orphaned"] == 2 and state["applied"] == 0
        assert t.position(s) == Decimal("2")
    finally:
        s.broker.close_gateway_execution_events()
        s.broker.close_strategy_notification_recovery()
        s.ledger.close()


def test_binding_requires_notification_recovery_and_a_sdk_consumer(tmp_path):
    t = _support()
    book = t.ledger(tmp_path / "ledger.sqlite3")
    broker = t.BtApiBroker(store=t.SdkStore())
    (a,) = t.strategies(broker, t.data(), "strategy-a")
    reader = t.consumer(tmp_path / "gateway.sqlite3", tmp_path / "sdk", "strategy-a")
    try:
        with pytest.raises(ValueError, match="notification_recovery"):
            broker.bind_gateway_execution_events(a, reader, tmp_path / "projection")
        broker.bind_direct_strategy_ledger(a, book, unreconciled=True)
        broker.bind_strategy_notification_recovery(a, tmp_path / "recovery", deployment_ref="d")
        with pytest.raises(ValueError, match="ServiceExecutionEventConsumer"):
            broker.bind_gateway_execution_events(a, object(), tmp_path / "projection")
    finally:
        reader.close()
        broker.close_strategy_notification_recovery()
        book.close()


def test_a_consumer_failure_disables_trading_and_commits_nothing(tmp_path):
    t = _support()
    s = t.stack(tmp_path, "gateway")
    try:
        t.place(s)
        t.publish(tmp_path / "gateway.sqlite3", t.observations()[:1])
        binding = s.broker._gateway_execution_bindings[id(s.a)]
        real = binding.consumer._call_port

        def broken(operation, arguments):
            raise RuntimeError("transport down")

        binding.consumer._call_port = broken
        s.broker.next()  # never raises from next()
        assert s.broker._trading_enabled is False
        assert s.broker.gateway_execution_events_state(s.a)["state"] == "FAILED"
        binding.consumer._call_port = real
        assert binding.consumer.checkpoint().cursor == 0
    finally:
        s.broker.close_gateway_execution_events()
        s.broker.close_strategy_notification_recovery()
        s.ledger.close()
