"""Day-scoped CTP return identities across a trading-day switch (R-3 review F1).

CTP ``FrontID``/``SessionID``/``OrderRef`` and ``ExchangeID``/``OrderSysID``
are unique within one trading day only; exchange order numbers restart every
day.  After a verified switch an own new-day order may carry the OrderSysID of
an own old-day order.  Its returns must resolve to the order of their trading
day, never to the old one, and a day-scoped return that names only an own
order of another day is not booked but counted and logged.  Routes without
offsets (OKX/Binance) keep plain-key matching.

UNIT/FAKE: fake facade, real ``backtrader.live_state`` in ``tmp_path``; the
CTP-shaped fills mirror ``bt_api_ctp.direct_write_provider.
project_ctp_execution_event("trade", ...)`` (OrderRef, ExchangeID, TradingDay,
OrderSysID; no FrontID/SessionID).
"""

import datetime as dt
import itertools

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from backtrader.brokers import _btapi_direct_mode as direct_mode
from bt_api_base.direct_write_protocol import (
    DirectExecutionEvent,
    DirectExecutionEventKind,
    NativeOrderIdentity,
)

from ._fakes import (
    EXCHANGE,
    OTHER_SYMBOL,
    SYMBOL,
    TODAY,
    TOMORROW,
    VENUE,
    order_event,
    position,
    quiet,
    run_day_switch,
    trade_event,
)

NEW_DAY = dt.date(2026, 11, 6)


def _buy(env, broker, size=1, feed=None):
    return broker.buy(
        env.strategy, feed or env.feed, size, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )


def _working(env, broker, sys_id, size=1):
    order = _buy(env, broker, size)
    call = env.api.place_calls[-1]
    env.api.push(order_event(call.identity, "accepted", sys_id=sys_id, qty=size))
    broker.next()
    assert order.status == bt.Order.Accepted
    return order, call


def _started(env, **params):
    broker = env.start(first_init=True, **params)
    quiet(broker)
    env.api.schedule.trading_day = NEW_DAY
    return broker


def _switch(env, broker, *, positions=()):
    """The provider moves to TOMORROW; one verification attempt completes the switch."""
    env.api.trading_day = TOMORROW
    env.api.positions = list(positions)
    env.api.active_orders, env.api.orders, env.api.trades = [], [], []
    facts = env.api.direct_account_facts(EXCHANGE, positions=False, active_orders=False)
    broker._direct_facts_results.append(("funds", facts))
    broker.next()
    assert run_day_switch(broker)["status"] == "completed"
    assert broker._direct_trading_day == TOMORROW


def _ctp_fill(identity, sys_id, trade_id, *, qty=1.0, symbol=OTHER_SYMBOL, price=3300.0):
    """A CTP trade return of ``identity``'s order (its OrderRef and trading day)."""
    fields = dict(identity.fields)
    ref = fields["order_ref"]
    return DirectExecutionEvent(
        kind=DirectExecutionEventKind.TRADE,
        exchange_name=EXCHANGE,
        symbol=symbol,
        identity=NativeOrderIdentity(
            exchange_name=EXCHANGE,
            client_order_id=ref,
            fields={
                "order_ref": ref,
                "exchange_id": VENUE,
                "trading_day": fields["trading_day"],
                "order_sys_id": sys_id,
            },
        ),
        exchange_order_id=sys_id,
        side="buy",
        offset="open",
        trade_id=trade_id,
        trade_price=price,
        trade_qty=qty,
        trading_day=fields["trading_day"],
    )


def _new_day_order(env, broker, sys_id, size=1):
    """An own order on hc2701 (also SHFE) accepted with ``sys_id`` on TOMORROW."""
    order = _buy(env, broker, size, feed=env.other_feed)
    assert order.status == bt.Order.Submitted
    call = env.api.place_calls[-1]
    assert call.identity.fields["trading_day"] == TOMORROW
    env.api.push(
        order_event(call.identity, "accepted", sys_id=sys_id, qty=size, symbol=OTHER_SYMBOL)
    )
    broker.next()
    assert order.status == bt.Order.Accepted
    return order, call


