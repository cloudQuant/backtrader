"""Fractional fills complete their order exactly (iteration 62 OKX demo rerun, 2026-11-08).

DEMO evidence: an OKX BTC-USDT-SWAP limit buy of 1.0 contract (lot 0.01) was
filled in many fractional fills (0.13, 0.01, 0.01, ...).  Binary float sums of
those fills leave a residue (``1.0 - 0.13 - 0.01 * 7 - 0.8 == -1.1e-16``), so
the order stayed Partial after its last fill, ``stop()`` reported a working
order and the closing sell left a ``1e-16`` phantom leg.  Fill quantities are
summed exactly and a residue within the quantity tolerance is zero: the order
completes (marker TERMINAL ``filled``), a partially filled order is cancelled
with its exact executed size, and legs, splits and the snapshot hold exact
values.  Backtest ``Order``/``BackBroker`` semantics are untouched.

UNIT/FAKE: fake facade + real ``backtrader.live_state`` in ``tmp_path``.
"""

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
    SYMBOL,
    TODAY,
    crash,
    drain,
    last_status,
    native_identity,
    order_event,
    position,
    quiet,
    snap,
    trade_event,
)

# The demo pattern (0.13 then lots of 0.01) and two sums with opposite residues.
DEMO = [0.13] + [0.01] * 7 + [0.8]  # remsize -1.1e-16, the sell leg -1.1e-16
MANY_LOTS = [0.13] + [0.01] * 87  # executed 1.0000000000000007
TENTHS = [0.1] * 10  # executed 0.9999999999999999
PATTERNS = pytest.mark.parametrize(
    "fills", [DEMO, MANY_LOTS, TENTHS], ids=["demo", "lots", "tenths"]
)


def _okx_fill(call, trade_id, qty, **kwargs):
    """An OKX-like trade return: own identity, no venue exchange id, fractional size."""
    fields = {key: call.identity.fields[key] for key in ("front_id", "session_id", "order_ref")}
    identity = NativeOrderIdentity(
        exchange_name=EXCHANGE, client_order_id=call.identity.client_order_id, fields=fields
    )
    return _trade(identity, trade_id, qty, **kwargs)


def _client_identity(client_order_id):
    """A client-order-id-only identity (OKX/Binance routes)."""
    return NativeOrderIdentity(
        exchange_name=EXCHANGE,
        client_order_id=client_order_id,
        fields={"inst_id": SYMBOL, "trading_day": TODAY},
        session_generation=1,
    )


def _trade(identity, trade_id, qty, *, side="buy", offset="open", sys_id="OKX-1", price=3500.0):
    return DirectExecutionEvent(
        kind=DirectExecutionEventKind.TRADE,
        exchange_name=EXCHANGE,
        symbol=SYMBOL,
        identity=identity,
        exchange_order_id=sys_id,
        side=side,
        offset=offset,
        trade_id=trade_id,
        trade_price=price,
        trade_qty=qty,
        trading_day=TODAY,
    )


def _place(env, broker, side, size, **kwargs):
    method = broker.buy if side == "buy" else broker.sell
    order = method(env.strategy, env.feed, size, price=3500.0, exectype=bt.Order.Limit, **kwargs)
    assert order.status == bt.Order.Submitted, order.info.get("error_code")
    call = env.api.place_calls[-1]
    return order, call


def _accept(env, broker, order, call, sys_id, offset="open"):
    env.api.push(
        order_event(
            call.identity,
            "accepted",
            sys_id=sys_id,
            side="buy" if order.isbuy() else "sell",
            offset=offset,
            qty=abs(order.size),
        )
    )
    broker.next()


def _fill(env, broker, events):
    for event in events:
        env.api.push(event)
        broker.next()


def _marker(env, call):
    marker = env.state().pending.get(call.marker_id)
    return marker["status"], marker["facts"].get("final_status")


def _ctp_fills(prefix, sys_id, fills, **kwargs):
    return [
        trade_event(f"{prefix}{index}", sys_id=sys_id, qty=qty, **kwargs)
        for index, qty in enumerate(fills)
    ]


