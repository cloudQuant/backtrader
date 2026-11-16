"""BT-side double proof of the 65.07 projection rows (INV65-07, D65-03).

INV65-07 keeps BT product code unchanged for Execution, so this file touches no
Broker, Strategy or order-dispatch code.  It exercises only the existing private
``_execution_parent_projection`` with real BT ``Order``/``DataBase``/``Position``
objects and synthetic in-memory fact doubles.

Rows proved here:

* only a ``VENUE`` fill becomes a position delta (a plan, a reservation, a sent
  child and a non-venue source never do);
* ``UNKNOWN``, frozen, unknown-child and absent facts never become a terminal
  order status, including after a persisted restart;
* dedupe holds across two fact snapshots, a JSON persistence round trip and a
  restart, and a later fact advances exactly once;
* a foreign status/fill identity is refused with a finite code, no emitted fact
  and no position delta, including after a restart;
* parent/child totals and per-child state are projected only from the supplied
  facts (a test-side consistency view; no product accessor is added).

Evidence level: UNIT/FAKE.  Nothing here proves an Execution service, a Gateway
acceptance, a venue fill, an account position or a delivered notification.
"""

import json
from decimal import Decimal

import pytest

import backtrader as bt
from backtrader.brokers._execution_parent_projection import (
    CHILD_STATES,
    CODES,
    apply_position_delta,
)
from backtrader.order import Order

from ._support import Ports, child, fill, make_order, projection, status

TERMINAL_STATUSES = (Order.Rejected, Order.Completed, Order.Canceled, Order.Expired)
TERMINAL_KINDS = frozenset({"rejected", "canceled", "completed"})


def _ports(**kwargs):
    _order, binding = make_order()
    kwargs.setdefault("statuses", {"req-1": status("ACCEPTED")})
    return Ports({"req-1": binding}, **kwargs)


def _persist(proj):
    """The restart state as a process would persist it: JSON text and back."""
    return json.loads(json.dumps(proj.snapshot(), sort_keys=True))


# ---------------------------------------------------------------------------
# row: only a VENUE fill becomes a position delta
# ---------------------------------------------------------------------------
def test_only_venue_fills_become_position_deltas():
    ports = _ports(fills={"req-1": (fill("f1", quantity="1", price="3500"),)})
    proj = projection(ports)
    first = proj.project("req-1")
    (delta,) = first.position_deltas
    position = bt.Position()
    apply_position_delta(position, delta)
    assert position.size == 1 and position.price == 3500.0

    # A later snapshot adds one non-venue fact.  The whole snapshot is refused,
    # so the internal transfer is never counted and the already-proven venue
    # fill is not applied a second time.
    ports.fill_facts["req-1"] = (
        fill("f1", quantity="1", price="3500"),
        fill("f2", child_id="c1", quantity="1", price="3500", source="INTERNAL_TRANSFER"),
    )
    refused = proj.project("req-1")
    assert refused.refused is True
    assert refused.code == "FILL_SOURCE_UNSUPPORTED"
    assert refused.code in CODES
    assert refused.position_deltas == ()
    assert refused.notifications == ()
    assert refused.parent_fact.filled == "1"
    assert position.size == 1

    # The venue-only snapshot still applies nothing new and keeps the fact.
    ports.fill_facts["req-1"] = (fill("f1", quantity="1", price="3500"),)
    recovered = proj.project("req-1")
    assert recovered.refused is False
    assert recovered.position_deltas == ()
    assert recovered.parent_fact.filled == "1"
    assert position.size == 1


@pytest.mark.parametrize("state", CHILD_STATES)
def test_child_states_never_produce_a_position_delta(state):
    ports = _ports(
        statuses={"req-1": status("ACCEPTED", children=(child("c1", state, quantity="3"),))}
    )
    result = projection(ports).project("req-1")
    assert result.position_deltas == ()
    assert result.parent_fact.filled == "0"
    assert result.parent_fact.remaining == "3"
    (fact,) = result.parent_fact.children
    assert fact.state == state
    assert fact.bt_status is None
    assert fact.affects_bt_status is False


