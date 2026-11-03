"""Re-verification G3: standard notify_order/notify_trade survive a process crash.

A ledger-bound direct Strategy on a real ``BtApiBroker`` (fake Store, SDK
strategy ledger, local owner fence) binds notification recovery. A spawned
child process trades and is killed (``os._exit``) at one crash window; a new
process binds the same recovery directory and deployment and must receive
exactly the journaled, unacknowledged notifications again, through the same
callbacks, as read-only ``RecoveredOrder``/``RecoveredTrade`` records.
INTEGRATION_SIM: local SQLite files and test-owned processes only.
"""

from __future__ import annotations

import multiprocessing
import os
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
    t = _helpers()
    ledger = t._ledger(directory / "ledger.sqlite3")
    store = t._Store()
    broker = t.BtApiBroker(store=store)
    owner = t._owner(broker, directory / "owner.sqlite3")
    data = t._data()
    strategies = t._strategies(broker, data, *refs)
    for strategy in strategies:
        broker.bind_direct_strategy_ledger(strategy, ledger, unreconciled=True)
    return t, ledger, broker, owner, data, strategies


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
    t, ledger, broker, _owner, data, (a, b) = _stack(directory, "strategy-a", "strategy-b")
    t._seed(ledger, "seed-a", "strategy-a", "2")
    t._seed(ledger, "seed-b", "strategy-b", "3")
    side_effects = directory / "side_effects.txt"

    def notify_order(self, order):
        _log(side_effects, f"{self.p.strategy_ref}:order:{order.getstatusname()}")
        if stage == "in_order_callback" and order.status == order.Completed:
            os._exit(71)

    def notify_trade(self, trade):
        _log(side_effects, f"{self.p.strategy_ref}:trade:{trade.status}")
        if stage == "in_trade_callback":
            os._exit(72)

    type(a).notify_order = notify_order
    type(a).notify_trade = notify_trade
    broker.bind_strategy_notification_recovery(a, directory / "recovery-a", deployment_ref="dep")
    broker.bind_strategy_notification_recovery(b, directory / "recovery-b", deployment_ref="dep")
    recovery_a = broker._strategy_notification_recovery[id(a)]
    if stage == "after_callback_before_ack":
        real_ack = recovery_a.orders.acknowledge

        def ack_then_die(event_id):
            pending = recovery_a.orders.pending()
            if pending is not None and b'"status_name":"Completed"' in pending.payload:
                os._exit(73)  # the callback returned, the ACK never happened
            return real_ack(event_id)

        recovery_a.orders.acknowledge = ack_then_die
    order_a = a.close(data=data, price=1500.0, exectype=bt.Order.Limit)
    order_b = b.close(data=data, price=1500.0, exectype=bt.Order.Limit)
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
    t, ledger, broker, owner, data, (a, b) = _stack(directory, "strategy-a", "strategy-b")
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
    return t, ledger, broker, owner, received, counts, (a, b)


