"""R28 explicitly bound Gateway notification transactions on real BT objects."""

import itertools

import backtrader as bt
import pandas as pd
import pytest

from backtrader.live_state.gateway_pending import GatewayPendingHost
from backtrader.metabase import OwnerContext
from tests.unit.live_state.test_gateway_execution_checkpoint import make_event, page, ready
from tests.unit.live_state.test_gateway_pending import inputs
from tests.unit.live_state.conftest import state, strategy_dir


class Strategy(bt.Strategy):
    def notify_order(self, order):
        self.events.append(("order", order.notification_id, order.replayed, order.executed.size))
        if self.fail == "order":
            raise RuntimeError("callback")

    def notify_trade(self, trade):
        self.events.append(("trade", trade.notification_id, trade.replayed, trade.size))

    def notify_fee_correction(self, order, trade, delta, currency):
        self.events.append(("fee", order.notification_id, order.replayed, delta))
        if self.fail == "fee":
            raise RuntimeError("callback")


def framework(quick=False):
    frame = pd.DataFrame(
        {"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.0], "volume": [1.0]},
        index=pd.to_datetime(["2026-11-03 09:00"]),
    )
    data = bt.feeds.PandasData(dataname=frame, name="rb")
    data._start()
    assert data.load()
    broker = bt.brokers.BtApiBroker()
    cerebro = bt.Cerebro(quicknotify=quick)
    cerebro.setbroker(broker)
    cerebro.stcount = itertools.count()
    cerebro.datas, cerebro.datasbyname = [data], {"rb": data}
    with OwnerContext.set_owner(cerebro):
        strategy = Strategy.__new__(Strategy)
    strategy.datas, strategy.data = [data], data
    strategy._tradehistoryon, strategy._quicknotify = True, quick
    strategy.events, strategy.fail = [], None
    return data, broker, strategy


def setup(ready, quick=False):
    host, binding, consumer = ready
    data, broker, strategy = framework(quick)
    order = bt.BuyOrder(owner=strategy, data=data, size=2, price=10.0, exectype=bt.Order.Limit)
    order.addcomminfo(broker.getcommissioninfo(data))
    order.submit(broker)
    order.accept(broker)
    broker.bind_gateway_notification_state(
        strategy, host=host, data_by_ref={"rb": data}, orders_by_key={"key-a": order}
    )
    events = [make_event(host), make_event(host, 8, fact="f" * 64, trade="c" * 64)]
    host.ingest_execution_page(
        page(binding, consumer, events), expected_revision=0, after_sequence=0
    )
    return host, data, broker, strategy, order


def fill(broker, strategy, order, quick=False):
    pos = broker.positions["rb"]
    pos.update(1, 10)
    order.execute(order.data.datetime[0], 1, 10, 0, 0, 0, 1, 10, 0.1, 0, 0, 1, 10)
    notice = order.clone()
    strategy._addnotification(notice, quicknotify=quick)
    return notice


@pytest.mark.parametrize("quick", [False, True])
def test_real_fill_and_confirmed_checkpoint(ready, quick):
    host, data, broker, strategy, order = setup(ready, quick)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order, quick)
    if not quick:
        strategy._notify()
    assert [event[0] for event in strategy.events] == ["order", "trade"]
    assert all(len(event[1]) == 64 and not event[2] for event in strategy.events)
    assert host.load_execution_notification_batch()["status"] == "confirmed"
    assert broker.assert_gateway_notifications_ackable(strategy, 3).applied_sequence == 3
    strategy.clear()
    broker.arm_gateway_notification_state(strategy, 8)


def test_callback_failure_replay_and_restore(state, ready):
    host, data, broker, strategy, order = setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    strategy.fail = "order"
    with pytest.raises(RuntimeError, match="callback"):
        strategy._notify()
    first = strategy.events[0]
    with pytest.raises(ValueError, match="ACK_BLOCKED"):
        broker.assert_gateway_notifications_ackable(strategy, 3)
    strategy.fail = None
    broker.replay_gateway_notifications(strategy)
    assert strategy.events[1][:3] == ("order", first[1], True)
    assert host.load_execution_notification_batch()["status"] == "confirmed"
    new_data, new_broker, new_strategy = framework()
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, host._binding)
    new_broker.bind_gateway_notification_state(
        new_strategy, host=reopened, data_by_ref={"rb": new_data}, orders_by_key={}
    )
    new_broker.restore_gateway_notification_state(new_strategy)
    assert not new_strategy.events and not new_strategy._orderspending
    assert len(new_strategy._orders) == 1


