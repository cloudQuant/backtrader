"""UNKNOWN, frozen and unreadable facts stay active with finite codes (65.07).

A missing status, a failed read, an unrecognized state and an UNKNOWN child are
UNKNOWN facts: never ``Rejected``, ``Completed`` or ``Canceled`` and never "not
sent".  A fill read failure never invents a fill and never erases the fills
that were already applied.
"""

import pytest

from backtrader.brokers._execution_parent_projection import (
    CODES,
    ExecutionParentProjection,
    ParentProjection,
)
from backtrader.order import Order

from ._support import Ports, child, fill, make_order, projection, status


def _ports(**kwargs):
    _order, binding = make_order()
    kwargs.setdefault("statuses", {"req-1": status("ACCEPTED")})
    return Ports({"req-1": binding}, **kwargs)


def test_missing_fill_source_is_unknown_not_zero_fills():
    _order, binding = make_order()
    proj = ExecutionParentProjection(
        binding_port={"req-1": binding},
        status_port={"req-1": status("ACCEPTED")},
    )
    result = proj.project("req-1")
    fact = result.parent_fact
    assert result.fills_known is False
    assert fact.fills_known is False
    assert fact.unknown is True
    assert fact.reason_code == "FILL_PORT_UNAVAILABLE"
    assert fact.filled == "0"
    assert result.position_deltas == ()
    assert [item.kind for item in result.notifications] == ["submitted", "accepted", "unknown"]
    assert proj.projection_status().unknown_facts == 1


def test_fill_read_failure_keeps_the_prior_total_and_recovers_once():
    ports = _ports(fills={"req-1": (fill("f1", quantity="1"),)})
    proj = projection(ports)
    first = proj.project("req-1")
    assert first.parent_fact.filled == "1"
    assert first.fills_known is True
    ports.raise_on.add("fills")
    failed = proj.project("req-1")
    assert failed.fills_known is False
    assert failed.position_deltas == ()
    assert failed.parent_fact.filled == "1"
    assert failed.parent_fact.reason_code == "FILL_PORT_UNAVAILABLE"
    assert failed.parent_fact.unknown is True
    ports.raise_on.clear()
    ports.fill_facts["req-1"] = (fill("f1", quantity="1"), fill("f2", quantity="1"))
    recovered = proj.project("req-1")
    assert [delta.fill_id for delta in recovered.position_deltas] == ["f2"]
    assert recovered.parent_fact.filled == "2"
    assert recovered.parent_fact.unknown is False
    assert recovered.fills_known is True


def test_status_read_failure_is_unknown_and_keeps_the_last_fact():
    ports = _ports()
    proj = projection(ports)
    first = proj.project("req-1")
    assert first.parent_fact.bt_status == Order.Accepted
    ports.raise_on.add("status")
    failed = proj.project("req-1")
    fact = failed.parent_fact
    assert fact.bt_status == Order.Accepted
    assert fact.unknown is True and fact.frozen is True
    assert fact.reason_code == "EXECUTION_STATUS_UNREADABLE"
    assert [item.kind for item in failed.notifications] == ["unknown"]
    assert failed.notifications[0].reason_code == "EXECUTION_STATUS_UNREADABLE"


def test_absent_status_keeps_the_last_accepted_fact_unknown():
    ports = _ports()
    proj = projection(ports)
    proj.project("req-1")
    del ports.statuses["req-1"]
    failed = proj.project("req-1")
    fact = failed.parent_fact
    assert fact.bt_status == Order.Accepted
    assert fact.state == "ACCEPTED"
    assert fact.reason_code == "EXECUTION_STATUS_ABSENT"
    assert fact.unknown is True and fact.frozen is True
    assert [item.kind for item in failed.notifications] == ["unknown"]
    ports.statuses["req-1"] = status("ACCEPTED")
    recovered = proj.project("req-1")
    assert recovered.notifications == ()
    assert recovered.parent_fact.unknown is False
    assert recovered.parent_fact.bt_status == Order.Accepted


def test_unknown_parent_with_a_fill_still_advances_the_fill_once():
    ports = _ports(
        statuses={"req-1": status("UNKNOWN")},
        fills={"req-1": (fill("f1", quantity="1"),)},
    )
    proj = projection(ports)
    first = proj.project("req-1")
    assert [delta.fill_id for delta in first.position_deltas] == ["f1"]
    assert first.parent_fact.filled == "1"
    assert first.parent_fact.bt_status == Order.Submitted
    assert first.parent_fact.unknown is True and first.parent_fact.frozen is True
    assert first.parent_fact.reason_code == "EXECUTION_PARENT_UNKNOWN"
    replay = proj.project("req-1")
    assert replay.position_deltas == ()
    assert replay.parent_fact.filled == "1"


def test_unknown_child_freezes_the_parent_until_it_resolves():
    ports = _ports(statuses={"req-1": status("ACCEPTED", children=(child("c1", "UNKNOWN"),))})
    proj = projection(ports)
    first = proj.project("req-1")
    fact = first.parent_fact
    assert fact.bt_status == Order.Accepted
    assert fact.frozen is True and fact.unknown is True
    assert fact.reason_code == "EXECUTION_CHILD_UNKNOWN"
    assert [item.kind for item in first.notifications] == ["submitted", "accepted", "unknown"]
    ports.statuses["req-1"] = status("ACCEPTED", children=(child("c1", "SENT"),))
    resolved = proj.project("req-1")
    assert resolved.notifications == ()
    assert resolved.parent_fact.frozen is False
    assert resolved.parent_fact.unknown is False
    assert resolved.position_deltas == ()
    # A resolved child does not move backwards.
    ports.statuses["req-1"] = status("ACCEPTED", children=(child("c1", "UNKNOWN"),))
    regressed = proj.project("req-1")
    assert regressed.refused is True
    assert regressed.code == "EXECUTION_CHILD_STATE_REGRESSED"


def test_two_states_bt_cannot_see_are_reported_with_distinct_finite_reasons():
    ports = _ports(
        statuses={
            "req-1": status("ACCEPTED", frozen=True),
            "req-2": status("UNKNOWN", request_id="req-2"),
        }
    )
    order1, binding1 = make_order(request_id="req-1")
    _order2, binding2 = make_order(request_id="req-2")
    ports.bindings.update({"req-1": binding1, "req-2": binding2})
    proj = projection(ports)
    frozen = proj.project("req-1").parent_fact
    unknown = proj.project("req-2").parent_fact
    assert frozen.reason_code == "EXECUTION_PARENT_FROZEN"
    assert unknown.reason_code == "EXECUTION_PARENT_UNKNOWN"
    for fact in (frozen, unknown):
        assert fact.bt_status in (Order.Submitted, Order.Accepted)
        assert fact.terminal is False
        assert fact.reason_code in CODES
    assert proj.projection_status().unknown_facts == 2


def test_projection_status_is_a_read_only_finite_view():
    ports = _ports()
    proj = projection(ports)
    proj.project("req-1")
    status_view = proj.projection_status()
    payload = status_view.payload()
    assert set(payload) == {
        "schema",
        "requests",
        "parents_projected",
        "children",
        "notifications_issued",
        "notifications_suppressed",
        "position_deltas_applied",
        "fills_suppressed",
        "refused",
        "conflicts",
        "unknown_facts",
        "restored",
        "last_error_code",
    }
    assert payload["schema"] == "execution.parent_projection/v1"
    assert payload["requests"] == 1
    assert payload["parents_projected"] == 1
    assert payload["last_error_code"] is None
    with pytest.raises(TypeError):
        payload["requests"] = 99
    assert isinstance(proj.project("req-1"), ParentProjection)
