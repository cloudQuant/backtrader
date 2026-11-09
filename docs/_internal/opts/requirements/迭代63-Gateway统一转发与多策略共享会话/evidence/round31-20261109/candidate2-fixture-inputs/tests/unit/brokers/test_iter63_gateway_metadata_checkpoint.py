"""Date enrichment checkpoint tests use real BT objects and a real pending host."""

from pathlib import Path

import backtrader as bt
import pytest

from backtrader.live_state import pending as pending_module
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.brokers.test_iter63_gateway_notification_delivery import (
    fill,
    framework,
    prepare_fee,
    setup,
)
from tests.unit.live_state.conftest import state, strategy_dir
from tests.unit.live_state.test_gateway_execution_checkpoint import make_event, page, ready
from tests.unit.live_state.test_gateway_pending import inputs
from tests.unit.live_state.test_iter63_gateway_trade_date_pending import dated


def prepare(ready):
    host, binding, consumer = ready
    data, broker, strategy = framework()
    order = bt.BuyOrder(owner=strategy, data=data, size=2, price=10, exectype=bt.Order.Limit)
    order.addcomminfo(broker.getcommissioninfo(data))
    order.submit(broker)
    order.accept(broker)
    broker.bind_gateway_notification_state(
        strategy, host=host, data_by_ref={"rb": data}, orders_by_key={"key-a": order}
    )
    original = make_event(host)
    enrichment = dated(original, 6)
    host.ingest_execution_page(
        page(binding, consumer, [original, enrichment]), expected_revision=0, after_sequence=0
    )
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    strategy._notify()
    strategy.clear()
    return host, binding, data, broker, strategy, order, original, enrichment


def reopen(state, host, binding):
    data, broker, strategy = framework()
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    broker.bind_gateway_notification_state(
        strategy, host=reopened, data_by_ref={"rb": data}, orders_by_key={}
    )
    checkpoint = broker.restore_gateway_notification_state(strategy)
    return reopened, data, broker, strategy, checkpoint


def test_date_only_projection_durable_without_second_trade_or_notification(state, ready):
    host, binding, data, broker, strategy, order, original, event = prepare(ready)
    before = (
        order.executed.size,
        order.executed.comm,
        broker.positions["rb"].size,
        [
            (trade.size, trade.commission, trade.pnl)
            for groups in strategy._trades.values()
            for trades in groups.values()
            for trade in trades
        ],
        list(strategy.events),
    )
    broker.arm_gateway_notification_state(strategy, 6)
    with pytest.raises(ValueError, match="ACK_BLOCKED"):
        broker.assert_gateway_notifications_ackable(strategy, 6)
    checkpoint = broker.commit_gateway_trade_metadata(strategy, 6)
    assert checkpoint.applied_sequence == 6 and host.load_execution_notification_batch() is None
    assert order.info["gateway_trade_dates"] == {original.observation.trade_key_digest: "20261107"}
    assert (
        order.executed.size,
        order.executed.comm,
        broker.positions["rb"].size,
        [
            (trade.size, trade.commission, trade.pnl)
            for groups in strategy._trades.values()
            for trades in groups.values()
            for trade in trades
        ],
        list(strategy.events),
    ) == before
    metadata = checkpoint.projection["state"]["_gateway_strategy"]
    assert metadata["version"] == 2 and metadata["delivery"] == "none"
    assert metadata["event_fact_digest"] == event.fact_digest
    assert broker.assert_gateway_notifications_ackable(strategy, 6) == checkpoint
    before_bytes = Path(state.pending.path).read_bytes()
    assert broker.commit_gateway_trade_metadata(strategy, 6) == checkpoint
    assert Path(state.pending.path).read_bytes() == before_bytes
    reopened, new_data, new_broker, new_strategy, restored = reopen(state, host, binding)
    assert restored == checkpoint and not new_strategy.events
    recovered = next(iter(new_broker.orders.values()))
    assert recovered.info["gateway_trade_dates"] == order.info["gateway_trade_dates"]
    assert recovered.executed.size == 1 and new_broker.positions["rb"].size == 1
    trade = next(iter(next(iter(new_strategy._trades.values())).values()))[0]
    assert trade.size == 1 and trade.commission == 0.1
    assert new_broker.assert_gateway_notifications_ackable(new_strategy, 6) == restored
    with pytest.raises(ValueError, match="NO_PENDING"):
        new_broker.replay_gateway_notifications(new_strategy)


