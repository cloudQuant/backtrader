"""Synthetic broker-port tests using real Strategy, Order and Trade paths."""

import itertools

import pandas as pd
import pytest

import backtrader as bt
from backtrader.lineiterator import LineIterator
from backtrader.metabase import OwnerContext
from backtrader.position import trade_key_from_order


class _Strategy(bt.Strategy):
    pass


class _Broker(bt.brokers.BackBroker):
    def __init__(self):
        super().__init__()
        self.events = []
        self.fail = None
        self.receipt = object()

    def record(self, label):
        self.events.append(label)
        if self.fail == label:
            raise RuntimeError(label)

    def _gateway_prepare_notifications(self, strategy, orders, trades):
        self.record("prepare")
        self.orders, self.trades = orders, trades
        self.actual_trade = strategy._trades[strategy.data][trade_key_from_order(orders[0])][-1] if orders and orders[0].executed.size else None
        if self.actual_trade is not None:
            assert self.actual_trade.size == 1
        return self.receipt

    def _gateway_validate_fee_notifications(self, strategy, order, corrections, done):
        self.record("validate")
        self.done = done

    def _gateway_prepare_fee_notification(self, strategy, order, trade, delta, currency, sequence):
        self.record("prepare_fee")
        assert trade.commission == pytest.approx(0.1 + delta)
        assert strategy.__dict__["_fee_corrections_applied"][order.ref] == sequence
        return self.receipt

    def _gateway_confirm_notifications(self, strategy, receipt):
        assert receipt is self.receipt
        self.record("confirm")

    def acknowledge_service_execution_recovery_receipt(self, receipt):
        self.record("managed_ack")

    def release_service_execution_recovery_receipt(self, receipt):
        self.record("managed_release")


class _Listener:
    def __init__(self, broker, prefix):
        self.broker, self.prefix = broker, prefix

    def _notify_order(self, order):
        self.broker.record(self.prefix + "_order")

    def _notify_trade(self, trade):
        self.broker.record(self.prefix + "_trade")

    def _notify_cashvalue(self, *args):
        pass

    def _notify_fund(self, *args):
        pass

    def notify_order(self, order):
        self.broker.record(self.prefix + "_order")

    def notify_trade(self, trade):
        self.broker.record(self.prefix + "_trade")

    def notify_fee_correction(self, order, trade, delta, currency):
        self.broker.record(self.prefix + "_fee")


