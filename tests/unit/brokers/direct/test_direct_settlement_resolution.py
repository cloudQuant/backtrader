"""Resolution of an unclear settlement confirmation within the run (D62-29).

User decision 2026-11-06: read first, then decide, on both paths.  An unclear
confirmation (committed, so possibly sent, without a clear result) of the
verified current route and trading day leaves its marker UNKNOWN and blocks
writes (``settlement_unconfirmed``), whether the startup step or a running
trading-day switch made it.  A resolution loop on the facts poller (backoff
from ``direct_day_switch_retry_interval``) reads the provider's settlement
state read-only: ``confirmed`` closes the markers and lifts the block; a
complete ``unconfirmed`` closes them (``settlement_readback_unconfirmed``) and
runs the SDK settlement step once more; anything else retries.  After
``direct_settlement_resolution_attempts`` the loop stops (``manual_required``).
No settlement write once ``stop()`` began.

UNIT/FAKE: fake facade (read-only provider settlement state), real
``backtrader.live_state`` in ``tmp_path``.  The background poller is stopped
(``quiet``) so each test drives the attempts itself; one test uses the real
poller thread.
"""

import datetime as dt
import threading
import time

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from backtrader.live_state import read_audit
from bt_api_base.direct_write_protocol import SettlementStatus

from ._fakes import EXCHANGE, TODAY, TOMORROW, quiet, run_day_switch

BLOCK = {"*": "settlement_unconfirmed"}
NEW_DAY = dt.date(2026, 11, 6)


def _buy(env, broker):
    return broker.buy(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )


def _resolution(broker):
    return dict(broker.get_direct_reconcile_report().get("settlement_resolution") or {})


def run_resolution(broker):
    """One due facts-poller resolution attempt, then ``next`` applies it."""
    broker._direct_settlement_due = 0.0
    ran = broker._direct_settlement_poll()
    broker.next()
    return ran, _resolution(broker)


def _unclear_start(env, **params):
    """A restart whose startup confirmation is committed without a clear result."""
    env.init_flat()
    env.api.settlement_result = SettlementStatus.UNKNOWN
    broker = env.start(**params)
    quiet(broker)
    marker_id = env.api.settlement_calls[-1].marker_id
    assert marker_id is not None
    return broker, marker_id


# ---------------------------------------------------------------------------
# startup: an unclear outcome is UNKNOWN and resolved within the same run
# ---------------------------------------------------------------------------
def test_unclear_startup_confirmation_is_unknown_and_lifted_by_a_readback_in_the_run(env):
    broker, marker_id = _unclear_start(env)
    marker = env.state().pending.get(marker_id)
    assert marker["status"] == "UNKNOWN"  # not TERMINAL "unknown"
    assert marker["facts"]["reason"] == "settlement_outcome_unknown"
    assert broker.direct_writes_blocked() == BLOCK
    resolution = _resolution(broker)
    assert resolution["status"] == "pending" and resolution["attempts"] == 0
    assert resolution["trading_day"] == TODAY and resolution["source"] == "unclear_outcome"
    assert _buy(env, broker).info["error_code"] == "settlement_unconfirmed"

    env.api.settlement_readback = SettlementStatus.CONFIRMED  # read-only: confirmed today
    calls = len(env.api.settlement_calls)
    ran, resolution = run_resolution(broker)
    assert ran is True
    assert resolution["status"] == "resolved" and resolution["attempts"] == 1
    assert resolution["last_result"] == "confirmed"
    assert env.api.settlement_reads == [TODAY]
    assert len(env.api.settlement_calls) == calls  # no second confirmation
    marker = env.state().pending.get(marker_id)
    assert marker["status"] == "TERMINAL"
    assert marker["facts"]["resolution_evidence"] == "settlement_readback"
    assert broker.direct_writes_blocked() == {}
    assert _buy(env, broker).status == bt.Order.Submitted


