"""Trading-day switch while running (R-3; D62-14/22/29).

A trusted provider trading-day change freezes new orders
(``trading_day_switch_pending``) until one verification attempt re-checked the
session and account, confirmed the new day's settlement through the SDK, read
one complete account observation of the new day, resolved old-day pending
markers only from day-bound identity matches (else UNKNOWN + instrument block)
and adopted the venue's today/yesterday split.  Returns and own cancels keep
running; the waiting queue is held, not rejected.

UNIT/FAKE: fake facade, real ``backtrader.live_state`` in ``tmp_path``.  The
background poller is stopped (``quiet``) so each test drives the poller-side
verification itself; one test uses the real poller thread.
"""

import datetime as dt
import time

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from bt_api_base.direct_write_protocol import (
    DirectExecutionEvent,
    DirectExecutionEventKind,
    NativeOrderIdentity,
    SettlementStatus,
)
from bt_api_base.trading_session_protocol import TradingPhase

from ._fakes import (
    EXCHANGE,
    OTHER_SYMBOL,
    SYMBOL,
    T0,
    TODAY,
    TOMORROW,
    VENUE,
    YESTERDAY,
    crash,
    native_identity,
    order_event,
    position,
    quiet,
    run_day_switch,
    trade_event,
    window,
)

PENDING = "trading_day_switch_pending"
NEW_DAY = dt.date(2026, 11, 6)


def _buy(env, broker, size=1, feed=None, offset="open"):
    return broker.buy(
        env.strategy, feed or env.feed, size, price=3500.0, exectype=bt.Order.Limit, offset=offset
    )


def _working(env, broker, sys_id, size=1):
    order = _buy(env, broker, size)
    call = env.api.place_calls[-1]
    env.api.push(order_event(call.identity, "accepted", sys_id=sys_id, qty=size))
    broker.next()
    assert order.status == bt.Order.Accepted
    return order, call


def _filled(env, broker, sys_id, size=1):
    order, call = _working(env, broker, sys_id, size)
    env.api.push(trade_event(f"T{sys_id}", sys_id=sys_id, qty=size))
    broker.next()
    assert order.status == bt.Order.Completed
    return order, call


def _started(env, **params):
    broker = env.start(first_init=True, **params)
    quiet(broker)
    env.api.schedule.trading_day = NEW_DAY  # the venue calendar agrees with the new day
    return broker


def _new_day(env, broker, *, positions=(), active=(), orders=(), trades=(), via="funds"):
    """The provider moves to TOMORROW; one facts read reaches the strategy thread."""
    env.api.trading_day = TOMORROW
    env.api.positions = list(positions)
    env.api.active_orders = list(active)
    env.api.orders = list(orders)
    env.api.trades = list(trades)
    if via == "funds":
        facts = env.api.direct_account_facts(EXCHANGE, positions=False, active_orders=False)
    else:
        facts = env.api.direct_account_facts(EXCHANGE)
    broker._direct_facts_results.append((via, facts))
    broker.next()


# ---------------------------------------------------------------------------
# entry, freeze and exit
# ---------------------------------------------------------------------------
def test_day_change_without_reconnect_freezes_new_orders_until_verified(env):
    broker = _started(env)
    _filled(env, broker, "7001", size=2)
    places = len(env.api.place_calls)
    _new_day(env, broker, positions=[position("long", 2, 0, 2)])

    report = broker.get_direct_reconcile_report()["trading_day_switch"]
    assert report["status"] == "pending" and report["detected_by"] == "funds"
    assert (report["from_trading_day"], report["to_trading_day"]) == (TODAY, TOMORROW)
    assert broker.direct_writes_blocked() == {"*": PENDING}
    refused = _buy(env, broker)
    assert refused.status == bt.Order.Rejected and refused.info["error_code"] == PENDING
    assert len(env.api.place_calls) == places  # nothing reached the facade
    assert broker._direct_trading_day == TODAY  # nothing adopted yet

    report = run_day_switch(broker)
    assert report["status"] == "completed" and report["attempts"] == 1
    assert report["reconnected"] is False and report["settlement"] == "confirmed"
    assert broker._direct_trading_day == TOMORROW
    assert broker.get_direct_reconcile_report()["trading_day"] == TOMORROW
    assert broker.direct_writes_blocked() == {}
    assert _buy(env, broker).status == bt.Order.Submitted
    assert env.state().snapshot.read()["trading_day"] == TOMORROW