def _setup(quick=False, broker=None):
    frame = pd.DataFrame({"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.0], "volume": [1.0]}, index=pd.to_datetime(["2026-11-03 09:00"]))
    data = bt.feeds.PandasData(dataname=frame, name="rb")
    data._start()
    assert data.load()
    broker = broker or _Broker()
    cerebro = bt.Cerebro(quicknotify=quick)
    cerebro.setbroker(broker)
    cerebro.stcount = itertools.count()
    cerebro.datas = [data]
    cerebro.datasbyname = {"rb": data}
    with OwnerContext.set_owner(cerebro):
        strategy = _Strategy.__new__(_Strategy)
    strategy.datas = [data]
    strategy.data = data
    strategy._tradehistoryon = False
    strategy._quicknotify = quick
    return strategy, broker, data


def _fill(strategy, broker, data, quick=False, managed=False):
    order = bt.BuyOrder(owner=strategy, data=data, size=2, price=10, exectype=bt.Order.Limit, simulated=False)
    order.addcomminfo(broker.getcommissioninfo(data))
    order.submit(broker)
    order.accept(broker)
    order.execute(data.datetime[0], 1, 10, 0, 0, 0, 1, 10, 0.1, 0, 0, 1, 10)
    if managed:
        order.info["service_execution_recovery_receipt_id"] = "receipt"
    notification = order.clone()
    strategy._addnotification(notification, quicknotify=quick)
    return notification


def _listeners(strategy, broker):
    analyzer, observer = _Listener(broker, "analyzer"), _Listener(broker, "observer")
    strategy._all_analyzers_cache = [analyzer]
    strategy.analyzers.append(analyzer, name="test_analyzer")
    strategy._lineiterators[LineIterator.ObsType] = [observer]
    strategy.stats = [observer]
    strategy._iter_observers_for_notification = lambda: iter([observer])
    strategy.notify_order = lambda order: broker.record("user_order")
    strategy.notify_trade = lambda trade: broker.record("user_trade")
    strategy.notify_fee_correction = lambda *args: broker.record("user_fee")


@pytest.mark.parametrize("quick", [False, True])
def test_prepare_after_real_trade_update_and_confirm_after_callbacks(quick):
    strategy, broker, data = _setup(quick)
    _listeners(strategy, broker)
    order = _fill(strategy, broker, data, quick, managed=True)
    if not quick:
        strategy._notify()
    assert isinstance(broker.actual_trade, bt.Trade)
    assert broker.orders[0] is order
    assert broker.trades[0].size == broker.actual_trade.size == 1
    assert broker.events == ["prepare", "user_order", "analyzer_order", "observer_order", "user_trade", "analyzer_trade", "observer_trade", "managed_ack", "confirm"]


@pytest.mark.parametrize("failure", ["prepare", "user_order", "analyzer_order", "observer_order", "user_trade", "analyzer_trade", "observer_trade", "managed_ack"])
def test_failure_releases_managed_receipt_and_never_confirms(failure):
    strategy, broker, data = _setup()
    _listeners(strategy, broker)
    _fill(strategy, broker, data, managed=True)
    broker.fail = failure
    with pytest.raises(RuntimeError, match=failure):
        strategy._notify()
    assert "confirm" not in broker.events
    assert broker.events[-1] == "managed_release"


def test_fee_preflight_and_callback_failure_do_not_double_apply():
    strategy, broker, data = _setup()
    _listeners(strategy, broker)
    order = _fill(strategy, broker, data)
    trade = strategy._trades[data][trade_key_from_order(order)][-1]
    order.info["fee_corrections"] = [{"sequence": 1, "delta": 0.2, "currency": "CNY"}]
    broker.fail = "validate"
    with pytest.raises(RuntimeError, match="validate"):
        strategy._apply_fee_corrections(order)
    assert trade.commission == pytest.approx(0.1)
    assert "_fee_corrections_applied" not in strategy.__dict__
    broker.events.clear()
    broker.fail = "analyzer_fee"
    with pytest.raises(RuntimeError, match="analyzer_fee"):
        strategy._apply_fee_corrections(order)
    assert broker.events == ["validate", "prepare_fee", "user_fee", "analyzer_fee"]
    assert trade.commission == pytest.approx(0.3)
    assert trade.pnlcomm == pytest.approx(trade.pnl - 0.3)
    broker.events.clear()
    broker.fail = None
    strategy._apply_fee_corrections(order)
    assert broker.done == 1
    assert broker.events == ["validate"]
    assert trade.commission == pytest.approx(0.3)


def test_fee_confirms_after_all_listeners():
    strategy, broker, data = _setup()
    _listeners(strategy, broker)
    order = _fill(strategy, broker, data)
    order.info["fee_corrections"] = [{"sequence": 1, "delta": 0.2, "currency": "CNY"}]
    strategy._apply_fee_corrections(order)
    assert broker.events == ["validate", "prepare_fee", "user_fee", "analyzer_fee", "observer_fee", "confirm"]


@pytest.mark.parametrize("failure", ["prepare_fee", "user_fee", "analyzer_fee", "observer_fee"])
def test_fee_failure_never_confirms_and_replay_helper_only_notifies(failure):
    strategy, broker, data = _setup()
    _listeners(strategy, broker)
    order = _fill(strategy, broker, data)
    trade = strategy._trades[data][trade_key_from_order(order)][-1]
    order.info["fee_corrections"] = [{"sequence": 1, "delta": 0.2, "currency": "CNY"}]
    broker.fail = failure
    with pytest.raises(RuntimeError, match=failure):
        strategy._apply_fee_corrections(order)
    assert "confirm" not in broker.events
    assert trade.commission == pytest.approx(0.3)
    broker.fail = None
    broker.events.clear()
    strategy._notify_fee_correction_inner(order, trade, 0.2, "CNY")
    assert broker.events == ["user_fee", "analyzer_fee", "observer_fee"]
    assert trade.commission == pytest.approx(0.3)


def test_unbound_backbroker_keeps_original_notifications():
    strategy, broker, data = _setup(broker=bt.brokers.BackBroker())
    events = []
    strategy.notify_order = lambda order: events.append("order")
    strategy.notify_trade = lambda trade: events.append("trade")
    _fill(strategy, broker, data)
    strategy._notify()
    assert events == ["order", "trade"]


def test_fee_entries_remain_sequential_for_listener_observations():
    strategy, broker, data = _setup()
    order = _fill(strategy, broker, data)
    trade = strategy._trades[data][trade_key_from_order(order)][-1]
    seen = []
    broker._gateway_prepare_fee_notification = lambda *args: None
    strategy.notify_fee_correction = lambda order, trade, delta, currency: seen.append((delta, trade.commission))
    order.info["fee_corrections"] = [
        {"sequence": 1, "delta": 0.2, "currency": "CNY"},
        {"sequence": 2, "delta": 0.4, "currency": "CNY"},
    ]
    strategy._apply_fee_corrections(order)
    assert seen == [(0.2, pytest.approx(0.3)), (0.4, pytest.approx(0.7))]
    assert trade.commission == pytest.approx(0.7)
    assert "confirm" not in broker.events


def test_quick_empty_lists_and_none_receipt_preserve_identity_and_skip_confirm():
    strategy, broker, _ = _setup(quick=True)
    orders, trades = [], []
    def prepare(owner, received_orders, received_trades):
        assert owner is strategy
        assert received_orders is orders and received_trades is trades
        return None
    broker._gateway_prepare_notifications = prepare
    strategy._notify(qorders=orders, qtrades=trades)
    assert "confirm" not in broker.events


def test_bound_fee_snapshot_ignores_mutations_to_source_rows_and_list():
    from types import MappingProxyType

    strategy, broker, data = _setup()
    order = _fill(strategy, broker, data)
    trade = strategy._trades[data][trade_key_from_order(order)][-1]
    corrections = [
        {"sequence": 1, "delta": 0.2, "currency": "CNY"},
        {"sequence": 2, "delta": 0.4, "currency": "CNY"},
    ]
    order.info["fee_corrections"] = corrections
    broker._gateway_validate_fee_notifications = lambda owner, order, rows, done: tuple(
        MappingProxyType(dict(row)) for row in rows
    )
    broker._gateway_prepare_fee_notification = lambda *args: None
    seen = []

    def callback(order, trade, delta, currency):
        seen.append((delta, trade.commission))
        if len(seen) == 1:
            corrections[1]["delta"] = 9
            corrections.append({"sequence": 3, "delta": 10, "currency": "CNY"})

    strategy.notify_fee_correction = callback
    strategy._apply_fee_corrections(order)
    assert seen == [(0.2, pytest.approx(0.3)), (0.4, pytest.approx(0.7))]
    assert strategy.__dict__["_fee_corrections_applied"][order.ref] == 2
    assert trade.commission == pytest.approx(0.7)


def test_unbound_fee_path_keeps_dynamic_list_iteration():
    strategy, broker, data = _setup(broker=bt.brokers.BackBroker())
    order = _fill(strategy, broker, data)
    trade = strategy._trades[data][trade_key_from_order(order)][-1]
    corrections = [{"sequence": 1, "delta": 0.2, "currency": "CNY"}]
    order.info["fee_corrections"] = corrections
    seen = []

    def callback(order, trade, delta, currency):
        seen.append(delta)
        if len(seen) == 1:
            corrections.append({"sequence": 2, "delta": 0.4, "currency": "CNY"})

    strategy.notify_fee_correction = callback
    strategy._apply_fee_corrections(order)
    assert seen == [0.2, 0.4]
    assert trade.commission == pytest.approx(0.7)


@pytest.mark.parametrize("callback_failure", [False, True])
def test_managed_receipt_uses_current_broker_after_callback(callback_failure):
    strategy, original, data = _setup()
    order = _fill(strategy, original, data, managed=True)
    current = _Broker()

    def callback(order):
        strategy.broker = current
        if callback_failure:
            raise RuntimeError("callback failure")

    strategy.notify_order = callback
    if callback_failure:
        with pytest.raises(RuntimeError, match="callback failure"):
            strategy._notify()
        assert current.events == ["managed_release"]
        assert original.events == ["prepare"]
    else:
        strategy._notify()
        assert current.events == ["managed_ack"]
        assert original.events == ["prepare", "confirm"]
    assert order.info["service_execution_recovery_receipt_id"] == "receipt"


class _GuardBroker(_Broker):
    """A bounded port substitute; it does not persist or ACK events."""

    def __init__(self):
        super().__init__()
        self.active = False
        self.pending = False
        self.abort_raises = False

    def _activate(self, receipt):
        if self.active:
            raise RuntimeError("nested prepare")
        self.active = True
        self.pending = True
        return receipt

    def _gateway_prepare_notifications(self, strategy, orders, trades):
        if self.active:
            raise RuntimeError("nested prepare")
        return self._activate(super()._gateway_prepare_notifications(strategy, orders, trades))

    def _gateway_prepare_fee_notification(self, strategy, order, trade, delta, currency, sequence):
        if self.active:
            raise RuntimeError("nested prepare")
        return self._activate(super()._gateway_prepare_fee_notification(strategy, order, trade, delta, currency, sequence))

    def _gateway_confirm_notifications(self, strategy, receipt):
        assert self.active and receipt is self.receipt
        self.record("confirm")
        self.active = False
        self.pending = False

    def _gateway_abort_notifications(self, strategy, receipt):
        assert self.active and receipt is self.receipt
        self.active = False
        self.events.append("abort")
        if self.abort_raises:
            raise RuntimeError("abort failure")

    def replay_fee(self, strategy, order, trade, delta, currency):
        if self.active:
            raise RuntimeError("replay while active")
        assert self.pending
        strategy._notify_fee_correction_inner(order, trade, delta, currency)
        self.pending = False


@pytest.mark.parametrize("kind", ["order", "fee"])
@pytest.mark.parametrize("failure", ["callback", "confirm"])
def test_callback_or_confirm_failure_aborts_guard_and_allows_recovery(kind, failure):
    strategy, broker, data = _setup(broker=_GuardBroker())
    order = _fill(strategy, broker, data)
    trade = strategy._trades[data][trade_key_from_order(order)][-1]
    if kind == "fee":
        order.info["fee_corrections"] = [{"sequence": 1, "delta": 0.2, "currency": "CNY"}]
        invoke = lambda: strategy._apply_fee_corrections(order)
        if failure == "callback":
            strategy.notify_fee_correction = lambda *args: broker.record("callback")
    else:
        invoke = strategy._notify
        if failure == "callback":
            strategy.notify_order = lambda order: broker.record("callback")
    broker.fail = failure
    broker.abort_raises = True
    with pytest.raises(RuntimeError, match="^" + failure + "$"):
        invoke()
    assert broker.events[-1] == "abort"
    assert broker.pending and not broker.active
    broker.abort_raises = False
    broker.fail = None
    if kind == "fee":
        strategy.notify_fee_correction = lambda *args: None
        broker.replay_fee(strategy, order, trade, 0.2, "CNY")
        assert trade.commission == pytest.approx(0.3)
    else:
        strategy.notify_order = lambda order: None
        strategy._notify()
    assert not broker.pending and not broker.active


@pytest.mark.parametrize("kind", ["order", "fee"])
def test_nested_prepare_failure_does_not_abort_outer_active_receipt(kind):
    strategy, broker, data = _setup(broker=_GuardBroker())
    order = _fill(strategy, broker, data)

    def callback(*args):
        assert broker.active
        with pytest.raises(RuntimeError, match="nested prepare"):
            strategy._notify()
        assert broker.active and "abort" not in broker.events

    if kind == "order":
        strategy.notify_order = callback
        strategy._notify()
    else:
        order.info["fee_corrections"] = [{"sequence": 1, "delta": 0.2, "currency": "CNY"}]
        strategy.notify_fee_correction = callback
        strategy._apply_fee_corrections(order)
    assert not broker.active and not broker.pending
    assert broker.events.count("confirm") == 1
    assert "abort" not in broker.events


def test_managed_ack_failure_aborts_gateway_receipt_after_release():
    strategy, broker, data = _setup(broker=_GuardBroker())
    _fill(strategy, broker, data, managed=True)
    broker.fail = "managed_ack"
    with pytest.raises(RuntimeError, match="managed_ack"):
        strategy._notify()
    assert broker.events[-3:] == ["managed_ack", "managed_release", "abort"]
    assert broker.pending and not broker.active


@pytest.mark.parametrize("kind", ["order", "fee"])
def test_first_callback_cannot_reenter_replay(kind):
    strategy, broker, data = _setup(broker=_GuardBroker())
    order = _fill(strategy, broker, data)
    trade = strategy._trades[data][trade_key_from_order(order)][-1]

    def callback(*args):
        with pytest.raises(RuntimeError, match="replay while active"):
            broker.replay_fee(strategy, order, trade, 0.2, "CNY")
        assert broker.active and broker.pending

    if kind == "order":
        strategy.notify_order = callback
        strategy._notify()
    else:
        order.info["fee_corrections"] = [{"sequence": 1, "delta": 0.2, "currency": "CNY"}]
        strategy.notify_fee_correction = callback
        strategy._apply_fee_corrections(order)
    assert not broker.active and not broker.pending


@pytest.mark.parametrize("quick", [False, True])
def test_entry_rejection_precedes_all_queue_trade_and_fee_mutation(quick):
    strategy, broker, data = _setup(quick)
    original = _fill(strategy, broker, data)
    trade = strategy._trades[data][trade_key_from_order(original)][-1]
    order = bt.BuyOrder(owner=strategy, data=data, size=2, price=10, exectype=bt.Order.Limit, simulated=False)
    order.addcomminfo(broker.getcommissioninfo(data))
    order.submit(broker)
    order.accept(broker)
    order.execute(data.datetime[0], 1, 10, 0, 0, 0, 1, 10, 0.1, 0, 0, 1, 10)
    order.info["fee_corrections"] = [{"sequence": 1, "delta": 0.2, "currency": "CNY"}]
    orders_before = tuple(strategy._orderspending)
    trades_before = tuple(strategy._tradespending)
    trade_before = (trade.size, trade.commission, trade.pnlcomm)
    applied_before = strategy.__dict__.get("_fee_corrections_applied")

    def reject(owner):
        assert owner is strategy
        raise RuntimeError("entry blocked")

    broker._gateway_validate_notification_entry = reject
    with pytest.raises(RuntimeError, match="entry blocked"):
        strategy._addnotification(order.clone(), quicknotify=quick)
    assert tuple(strategy._orderspending) == orders_before
    assert tuple(strategy._tradespending) == trades_before
    assert (trade.size, trade.commission, trade.pnlcomm) == trade_before
    assert strategy.__dict__.get("_fee_corrections_applied") is applied_before


def test_unbound_entry_validator_none_keeps_real_trade_path():
    strategy, broker, data = _setup()
    calls = []
    broker._gateway_validate_notification_entry = lambda owner: calls.append(owner)
    order = _fill(strategy, broker, data)
    trade = strategy._trades[data][trade_key_from_order(order)][-1]
    assert calls == [strategy]
    assert strategy._orderspending == [order]
    assert trade.size == 1 and trade.commission == pytest.approx(0.1)
