"""Test-only BrokerBase adapter for a non-venue, two-leg transfer.

Cerebro drives the real broker/strategy notification lifecycle. The local
Transfer is a synthetic candidate, not a shipped SDK contract, authorization,
execution service, durable journal, or a venue trade. In-memory replay is the
only replay exercised; crash recovery, atomic commit and account facts are
NOT_RUN. No BT private method is invoked by this prototype.
"""

from collections import deque
from dataclasses import dataclass
from pathlib import Path
import sys

import backtrader as bt
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", autouse=True)
def isolated_sources():
    assert Path(bt.__file__).resolve().is_relative_to(ROOT)
    yield
    escaped = {}
    for name, module in tuple(sys.modules.items()):
        if name == "backtrader" or name.startswith(("backtrader.", "bt_api_py", "bt_api_")):
            source = getattr(module, "__file__", None)
            if source and not Path(source).resolve().is_relative_to(ROOT):
                escaped[name] = source
    assert not escaped, f"non-worktree modules: {escaped}"


@dataclass(frozen=True)
class TransferLeg:
    strategy: str
    parent: str
    quantity: int


@dataclass(frozen=True)
class InternalTransfer:
    transfer_id: str
    source: str
    price: float
    legs: tuple[TransferLeg, TransferLeg]


class SyntheticTransferBroker(bt.BrokerBase):
    """Minimal synthetic adapter; money, venue and authorization are out of scope."""

    def __init__(self, facts):
        super().__init__()
        self.startingcash = 10000.0
        self.facts = deque(facts)
        self.orders = {}
        self.strategy_positions = {}
        self.account_position = bt.Position()
        self.notifications = deque()
        self.applied = {}
        self.lifecycle = []

    def start(self):
        super().start()
        self.lifecycle.append("start")

    def stop(self):
        self.lifecycle.append("stop")
        super().stop()

    def getcash(self):
        return 10000.0  # controlled placeholder; not a strategy/account valuation

    def getvalue(self, datas=None):
        return 10000.0

    def getposition(self, data, side=None):
        if side is not None:
            raise ValueError("not modelled")
        return self.account_position

    def get_strategy_position(self, strategy, data, side=None):
        if side is not None:
            raise ValueError("not modelled")
        return self.strategy_positions.setdefault((strategy.p.label, data), bt.Position())

    def submit(self, order):
        key = order.info.get("parent_id")
        if key in self.orders:
            raise ValueError("duplicate synthetic parent")
        order.addcomminfo(self.getcommissioninfo(order.data))
        order.submit(self)
        order.accept(self)
        self.orders[key] = order
        return order

    def buy(self, owner, data, size, price=None, plimit=None, exectype=None, valid=None,
            tradeid=0, oco=None, trailamount=None, trailpercent=None, parent=None,
            transmit=True, **kwargs):
        order = bt.BuyOrder(owner=owner, data=data, size=size, price=price, pricelimit=plimit,
            exectype=exectype, valid=valid, tradeid=tradeid, oco=oco, parent=parent,
            transmit=transmit)
        order.addinfo(**kwargs)
        return self.submit(order)

    def sell(self, owner, data, size, price=None, plimit=None, exectype=None, valid=None,
             tradeid=0, oco=None, trailamount=None, trailpercent=None, parent=None,
             transmit=True, **kwargs):
        order = bt.SellOrder(owner=owner, data=data, size=size, price=price, pricelimit=plimit,
            exectype=exectype, valid=valid, tradeid=tradeid, oco=oco, parent=parent,
            transmit=transmit)
        order.addinfo(**kwargs)
        return self.submit(order)

    def get_notification(self):
        return self.notifications.popleft() if self.notifications else None

    def next(self):
        if not self.facts:
            return
        fact = self.facts[0]
        if fact.transfer_id in self.applied:
            if self.applied[fact.transfer_id] != fact:
                raise ValueError("synthetic transfer identity conflict")
            self.facts.popleft()
            return
        if any(leg.parent not in self.orders for leg in fact.legs):
            return
        if fact.source != "internal_transfer" or sum(leg.quantity for leg in fact.legs) != 0:
            raise ValueError("invalid synthetic transfer")
        for leg in fact.legs:
            order = self.orders[leg.parent]
            if order.owner.p.label != leg.strategy or order.size != leg.quantity:
                raise ValueError("synthetic leg binding mismatch")
        self.facts.popleft()
        for leg in fact.legs:
            order = self.orders[leg.parent]
            pos = self.get_strategy_position(order.owner, order.data)
            size, price, opened, closed = pos.update(leg.quantity, fact.price)
            order.addinfo(execution_source=fact.source, internal_transfer_id=fact.transfer_id)
            order.execute(order.data.datetime[0], leg.quantity, fact.price, closed, 0, 0,
                opened, abs(opened) * fact.price, 0, 0, 0, size, price)
            self.notifications.append(order.clone())
        self.applied[fact.transfer_id] = fact