def test_provider_session_day_is_detected_before_any_facts_read(env):
    broker = _started(env)
    env.api.trading_day = TOMORROW  # the provider session moved; no facts read yet
    refused = _buy(env, broker)
    assert refused.info["error_code"] == PENDING
    assert env.api.place_calls == []
    report = broker.get_direct_reconcile_report()["trading_day_switch"]
    assert report["detected_by"] == "provider_session"
    assert run_day_switch(broker)["status"] == "completed"
    assert _buy(env, broker).status == bt.Order.Submitted


def test_new_day_settlement_is_confirmed_although_an_old_order_stays_unknown(env):
    """D62-29: settlement may proceed; it neither clears UNKNOWN nor releases writes."""
    broker = _started(env)
    working, call = _working(env, broker, "7101")
    _new_day(env, broker)  # CTP: the new day's complete order list has no old orders
    assert len(env.api.settlement_calls) == 1  # startup only
    report = run_day_switch(broker)

    assert report["status"] == "completed" and report["settlement"] == "confirmed"
    startup, switch = env.api.settlement_calls
    assert switch.trading_day == TOMORROW and switch.host_scope == broker._direct_uuid
    settlement = env.state().pending.get(switch.marker_id)
    assert settlement["status"] == "TERMINAL"
    assert settlement["facts"]["final_status"] == "confirmed"
    marker = env.state().pending.get(call.marker_id)
    assert marker["status"] == "UNKNOWN"
    assert marker["facts"]["reason"] == "previous_trading_day_unresolved"
    assert report["unknown_markers"] == [call.marker_id]
    assert broker.direct_writes_blocked() == {SYMBOL: "previous_day_pending_unknown"}
    assert _buy(env, broker).info["error_code"] == "previous_day_pending_unknown"
    assert _buy(env, broker, feed=env.other_feed).status == bt.Order.Submitted
    assert working.alive() and working.info["outcome_unknown"] is True


def test_unresolved_old_day_order_takes_no_automatic_write_and_stays_unknown(env):
    broker = _started(env)
    working, call = _working(env, broker, "7201")
    _new_day(env, broker)
    run_day_switch(broker)
    cancels = len(env.api.cancel_calls)
    broker.cancel(working)
    assert len(env.api.cancel_calls) == cancels  # its day-scoped ids may be reused
    assert working.info["cancel_error"] == "previous_day_pending_unknown"
    summary = broker.stop()
    assert summary["cancelled_requested"] == 0 and summary["unresolved_working_orders"] == 1
    assert len(env.api.cancel_calls) == cancels
    again = env.start()
    assert again.direct_writes_blocked() == {SYMBOL: "pending_unknown"}
    assert env.state().pending.get(call.marker_id)["status"] == "UNKNOWN"


def test_old_day_order_still_working_under_its_identity_and_day_is_verified(env):
    """A venue whose new-day query still lists the old-day order (e.g. GTC)."""
    broker = _started(env)
    working, call = _working(env, broker, "7301")
    _new_day(env, broker, active=[order_event(call.identity, "accepted", sys_id="7301")])
    report = run_day_switch(broker)
    marker = env.state().pending.get(call.marker_id)
    assert marker["status"] == "ACCEPTED"
    assert marker["facts"]["resolution_evidence"] == "trading_day_switch_working_order"
    assert report["verified_markers"] == [call.marker_id] and report["unknown_markers"] == []
    assert broker.direct_writes_blocked() == {}
    assert working.alive() and "outcome_unknown" not in working.info


