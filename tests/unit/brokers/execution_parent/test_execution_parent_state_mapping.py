"""Execution parent/child state mapping to BT order facts (65.07, UNIT/FAKE).

Real BT orders carry the declared binding; the Execution facts are synthetic
mappings in the committed ``parent_submit_service.status()`` shape.  No
Execution service, Gateway, provider or account is contacted.
"""

import pytest

import backtrader as bt
from backtrader.brokers._execution_parent_projection import (
    CHILD_STATES,
    ExecutionParentProjectionError,
    order_binding,
)
from backtrader.order import Order

from ._support import (
    Ports,
    absent_status,
    cancel,
    child,
    completion,
    fill,
    kinds,
    make_feed,
    make_order,
    projection,
    status,
)


def _project(statuses, *, fills=None, cancels=None, completions=None, binding=None):
    _order, binding = make_order() if binding is None else (None, binding)
    ports = Ports(
        {"req-1": binding},
        statuses=statuses,
        fills=fills,
        cancels=cancels,
        completions=completions,
    )
    return projection(ports), ports


# ---------------------------------------------------------------------------
# parent states
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("state", ["RECEIVED", "RISK_CLAIMED", "REGISTERING"])
def test_pre_acceptance_states_stay_submitted(state):
    proj, _ports = _project({"req-1": status(state)})
    result = proj.project("req-1")
    fact = result.parent_fact
    assert result.refused is False and result.code is None
    assert fact.bt_status == Order.Submitted
    assert fact.bt_status_name == "Submitted"
    assert fact.terminal is False and fact.unknown is False and fact.frozen is False
    assert kinds(result) == ["submitted"]
    assert result.notifications[0].bt_ref == fact.bt_ref


def test_forward_pre_acceptance_states_notify_once():
    proj, ports = _project({"req-1": status("RECEIVED")})
    assert kinds(proj.project("req-1")) == ["submitted"]
    ports.statuses["req-1"] = status("RISK_CLAIMED")
    second = proj.project("req-1")
    assert second.notifications == () and second.suppressed_notifications == 1
    ports.statuses["req-1"] = status("REGISTERING")
    third = proj.project("req-1")
    assert third.notifications == () and third.suppressed_notifications == 1
    ports.statuses["req-1"] = status("ACCEPTED")
    fourth = proj.project("req-1")
    assert kinds(fourth) == ["accepted"]
    assert fourth.parent_fact.bt_status == Order.Accepted


def test_accepted_state_and_restart_first_fact():
    proj, _ports = _project({"req-1": status("ACCEPTED")})
    result = proj.project("req-1")
    assert kinds(result) == ["submitted", "accepted"]
    assert result.parent_fact.bt_status == Order.Accepted
    assert result.parent_fact.terminal is False
    keys = [item.dedupe_key for item in result.notifications]
    assert len(set(keys)) == len(keys)
    assert all(key.startswith("epp:") for key in keys)


def test_rejected_state_is_terminal_and_replay_is_suppressed():
    proj, _ports = _project({"req-1": status("REJECTED", last_error="remote_rejected")})
    result = proj.project("req-1")
    assert kinds(result) == ["submitted", "rejected"]
    assert result.parent_fact.bt_status == Order.Rejected
    assert result.parent_fact.terminal is True
    assert result.parent_fact.reason_code == "EXECUTION_REMOTE_REJECTED"
    replay = proj.project("req-1")
    assert replay.notifications == ()
    assert replay.suppressed_notifications == 2
    assert replay.parent_fact.bt_status == Order.Rejected


def test_unknown_state_is_never_terminal():
    proj, _ports = _project({"req-1": status("UNKNOWN", last_error="parent_outcome_unknown")})
    result = proj.project("req-1")
    fact = result.parent_fact
    assert fact.bt_status == Order.Submitted
    assert fact.bt_status not in (Order.Rejected, Order.Completed, Order.Canceled)
    assert fact.terminal is False and fact.unknown is True and fact.frozen is True
    assert fact.reason_code == "EXECUTION_PARENT_UNKNOWN"
    assert kinds(result) == ["submitted", "unknown"]


