"""Recovery fee corrections: applied when valid, fenced when not (F5).

A higher cumulative fee in the order's currency for an unchanged quantity is a
fee-only correction (``_apply_fee_only_correction``): the commission moves, no
fill is fabricated. Unusable, regressed or foreign-currency fees keep the fence.
"""

from collections import deque
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backtrader.brokers.btapibroker import BtApiBroker


class _Order:
    Submitted, Accepted, Partial, Completed, Canceled, Rejected = range(6)
    size = 2
    status = Partial
    ref = 17

    def __init__(self, *, commission=0.0, currency="CNY"):
        self.info = {
            "service_execution_recovery_managed": True,
            "managed_intent_id": "intent-a",
            "cumulative_commission_currency": currency,
        }
        self.executed = SimpleNamespace(
            size=1.0, remsize=1.0, price=100.0, comm=commission, exbits=deque([object()])
        )

    def addinfo(self, **values):
        self.info.update(values)

    def partial(self):
        self.status = self.Partial

    def alive(self):
        return self.status == self.Partial

    def clone(self):
        import copy

        return copy.copy(self)


def _broker(order):
    frozen = []
    store = SimpleNamespace(freeze_openings=frozen.append)
    broker = BtApiBroker(store=store)
    broker._service_execution_session = SimpleNamespace(
        recovery_journal=object(),
        adapter=SimpleNamespace(recovery_history=lambda: ()),
    )
    broker.orders[order.ref] = order
    broker._startup_ready = True
    return broker, frozen


def _update(order, *, fee="2", currency="CNY"):
    return {
        "bt_order_ref": order.ref,
        "status": "partial",
        "execution_source": "cumulative",
        "filled_quantity": "1",
        "average_price": "100",
        "cumulative_commission": fee,
        "fee_currency": currency,
    }


def test_valid_late_fee_is_corrected_without_fabricating_a_fill(monkeypatch):
    order = _Order()
    broker, frozen = _broker(order)
    monkeypatch.setattr(broker, "_cache_order_identifiers", lambda *args, **kwargs: None)
    monkeypatch.setattr(broker, "_retry_pending_trade_updates", lambda: None)
    broker._apply_order_update(_update(order))
    assert broker._trading_enabled is not False and not frozen
    assert order.executed.size == 1  # no fill fabricated
    assert order.executed.comm == 2.0
    assert len(order.executed.exbits) == 1
    (correction,) = order.info["fee_corrections"]
    assert (correction["sequence"], correction["currency"]) == (1, "CNY")
    assert Decimal(correction["delta"]) == Decimal(correction["cumulative"]) == Decimal("2")
    assert "execution_commission_unavailable" not in order.info


@pytest.mark.parametrize(
    ("fee", "currency"),
    [("NaN", "CNY"), ("-1", "CNY"), ("0", "USD"), ("0", "")],
)
def test_unusable_fee_or_conflicting_currency_fences(fee, currency):
    order = _Order()
    broker, _ = _broker(order)
    with pytest.raises(RuntimeError, match="projection unavailable"):
        broker._apply_trade_from_order_update(order, _update(order, fee=fee, currency=currency))
    assert order.info["execution_commission_unavailable"] is True
    assert order.executed.comm == 0
    assert len(order.executed.exbits) == 1


def test_unchanged_fee_is_idempotent(monkeypatch):
    order = _Order(commission=2.0)
    broker, _ = _broker(order)
    statuses = []
    monkeypatch.setattr(broker, "_set_status_after_fill", statuses.append)
    update = _update(order)
    assert broker._apply_trade_from_order_update(order, update) == "ignored"
    assert broker._apply_trade_from_order_update(order, update) == "ignored"
    assert statuses == [order, order]
    assert order.executed.comm == 2
    assert len(order.executed.exbits) == 1


def test_regressed_cumulative_fee_fences_without_refund():
    order = _Order(commission=2.0)
    broker, _ = _broker(order)
    with pytest.raises(RuntimeError, match="projection unavailable"):
        broker._apply_trade_from_order_update(order, _update(order, fee="1"))
    assert order.executed.comm == 2
    assert order.info["execution_commission_unavailable"] is True


def test_recovery_event_with_same_fee_keeps_existing_commission():
    order = _Order(commission=2.0)
    broker, frozen = _broker(order)
    broker._apply_service_execution_recovery_event(
        order,
        {
            "event_type": "provider_commission_evidence",
            "state": "PARTIALLY_FILLED",
            "sequence": 1,
            "event_id": "event-a",
            "details": {
                "filled_quantity": "1",
                "average_price": "100",
                "cumulative_commission": "2",
                "cumulative_commission_currency": "CNY",
            },
        },
    )
    assert order.executed.comm == 2
    assert len(order.executed.exbits) == 1
    assert not frozen
    assert order.info["recovery_latest_source_event_id"] == "event-a"


def test_claimed_recovery_receipt_with_late_fee_is_corrected():
    order = _Order()
    broker, frozen = _broker(order)
    event = {
        "intent_id": "intent-a",
        "event_type": "provider_commission_evidence",
        "state": "PARTIALLY_FILLED",
        "details": {
            "filled_quantity": "1",
            "average_price": "100",
            "cumulative_commission": "2",
            "cumulative_commission_currency": "CNY",
        },
    }
    receipt = {
        "receipt_id": "receipt-a",
        "sequence": 1,
        "event": event,
        "matched_manifest": True,
        "callback_pending": True,
    }
    adapter = broker._service_execution_session.adapter
    adapter.recovery_startup_cursor = 0
    adapter.recovery_history = lambda: (receipt,)
    adapter.claim_recovery_callback = lambda _: SimpleNamespace(
        receipt_id="receipt-a",
        sequence=1,
        intent_id="intent-a",
        event=event,
    )
    broker._recovery_orders_by_intent["intent-a"] = order
    broker._process_service_execution_recovery()
    assert not frozen and getattr(broker, "_service_execution_recovery_failed", False) is not True
    assert order.executed.comm == 2.0 and len(order.executed.exbits) == 1
    assert Decimal(order.info["fee_corrections"][0]["delta"]) == Decimal("2")
    assert "receipt-a" in broker._recovery_queued_receipts  # acknowledged after delivery