# ---------------------------------------------------------------------------
# OKX-like route (no venue offsets): the reported defect
# ---------------------------------------------------------------------------
@PATTERNS
def test_fractional_fills_complete_the_buy_and_the_closing_sell(env, fills):
    broker = env.start(first_init=True, require_offset=False)
    quiet(broker)
    buy, call = _place(env, broker, "buy", 1.0)
    _accept(env, broker, buy, call, "OKX-1")
    _fill(env, broker, [_okx_fill(call, f"B{i}", qty) for i, qty in enumerate(fills)])
    assert buy.status == bt.Order.Completed
    assert buy.executed.size == 1.0 and buy.executed.remsize == 0.0
    assert _marker(env, call) == ("TERMINAL", "filled")
    assert last_status(drain(broker))[-1] == "Completed"
    long_leg = broker.getposition(env.feed, side="long")
    assert long_leg.size == 1.0 and broker.getposition(env.feed).size == 1.0
    assert env.state().snapshot.read()["positions"][SYMBOL]["long"]["total"] == 1

    sell, call = _place(env, broker, "sell", 1.0)
    _accept(env, broker, sell, call, "OKX-2", offset="close")
    _fill(
        env,
        broker,
        [
            _okx_fill(call, f"S{i}", qty, side="sell", offset="close", sys_id="OKX-2")
            for i, qty in enumerate(fills)
        ],
    )
    assert sell.status == bt.Order.Completed
    assert sell.executed.size == -1.0 and sell.executed.remsize == 0.0
    assert _marker(env, call) == ("TERMINAL", "filled")
    long_leg = broker.getposition(env.feed, side="long")
    assert long_leg.size == 0 and long_leg.price == 0.0  # no 1e-16 phantom leg
    assert broker.getposition(env.feed, side="short").size == 0
    assert broker.getposition(env.feed).size == 0
    assert all(bit.opened == 0 for bit in sell.executed.exbits)  # no phantom reversal
    assert env.state().snapshot.read()["positions"] == {}
    summary = broker.stop()
    assert summary["status"] == "STOPPED" and summary["unresolved_working_orders"] == 0
    assert env.state().pending.active() == []


# ---------------------------------------------------------------------------
# CTP-style route: explicit offsets, today/yesterday split
# ---------------------------------------------------------------------------
@PATTERNS
def test_fractional_open_and_close_today_keep_exact_legs_and_split(env, fills):
    broker = env.start(first_init=True)
    quiet(broker)
    buy, call = _place(env, broker, "buy", 1.0, offset="open")
    _accept(env, broker, buy, call, "8001")
    _fill(env, broker, _ctp_fills("O", "8001", fills))
    assert buy.status == bt.Order.Completed and _marker(env, call) == ("TERMINAL", "filled")
    view = broker.get_closable(env.feed, "long")
    assert view["total"] == 1.0 and view["today"] == 1.0 and view["closable_today"] == 1.0
    assert env.state().snapshot.read()["positions"][SYMBOL]["long"] == {
        "total": 1,
        "today": 1,
        "yesterday": 0,
    }

    sell, call = _place(env, broker, "sell", 1.0, offset="close_today")
    _accept(env, broker, sell, call, "8002", offset="close_today")
    _fill(env, broker, _ctp_fills("C", "8002", fills, side="sell", offset="close_today"))
    assert sell.status == bt.Order.Completed and _marker(env, call) == ("TERMINAL", "filled")
    view = broker.get_closable(env.feed, "long")
    assert view["total"] == 0 and view["today"] == 0 and view["closable"] == 0
    assert broker.getposition(env.feed).size == 0
    assert env.state().snapshot.read()["positions"] == {}


def test_hedged_legs_report_an_exact_net_position(env):
    broker = env.start(first_init=True)
    quiet(broker)
    buy, call = _place(env, broker, "buy", 0.3, offset="open")
    _accept(env, broker, buy, call, "8101")
    _fill(env, broker, _ctp_fills("L", "8101", [0.1, 0.1, 0.1]))
    sell, call = _place(env, broker, "sell", 0.1, offset="open")
    _accept(env, broker, sell, call, "8102")
    _fill(env, broker, _ctp_fills("H", "8102", [0.1], side="sell"))
    assert buy.status == sell.status == bt.Order.Completed
    assert broker.getposition(env.feed, side="long").size == 0.3
    assert broker.getposition(env.feed).size == 0.2  # not 0.19999999999999998
    entry = env.state().snapshot.read()["positions"][SYMBOL]
    assert (entry["long"]["total"], entry["short"]["total"], entry["net"]) == (0.3, 0.1, 0.2)


