"""Foreign, regressed and conflicting facts are refused (65.07).

A refused projection changes no fact, emits no notification and applies no
position delta; every refusal code is finite and published in ``CODES``.
"""

import pytest

from backtrader.brokers._execution_parent_projection import (
    CODES,
    ExecutionParentProjection,
    ExecutionParentProjectionError,
)
from backtrader.order import Order

from ._support import (
    SHA_A,
    SHA_B,
    Ports,
    cancel,
    child,
    completion,
    fill,
    make_order,
    projection,
    status,
)


def _single(**kwargs):
    _order, binding = make_order()
    ports = Ports({"req-1": binding}, statuses={"req-1": status("ACCEPTED")}, **kwargs)
    return projection(ports), ports


def test_foreign_status_request_id_is_refused():
    proj, ports = _single()
    proj.project("req-1")
    ports.statuses["req-1"] = status("ACCEPTED", request_id="req-2")
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_IDENTITY_FOREIGN"
    assert result.parent_fact.bt_status == Order.Accepted
    assert proj.projection_status().refused == 1


def test_changed_parent_ref_is_refused():
    proj, ports = _single()
    proj.project("req-1")
    ports.statuses["req-1"] = status("ACCEPTED", parent_ref="par-2")
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_IDENTITY_REGRESSED"


def test_changed_request_digest_is_refused():
    proj, ports = _single()
    proj.project("req-1")
    ports.statuses["req-1"] = status("ACCEPTED", sha=SHA_B)
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_IDENTITY_CONFLICT"
    assert proj.projection_status().conflicts == 1


def test_changed_binding_is_refused():
    proj, ports = _single()
    proj.project("req-1")
    _order, changed = make_order(size=5)
    ports.bindings["req-1"] = changed
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_BINDING_CONFLICT"
    assert proj.projection_status().conflicts == 1


def test_missing_binding_is_refused():
    ports = Ports({}, statuses={"req-1": status("ACCEPTED")})
    result = projection(ports).project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_BINDING_ABSENT"
    assert result.parent_fact is None


def test_binding_for_another_request_is_refused():
    _order, binding = make_order(request_id="req-2")
    ports = Ports({"req-1": binding}, statuses={"req-1": status("ACCEPTED")})
    result = projection(ports).project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_IDENTITY_FOREIGN"


def test_binding_with_an_unknown_key_is_refused():
    _order, binding = make_order()
    binding["unexpected"] = 1
    ports = Ports({"req-1": binding}, statuses={"req-1": status("ACCEPTED")})
    result = projection(ports).project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_BINDING_INVALID"


def test_a_child_identity_cannot_move_to_another_request():
    first_order, first_binding = make_order(request_id="req-1")
    _second_order, second_binding = make_order(request_id="req-2")
    ports = Ports(
        {"req-1": first_binding, "req-2": second_binding},
        statuses={
            "req-1": status("ACCEPTED", request_id="req-1", children=(child("c1", "SENT"),)),
            "req-2": status("ACCEPTED", request_id="req-2", children=(child("c1", "SENT"),)),
        },
    )
    proj = projection(ports)
    assert proj.project("req-1").refused is False
    result = proj.project("req-2")
    assert result.refused is True
    assert result.code == "EXECUTION_CHILD_IDENTITY_FOREIGN"


def test_child_state_regression_is_refused():
    proj, ports = _single()
    ports.statuses["req-1"] = status("ACCEPTED", children=(child("c1", "SENT"),))
    proj.project("req-1")
    ports.statuses["req-1"] = status("ACCEPTED", children=(child("c1", "RESERVED"),))
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_CHILD_STATE_REGRESSED"


def test_a_vanished_child_is_refused():
    proj, ports = _single()
    ports.statuses["req-1"] = status("ACCEPTED", children=(child("c1", "SENT"),))
    proj.project("req-1")
    ports.statuses["req-1"] = status("ACCEPTED")
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_CHILD_MISSING"


def test_a_rejected_parent_cannot_have_children():
    proj, ports = _single()
    ports.statuses["req-1"] = status("REJECTED", children=(child("c1", "SENT"),))
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_REJECTED_WITH_CHILDREN"


def test_a_changed_cancel_identity_is_refused():
    proj, ports = _single()
    ports.cancels["req-1"] = cancel("cancel-1", "UNKNOWN")
    proj.project("req-1")
    ports.cancels["req-1"] = cancel("cancel-2", "CANCELED")
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "CANCEL_FACT_CONFLICT"


def test_a_changed_completion_identity_is_refused():
    proj, ports = _single()
    ports.cancels.pop("req-1", None)
    ports.completions["req-1"] = completion("complete-1")
    assert proj.project("req-1").refused is False
    ports.completions["req-1"] = completion("complete-2")
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "COMPLETION_FACT_CONFLICT"


def test_a_completion_after_a_cancel_is_a_terminal_conflict():
    proj, ports = _single()
    ports.cancels["req-1"] = cancel(outcome="CANCELED")
    first = proj.project("req-1")
    assert first.parent_fact.bt_status == Order.Canceled
    ports.completions["req-1"] = completion()
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_TERMINAL_CONFLICT"
    assert result.parent_fact.bt_status == Order.Canceled


