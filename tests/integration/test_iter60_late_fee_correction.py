"""Iteration 60, re-verification F5: late provider fees are corrected, not dropped.

A cumulative report with the same filled quantity and a higher provider fee is
a fee-only correction: the order commission, the strategy ledger (fee-only
``apply_execution``), the Strategy's Trade (``commission``/``pnlcomm``) and a
``notify_fee_correction`` hook all follow, exactly once per correction. No
fill is fabricated. A repeated identical fee is a no-op; a lower fee or a
different currency keeps the recovery fence.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("bt_api_py.strategy_ledger")

import backtrader as bt  # noqa: E402
from tests.integration import test_iter60_direct_strategy_account_book as base  # noqa: E402
from tests.integration.test_iter60_direct_strategy_account_book import stack  # noqa: E402,F401


class _Listener:
    def __init__(self):
        self.calls = []

    def notify_fee_correction(self, order, trade, delta, currency):
        self.calls.append((order.ref, None if trade is None else trade.commission, delta, currency))


@pytest.fixture
def setup(stack):
    order = stack.a.close(data=stack.data, price=1500.0, exectype=bt.Order.Limit)
    stack.broker._record_provider_fee(order, {"fee_currency": "CNY"}, 1.5)
    order.addinfo(cumulative_commission_currency="CNY")
    base._fill(stack.broker, order, 2)
    order.executed.comm = 1.5
    for exbit in order.executed.exbits:
        exbit.closedcomm = 1.5 if exbit.closed else exbit.closedcomm
    stack.a._addnotification(order)  # the Strategy builds its Trade from the fill
    trades = [t for ts in stack.a._trades[stack.data].values() for t in ts]
    listener = _Listener()
    stack.a.analyzers = [listener]
    return stack, order, trades, listener


def test_late_fee_moves_order_ledger_and_trade_once(setup):
    stack, order, trades, listener = setup
    before = order.executed.comm
    trade = stack.a._order_last_trade().get(order.ref)
    trade_commission = trade.commission
    assert stack.broker._apply_fee_only_correction(order, "3.5", "CNY") == "corrected"
    assert order.executed.comm == 3.5 and order.executed.size == -2  # no fill fabricated
    stack.broker.notify(order)  # books the ledger fee
    fees = stack.ledger.snapshot("strategy-a").fees_since_baseline
    assert dict(fees) == {"CNY": Decimal("3.5")}
    stack.a._addnotification(order)
    assert trade is stack.a._order_last_trade().get(order.ref) and trade in trades
    assert trade.commission == pytest.approx(trade_commission + 3.5 - before)
    assert listener.calls == [(order.ref, trade.commission, pytest.approx(3.5 - before), "CNY")]
    assert trade.pnlcomm == pytest.approx(trade.pnl - trade.commission)
    # Redelivery of the same cumulative fee and of the notification: no change.
    assert stack.broker._apply_fee_only_correction(order, "3.5", "CNY") == "unchanged"
    stack.broker.notify(order)
    stack.a._addnotification(order)
    assert len(listener.calls) == 1
    assert dict(stack.ledger.snapshot("strategy-a").fees_since_baseline) == {"CNY": Decimal("3.5")}


@pytest.mark.parametrize("fee, currency", [("1.0", "CNY"), ("9", "USD"), ("nan", "CNY"), ("2", "")])
def test_lower_foreign_or_invalid_fees_keep_the_fence(setup, fee, currency):
    stack, order, _trades, listener = setup
    with pytest.raises(RuntimeError, match="recovery projection unavailable"):
        stack.broker._apply_fee_only_correction(order, fee, currency)
    assert order.info.get("execution_commission_unavailable") is True
    assert order.executed.comm == 1.5 and listener.calls == []


def test_service_recovery_cumulative_report_applies_the_correction(setup, monkeypatch):
    stack, order, _trades, listener = setup
    monkeypatch.setattr(stack.broker, "_uses_service_execution_recovery", lambda: True)
    order.addinfo(service_execution_recovery_managed=True)
    update = {
        "execution_source": "cumulative",
        "filled_quantity": abs(order.executed.size),
        "average_price": 1500.0,
        "cumulative_commission": "4.25",
        "fee_currency": "CNY",
    }
    stack.broker._apply_trade_from_order_update(order, update)
    assert order.executed.comm == 4.25 and order.executed.size == -2
    assert [entry["delta"] for entry in order.info["fee_corrections"]] == ["2.75"]
    stack.a._addnotification(order)
    assert listener.calls and listener.calls[0][2] == pytest.approx(2.75)
    assert dict(stack.ledger.snapshot("strategy-a").fees_since_baseline) == {"CNY": Decimal("4.25")}
    stack.broker._apply_trade_from_order_update(order, update)  # redelivered: idempotent
    stack.a._addnotification(order)
    assert len(listener.calls) == 1


def test_order_without_a_trade_still_reports_the_correction(stack):
    order = stack.a.close(data=stack.data, price=1500.0, exectype=bt.Order.Limit)
    base._fill(stack.broker, order, 1)
    order.executed.comm = 0.0
    listener = _Listener()
    stack.a.analyzers = [listener]
    assert stack.broker._apply_fee_only_correction(order, "0.8", "CNY") == "corrected"
    stack.a._apply_fee_corrections(order)
    assert listener.calls == [(order.ref, None, pytest.approx(0.8), "CNY")]