def _long_03(env, broker, sys_id):
    buy, call = _place(env, broker, "buy", 0.3, offset="open")
    _accept(env, broker, buy, call, sys_id)
    _fill(env, broker, _ctp_fills("L", sys_id, [0.1, 0.1, 0.1]))
    assert buy.status == bt.Order.Completed


def test_working_close_orders_leave_an_exact_closable_view(env):
    broker = env.start(first_init=True)
    quiet(broker)
    _long_03(env, broker, "8201")
    _place(env, broker, "sell", 0.1, offset="close_today")
    view = broker.get_closable(env.feed, "long")
    # 0.3 - 0.1 is 0.19999999999999998 in floats
    assert view["frozen_close"] == 0.1 and view["closable_today"] == 0.2
    assert view["closable"] == 0.2
    _place(env, broker, "sell", 0.2, offset="close")  # SHFE: a plain close is yesterday's
    view = broker.get_closable(env.feed, "long")
    assert view["frozen_close"] == 0.3 and view["closable"] == 0  # 0.2 + 0.1 in floats is not


def test_same_offset_close_orders_freeze_an_exact_volume(env):
    broker = env.start(first_init=True)
    quiet(broker)
    _long_03(env, broker, "8202")
    _place(env, broker, "sell", 0.1, offset="close_today")
    _place(env, broker, "sell", 0.2, offset="close_today")
    view = broker.get_closable(env.feed, "long")
    assert view["frozen_close"] == 0.3 and view["closable_today"] == 0


def test_close_yesterday_consumes_an_exact_yesterday_volume(env):
    env.init_flat()
    env.write_snapshot({SYMBOL: snap(long=(0.3, 0, 0.3))})
    env.api.positions = [position("long", 0.3, 0, 0.3)]
    broker = env.start()
    quiet(broker)
    assert broker.direct_writes_blocked() == {}
    close, call = _place(env, broker, "sell", 0.1, offset="close_yesterday")
    _accept(env, broker, close, call, "8401", offset="close_yesterday")
    _fill(env, broker, _ctp_fills("Y", "8401", [0.1], side="sell", offset="close_yesterday"))
    assert close.status == bt.Order.Completed
    view = broker.get_closable(env.feed, "long")
    # 0.3 - 0.1 is 0.19999999999999998 in floats
    assert view["yesterday"] == 0.2 and view["closable_yesterday"] == 0.2
    assert view["total"] == 0.2
    entry = env.state().snapshot.read()["positions"][SYMBOL]["long"]
    assert entry == {"total": 0.2, "today": 0, "yesterday": 0.2}
    crash(broker)


def test_foreign_working_close_orders_freeze_an_exact_volume(env):
    """Another client's working close orders on the account (D62-17) freeze 0.1 + 0.2."""
    env.init_flat()
    env.write_snapshot({SYMBOL: snap(long=(0.3, 0.3, 0))})
    env.api.positions = [position("long", 0.3, 0.3, 0)]
    env.api.active_orders = [
        order_event(
            native_identity(ref),
            "accepted",
            sys_id=sys_id,
            side="sell",
            offset="close_today",
            qty=qty,
        )
        for ref, sys_id, qty in (("990000000001", "9901", 0.1), ("990000000002", "9902", 0.2))
    ]
    broker = env.start()
    quiet(broker)
    assert broker.get_direct_reconcile_report()["foreign_working_orders"] == 2
    view = broker.get_closable(env.feed, "long")
    assert view["frozen_close"] == 0.3 and view["closable_today"] == 0
    crash(broker)


# ---------------------------------------------------------------------------
# cancel after fractional fills
# ---------------------------------------------------------------------------
def test_cancel_after_fractional_fills_keeps_the_exact_executed_size(env):
    broker = env.start(first_init=True, require_offset=False)
    quiet(broker)
    order, call = _place(env, broker, "buy", 1.0)
    _accept(env, broker, order, call, "OKX-3")
    fills = [0.13, 0.01, 0.01]
    _fill(env, broker, [_okx_fill(call, f"P{i}", q, sys_id="OKX-3") for i, q in enumerate(fills)])
    assert order.status == bt.Order.Partial
    broker.cancel(order)
    env.api.push(order_event(call.identity, "cancelled", sys_id="OKX-3", qty=1.0, filled=0.15))
    broker.next()
    assert order.status == bt.Order.Canceled
    assert order.executed.size == 0.15 and order.executed.remsize == 0.85
    assert _marker(env, call) == ("TERMINAL", "cancelled")
    assert broker.getposition(env.feed, side="long").size == 0.15
    assert env.state().snapshot.read()["positions"][SYMBOL]["long"]["total"] == 0.15
    assert broker.stop()["status"] == "STOPPED"