def test_unknown_resolves_once_to_accepted():
    proj, ports = _project({"req-1": status("UNKNOWN")})
    first = proj.project("req-1")
    assert first.parent_fact.unknown is True
    ports.statuses["req-1"] = status("ACCEPTED")
    second = proj.project("req-1")
    assert kinds(second) == ["accepted"]
    assert second.parent_fact.bt_status == Order.Accepted
    assert second.parent_fact.unknown is False
    third = proj.project("req-1")
    assert third.notifications == ()


def test_unknown_resolves_once_to_rejected():
    proj, ports = _project({"req-1": status("UNKNOWN")})
    proj.project("req-1")
    ports.statuses["req-1"] = status("REJECTED")
    second = proj.project("req-1")
    assert kinds(second) == ["rejected"]
    assert second.parent_fact.bt_status == Order.Rejected


def test_absent_status_is_unknown_not_not_sent():
    proj, _ports = _project({})
    result = proj.project("req-1")
    fact = result.parent_fact
    assert fact.bt_status == Order.Submitted
    assert fact.unknown is True and fact.frozen is True
    assert fact.reason_code == "EXECUTION_STATUS_ABSENT"
    assert kinds(result) == ["submitted", "unknown"]
    assert fact.remaining == "3"


def test_committed_missing_row_shape_is_absent():
    proj, _ports = _project({"req-1": absent_status()})
    result = proj.project("req-1")
    assert result.parent_fact.reason_code == "EXECUTION_STATUS_ABSENT"
    assert result.parent_fact.unknown is True


def test_unrecognized_state_is_unknown():
    proj, _ports = _project({"req-1": status("SETTLING")})
    result = proj.project("req-1")
    fact = result.parent_fact
    assert fact.bt_status == Order.Submitted
    assert fact.state is None
    assert fact.reason_code == "EXECUTION_STATE_UNRECOGNIZED"
    assert fact.unknown is True and fact.frozen is True


def test_frozen_accepted_parent_stays_active_never_terminal():
    proj, _ports = _project({"req-1": status("ACCEPTED", frozen=True)})
    result = proj.project("req-1")
    fact = result.parent_fact
    assert fact.frozen is True and fact.unknown is True
    assert fact.reason_code == "EXECUTION_PARENT_FROZEN"
    assert fact.bt_status == Order.Accepted
    assert fact.terminal is False
    assert kinds(result) == ["submitted", "accepted", "unknown"]


def test_frozen_pre_acceptance_parent_stays_submitted():
    proj, _ports = _project({"req-1": status("REGISTERING", frozen=True)})
    result = proj.project("req-1")
    assert result.parent_fact.bt_status == Order.Submitted
    assert result.parent_fact.frozen is True
    assert result.parent_fact.reason_code == "EXECUTION_PARENT_FROZEN"


# ---------------------------------------------------------------------------
# child states never move the strategy order
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("state", CHILD_STATES)
def test_child_states_never_affect_the_strategy_order(state):
    proj, _ports = _project(
        {"req-1": status("ACCEPTED", children=(child("c1", state, quantity="2"),))}
    )
    result = proj.project("req-1")
    (fact,) = result.parent_fact.children
    assert fact.child_id == "c1"
    assert fact.state == state
    assert fact.bt_status is None
    assert fact.affects_bt_status is False
    assert fact.quantity == "2"
    assert fact.filled == "0"
    assert fact.remaining == "2"
    assert result.parent_fact.bt_status == Order.Accepted
    if state == "UNKNOWN":
        assert fact.unknown is True
        assert fact.reason_code == "EXECUTION_CHILD_UNKNOWN"
        assert result.parent_fact.frozen is True
        assert kinds(result) == ["submitted", "accepted", "unknown"]
    else:
        assert fact.unknown is False
        assert result.parent_fact.frozen is False
        assert kinds(result) == ["submitted", "accepted"]