# ---------------------------------------------------------------------------
# row: UNKNOWN / frozen never terminal, across a persisted restart
# ---------------------------------------------------------------------------
_CASES = [
    pytest.param(
        lambda: status("UNKNOWN"),
        "EXECUTION_PARENT_UNKNOWN",
        lambda: status("ACCEPTED"),
        ["accepted"],
        id="parent-unknown",
    ),
    pytest.param(
        lambda: status("ACCEPTED", frozen=True),
        "EXECUTION_PARENT_FROZEN",
        lambda: status("ACCEPTED"),
        [],
        id="frozen-accepted",
    ),
    pytest.param(
        lambda: status("ACCEPTED", children=(child("c1", "UNKNOWN"),)),
        "EXECUTION_CHILD_UNKNOWN",
        lambda: status("ACCEPTED", children=(child("c1", "SENT"),)),
        [],
        id="unknown-child",
    ),
    pytest.param(
        lambda: None,
        "EXECUTION_STATUS_ABSENT",
        lambda: status("ACCEPTED"),
        ["accepted"],
        id="absent-status",
    ),
]


@pytest.mark.parametrize("fact_factory, reason_code, resolution_factory, resolved_kinds", _CASES)
def test_unknown_or_frozen_facts_stay_non_terminal_across_a_restart(
    fact_factory, reason_code, resolution_factory, resolved_kinds
):
    fact = fact_factory()
    ports = Ports(
        {"req-1": make_order()[1]},
        statuses={} if fact is None else {"req-1": fact},
        fills={"req-1": ()},
    )
    proj = projection(ports)
    first = proj.project("req-1")
    assert first.refused is False
    assert first.parent_fact.bt_status not in TERMINAL_STATUSES
    assert first.parent_fact.terminal is False
    assert first.parent_fact.unknown is True
    assert first.parent_fact.frozen is True
    assert first.parent_fact.reason_code == reason_code
    assert not ({item.kind for item in first.notifications} & TERMINAL_KINDS)

    snapshot = _persist(proj)
    restarted = projection(ports, restore=snapshot)

    # The same persisted fact is not re-emitted and never becomes terminal.
    again = restarted.project("req-1")
    assert again.refused is False
    assert again.position_deltas == ()
    assert again.notifications == ()
    assert again.parent_fact.bt_status not in TERMINAL_STATUSES
    assert again.parent_fact.terminal is False
    assert again.parent_fact.unknown is True
    assert again.parent_fact.frozen is True
    assert again.parent_fact.reason_code == reason_code

    # An authoritative resolution advances once and is not terminal either.
    ports.statuses["req-1"] = resolution_factory()
    resolved = restarted.project("req-1")
    assert resolved.parent_fact.bt_status == Order.Accepted
    assert resolved.parent_fact.bt_status not in TERMINAL_STATUSES
    assert resolved.parent_fact.terminal is False
    assert resolved.parent_fact.unknown is False
    assert resolved.parent_fact.frozen is False
    assert resolved.position_deltas == ()
    assert [item.kind for item in resolved.notifications] == resolved_kinds
    assert restarted.project("req-1").notifications == ()


def test_a_frozen_pre_acceptance_fact_is_non_terminal():
    ports = Ports(
        {"req-1": make_order()[1]},
        statuses={"req-1": status("REGISTERING", frozen=True)},
        fills={"req-1": ()},
    )
    result = projection(ports).project("req-1")
    fact = result.parent_fact
    assert fact.bt_status == Order.Submitted
    assert fact.bt_status not in TERMINAL_STATUSES
    assert fact.terminal is False
    assert fact.unknown is True and fact.frozen is True
    assert fact.reason_code == "EXECUTION_PARENT_FROZEN"
    assert not ({item.kind for item in result.notifications} & TERMINAL_KINDS)


