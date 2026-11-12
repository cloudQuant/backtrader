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
    params = (("label", None), ("direction", None), ("parent_id", None), ("order_size", 2))

    def __init__(self):
        self.events = []
        self.snapshots = []
        self.parent_order = None

    def next(self):
        if len(self) == 1:
            order_method = self.buy if self.p.direction == "buy" else self.sell
            self.parent_order = order_method(size=self.p.order_size, price=100, exectype=bt.Order.Limit,
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


@dataclass(frozen=True)
class SyntheticAllocation:
    """A test-only allocation, not a provider fill or an implemented SDK event."""
    event_id: str
    strategy: str
    parent: str
    quantity: int
    price: float
    fee: float
    source: str = "synthetic_strategy_allocation"


class MixedSourceBroker(SyntheticTransferBroker):
    """Test-only extension: separate partial events and in-memory ID checks."""

    def next(self):
        if not self.facts:
            return
        fact = self.facts[0]
        key = fact.transfer_id if isinstance(fact, InternalTransfer) else fact.event_id
        if key in self.applied:
            if self.applied[key] != fact:
                raise ValueError("synthetic identity conflict")
            self.facts.popleft()
            return
        legs = fact.legs if isinstance(fact, InternalTransfer) else (
            TransferLeg(fact.strategy, fact.parent, fact.quantity),
        )
        if any(leg.parent not in self.orders for leg in legs):
            return
        if isinstance(fact, InternalTransfer) and (
                fact.source != "internal_transfer" or sum(leg.quantity for leg in legs) != 0):
            raise ValueError("invalid synthetic transfer")
        for leg in legs:
            order = self.orders[leg.parent]
            if (order.owner.p.label != leg.strategy or order.executed.remsize * leg.quantity <= 0
                    or abs(leg.quantity) > abs(order.executed.remsize)):
                raise ValueError("synthetic leg binding mismatch")
        self.facts.popleft()
        for leg in legs:
            order = self.orders[leg.parent]
            pos = self.get_strategy_position(order.owner, order.data)
            size, price, opened, closed = pos.update(leg.quantity, fact.price)
            fee = fact.fee if isinstance(fact, SyntheticAllocation) else 0.0
            order.addinfo(execution_source=fact.source, latest_event_id=key)
            order.execute(order.data.datetime[0], leg.quantity, fact.price, closed, 0, 0,
                opened, abs(opened) * fact.price, fee, 0, 0, size, price)
            self.notifications.append(order.clone())
        self.applied[key] = fact


class MixedCapture(CaptureStrategy):
    def __init__(self):
        super().__init__()
        self.order_observations = []
        self.notices = []

    def notify_order(self, order):
        super().notify_order(order)
        self.notices.append(order)
        self.order_observations.append({
            "status": order.status,
            "size": order.executed.size,
            "commission": order.executed.comm,
            "source": order.info.get("execution_source"),
            "event_id": order.info.get("latest_event_id"),
            "bits": tuple((bit.size, bit.price, bit.comm,
                           getattr(bit, "execution_source", None),
                           getattr(bit, "event_id", None))
                          for bit in order.executed.iterpending()),
        })


def test_one_parent_partial_transfer_then_synthetic_allocation_with_replays():
    transfer = InternalTransfer("transfer-2", "internal_transfer", 100.0,
        (TransferLeg("a", "parent-a", 2), TransferLeg("b", "parent-b", -2)))
    allocation = SyntheticAllocation("allocation-1", "a", "parent-a", 2, 99.5, 0.5)
    adapter = MixedSourceBroker([transfer, transfer, allocation, allocation])
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.setbroker(adapter)
    bars = pd.DataFrame({"open": [100.0] * 7, "high": [100.0] * 7, "low": [99.0] * 7,
        "close": [100.0] * 7, "volume": [10.0] * 7},
        index=pd.date_range("2026-11-12", periods=7, freq="min"))
    cerebro.adddata(bt.feeds.PandasData(dataname=bars, name="synthetic"))
    cerebro.addstrategy(MixedCapture, label="a", direction="buy", parent_id="parent-a", order_size=4)
    cerebro.addstrategy(MixedCapture, label="b", direction="sell", parent_id="parent-b", order_size=2)
    a, b = cerebro.run()
    assert a.get_strategy_position().size == 4 and b.get_strategy_position().size == -2
    assert a.parent_order.status == bt.Order.Completed and a.parent_order.executed.size == 4
    assert a.parent_order.executed.comm == 0.5
    assert a.order_observations == [
        {"status": bt.Order.Partial, "size": 2, "commission": 0.0,
         "source": "internal_transfer", "event_id": "transfer-2",
         "bits": ((2, 100.0, 0.0, None, None),)},
        {"status": bt.Order.Completed, "size": 4, "commission": 0.5,
         "source": "synthetic_strategy_allocation", "event_id": "allocation-1",
         "bits": ((2, 99.5, 0.5, None, None),)},
    ]
    # A Trade notification is emitted on the first opening; adding to the same
    # Trade does not emit a second Trade notification in this BT lifecycle.
    assert [event for event in a.events if event[0] == "trade"] == [
        ("trade", 2, 100.0, 0.0, 0.0, None)
    ]
    # Order.clone() shares info: an earlier retained notification now exposes
    # the latest source, even though the callback snapshot above was correct.
    assert a.notices[0].info is a.notices[1].info
    assert a.notices[0].info.get("execution_source") == "synthetic_strategy_allocation"
    assert set(adapter.applied) == {"transfer-2", "allocation-1"} and not adapter.facts
