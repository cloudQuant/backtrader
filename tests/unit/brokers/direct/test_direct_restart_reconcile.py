"""Restart reconciliation and pending markers (D62-14/16/17/22, R-3).

UNIT/FAKE: fake facade + real ``backtrader.live_state`` in ``tmp_path``.
"""

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt

from ._fakes import (
    OTHER_SYMBOL,
    SYMBOL,
    TODAY,
    VENUE,
    YESTERDAY,
    crash,
    drain,
    native_identity,
    order_event,
    position,
    snap,
    trade_event,
)


def _buy(env, broker, size=1, offset="open"):
    return broker.buy(
        env.strategy, env.feed, size, price=3500.0, exectype=bt.Order.Limit, offset=offset
    )


# ---------------------------------------------------------------------------
# snapshot vs venue positions
# ---------------------------------------------------------------------------
def test_snapshot_equal_to_venue_starts_without_blocks(env):
    env.init_flat()
    env.write_snapshot({SYMBOL: snap(long=(2, 2, 0))})
    env.api.positions = [position("long", 2, 2, 0), position("short", 0, 0, 0)]
    broker = env.start()
    report = broker.get_direct_reconcile_report()
    assert report["mismatches"] == [] and report["other_instruments"] == []
    assert broker.direct_writes_blocked() == {}
    assert broker.getposition(env.feed).size == 2
    assert broker.getposition(env.feed, side="long").size == 2
    assert broker.getposition(env.feed, side="short").size == 0
    view = broker.get_closable(env.feed, "long")
    assert view["total"] == 2 and view["today"] == 2 and view["closable_today"] == 2


@pytest.mark.parametrize(
    "venue_rows, side, local, remote",
    [
        ([position("long", 3, 3, 0)], "long", 2, 3),
        ([position("long", 1, 1, 0)], "long", 2, 1),
        ([], "long", 2, 0),
        ([position("long", 2, 2, 0), position("short", 1, 1, 0)], "short", 0, 1),
    ],
)
def test_side_total_mismatch_blocks_the_symbol(env, venue_rows, side, local, remote):
    env.init_flat()
    env.write_snapshot({SYMBOL: snap(long=(2, 2, 0))})
    env.api.positions = venue_rows
    broker = env.start()
    assert broker.direct_writes_blocked() == {SYMBOL: "startup_position_mismatch"}
    mismatches = broker.get_direct_reconcile_report()["mismatches"]
    assert {"symbol": SYMBOL, "side": side, "local": local, "venue": remote} in mismatches
    order = _buy(env, broker)
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == "startup_position_mismatch"
    assert env.api.place_calls == []  # nothing corrects the account automatically


def test_instruments_only_on_the_venue_are_reported_not_blocked(env):
    env.init_flat()
    env.api.positions = [position("long", 1, 1, 0, symbol=OTHER_SYMBOL)]
    broker = env.start()
    report = broker.get_direct_reconcile_report()
    assert report["other_instruments"] == [OTHER_SYMBOL]
    assert report["mismatches"] == []
    assert broker.direct_writes_blocked() == {}
    assert _buy(env, broker).status == bt.Order.Submitted


def test_snapshot_from_an_earlier_trading_day_rolls_today_into_yesterday(env):
    env.init_flat()
    env.write_snapshot({SYMBOL: snap(long=(2, 2, 0), short=(1, 1, 0))}, trading_day=YESTERDAY)
    env.api.positions = [position("long", 2, 0, 2), position("short", 1, 0, 1)]
    broker = env.start()
    assert broker.direct_writes_blocked() == {}
    assert broker.get_direct_reconcile_report()["snapshot_trading_day"] == YESTERDAY
    long_view = broker.get_closable(env.feed, "long")
    assert long_view["today"] == 0 and long_view["yesterday"] == 2
    assert long_view["closable_today"] == 0 and long_view["closable_yesterday"] == 2
    assert broker.getposition(env.feed).size == 1  # net = 2 long - 1 short
    rewritten = env.state().snapshot.read()
    assert rewritten["trading_day"] == TODAY
    assert rewritten["positions"][SYMBOL]["long"] == {"total": 2, "today": 0, "yesterday": 2}


