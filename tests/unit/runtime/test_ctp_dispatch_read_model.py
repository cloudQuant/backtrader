from __future__ import annotations

from types import SimpleNamespace

import pytest

from backtrader_runtime.ctp_managed_cancel_binding import (
    CtpManagedCancelActionBindingV1,
    CtpManagedCancelTargetV1,
)
from backtrader_runtime.ctp_dispatch_read_model import (
    CtpDispatchReadExpectation,
    CtpDispatchReadModelError,
    read_ctp_managed_dispatch_model,
    reduce_ctp_managed_dispatch_projection,
)


COMMAND_ID = "submit.command.41"
INTENT_ID = "intent.41"
RUNTIME_ORDER_ID = "bt-managed-v1:" + "a" * 64
ORDER_REF = "000000000123"
ORDER_SYS_ID = "sys-order-123"


def _order_state(provider_state=None, *, terminal=None, source_kind=None, updated_at_ns=None):
    return SimpleNamespace(
        provider_state=provider_state,
        terminal=terminal,
        source_kind=source_kind,
        updated_at_ns=updated_at_ns,
    )


def _submit_projection(
    *,
    command_id=COMMAND_ID,
    command_status="COMPLETED",
    local_dispatch_outcome="QUEUED",
    order_state=None,
    unknown_resolution=None,
):
    return SimpleNamespace(
        command_id=command_id,
        operation="SUBMIT",
        command_status=command_status,
        local_dispatch_outcome=local_dispatch_outcome,
        submit_action=SimpleNamespace(
            managed_intent_id=INTENT_ID,
            runtime_order_id=RUNTIME_ORDER_ID,
            order_ref=ORDER_REF,
            order_state=order_state or _order_state(),
        ),
        cancel_action=None,
        unknown_resolution=unknown_resolution,
    )


def _cancel_target(**overrides):
    fields = {
        "order_ref": ORDER_REF,
        "exchange_id": "SHFE",
        "order_sys_id": ORDER_SYS_ID,
        "front_id": 8,
        "session_id": 13,
    }
    fields.update(overrides)
    return CtpManagedCancelTargetV1(**fields)


def _cancel_binding(**target_changes):
    return CtpManagedCancelActionBindingV1(
        handoff_request_digest="b" * 64,
        managed_action_id="cancel.action.41",
        target=_cancel_target(**target_changes),
    )


def _cancel_projection(
    *,
    command_status="COMPLETED",
    local_dispatch_outcome="QUEUED",
    action_state=None,
    action_terminal=None,
    action_source=None,
    action_updated_at=None,
    target_order_state=None,
    unknown_resolution=None,
):
    return SimpleNamespace(
        command_id="cancel.command.41",
        operation="CANCEL",
        command_status=command_status,
        local_dispatch_outcome=local_dispatch_outcome,
        submit_action=None,
        cancel_action=SimpleNamespace(
            managed_action_id="cancel.action.41",
            action_state=action_state,
            terminal=action_terminal,
            source_kind=action_source,
            updated_at_ns=action_updated_at,
            target_order=SimpleNamespace(
                managed_intent_id=INTENT_ID,
                runtime_order_id=RUNTIME_ORDER_ID,
                order_ref=ORDER_REF,
                exchange_id="SHFE",
                order_sys_id=ORDER_SYS_ID,
                front_id=8,
                session_id=13,
                order_state=target_order_state or _order_state(),
            ),
        ),
        unknown_resolution=unknown_resolution,
    )


def _submit_expected(**overrides):
    values = {
        "command_id": COMMAND_ID,
        "operation": "SUBMIT",
        "managed_intent_id": INTENT_ID,
        "runtime_order_id": RUNTIME_ORDER_ID,
        "order_ref": ORDER_REF,
    }
    values.update(overrides)
    return CtpDispatchReadExpectation(**values)


def _cancel_expected(**target_changes):
    return CtpDispatchReadExpectation(
        command_id="cancel.command.41",
        operation="CANCEL",
        managed_intent_id=INTENT_ID,
        runtime_order_id=RUNTIME_ORDER_ID,
        order_ref=ORDER_REF,
        cancel_binding=_cancel_binding(**target_changes),
    )


def test_local_queued_submit_does_not_create_provider_state_or_broker_ack():
    model = reduce_ctp_managed_dispatch_projection(_submit_projection(), _submit_expected())

    assert model.local_dispatch_outcome == "QUEUED"
    assert model.provider_order_state is None
    assert model.provider_order_source_kind is None
    assert model.cancel_action_state is None
    assert model.target_order_state is None
    assert model.action_requires_write_freeze is False
    assert not hasattr(model, "accepted")
    assert not hasattr(model, "broker_status")


def test_local_rejection_stays_separate_from_provider_order_rejection():
    projection = _submit_projection(
        command_status="COMPLETED",
        local_dispatch_outcome="REJECTED",
    )

    model = reduce_ctp_managed_dispatch_projection(projection, _submit_expected())

    assert model.local_dispatch_outcome == "REJECTED"
    assert model.provider_order_state is None
    assert model.action_requires_write_freeze is False


