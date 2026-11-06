"""Restart after an unclear trading-day-switch settlement (R-3 review F6, D62-29).

The switch marks its settlement confirmation UNKNOWN when the outcome is
unclear.  At the next start, an UNKNOWN ``settlement_confirm`` marker of the
verified current route and trading day is checked by one read-only settlement
readback on the current session: ``confirmed`` closes it (TERMINAL, evidence
``settlement_readback``); anything else keeps it UNKNOWN, keeps every write
blocked and never confirms again.  Markers of other days are left for manual
resolution.  Also: the facts poller publishes a verification payload before it
counts it.

UNIT/FAKE: fake facade (read-only provider settlement state), real
``backtrader.live_state`` in ``tmp_path``.
"""

import collections
import datetime as dt

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from backtrader.live_state import read_audit
from bt_api_base.direct_write_protocol import SettlementStatus

from ._fakes import EXCHANGE, TOMORROW, quiet, run_day_switch

NEW_DAY = dt.date(2026, 11, 6)


def _buy(env, broker):
    return broker.buy(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )


def _new_day(env, broker):
    env.api.trading_day = TOMORROW
    env.api.positions, env.api.active_orders, env.api.orders, env.api.trades = [], [], [], []
    facts = env.api.direct_account_facts(EXCHANGE, positions=False, active_orders=False)
    broker._direct_facts_results.append(("funds", facts))
    broker.next()


def _unclear_switch_settlement(env) -> str:
    """Run a switch whose settlement confirmation was committed with no clear result."""
    env.init_flat()
    broker = env.start()
    quiet(broker)
    env.api.schedule.trading_day = NEW_DAY
    env.api.settlement_result = SettlementStatus.UNKNOWN
    _new_day(env, broker)
    assert run_day_switch(broker)["settlement"] == "unclear"
    marker_id = env.api.settlement_calls[-1].marker_id
    marker = env.state().pending.get(marker_id)
    assert marker["status"] == "UNKNOWN" and marker["trading_day"] == TOMORROW
    broker.stop()
    env.api.settlement_result = SettlementStatus.CONFIRMED
    return marker_id


def test_unclear_switch_settlement_is_resolved_by_a_confirmed_readback(env):
    marker_id = _unclear_switch_settlement(env)
    env.api.settlement_readback = SettlementStatus.CONFIRMED  # read-only: confirmed today
    calls = len(env.api.settlement_calls)
    again = env.start()
    assert again.direct_writes_blocked() == {}, again.direct_writes_blocked()
    marker = env.state().pending.get(marker_id)
    assert marker["status"] == "TERMINAL"
    assert marker["facts"]["final_status"] == "confirmed"
    assert marker["facts"]["resolution_evidence"] == "settlement_readback"
    assert marker["resolution"]["kind"] == "settlement_readback"
    assert env.api.settlement_reads == [TOMORROW]  # one read on the current session
    # The usual startup step only read again: nothing new was committed or sent.
    assert [call.marker_id for call in env.api.settlement_calls[calls:]] == [None]
    (entry,) = again.get_direct_reconcile_report()["settlement_readbacks"]
    assert entry == {
        "marker_id": marker_id,
        "trading_day": TOMORROW,
        "status": "confirmed",
        "resolved": True,
    }
    (audit,) = [
        record
        for record in read_audit(str(env.strategy_dir))
        if record["event"] == "pending_settlement_readback_resolution"
    ]
    assert audit["marker_id"] == marker_id and audit["trading_day"] == TOMORROW
    assert _buy(env, again).status == bt.Order.Submitted


def _session_moves(api):
    def read():
        api.session_generation = 2  # re-login while reading: not this session's answer
        return SettlementStatus.CONFIRMED

    api.provider.settlement_status = read


@pytest.mark.parametrize(
    "readback, status",
    [
        (lambda api: None, "unconfirmed"),  # complete readback: not confirmed
        (lambda api: setattr(api, "settlement_readback", SettlementStatus.UNKNOWN), "unknown"),
        (
            lambda api: setattr(api, "settlement_error", TimeoutError("readback timed out")),
            "readback_failed:TimeoutError",
        ),
        (lambda api: delattr(api.provider, "settlement_status"), "readback_unavailable"),
        (_session_moves, "session_changed"),
    ],
    ids=["unconfirmed", "unknown", "failed", "unavailable", "session_changed"],
)
def test_unclear_switch_settlement_without_a_confirmed_readback_stays_blocked(
    env, readback, status
):
    marker_id = _unclear_switch_settlement(env)
    readback(env.api)
    calls = len(env.api.settlement_calls)
    again = env.start()
    assert again.direct_writes_blocked() == {"*": "pending_unknown"}
    assert env.state().pending.get(marker_id)["status"] == "UNKNOWN"
    # Never confirmed again automatically (no blind retry), not even read-first.
    assert len(env.api.settlement_calls) == calls
    (entry,) = again.get_direct_reconcile_report()["settlement_readbacks"]
    assert entry["status"] == status and entry["resolved"] is False
    assert _buy(env, again).info["error_code"] == "pending_unknown"


def test_unclear_settlement_of_another_day_is_left_for_manual_resolution(env):
    marker_id = _unclear_switch_settlement(env)
    env.api.trading_day = "20261109"  # restarted on a later trading day
    env.api.settlement_readback = SettlementStatus.CONFIRMED
    again = env.start()
    assert env.api.settlement_reads == []  # no readback can speak for another day
    assert env.state().pending.get(marker_id)["status"] == "UNKNOWN"
    assert again.direct_writes_blocked() == {"*": "pending_unknown"}
    assert "settlement_readbacks" not in again.get_direct_reconcile_report()


# ---------------------------------------------------------------------------
# facts poller hand-off
# ---------------------------------------------------------------------------
def test_the_poller_publishes_the_switch_payload_before_counting_it(env):
    """A reader that sees the ``day_switch`` count must also find the payload."""
    broker = env.start(first_init=True)
    quiet(broker)
    env.api.schedule.trading_day = NEW_DAY
    _new_day(env, broker)
    counts_at_append = []

    class Recording(collections.deque):
        def append(self, item):
            counts_at_append.append(broker.get_direct_refresh_counts()["day_switch"])
            super().append(item)

    broker._direct_facts_results = Recording(broker._direct_facts_results, maxlen=8)
    broker._direct_day_switch_due = 0.0
    broker._direct_day_switch_poll()
    assert counts_at_append == [0]
    assert broker.get_direct_refresh_counts()["day_switch"] == 1
    broker.next()
    report = broker.get_direct_reconcile_report()["trading_day_switch"]
    assert report["status"] == "completed"