class CaptureStrategy(bt.Strategy):
    params = (("label", None), ("direction", None), ("parent_id", None))

    def __init__(self):
        self.events = []
        self.snapshots = []
        self.parent_order = None

    def next(self):
        if len(self) == 1:
            order_method = self.buy if self.p.direction == "buy" else self.sell
            self.parent_order = order_method(size=2, price=100, exectype=bt.Order.Limit,
                                             parent_id=self.p.parent_id)
        self.snapshots.append((self.get_strategy_position().size, self.getposition().size))

    def notify_order(self, order):
        self.events.append(("order", order.status, order.executed.size,
                            order.info.get("execution_source"),
                            order.info.get("internal_transfer_id"), order.info.get("parent_id")))

    def notify_trade(self, trade):
        self.events.append(("trade", trade.size, trade.price, trade.pnl, trade.commission,
                            getattr(trade, "execution_source", None)))


def test_cerebro_delivers_two_synthetic_transfer_legs_without_venue_trade():
    fact = InternalTransfer("transfer-1", "internal_transfer", 100.0,
        (TransferLeg("a", "parent-a", 2), TransferLeg("b", "parent-b", -2)))
    adapter = SyntheticTransferBroker([fact, fact])
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.setbroker(adapter)
    bars = pd.DataFrame({"open": [100.0] * 4, "high": [100.0] * 4, "low": [100.0] * 4,
        "close": [100.0] * 4, "volume": [10.0] * 4},
        index=pd.date_range("2026-11-12", periods=4, freq="min"))
    cerebro.adddata(bt.feeds.PandasData(dataname=bars, name="synthetic"))
    cerebro.addstrategy(CaptureStrategy, label="a", direction="buy", parent_id="parent-a")
    cerebro.addstrategy(CaptureStrategy, label="b", direction="sell", parent_id="parent-b")
    a, b = cerebro.run()
    assert adapter.lifecycle == ["start", "stop"]
    assert (a.get_strategy_position().size, b.get_strategy_position().size) == (2, -2)
    assert a.getposition().size == b.getposition().size == 0
    assert (a.parent_order.executed.size, b.parent_order.executed.size) == (2, -2)
    assert (a.parent_order.status, b.parent_order.status) == (bt.Order.Completed, bt.Order.Completed)
    assert not hasattr(a.parent_order.executed.exbits[0], "execution_source")
    assert not hasattr(a.parent_order.executed.exbits[0], "internal_transfer_id")
    assert a.events == [("order", bt.Order.Completed, 2, "internal_transfer", "transfer-1", "parent-a"),
                        ("trade", 2, 100.0, 0.0, 0.0, None)]
    assert b.events == [("order", bt.Order.Completed, -2, "internal_transfer", "transfer-1", "parent-b"),
                        ("trade", -2, 100.0, 0.0, 0.0, None)]
    assert a.snapshots[-1] == (2, 0) and b.snapshots[-1] == (-2, 0)
    assert len(adapter.applied) == 1 and not adapter.facts
