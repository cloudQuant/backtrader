"""65.01 offline research: BT projections, not provider or Gateway evidence.

All prices, fees and margin inputs are controlled examples. An OrderExecutionBit
here is a framework projection of an internal event, not an exchange fill.
"""

import itertools

import backtrader as bt
import pandas as pd
import pytest

from backtrader.metabase import OwnerContext


class Capture(bt.Strategy):
    def notify_order(self, order):
        self.events.append(("order", order.status, order.executed.size, order.info.get("source")))

    def notify_trade(self, trade):
        self.events.append(("trade", trade.size, trade.price, trade.pnl, trade.commission))

    def notify_fee_correction(self, order, trade, delta, currency):
        self.events.append(("fee", delta, currency, trade.commission if trade else None))


class ControlledBook:
    """Test-only input values; it is not an authoritative or durable ledger."""

    def __init__(self, position, budget, realized, unrealized, fee, margin, inflight):
        self.position = position
        self.budget = budget
        self.realized = realized
        self.unrealized = unrealized
        self.fee = fee
        self.margin = margin
        self.inflight = inflight

    def getposition(self, data):
        return self.position

    def getvalue(self):
        if None in (self.budget, self.realized, self.unrealized, self.fee):
            raise ValueError("controlled input unavailable")
        return self.budget + self.realized + self.unrealized - self.fee

    def getcash(self, *, currency=None):
        if self.margin is None or self.inflight is None:
            raise ValueError("controlled input unavailable")
        return self.getvalue() - self.margin - self.inflight


def framework():
    frame = pd.DataFrame(
        {"open": [100.0], "high": [100.0], "low": [100.0], "close": [100.0], "volume": [10.0]},
        index=pd.to_datetime(["2026-11-12 09:00"]),
    )
    data = bt.feeds.PandasData(dataname=frame, name="test")
    data._start()
    assert data.load()
    broker = bt.brokers.BackBroker()
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    cerebro.stcount = itertools.count()
    cerebro.datas, cerebro.datasbyname = [data], {"test": data}
    strategies = []
    for _ in range(2):
        with OwnerContext.set_owner(cerebro):
            strategy = Capture.__new__(Capture)
        strategy.datas, strategy.data = [data], data
        strategy._tradehistoryon, strategy._quicknotify = True, False
        strategy.events = []
        strategies.append(strategy)
    return data, broker, strategies


def make_order(strategy, data, broker, size, *, source):
    cls = bt.BuyOrder if size > 0 else bt.SellOrder
    order = cls(owner=strategy, data=data, size=abs(size), price=100, exectype=bt.Order.Limit)
    order.addcomminfo(bt.CommInfoBase(commission=0, margin=600, mult=10))
    order.addinfo(source=source)
    order.submit(broker)
    order.accept(broker)
    return order


def project(strategy, order, position, size, price, *, fee=0):
    old_price = position.price
    _, _, opened, closed = position.update(size, price)
    pnl = order.comminfo.profitandloss(-closed, old_price, price) if closed else 0
    order.execute(order.data.datetime[0], size, price, closed, 0, fee if closed else 0,
                  opened, 0, fee if opened else 0, 0, pnl, position.size, position.price)
    strategy._addnotification(order.clone())
    strategy._notify()
    strategy.clear()


def test_internal_opposing_positions_and_notifications_without_venue_facts():
    data, broker, (a, b) = framework()
    apos, bpos = bt.Position(), bt.Position()
    buy = make_order(a, data, broker, 5, source="internal_transfer")
    sell = make_order(b, data, broker, -5, source="internal_transfer")
    project(a, buy, apos, 5, 100)
    project(b, sell, bpos, -5, 100)

    assert (apos.size, apos.price, bpos.size, bpos.price) == (5, 100, -5, 100)
    assert broker.getposition(data).size == 0
    assert (buy.executed.size, sell.executed.size) == (5, -5)
    assert (buy.status, sell.status) == (bt.Order.Completed, bt.Order.Completed)
    assert a.events == [("order", bt.Order.Completed, 5, "internal_transfer"), ("trade", 5, 100, 0, 0)]
    assert b.events == [("order", bt.Order.Completed, -5, "internal_transfer"), ("trade", -5, 100, 0, 0)]
    bit = buy.executed.exbits[0]
    assert not hasattr(bit, "source") and not hasattr(bit, "trade_id")