def test_same_day_today_split_mismatch_blocks_the_symbol(env):
    env.init_flat()
    env.write_snapshot({SYMBOL: snap(long=(2, 2, 0))})
    env.api.positions = [position("long", 2, 1, 1)]
    broker = env.start()
    assert broker.direct_writes_blocked() == {SYMBOL: "startup_today_split_mismatch"}
    mismatch = broker.get_direct_reconcile_report()["mismatches"][0]
    assert mismatch["field"] == "today" and mismatch["local"] == 2 and mismatch["venue"] == 1


def test_unknown_venue_split_stays_unknown_when_totals_agree(env):
    env.init_flat()
    env.write_snapshot({SYMBOL: snap(long=(2, None, None))})
    env.api.positions = [position("long", 2, None, None)]
    broker = env.start()
    assert broker.direct_writes_blocked() == {}
    view = broker.get_closable(env.feed, "long")
    assert view["today"] is None and view["closable_today"] is None
    assert view["closable"] == 2


# ---------------------------------------------------------------------------
# pending markers
# ---------------------------------------------------------------------------
def test_same_day_marker_absent_from_complete_order_list_becomes_terminal(env):
    env.init_flat()
    marker_id, _identity = env.seed_marker("000000000011", status="DISPATCHED")
    other_id, _ = env.seed_marker("000000000012", local_seq=2, bt_ref=2, status="PREPARED")
    broker = env.start()
    state = env.state()
    for mid in (marker_id, other_id):
        marker = state.pending.get(mid)
        assert marker["status"] == "TERMINAL"
        assert marker["facts"]["final_status"] == "not_found_at_venue"
        assert marker["facts"]["resolution_evidence"] == "startup_complete_order_query"
    assert broker.direct_writes_blocked() == {}
    assert broker.get_restored_orders() == []


def test_marker_of_a_working_order_is_restored_and_must_be_taken_over(env):
    env.init_flat()
    marker_id, identity = env.seed_marker("000000000021", local_seq=3, bt_ref=7)
    foreign = native_identity("000000000099")  # someone else's working order
    env.api.active_orders = [
        order_event(identity, "accepted", sys_id="2001", side="buy", qty=2, price=3480.0),
        order_event(foreign, "accepted", sys_id="9999", side="sell", qty=1),
    ]
    broker = env.start()
    report = broker.get_direct_reconcile_report()
    assert report["restored_orders"] == 1 and report["foreign_working_orders"] == 1
    assert env.state().pending.get(marker_id)["status"] == "ACCEPTED"

    (restored,) = broker.get_restored_orders()
    assert restored.status == bt.Order.Accepted
    assert restored.info["restored"] is True
    assert restored.info["original_ref"] == 7 and restored.info["local_seq"] == 3
    assert restored.size == 2 and restored.price == 3480.0
    assert restored.owner is None

    refused = _buy(env, broker)
    assert refused.info["error_code"] == "restored_orders_not_taken_over"
    assert env.api.place_calls == []
    drain(broker)

    taken = broker.take_over_restored_orders(env.strategy)
    assert taken == [restored] and restored.owner is env.strategy
    notes = drain(broker)
    assert [n.ref for n in notes] == [restored.ref] and notes[0].info["restored"] is True
    assert broker.get_restored_orders() == []
    assert _buy(env, broker).status == bt.Order.Submitted
    with pytest.raises(Exception):
        broker.take_over_restored_orders(object())  # one strategy per directory

    # Cancel uses the original identity plus the learned venue order id; the
    # foreign working order is never touched.
    broker.cancel(restored)
    (call,) = env.api.cancel_calls
    assert call.target.client_order_id == "000000000021"
    assert call.target.fields["front_id"] == identity.fields["front_id"]
    assert call.target.fields["order_sys_id"] == "2001"


def test_restored_order_without_its_data_feed_blocks_the_symbol(env):
    env.init_flat()
    _marker_id, identity = env.seed_marker("000000000031", symbol="ag2612")
    env.api.active_orders = [order_event(identity, "accepted", symbol="ag2612")]
    broker = env.start()
    # Feeds attach after the broker starts; the restore waits for one.
    assert "ag2612" not in broker.direct_writes_blocked()
    broker.next()  # every feed of the run has started by the first next()
    assert broker.direct_writes_blocked()["ag2612"] == "restored_order_without_data"


