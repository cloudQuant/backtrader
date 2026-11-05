"""Order submission, returns, fills and cancel in direct mode (R-10, D62-15a/26/31/33).

UNIT/FAKE: fake facade + real ``backtrader.live_state`` in ``tmp_path``.
"""

import datetime as dt
from decimal import Decimal

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from backtrader.brokers._btapi_direct_mode import DirectModeError

from ._fakes import (
    SYMBOL,
    TODAY,
    VENUE,
    drain,
    last_status,
    native_identity,
    not_live,
    not_qualified,
    order_event,
    position,
    snap,
    trade_event,
)


def _order(env, broker, side="buy", size=1, **kwargs):
    kwargs.setdefault("price", 3500.0)
    kwargs.setdefault("exectype", bt.Order.Limit)
    method = broker.buy if side == "buy" else broker.sell
    return method(env.strategy, env.feed, size, **kwargs)


def _accepted(env, broker, order, sys_id):
    call = env.api.place_calls[-1]
    env.api.push(
        order_event(
            call.identity,
            "accepted",
            sys_id=sys_id,
            side="buy" if order.isbuy() else "sell",
            offset=order.info.get("offset") or "open",
            qty=abs(order.size),
        )
    )
    broker.next()
    return call


@pytest.fixture
def broker(env):
    return env.start(first_init=True)


# ---------------------------------------------------------------------------
# local refusals (nothing reaches the SDK)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kwargs, reason",
    [
        ({}, "explicit_offset_required"),
        ({"offset": "open", "exectype": bt.Order.Stop}, "order_type_unrepresentable"),
        (
            {"offset": "open", "exectype": bt.Order.StopLimit, "plimit": 3501.0},
            "order_type_unrepresentable",
        ),
        ({"offset": "open", "valid": dt.timedelta(hours=1)}, "order_validity_unrepresentable"),
        (
            {"offset": "open", "valid": dt.datetime(2026, 11, 6, 15, 0)},
            "order_validity_unrepresentable",
        ),
        ({"offset": "close"}, "insufficient_closable_position"),
        ({"offset": "close_today"}, "insufficient_closable_position"),
    ],
)
def test_precheck_refusals_never_reach_the_sdk(env, broker, kwargs, reason):
    order = _order(env, broker, side="sell", **kwargs)
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == reason
    assert env.api.place_calls == []
    assert last_status(drain(broker)) == ["Rejected"]
    assert env.state().pending.active() == []


def test_target_feed_not_live_is_refused_locally(env, broker):
    not_live(env.feed)
    order = _order(env, broker, offset="open")
    assert order.info["error_code"] == "target_feed_not_live"
    assert env.api.place_calls == []


def test_unqualified_target_data_is_refused_but_other_feeds_do_not_matter(env, broker):
    not_live(env.other_feed)  # D62-15b: only the target data counts
    assert _order(env, broker, offset="open").status == bt.Order.Submitted
    not_qualified(env.feed, "SOURCE_STALE")
    order = _order(env, broker, offset="open")
    assert order.info["error_code"] == "target_data_not_tradable:SOURCE_STALE"


def test_write_admission_disabled_refuses_writes_and_skips_settlement(env):
    env.api.write_admission.enabled = False
    broker = env.start(first_init=True)
    assert env.api.settlement_calls == []
    assert broker.direct_writes_blocked() == {"*": "write_admission_disabled"}
    order = _order(env, broker, offset="open")
    assert order.info["error_code"] == "write_admission_disabled"
    assert env.api.place_calls == []


def test_unknown_closable_split_refuses_close_today_but_not_plain_close(env):
    env.init_flat()
    env.write_snapshot({SYMBOL: snap(long=(2, None, None))})
    env.api.positions = [position("long", 2, None, None)]
    broker = env.start()
    refused = _order(env, broker, side="sell", offset="close_today")
    assert refused.info["error_code"] == "closable_unknown"
    refused = _order(env, broker, side="sell", offset="close_yesterday")
    assert refused.info["error_code"] == "closable_unknown"
    plain = _order(env, broker, side="sell", size=2, offset="close")
    assert plain.status == bt.Order.Submitted