@pytest.mark.parametrize(
    ("stage", "exit_code", "expected_a"),
    [
        # Crash inside the Completed callback: it is delivered again.
        ("in_order_callback", 71, [("order", "Completed")]),
        # Callback returned, ACK lost: delivered again (at least once).
        ("after_callback_before_ack", 73, [("order", "Completed")]),
        # Crash inside the trade callback: the trade is delivered again.
        ("in_trade_callback", 72, [("trade", None)]),
        # Everything acknowledged: nothing is delivered twice.
        ("after_ack", 74, []),
    ],
)
def test_standard_notifications_survive_a_process_crash(tmp_path, stage, exit_code, expected_a):
    assert _run(tmp_path, stage) == exit_code
    side_effects = (tmp_path / "side_effects.txt").read_text(encoding="utf-8").splitlines()
    t, ledger, broker, owner, received, counts, (a, b) = _restart(tmp_path)
    try:
        replayed = received["strategy-a"]
        assert all(getattr(item, "recovered", False) for item in replayed)
        shape = [
            ("order", item.getstatusname()) if isinstance(item, _recovered_order()) else ("trade", None)
            for item in replayed
        ]
        assert shape == expected_a, (shape, side_effects)
        assert counts[0] == len(expected_a)
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
                assert item.status == item.Completed and item.issell()
                assert item.executed.size == -2.0 and item.executed.price == 1500.0
                assert item.info["recovery_event_id"]
            else:
                assert item.ref > 0 and item.data_name == t.INSTRUMENT
        # The replay was acknowledged: a third start delivers nothing.
        broker.close_strategy_notification_recovery()
        again = t.BtApiBroker(store=t._Store())
        (a2,) = t._strategies(again, t._data(), "strategy-a")
        handoff = t._owner(again, tmp_path / "owner2.sqlite3")
        again.bind_direct_strategy_ledger(a2, ledger, unreconciled=True)
        assert (
            again.bind_strategy_notification_recovery(
                a2, tmp_path / "recovery-a", deployment_ref="dep"
            )
            == 0
        )
        again.close_strategy_notification_recovery()
        handoff.close()
    finally:
        owner.close()
        ledger.close()


def _recovered_order():
    from backtrader.brokers._btapi_strategy_events import RecoveredOrder

    return RecoveredOrder


def test_live_notifications_are_acknowledged_only_after_the_callback(tmp_path):
    t, ledger, broker, owner, data, (a,) = _stack(tmp_path, "strategy-a")
    t._seed(ledger, "seed-a", "strategy-a", "2")
    seen = []

    def notify_order(self, order):
        if order.status == order.Completed:
            raise RuntimeError("strategy bug")
        seen.append(order.getstatusname())

    type(a).notify_order = notify_order
    try:
        broker.bind_strategy_notification_recovery(a, tmp_path / "rec", deployment_ref="dep")
        recovery = broker._strategy_notification_recovery[id(a)]
        order = a.close(data=data, price=1500.0, exectype=bt.Order.Limit)
        t._fill(broker, order, 2)
        with pytest.raises(RuntimeError, match="strategy bug"):
            _cycle(broker, [a])
        pending = recovery.orders.pending()
        assert pending is not None and b'"status_name":"Completed"' in pending.payload
        assert seen == ["Accepted"]
    finally:
        broker.close_strategy_notification_recovery()
        owner.close()
        ledger.close()


def test_binding_requires_a_ledger_bound_strategy_and_the_same_deployment(tmp_path):
    t, ledger, broker, owner, data, (a,) = _stack(tmp_path, "strategy-a")
    try:
        (stranger,) = t._strategies(broker, data, "strategy-z")
        with pytest.raises(ValueError, match="bound to the ledger"):
            broker.bind_strategy_notification_recovery(
                stranger, tmp_path / "rec-z", deployment_ref="dep"
            )
        broker.bind_strategy_notification_recovery(a, tmp_path / "rec", deployment_ref="dep")
        with pytest.raises(ValueError, match="already has"):
            broker.bind_strategy_notification_recovery(a, tmp_path / "rec", deployment_ref="dep")
        broker.close_strategy_notification_recovery()
        other = t.BtApiBroker(store=t._Store())
        (a2,) = t._strategies(other, data, "strategy-a")
        handoff = t._owner(other, tmp_path / "owner2.sqlite3")
        other.bind_direct_strategy_ledger(a2, ledger, unreconciled=True)
        with pytest.raises(Exception) as info:  # an existing outbox of another deployment
            other.bind_strategy_notification_recovery(a2, tmp_path / "rec", deployment_ref="dep-2")
        assert getattr(info.value, "code", "") or "deployment" in str(info.value)
        handoff.close()
    finally:
        owner.close()
        ledger.close()


if __name__ == "__main__":  # spawn safety on macOS
    pass
