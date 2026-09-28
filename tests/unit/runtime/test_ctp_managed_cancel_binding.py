from __future__ import annotations

from decimal import Decimal

import pytest

from backtrader_runtime.ctp_managed_cancel_binding import (
    CtpManagedCancelTargetV1,
    bind_ctp_managed_cancel_handoff,
)
from backtrader_runtime.ctp_managed_handoff import (
    CtpManagedCancelHandoff,
    CtpManagedHandoffError,
    freeze_ctp_request_fields,
)


SCOPE_KEY = "scope:" + "a" * 64
ACCOUNT_KEY = "account:" + "b" * 64
ORDER_REF = "000000000123"
ORDER_SYS_ID = "sys-order-123"


def _cancel_fields(**overrides):
    fields = {
        "ActionFlag": "0",
        "BrokerID": "9999",
        "ExchangeID": "SHFE",
        "FrontID": 8,
        "LimitPrice": Decimal("0"),
        "OrderRef": ORDER_REF,
        "OrderSysID": ORDER_SYS_ID,
        "SessionID": 13,
        "VolumeChange": 0,
    }
    fields.update(overrides)
    return freeze_ctp_request_fields(fields)


def _cancel(**overrides):
    values = {
        "scope_key": SCOPE_KEY,
        "account_key": ACCOUNT_KEY,
        "trading_day": "20260925",
        "managed_intent_id": "intent.41",
        "runtime_order_id": "bt-managed-v1:" + "c" * 64,
        "ctp_order_ref": ORDER_REF,
        "runtime_action_id": "cancel.action.41",
        "managed_cancel_intent_id": "cancel.action.41",
        "target_order_ref": ORDER_REF,
        "target_order_sys_id": ORDER_SYS_ID,
        "target_front_id": 8,
        "target_session_id": 13,
        "request_fields": _cancel_fields(),
    }
    values.update(overrides)
    return CtpManagedCancelHandoff(**values)


def _target(**overrides):
    values = {
        "order_ref": ORDER_REF,
        "exchange_id": "SHFE",
        "order_sys_id": ORDER_SYS_ID,
        "front_id": 8,
        "session_id": 13,
    }
    values.update(overrides)
    return CtpManagedCancelTargetV1(**values)


def test_cancel_binding_requires_and_preserves_complete_target_and_action_identity():
    handoff = _cancel()

    binding = bind_ctp_managed_cancel_handoff(handoff, target=_target())

    assert binding.version == 1
    assert binding.managed_action_id == "cancel.action.41"
    assert binding.target == _target()
    assert binding.handoff_request_digest == handoff.request_digest
    assert len(binding.binding_digest) == 64
    assert binding.binding_digest == bind_ctp_managed_cancel_handoff(
        _cancel(), target=_target()
    ).binding_digest


def test_cancel_binding_rejects_missing_exchange_id_even_if_v1_handoff_constructs():
    handoff = _cancel(request_fields=_cancel_fields(ExchangeID=None))

    with pytest.raises(CtpManagedHandoffError, match="exchangeid_mismatch"):
        bind_ctp_managed_cancel_handoff(handoff, target=_target())


@pytest.mark.parametrize(
    "target_changes, message",
    [
        ({"exchange_id": "DCE"}, "exchangeid_mismatch"),
        ({"order_ref": "000000000999"}, "target_mismatch"),
        ({"order_sys_id": "another-order"}, "target_mismatch"),
        ({"front_id": 9}, "target_mismatch"),
        ({"session_id": 14}, "target_mismatch"),
    ],
)
def test_cancel_binding_rejects_any_target_tuple_change(target_changes, message):
    with pytest.raises(CtpManagedHandoffError, match=message):
        bind_ctp_managed_cancel_handoff(_cancel(), target=_target(**target_changes))


def test_cancel_binding_rejects_request_echo_mismatch_for_exchange_id():
    handoff = _cancel(request_fields=_cancel_fields(ExchangeID="DCE"))

    with pytest.raises(CtpManagedHandoffError, match="exchangeid_mismatch"):
        bind_ctp_managed_cancel_handoff(handoff, target=_target())
