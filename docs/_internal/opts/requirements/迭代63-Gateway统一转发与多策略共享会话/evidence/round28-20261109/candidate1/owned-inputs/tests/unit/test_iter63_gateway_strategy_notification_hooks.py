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