def test_reused_ids_of_the_new_day_are_never_taken_for_the_old_order(env):
    """Same FrontID/SessionID/OrderRef or OrderSysID on another trading day: another order."""
    broker = _started(env)
    working, call = _working(env, broker, "7401")
    fields = dict(call.identity.fields)
    reused = native_identity(fields["order_ref"], trading_day=TOMORROW)
    _new_day(env, broker, active=[order_event(reused, "accepted", sys_id="7401")])
    run_day_switch(broker)
    assert env.state().pending.get(call.marker_id)["status"] == "UNKNOWN"
    assert broker.direct_writes_blocked() == {SYMBOL: "previous_day_pending_unknown"}
    # A new-day fill with the old OrderSysID belongs to another order.
    identity = NativeOrderIdentity(
        exchange_name=EXCHANGE,
        client_order_id=None,
        fields={"exchange_id": VENUE, "order_sys_id": "7401", "trading_day": TOMORROW},
    )
    env.api.push(
        DirectExecutionEvent(
            kind=DirectExecutionEventKind.TRADE,
            exchange_name=EXCHANGE,
            symbol=SYMBOL,
            identity=identity,
            exchange_order_id="7401",
            side="buy",
            offset="open",
            trade_id="T-NEW-DAY",
            trade_price=3500.0,
            trade_qty=1.0,
            trading_day=TOMORROW,
        )
    )
    broker.next()
    assert broker.getposition(env.feed, side="long").size == 0
    assert working.executed.size == 0


@pytest.mark.parametrize("venue_filled, resolved", [(0.0, True), (1.0, False)])
def test_old_day_terminal_order_is_resolved_only_with_all_fills_applied(
    env, venue_filled, resolved
):
    broker = _started(env)
    working, call = _working(env, broker, "7501", size=2)
    ended = order_event(call.identity, "cancelled", sys_id="7501", qty=2, filled=venue_filled)
    positions = [position("long", venue_filled, venue_filled, 0)] if venue_filled else []
    _new_day(env, broker, orders=[ended], positions=positions)
    report = run_day_switch(broker)
    marker = env.state().pending.get(call.marker_id)
    if resolved:
        assert working.status == bt.Order.Canceled
        assert marker["status"] == "TERMINAL"
        assert marker["facts"]["resolution_evidence"] == "trading_day_switch_order_query"
        assert report["resolved_markers"] == [call.marker_id]
        assert broker.direct_writes_blocked() == {}
    else:  # a fill the Broker never saw: only a trade record could prove it
        assert working.alive() and marker["status"] == "UNKNOWN"
        assert broker.direct_writes_blocked() == {SYMBOL: "previous_day_pending_unknown"}


# ---------------------------------------------------------------------------
# settlement (D62-29)
# ---------------------------------------------------------------------------
def test_unclear_settlement_keeps_writes_blocked_and_is_never_repeated(env):
    broker = _started(env)
    env.api.settlement_result = SettlementStatus.UNKNOWN  # committed, outcome unknown
    confirm = env.api.ensure_settlement_confirmed

    def confirm_then_reconnect(*args, **kwargs):
        result = confirm(*args, **kwargs)
        env.api.session_generation = 2  # the session changes during the confirmation
        return result

    env.api.ensure_settlement_confirmed = confirm_then_reconnect
    _new_day(env, broker)
    report = run_day_switch(broker)
    assert report["status"] == "pending" and report["last_reason"] == "session_changed"
    assert report["settlement"] == "unclear"
    assert broker.direct_writes_blocked() == {"*": "settlement_unconfirmed"}
    report = run_day_switch(broker)  # re-verified on the new session, no second confirm
    assert report["status"] == "completed" and report["reconnected"] is True
    assert len(env.api.settlement_calls) == 2  # startup + one switch confirmation
    marker = env.state().pending.get(env.api.settlement_calls[-1].marker_id)
    assert marker["status"] == "UNKNOWN"
    assert marker["facts"]["reason"] == "settlement_outcome_unknown"
    assert broker.direct_writes_blocked() == {"*": "settlement_unconfirmed"}
    assert _buy(env, broker).info["error_code"] == "settlement_unconfirmed"