def test_cancelled_return_ahead_of_its_fractional_fills(env):
    broker = env.start(first_init=True, require_offset=False)
    quiet(broker)
    order, call = _place(env, broker, "sell", 1.0)
    _accept(env, broker, order, call, "OKX-4")
    env.api.push(
        order_event(call.identity, "cancelled", sys_id="OKX-4", side="sell", qty=1.0, filled=0.15)
    )
    broker.next()
    assert order.alive()  # its fills are still to come
    fills = [0.13, 0.01, 0.01]
    _fill(
        env,
        broker,
        [_okx_fill(call, f"Q{i}", q, side="sell", sys_id="OKX-4") for i, q in enumerate(fills)],
    )
    assert order.status == bt.Order.Canceled
    assert order.executed.size == -0.15 and order.executed.remsize == -0.85
    assert _marker(env, call) == ("TERMINAL", "cancelled")
    assert broker.getposition(env.feed, side="short").size == 0.15


def test_cancelled_return_waits_while_fills_are_short_of_the_venue_cumulative(env):
    broker = env.start(first_init=True, require_offset=False)
    quiet(broker)
    order, call = _place(env, broker, "buy", 1.0)
    env.api.push(order_event(call.identity, "cancelled", sys_id="OKX-5", qty=1.0, filled=0.15))
    broker.next()
    _fill(env, broker, [_okx_fill(call, "R0", 0.13, sys_id="OKX-5")])
    assert order.status == bt.Order.Partial  # 0.02 still to come: never a residue
    _fill(env, broker, [_okx_fill(call, "R1", 0.02, sys_id="OKX-5")])
    assert order.status == bt.Order.Canceled and order.executed.size == 0.15


# ---------------------------------------------------------------------------
# restart: the restored order's base and remaining size
# ---------------------------------------------------------------------------
def test_restored_order_base_and_remaining_fills_are_exact(env):
    """CTP-style: the base is the listed fills (0.15, not 0.15000000000000002)."""
    env.init_flat()
    _marker_id, identity = env.seed_marker("000000000801")
    env.api.active_orders = [
        order_event(identity, "partially_filled", sys_id="8301", qty=0.7, filled=0.15)
    ]
    env.api.trades = _ctp_fills("T", "8301", [0.13, 0.01, 0.01])
    env.api.positions = [position("long", 0.15, 0.15, 0)]
    broker = env.start()
    quiet(broker)
    assert broker.direct_writes_blocked() == {}
    assert broker.getposition(env.feed, side="long").size == 0.15
    (restored,) = broker.take_over_restored_orders(env.strategy)
    # 0.7 - 0.15000000000000002 would be 0.5499999999999999
    assert restored.info["venue_filled_before"] == 0.15 and restored.size == 0.55
    _fill(env, broker, _ctp_fills("U", "8301", [0.05] * 11))
    assert restored.status == bt.Order.Completed
    assert restored.executed.size == 0.55 and restored.executed.remsize == 0.0
    assert broker.getposition(env.feed, side="long").size == 0.7
    assert "fill_gaps" not in broker.get_direct_reconcile_report()
    crash(broker)


def test_restored_client_order_id_order_completes_on_fractional_fills(env):
    """OKX/Binance route: the restored order is the venue's remaining 0.87."""
    env.init_flat()
    identity = _client_identity("btabc0000000r1")
    env.seed_marker("", identity=identity)
    env.write_snapshot({SYMBOL: snap(long=(0.13, None, None))})
    env.api.active_orders = [
        order_event(identity, "partially_filled", sys_id="OKX-7", qty=1.0, filled=0.13)
    ]
    env.api.positions = [position("long", 0.13, venue=None)]
    broker = env.start(require_offset=False)
    quiet(broker)
    assert broker.direct_writes_blocked() == {}
    (restored,) = broker.take_over_restored_orders(env.strategy)
    assert restored.size == 0.87 and restored.info["venue_filled_before"] == 0.13
    _fill(
        env, broker, [_trade(identity, f"W{i}", q, sys_id="OKX-7") for i, q in enumerate(DEMO[1:])]
    )
    assert restored.status == bt.Order.Completed
    assert restored.executed.size == 0.87 and restored.executed.remsize == 0.0
    assert broker.getposition(env.feed, side="long").size == 1.0
    assert broker.stop()["status"] == "STOPPED"