def test_reject_wrong_sequence_normal_trade_cross_strategy_and_date_conflict(state, ready):
    host, binding, consumer = ready
    data, broker, strategy = framework()
    order = bt.BuyOrder(owner=strategy, data=data, size=2, price=10, exectype=bt.Order.Limit)
    order.addcomminfo(broker.getcommissioninfo(data))
    broker.bind_gateway_notification_state(
        strategy, host=host, data_by_ref={"rb": data}, orders_by_key={"key-a": order}
    )
    original = make_event(host)
    event = dated(original, 6)
    host.ingest_execution_page(
        page(binding, consumer, [original, event]), expected_revision=0, after_sequence=0
    )
    broker.arm_gateway_notification_state(strategy, 3)
    before = Path(state.pending.path).read_bytes()
    with pytest.raises(ValueError, match="METADATA_EVENT_INVALID"):
        broker.commit_gateway_trade_metadata(strategy, 3)
    with pytest.raises(ValueError, match="METADATA_SCOPE"):
        broker.commit_gateway_trade_metadata(strategy, 6)
    _, _, other = framework()
    with pytest.raises(ValueError, match="NOT_BOUND"):
        broker.commit_gateway_trade_metadata(other, 3)
    assert Path(state.pending.path).read_bytes() == before
    fill(broker, strategy, order)
    strategy._notify()
    strategy.clear()
    broker.arm_gateway_notification_state(strategy, 6)
    order.info["gateway_trade_dates"] = {event.observation.trade_key_digest: "20261108"}
    before = Path(state.pending.path).read_bytes()
    with pytest.raises(ValueError, match="DATE_CONFLICT"):
        broker.commit_gateway_trade_metadata(strategy, 6)
    assert Path(state.pending.path).read_bytes() == before


def test_unconfirmed_notification_blocks_date_checkpoint(ready):
    host, binding, consumer = ready
    data, broker, strategy = framework()
    order = bt.BuyOrder(owner=strategy, data=data, size=2, price=10, exectype=bt.Order.Limit)
    order.addcomminfo(broker.getcommissioninfo(data))
    broker.bind_gateway_notification_state(
        strategy, host=host, data_by_ref={"rb": data}, orders_by_key={"key-a": order}
    )
    original = make_event(host)
    host.ingest_execution_page(
        page(binding, consumer, [original, dated(original, 6)]),
        expected_revision=0,
        after_sequence=0,
    )
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    strategy.fail = "order"
    with pytest.raises(RuntimeError):
        strategy._notify()
    with pytest.raises(ValueError, match="BUSY"):
        broker.arm_gateway_notification_state(strategy, 6)
    with pytest.raises(ValueError, match="METADATA_SCOPE"):
        broker.commit_gateway_trade_metadata(strategy, 6)
    assert host.load_execution_notification_batch()["status"] == "pending"


@pytest.mark.parametrize("stage", ["before", "after"])
def test_write_failure_requires_reopen_and_never_acks_early(state, ready, monkeypatch, stage):
    host, binding, data, broker, strategy, order, original, event = prepare(ready)
    broker.arm_gateway_notification_state(strategy, 6)
    atomic = pending_module.atomic_write_json

    def fail(*args):
        if stage == "after":
            atomic(*args)
        raise OSError(stage)

    monkeypatch.setattr(pending_module, "atomic_write_json", fail)
    with pytest.raises(OSError, match=stage):
        broker.commit_gateway_trade_metadata(strategy, 6)
    with pytest.raises(ValueError, match="ACK_BLOCKED"):
        broker.assert_gateway_notifications_ackable(strategy, 6)
    with pytest.raises(ValueError, match="FAULT"):
        broker._gateway_resume_notifications(strategy)
    monkeypatch.setattr(pending_module, "atomic_write_json", atomic)
    reopened, new_data, new_broker, new_strategy, checkpoint = reopen(state, host, binding)
    if stage == "before":
        assert checkpoint.applied_sequence == 3
        with pytest.raises(ValueError, match="ACK_BLOCKED"):
            new_broker.assert_gateway_notifications_ackable(new_strategy, 6)
        new_broker.arm_gateway_notification_state(new_strategy, 6)
        checkpoint = new_broker.commit_gateway_trade_metadata(new_strategy, 6)
    assert checkpoint.applied_sequence == 6
    assert new_broker.assert_gateway_notifications_ackable(new_strategy, 6) == checkpoint
    assert not new_strategy.events


