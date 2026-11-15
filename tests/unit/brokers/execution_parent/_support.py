"""Shared fakes for the Execution parent projection tests (UNIT/FAKE only).

A real BT ``DataBase``, real ``BuyOrder``/``SellOrder`` and a real ``Position``
are used together with in-memory fact ports.  Nothing here contacts a provider,
an Execution service, a Gateway or an account; the status/fill/cancel values
are synthetic and use the committed ``parent_submit_service.status()`` shape.
"""

import datetime as dt

import backtrader as bt

SHA_A = "a" * 64
SHA_B = "b" * 64
DAY = "20261109"


class ListFeed(bt.feeds.DataBase):
    """A real ``DataBase`` loaded from one ``(datetime, price)`` bar."""

    params = (("bars", ()),)

    def start(self):
        super().start()
        self._idx = 0

    def _load(self):
        if self._idx >= len(self.p.bars):
            return False
        when, price = self.p.bars[self._idx]
        self._idx += 1
        self.lines.datetime[0] = bt.date2num(when)
        for name in ("open", "high", "low", "close"):
            getattr(self.lines, name)[0] = price
        self.lines.volume[0] = 1.0
        self.lines.openinterest[0] = 0.0
        return True


def make_feed(symbol="rb", price=3500.0):
    feed = ListFeed(dataname=symbol, bars=[(dt.datetime(2026, 11, 5, 9, 1), price)])
    feed._start()
    assert feed.load() is True
    return feed


def make_order(
    *,
    side="buy",
    size=3,
    price=3500.0,
    request_id="req-1",
    offset="open",
    parent_ref="par-1",
    strategy_ref="strat-1",
    trading_day=DAY,
    feed=None,
):
    """Build a real BT order and the declared binding derived from it."""
    from backtrader.brokers._execution_parent_projection import order_binding

    feed = make_feed() if feed is None else feed
    cls = bt.BuyOrder if side == "buy" else bt.SellOrder
    order = cls(owner=None, data=feed, size=size, price=price, exectype=bt.Order.Limit, valid=None)
    binding = order_binding(
        order,
        request_id,
        offset=offset,
        parent_ref=parent_ref,
        strategy_ref=strategy_ref,
        trading_day=trading_day,
    )
    return order, binding


def child(child_id, state, quantity="1", reservation_id=None, attempts=1, last_error=None):
    return {
        "child_id": child_id,
        "state": state,
        "quantity": quantity,
        "reservation_id": reservation_id,
        "attempts": attempts,
        "last_error": last_error,
    }


def status(
    state="ACCEPTED",
    *,
    request_id="req-1",
    parent_ref="par-1",
    sha=SHA_A,
    children=(),
    frozen=False,
    last_error=None,
    attempts=1,
    unknown_children=None,
):
    children = tuple(children)
    if unknown_children is None:
        unknown_children = tuple(
            item["child_id"] for item in children if item["state"] == "UNKNOWN"
        )
    return {
        "status": state,
        "source": "LOCAL_JOURNAL",
        "request_id": request_id,
        "parent_ref": parent_ref,
        "state": state,
        "request_sha256": sha,
        "risk_selected": False,
        "registration_operation_id": "op-" + request_id,
        "remote_attempts": attempts,
        "last_error": last_error,
        "frozen": frozen,
        "children": children,
        "unknown_children": tuple(unknown_children),
    }


def absent_status(request_id="req-1"):
    """The committed shape of a missing journal row."""
    return {
        "status": "UNKNOWN",
        "source": "LOCAL_JOURNAL",
        "request_id": request_id,
        "parent_ref": None,
        "state": None,
        "request_sha256": None,
        "risk_selected": None,
        "registration_operation_id": None,
        "remote_attempts": 0,
        "last_error": None,
        "frozen": None,
        "children": (),
        "unknown_children": (),
    }


def fill(
    fill_id,
    *,
    child_id="c1",
    quantity="1",
    price="3500",
    source="VENUE",
    side=None,
    offset=None,
    trading_day=DAY,
    exchange_trade_id=None,
    parent_ref=None,
):
    fact = {
        "fill_id": fill_id,
        "child_id": child_id,
        "quantity": quantity,
        "price": price,
        "source": source,
    }
    for name, value in (
        ("side", side),
        ("offset", offset),
        ("trading_day", trading_day),
        ("exchange_trade_id", exchange_trade_id),
        ("parent_ref", parent_ref),
    ):
        if value is not None:
            fact[name] = value
    return fact


def cancel(cancel_id="cancel-1", outcome="CANCELED", reason_code=None):
    fact = {"cancel_id": cancel_id, "outcome": outcome}
    if reason_code is not None:
        fact["reason_code"] = reason_code
    return fact


def completion(completion_id="complete-1", completed_quantity="3"):
    return {"completion_id": completion_id, "completed_quantity": completed_quantity}


class Ports:
    """In-memory fact ports; only the five read methods are callable by design."""

    def __init__(self, bindings, statuses=None, fills=None, cancels=None, completions=None):
        self.bindings = dict(bindings)
        self.statuses = dict(statuses or {})
        self.fill_facts = dict(fills or {})
        self.cancels = dict(cancels or {})
        self.completions = dict(completions or {})
        self.reads = []
        self.write_calls = []
        self.raise_on = set()

    def binding(self, request_id):
        self.reads.append(("binding", request_id))
        if "binding" in self.raise_on:
            raise RuntimeError("synthetic binding read failure")
        return self.bindings.get(request_id)

    def status(self, request_id):
        self.reads.append(("status", request_id))
        if "status" in self.raise_on:
            raise RuntimeError("synthetic status read failure")
        return self.statuses.get(request_id)

    def fills(self, request_id):
        self.reads.append(("fills", request_id))
        if "fills" in self.raise_on:
            raise RuntimeError("synthetic fills read failure")
        return self.fill_facts.get(request_id, ())

    def cancel(self, request_id):
        self.reads.append(("cancel", request_id))
        if "cancel" in self.raise_on:
            raise RuntimeError("synthetic cancel read failure")
        return self.cancels.get(request_id)

    def completion(self, request_id):
        self.reads.append(("completion", request_id))
        if "completion" in self.raise_on:
            raise RuntimeError("synthetic completion read failure")
        return self.completions.get(request_id)

    def make_order(self, *args, **kwargs):
        self.write_calls.append("make_order")
        raise AssertionError("the projection must not use a direct order path")

    def cancel_order(self, *args, **kwargs):
        self.write_calls.append("cancel_order")
        raise AssertionError("the projection must not use a direct cancel path")


def projection(ports, restore=None):
    from backtrader.brokers._execution_parent_projection import ExecutionParentProjection

    return ExecutionParentProjection(
        binding_port=ports,
        status_port=ports,
        fill_port=ports,
        cancel_port=ports,
        completion_port=ports,
        restore=restore,
    )


def kinds(result):
    return [item.kind for item in result.notifications]