@pytest.mark.parametrize("failure", ["readback_unknown", "raised_before_commit"])
def test_settlement_that_sent_nothing_keeps_the_freeze_and_is_retried(env, failure):
    broker = _started(env)
    if failure == "readback_unknown":
        env.api.settlement_readback = SettlementStatus.UNKNOWN
    else:
        env.api.settlement_error = TimeoutError("settlement readback timed out")
    _new_day(env, broker)
    report = run_day_switch(broker)
    assert report["status"] == "pending" and report["last_reason"] == "settlement_unverified"
    assert report["settlement"] == "unverified"
    assert broker.direct_writes_blocked() == {"*": PENDING}
    env.api.settlement_readback = None
    env.api.settlement_error = None
    report = run_day_switch(broker)
    assert report["status"] == "completed" and report["settlement"] == "confirmed"
    assert broker.direct_writes_blocked() == {}


def test_previous_day_unconfirmed_settlement_is_superseded_by_the_new_day(env):
    env.api.settlement_result = SettlementStatus.UNKNOWN
    broker = _started(env)
    assert broker.direct_writes_blocked() == {"*": "settlement_unconfirmed"}
    env.api.settlement_result = SettlementStatus.CONFIRMED
    _new_day(env, broker)
    assert run_day_switch(broker)["settlement"] == "confirmed"
    assert broker.direct_writes_blocked() == {}


# ---------------------------------------------------------------------------
# session, account and day verification
# ---------------------------------------------------------------------------
def test_reconnect_with_the_day_change_is_verified_on_the_new_session(env):
    broker = _started(env)
    env.api.session_generation = 2
    _new_day(env, broker)
    report = run_day_switch(broker)
    assert report["status"] == "completed"
    assert report["reconnected"] is True and report["session_generation"] == 2
    assert broker._direct_session_generation == 2


@pytest.mark.parametrize(
    "break_it, reason",
    [
        (lambda api: setattr(api, "session_generation", None), "session_unavailable"),
        (lambda api: setattr(api, "complete", False), "account_facts_incomplete"),
    ],
)
def test_unverifiable_session_or_facts_keep_the_freeze(env, break_it, reason):
    broker = _started(env)
    _new_day(env, broker)
    break_it(env.api)
    report = run_day_switch(broker)
    assert report["status"] == "pending" and report["last_reason"] == reason
    assert len(env.api.settlement_calls) == 1  # no settlement before verification
    assert _buy(env, broker).info["error_code"] == PENDING
    env.api.session_generation, env.api.complete = 1, True
    assert run_day_switch(broker)["status"] == "completed"


def test_account_change_during_the_switch_blocks_every_write(env):
    broker = _started(env)
    _new_day(env, broker)
    env.api.provider.reference = "simnow:999999"
    report = run_day_switch(broker)
    assert report["status"] == "failed" and report["last_reason"] == "account_binding_mismatch"
    assert len(env.api.settlement_calls) == 1  # never confirmed for another account
    assert broker.direct_writes_blocked() == {"*": "account_binding_mismatch"}
    assert _buy(env, broker).info["error_code"] == "account_binding_mismatch"
    assert broker._direct_day_switch_request is None


def test_trading_day_regression_blocks_every_write(env):
    broker = _started(env)
    env.api.trading_day = YESTERDAY
    facts = env.api.direct_account_facts(EXCHANGE, positions=False, active_orders=False)
    broker._direct_facts_results.append(("funds", facts))
    broker.next()
    assert broker.direct_writes_blocked() == {"*": "trading_day_regressed"}
    assert broker._direct_day_switch_request is None
    assert _buy(env, broker).info["error_code"] == "trading_day_regressed"