def test_repeated_known_date_event_advances_without_duplicate_economics(ready):
    host, binding, data, broker, strategy, order, original, event = prepare(ready)
    broker.arm_gateway_notification_state(strategy, 6)
    first = broker.commit_gateway_trade_metadata(strategy, 6)
    repeated = dated(original, 8, fact="9" * 64)
    host.ingest_execution_page(
        page(binding, first.consumer_ref, [repeated]),
        expected_revision=first.revision,
        after_sequence=6,
    )
    callbacks = list(strategy.events)
    broker.arm_gateway_notification_state(strategy, 8)
    with pytest.raises(ValueError, match="ACK_BLOCKED"):
        broker.assert_gateway_notifications_ackable(strategy, 6)
    second = broker.commit_gateway_trade_metadata(strategy, 8)
    assert second.applied_sequence == 8 and host.load_execution_notification_batch() is None
    assert order.info["gateway_trade_dates"] == {original.observation.trade_key_digest: "20261107"}
    assert order.executed.size == 1 and broker.positions["rb"].size == 1
    assert strategy.events == callbacks
    assert broker.assert_gateway_notifications_ackable(strategy, 8) == second


def test_revision_change_after_arm_rejects_without_mutating_order(ready):
    host, binding, data, broker, strategy, order, original, event = prepare(ready)
    broker.arm_gateway_notification_state(strategy, 6)
    checkpoint = host.load_execution_checkpoint()
    host.ingest_execution_page(
        page(binding, checkpoint.consumer_ref, [dated(original, 8, fact="9" * 64)]),
        expected_revision=checkpoint.revision,
        after_sequence=6,
    )
    with pytest.raises(ValueError, match="METADATA_SCOPE"):
        broker.commit_gateway_trade_metadata(strategy, 6)
    assert "gateway_trade_dates" not in order.info
    assert host.load_execution_checkpoint().applied_sequence == 3


@pytest.mark.parametrize(
    "field",
    ["version", "delivery", "through_sequence", "event_fact_digest", "fee", "orders_pending"],
)
def test_invalid_metadata_cannot_authorize_ack_or_partially_restore(state, ready, field):
    import json

    host, binding, data, broker, strategy, order, original, event = prepare(ready)
    broker.arm_gateway_notification_state(strategy, 6)
    broker.commit_gateway_trade_metadata(strategy, 6)
    path = Path(state.pending.path)
    raw = json.loads(path.read_bytes())
    metadata = raw["gateway"]["execution"]["projection"]["state"]["_gateway_strategy"]
    metadata[field] = {
        "version": 1,
        "delivery": "order",
        "through_sequence": 3,
        "event_fact_digest": "0" * 64,
        "fee": {},
        "orders_pending": ["x"],
    }[field]
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="ACK_BLOCKED"):
        broker.assert_gateway_notifications_ackable(strategy, 6)
    data2, broker2, strategy2 = framework()
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    broker2.bind_gateway_notification_state(
        strategy2, host=reopened, data_by_ref={"rb": data2}, orders_by_key={}
    )
    with pytest.raises(ValueError):
        broker2.restore_gateway_notification_state(strategy2)
    assert not strategy2._orders and not strategy2._trades and not broker2.orders
    assert path.read_bytes() == before


