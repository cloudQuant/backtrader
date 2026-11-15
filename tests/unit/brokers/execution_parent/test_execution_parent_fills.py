"""Authoritative fills, position deltas and no fabricated fills (65.07).

Real BT ``Order``/``Position`` objects plus synthetic authoritative fill facts.
A plan, a reservation or a sent child never becomes a position delta.
"""

import pytest

import backtrader as bt
from backtrader.brokers._execution_parent_projection import (
    ExecutionParentProjectionError,
    PositionDelta,
    apply_position_delta,
)
from backtrader.order import Order

from ._support import (
    DAY,
    Ports,
    child,
    fill,
    make_order,
    projection,
    status,
)


def _project(*, side="buy", size=3, state="ACCEPTED", children=(), fills=None):
    _order, binding = make_order(side=side, size=size)
    ports = Ports(
        {"req-1": binding},
        statuses={"req-1": status(state, children=children)},
        fills={} if fills is None else {"req-1": tuple(fills)},
    )
    return projection(ports), ports


def test_partial_fill_advances_once_and_updates_a_real_position():
    proj, ports = _project(
        children=(child("c1", "SENT", quantity="3"),),
        fills=(fill("f1", child_id="c1", quantity="1", price="3499"),),
    )
    result = proj.project("req-1")
    fact = result.parent_fact
    assert fact.bt_status == Order.Accepted
    assert fact.terminal is False
    assert fact.filled == "1"
    assert fact.remaining == "2"
    (delta,) = result.position_deltas
    assert delta.quantity == "1"
    assert delta.price == "3499"
    assert delta.side == "buy"
    assert delta.child_id == "c1"
    assert delta.fill_id == "f1"
    assert delta.delta_key.startswith("epp:")
    position = bt.Position()
    assert apply_position_delta(position, delta) == (1.0, 3499.0, 1.0, 0)
    assert position.size == 1 and position.price == 3499.0
    # The same snapshot again is a duplicate, not a second fill.
    replay = proj.project("req-1")
    assert replay.position_deltas == ()
    assert replay.suppressed_fills == 1
    assert replay.parent_fact.filled == "1"
    assert position.size == 1


def test_three_child_fills_advance_one_at_a_time():
    children = (
        child("c1", "SENT", quantity="1"),
        child("c2", "SENT", quantity="1"),
        child("c3", "PLANNED", quantity="1"),
    )
    proj, ports = _project(
        children=children,
        fills=(
            fill("f1", child_id="c1", quantity="1", price="3500"),
            fill("f2", child_id="c2", quantity="1", price="3501"),
        ),
    )
    first = proj.project("req-1")
    assert [delta.fill_id for delta in first.position_deltas] == ["f1", "f2"]
    assert first.parent_fact.filled == "2"
    position = bt.Position()
    for delta in first.position_deltas:
        apply_position_delta(position, delta)
    assert position.size == 2 and position.price == pytest.approx(3500.5)
    ports.statuses["req-1"] = status("ACCEPTED", children=children)
    ports.fill_facts["req-1"] = (
        fill("f1", child_id="c1", quantity="1", price="3500"),
        fill("f2", child_id="c2", quantity="1", price="3501"),
        fill("f3", child_id="c3", quantity="1", price="3502"),
    )
    second = proj.project("req-1")
    assert [delta.fill_id for delta in second.position_deltas] == ["f3"]
    assert second.suppressed_fills == 2
    assert second.parent_fact.filled == "3"
    assert second.parent_fact.remaining == "0"
    (delta,) = second.position_deltas
    apply_position_delta(position, delta)
    assert position.size == 3 and position.price == pytest.approx(3501.0)
    c1, c2, c3 = second.parent_fact.children
    assert (c1.filled, c2.filled, c3.filled) == ("1", "1", "1")
    assert c3.state == "PLANNED"


def test_full_venue_fill_is_not_completed_without_the_completion_fact():
    proj, _ports = _project(
        children=(child("c1", "SENT", quantity="3"),),
        fills=(fill("f1", child_id="c1", quantity="3"),),
    )
    result = proj.project("req-1")
    assert result.parent_fact.filled == "3"
    assert result.parent_fact.remaining == "0"
    assert result.parent_fact.bt_status == Order.Accepted
    assert result.parent_fact.bt_status != Order.Completed
    assert result.parent_fact.terminal is False
    assert [item.kind for item in result.notifications] == ["submitted", "accepted"]


def test_plans_reservations_and_sent_children_never_create_deltas():
    proj, _ports = _project(
        children=(
            child("c1", "PLANNED", quantity="1"),
            child("c2", "RESERVING", quantity="1"),
            child("c3", "RESERVED", quantity="1"),
            child("c4", "DISPATCHING", quantity="1"),
            child("c5", "SENT", quantity="1"),
        )
    )
    result = proj.project("req-1")
    assert result.position_deltas == ()
    assert result.parent_fact.filled == "0"
    assert result.parent_fact.remaining == "3"