def test_closing_more_than_the_closable_volume_is_refused(env):
    env.init_flat()
    env.write_snapshot({SYMBOL: snap(long=(2, 1, 1))})
    env.api.positions = [position("long", 2, 1, 1)]
    broker = env.start()
    assert (
        _order(env, broker, side="sell", size=2, offset="close_today").info["error_code"]
        == "insufficient_closable_position"
    )
    assert (
        _order(env, broker, side="sell", size=3, offset="close").info["error_code"]
        == "insufficient_closable_position"
    )
    # Whole sides are closable (an order never freezes against itself).
    assert _order(env, broker, side="sell", size=1, offset="close_today").status == (
        bt.Order.Submitted
    )
    assert _order(env, broker, side="sell", size=1, offset="close_yesterday").status == (
        bt.Order.Submitted
    )
    # Both working closes now freeze the whole long side.
    assert (
        _order(env, broker, side="sell", size=1, offset="close").info["error_code"]
        == "insufficient_closable_position"
    )


def test_closable_view_reports_venue_and_requires_direct_mode(env, broker):
    view = broker.get_closable(env.feed, "long")
    assert view["venue"] is None and view["total"] == 0
    env.store.direct_write_mode = False
    with pytest.raises(DirectModeError) as err:
        env.broker().get_closable(env.feed, "long")
    assert err.value.code == "closable_view_requires_direct_mode"


def test_sdk_refusal_before_send_rejects_the_order(env, broker):
    from bt_api_base.direct_write_protocol import WriteAdmissionDenied

    env.api.make_order_error = WriteAdmissionDenied("write_admission_disabled", "x")
    order = _order(env, broker, offset="open")
    assert order.info["error_code"] == "direct_write_refused:write_admission_disabled"


# ---------------------------------------------------------------------------
# happy path: open, fills, close_today
# ---------------------------------------------------------------------------
def test_open_fill_and_close_today_round_trip(env, broker):
    order = _order(env, broker, size=2, offset="open")
    assert order.status == bt.Order.Submitted
    assert order.info["local_seq"] == 1
    (call,) = env.api.place_calls
    assert call.durable_before_send is True  # marker durable before the "send"
    assert call.host_scope == broker._direct_uuid
    request = call.request
    assert request.symbol == SYMBOL and request.side.value.lower() == "buy"
    assert request.quantity == Decimal("2.0") and request.price == Decimal("3500.0")
    assert request.offset == "open" and request.time_in_force == "GFD"
    assert call.summary["local_seq"] == 1 and call.summary["bt_ref"] == order.ref
    marker = env.state().pending.get(call.marker_id)
    assert marker["status"] == "DISPATCHED" and marker["local_seq"] == 1
    assert marker["bt_ref"] == order.ref
    assert last_status(drain(broker)) == ["Submitted"]

    _accepted(env, broker, order, "1001")
    assert order.status == bt.Order.Accepted
    marker = env.state().pending.get(call.marker_id)
    assert marker["status"] == "ACCEPTED" and marker["facts"]["order_sys_id"] == "1001"

    env.api.push(trade_event("T1", sys_id="1001", qty=1, price=3500.0))
    broker.next()
    assert order.status == bt.Order.Partial
    assert broker.getposition(env.feed, side="long").size == 1
    snapshot = env.state().snapshot.read()
    assert snapshot["positions"][SYMBOL]["long"] == {"total": 1, "today": 1, "yesterday": 0}

    env.api.push(trade_event("T1", sys_id="1001", qty=1, price=3500.0))  # duplicate return
    broker.next()
    assert broker.getposition(env.feed, side="long").size == 1
    assert order.executed.size == 1

    env.api.push(trade_event("T2", sys_id="1001", qty=1, price=3510.0))
    broker.next()
    assert order.status == bt.Order.Completed
    assert broker.getposition(env.feed).size == 2
    assert broker.getposition(env.feed, side="long").price == pytest.approx(3505.0)
    assert env.state().pending.get(call.marker_id)["status"] == "TERMINAL"
    snapshot = env.state().snapshot.read()
    assert snapshot["positions"][SYMBOL]["long"] == {"total": 2, "today": 2, "yesterday": 0}
    assert snapshot["applied_trades"][TODAY] == [
        f"{VENUE}|T1|buy|1001",
        f"{VENUE}|T2|buy|1001",
    ]
    assert last_status(drain(broker)) == ["Accepted", "Partial", "Completed"]

    view = broker.get_closable(env.feed, "long")
    assert view["closable_today"] == 2 and view["closable_yesterday"] == 0
    assert view["venue"] == VENUE

    close = _order(env, broker, side="sell", size=2, offset="close_today")
    assert close.status == bt.Order.Submitted, close.info.get("error_code")
    assert env.api.place_calls[-1].request.offset == "close_today"
    assert env.api.place_calls[-1].request.exchange_id == VENUE
    assert broker.get_closable(env.feed, "long")["closable_today"] == 0  # frozen
    _accepted(env, broker, close, "1002")
    env.api.push(
        trade_event("T3", sys_id="1002", side="sell", offset="close_today", qty=2, price=3520.0)
    )
    broker.next()
    assert close.status == bt.Order.Completed
    assert broker.getposition(env.feed).size == 0
    assert broker.getposition(env.feed, side="long").size == 0
    assert close.executed.pnl == pytest.approx(2 * (3520.0 - 3505.0))
    view = broker.get_closable(env.feed, "long")
    assert view["today"] == 0 and view["total"] == 0
    assert env.state().snapshot.read()["positions"] == {}