@pytest.mark.parametrize("seen_by", ["facts_read", "verification"])
def test_an_earlier_day_seen_while_switching_is_a_regression_not_a_target(env, seen_by):
    broker = _started(env)
    _new_day(env, broker)
    env.api.trading_day = YESTERDAY
    if seen_by == "facts_read":
        facts = env.api.direct_account_facts(EXCHANGE, positions=False, active_orders=False)
        broker._direct_facts_results.append(("funds", facts))
        broker.next()
    report = run_day_switch(broker)
    assert report["status"] == "failed" and report["last_reason"] == "trading_day_regressed"
    assert broker._direct_trading_day == TODAY
    assert broker.direct_writes_blocked() == {"*": "trading_day_regressed"}


def test_a_further_day_change_retargets_the_pending_switch(env):
    broker = _started(env)
    _new_day(env, broker)
    env.api.trading_day = "20261109"
    env.api.schedule.trading_day = dt.date(2026, 11, 9)
    report = run_day_switch(broker)  # still targeting TOMORROW: the provider moved on
    assert report["status"] == "pending" and report["to_trading_day"] == "20261109"
    report = run_day_switch(broker)
    assert report["status"] == "completed" and broker._direct_trading_day == "20261109"


# ---------------------------------------------------------------------------
# positions (D62-22), returns and waiting orders during the switch
# ---------------------------------------------------------------------------
def test_venue_today_yesterday_facts_are_preferred_over_local_conversion(env):
    env.store._sdk_routes = {SYMBOL: EXCHANGE, OTHER_SYMBOL: EXCHANGE}
    broker = _started(env)
    _filled(env, broker, "7601", size=2)
    order = broker.buy(
        env.strategy, env.other_feed, 1, price=3300.0, exectype=bt.Order.Limit, offset="open"
    )
    env.api.push(
        order_event(
            env.api.place_calls[-1].identity, "accepted", sys_id="7602", symbol=OTHER_SYMBOL
        )
    )
    env.api.push(trade_event("T7602", sys_id="7602", symbol=OTHER_SYMBOL, price=3300.0))
    broker.next()
    assert order.status == bt.Order.Completed
    _new_day(
        env,
        broker,
        positions=[
            position("long", 2, 1, 1),  # the venue's split, not the local 0/2 conversion
            position("long", 1, None, None, symbol=OTHER_SYMBOL),  # no venue split
        ],
    )
    report = run_day_switch(broker)
    assert report["split_sources"][SYMBOL]["long"] == "venue"
    assert report["split_sources"][OTHER_SYMBOL]["long"] == "local_conversion"
    view = broker.get_closable(env.feed, "long")
    assert view["today"] == 1 and view["yesterday"] == 1
    other = broker.get_closable(env.other_feed, "long")
    assert other["today"] == 0 and other["yesterday"] == 1
    assert report["calendar"][SYMBOL] == "match"
    assert broker.direct_writes_blocked() == {}


def test_calendar_contradicting_the_new_day_leaves_a_missing_split_unknown(env):
    broker = _started(env)
    _filled(env, broker, "7701", size=1)
    env.api.schedule.trading_day = dt.date(2026, 11, 5)  # calendar still says the old day
    _new_day(env, broker, positions=[position("long", 1, None, None)])
    report = run_day_switch(broker)
    assert report["calendar"][SYMBOL] == "mismatch"
    assert report["split_sources"][SYMBOL]["long"] == "unknown"
    assert broker.get_closable(env.feed, "long")["today"] is None
    refused = broker.sell(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="close_yesterday"
    )
    assert refused.info["error_code"] == "closable_unknown"