def test_v1_projection_without_batch_cannot_restore_or_ack(state, ready):
    import json

    host, binding, data, broker, strategy, order, original, event = prepare(ready)
    path = Path(state.pending.path)
    raw = json.loads(path.read_bytes())
    del raw["gateway"]["execution"]["projection"]["state"]["_gateway_notifications"]
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="ACK_BLOCKED"):
        broker.assert_gateway_notifications_ackable(strategy, 3)
    data2, broker2, strategy2 = framework()
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    broker2.bind_gateway_notification_state(
        strategy2, host=reopened, data_by_ref={"rb": data2}, orders_by_key={}
    )
    with pytest.raises(ValueError):
        broker2.restore_gateway_notification_state(strategy2)
    assert not strategy2._orders and not broker2.orders


def test_metadata_checkpoint_restores_in_fresh_interpreter(state, ready):
    import json
    import os
    import subprocess
    import sys

    host, binding, data, broker, strategy, order, original, event = prepare(ready)
    broker.arm_gateway_notification_state(strategy, 6)
    broker.commit_gateway_trade_metadata(strategy, 6)
    args = {
        "directory": str(state.strategy_dir),
        "uuid": state.strategy_uuid,
        "binding": {
            key: getattr(binding, key)
            for key in ("journal_id", "account_scope", "strategy_scope", "principal")
        },
        "trade_key": original.observation.trade_key_digest,
    }
    script = r"""
import json, sys
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.brokers.test_iter63_gateway_notification_delivery import framework
args = json.loads(sys.argv[1])
data, broker, strategy = framework()
host = GatewayPendingHost(args["directory"], args["uuid"], GatewayCommandBinding(**args["binding"]))
broker.bind_gateway_notification_state(strategy, host=host, data_by_ref={"rb": data}, orders_by_key={})
checkpoint = broker.restore_gateway_notification_state(strategy)
order = next(iter(broker.orders.values()))
assert order.info["gateway_trade_dates"] == {args["trade_key"]: "20261107"}
assert order.executed.size == 1 and broker.positions["rb"].size == 1
trade = next(iter(next(iter(strategy._trades.values())).values()))[0]
assert trade.size == 1 and trade.commission == 0.1 and strategy.events == []
assert broker.assert_gateway_notifications_ackable(strategy, 6) == checkpoint
"""
    root = Path(bt.__file__).resolve().parent.parent
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(args)],
        cwd=str(root),
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)


@pytest.mark.parametrize("quick", [False, True])
def test_resume_pending_from_strategy_notification_point(state, ready, quick):
    host, data, broker, strategy, order = setup(ready, quick=quick)
    broker.arm_gateway_notification_state(strategy, 3)
    strategy.fail = "order"
    with pytest.raises(RuntimeError, match="callback"):
        fill(broker, strategy, order, quick=quick)
        if not quick:
            strategy._notify()
    batch = host.load_execution_notification_batch()
    data2, broker2, strategy2 = framework(quick)
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, host._binding)
    broker2.bind_gateway_notification_state(
        strategy2, host=reopened, data_by_ref={"rb": data2}, orders_by_key={}
    )
    broker2.restore_gateway_notification_state(strategy2)
    with pytest.raises(ValueError, match="PENDING_NEW_NOTIFICATIONS"):
        broker2._gateway_resume_notifications(strategy2, qorders=[object()])
    assert not strategy2.events and reopened.load_execution_notification_batch() == batch
    strategy2._notify()
    assert [item[:3] for item in strategy2.events] == [
        (item["kind"], item["notification_id"], True) for item in batch["notifications"]
    ]
    assert reopened.load_execution_notification_batch()["status"] == "confirmed"
    assert broker2._gateway_resume_notifications(strategy2) is False


def test_resume_fee_before_order_using_original_listeners(ready):
    host, data, broker, strategy, order = prepare_fee(ready)
    strategy.fail = "fee"
    with pytest.raises(RuntimeError, match="callback"):
        strategy._addnotification(order.clone())
    batch = host.load_execution_notification_batch()
    commission = strategy._order_last_trade()[order.ref].commission
    strategy.fail = None
    strategy._notify()
    assert [item[:3] for item in strategy.events[-2:]] == [
        (item["kind"], item["notification_id"], True) for item in batch["notifications"]
    ]
    assert strategy._order_last_trade()[order.ref].commission == commission
    assert host.load_execution_notification_batch()["status"] == "confirmed"