def test_pending_reopen_restores_real_objects_without_refill(state, ready):
    host, data, broker, strategy, order = setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    strategy.fail = "order"
    with pytest.raises(RuntimeError):
        strategy._notify()
    original_id = strategy.events[0][1]
    new_data, new_broker, new_strategy = framework()
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, host._binding)
    new_broker.bind_gateway_notification_state(
        new_strategy, host=reopened, data_by_ref={"rb": new_data}, orders_by_key={}
    )
    new_broker.restore_gateway_notification_state(new_strategy)
    new_broker.replay_gateway_notifications(new_strategy)
    assert new_strategy.events[0][:3] == ("order", original_id, True)
    assert [event[0] for event in new_strategy.events] == ["order", "trade"]
    restored_trade = next(iter(next(iter(new_strategy._trades.values())).values()))[0]
    assert restored_trade.size == 1 and restored_trade.commission == 0.1
    assert new_broker.positions["rb"].size == 1


def prepare_fee(ready):
    host, data, broker, strategy, order = setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    strategy._notify()
    strategy.clear()
    broker.arm_gateway_notification_state(strategy, 8)
    order.info["fee_corrections"] = ({"sequence": 1, "delta": "0.25", "currency": "CNY"},)
    return host, data, broker, strategy, order


@pytest.mark.parametrize("failure", ["before", "after", "callback"])
def test_fee_replay_without_reapplying(ready, monkeypatch, failure):
    from backtrader.live_state import pending as pending_module

    host, data, broker, strategy, order = prepare_fee(ready)
    original = pending_module.atomic_write_json

    def fail_before(*args):
        raise OSError("before")

    def fail_after(*args):
        original(*args)
        raise OSError("after")

    if failure in ("before", "after"):
        monkeypatch.setattr(
            pending_module, "atomic_write_json", fail_before if failure == "before" else fail_after
        )
    else:
        strategy.fail = "fee"
    notice = order.clone()
    with pytest.raises((OSError, RuntimeError)):
        strategy._addnotification(notice)
    trade = strategy._order_last_trade()[order.ref]
    assert trade.commission == 0.35
    with pytest.raises(ValueError):
        broker.assert_gateway_notifications_ackable(strategy, 8)
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    strategy.fail = None
    broker.replay_gateway_notifications(strategy)
    assert trade.commission == 0.35
    assert [event[0] for event in strategy.events[-2:]] == ["fee", "order"]
    assert all(event[2] for event in strategy.events[-2:])
    assert host.load_execution_notification_batch()["status"] == "confirmed"


def test_fee_preflight_does_not_apply_mixed_or_multiple(ready):
    host, data, broker, strategy, order = prepare_fee(ready)
    order.info["fee_corrections"] = (
        {"sequence": 1, "delta": "0.25", "currency": "CNY"},
        {"sequence": 2, "delta": "0.5", "currency": "CNY"},
    )
    trade = strategy._order_last_trade()[order.ref]
    with pytest.raises(ValueError, match="FEE_INVALID"):
        strategy._addnotification(order.clone())
    assert trade.commission == 0.1
    assert strategy.__dict__.get("_fee_corrections_applied", {}).get(order.ref, 0) == 0
    previous_callbacks = list(strategy.events)
    with pytest.raises(ValueError, match="FAULT"):
        strategy._notify()
    with pytest.raises(ValueError, match="ACK_BLOCKED"):
        broker.assert_gateway_notifications_ackable(strategy, 3)
    assert strategy.events == previous_callbacks
    assert host.load_execution_checkpoint().applied_sequence == 3