def test_restored_order_waits_for_its_feed_to_attach(env):
    """A working order of ours is restored when its feed starts after the broker."""
    env.init_flat()
    _marker_id, identity = env.seed_marker("000000000032")
    env.api.active_orders = [order_event(identity, "accepted")]
    feeds = list(env.store._data_feeds)
    env.store._data_feeds.clear()  # the broker starts before any feed attaches
    broker = env.start()
    assert broker.get_restored_orders() == []
    for feed in feeds:
        env.store._data_feeds.append(feed)
        broker.data_started(feed)
    restored = broker.get_restored_orders()
    assert len(restored) == 1 and restored[0].info["restored"] is True
    broker.next()
    assert SYMBOL not in broker.direct_writes_blocked()


def test_trades_of_a_terminal_marker_are_applied_once_across_restarts(env):
    env.init_flat()
    marker_id, identity = env.seed_marker("000000000041")
    env.api.orders = [order_event(identity, "filled", sys_id="4001", qty=2, filled=2)]
    env.api.trades = [
        trade_event("T1", sys_id="4001", qty=1, price=3500.0),
        trade_event("T2", sys_id="4001", qty=1, price=3510.0),
    ]
    env.api.positions = [position("long", 2, 2, 0)]
    broker = env.start()
    report = broker.get_direct_reconcile_report()
    assert report["applied_missing_trades"] == 2 and report["mismatches"] == []
    assert broker.getposition(env.feed, side="long").size == 2
    assert broker.getposition(env.feed, side="long").price == pytest.approx(3505.0)
    marker = env.state().pending.get(marker_id)
    assert marker["status"] == "TERMINAL" and marker["facts"]["final_status"] == "filled"
    snapshot = env.state().snapshot.read()
    assert snapshot["positions"][SYMBOL]["long"] == {"total": 2, "today": 2, "yesterday": 0}
    assert len(snapshot["applied_trades"][TODAY]) == 2
    assert snapshot["position_prices"][SYMBOL]["long"] == pytest.approx(3505.0)
    broker.stop()

    again = env.start()
    assert again.get_direct_reconcile_report()["applied_missing_trades"] == 0
    assert again.getposition(env.feed, side="long").size == 2
    assert again.getposition(env.feed, side="long").price == pytest.approx(3505.0)
    assert again.direct_writes_blocked() == {}


def test_trades_of_a_working_marker_are_not_reapplied_after_a_second_restart(env):
    """The applied-trade keys in the snapshot de-duplicate across restarts."""
    env.init_flat()
    marker_id, identity = env.seed_marker("000000000051")
    env.api.active_orders = [
        order_event(identity, "partially_filled", sys_id="5001", qty=2, filled=1)
    ]
    env.api.trades = [trade_event("T1", sys_id="5001", qty=1)]
    env.api.positions = [position("long", 1, 1, 0)]
    first = env.start()
    assert first.get_direct_reconcile_report()["applied_missing_trades"] == 1
    assert first.getposition(env.feed, side="long").size == 1
    crash(first)

    second = env.start()
    report = second.get_direct_reconcile_report()
    assert report["applied_missing_trades"] == 0 and report["mismatches"] == []
    assert second.getposition(env.feed, side="long").size == 1
    assert env.state().pending.get(marker_id)["status"] == "ACCEPTED"


def test_restored_partially_filled_order_completes_with_its_remaining_fill(env):
    env.init_flat()
    _marker_id, identity = env.seed_marker("000000000061")
    env.api.active_orders = [
        order_event(identity, "partially_filled", sys_id="6001", qty=2, filled=1)
    ]
    env.api.trades = [trade_event("T1", sys_id="6001", qty=1)]
    env.api.positions = [position("long", 1, 1, 0)]
    broker = env.start()
    (restored,) = broker.take_over_restored_orders(env.strategy)
    assert restored.status == bt.Order.Accepted
    env.api.push(trade_event("T1", sys_id="6001", qty=1))  # replayed old return: ignored
    env.api.push(trade_event("T2", sys_id="6001", qty=1))
    broker.next()
    assert broker.getposition(env.feed, side="long").size == 2
    assert restored.status == bt.Order.Completed


