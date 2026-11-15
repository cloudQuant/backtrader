"""Replay, dedupe keys and restart projection (65.07).

The same Execution facts twice (in one instance or after a snapshot/restore)
produce no second notification and no second position delta; a later fact
advances exactly once; a regressed or foreign identity is refused.
"""

import json

import pytest

from backtrader.brokers._execution_parent_projection import (
    STATE_SCHEMA,
    ExecutionParentProjectionError,
    apply_position_delta,
)
from backtrader.order import Order

from ._support import SHA_A, Ports, fill, make_order, projection, status


def _make(*, state="ACCEPTED", fills=(), sha=SHA_A):
    _order, binding = make_order()
    ports = Ports(
        {"req-1": binding},
        statuses={"req-1": status(state, sha=sha)},
        fills={"req-1": tuple(fills)},
    )
    return ports, binding


def test_same_facts_twice_do_not_duplicate():
    ports, _binding = _make(fills=(fill("f1", quantity="1"),))
    proj = projection(ports)
    first = proj.project("req-1")
    assert len(first.notifications) == 2
    assert len(first.position_deltas) == 1
    second = proj.project("req-1")
    assert second.notifications == ()
    assert second.position_deltas == ()
    assert second.suppressed_notifications == 2
    assert second.suppressed_fills == 1
    status_view = proj.projection_status()
    assert status_view.notifications_issued == 2
    assert status_view.notifications_suppressed == 2
    assert status_view.position_deltas_applied == 1
    assert status_view.fills_suppressed == 1


def test_notification_keys_are_deterministic_across_instances():
    ports, _binding = _make(fills=(fill("f1", quantity="1"),))
    first = projection(ports).project("req-1")
    second = projection(ports).project("req-1")
    assert [item.dedupe_key for item in first.notifications] == [
        item.dedupe_key for item in second.notifications
    ]
    assert [delta.delta_key for delta in first.position_deltas] == [
        delta.delta_key for delta in second.position_deltas
    ]


def test_snapshot_is_detached_json_safe_and_deterministic():
    ports, _binding = _make(fills=(fill("f1", quantity="1"),))
    proj = projection(ports)
    proj.project("req-1")
    first = proj.snapshot()
    second = proj.snapshot()
    assert first == second
    assert first["schema"] == STATE_SCHEMA
    encoded = json.dumps(first, sort_keys=True)
    assert json.loads(encoded) == first
    # Mutating the copy cannot change the projection state.
    first["requests"]["req-1"]["fills"].clear()
    assert proj.snapshot()["requests"]["req-1"]["fills"]


def test_restart_with_the_same_facts_emits_nothing():
    ports, binding = _make(fills=(fill("f1", quantity="1"),))
    proj = projection(ports)
    proj.project("req-1")
    snapshot = proj.snapshot()
    restarted = projection(ports, restore=snapshot)
    assert restarted.projection_status().restored is True
    result = restarted.project("req-1")
    assert result.notifications == ()
    assert result.position_deltas == ()
    assert result.parent_fact.filled == "1"
    assert result.parent_fact.bt_status == Order.Accepted


def test_restart_advances_a_later_fact_exactly_once():
    ports, _binding = _make(fills=(fill("f1", quantity="1"),))
    proj = projection(ports)
    proj.project("req-1")
    snapshot = proj.snapshot()
    ports.fill_facts["req-1"] = (fill("f1", quantity="1"), fill("f2", quantity="1"))
    restarted = projection(ports, restore=snapshot)
    first = restarted.project("req-1")
    assert [delta.fill_id for delta in first.position_deltas] == ["f2"]
    assert first.parent_fact.filled == "2"
    second = restarted.project("req-1")
    assert second.position_deltas == ()
    assert second.suppressed_fills == 2
    position = 0.0
    for delta in first.position_deltas:
        position += float(delta.quantity)
    assert position == 1.0


def test_restart_after_unknown_resolves_once():
    ports, _binding = _make(state="UNKNOWN")
    proj = projection(ports)
    first = proj.project("req-1")
    assert first.parent_fact.unknown is True
    snapshot = proj.snapshot()
    ports.statuses["req-1"] = status("ACCEPTED")
    restarted = projection(ports, restore=snapshot)
    resolved = restarted.project("req-1")
    assert [item.kind for item in resolved.notifications] == ["accepted"]
    assert resolved.parent_fact.bt_status == Order.Accepted
    assert restarted.project("req-1").notifications == ()


def test_restart_refuses_a_changed_binding():
    ports, _binding = _make()
    proj = projection(ports)
    proj.project("req-1")
    snapshot = proj.snapshot()
    _order, changed = make_order(size=4)
    ports.bindings["req-1"] = changed
    result = projection(ports, restore=snapshot).project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_BINDING_CONFLICT"


def test_restart_refuses_a_regressed_parent_state():
    ports, _binding = _make()
    proj = projection(ports)
    proj.project("req-1")
    snapshot = proj.snapshot()
    ports.statuses["req-1"] = status("REGISTERING")
    result = projection(ports, restore=snapshot).project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_STATE_REGRESSED"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda state: state.update({"schema": "other/v1"}),
        lambda state: state["requests"]["req-1"].update({"unexpected": 1}),
        lambda state: state["requests"]["req-1"]["issued"].append("plain-key"),
        lambda state: state["requests"]["req-1"].update({"parent_state": "SETTLING"}),
        lambda state: state["requests"]["req-1"].update({"fills": {"f1": "not-a-digest"}}),
        lambda state: state["requests"]["req-1"].update({"fill_total": "9"}),
        lambda state: state["requests"]["req-1"].update({"fills_known": False}),
    ],
)
def test_restore_rejects_a_malformed_state(mutate):
    ports, _binding = _make(fills=(fill("f1", quantity="1"),))
    proj = projection(ports)
    proj.project("req-1")
    snapshot = proj.snapshot()
    mutate(snapshot)
    with pytest.raises(ExecutionParentProjectionError) as error:
        projection(ports, restore=snapshot)
    assert error.value.code == "RESTORE_INVALID"


def test_refusal_does_not_prevent_later_progress():
    ports, _binding = _make(fills=(fill("f1", quantity="1"),))
    proj = projection(ports)
    proj.project("req-1")
    foreign = status("ACCEPTED", request_id="req-2")
    ports.statuses["req-1"] = foreign
    refused = proj.project("req-1")
    assert refused.refused is True
    assert refused.code == "EXECUTION_IDENTITY_FOREIGN"
    assert refused.parent_fact.bt_status == Order.Accepted
    ports.statuses["req-1"] = status("ACCEPTED")
    ports.fill_facts["req-1"] = (fill("f1", quantity="1"), fill("f2", quantity="1"))
    progressed = proj.project("req-1")
    assert progressed.refused is False
    assert [delta.fill_id for delta in progressed.position_deltas] == ["f2"]


def test_position_delta_requires_a_real_position():
    ports, _binding = _make(fills=(fill("f1", quantity="1"),))
    result = projection(ports).project("req-1")
    (delta,) = result.position_deltas
    import backtrader as bt

    position = bt.Position()
    apply_position_delta(position, delta)
    assert position.size == 1