def test_returns_are_processed_and_old_day_cancels_wait_for_the_switch(env):
    broker = _started(env)
    working, call = _working(env, broker, "7801", size=2)
    _new_day(env, broker)
    env.api.push(trade_event("T7801", sys_id="7801", qty=1))  # a new-day fill
    broker.next()
    assert working.status == bt.Order.Partial
    assert broker.getposition(env.feed, side="long").size == 1
    broker.cancel(working)
    # Day-scoped ids of the old day may be reused on the new day's session.
    assert env.api.cancel_calls == []
    assert working.info["cancel_error"] == "previous_day_pending_unknown"
    env.api.active_orders = [
        order_event(call.identity, "partially_filled", sys_id="7801", qty=2, filled=1)
    ]
    env.api.trades = [trade_event("T7801", sys_id="7801", qty=1)]
    env.api.positions = [position("long", 1, 1, 0)]
    report = run_day_switch(broker)
    assert report["status"] == "completed" and report["verified_markers"] == [call.marker_id]
    view = broker.get_closable(env.feed, "long")
    assert view["today"] == 1 and view["yesterday"] == 0  # venue: a fill of the new day
    key = broker._direct_trade_key(trade_event("T7801", sys_id="7801", qty=1))
    assert broker._direct_applied == {TOMORROW: [key]}
    env.api.push(trade_event("T7801", sys_id="7801", qty=1))  # replayed return
    broker.next()
    assert broker.getposition(env.feed, side="long").size == 1
    broker.cancel(working)  # verified working under its identity and day
    (cancel,) = env.api.cancel_calls
    assert cancel.target.fields["trading_day"] == TODAY


def test_waiting_order_is_held_not_rejected_during_the_switch(env, clock):
    broker = _started(env)
    env.api.schedule.phase = TradingPhase.CLOSED
    env.api.schedule.next_window = window(T0 + dt.timedelta(hours=1), T0 + dt.timedelta(hours=3))
    waiting = _buy(env, broker)
    assert waiting.info["waiting_session"] is True
    env.api.trading_day = TOMORROW  # the night session's trading day
    clock["value"] = T0 + dt.timedelta(hours=1)
    env.api.schedule.phase = TradingPhase.CONTINUOUS
    broker.next()
    assert env.api.place_calls == []
    assert waiting.status == bt.Order.Submitted
    assert env.state().waiting.get(waiting.info["waiting_id"])["status"] == "WAITING"
    assert broker.direct_writes_blocked() == {"*": PENDING}
    run_day_switch(broker)  # verified, then dispatched in the same broker step
    (call,) = env.api.place_calls
    assert call.summary["local_seq"] == waiting.info["local_seq"]
    assert call.identity.fields["trading_day"] == TOMORROW


# ---------------------------------------------------------------------------
# crash safety and the background poller
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("crash_point", ["before_verification", "before_snapshot"])
def test_crash_during_the_switch_restarts_into_a_consistent_state(env, crash_point):
    env.init_flat()
    broker = env.start()
    quiet(broker)
    env.api.schedule.trading_day = NEW_DAY
    _filled(env, broker, "7901", size=2)
    _working_order, call = _working(env, broker, "7902")
    _new_day(env, broker, positions=[position("long", 2, 0, 2)])
    if crash_point == "before_snapshot":

        def crash_now():
            raise RuntimeError("process died")

        broker._direct_write_snapshot = crash_now
        with pytest.raises(RuntimeError):
            run_day_switch(broker)
        assert env.state().pending.get(call.marker_id)["status"] == "UNKNOWN"
    crash(broker)
    assert env.state().snapshot.read()["trading_day"] == TODAY  # the old day's snapshot

    again = env.start()
    report = again.get_direct_reconcile_report()
    assert report["trading_day"] == TOMORROW and report["snapshot_trading_day"] == TODAY
    assert report["mismatches"] == [] and report["unknown_markers"] == [call.marker_id]
    assert again.direct_writes_blocked() == {SYMBOL: "pending_unknown"}
    view = again.get_closable(env.feed, "long")
    assert view["total"] == 2 and view["today"] == 0 and view["yesterday"] == 2
    assert env.api.settlement_calls[-1].trading_day == TOMORROW
    assert env.state().snapshot.read()["trading_day"] == TOMORROW