def test_restored_partially_filled_order_cancel_counts_only_new_fills(env):
    env.init_flat()
    _marker_id, identity = env.seed_marker("000000000062")
    env.api.active_orders = [
        order_event(identity, "partially_filled", sys_id="6002", qty=3, filled=1)
    ]
    env.api.trades = [trade_event("T1", sys_id="6002", qty=1)]
    env.api.positions = [position("long", 1, 1, 0)]
    broker = env.start()
    (restored,) = broker.take_over_restored_orders(env.strategy)
    env.api.push(order_event(identity, "cancelled", sys_id="6002", qty=3, filled=1))
    broker.next()
    assert restored.status == bt.Order.Canceled


@pytest.mark.parametrize("seeded_status", ["DISPATCHED", "ACCEPTED", "PREPARED"])
def test_marker_from_an_older_trading_day_becomes_unknown_and_blocks(env, seeded_status):
    env.init_flat()
    marker_id, _identity = env.seed_marker(
        "000000000071", trading_day=YESTERDAY, status=seeded_status
    )
    broker = env.start()
    marker = env.state().pending.get(marker_id)
    assert marker["status"] == "UNKNOWN"
    assert broker.get_direct_reconcile_report()["unknown_markers"] == [marker_id]
    assert broker.direct_writes_blocked() == {SYMBOL: "pending_unknown"}
    assert _buy(env, broker).info["error_code"] == "pending_unknown"
    broker.stop()

    # UNKNOWN is sticky across restarts until an operator resolves it.
    again = env.start()
    assert again.direct_writes_blocked() == {SYMBOL: "pending_unknown"}
    assert env.state().pending.get(marker_id)["status"] == "UNKNOWN"


def test_unknown_cancel_marker_blocks_every_write(env):
    from bt_api_base.direct_write_protocol import PreDispatchRecord, WriteOperation

    env.init_flat()
    state = env.state()
    target = native_identity("000000000081", order_sys_id="8001")
    marker_id = state.pending.commit(
        PreDispatchRecord(
            operation=WriteOperation.CANCEL,
            host_scope=state.strategy_uuid,
            exchange_name=target.exchange_name,
            symbol=SYMBOL,
            identity=None,
            target_identity=target,
            request_summary={},
            trading_day=TODAY,
            session_generation=1,
            created_at_utc="2026-11-05T01:00:00.000000Z",
        )
    )
    assert state.pending.mark(marker_id, "UNKNOWN")
    broker = env.start()
    assert broker.direct_writes_blocked()["*"] == "pending_unknown"


def test_trade_venue_is_learned_for_closable_view(env):
    env.init_flat()
    _marker_id, identity = env.seed_marker("000000000091")
    env.api.orders = [order_event(identity, "filled", sys_id="9101", qty=1, filled=1)]
    env.api.trades = [trade_event("T9", sys_id="9101", qty=1)]
    env.api.positions = [position("long", 1, 1, 0, venue=None)]
    broker = env.start()
    assert broker.get_closable(env.feed, "long")["venue"] == VENUE


def test_configured_instrument_with_venue_position_and_flat_snapshot_is_blocked(env):
    """D62-16: the strategy's own (configured) instrument cannot hide in other_instruments."""
    env.start(first_init=True).stop()
    env.store._sdk_routes = {SYMBOL: "CTP___FUTURE"}
    env.api.positions = [position("long", 1, today=1, yesterday=0)]
    broker = env.start()
    report = broker.get_direct_reconcile_report()
    assert SYMBOL not in report["other_instruments"]
    assert broker.direct_writes_blocked().get(SYMBOL) == "startup_position_mismatch"