def test_resume_callback_failure_keeps_pending_for_later_retry(ready):
    host, data, broker, strategy, order = setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    strategy.fail = "order"
    with pytest.raises(RuntimeError, match="callback"):
        strategy._notify()
    original_batch = host.load_execution_notification_batch()
    with pytest.raises(RuntimeError, match="callback"):
        strategy._notify()
    assert host.load_execution_notification_batch() == original_batch
    strategy.fail = None
    strategy._notify()
    assert host.load_execution_notification_batch()["status"] == "confirmed"


def test_metadata_only_rejects_normal_notification_before_mutation(ready):
    host, binding, data, broker, strategy, order, original, event = prepare(ready)
    broker.arm_gateway_notification_state(strategy, 6)
    notice = order.clone()
    before = (list(strategy._orderspending), list(strategy._tradespending), list(strategy.events))
    with pytest.raises(ValueError, match="METADATA_ONLY"):
        strategy._addnotification(notice)
    with pytest.raises(ValueError, match="METADATA_ONLY"):
        broker._gateway_prepare_notifications(strategy, [notice], [])
    binding_state = broker._gateway_binding(strategy, required=True)
    with pytest.raises(ValueError, match="METADATA_ONLY"):
        broker._gateway_commit(binding_state, [notice], [])
    assert (strategy._orderspending, strategy._tradespending, strategy.events) == before
    assert host.load_execution_checkpoint().applied_sequence == 3
    assert broker.commit_gateway_trade_metadata(strategy, 6).applied_sequence == 6


def test_metadata_only_rejects_fee_preflight(ready):
    host, binding, data, broker, strategy, order, original, event = prepare(ready)
    broker.arm_gateway_notification_state(strategy, 6)
    with pytest.raises(ValueError, match="METADATA_ONLY"):
        broker._gateway_validate_fee_notifications(
            strategy, order, ({"sequence": 1, "delta": 0.2, "currency": "CNY"},), 0
        )
    assert host.load_execution_checkpoint().applied_sequence == 3


def test_metadata_only_cannot_authorize_old_v1_notification_ack_or_restore(state, ready):
    host, binding, data, broker, strategy, order, original, event = prepare(ready)
    broker.arm_gateway_notification_state(strategy, 6)
    notice = order.clone()
    # Recreate an already persisted v1 batch using the old low-level host API.
    strategy._orderspending.append(notice)
    bound = broker._gateway_binding(strategy, required=True)
    snapshot, orders, _, order_keys, *_ = broker._gateway_graph(bound, [notice], [])
    item = broker._gateway_notice(bound, "order", 0, order_keys[0], {})
    orders[order_keys[0]].notification_id = item["notification_id"]
    snapshot, *_ = broker._gateway_graph(bound, [notice], [])
    checkpoint = host.commit_execution_notification_batch(
        6,
        snapshot,
        [item],
        expected_revision=bound.arm_checkpoint.revision,
        expected_applied_sequence=bound.arm_checkpoint.applied_sequence,
    )
    batch = host.load_execution_notification_batch()
    host.confirm_execution_notification_batch(
        batch["batch_id"],
        expected_revision=checkpoint.revision,
        expected_applied_sequence=6,
        expected_projection_digest=checkpoint.projection_digest,
    )
    with pytest.raises(ValueError, match="ACK_BLOCKED"):
        broker.assert_gateway_notifications_ackable(strategy, 6)
    new_data, new_broker, new_strategy = framework()
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    new_broker.bind_gateway_notification_state(
        new_strategy, host=reopened, data_by_ref={"rb": new_data}, orders_by_key={}
    )
    with pytest.raises(ValueError, match="RESTORE_INVALID"):
        new_broker.restore_gateway_notification_state(new_strategy)
    assert not new_strategy._orders and not new_strategy._trades and not new_broker.orders