def test_sell_fill_is_a_negative_delta():
    proj, _ports = _project(
        side="sell",
        children=(child("c1", "SENT", quantity="2"),),
        fills=(fill("f1", child_id="c1", quantity="2", price="3600"),),
    )
    result = proj.project("req-1")
    (delta,) = result.position_deltas
    assert delta.side == "sell" and delta.quantity == "-2"
    position = bt.Position()
    apply_position_delta(position, delta)
    assert position.size == -2 and position.price == 3600.0


def test_fill_side_mismatch_is_refused():
    proj, _ports = _project(side="buy", fills=(fill("f1", quantity="1", side="sell"),))
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "FILL_SIDE_MISMATCH"
    assert result.position_deltas == ()
    assert result.notifications == ()


def test_fill_offset_mismatch_is_refused():
    proj, _ports = _project(fills=(fill("f1", quantity="1", offset="close"),))
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "FILL_OFFSET_MISMATCH"
    assert result.position_deltas == ()


def test_fill_source_other_than_venue_is_refused():
    proj, _ports = _project(fills=(fill("f1", quantity="1", source="INTERNAL_TRANSFER"),))
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "FILL_SOURCE_UNSUPPORTED"
    assert result.position_deltas == ()
    assert _ports.write_calls == []


def test_fill_exceeding_the_order_is_refused_without_partial_apply():
    proj, ports = _project(
        fills=(
            fill("f1", quantity="2", price="3500"),
            fill("f2", quantity="2", price="3500"),
        )
    )
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "FILL_QUANTITY_EXCEEDS_ORDER"
    assert result.position_deltas == ()
    assert proj.projection_status().position_deltas_applied == 0
    # Nothing was committed: the same request can still project the legal part.
    ports.fill_facts["req-1"] = (fill("f1", quantity="2", price="3500"),)
    legal = proj.project("req-1")
    assert legal.refused is False
    assert [delta.fill_id for delta in legal.position_deltas] == ["f1"]
    assert legal.parent_fact.filled == "2"


def test_fill_exceeding_its_child_quantity_is_refused():
    proj, _ports = _project(
        children=(child("c1", "SENT", quantity="1"),),
        fills=(fill("f1", child_id="c1", quantity="2"),),
    )
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "FILL_QUANTITY_EXCEEDS_CHILD"


def test_same_fill_id_with_different_content_is_refused():
    proj, ports = _project(fills=(fill("f1", quantity="1"),))
    proj.project("req-1")
    ports.fill_facts["req-1"] = (fill("f1", quantity="2"),)
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "FILL_FACT_CONFLICT"
    assert result.position_deltas == ()
    assert result.parent_fact.filled == "1"
    assert proj.projection_status().conflicts == 1


def test_duplicate_fill_in_one_snapshot_applies_once():
    proj, _ports = _project(fills=(fill("f1", quantity="1"), fill("f1", quantity="1")))
    result = proj.project("req-1")
    assert [delta.fill_id for delta in result.position_deltas] == ["f1"]
    assert result.suppressed_fills == 1
    assert result.parent_fact.filled == "1"


def test_late_fill_for_an_unlisted_child_is_applied_once():
    proj, ports = _project()
    first = proj.project("req-1")
    assert first.position_deltas == ()
    ports.fill_facts["req-1"] = (fill("f9", child_id="c9", quantity="1"),)
    second = proj.project("req-1")
    assert [delta.fill_id for delta in second.position_deltas] == ["f9"]
    assert second.parent_fact.filled == "1"
    assert second.parent_fact.children == ()
    third = proj.project("req-1")
    assert third.position_deltas == ()


def test_fill_metadata_is_preserved():
    proj, _ports = _project(
        fills=(
            fill(
                "f1",
                child_id="c1",
                quantity="1",
                price="3510.5",
                trading_day=DAY,
                exchange_trade_id="trade-7",
            ),
        )
    )
    result = proj.project("req-1")
    (delta,) = result.position_deltas
    assert delta.trading_day == DAY
    assert delta.exchange_trade_id == "trade-7"
    assert delta.price == "3510.5"
    assert delta.quantity == "1"


def test_fill_total_equal_to_the_order_is_allowed():
    proj, _ports = _project(fills=(fill("f1", quantity="3"),))
    result = proj.project("req-1")
    assert result.refused is False
    assert result.parent_fact.filled == "3"
    assert result.parent_fact.remaining == "0"


def test_apply_position_delta_requires_real_objects():
    proj, _ports = _project(fills=(fill("f1", quantity="1"),))
    result = proj.project("req-1")
    (delta,) = result.position_deltas
    assert isinstance(delta, PositionDelta)
    with pytest.raises(ExecutionParentProjectionError) as wrong_delta:
        apply_position_delta(bt.Position(), object())
    assert wrong_delta.value.code == "POSITION_DELTA_INVALID"
    with pytest.raises(ExecutionParentProjectionError) as wrong_position:
        apply_position_delta(object(), delta)
    assert wrong_position.value.code == "POSITION_DELTA_INVALID"
