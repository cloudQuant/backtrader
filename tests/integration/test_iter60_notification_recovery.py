"""Re-verification G3: standard notify_order/notify_trade survive a process crash.

A ledger-bound direct Strategy on a real ``BtApiBroker`` (fake Store, SDK
strategy ledger, local owner fence) binds notification recovery. A spawned
child process trades and is killed (``os._exit``) at one crash window; a new
process binds the same recovery directory and deployment and must receive
exactly the journaled, unacknowledged notifications again, in journal order,
through the same callbacks, as read-only ``RecoveredOrder``/``RecoveredTrade``
records carrying the original stable ``notification_id``.
INTEGRATION_SIM: local SQLite files and test-owned processes only.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import sqlite3
import sys
from pathlib import Path

import pytest

pytest.importorskip("bt_api_py.strategy_ledger")

import backtrader as bt  # noqa: E402

_HERE = Path(__file__).resolve().parent


def _helpers():
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    import test_iter60_direct_strategy_account_book as helpers

    return helpers


def _stack(directory, *refs):
    """A ledger-bound Broker without provider dispatch (no owner fence needed).

    Orders are placed with ``_place``: reserved in the ledger and queued
    through ``BtApiBroker.notify`` exactly as a Store-confirmed order would be.
    """

    t = _helpers()
    ledger = t._ledger(directory / "ledger.sqlite3")
    broker = t.BtApiBroker(store=t._Store())
    data = t._data()
    strategies = t._strategies(broker, data, *refs)
    for strategy in strategies:
        broker.bind_direct_strategy_ledger(strategy, ledger, unreconciled=True)
    return t, ledger, broker, data, strategies


def _place(broker, ledger, strategy, data, size, *, price=1500.0):
    """Reserve a closing SELL in the ledger and report it Accepted by the Broker."""

    from decimal import Decimal

    from bt_api_py.strategy_ledger import LedgerIntent

    t = _helpers()
    order = bt.SellOrder(
        owner=strategy, data=data, size=size, price=price, exectype=bt.Order.Limit,
        simulated=False,
    )
    intent_id = f"intent-{strategy.p.strategy_ref}-{order.ref}"
    ledger.reserve(
        LedgerIntent(intent_id, strategy.p.strategy_ref, t.INSTRUMENT, "SELL", Decimal(size),
                     Decimal(str(price)))
    )
    order.addinfo(strategy_ledger_intent_id=intent_id)
    order.addcomminfo(broker.getcommissioninfo(data))
    order.submit(broker)
    broker.orders[order.ref] = order
    order.accept(broker)
    broker.notify(order)
    return order


def _cycle(broker, strategies):
    """What Cerebro does each step: hand queued notifications to their owners."""

    while True:
        notification = broker.get_notification()
        if notification is None:
            break
        notification.owner._addnotification(notification, quicknotify=False)
    for strategy in strategies:
        strategy._notify()


def _log(path, line):
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(line + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _child(directory, stage):
    directory = Path(directory)
    t, ledger, broker, data, (a, b) = _stack(directory, "strategy-a", "strategy-b")
    t._seed(ledger, "seed-a", "strategy-a", "2")
    t._seed(ledger, "seed-b", "strategy-b", "3")
    side_effects = directory / "side_effects.txt"

    def notify_order(self, order):
        _log(side_effects, f"{self.p.strategy_ref}:order:{order.getstatusname()}:{order.notification_id}")
        if stage == "in_order_callback" and order.status == order.Completed:
            os._exit(71)

    def notify_trade(self, trade):
        _log(side_effects, f"{self.p.strategy_ref}:trade:{trade.status}:{trade.notification_id}")
        if stage == "in_trade_callback":
            os._exit(72)

    type(a).notify_order = notify_order
    type(a).notify_trade = notify_trade
    broker.bind_strategy_notification_recovery(a, directory / "recovery-a", deployment_ref="dep")
    broker.bind_strategy_notification_recovery(b, directory / "recovery-b", deployment_ref="dep")
    recovery_a = broker._strategy_notification_recovery[id(a)]
    if stage == "after_callback_before_ack":
        real_ack = recovery_a.journal.acknowledge

        def ack_then_die(event_id):
            for entry in recovery_a.journal.pending():
                if entry.event_id == event_id and b'"status_name":"Completed"' in entry.payload:
                    os._exit(73)  # the callback returned, the ACK never happened
            return real_ack(event_id)

        recovery_a.journal.acknowledge = ack_then_die
    if stage == "before_delivery":
        order_a = _place(broker, ledger, a, data, 2)
        t._fill(broker, order_a, 2)
        # Journaled by the Broker and the Strategy, never delivered.
        while (notification := broker.get_notification()) is not None:
            notification.owner._addnotification(notification, quicknotify=False)
        os._exit(75)
    order_a = _place(broker, ledger, a, data, 2)
    order_b = _place(broker, ledger, b, data, 3)
    t._fill(broker, order_a, 2)
    t._fill(broker, order_b, 3)
    _cycle(broker, [a, b])
    os._exit(74)  # every callback returned and was acknowledged


def _run(directory, stage):
    context = multiprocessing.get_context("spawn")
    child = context.Process(target=_child, args=(str(directory), stage))
    child.start()
    child.join(timeout=60)
    try:
        return child.exitcode
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)


def _restart(directory):
    t, ledger, broker, data, (a, b) = _stack(directory, "strategy-a", "strategy-b")
    received = {"strategy-a": [], "strategy-b": []}

    def notify_order(self, order):
        received[self.p.strategy_ref].append(order)

    def notify_trade(self, trade):
        received[self.p.strategy_ref].append(trade)

    type(a).notify_order = notify_order
    type(a).notify_trade = notify_trade
    counts = (
        broker.bind_strategy_notification_recovery(a, directory / "recovery-a", deployment_ref="dep"),
        broker.bind_strategy_notification_recovery(b, directory / "recovery-b", deployment_ref="dep"),
    )
    return t, ledger, broker, received, counts, (a, b)


def _recovered_order():
    from backtrader.brokers._btapi_strategy_events import RecoveredOrder

    return RecoveredOrder


def _shape(items):
    return [
        ("order", item.getstatusname()) if isinstance(item, _recovered_order()) else ("trade", item.status)
        for item in items
    ]


@pytest.mark.parametrize(
    ("stage", "exit_code", "expected_a"),
    [
        # Crash inside the Completed callback: it and the trades after it again.
        ("in_order_callback", 71, [("order", "Completed"), ("trade", 1)]),
        # Callback returned, ACK lost: delivered again (at least once).
        ("after_callback_before_ack", 73, [("order", "Completed"), ("trade", 1)]),
        # Crash inside the trade callback: the trade is delivered again.
        ("in_trade_callback", 72, [("trade", 1)]),
        # Journaled, never delivered: all of it, in journal order.
        (
            "before_delivery",
            75,
            [("order", "Submitted"), ("order", "Accepted"), ("order", "Completed"), ("trade", 1)],
        ),
        # Everything acknowledged: nothing is delivered twice.
        ("after_ack", 74, []),
    ],
)
def test_standard_notifications_survive_a_process_crash(tmp_path, stage, exit_code, expected_a):
    assert _run(tmp_path, stage) == exit_code
    side_effects_path = tmp_path / "side_effects.txt"
    side_effects = (
        side_effects_path.read_text(encoding="utf-8").splitlines()
        if side_effects_path.exists()
        else []
    )
    t, ledger, broker, received, counts, (a, b) = _restart(tmp_path)
    try:
        replayed = received["strategy-a"]
        assert all(getattr(item, "recovered", False) for item in replayed)
        assert all(item.replayed is True for item in replayed)
        shape = _shape(replayed)
        # A Submitted notification exists only on some paths; the crash windows
        # after it pin the order of everything that follows it.
        assert [s for s in shape if s != ("order", "Submitted")] == [
            s for s in expected_a if s != ("order", "Submitted")
        ], (shape, side_effects)
        assert counts[0] == len(shape)
        # The replay carries the id the crashed process delivered with.
        delivered_ids = {line.rsplit(":", 1)[1] for line in side_effects}
        for item in replayed:
            if stage in ("in_order_callback", "after_callback_before_ack", "in_trade_callback"):
                if item is replayed[0]:
                    assert item.notification_id in delivered_ids
        # Own scope only: B may get its own unacknowledged notifications back
        # (the child died before B's turn), never A's (A closed 2, B closed 3).
        for item in received["strategy-b"]:
            assert getattr(item, "recovered", False)
            if isinstance(item, _recovered_order()):
                assert item.size == -3.0
        if stage == "after_ack":
            assert received["strategy-b"] == []
        for item in replayed:
            if isinstance(item, _recovered_order()):
                assert item.issell() and item.info["strategy_ledger_intent_id"]
                if item.status == item.Completed:
                    assert item.executed.size == -2.0 and item.executed.price == 1500.0
            else:
                assert item.data_name == t.INSTRUMENT and item.isopen and item.size == -2.0
                assert item.order_notification_id
        # The replay was acknowledged: a third start delivers nothing.
        broker.close_strategy_notification_recovery()
        again = t.BtApiBroker(store=t._Store())
        (a2,) = t._strategies(again, t._data(), "strategy-a")
        again.bind_direct_strategy_ledger(a2, ledger, unreconciled=True)
        assert (
            again.bind_strategy_notification_recovery(
                a2, tmp_path / "recovery-a", deployment_ref="dep"
            )
            == 0
        )
        again.close_strategy_notification_recovery()
    finally:
        ledger.close()


def test_live_notifications_are_acknowledged_only_after_the_callback(tmp_path):
    t, ledger, broker, data, (a,) = _stack(tmp_path, "strategy-a")
    t._seed(ledger, "seed-a", "strategy-a", "2")
    seen = []

    def notify_order(self, order):
        if order.status == order.Completed:
            raise RuntimeError("strategy bug")
        seen.append((order.getstatusname(), order.notification_id, order.replayed))

    type(a).notify_order = notify_order
    try:
        broker.bind_strategy_notification_recovery(a, tmp_path / "rec", deployment_ref="dep")
        recovery = broker._strategy_notification_recovery[id(a)]
        order = _place(broker, ledger, a, data, 2)
        t._fill(broker, order, 2)
        with pytest.raises(RuntimeError, match="strategy bug"):
            _cycle(broker, [a])
        pending = recovery.journal.pending()
        assert [b'"status_name":"Completed"' in e.payload for e in pending][0] is True
        assert [kind for kind in (e.kind for e in pending)] == ["order", "trade"]
        assert [name for name, _id, _r in seen][-1] == "Accepted"
        assert all(nid and replayed is False for _n, nid, replayed in seen)
        assert broker.strategy_notification_recovery_state(a) == "ACTIVE"
    finally:
        broker.close_strategy_notification_recovery()
        ledger.close()


def test_notification_ids_are_stable_and_derive_from_ledger_identity(tmp_path):
    t, ledger, broker, data, (a,) = _stack(tmp_path, "strategy-a")
    t._seed(ledger, "seed-a", "strategy-a", "2")
    seen = []
    type(a).notify_order = lambda self, order: seen.append(order)
    try:
        broker.bind_strategy_notification_recovery(a, tmp_path / "rec", deployment_ref="dep")
        recovery = broker._strategy_notification_recovery[id(a)]
        order = _place(broker, ledger, a, data, 2)
        t._fill(broker, order, 2)
        _cycle(broker, [a])
        completed = [o for o in seen if o.status == o.Completed][0]
        # The same fact journaled again (e.g. a provider redelivery after a
        # restart) maps to the same id and is flagged as delivered before.
        assert recovery.journal_order(order) == (completed.notification_id, True)
        assert completed.info["notification_id"] == completed.notification_id
        assert len({o.notification_id for o in seen}) == len(seen)
        assert recovery.journal.stats()["pending"] == 0
    finally:
        broker.close_strategy_notification_recovery()
        ledger.close()


def test_other_ledger_generation_requires_an_explicit_resync(tmp_path):
    t, ledger, broker, data, (a,) = _stack(tmp_path, "strategy-a")
    t._seed(ledger, "seed-a", "strategy-a", "2")
    type(a).notify_order = lambda self, order: None
    broker.bind_strategy_notification_recovery(a, tmp_path / "rec", deployment_ref="dep")
    order = _place(broker, ledger, a, data, 2)
    t._fill(broker, order, 2)  # journaled, never delivered
    broker.close_strategy_notification_recovery()
    ledger.close()
    # The ledger is rebuilt: a new journal generation.
    (tmp_path / "ledger.sqlite3").unlink()
    from backtrader.brokers._btapi_strategy_events import StrategyNotificationRecoveryError

    t, ledger, broker, data, (a,) = _stack(tmp_path, "strategy-a")
    replayed = []
    type(a).notify_order = lambda self, order: replayed.append(order)
    try:
        with pytest.raises(StrategyNotificationRecoveryError) as info:
            broker.bind_strategy_notification_recovery(a, tmp_path / "rec", deployment_ref="dep")
        assert info.value.code == "RESYNC_REQUIRED"
        assert broker.strategy_notification_recovery_state(a) == "RESYNC_REQUIRED"
        assert replayed == []
        assert "notify_order" not in a.__dict__
        assert broker.bind_strategy_notification_recovery(
            a, tmp_path / "rec", deployment_ref="dep", resync=True
        ) == 0
        assert replayed == [] and broker.strategy_notification_recovery_state(a) == "ACTIVE"
        aside = list((tmp_path / "rec").glob("*.resync-1"))
        assert len(aside) == 1  # kept for audit, never deleted
        with sqlite3.connect(aside[0]) as db:
            assert db.execute("SELECT COUNT(*) FROM journal_notification WHERE acked=0").fetchone()[0] > 0
    finally:
        broker.close_strategy_notification_recovery()
        ledger.close()


def test_binding_requires_a_scope_and_the_same_deployment(tmp_path):
    t, ledger, broker, data, (a,) = _stack(tmp_path, "strategy-a")
    from backtrader.brokers._btapi_strategy_events import StrategyNotificationRecoveryError

    try:
        (stranger,) = t._strategies(broker, data, "strategy-z")
        with pytest.raises(ValueError, match="explicit generation"):
            broker.bind_strategy_notification_recovery(
                stranger, tmp_path / "rec-z", deployment_ref="dep"
            )
        broker.bind_strategy_notification_recovery(a, tmp_path / "rec", deployment_ref="dep")
        with pytest.raises(ValueError, match="already has"):
            broker.bind_strategy_notification_recovery(a, tmp_path / "rec", deployment_ref="dep")
        broker.close_strategy_notification_recovery()
        other = t.BtApiBroker(store=t._Store())
        (a2,) = t._strategies(other, data, "strategy-a")
        other.bind_direct_strategy_ledger(a2, ledger, unreconciled=True)
        with pytest.raises(StrategyNotificationRecoveryError) as info:
            other.bind_strategy_notification_recovery(a2, tmp_path / "rec", deployment_ref="dep-2")
        assert info.value.code == "SCOPE_MISMATCH"
    finally:
        ledger.close()


def test_explicit_generation_journals_a_non_ledger_strategy(tmp_path):
    """Gateway-style path: no direct ledger, the upstream generation is explicit."""

    t = _helpers()
    broker = t.BtApiBroker(store=t._Store())
    data = t._data()
    (a,) = t._strategies(broker, data, "strategy-g")
    seen = []
    type(a).notify_order = lambda self, order: seen.append(order)
    try:
        broker.bind_strategy_notification_recovery(
            a, tmp_path / "rec", deployment_ref="dep", generation="gateway-gen-1"
        )
        order = bt.SellOrder(
            owner=a, data=data, size=1, price=1500.0, exectype=bt.Order.Limit, simulated=False
        )
        order.addinfo(client_order_id="cid-1")
        order.addcomminfo(broker.getcommissioninfo(data))
        order.submit(broker)
        broker.notify(order)
        _cycle(broker, [a])
        assert seen and seen[0].notification_id and seen[0].replayed is False
        recovery = broker._strategy_notification_recovery[id(a)]
        assert recovery.journal.stats()["pending"] == 0
        payload = json.loads(recovery.journal._db.execute(
            "SELECT payload FROM journal_notification"
        ).fetchone()[0])
        assert payload["identity"] == "client_order_id:cid-1"
        broker.close_strategy_notification_recovery()
        broker2 = t.BtApiBroker(store=t._Store())
        (a2,) = t._strategies(broker2, data, "strategy-g")
        from backtrader.brokers._btapi_strategy_events import StrategyNotificationRecoveryError

        with pytest.raises(StrategyNotificationRecoveryError, match="RESYNC_REQUIRED"):
            broker2.bind_strategy_notification_recovery(
                a2, tmp_path / "rec", deployment_ref="dep", generation="gateway-gen-2"
            )
    finally:
        broker.close_strategy_notification_recovery()


if __name__ == "__main__":  # spawn safety on macOS
    pass
