"""Pure CTP DTO/receipt contracts; these never create a Store or grant authority."""

import pytest

from backtrader.stores.btapistore import BtApiStore
from backtrader_runtime.managed_execution import (
    CtpQueueReceiptState,
    classify_ctp_queue_receipt,
)


def _receipt(operation, *, queued=True):
    result = {
        "kind": "command_receipt",
        "command": operation,
        "receipt_id": ("a" if operation == "submit" else "b") * 32,
        "bt_order_ref": 7,
        "client_order_id": "000000000123",
        "status": "submitted" if queued else "rejected",
        "queued": queued,
        "priority": "cancel" if operation == "cancel" else "open",
        "queue_depth": 1 if queued else 0,
    }
    if not queued:
        result.update(
            error_code="command_queue_full",
            error_msg="SDK command queue cannot safely accept this command",
        )
    return result


@pytest.mark.parametrize("operation", ("submit", "cancel"))
def test_local_queue_receipt_is_unknown_not_provider_ack(operation):
    classification = classify_ctp_queue_receipt(
        _receipt(operation),
        operation=operation,
        expected_bt_order_ref=7,
        expected_client_order_id="000000000123",
    )

    assert classification.operation == operation
    assert classification.state is CtpQueueReceiptState.UNKNOWN
    assert classification.queued is True
    assert classification.receipt_id == ("a" if operation == "submit" else "b") * 32
    assert not hasattr(classification, "provider_order_id")
    assert not hasattr(classification, "provider_acknowledgement")


def test_local_queue_rejection_is_not_a_provider_observation():
    classification = classify_ctp_queue_receipt(
        _receipt("submit", queued=False),
        operation="submit",
        expected_bt_order_ref=7,
        expected_client_order_id="000000000123",
    )

    assert classification.state is CtpQueueReceiptState.REJECTED
    assert classification.queued is False
    assert classification.error_code == "command_queue_full"
    assert not hasattr(classification, "provider_order_id")


def test_managed_request_model_identity_shape_is_a_pure_signature_contract():
    class ManagedOrderRequest:
        def __init__(self, managed_intent_id, runtime_order_id, hedge_flag):
            self.managed_intent_id = managed_intent_id
            self.runtime_order_id = runtime_order_id
            self.hedge_flag = hedge_flag

    BtApiStore._require_sdk_request_model_fields(
        ManagedOrderRequest,
        ("managed_intent_id", "runtime_order_id", "hedge_flag"),
        "OrderRequest",
    )