def test_marker_without_complete_order_list_is_kept_and_blocks(env):
    """Absence from working orders alone never proves a marker was not sent."""
    first = env.start(first_init=True)
    first.stop()
    marker_id, _identity = env.seed_marker("000000000401")
    original = env.api.direct_account_facts

    def without_all_orders(exchange_name, **sections):
        sections.pop("all_orders", None)
        return original(exchange_name, **sections)

    env.api.direct_account_facts = without_all_orders
    broker = env.start()
    assert marker_id in broker.get_direct_reconcile_report()["unknown_markers"]
    assert broker.direct_writes_blocked().get(SYMBOL) == "pending_unverified"
    assert env.state().pending.get(marker_id)["status"] != "TERMINAL"


def test_one_way_net_position_reconciles_against_the_long_or_short_leg():
    from backtrader.brokers._btapi_direct_mode import _leg_fact

    long_net = _leg_fact(position("net", 2))
    assert (long_net.side, long_net.total) == ("long", 2.0)
    short_net = _leg_fact(position("net", -1))
    assert (short_net.side, short_net.total) == ("short", 1.0)
    assert _leg_fact(position("net", 0)) is None
    assert _leg_fact(position("long", 3)).side == "long"


def test_restored_order_is_built_on_the_first_bar_of_a_just_attached_feed(env):
    """A just-attached live feed has no bar yet: a BT Order needs one (SimNow 2026-11-05)."""
    import datetime as _dt
    from types import SimpleNamespace as _NS

    from ._fakes import ListFeed

    env.init_flat()
    _marker_id, identity = env.seed_marker("000000000034")
    env.api.active_orders = [order_event(identity, "accepted")]
    env.store._data_feeds.clear()  # the broker starts before any feed attaches
    broker = env.start()
    fresh = ListFeed(dataname=SYMBOL, bars=[(_dt.datetime(2026, 11, 5, 9, 2), 3501.0)])
    fresh._start()
    fresh.trade_qualification = lambda: _NS(ok=True, reasons=())
    env.store._data_feeds.append(fresh)
    broker.data_started(fresh)  # attached, but no bar has been delivered yet
    assert len(fresh) == 0
    broker.next()
    assert broker.get_restored_orders() == []  # still waiting for a bar
    assert fresh.load() is True
    broker.next()
    restored = broker.get_restored_orders()
    assert len(restored) == 1 and restored[0].data is fresh
    assert restored[0].info["restored"] is True
    assert SYMBOL not in broker.direct_writes_blocked()


def test_restored_order_after_takeover_is_notified_to_the_bound_strategy(env):
    """Restored after strategy.start(): delivered by notification with the restored flag."""
    env.init_flat()
    _marker_id, identity = env.seed_marker("000000000035")
    env.api.active_orders = [order_event(identity, "accepted")]
    feeds = list(env.store._data_feeds)
    env.store._data_feeds.clear()
    broker = env.start()
    strategy = object()
    assert broker.take_over_restored_orders(strategy) == []  # nothing restorable yet
    for feed in feeds:
        env.store._data_feeds.append(feed)
        broker.data_started(feed)
    notified = [order for order in broker.notifs if order.info.get("restored")]
    assert len(notified) == 1
    assert broker.get_restored_orders() == []  # handed over, not kept for takeover


def test_fractional_fills_are_kept_in_the_snapshot_across_restarts(env):
    """Binance demo 2026-11-06: a 0.002 BTC fill was rounded out of the snapshot."""
    env.init_flat()
    _marker_id, identity = env.seed_marker("000000000042")
    env.api.orders = [order_event(identity, "filled", sys_id="4002", qty=0.002, filled=0.002)]
    env.api.trades = [trade_event("T9", sys_id="4002", qty=0.002, price=76748.5)]
    env.api.positions = [position("long", 0.002, None, None)]
    broker = env.start()
    assert broker.get_direct_reconcile_report()["mismatches"] == []
    assert broker.getposition(env.feed, side="long").size == pytest.approx(0.002)
    snapshot = env.state().snapshot.read()
    assert snapshot["positions"][SYMBOL]["long"]["total"] == pytest.approx(0.002)
    broker.stop()
    again = env.start()
    assert again.get_direct_reconcile_report()["mismatches"] == []
    assert SYMBOL not in again.direct_writes_blocked()