def test_unclear_startup_confirmation_proven_absent_is_confirmed_again(env):
    broker, old_id = _unclear_start(env)
    env.api.settlement_result = SettlementStatus.CONFIRMED  # the next confirmation works
    calls = len(env.api.settlement_calls)
    ran, resolution = run_resolution(broker)  # readback: complete, not confirmed
    assert ran is True
    assert resolution["status"] == "resolved" and resolution["last_result"] == "unconfirmed"
    assert resolution["last_settlement"] == "confirmed" and resolution["reconfirmations"] == 1
    old = env.state().pending.get(old_id)
    assert old["status"] == "TERMINAL"
    assert old["facts"]["final_status"] == "unconfirmed"
    assert old["facts"]["resolution_evidence"] == "settlement_readback_unconfirmed"
    (call,) = env.api.settlement_calls[calls:]  # one new confirmation, a new marker
    new = env.state().pending.get(call.marker_id)
    assert call.marker_id != old_id
    assert new["status"] == "TERMINAL" and new["facts"]["final_status"] == "confirmed"
    assert old["resolution"]["resolved_at_utc"] <= new["committed_at_utc"]  # closed first
    (audit,) = [
        record
        for record in read_audit(str(env.strategy_dir))
        if record["event"] == "pending_settlement_readback_resolution"
    ]
    assert audit["marker_id"] == old_id and audit["outcome"] == "unconfirmed"
    assert audit["evidence"] == "settlement_readback_unconfirmed"
    assert broker.direct_writes_blocked() == {}
    assert _buy(env, broker).status == bt.Order.Submitted


def test_reconfirmation_with_an_unclear_result_keeps_the_loop_running(env):
    broker, old_id = _unclear_start(env)  # the next confirmation is unclear too
    ran, resolution = run_resolution(broker)
    assert resolution["status"] == "pending" and resolution["last_settlement"] == "unclear"
    new_id = env.api.settlement_calls[-1].marker_id
    assert new_id != old_id
    assert env.state().pending.get(old_id)["status"] == "TERMINAL"
    assert env.state().pending.get(new_id)["status"] == "UNKNOWN"
    assert broker.direct_writes_blocked() == BLOCK

    env.api.settlement_readback = SettlementStatus.CONFIRMED
    calls = len(env.api.settlement_calls)
    ran, resolution = run_resolution(broker)
    assert resolution["status"] == "resolved" and resolution["attempts"] == 2
    assert len(env.api.settlement_calls) == calls  # the readback decided
    assert env.state().pending.get(new_id)["facts"]["resolution_evidence"] == (
        "settlement_readback"
    )
    assert broker.direct_writes_blocked() == {}


def test_the_background_poller_runs_the_resolution(env):
    env.init_flat()
    env.api.settlement_result = SettlementStatus.UNKNOWN
    broker = env.start(direct_day_switch_retry_interval=0.05)
    assert broker.direct_writes_blocked() == BLOCK
    env.api.settlement_readback = SettlementStatus.CONFIRMED
    deadline = time.monotonic() + 10.0
    while (
        broker.get_direct_refresh_counts()["settlement_resolution"] < 1
        and time.monotonic() < deadline
    ):
        time.sleep(0.05)
    assert broker.get_direct_refresh_counts()["settlement_resolution"] >= 1
    broker.next()
    assert _resolution(broker)["status"] == "resolved"
    assert broker.direct_writes_blocked() == {}


# ---------------------------------------------------------------------------
# running trading-day switch
# ---------------------------------------------------------------------------
def test_unclear_switch_settlement_is_resolved_within_the_run(env):
    broker = env.start(first_init=True)
    quiet(broker)
    env.api.schedule.trading_day = NEW_DAY
    env.api.settlement_result = SettlementStatus.UNKNOWN
    env.api.trading_day = TOMORROW
    facts = env.api.direct_account_facts(EXCHANGE, positions=False, active_orders=False)
    broker._direct_facts_results.append(("funds", facts))
    broker.next()
    switch = run_day_switch(broker)
    assert switch["settlement"] == "unclear"
    marker_id = env.api.settlement_calls[-1].marker_id
    assert env.state().pending.get(marker_id)["status"] == "UNKNOWN"
    assert broker.direct_writes_blocked() == BLOCK
    assert _resolution(broker)["trading_day"] == TOMORROW

    env.api.settlement_readback = SettlementStatus.CONFIRMED
    calls = len(env.api.settlement_calls)
    ran, resolution = run_resolution(broker)
    assert resolution["status"] == "resolved"
    assert env.api.settlement_reads == [TOMORROW]
    assert len(env.api.settlement_calls) == calls
    marker = env.state().pending.get(marker_id)
    assert marker["status"] == "TERMINAL"
    assert marker["resolution"]["trading_day"] == TOMORROW
    report = broker.get_direct_reconcile_report()
    assert report["trading_day_switch"]["status"] == "completed"
    assert broker._direct_trading_day == TOMORROW
    assert broker.direct_writes_blocked() == {}  # no restart needed
    assert _buy(env, broker).status == bt.Order.Submitted