def test_the_background_poller_runs_the_verification(env):
    broker = env.start(first_init=True, direct_day_switch_retry_interval=0.1)
    env.api.schedule.trading_day = NEW_DAY
    env.api.trading_day = TOMORROW
    assert _buy(env, broker).info["error_code"] == PENDING
    deadline = time.monotonic() + 10.0
    while broker.get_direct_refresh_counts()["day_switch"] < 1 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert broker.get_direct_refresh_counts()["day_switch"] >= 1
    broker.next()
    report = broker.get_direct_reconcile_report()["trading_day_switch"]
    assert report["status"] == "completed"
    assert _buy(env, broker).status == bt.Order.Submitted


# ---------------------------------------------------------------------------
# routes without venue offsets (OKX/Binance: the trading day is the UTC date)
# ---------------------------------------------------------------------------
def test_route_without_offsets_crosses_the_day_with_a_resting_gtc_order(env):
    """R-3 is CTP-style only: the new day is adopted, nothing frozen, no settlement."""
    broker = env.start(first_init=True, require_offset=False)
    quiet(broker)
    probes = []
    env.api.provider.trading_day = lambda: probes.append(1) or env.api.trading_day
    resting = broker.buy(env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit)
    call = env.api.place_calls[-1]
    assert call.request.time_in_force == "GTC"
    env.api.push(order_event(call.identity, "accepted", sys_id="9901"))
    broker.next()
    assert resting.status == bt.Order.Accepted

    env.api.trading_day = TOMORROW  # the UTC date moved; the GTC order rests on
    env.api.active_orders = [order_event(call.identity, "accepted", sys_id="9901")]
    broker._direct_facts_results.append(("audit", env.api.direct_account_facts(EXCHANGE)))
    broker.next()
    assert broker._direct_trading_day == TOMORROW  # adopted at once
    assert broker.direct_writes_blocked() == {}
    assert "trading_day_switch" not in broker.get_direct_reconcile_report()
    assert broker._direct_day_switch_request is None
    other = broker.buy(env.strategy, env.other_feed, 1, price=3300.0, exectype=bt.Order.Limit)
    assert other.status == bt.Order.Submitted  # never frozen
    assert probes == []  # no per-order provider trading-day check

    # Returns stamped with the new day still belong to the resting order.
    fields = dict(call.identity.fields, trading_day=TOMORROW, order_sys_id="9901")
    fill = DirectExecutionEvent(
        kind=DirectExecutionEventKind.TRADE,
        exchange_name=EXCHANGE,
        symbol=SYMBOL,
        identity=NativeOrderIdentity(
            exchange_name=EXCHANGE,
            client_order_id=None,
            fields={"exchange_id": VENUE, "order_sys_id": "9901", "trading_day": TOMORROW},
        ),
        exchange_order_id="9901",
        side="buy",
        offset="open",
        trade_id="T9901",
        trade_price=3500.0,
        trade_qty=1.0,
        trading_day=TOMORROW,
    )
    env.api.push(fill)
    broker.next()
    assert resting.status == bt.Order.Completed
    assert broker.getposition(env.feed).size == 1
    later = native_identity(fields["order_ref"], trading_day=TOMORROW)  # same session triple
    assert broker._direct_order_for_event(order_event(later, "filled", sys_id="9901")) is resting
    marker = env.state().pending.get(call.marker_id)
    assert marker["status"] == "TERMINAL" and marker["facts"]["final_status"] == "filled"
    assert len(env.api.settlement_calls) == 1  # startup only
    assert broker.direct_writes_blocked() == {}