def test_short_open_and_buy_close_today(env, broker):
    order = _order(env, broker, side="sell", size=1, offset="open")
    _accepted(env, broker, order, "2001")
    env.api.push(trade_event("S1", sys_id="2001", side="sell", qty=1, price=3500.0))
    broker.next()
    assert broker.getposition(env.feed).size == -1
    assert broker.getposition(env.feed, side="short").size == 1
    assert env.state().snapshot.read()["positions"][SYMBOL]["net"] == -1

    close = _order(env, broker, side="buy", size=1, offset="close_today")
    assert close.status == bt.Order.Submitted, close.info.get("error_code")
    _accepted(env, broker, close, "2002")
    env.api.push(
        trade_event("S2", sys_id="2002", side="buy", offset="close_today", qty=1, price=3490.0)
    )
    broker.next()
    assert broker.getposition(env.feed).size == 0
    assert close.executed.pnl == pytest.approx(10.0)


def test_plain_close_on_a_split_venue_consumes_yesterday(env):
    env.init_flat()
    env.write_snapshot({SYMBOL: snap(long=(2, 1, 1))})
    env.api.positions = [position("long", 2, 1, 1)]
    broker = env.start()
    close = _order(env, broker, side="sell", size=1, offset="close")
    _accepted(env, broker, close, "3001")
    env.api.push(trade_event("C1", sys_id="3001", side="sell", offset="close", qty=1))
    broker.next()
    view = broker.get_closable(env.feed, "long")
    assert view["today"] == 1 and view["yesterday"] == 0 and view["venue"] == VENUE


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------
def test_cancel_uses_original_identity_and_learned_order_sys_id(env, broker):
    order = _order(env, broker, offset="open")
    call = _accepted(env, broker, order, "4001")
    drain(broker)
    broker.cancel(order)
    (cancel,) = env.api.cancel_calls
    assert cancel.symbol == SYMBOL
    assert cancel.target.client_order_id == call.identity.client_order_id
    for key in ("front_id", "session_id", "order_ref", "exchange_id", "trading_day"):
        assert cancel.target.fields[key] == call.identity.fields[key]
    assert cancel.target.fields["order_sys_id"] == "4001"
    cancel_marker = env.state().pending.get(cancel.marker_id)
    assert cancel_marker["operation"] == "cancel" and cancel_marker["status"] == "DISPATCHED"
    assert cancel_marker["bt_ref"] == order.ref

    broker.cancel(order)  # already requested: no second venue cancel
    assert len(env.api.cancel_calls) == 1

    env.api.push(order_event(call.identity, "cancelled", sys_id="4001"))
    broker.next()
    assert order.status == bt.Order.Canceled
    assert last_status(drain(broker)) == ["Canceled"]
    place_marker = env.state().pending.get(call.marker_id)
    assert place_marker["facts"]["final_status"] == "cancelled"
    assert env.state().pending.get(cancel.marker_id)["status"] == "TERMINAL"
    assert env.state().pending.active() == []


def test_cancel_error_return_allows_a_new_cancel(env, broker):
    from bt_api_base.direct_write_protocol import DirectExecutionEventKind

    order = _order(env, broker, offset="open")
    call = _accepted(env, broker, order, "4101")
    broker.cancel(order)
    env.api.push(
        order_event(
            call.identity,
            "accepted",
            sys_id="4101",
            kind=DirectExecutionEventKind.CANCEL_ERROR,
            error_code="26",
        )
    )
    broker.next()
    assert order.alive() and order.info["cancel_error"] == "26"
    broker.cancel(order)
    assert len(env.api.cancel_calls) == 2