def test_sent_child_is_not_a_fill_and_planned_attempts_are_visible():
    proj, _ports = _project(
        {
            "req-1": status(
                "ACCEPTED",
                children=(
                    child("c1", "SENT", quantity="2", attempts=2),
                    child("c2", "PLANNED", quantity="1", attempts=0),
                ),
            )
        }
    )
    result = proj.project("req-1")
    assert result.position_deltas == ()
    assert result.parent_fact.filled == "0"
    sent, planned = result.parent_fact.children
    assert sent.state == "SENT" and sent.attempts == 2
    assert planned.state == "PLANNED" and planned.attempts == 0


# ---------------------------------------------------------------------------
# cancel / completion facts
# ---------------------------------------------------------------------------
def test_canceled_fact_is_terminal():
    proj, _ports = _project(
        {"req-1": status("ACCEPTED")}, cancels={"req-1": cancel(outcome="CANCELED")}
    )
    result = proj.project("req-1")
    assert kinds(result) == ["submitted", "accepted", "canceled"]
    fact = result.parent_fact
    assert fact.bt_status == Order.Canceled
    assert fact.terminal is True and fact.unknown is False
    replay = proj.project("req-1")
    assert replay.notifications == ()
    assert replay.parent_fact.bt_status == Order.Canceled


def test_cancel_unknown_keeps_the_order_active():
    proj, _ports = _project(
        {"req-1": status("ACCEPTED")}, cancels={"req-1": cancel(outcome="UNKNOWN")}
    )
    result = proj.project("req-1")
    fact = result.parent_fact
    assert fact.bt_status == Order.Accepted
    assert fact.terminal is False and fact.unknown is True
    assert fact.reason_code == "CANCEL_OUTCOME_UNKNOWN"
    assert kinds(result) == ["submitted", "accepted", "unknown"]


def test_cancel_rejected_does_not_change_the_order():
    proj, _ports = _project(
        {"req-1": status("ACCEPTED")}, cancels={"req-1": cancel(outcome="REJECTED")}
    )
    result = proj.project("req-1")
    fact = result.parent_fact
    assert fact.bt_status == Order.Accepted
    assert fact.unknown is False and fact.frozen is False
    assert fact.reason_code == "CANCEL_REJECTED"
    assert kinds(result) == ["submitted", "accepted"]


def test_cancel_cannot_be_proven_with_an_unknown_child():
    proj, _ports = _project(
        {"req-1": status("ACCEPTED", children=(child("c1", "UNKNOWN"),))},
        cancels={"req-1": cancel(outcome="CANCELED")},
    )
    result = proj.project("req-1")
    fact = result.parent_fact
    assert fact.bt_status == Order.Accepted
    assert fact.terminal is False
    assert fact.reason_code == "CANCEL_UNRESOLVED_CHILDREN"
    assert "canceled" not in kinds(result)


def test_a_late_cancel_does_not_reopen_a_rejected_parent():
    proj, _ports = _project(
        {"req-1": status("REJECTED")}, cancels={"req-1": cancel(outcome="UNKNOWN")}
    )
    result = proj.project("req-1")
    fact = result.parent_fact
    assert fact.bt_status == Order.Rejected
    assert fact.terminal is True
    assert fact.unknown is False and fact.frozen is False
    assert fact.reason_code == "EXECUTION_REMOTE_REJECTED"
    assert kinds(result) == ["submitted", "rejected"]


def test_a_missing_status_after_a_cancel_keeps_the_terminal_fact():
    proj, ports = _project(
        {"req-1": status("ACCEPTED")}, cancels={"req-1": cancel(outcome="CANCELED")}
    )
    first = proj.project("req-1")
    assert first.parent_fact.bt_status == Order.Canceled
    del ports.statuses["req-1"]
    ports.raise_on.add("fills")
    second = proj.project("req-1")
    fact = second.parent_fact
    assert fact.bt_status == Order.Canceled
    assert fact.terminal is True
    assert fact.unknown is False and fact.frozen is False
    assert second.notifications == ()