def test_fee_pending_reopen_restores_and_replays_without_reapply(state, ready):
    host, data, broker, strategy, order = prepare_fee(ready)
    strategy.fail = "fee"
    with pytest.raises(RuntimeError, match="callback"):
        strategy._addnotification(order.clone())
    first_id = strategy.events[-1][1]
    assert host.load_execution_notification_batch()["status"] == "pending"
    new_data, new_broker, new_strategy = framework()
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, host._binding)
    new_broker.bind_gateway_notification_state(
        new_strategy, host=reopened, data_by_ref={"rb": new_data}, orders_by_key={}
    )
    new_broker.restore_gateway_notification_state(new_strategy)
    new_broker.replay_gateway_notifications(new_strategy)
    assert [event[0] for event in new_strategy.events] == ["fee", "order"]
    assert new_strategy.events[0][:3] == ("fee", first_id, True)
    trade = next(iter(next(iter(new_strategy._trades.values())).values()))[0]
    assert trade.commission == 0.35 and trade.size == 1
    assert new_strategy.__dict__["_fee_corrections_applied"]
    assert reopened.load_execution_notification_batch()["status"] == "confirmed"


def test_fee_callback_mutation_rejected_before_order_notification(ready):
    host, data, broker, strategy, order = prepare_fee(ready)

    def mutate(notice, trade, delta, currency):
        notice.info["mutated"] = True

    strategy.notify_fee_correction = mutate
    strategy._addnotification(order.clone())
    with pytest.raises(ValueError, match="PROJECTION_CONFLICT"):
        strategy._notify()
    assert host.load_execution_notification_batch()["status"] == "pending"