def test_cancelled_return_waits_for_its_in_flight_trades(env, broker):
    order = _order(env, broker, size=3, offset="open")
    call = _accepted(env, broker, order, "4201")
    env.api.push(order_event(call.identity, "cancelled", sys_id="4201", qty=3, filled=2))
    broker.next()
    assert order.alive()  # two lots of trades are still to come
    env.api.push(trade_event("F1", sys_id="4201", qty=1))
    broker.next()
    assert order.status == bt.Order.Partial
    env.api.push(trade_event("F2", sys_id="4201", qty=1))
    broker.next()
    assert order.status == bt.Order.Canceled
    assert order.executed.size == 2
    assert broker.getposition(env.feed).size == 2


def test_venue_rejection_return_rejects_the_order(env, broker):
    from bt_api_base.direct_write_protocol import DirectExecutionEventKind

    order = _order(env, broker, offset="open")
    call = env.api.place_calls[-1]
    env.api.push(
        order_event(
            call.identity,
            "rejected",
            sys_id=None,
            kind=DirectExecutionEventKind.ORDER_ERROR,
            error_code="31",
        )
    )
    broker.next()
    assert order.status == bt.Order.Rejected and order.info["error_code"] == "31"
    assert env.state().pending.get(call.marker_id)["facts"]["final_status"] == "rejected"


# ---------------------------------------------------------------------------
# send outcomes
# ---------------------------------------------------------------------------
def test_definitely_not_sent_rejects_and_closes_the_marker(env, broker):
    env.api.outcomes.append({"sent": False, "error_code": "session_changed_before_dispatch"})
    order = _order(env, broker, offset="open")
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == "not_sent:session_changed_before_dispatch"
    marker = env.state().pending.get(env.api.place_calls[-1].marker_id)
    assert marker["status"] == "TERMINAL" and marker["facts"]["final_status"] == "not_sent"
    assert broker.direct_writes_blocked() == {}


def test_unknown_send_outcome_blocks_symbol_until_identity_matched_return(env, broker):
    env.api.outcomes.append({"sent": None, "error_code": "ctp_direct_submit_outcome_unknown"})
    order = _order(env, broker, offset="open")
    call = env.api.place_calls[-1]
    assert order.status == bt.Order.Submitted and order.info["outcome_unknown"] is True
    assert broker.direct_writes_blocked() == {SYMBOL: "pending_unknown"}
    marker = env.state().pending.get(call.marker_id)
    assert marker["status"] == "DISPATCHED" and marker["facts"]["send_outcome"] == "unknown"
    assert _order(env, broker, offset="open").info["error_code"] == "pending_unknown"
    assert len(env.api.place_calls) == 1

    # A return for someone else's identity proves nothing about this order.
    env.api.push(order_event(native_identity("000000000999"), "accepted", sys_id="9999"))
    broker.next()
    assert broker.direct_writes_blocked() == {SYMBOL: "pending_unknown"}

    env.api.push(order_event(call.identity, "accepted", sys_id="5001"))
    broker.next()
    assert order.status == bt.Order.Accepted
    assert broker.direct_writes_blocked() == {}
    assert _order(env, broker, offset="open").status == bt.Order.Submitted


def test_day_validity_is_allowed_and_recorded(env, broker):
    order = _order(env, broker, offset="open", valid=bt.Order.DAY)
    assert order.status == bt.Order.Submitted
    assert order.info["valid_intent"] == {"kind": "day", "value": None}


def test_market_orders_are_passed_through(env, broker):
    order = _order(env, broker, offset="open", exectype=bt.Order.Market, price=None)
    assert order.status == bt.Order.Submitted
    assert env.api.place_calls[-1].request.price is None


def test_quantity_unit_follows_contract_metadata(env, broker):
    """OKX SWAP sizes are contract counts: the unit comes from the Store metadata."""
    env.store.contract_metadata = {SYMBOL: {"quantity_unit": "contracts"}}
    _order(env, broker, offset="open")
    assert env.api.place_calls[-1].request.quantity_unit == "contracts"
    env.store.contract_metadata = {}
    _order(env, broker, offset="open")
    assert env.api.place_calls[-1].request.quantity_unit == "base"


def test_facts_reads_are_scoped_to_the_configured_symbols(env):
    env.store._sdk_routes = {SYMBOL: "CTP___FUTURE"}
    env.start(first_init=True)
    assert env.api.facts_calls and all(
        call.get("symbols") == [SYMBOL] for call in env.api.facts_calls
    )