def test_a_reissued_switch_request_never_confirms_while_one_is_unclear(env):
    """D62-29: an outstanding unclear confirmation of the target day is not repeated."""
    broker = env.start(first_init=True)
    quiet(broker)
    env.api.schedule.trading_day = NEW_DAY
    env.api.settlement_result = SettlementStatus.UNKNOWN
    confirm = env.api.ensure_settlement_confirmed

    def confirm_then_reconnect(*args, **kwargs):
        result = confirm(*args, **kwargs)
        env.api.session_generation = 2  # this attempt cannot complete the switch
        return result

    env.api.ensure_settlement_confirmed = confirm_then_reconnect
    env.api.trading_day = TOMORROW
    facts = env.api.direct_account_facts(EXCHANGE, positions=False, active_orders=False)
    broker._direct_facts_results.append(("funds", facts))
    broker.next()
    assert run_day_switch(broker)["status"] == "pending"
    calls = len(env.api.settlement_calls)
    marker_id = env.api.settlement_calls[-1].marker_id
    broker._direct_request_day_switch(TOMORROW, settle=True)  # e.g. a retarget back
    switch = run_day_switch(broker)
    assert switch["status"] == "completed" and switch["settlement"] == "unclear"
    assert len(env.api.settlement_calls) == calls  # no second confirmation
    assert env.state().pending.get(marker_id)["status"] == "UNKNOWN"
    assert broker.direct_writes_blocked() == BLOCK
    assert _resolution(broker)["status"] == "pending"


def test_another_account_on_the_session_stops_the_loop_without_a_read(env):
    broker, marker_id = _unclear_start(env)
    env.api.settlement_readback = SettlementStatus.CONFIRMED
    env.api.provider.reference = "another-account"
    ran, resolution = run_resolution(broker)
    assert resolution["status"] == "manual_required"
    assert resolution["last_result"] == "account_unverified"
    assert env.api.settlement_reads == []
    assert env.state().pending.get(marker_id)["status"] == "UNKNOWN"
    assert broker.direct_writes_blocked() == BLOCK


# ---------------------------------------------------------------------------
# backoff and cap
# ---------------------------------------------------------------------------
def test_incomplete_readback_retries_after_the_backoff_then_requires_manual(env):
    broker, marker_id = _unclear_start(env, direct_settlement_resolution_attempts=3)
    env.api.settlement_readback = SettlementStatus.UNKNOWN  # incomplete readback
    calls = len(env.api.settlement_calls)
    # First attempt one base interval (15 s) after the unclear outcome.
    assert 14.0 < broker._direct_settlement_due - time.monotonic() <= 15.0
    assert broker._direct_settlement_poll() is False  # not due: nothing read
    assert env.api.settlement_reads == []

    for attempt, delay in ((1, 30.0), (2, 60.0)):
        ran, resolution = run_resolution(broker)
        assert ran is True
        assert resolution["status"] == "pending" and resolution["attempts"] == attempt
        assert resolution["last_result"] == "unknown"
        assert delay - 1.0 < broker._direct_settlement_due - time.monotonic() <= delay
        assert broker._direct_settlement_poll() is False  # backoff respected
        assert len(env.api.settlement_reads) == attempt

    ran, resolution = run_resolution(broker)
    assert resolution["status"] == "manual_required" and resolution["attempts"] == 3
    assert resolution["max_attempts"] == 3 and resolution["last_result"] == "unknown"
    assert broker._direct_settlement_request is None
    broker._direct_settlement_due = 0.0
    assert broker._direct_settlement_poll() is False  # no more attempts
    assert len(env.api.settlement_reads) == 3
    assert len(env.api.settlement_calls) == calls  # never confirmed while unclear
    assert env.state().pending.get(marker_id)["status"] == "UNKNOWN"
    assert broker.direct_writes_blocked() == BLOCK


