"""I63-E081: order-command completions route to the command branch (UNIT/FAKE).

An earlier refactor left the submit/cancel/query completion tail inside
``_apply_order_reconciliation_completion`` where ``command`` was undefined:
submit/cancel completions were silently ignored and a matched order-scoped
reconciliation raised ``NameError``. These tests pin the restored routing; they
use a synthetic Store and no SDK, provider or account.
"""

from __future__ import annotations

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.order import BuyOrder


class _Store:
    def __init__(self, verified=True):
        self.verified = verified
        self.calls = []

    def verify_order_response(self, correlation, response):
        self.calls.append(("submit", correlation, response))
        return self.verified

    def verify_cancel_response(self, correlation, response):
        self.calls.append(("cancel", correlation, response))
        return self.verified


class _Data:
    _name = "X"

    def __len__(self):
        return 1


def _broker(store):
    broker = BtApiBroker(store=store)
    notified = []
    broker.notify = notified.append
    order = BuyOrder(owner=None, data=_Data(), size=1, price=None,
                     exectype=bt.Order.Market, simulated=True)
    order.submit(broker)
    broker.orders[order.ref] = order
    broker._order_correlations[order.ref] = {"correlation": order.ref}
    return broker, order, notified


def _completion(order, command, status, **response):
    body = {"kind": "verified_order_ack", "verified_order_ack": True,
            "operation": command, "status": status}
    body.update(response)
    return {"kind": "command_completion", "command": command, "bt_order_ref": order.ref,
            "receipt_id": "r-1", "success": True, "response": body}


def test_verified_submit_accept_is_applied():
    store = _Store()
    broker, order, notified = _broker(store)
    broker._apply_command_completion(_completion(order, "submit", "accepted"))
    assert store.calls and store.calls[0][0] == "submit"
    assert order.status == order.Accepted
    assert order.info.get("submit_command_completed") is True
    assert notified == [order]


def test_verified_submit_reject_rejects_original_order():
    broker, order, notified = _broker(_Store())
    broker._apply_command_completion(
        _completion(order, "submit", "rejected", error_code="remote_reject"))
    assert order.status == order.Rejected
    assert order.info.get("error_code") == "remote_reject"
    assert notified == [order]


def test_unverified_submit_is_unknown_not_accepted():
    broker, order, notified = _broker(_Store(verified=False))
    reconciles = []
    broker._request_order_reconcile = reconciles.append
    broker._apply_command_completion(_completion(order, "submit", "accepted"))
    assert order.status == order.Submitted
    assert order.info.get("execution_unknown") is True
    assert reconciles == [order]


def test_unmatched_order_reconciliation_does_not_raise_name_error():
    broker, order, _ = _broker(_Store())
    # Receipt mismatch returns before any projection; the method must not
    # contain a reference to the command-completion variable.
    broker._apply_order_reconciliation_completion(
        {"bt_order_ref": order.ref, "receipt_id": "other"})
    code = BtApiBroker._apply_order_reconciliation_completion.__code__
    assert "command" not in code.co_names and "command" not in code.co_varnames