def test_unresolved_unknown_stays_frozen_even_if_a_callback_projection_exists():
    projection = _submit_projection(
        command_status="UNKNOWN",
        local_dispatch_outcome="UNKNOWN",
        order_state=_order_state(
            "ACKNOWLEDGED",
            terminal=False,
            source_kind="CALLBACK",
            updated_at_ns=10,
        ),
    )

    model = reduce_ctp_managed_dispatch_projection(projection, _submit_expected())

    assert model.command_status == "UNKNOWN"
    assert model.local_dispatch_outcome == "UNKNOWN"
    assert model.provider_order_state == "ACKNOWLEDGED"
    assert model.action_requires_write_freeze is True


def test_verified_unknown_resolution_preserves_unknown_receipt_but_resolves_action():
    resolution = SimpleNamespace(
        order_terminal_state="REJECTED",
        cancel_action_terminal_state=None,
        verified_at_ns=9,
        resolved_at_ns=10,
    )
    projection = _submit_projection(
        command_status="UNKNOWN",
        local_dispatch_outcome="UNKNOWN",
        order_state=_order_state(
            "REJECTED",
            terminal=True,
            source_kind="RECONCILIATION",
            updated_at_ns=11,
        ),
        unknown_resolution=resolution,
    )

    model = reduce_ctp_managed_dispatch_projection(projection, _submit_expected())

    assert model.local_dispatch_outcome == "UNKNOWN"
    assert model.provider_order_state == "REJECTED"
    assert model.unknown_resolution_order_state == "REJECTED"
    assert model.action_requires_write_freeze is False


def test_cancel_action_terminal_does_not_make_target_order_terminal():
    projection = _cancel_projection(
        action_state="TERMINAL",
        action_terminal=True,
        action_source="CALLBACK",
        action_updated_at=12,
        target_order_state=_order_state(
            "ACKNOWLEDGED",
            terminal=False,
            source_kind="CALLBACK",
            updated_at_ns=13,
        ),
    )

    model = reduce_ctp_managed_dispatch_projection(projection, _cancel_expected())

    assert model.provider_order_state is None
    assert model.cancel_action_state == "TERMINAL"
    assert model.target_order_state == "ACKNOWLEDGED"
    assert model.cancel_target == _cancel_target()


def test_cancel_unknown_freeze_keeps_action_and_target_order_facts_separate():
    projection = _cancel_projection(
        command_status="UNKNOWN",
        local_dispatch_outcome="UNKNOWN",
        action_state="ACKNOWLEDGED",
        action_terminal=False,
        action_source="CALLBACK",
        action_updated_at=14,
        target_order_state=_order_state(
            "PARTIALLY_FILLED",
            terminal=False,
            source_kind="CALLBACK",
            updated_at_ns=15,
        ),
    )

    model = reduce_ctp_managed_dispatch_projection(projection, _cancel_expected())

    assert model.local_dispatch_outcome == "UNKNOWN"
    assert model.cancel_action_state == "ACKNOWLEDGED"
    assert model.target_order_state == "PARTIALLY_FILLED"
    assert model.action_requires_write_freeze is True


@pytest.mark.parametrize(
    "projection,expected",
    [
        (_submit_projection(command_id="other.command"), _submit_expected()),
        (_submit_projection(), _submit_expected(runtime_order_id="bt-managed-v1:" + "c" * 64)),
        (_submit_projection(), _submit_expected(order_ref="000000000999")),
        (
            _submit_projection(command_status="COMPLETED", local_dispatch_outcome="UNKNOWN"),
            _submit_expected(),
        ),
    ],
)
def test_reducer_rejects_wrong_command_identity_or_local_state(projection, expected):
    with pytest.raises(CtpDispatchReadModelError):
        reduce_ctp_managed_dispatch_projection(projection, expected)


def test_reducer_rejects_cancel_action_or_any_target_tuple_mismatch():
    projection = _cancel_projection()
    projection.cancel_action.managed_action_id = "another.cancel.action"

    with pytest.raises(CtpDispatchReadModelError, match="action identity"):
        reduce_ctp_managed_dispatch_projection(projection, _cancel_expected())

    projection = _cancel_projection()
    projection.cancel_action.target_order.exchange_id = "DCE"
    with pytest.raises(CtpDispatchReadModelError, match="target identity"):
        reduce_ctp_managed_dispatch_projection(projection, _cancel_expected())


def test_main_thread_reader_passes_the_exact_sealed_scope_and_command_unchanged():
    scope = object()

    class Reader:
        def __init__(self):
            self.calls = []

        def read_ctp_dispatch_projection(self, received_scope, command_id):
            self.calls.append((received_scope, command_id))
            return _submit_projection()

    reader = Reader()
    model = read_ctp_managed_dispatch_model(reader, scope, _submit_expected())

    assert reader.calls == [(scope, COMMAND_ID)]
    assert reader.calls[0][0] is scope
    assert model.local_dispatch_outcome == "QUEUED"


def test_missing_exact_command_projection_returns_no_state_instead_of_acceptance():
    class Reader:
        def read_ctp_dispatch_projection(self, scope, command_id):
            return None

    assert read_ctp_managed_dispatch_model(Reader(), object(), _submit_expected()) is None
