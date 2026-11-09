"""Gateway recovery is resumed at the existing Strategy notification point."""

import pytest

import backtrader as bt
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.brokers.test_iter63_gateway_notification_delivery import (
    fill,
    framework,
    prepare_fee,
    setup,
)
from tests.unit.live_state.conftest import state, strategy_dir
from tests.unit.live_state.test_gateway_execution_checkpoint import ready
from tests.unit.live_state.test_gateway_pending import inputs
from tests.unit.test_iter63_gateway_strategy_notification_hooks import _fill, _setup


@pytest.mark.parametrize("result", [False, None, 1, "true"])
def test_only_exact_true_suppresses_ordinary_notification(result):
    strategy, broker, data = _setup(broker=bt.brokers.BackBroker())
    seen = []
    broker._gateway_resume_notifications = lambda owner, **kwargs: result
    strategy.notify_order = lambda order: seen.append("order")
    strategy.notify_trade = lambda trade: seen.append("trade")
    _fill(strategy, broker, data)
    strategy._notify()
    assert seen == ["order", "trade"]


def test_true_returns_before_any_notification_side_effect():
    strategy, broker, data = _setup(broker=bt.brokers.BackBroker())
    order = _fill(strategy, broker, data)
    seen = []
    broker._gateway_resume_notifications = lambda owner, **kwargs: seen.append((owner, kwargs)) or True
    strategy.notify_order = lambda order: pytest.fail("ordinary callback must not run")
    strategy._notify()
    assert seen == [(strategy, {"qorders": None, "qtrades": None})]
    assert strategy._orderspending == [order]


def test_no_binding_keeps_ordinary_real_notification():
    strategy, broker, data = _setup(broker=bt.brokers.BackBroker())
    seen = []
    strategy.notify_order = lambda order: seen.append("order")
    strategy.notify_trade = lambda trade: seen.append("trade")
    _fill(strategy, broker, data)
    strategy._notify()
    assert seen == ["order", "trade"]


@pytest.mark.parametrize("quick", [False, True])
def test_reopened_pending_resumes_once_without_refilling(state, ready, quick):
    host, data, broker, strategy, order = setup(ready, quick)
    broker.arm_gateway_notification_state(strategy, 3)
    strategy.fail = "order"
    with pytest.raises(RuntimeError, match="callback"):
        fill(broker, strategy, order, quick)
        if not quick:
            strategy._notify()
    first_id = strategy.events[0][1]
    new_data, new_broker, new_strategy = framework(quick)
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, host._binding)
    new_broker.bind_gateway_notification_state(
        new_strategy, host=reopened, data_by_ref={"rb": new_data}, orders_by_key={}
    )
    new_broker.restore_gateway_notification_state(new_strategy)
    restored_trade = next(iter(next(iter(new_strategy._trades.values())).values()))[0]
    before = (restored_trade.size, restored_trade.commission, new_broker.positions["rb"].size)
    new_strategy._notify()
    assert [event[0] for event in new_strategy.events] == ["order", "trade"]
    assert new_strategy.events[0][:3] == ("order", first_id, True)
    assert (restored_trade.size, restored_trade.commission, new_broker.positions["rb"].size) == before == (1, 0.1, 1)
    assert reopened.load_execution_notification_batch()["status"] == "confirmed"


def test_retry_callback_failure_retains_pending_until_later_notify(ready):
    host, data, broker, strategy, order = setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    strategy.fail = "order"
    with pytest.raises(RuntimeError, match="callback"):
        strategy._notify()
    with pytest.raises(RuntimeError, match="callback"):
        strategy._notify()
    assert host.load_execution_notification_batch()["status"] == "pending"
    strategy.fail = None
    strategy._notify()
    assert host.load_execution_notification_batch()["status"] == "confirmed"
    assert [event[2] for event in strategy.events] == [False, True, True, True]


def test_pending_rejects_new_quick_notifications(ready):
    host, data, broker, strategy, order = setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    strategy.fail = "order"
    with pytest.raises(RuntimeError, match="callback"):
        strategy._notify()
    before = list(strategy.events)
    with pytest.raises(ValueError, match="PENDING_NEW_NOTIFICATIONS"):
        strategy._notify(qorders=[order])
    assert strategy.events == before
    assert host.load_execution_notification_batch()["status"] == "pending"


def test_active_callback_reentry_is_rejected_without_losing_pending(ready):
    host, data, broker, strategy, order = setup(ready)
    broker.arm_gateway_notification_state(strategy, 3)
    fill(broker, strategy, order)
    strategy.notify_order = lambda order: strategy._notify()
    with pytest.raises(ValueError, match="BUSY"):
        strategy._notify()
    assert host.load_execution_notification_batch()["status"] == "pending"
    strategy.notify_order = lambda order: None
    strategy._notify()
    assert host.load_execution_notification_batch()["status"] == "confirmed"


def test_pending_fee_replays_existing_listener_path_without_reapplying(ready):
    host, data, broker, strategy, order = prepare_fee(ready)
    strategy.fail = "fee"
    with pytest.raises(RuntimeError, match="callback"):
        strategy._addnotification(order.clone())
    trade = strategy._order_last_trade()[order.ref]
    assert trade.commission == pytest.approx(0.35)
    first_id = strategy.events[-1][1]
    strategy.fail = None
    strategy._notify()
    assert [(event[0], event[2]) for event in strategy.events[-2:]] == [("fee", True), ("order", True)]
    assert strategy.events[-2][1] == first_id
    assert trade.commission == pytest.approx(0.35)
    assert host.load_execution_notification_batch()["status"] == "confirmed"
