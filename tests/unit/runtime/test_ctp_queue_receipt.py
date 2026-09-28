"""Pure tests for classifying asynchronous managed CTP Store receipts."""

from __future__ import annotations

from typing import Any

import pytest

from backtrader_runtime.managed_execution import (
    CtpQueueReceiptState,
    ManagedExecutionBindingError,
    classify_ctp_queue_receipt,
)


BT_ORDER_REF = 73
CLIENT_ORDER_ID = "000000000073"
RECEIPT_ID = "a" * 32


def _receipt(operation: str, *, queued: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": "command_receipt",
        "command": operation,
        "receipt_id": RECEIPT_ID,
        "bt_order_ref": BT_ORDER_REF,
        "client_order_id": CLIENT_ORDER_ID,
        "status": "submitted" if queued else "rejected",
        "queued": queued,
        "priority": "cancel" if operation == "cancel" else "open",
        "queue_depth": 1 if queued else 0,
    }
    if not queued:
        result["error_code"] = "command_queue_full"
        result["error_msg"] = "SDK command queue cannot safely accept this command"
    return result


@pytest.mark.parametrize("operation", ("submit", "cancel"))
def test_queued_submit_and_cancel_receipts_are_unknown_not_provider_ack(operation: str) -> None:
    classification = classify_ctp_queue_receipt(
        _receipt(operation, queued=True),
        operation=operation,
        expected_bt_order_ref=BT_ORDER_REF,
        expected_client_order_id=CLIENT_ORDER_ID,
    )

    assert classification.operation == operation
    assert classification.state is CtpQueueReceiptState.UNKNOWN
    assert classification.queued is True
    assert classification.receipt_id == RECEIPT_ID
    assert classification.error_code is None
    # The classification type intentionally has no provider order ID or
    # ProviderObservation field that could accidentally be projected as ACK.
    assert not hasattr(classification, "provider_order_id")
    assert not hasattr(classification, "provider_observation")


@pytest.mark.parametrize("operation", ("submit", "cancel"))
def test_rejected_receipts_are_local_rejections_only_after_identity_validation(
    operation: str,
) -> None:
    classification = classify_ctp_queue_receipt(
        _receipt(operation, queued=False),
        operation=operation,
        expected_bt_order_ref=BT_ORDER_REF,
        expected_client_order_id=CLIENT_ORDER_ID,
    )

    assert classification.operation == operation
    assert classification.state is CtpQueueReceiptState.REJECTED
    assert classification.queued is False
    assert classification.error_code == "command_queue_full"
    assert not hasattr(classification, "provider_order_id")


@pytest.mark.parametrize(
    ("mutate", "operation", "expected_ref", "expected_client_id"),
    (
        (lambda receipt: receipt.update(kind="order"), "submit", BT_ORDER_REF, CLIENT_ORDER_ID),
        (lambda receipt: receipt.update(command="cancel"), "submit", BT_ORDER_REF, CLIENT_ORDER_ID),
        (lambda receipt: receipt.update(bt_order_ref=74), "submit", BT_ORDER_REF, CLIENT_ORDER_ID),
        (
            lambda receipt: receipt.update(client_order_id="000000000074"),
            "submit",
            BT_ORDER_REF,
            CLIENT_ORDER_ID,
        ),
        (
            lambda receipt: receipt.update(receipt_id="invalid"),
            "submit",
            BT_ORDER_REF,
            CLIENT_ORDER_ID,
        ),
        (lambda receipt: receipt.update(queued=1), "submit", BT_ORDER_REF, CLIENT_ORDER_ID),
        (lambda receipt: receipt.pop("error_msg"), "submit", BT_ORDER_REF, CLIENT_ORDER_ID),
        (
            lambda receipt: receipt.update(status="accepted"),
            "submit",
            BT_ORDER_REF,
            CLIENT_ORDER_ID,
        ),
        (
            lambda receipt: receipt.update(provider_order_id="venue-order-1"),
            "submit",
            BT_ORDER_REF,
            CLIENT_ORDER_ID,
        ),
        (
            lambda receipt: receipt.update(id="venue-order-1"),
            "submit",
            BT_ORDER_REF,
            CLIENT_ORDER_ID,
        ),
        (lambda receipt: receipt.pop("error_code"), "submit", BT_ORDER_REF, CLIENT_ORDER_ID),
        (
            lambda receipt: receipt.update(status="accepted"),
            "cancel",
            BT_ORDER_REF,
            CLIENT_ORDER_ID,
        ),
    ),
)
def test_invalid_receipts_fail_closed(
    mutate: Any, operation: str, expected_ref: Any, expected_client_id: str
) -> None:
    receipt = _receipt(operation, queued=False)
    mutate(receipt)

    with pytest.raises(ManagedExecutionBindingError):
        classify_ctp_queue_receipt(
            receipt,
            operation=operation,
            expected_bt_order_ref=expected_ref,
            expected_client_order_id=expected_client_id,
        )