def test_a_canceled_fact_conflicts_with_a_rejected_state():
    proj, ports = _single(cancels={"req-1": cancel(outcome="CANCELED")})
    ports.statuses["req-1"] = status("REJECTED")
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_TERMINAL_CONFLICT"


def test_a_completion_fact_conflicts_with_a_rejected_state():
    proj, ports = _single(completions={"req-1": completion()})
    ports.statuses["req-1"] = status("REJECTED")
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "EXECUTION_TERMINAL_CONFLICT"


def test_a_fill_for_another_parent_is_refused():
    proj, _ports = _single(fills={"req-1": (fill("f1", quantity="1", parent_ref="par-9"),)})
    result = proj.project("req-1")
    assert result.refused is True
    assert result.code == "FILL_FACT_FOREIGN"
    assert result.position_deltas == ()


def test_a_fill_identity_cannot_move_to_another_request():
    _order, first_binding = make_order(request_id="req-1")
    _order, second_binding = make_order(request_id="req-2")
    ports = Ports(
        {"req-1": first_binding, "req-2": second_binding},
        statuses={
            "req-1": status("ACCEPTED", request_id="req-1"),
            "req-2": status("ACCEPTED", request_id="req-2"),
        },
        fills={
            "req-1": (fill("f1", quantity="1"),),
            "req-2": (fill("f1", quantity="1"),),
        },
    )
    proj = projection(ports)
    assert proj.project("req-1").refused is False
    result = proj.project("req-2")
    assert result.refused is True
    assert result.code == "FILL_FACT_FOREIGN"


def test_a_refusal_is_side_effect_free():
    proj, ports = _single(fills={"req-1": (fill("f1", quantity="1"),)})
    first = proj.project("req-1")
    assert first.position_deltas
    before = proj.projection_status()
    ports.statuses["req-1"] = status("ACCEPTED", children=(child("c1", "SENT", quantity="3"),))
    proj.project("req-1")
    ports.statuses["req-1"] = status("ACCEPTED")
    ports.fill_facts["req-1"] = (fill("f1", quantity="1"), fill("f2", quantity="1"))
    refused = proj.project("req-1")
    assert refused.refused is True
    assert refused.code == "EXECUTION_CHILD_MISSING"
    assert refused.position_deltas == ()
    assert refused.notifications == ()
    after = proj.projection_status()
    assert after.position_deltas_applied == before.position_deltas_applied
    assert after.notifications_issued == before.notifications_issued
    assert after.refused == before.refused + 1
    ports.statuses["req-1"] = status("ACCEPTED", children=(child("c1", "SENT", quantity="3"),))
    recovered = proj.project("req-1")
    assert recovered.refused is False
    assert [delta.fill_id for delta in recovered.position_deltas] == ["f2"]


@pytest.mark.parametrize(
    "code",
    [
        "EXECUTION_IDENTITY_FOREIGN",
        "EXECUTION_IDENTITY_REGRESSED",
        "EXECUTION_IDENTITY_CONFLICT",
        "EXECUTION_BINDING_CONFLICT",
        "EXECUTION_CHILD_IDENTITY_FOREIGN",
        "EXECUTION_CHILD_STATE_REGRESSED",
        "EXECUTION_CHILD_MISSING",
        "EXECUTION_REJECTED_WITH_CHILDREN",
        "CANCEL_FACT_CONFLICT",
        "COMPLETION_FACT_CONFLICT",
        "EXECUTION_TERMINAL_CONFLICT",
        "FILL_FACT_FOREIGN",
    ],
)
def test_every_refusal_code_is_finite(code):
    assert code in CODES


def test_invalid_request_id_raises_a_finite_error():
    proj, _ports = _single()
    with pytest.raises(ExecutionParentProjectionError) as error:
        proj.project("")
    assert error.value.code == "INVALID_REQUEST_ID"


def test_invalid_port_object_raises():
    with pytest.raises(ExecutionParentProjectionError) as error:
        ExecutionParentProjection(binding_port=object(), status_port=object())
    assert error.value.code == "PORT_INVALID"


def test_a_malformed_status_is_unknown_not_a_refusal():
    proj, ports = _single()
    ports.statuses["req-1"] = {"request_id": "req-1", "state": "ACCEPTED"}
    result = proj.project("req-1")
    assert result.refused is False
    assert result.parent_fact.reason_code == "EXECUTION_STATUS_UNREADABLE"
    assert result.parent_fact.unknown is True


def test_an_invalid_child_quantity_is_unknown_not_a_refusal():
    proj, ports = _single()
    ports.statuses["req-1"] = status(
        "ACCEPTED", children=(child("c1", "SENT", quantity="not-a-number"),)
    )
    result = proj.project("req-1")
    assert result.refused is False
    assert result.parent_fact.reason_code == "EXECUTION_CHILD_QUANTITY_INVALID"
    assert result.parent_fact.unknown is True


def test_the_sha_constant_matches_the_committed_shape():
    assert len(SHA_A) == 64 and SHA_A != SHA_B