# ---------------------------------------------------------------------------
# venue quantities that carry float noise: only the tolerance absorbs it
# ---------------------------------------------------------------------------
def test_noisy_quantities_within_the_tolerance_complete_and_flatten(env):
    noisy = 0.1 + 0.2  # 0.30000000000000004, e.g. a quantity computed in floats upstream
    broker = env.start(first_init=True, require_offset=False)
    quiet(broker)
    buy, call = _place(env, broker, "buy", 0.6)
    _fill(env, broker, [_okx_fill(call, f"N{i}", noisy) for i in range(2)])
    assert buy.status == bt.Order.Completed and _marker(env, call) == ("TERMINAL", "filled")
    assert buy.executed.size == 0.6 and buy.executed.remsize == 0.0
    # The leg keeps the venue's noisy sum (0.6000000000000001); a clean 0.6
    # close leaves 1e-16, which is flat, not a remaining position.
    assert broker.getposition(env.feed, side="long").size == pytest.approx(0.6, abs=1e-12)
    sell, call = _place(env, broker, "sell", 0.6)
    _fill(env, broker, [_okx_fill(call, "M0", 0.6, side="sell", offset="close", sys_id="OKX-8")])
    assert sell.status == bt.Order.Completed and _marker(env, call) == ("TERMINAL", "filled")
    long_leg = broker.getposition(env.feed, side="long")
    assert long_leg.size == 0 and long_leg.price == 0.0
    assert broker.getposition(env.feed, side="short").size == 0
    assert broker.getposition(env.feed).size == 0
    assert all(bit.opened == 0 for bit in sell.executed.exbits)
    assert env.state().snapshot.read()["positions"] == {}


def test_fill_gap_report_of_a_restored_order_is_exact(env, monkeypatch):
    """The applied side of a fill gap is the restored base plus the fills (0.1 + 0.2)."""
    now = {"t": 1000.0}
    monkeypatch.setattr(direct_mode, "_monotonic", lambda: now["t"])
    env.init_flat()
    identity = _client_identity("btabc0000000r2")
    env.seed_marker("", identity=identity)
    env.write_snapshot({SYMBOL: snap(long=(0.1, None, None))})
    env.api.active_orders = [
        order_event(identity, "partially_filled", sys_id="OKX-9", qty=1.0, filled=0.1)
    ]
    env.api.positions = [position("long", 0.1, venue=None)]
    broker = env.start(require_offset=False)
    quiet(broker)
    (restored,) = broker.take_over_restored_orders(env.strategy)
    _fill(env, broker, [_trade(identity, f"G{i}", 0.1, sys_id="OKX-9") for i in range(2)])
    assert restored.executed.size == 0.2
    env.api.push(order_event(identity, "partially_filled", sys_id="OKX-9", qty=1.0, filled=0.5))
    broker.next()
    now["t"] += 5.1  # past the trade-match window: the gap opens
    broker.next()
    (entry,) = broker.get_direct_reconcile_report()["fill_gaps"]["open"].values()
    assert (entry["venue_filled"], entry["applied"]) == (0.5, 0.3)  # 0.1 + 0.2 in floats is not 0.3
    crash(broker)


# ---------------------------------------------------------------------------
# a real remainder is never snapped away
# ---------------------------------------------------------------------------
def test_one_lot_short_stays_partial(env):
    broker = env.start(first_init=True, require_offset=False)
    quiet(broker)
    order, call = _place(env, broker, "buy", 1.0)
    _fill(env, broker, [_okx_fill(call, f"V{i}", 0.01) for i in range(99)])
    assert order.status == bt.Order.Partial
    assert order.executed.size == 0.99 and order.executed.remsize == 0.01
    _fill(env, broker, [_okx_fill(call, "V99", 0.01)])
    assert order.status == bt.Order.Completed and order.executed.size == 1.0


def test_quantity_tolerance_scales_with_the_quantity():
    assert direct_mode._qty_tol(0.002) == pytest.approx(1e-9)
    assert direct_mode._qty_tol(-5000.0) == pytest.approx(5e-6)
    assert direct_mode._qty_sum(0.13, 0.01, 0.01) == 0.15
    assert direct_mode._qty_sum(1.0, -0.13, -0.87) == 0.0