def test_partial_virtual_close_fee_and_strategy_getters_use_controlled_scope():
    data, broker, (a, b) = framework()
    apos, bpos = bt.Position(), bt.Position()
    project(a, make_order(a, data, broker, 5, source="internal_transfer"), apos, 5, 100)
    project(b, make_order(b, data, broker, -5, source="internal_transfer"), bpos, -5, 100)
    close = make_order(a, data, broker, -5, source="conversion_real_sell_open_projection")
    project(a, close, apos, -2, 110, fee=3)
    # A's remaining unrealized = 3 * (110 - 100) * 10; B's = -5 * 10 * 10.
    # 600 per unit is supplied for this experiment, not a prescribed margin policy.
    a.account_book = ControlledBook(apos, 10000, 200, 300, 3, 1800, 0)
    b.account_book = ControlledBook(bpos, 10000, 0, -500, 0, 3000, 0)
    assert (apos.size, apos.price, bpos.size, bpos.price) == (3, 100, -5, 100)
    assert (close.status, close.executed.size, close.executed.remsize) == (bt.Order.Partial, -2, -3)
    assert (close.executed.pnl, close.executed.comm) == (200, 3)
    # Partial reduction updates Trade state, but does not emit notify_trade.
    assert a.events[-1] == ("order", bt.Order.Partial, -2, "conversion_real_sell_open_projection")
    atrade = list(a._trades[data].values())[0][-1]
    btrade = list(b._trades[data].values())[0][-1]
    assert (atrade.size, atrade.price, atrade.pnl, atrade.commission, atrade.pnlcomm) == (3, 100, 200, 3, 197)
    assert (btrade.size, btrade.price, btrade.pnl, btrade.commission) == (-5, 100, 0, 0)
    assert a.get_strategy_position().size == 3 and b.get_strategy_position().size == -5
    assert (a.get_strategy_value(), a.get_strategy_cash()) == (10497, 8697)
    assert (b.get_strategy_value(), b.get_strategy_cash()) == (9500, 6500)
    assert a.getposition().size == 0  # account state was not projected by this test
    a.account_book.margin = None
    with pytest.raises(ValueError, match="unavailable"):
        a.get_strategy_cash()


def test_order_execution_has_no_intrinsic_event_deduplication():
    data, broker, (a, _) = framework()
    position = bt.Position()
    order = make_order(a, data, broker, 5, source="internal_transfer")
    project(a, order, position, 2, 100)
    # Deliberate duplicate to expose the required upstream event identity/fence.
    project(a, order, position, 2, 100)
    assert position.size == order.executed.size == 4
    assert order.status == bt.Order.Partial


def test_fee_revision_is_applied_once_to_existing_trade_in_process():
    data, broker, (a, _) = framework()
    position = bt.Position()
    project(a, make_order(a, data, broker, 5, source="internal_transfer"), position, 5, 100)
    close = make_order(a, data, broker, -5, source="conversion_real_sell_open_projection")
    project(a, close, position, -2, 110, fee=3)
    trade = list(a._trades[data].values())[0][-1]

    # The producer would need to update the Order and supply a stable revision.
    close.executed.comm += 1
    close.addinfo(fee_corrections=[{"sequence": 1, "delta": 1, "currency": "TEST"}])
    a._apply_fee_corrections(close)
    a._apply_fee_corrections(close)
    assert (trade.pnl, trade.commission, trade.pnlcomm, close.executed.comm) == (200, 4, 196, 4)
    assert a.events.count(("fee", 1.0, "TEST", 4.0)) == 1
