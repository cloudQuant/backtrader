from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from backtrader_runtime.ctp_managed_handoff import (
    CtpManagedCancelHandoff,
    CtpManagedHandoffError,
    CtpManagedLocalQueuedReceipt,
    CtpManagedNativeSubmissionReceipt,
    CtpManagedSubmitHandoff,
    freeze_ctp_request_fields,
    require_local_queued_receipt,
    require_native_submission_receipt,
)


SCOPE_KEY = "scope:" + "a" * 64
ACCOUNT_KEY = "account:" + "b" * 64
TRADING_DAY = "20260925"
INTENT_ID = "intent.41"
RUNTIME_ORDER_ID = "bt-managed-v1:" + "c" * 64
ORDER_REF = "000000000123"
ORDER_SYS_ID = "sys-order-123"


def _submit_fields(**overrides):
    fields = {
        "BrokerID": "9999",
        "Direction": "0",
        "ExchangeID": "SHFE",
        "InstrumentID": "rb2701",
        "LimitPrice": Decimal("3500.25"),
        "OrderRef": ORDER_REF,
        "VolumeTotalOriginal": 1,
    }
    fields.update(overrides)
    return freeze_ctp_request_fields(fields)


def _submit(**overrides):
    values = {
        "scope_key": SCOPE_KEY,
        "account_key": ACCOUNT_KEY,
        "trading_day": TRADING_DAY,
        "managed_intent_id": INTENT_ID,
        "runtime_order_id": RUNTIME_ORDER_ID,
        "ctp_order_ref": ORDER_REF,
        "request_fields": _submit_fields(),
    }
    values.update(overrides)
    return CtpManagedSubmitHandoff(**values)


def _cancel_fields(**overrides):
    fields = {
        "ActionFlag": "0",
        "BrokerID": "9999",
        "FrontID": 8,
        "OrderRef": ORDER_REF,
        "OrderSysID": ORDER_SYS_ID,
        "SessionID": 13,
    }
    fields.update(overrides)
    return freeze_ctp_request_fields(fields)


def _cancel(**overrides):
    values = {
        "scope_key": SCOPE_KEY,
        "account_key": ACCOUNT_KEY,
        "trading_day": TRADING_DAY,
        "managed_intent_id": INTENT_ID,
        "runtime_order_id": RUNTIME_ORDER_ID,
        "ctp_order_ref": ORDER_REF,
        "runtime_action_id": "cancel.intent.41",
        "managed_cancel_intent_id": "cancel.intent.41",
        "target_order_ref": ORDER_REF,
        "target_order_sys_id": ORDER_SYS_ID,
        "target_front_id": 8,
        "target_session_id": 13,
        "request_fields": _cancel_fields(),
    }
    values.update(overrides)
    return CtpManagedCancelHandoff(**values)


def test_submit_handoff_binds_scope_account_day_order_identity_and_full_request():
    handoff = _submit()

    assert handoff.operation == "SUBMIT"
    assert handoff.version == 1
    assert handoff.request_fields == _submit_fields()
    assert len(handoff.request_digest) == 64
    assert handoff.request_digest == _submit().request_digest
    assert (
        handoff.request_digest
        != _submit(request_fields=_submit_fields(LimitPrice=Decimal("3500.50"))).request_digest
    )
    assert handoff.request_digest != _submit(account_key="account:" + "d" * 64).request_digest
    assert handoff.request_digest != _submit(trading_day="20260926").request_digest


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"scope_key": "scope:bad"}, "execution_scope_key"),
        ({"account_key": "account:bad"}, "execution_account_key"),
        ({"trading_day": "20260230"}, "trading_day"),
        ({"managed_intent_id": " bad"}, "managed_intent_id"),
        ({"managed_intent_id": "x" * 129}, "managed_intent_id"),
        ({"runtime_order_id": "order-123"}, "runtime_order_id"),
        ({"ctp_order_ref": "123"}, "ctp_order_ref"),
        ({"version": True}, "version"),
        ({"request_fields": (("OrderRef", "000000000124"),)}, "order_ref_mismatch"),
        (
            {"request_fields": (("VolumeTotalOriginal", 1), ("OrderRef", ORDER_REF))},
            "not_canonical",
        ),
    ],
)
def test_submit_handoff_rejects_malformed_or_mismatched_identity(changes, message):
    with pytest.raises(CtpManagedHandoffError, match=message):
        _submit(**changes)


def test_request_fields_freeze_only_plain_canonical_scalar_values():
    mutable = {"OrderRef": ORDER_REF, "LimitPrice": Decimal("3500.25")}
    frozen = freeze_ctp_request_fields(mutable)
    mutable["OrderRef"] = "000000000999"

    assert dict(frozen)["OrderRef"] == ORDER_REF
    with pytest.raises(CtpManagedHandoffError, match="nonempty_dict"):
        freeze_ctp_request_fields({})
    with pytest.raises(CtpManagedHandoffError, match="field_name"):
        freeze_ctp_request_fields({1: "not a field"})
    with pytest.raises(CtpManagedHandoffError, match="unsupported_ctp_request_value"):
        freeze_ctp_request_fields({"OrderRef": ORDER_REF, "Extra": ["mutable"]})