# The row below is the one place a BT product change would be required
# (INV65-07 / D65-03): ``PARENT_TRANSITIONS`` omits the identity transition for
# RECEIVED/RISK_CLAIMED/REGISTERING, so re-projecting the same authoritative
# pre-acceptance state is refused as EXECUTION_STATE_REGRESSED instead of being
# idempotent.  BT product code is not changed here; the strict xfail records the
# evidence and fails if a later change ever makes the row pass without removing
# this marker.  The fact itself stays non-terminal and no delta is duplicated.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "repeated pre-acceptance state is refused as EXECUTION_STATE_REGRESSED; "
        "fixing it changes BT product code (INV65-07/D65-03)"
    ),
)
@pytest.mark.parametrize("state", ["RECEIVED", "RISK_CLAIMED", "REGISTERING"])
def test_repeating_the_same_pre_acceptance_state_is_idempotent(state):
    ports = Ports(
        {"req-1": make_order()[1]},
        statuses={"req-1": status(state)},
        fills={"req-1": ()},
    )
    proj = projection(ports)
    first = proj.project("req-1")
    assert first.refused is False
    second = proj.project("req-1")
    assert second.refused is False
    assert second.code is None
    assert second.notifications == ()
    assert second.parent_fact.bt_status == first.parent_fact.bt_status


# ---------------------------------------------------------------------------
# row: dedupe across two snapshots, JSON persistence and a restart
# ---------------------------------------------------------------------------
def test_two_snapshots_and_a_json_restart_do_not_double_count():
    ports = _ports(fills={"req-1": (fill("f1", quantity="1", price="3500"),)})
    proj = projection(ports)
    first = proj.project("req-1")
    position = bt.Position()
    apply_position_delta(position, first.position_deltas[0])
    first_keys = [item.dedupe_key for item in first.notifications]
    assert len(first_keys) == 2

    snapshot_a = _persist(proj)
    second = proj.project("req-1")
    assert second.position_deltas == () and second.notifications == ()
    snapshot_b = _persist(proj)
    assert snapshot_a == snapshot_b

    for snapshot in (snapshot_a, snapshot_b):
        restarted = projection(ports, restore=snapshot)
        assert restarted.projection_status().restored is True
        result = restarted.project("req-1")
        assert result.position_deltas == ()
        assert result.notifications == ()
        assert result.suppressed_fills == 1
        assert result.suppressed_notifications == len(first_keys)
        assert position.size == 1

    # A later fact after the restart advances exactly once.
    ports.fill_facts["req-1"] = (
        fill("f1", quantity="1", price="3500"),
        fill("f2", quantity="1", price="3501"),
    )
    advanced = projection(ports, restore=snapshot_b).project("req-1")
    assert [delta.fill_id for delta in advanced.position_deltas] == ["f2"]
    apply_position_delta(position, advanced.position_deltas[0])
    assert position.size == 2 and position.price == pytest.approx(3500.5)
    replay = projection(ports, restore=snapshot_b).project("req-1")
    assert [delta.fill_id for delta in replay.position_deltas] == ["f2"]
    # The replay comes from the same persisted snapshot, so the delta identity
    # (not a second fill) is what a caller must dedupe on.
    assert replay.position_deltas[0].delta_key == advanced.position_deltas[0].delta_key


# ---------------------------------------------------------------------------
# row: a foreign identity is refused
# ---------------------------------------------------------------------------
def test_a_restarted_projection_refuses_a_foreign_status_identity():
    ports = _ports()
    proj = projection(ports)
    first = proj.project("req-1")
    assert first.parent_fact.bt_status == Order.Accepted
    snapshot = _persist(proj)

    ports.statuses["req-1"] = status("ACCEPTED", request_id="req-2")
    restarted = projection(ports, restore=snapshot)
    refused = restarted.project("req-1")
    assert refused.refused is True
    assert refused.code == "EXECUTION_IDENTITY_FOREIGN"
    assert refused.code in CODES
    assert refused.position_deltas == ()
    assert refused.notifications == ()
    assert refused.parent_fact.bt_status == Order.Accepted
    assert refused.parent_fact.terminal is False