@pytest.mark.parametrize("construct", [False, True])
def test_cold_broker_import_does_not_attempt_sdk_imports(construct):
    import os
    import pathlib
    import subprocess
    import sys

    source_root = str(pathlib.Path(bt.__file__).resolve().parent.parent)
    script = """
import importlib.abc
import pathlib
import sys
sys.path.insert(0, sys.argv[1])
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0].startswith("bt_api_"):
            raise AssertionError("unexpected optional SDK import: " + fullname)
sys.meta_path.insert(0, Block())
import backtrader
from backtrader.brokers.btapibroker import BtApiBroker
assert pathlib.Path(backtrader.__file__).resolve().parent.parent == pathlib.Path(sys.argv[1]).resolve()
if sys.argv[2] == "construct":
    assert BtApiBroker().store is None
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, source_root, "construct" if construct else "import"],
        text=True,
        capture_output=True,
        cwd=os.path.dirname(source_root),
    )
    assert result.returncode == 0, result.stderr


def test_startup_evidence_that_was_not_provided_equals_the_sdk_summary():
    # The broker answers "no evidence" itself so that it needs no SDK import; the SDK owns the
    # shape, so the two must stay equal.
    from bt_api_py.startup_recovery import normalise_startup_account_state as sdk_summary

    broker_summary = bt.brokers.BtApiBroker._normalise_startup_account_state
    assert broker_summary(None) == sdk_summary(None)
    supplied = dict.fromkeys(
        ("nonzero_position_record_count", "gross_position_lots", "active_orders_count"), 0
    )
    assert broker_summary(supplied) == sdk_summary(supplied)
    assert broker_summary(supplied)["provided"] is True


def test_fee_then_order_confirmation(ready):
    host, data, broker, strategy, order = prepare_fee(ready)
    strategy._addnotification(order.clone())
    assert strategy.events[-1][0] == "fee"
    assert host.load_execution_notification_batch()["status"] == "pending"
    with pytest.raises(ValueError, match="ACK_BLOCKED"):
        broker.assert_gateway_notifications_ackable(strategy, 8)
    strategy._notify()
    assert [event[0] for event in strategy.events[-2:]] == ["fee", "order"]
    assert strategy.events[-2][1] != strategy.events[-1][1]
    assert host.load_execution_notification_batch()["status"] == "confirmed"


def test_binding_and_receipt_scope_are_rejected(ready):
    host, data, broker, strategy, order = setup(ready)
    with pytest.raises(ValueError, match="SEQUENCE"):
        broker.arm_gateway_notification_state(strategy, 8)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    with pytest.raises(ValueError, match="RECEIPT"):
        broker._gateway_confirm_notifications(strategy, object())
    other_data, other_broker, other_strategy = framework()
    with pytest.raises(ValueError, match="NOT_BOUND"):
        broker._gateway_confirm_notifications(other_strategy, object())
    strategy._notify()
    assert host.load_execution_notification_batch()["status"] == "confirmed"


def test_unbound_broker_retains_notification_behavior():
    data, broker, strategy = framework()
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addcomminfo(broker.getcommissioninfo(data))
    order.submit(broker)
    order.accept(broker)
    strategy._addnotification(order.clone())
    strategy._notify()
    assert strategy.events == [("order", None, False, 0)]


def test_failure_before_candidate_blocks_reuse_until_restart(ready, monkeypatch):
    host, data, broker, strategy, order = setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)

    def unavailable(*args):
        raise ValueError("codec unavailable")

    monkeypatch.setattr(broker, "_gateway_graph", unavailable)
    with pytest.raises(ValueError, match="codec unavailable"):
        strategy._notify()
    assert not strategy.events and host.load_execution_checkpoint().applied_sequence == 0
    with pytest.raises(ValueError, match="RESTART_REQUIRED"):
        broker.replay_gateway_notifications(strategy)
    with pytest.raises(ValueError, match="BUSY"):
        broker.arm_gateway_notification_state(strategy, 3)


def test_reentrant_replay_cannot_confirm_before_callback_returns(ready):
    host, data, broker, strategy, order = setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    strategy.fail = "order"
    with pytest.raises(RuntimeError):
        strategy._notify()
    strategy.fail = None

    def reenter(order):
        strategy._notify()

    strategy.notify_order = reenter
    with pytest.raises(ValueError, match="BUSY"):
        broker.replay_gateway_notifications(strategy)
    assert host.load_execution_notification_batch()["status"] == "pending"


def test_replay_refuses_modified_framework_objects(ready):
    host, data, broker, strategy, order = setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    notice = fill(broker, strategy, order)

    def modify_then_fail(notified):
        notified.executed.size = 99
        raise RuntimeError("mutated")

    strategy.notify_order = modify_then_fail
    with pytest.raises(RuntimeError, match="mutated"):
        strategy._notify()
    with pytest.raises(ValueError, match="PROJECTION_CONFLICT"):
        broker.replay_gateway_notifications(strategy)
    assert host.load_execution_notification_batch()["status"] == "pending"
    with pytest.raises(ValueError, match="RESTART_REQUIRED"):
        broker.replay_gateway_notifications(strategy)


def test_invalid_restore_metadata_installs_no_partial_state(state, ready):
    import json

    host, data, broker, strategy, order = setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    strategy.fail = "order"
    with pytest.raises(RuntimeError):
        strategy._notify()
    with open(state.pending.path, encoding="utf-8") as source:
        raw = json.load(source)
    raw["gateway"]["execution"]["projection"]["state"]["_gateway_strategy"]["orders_pending"] = []
    with open(state.pending.path, "w", encoding="utf-8") as target:
        json.dump(raw, target)
    new_data, new_broker, new_strategy = framework()
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, host._binding)
    new_broker.bind_gateway_notification_state(
        new_strategy, host=reopened, data_by_ref={"rb": new_data}, orders_by_key={}
    )
    with pytest.raises(ValueError, match="RESTORE_INVALID"):
        new_broker.restore_gateway_notification_state(new_strategy)
    assert not new_strategy._orders and not new_strategy._orderspending and not new_strategy._trades
    assert not new_broker.orders and not new_broker.positions


@pytest.mark.parametrize("phase", ["order", "fee"])
def test_first_callback_cannot_reenter_replay_or_confirm(ready, phase):
    if phase == "fee":
        host, data, broker, strategy, order = prepare_fee(ready)
    else:
        host, data, broker, strategy, order = setup(ready)
        broker.arm_gateway_notification_state(strategy, 3)
        fill(broker, strategy, order)

    def reenter(*args):
        with pytest.raises(ValueError, match="BUSY"):
            broker.replay_gateway_notifications(strategy)
        raise RuntimeError("outer callback failed")

    if phase == "fee":
        strategy.notify_fee_correction = reenter
        with pytest.raises(RuntimeError, match="outer callback"):
            strategy._addnotification(order.clone())
    else:
        strategy.notify_order = reenter
        with pytest.raises(RuntimeError, match="outer callback"):
            strategy._notify()
    assert host.load_execution_notification_batch()["status"] == "pending"
    strategy.notify_order = lambda order: None
    strategy.notify_fee_correction = lambda *args: None
    broker.replay_gateway_notifications(strategy)
    assert host.load_execution_notification_batch()["status"] == "confirmed"


def test_direct_selected_and_later_session_attachment_rejected(ready):
    from types import SimpleNamespace
    from backtrader.service.service_execution_session import ServiceExecutionSession
    from backtrader.service.managed_runtime_host import ManagedRuntimeCerebroSession

    host, binding, consumer = ready
    data, broker, strategy = framework()
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    broker.store = SimpleNamespace(direct_write_mode=True)
    with pytest.raises(ValueError, match="MODE_CONFLICT"):
        broker.bind_gateway_notification_state(
            strategy, host=host, data_by_ref={"rb": data}, orders_by_key={"key-a": order}
        )
    broker.store = None
    broker.bind_gateway_notification_state(
        strategy, host=host, data_by_ref={"rb": data}, orders_by_key={"key-a": order}
    )
    service = object.__new__(ServiceExecutionSession)
    managed = object.__new__(ManagedRuntimeCerebroSession)
    with pytest.raises(ValueError, match="MODE_CONFLICT"):
        broker.attach_service_execution_session(service)
    with pytest.raises(ValueError, match="MODE_CONFLICT"):
        broker.attach_managed_runtime_session(managed)
    assert broker._service_execution_session is None and broker._managed_runtime_session is None
    broker.store = SimpleNamespace(direct_write_mode=True)
    with pytest.raises(ValueError, match="MODE_OR_POSITION_CONFLICT"):
        broker.start()


def test_later_foreign_order_on_same_feed_blocks_commit_and_ack(ready):
    host, data, broker, strategy, order = setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    _, _, other = framework()
    foreign = bt.BuyOrder(owner=other, data=data, size=1, price=10, exectype=bt.Order.Limit)
    broker.orders[foreign.ref] = foreign
    with pytest.raises(ValueError, match="MODE_OR_POSITION_CONFLICT"):
        strategy._notify()
    assert not strategy.events and host.load_execution_checkpoint().applied_sequence == 0
    del broker.orders[foreign.ref]
    with pytest.raises(ValueError, match="ACK_BLOCKED"):
        broker.assert_gateway_notifications_ackable(strategy, 3)
    with pytest.raises(ValueError, match="FAULT"):
        strategy._notify()


def test_foreign_order_during_callback_blocks_confirmation(ready):
    host, data, broker, strategy, order = setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    _, _, other = framework()
    foreign = bt.BuyOrder(owner=other, data=data, size=1, price=10, exectype=bt.Order.Limit)

    def add_foreign(notice):
        broker.orders[foreign.ref] = foreign

    strategy.notify_order = add_foreign
    with pytest.raises(ValueError, match="MODE_OR_POSITION_CONFLICT"):
        strategy._notify()
    assert host.load_execution_notification_batch()["status"] == "pending"
    del broker.orders[foreign.ref]
    with pytest.raises(ValueError, match="ACK_BLOCKED"):
        broker.assert_gateway_notifications_ackable(strategy, 3)
    with pytest.raises(ValueError, match="RESTART_REQUIRED"):
        broker.replay_gateway_notifications(strategy)


def test_caught_nested_fee_preflight_failure_still_blocks_outer_confirmation(ready):
    host, data, broker, strategy, order = setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    notice = fill(broker, strategy, order)

    def nested(notified):
        notice.info["fee_corrections"] = ({"sequence": 1, "delta": "0.2", "currency": "CNY"},)
        with pytest.raises(ValueError, match="FAULT"):
            strategy._apply_fee_corrections(notice)

    strategy.notify_order = nested
    with pytest.raises(ValueError, match="FAULT"):
        strategy._notify()
    assert host.load_execution_notification_batch()["status"] == "pending"
    with pytest.raises(ValueError, match="ACK_BLOCKED"):
        broker.assert_gateway_notifications_ackable(strategy, 3)


def test_thread_identity_must_match_even_if_ident_reused(ready, monkeypatch):
    import threading
    import backtrader.brokers._btapi_gateway_notifications as notifications

    host, data, broker, strategy, order = setup(ready)
    ident = threading.get_ident()
    distinct_thread = threading.Thread()
    monkeypatch.setattr(notifications.threading, "get_ident", lambda: ident)
    monkeypatch.setattr(notifications.threading, "current_thread", lambda: distinct_thread)
    with pytest.raises(ValueError, match="SCOPE"):
        broker.arm_gateway_notification_state(strategy, 3)
    assert host.load_execution_checkpoint().applied_sequence == 0


@pytest.mark.parametrize("phase", ["normal", "quick", "fee"])
def test_reentrant_addnotification_is_rejected_before_framework_mutation(ready, phase):
    if phase == "fee":
        host, data, broker, strategy, order = prepare_fee(ready)
    else:
        host, data, broker, strategy, order = setup(ready, quick=(phase == "quick"))
        broker.arm_gateway_notification_state(strategy, 3)

    nested_order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    nested_order.addcomminfo(broker.getcommissioninfo(data))
    nested_order.submit(broker)
    nested_order.accept(broker)
    nested_order.execute(data.datetime[0], 1, 10, 0, 0, 0, 1, 10, 0.1, 0, 0, 1, 10)
    nested = nested_order.clone()
    nested.info["fee_corrections"] = ({"sequence": 1, "delta": "0.2", "currency": "CNY"},)
    attempts = []

    def snapshot():
        trades = [
            trade
            for groups in strategy._trades.values()
            for items in groups.values()
            for trade in items
        ]
        return (
            tuple(map(id, strategy._orderspending)),
            tuple(map(id, strategy._tradespending)),
            tuple((id(trade), trade.size, trade.commission, trade.pnlcomm) for trade in trades),
            dict(strategy.__dict__.get("_fee_corrections_applied", {})),
        )

    def reenter(*args):
        before = snapshot()
        with pytest.raises(ValueError, match="BUSY"):
            strategy._addnotification(nested, quicknotify=(phase == "quick"))
        assert snapshot() == before
        attempts.append(True)

    if phase == "fee":
        strategy.notify_fee_correction = reenter
        strategy._addnotification(order.clone())
        strategy._notify()
    else:
        strategy.notify_order = reenter
        fill(broker, strategy, order, quick=(phase == "quick"))
        if phase == "normal":
            strategy._notify()
    assert attempts == [True]
    assert nested.notification_id is None
    batch = host.load_execution_notification_batch()
    assert batch["status"] == "confirmed"
    assert [item["kind"] for item in batch["notifications"]] == (
        ["fee", "order"] if phase == "fee" else ["order", "trade"]
    )


def test_unarmed_notification_rejected_before_strategy_mutation(ready):
    host, data, broker, strategy, order = setup(ready)
    notice = order.clone()
    with pytest.raises(ValueError, match="NOT_ARMED"):
        strategy._addnotification(notice)
    assert not strategy._orderspending and not strategy._trades
    assert host.load_execution_checkpoint().applied_sequence == 0


def test_uncaught_reentrant_entry_keeps_original_batch_pending(ready):
    host, data, broker, strategy, order = setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    nested = order.clone()
    fill(broker, strategy, order)
    original_pending = tuple(map(id, strategy._orderspending))
    strategy.notify_order = lambda notified: strategy._addnotification(nested)
    with pytest.raises(ValueError, match="BUSY"):
        strategy._notify()
    assert tuple(map(id, strategy._orderspending)) == original_pending
    assert host.load_execution_notification_batch()["status"] == "pending"
    strategy.notify_order = lambda notified: None
    broker.replay_gateway_notifications(strategy)
    assert host.load_execution_notification_batch()["status"] == "confirmed"