@pytest.fixture
def warnings(monkeypatch):
    calls = []
    monkeypatch.setattr(
        direct_mode, "throttled_warning", lambda *a, **k: calls.append(a), raising=False
    )
    return calls


# ---------------------------------------------------------------------------
# routes with explicit offsets (CTP)
# ---------------------------------------------------------------------------
def test_own_new_day_order_reusing_an_old_day_order_sys_id_gets_its_fill(env, warnings):
    broker = _started(env)
    old, _old_call = _working(env, broker, "7401")  # learns SHFE/7401 on TODAY
    _switch(env, broker)
    new, call = _new_day_order(env, broker, "7401")  # the venue reuses 7401 on TOMORROW
    env.api.push(_ctp_fill(call.identity, "7401", "T-NEW-7401"))
    broker.next()
    assert new.status == bt.Order.Completed, "own new-day fill was dropped"
    assert broker.getposition(env.other_feed, side="long").size == 1
    assert old.alive() and old.executed.size == 0  # the old-day order is untouched
    assert "other_day_returns" not in broker.get_direct_reconcile_report()
    assert warnings == []


def test_reused_order_sys_id_after_the_old_order_completed_normally(env):
    """No UNKNOWN needed: a normally filled old-day order learned the same id."""
    broker = _started(env)
    old, _call = _working(env, broker, "7401")
    env.api.push(trade_event("T7401", sys_id="7401"))
    broker.next()
    assert old.status == bt.Order.Completed
    _switch(env, broker, positions=[position("long", 1, 0, 1)])
    assert broker.direct_writes_blocked() == {}
    new, call = _new_day_order(env, broker, "7401")
    env.api.push(_ctp_fill(call.identity, "7401", "T-NEW-7401"))
    broker.next()
    assert new.status == bt.Order.Completed and new.executed.size == 1
    assert old.executed.size == 1
    assert broker.getposition(env.feed, side="long").size == 1
    assert broker.getposition(env.other_feed, side="long").size == 1
    assert broker.direct_writes_blocked() == {}


def test_reused_session_triple_resolves_only_the_order_of_its_trading_day(env):
    """Both own orders keep their FrontID/SessionID/OrderRef on their own day."""
    broker = _started(env)
    old, old_call = _working(env, broker, "7401")
    _switch(env, broker)
    reused_ref = int(old_call.identity.fields["order_ref"])
    env.api._refs = itertools.count(reused_ref)  # same front/session, OrderRef reused
    new = _buy(env, broker, feed=env.other_feed)
    new_call = env.api.place_calls[-1]
    triple = ("front_id", "session_id", "order_ref")
    assert [new_call.identity.fields[k] for k in triple] == [
        old_call.identity.fields[k] for k in triple
    ]
    # A late return of the old day without an OrderSysID (session triple only).
    late = order_event(old_call.identity, "accepted", sys_id=None)
    assert broker._direct_order_for_event(late) is old
    fresh = order_event(new_call.identity, "accepted", sys_id=None, symbol=OTHER_SYMBOL)
    assert broker._direct_order_for_event(fresh) is new