def test_a_restarted_projection_refuses_a_foreign_fill_identity():
    ports = _ports()
    proj = projection(ports)
    proj.project("req-1")
    snapshot = _persist(proj)
    ports.fill_facts["req-1"] = (fill("f1", quantity="1", parent_ref="par-9"),)

    result = projection(ports, restore=snapshot).project("req-1")
    assert result.refused is True
    assert result.code == "FILL_FACT_FOREIGN"
    assert result.code in CODES
    assert result.position_deltas == ()
    assert result.notifications == ()
    assert result.parent_fact.bt_status == Order.Accepted


def test_a_foreign_child_identity_is_refused_without_touching_the_first_request():
    _first_order, first_binding = make_order(request_id="req-1")
    _second_order, second_binding = make_order(request_id="req-2")
    ports = Ports(
        {"req-1": first_binding, "req-2": second_binding},
        statuses={
            "req-1": status("ACCEPTED", request_id="req-1", children=(child("c1", "SENT"),)),
            "req-2": status("ACCEPTED", request_id="req-2", children=(child("c1", "SENT"),)),
        },
        fills={"req-1": (), "req-2": ()},
    )
    proj = projection(ports)
    first = proj.project("req-1")
    assert first.refused is False
    snapshot = _persist(proj)

    refused = projection(ports, restore=snapshot).project("req-2")
    assert refused.refused is True
    assert refused.code == "EXECUTION_CHILD_IDENTITY_FOREIGN"
    assert refused.position_deltas == ()
    assert refused.notifications == ()
    # The restored first request is untouched and still projects its own child.
    own = projection(ports, restore=snapshot).project("req-1")
    assert own.refused is False
    assert own.parent_fact.children[0].child_id == "c1"


# ---------------------------------------------------------------------------
# strategy-view consistency, computed only from the supplied facts
# ---------------------------------------------------------------------------
def test_parent_and_child_totals_are_projected_from_the_supplied_facts_only():
    children = (
        child("c1", "SENT", quantity="1"),
        child("c2", "SENT", quantity="1"),
        child("c3", "PLANNED", quantity="1", attempts=0),
    )
    ports = _ports(
        statuses={"req-1": status("ACCEPTED", children=children)},
        fills={
            "req-1": (
                fill("f1", child_id="c1", quantity="1", price="3500"),
                fill("f2", child_id="c2", quantity="1", price="3501"),
            )
        },
    )
    result = projection(ports).project("req-1")
    fact = result.parent_fact
    assert (fact.quantity, fact.filled, fact.remaining) == ("3", "2", "1")
    assert [delta.child_id for delta in result.position_deltas] == ["c1", "c2"]
    assert [
        (item.child_id, item.state, item.quantity, item.filled, item.remaining)
        for item in fact.children
    ] == [
        ("c1", "SENT", "1", "1", "0"),
        ("c2", "SENT", "1", "1", "0"),
        ("c3", "PLANNED", "1", "0", "1"),
    ]
    assert sum(Decimal(item.filled) for item in fact.children) == Decimal(fact.filled)
    assert sum(Decimal(item.quantity) for item in fact.children) == Decimal(fact.quantity)
    assert [item.bt_status for item in fact.children] == [None, None, None]
    assert not any(item.affects_bt_status for item in fact.children)
    assert fact.terminal is False

    # With no supplied status or children nothing is invented: no child rows,
    # no fill, an explicit unknown and the declared quantity only.
    bare = Ports({"req-1": make_order()[1]}, statuses={}, fills={"req-1": ()})
    bare_fact = projection(bare).project("req-1").parent_fact
    assert bare_fact.children == ()
    assert bare_fact.filled == "0"
    assert bare_fact.remaining == "3"
    assert bare_fact.fills_known is True
    assert bare_fact.unknown is True
    assert bare_fact.reason_code == "EXECUTION_STATUS_ABSENT"