def test_cancel_resolution_from_unknown_to_canceled():
    proj, ports = _project(
        {"req-1": status("ACCEPTED")}, cancels={"req-1": cancel(outcome="UNKNOWN")}
    )
    proj.project("req-1")
    ports.cancels["req-1"] = cancel(outcome="CANCELED")
    result = proj.project("req-1")
    assert kinds(result) == ["canceled"]
    assert result.parent_fact.bt_status == Order.Canceled


def test_completion_fact_is_the_only_completed_source():
    proj, _ports = _project(
        {"req-1": status("ACCEPTED")},
        fills={"req-1": (fill("f1", quantity="3"),)},
        completions={"req-1": completion(completed_quantity="3")},
    )
    result = proj.project("req-1")
    assert kinds(result) == ["submitted", "accepted", "completed"]
    assert result.parent_fact.bt_status == Order.Completed
    assert result.parent_fact.terminal is True


def test_completion_quantity_mismatch_is_refused():
    proj, _ports = _project(
        {"req-1": status("ACCEPTED")}, completions={"req-1": completion(completed_quantity="2")}
    )
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "COMPLETION_QUANTITY_MISMATCH"
    assert result.notifications == ()


def test_completion_with_unknown_child_is_unprovable():
    proj, _ports = _project(
        {"req-1": status("ACCEPTED", children=(child("c1", "UNKNOWN"),))},
        completions={"req-1": completion(completed_quantity="3")},
    )
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "COMPLETION_FACT_UNPROVABLE"


# ---------------------------------------------------------------------------
# terminal regression
# ---------------------------------------------------------------------------
def test_terminal_rejection_never_regresses_to_accepted():
    proj, ports = _project({"req-1": status("REJECTED")})
    first = proj.project("req-1")
    assert first.parent_fact.bt_status == Order.Rejected
    ports.statuses["req-1"] = status("ACCEPTED")
    second = proj.project("req-1")
    assert second.refused is True
    assert second.code == "EXECUTION_STATE_REGRESSED"
    assert second.parent_fact.bt_status == Order.Rejected


# ---------------------------------------------------------------------------
# declaring the binding from a real BT order
# ---------------------------------------------------------------------------
def test_order_binding_reads_a_real_buy_order_without_submitting():
    order, binding = make_order(side="buy", size=3, price=3500.0)
    assert binding["bt_ref"] == order.ref
    assert binding["side"] == "buy"
    assert binding["quantity"] == "3"
    assert binding["price"] == "3500"
    assert binding["offset"] == "open"
    assert binding["parent_ref"] == "par-1"
    assert order.status == bt.Order.Created
    assert order.broker is None


def test_order_binding_reads_a_real_sell_order():
    order, binding = make_order(side="sell", size=2.5, price=3499.5)
    assert order.issell() is True
    assert binding["side"] == "sell"
    assert binding["quantity"] == "2.5"
    assert binding["price"] == "3499.5"


def test_order_binding_refuses_a_market_order():
    feed = make_feed()
    order = bt.BuyOrder(
        owner=None, data=feed, size=3, price=None, exectype=bt.Order.Market, valid=None
    )
    with pytest.raises(ExecutionParentProjectionError) as error:
        order_binding(order, "req-1", offset="open")
    assert error.value.code == "EXECUTION_BINDING_INVALID"


def test_projection_refuses_a_binding_without_a_limit_price():
    ports = Ports(
        {"req-1": {"bt_ref": 1, "side": "buy", "offset": "open", "quantity": "3", "price": None}}
    )
    result = projection(ports).project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_BINDING_INVALID"
    assert result.parent_fact is None