def test_cancel_handoff_binds_action_and_exact_native_target_tuple():
    handoff = _cancel()

    assert handoff.operation == "CANCEL"
    assert handoff.runtime_action_id == handoff.managed_cancel_intent_id
    assert handoff.target_order_ref == handoff.ctp_order_ref
    assert handoff.request_digest == _cancel().request_digest
    assert (
        handoff.request_digest
        != _cancel(
            target_session_id=14,
            request_fields=_cancel_fields(SessionID=14),
        ).request_digest
    )
    assert (
        handoff.request_digest
        != _cancel(request_fields=_cancel_fields(ActionFlag="1")).request_digest
    )


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"managed_cancel_intent_id": "cancel.intent.other"}, "runtime_action_id"),
        ({"managed_intent_id": "x" * 129}, "managed_intent_id"),
        ({"runtime_action_id": "x" * 129}, "runtime_action_id"),
        ({"managed_cancel_intent_id": "x" * 129}, "managed_cancel_intent_id"),
        ({"target_order_ref": "000000000124"}, "target_order_ref_mismatch"),
        ({"target_order_sys_id": ""}, "target_order_sys_id"),
        ({"target_front_id": True}, "target_front_id"),
        ({"target_session_id": 0}, "target_session_id"),
        ({"request_fields": _cancel_fields(OrderSysID="other-order")}, "ordersysid_mismatch"),
        ({"request_fields": _cancel_fields(FrontID="8")}, "frontid_mismatch"),
        ({"request_fields": _cancel_fields(SessionID=14)}, "sessionid_mismatch"),
    ],
)
def test_cancel_handoff_rejects_malformed_or_mismatched_target(changes, message):
    with pytest.raises(CtpManagedHandoffError, match=message):
        _cancel(**changes)


def test_local_queue_receipt_cannot_be_misread_as_native_submission_or_provider_ack():
    handoff = _submit()
    local = CtpManagedLocalQueuedReceipt(
        operation="SUBMIT",
        request_digest=handoff.request_digest,
        queue_receipt_id="1" * 32,
        queue_depth=0,
    )
    native = CtpManagedNativeSubmissionReceipt(
        operation="SUBMIT",
        request_digest=handoff.request_digest,
        echoed_handoff=handoff,
        native_request_id=41,
        submit_code=0,
    )

    assert require_local_queued_receipt(local, handoff) is local
    assert local.state == "LOCAL_QUEUED"
    assert local.provider_acknowledged is False
    with pytest.raises(CtpManagedHandoffError, match="native_submission_receipt_handoff_mismatch"):
        require_native_submission_receipt(local, handoff)

    assert require_native_submission_receipt(native, handoff) is native
    assert native.state == "NATIVE_SUBMITTED"
    assert native.provider_acknowledged is False
    with pytest.raises(CtpManagedHandoffError, match="local_queue_receipt_handoff_mismatch"):
        require_local_queued_receipt(native, handoff)


def test_receipt_requires_exact_operation_and_digest_match():
    handoff = _submit()
    wrong_digest = "f" * 64
    local = CtpManagedLocalQueuedReceipt("SUBMIT", wrong_digest, "2" * 32, 2)
    native = CtpManagedNativeSubmissionReceipt("CANCEL", _cancel().request_digest, _cancel(), 2, 0)

    with pytest.raises(CtpManagedHandoffError, match="local_queue_receipt_handoff_mismatch"):
        require_local_queued_receipt(local, handoff)
    with pytest.raises(CtpManagedHandoffError, match="native_submission_receipt_handoff_mismatch"):
        require_native_submission_receipt(native, handoff)
    with pytest.raises(CtpManagedHandoffError, match="native_submission_not_accepted"):
        CtpManagedNativeSubmissionReceipt("SUBMIT", handoff.request_digest, handoff, 3, -1)
    with pytest.raises(CtpManagedHandoffError, match="native_request_id"):
        CtpManagedNativeSubmissionReceipt("SUBMIT", handoff.request_digest, handoff, 0, 0)


def test_native_receipt_rejects_a_different_full_handoff_echo():
    handoff = _submit()
    altered_echo = _submit(account_key="account:" + "e" * 64)
    altered_receipt = CtpManagedNativeSubmissionReceipt(
        operation="SUBMIT",
        request_digest=altered_echo.request_digest,
        echoed_handoff=altered_echo,
        native_request_id=41,
        submit_code=0,
    )

    with pytest.raises(CtpManagedHandoffError, match="native_submission_receipt_handoff_mismatch"):
        require_native_submission_receipt(altered_receipt, handoff)

    with pytest.raises(CtpManagedHandoffError, match="native_submission_receipt_handoff_mismatch"):
        replace(altered_receipt, echoed_handoff=handoff)