def test_queued_receipt_cannot_include_rejection_fields() -> None:
    receipt = _receipt("submit", queued=True)
    receipt["error_code"] = "command_queue_full"

    with pytest.raises(ManagedExecutionBindingError):
        classify_ctp_queue_receipt(
            receipt,
            operation="submit",
            expected_bt_order_ref=BT_ORDER_REF,
            expected_client_order_id=CLIENT_ORDER_ID,
        )


@pytest.mark.parametrize(
    ("expected_ref", "expected_client_id"),
    ((True, CLIENT_ORDER_ID), (BT_ORDER_REF, ""), (BT_ORDER_REF, " client ")),
)
def test_invalid_expected_identity_never_classifies_a_local_rejection(
    expected_ref: Any, expected_client_id: str
) -> None:
    with pytest.raises(ManagedExecutionBindingError):
        classify_ctp_queue_receipt(
            _receipt("submit", queued=False),
            operation="submit",
            expected_bt_order_ref=expected_ref,
            expected_client_order_id=expected_client_id,
        )


def test_recovered_binding_uses_exact_native_order_ref_when_framework_ref_is_absent() -> None:
    receipt = _receipt("cancel", queued=True)
    receipt["bt_order_ref"] = None

    classification = classify_ctp_queue_receipt(
        receipt,
        operation="cancel",
        expected_bt_order_ref=None,
        expected_client_order_id=CLIENT_ORDER_ID,
    )

    assert classification.state is CtpQueueReceiptState.UNKNOWN


def test_recovered_binding_local_rejection_requires_exact_native_order_ref() -> None:
    receipt = _receipt("cancel", queued=False)
    receipt["bt_order_ref"] = None

    classification = classify_ctp_queue_receipt(
        receipt,
        operation="cancel",
        expected_bt_order_ref=None,
        expected_client_order_id=CLIENT_ORDER_ID,
    )

    assert classification.state is CtpQueueReceiptState.REJECTED
    assert classification.error_code == "command_queue_full"


def test_recovered_binding_rejects_receipt_with_a_different_framework_ref() -> None:
    receipt = _receipt("cancel", queued=True)
    receipt["bt_order_ref"] = BT_ORDER_REF

    with pytest.raises(ManagedExecutionBindingError):
        classify_ctp_queue_receipt(
            receipt,
            operation="cancel",
            expected_bt_order_ref=None,
            expected_client_order_id=CLIENT_ORDER_ID,
        )


@pytest.mark.parametrize("client_order_id", ("123", "00000000012x", " 000000000123"))
def test_malformed_ctp_native_order_ref_cannot_classify_a_receipt(
    client_order_id: str,
) -> None:
    with pytest.raises(ManagedExecutionBindingError):
        classify_ctp_queue_receipt(
            _receipt("cancel", queued=True),
            operation="cancel",
            expected_bt_order_ref=BT_ORDER_REF,
            expected_client_order_id=client_order_id,
        )


def test_invalid_operation_fails_closed() -> None:
    with pytest.raises(ManagedExecutionBindingError):
        classify_ctp_queue_receipt(
            _receipt("submit", queued=True),
            operation=[],
            expected_bt_order_ref=BT_ORDER_REF,
            expected_client_order_id=CLIENT_ORDER_ID,
        )