@pytest.mark.parametrize("new_day", [False, True], ids=["same_day", "new_day"])
def test_fill_before_its_order_return_is_handled_as_on_the_same_day(env, warnings, new_day):
    """A fill that overtakes its order return stays unmatched, as on the same day.

    On the new day it names the old-day order through the reused OrderSysID:
    it is not booked there, and it is counted and logged instead of silent.
    """
    broker = _started(env)
    old, _old_call = _working(env, broker, "7401")
    if new_day:
        _switch(env, broker)
    sys_id = "7401" if new_day else "7402"  # unique within a day, reused on the next
    new = _buy(env, broker, size=2, feed=env.other_feed)
    call = env.api.place_calls[-1]
    env.api.push(_ctp_fill(call.identity, sys_id, "T1"))  # before the order return
    broker.next()
    assert new.status == bt.Order.Submitted and new.executed.size == 0
    assert old.executed.size == 0  # never booked on another order
    assert broker.getposition(env.feed, side="long").size == 0
    assert broker.getposition(env.other_feed, side="long").size == 0
    env.api.push(order_event(call.identity, "accepted", sys_id=sys_id, qty=2, symbol=OTHER_SYMBOL))
    env.api.push(_ctp_fill(call.identity, sys_id, "T2"))
    broker.next()
    assert new.status == bt.Order.Partial and new.executed.size == 1
    assert old.executed.size == 0
    report = broker.get_direct_reconcile_report()
    if new_day:
        other = report["other_day_returns"]
        assert other["count"] == 1
        last = other["last"]
        assert (last["kind"], last["symbol"], last["exchange_order_id"]) == (
            "trade",
            OTHER_SYMBOL,
            "7401",
        )
        assert (last["trading_day"], last["order_trading_day"]) == (TOMORROW, TODAY)
        assert len(warnings) == 1
    else:
        assert "other_day_returns" not in report
        assert warnings == []


def test_restored_order_and_a_new_day_order_reusing_its_id_stay_apart(env):
    """Restart restore: no index is persisted; the restored order is keyed by its day."""
    env.init_flat()
    _marker_id, identity = env.seed_marker("000000000071", local_seq=50, bt_ref=50)
    env.api.active_orders = [order_event(identity, "accepted", sys_id="7401", qty=2, remaining=2)]
    broker = env.start()
    quiet(broker)
    env.api.schedule.trading_day = NEW_DAY
    (restored,) = broker.take_over_restored_orders(env.strategy)
    env.api.push(_ctp_fill(identity, "7401", "T1", symbol=SYMBOL, price=3500.0))
    broker.next()
    assert restored.status == bt.Order.Partial and restored.executed.size == 1
    _switch(env, broker, positions=[position("long", 1, 0, 1)])
    env.api._refs = itertools.count(71)  # same front/session reuse the restored OrderRef
    new, call = _new_day_order(env, broker, "7401")  # and the venue reuses 7401
    triple = ("front_id", "session_id", "order_ref")
    assert [call.identity.fields[k] for k in triple] == [identity.fields[k] for k in triple]
    env.api.push(_ctp_fill(call.identity, "7401", "T-NEW"))
    broker.next()
    assert new.status == bt.Order.Completed
    assert restored.executed.size == 1
    assert broker.getposition(env.other_feed, side="long").size == 1
    late = order_event(identity, "accepted", sys_id=None, qty=2)  # old day, triple only
    assert broker._direct_order_for_event(late) is restored


# ---------------------------------------------------------------------------
# routes without offsets (OKX/Binance): plain keys, no day binding
# ---------------------------------------------------------------------------
def test_route_without_offsets_keeps_plain_identity_keys(env, warnings):
    broker = env.start(first_init=True, require_offset=False)
    quiet(broker)
    resting = broker.buy(env.strategy, env.feed, 2, price=3500.0, exectype=bt.Order.Limit)
    call = env.api.place_calls[-1]
    env.api.push(order_event(call.identity, "accepted", sys_id="9901", qty=2))
    broker.next()
    assert all(key[0] != "d" for key in broker._direct_index)
    other_day = dict(call.identity.fields, trading_day=TOMORROW)
    fill = _ctp_fill(
        NativeOrderIdentity(exchange_name=EXCHANGE, client_order_id=None, fields=other_day),
        "9901",
        "T9901",
        symbol=SYMBOL,
        price=3500.0,
    )
    env.api.push(fill)  # another day stamp still belongs to the GTC order
    broker.next()
    assert resting.status == bt.Order.Partial and resting.executed.size == 1
    assert all(key[0] != "d" for key in broker._direct_index)
    assert "other_day_returns" not in broker.get_direct_reconcile_report()
    assert warnings == []
