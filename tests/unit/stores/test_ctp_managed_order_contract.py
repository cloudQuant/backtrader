"""Contracts for the Backtrader-owned managed CTP order and receipt mapping.

These tests exercise the public contract directly.  They do not import any
provider SDK, plugin, or runtime package, and they do not create a journal or
provider request.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from types import SimpleNamespace

import pytest

from backtrader.order import OrderBase
from backtrader.stores.ctp_managed_order_contract import (
    CtpQueueReceiptState,
    ManagedExecutionBindingError,
    _managed_runtime_order_id,
    classify_ctp_queue_receipt,
    strict_limit_intent_from_order,
)

BT_ORDER_REF = 73
CLIENT_ORDER_ID = "000000000073"
RECEIPT_ID = "a" * 32
SCOPE_KEY = "scope:" + "a" * 64
METADATA_DIGEST = "d" * 64


def _receipt(operation: str, *, queued: bool, **overrides):
    receipt = {
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
        receipt["error_code"] = "command_queue_full"
        receipt["error_msg"] = "SDK command queue cannot safely accept this command"
    receipt.update(overrides)
    return receipt


@pytest.mark.parametrize("operation", ("submit", "cancel"))
def test_queued_receipt_is_local_unknown_not_provider_ack(operation):
    classification = classify_ctp_queue_receipt(
        _receipt(operation, queued=True),
        operation=operation,
        expected_bt_order_ref=BT_ORDER_REF,
        expected_client_order_id=CLIENT_ORDER_ID,
    )

    assert classification.operation == operation
    assert classification.state is CtpQueueReceiptState.UNKNOWN
    assert classification.receipt_id == RECEIPT_ID
    assert classification.queued is True
    assert classification.error_code is None


@pytest.mark.parametrize("operation", ("submit", "cancel"))
def test_rejected_receipt_is_local_rejection_only_after_identity_match(operation):
    classification = classify_ctp_queue_receipt(
        _receipt(operation, queued=False),
        operation=operation,
        expected_bt_order_ref=BT_ORDER_REF,
        expected_client_order_id=CLIENT_ORDER_ID,
    )

    assert classification.state is CtpQueueReceiptState.REJECTED
    assert classification.queued is False
    assert classification.error_code == "command_queue_full"


@pytest.mark.parametrize(
    "overrides",
    (
        {"bt_order_ref": 74},
        {"client_order_id": "000000000074"},
        {"kind": "order"},
        {"command": "query"},
        {"receipt_id": "not-a-receipt"},
        {"priority": "cancel"},
        {"queue_depth": -1},
    ),
)
def test_malformed_receipts_fail_closed(overrides):
    with pytest.raises(ManagedExecutionBindingError):
        classify_ctp_queue_receipt(
            _receipt("submit", queued=True, **overrides),
            operation="submit",
            expected_bt_order_ref=BT_ORDER_REF,
            expected_client_order_id=CLIENT_ORDER_ID,
        )


def test_non_boolean_queued_flag_fails_closed():
    receipt = _receipt("submit", queued=True)
    receipt["queued"] = "yes"

    with pytest.raises(ManagedExecutionBindingError):
        classify_ctp_queue_receipt(
            receipt,
            operation="submit",
            expected_bt_order_ref=BT_ORDER_REF,
            expected_client_order_id=CLIENT_ORDER_ID,
        )


def test_receipt_cannot_smuggle_provider_fields():
    receipt = _receipt("submit", queued=True, error_code="late_failure")

    with pytest.raises(ManagedExecutionBindingError, match="fields are incomplete"):
        classify_ctp_queue_receipt(
            receipt,
            operation="submit",
            expected_bt_order_ref=BT_ORDER_REF,
            expected_client_order_id=CLIENT_ORDER_ID,
        )


def test_recovered_binding_uses_exact_native_client_order_id():
    classification = classify_ctp_queue_receipt(
        _receipt("cancel", queued=True, bt_order_ref=None),
        operation="cancel",
        expected_bt_order_ref=None,
        expected_client_order_id=CLIENT_ORDER_ID,
    )

    assert classification.state is CtpQueueReceiptState.UNKNOWN

    with pytest.raises(ManagedExecutionBindingError):
        classify_ctp_queue_receipt(
            _receipt("cancel", queued=True, bt_order_ref=None, client_order_id="123"),
            operation="cancel",
            expected_bt_order_ref=None,
            expected_client_order_id="123",
        )


def test_managed_runtime_order_id_is_deterministic_and_scope_bound():
    scope = SimpleNamespace(key=SCOPE_KEY)

    derived = _managed_runtime_order_id(scope, "intent-1")

    assert derived == _managed_runtime_order_id(scope, "intent-1")
    assert derived.startswith("bt-managed-v1:")
    assert _managed_runtime_order_id(scope, "intent-2") != derived
    assert (
        _managed_runtime_order_id(SimpleNamespace(key="scope:" + "b" * 64), "intent-1") != derived
    )


@pytest.mark.parametrize(
    "scope",
    (SimpleNamespace(key="short"), SimpleNamespace(key=None), object()),
)
def test_managed_runtime_order_id_rejects_non_canonical_scope(scope):
    with pytest.raises(ManagedExecutionBindingError):
        _managed_runtime_order_id(scope, "intent-1")


def test_managed_runtime_order_id_rejects_non_canonical_intent():
    with pytest.raises(ManagedExecutionBindingError):
        _managed_runtime_order_id(SimpleNamespace(key=SCOPE_KEY), " intent-1")


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


class PositionEffect(Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    CLOSE_TODAY = "CLOSE_TODAY"
    CLOSE_YESTERDAY = "CLOSE_YESTERDAY"


class OrderIntent:
    @staticmethod
    def limit(**fields):
        return SimpleNamespace(**fields)


def _execution():
    return SimpleNamespace(
        Side=Side,
        PositionEffect=PositionEffect,
        OrderIntent=OrderIntent,
    )


def _runtime(*, live=False, snapshot=None):
    return SimpleNamespace(
        execution=_execution(),
        scope=SimpleNamespace(provider="CTP", key=SCOPE_KEY),
        contract=SimpleNamespace(mode="live" if live else "replay"),
        instrument_metadata_snapshot=snapshot,
    )


def _order(*, info=None, size=2, price=Decimal("100"), exectype=OrderBase.Limit):
    order_info = {
        "managed_order_type": "LIMIT",
        "managed_instrument": "rb2510",
        "managed_intent_id": "intent-1",
        "managed_signal_id": "signal-1",
        "managed_metadata_version": "metadata-v1",
        "managed_instrument_metadata_digest": METADATA_DIGEST,
        "managed_position_effect": "OPEN",
        "offset": "open",
        "reduce_only": False,
    }
    order_info.update(info or {})
    order = SimpleNamespace(
        ref=42,
        size=size,
        price=price,
        pricelimit=None,
        exectype=exectype,
        valid=None,
        tradeid=0,
        data=SimpleNamespace(_name="rb2510"),
        info=order_info,
        created=SimpleNamespace(price=price),
    )
    order.isbuy = lambda: True
    order.issell = lambda: False
    return order


def test_strict_limit_intent_maps_actual_order_facts():
    intent = strict_limit_intent_from_order(_order(), _runtime())

    assert intent.intent_id == "intent-1"
    assert intent.signal_id == "signal-1"
    assert intent.instrument == "rb2510"
    assert intent.side is Side.BUY
    assert intent.quantity == Decimal("2")
    assert intent.price == Decimal("100")
    assert intent.position_effect is PositionEffect.OPEN
    assert intent.reduce_only is False
    assert intent.metadata_version == "metadata-v1"
    assert intent.tags["instrument_metadata_digest"] == METADATA_DIGEST


@pytest.mark.parametrize(
    "order",
    (
        _order(info={"managed_order_type": "MARKET"}),
        _order(exectype=OrderBase.Market),
        _order(info={"managed_instrument": "rb2601"}),
        _order(info={"offset": "close"}),
        _order(info={"reduce_only": True}),
        _order(price=Decimal("0")),
        _order(size=Decimal("0")),
    ),
)
def test_strict_limit_intent_rejects_framework_drift(order):
    with pytest.raises(ManagedExecutionBindingError):
        strict_limit_intent_from_order(order, _runtime())


def test_strict_limit_intent_rejects_strategy_supplied_quantity_unit():
    order = _order(info={"quantity_unit": "contracts"})

    with pytest.raises(ManagedExecutionBindingError, match="sealed instrument metadata"):
        strict_limit_intent_from_order(order, _runtime())


def test_live_runtime_requires_sealed_instrument_metadata():
    with pytest.raises(ManagedExecutionBindingError, match="sealed instrument metadata"):
        strict_limit_intent_from_order(_order(), _runtime(live=True))


def test_sealed_metadata_digest_must_match_the_order():
    snapshot = SimpleNamespace(
        instrument_metadata=lambda instrument: SimpleNamespace(quantity_unit="contracts"),
        instrument_digest=lambda instrument: "e" * 64,
    )

    with pytest.raises(ManagedExecutionBindingError, match="digest does not match"):
        strict_limit_intent_from_order(
            _order(),
            _runtime(live=True, snapshot=snapshot),
        )


def test_runtime_without_execution_contracts_is_rejected():
    with pytest.raises(ManagedExecutionBindingError, match="lacks execution contracts"):
        strict_limit_intent_from_order(_order(), SimpleNamespace())