# ---------------------------------------------------------------------------
# stop fence (F3)
# ---------------------------------------------------------------------------
def test_stop_during_the_readback_closes_nothing_and_confirms_nothing(env):
    broker, marker_id = _unclear_start(env)
    env.api.settlement_result = SettlementStatus.CONFIRMED
    reading, release = threading.Event(), threading.Event()
    read = env.api.provider.settlement_status

    def slow_read():
        reading.set()
        release.wait(10)
        return read()  # complete, not confirmed: a reconfirmation would be due

    env.api.provider.settlement_status = slow_read
    calls = len(env.api.settlement_calls)
    broker._direct_settlement_due = 0.0
    poller = threading.Thread(target=broker._direct_settlement_poll, daemon=True)
    poller.start()
    assert reading.wait(5)
    assert broker.stop()["status"] == "STOPPED"
    release.set()
    poller.join(5)
    assert not poller.is_alive()
    assert len(env.api.settlement_calls) == calls  # no confirmation after stop() began
    assert env.state().pending.get(marker_id)["status"] == "UNKNOWN"  # not closed
    kind, payload = broker._direct_facts_results[-1]
    assert kind == "settlement_resolution" and payload["result"] == "broker_stopping"


def test_a_due_attempt_after_stop_reads_and_writes_nothing(env):
    broker, marker_id = _unclear_start(env)
    env.api.settlement_result = SettlementStatus.CONFIRMED
    calls = len(env.api.settlement_calls)
    broker.stop()
    broker._direct_settlement_due = 0.0
    broker._direct_settlement_poll()
    assert env.api.settlement_reads == []
    assert len(env.api.settlement_calls) == calls
    assert env.state().pending.get(marker_id)["status"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# restart
# ---------------------------------------------------------------------------
def test_restart_with_an_unknown_marker_of_today_runs_the_same_loop(env):
    broker, marker_id = _unclear_start(env)
    broker.stop()
    env.api.settlement_readback = SettlementStatus.UNKNOWN
    calls = len(env.api.settlement_calls)
    again = env.start()  # first attempt synchronously, before started
    quiet(again)
    assert env.api.settlement_reads == [TODAY]
    assert len(env.api.settlement_calls) == calls
    resolution = _resolution(again)
    assert resolution["status"] == "pending" and resolution["attempts"] == 1
    assert resolution["source"] == "restart"
    assert again.direct_writes_blocked() == BLOCK

    env.api.settlement_readback = SettlementStatus.CONFIRMED
    ran, resolution = run_resolution(again)
    assert resolution["status"] == "resolved" and resolution["attempts"] == 2
    assert env.state().pending.get(marker_id)["status"] == "TERMINAL"
    assert again.direct_writes_blocked() == {}


def test_restart_on_another_day_leaves_the_marker_untouched(env):
    broker, marker_id = _unclear_start(env)
    broker.stop()
    env.api.trading_day = TOMORROW
    env.api.settlement_result = SettlementStatus.CONFIRMED
    again = env.start()
    quiet(again)
    assert env.api.settlement_reads == []  # no readback can speak for another day
    assert env.state().pending.get(marker_id)["status"] == "UNKNOWN"
    assert again.direct_writes_blocked() == {"*": "pending_unknown"}
    assert "settlement_resolution" not in again.get_direct_reconcile_report()
    assert again._direct_settlement_request is None


def test_a_disabled_loop_reads_nothing_and_requires_manual_resolution(env):
    broker, marker_id = _unclear_start(env)
    broker.stop()
    env.api.settlement_readback = SettlementStatus.CONFIRMED
    again = env.start(direct_settlement_resolution_attempts=0)
    quiet(again)
    assert env.api.settlement_reads == []
    resolution = _resolution(again)
    assert resolution["status"] == "manual_required" and resolution["attempts"] == 0
    assert env.state().pending.get(marker_id)["status"] == "UNKNOWN"
    assert again.direct_writes_blocked() == BLOCK
