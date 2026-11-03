"""Iteration 60, re-verification F5: late provider fees are corrected, not dropped.

A fee-only correction (same quantity, higher provider fee in the same
currency) moves the order commission, the strategy ledger (fee-only
``apply_execution``), the Strategy's Trade (``commission``/``pnlcomm``) and
calls ``notify_fee_correction`` on the Strategy, its analyzers and observers,
exactly once per correction. No fill is fabricated. A repeated identical fee is
a no-op; a lower fee or a different currency stays fail-closed.

Two entries: the service-recovery cumulative report (``_apply_fee_only_correction``)
and, in direct mode, a provider re-reporting an applied fill id with its
corrected fee (``_apply_repeated_fill_fee``). With notification recovery bound,
the correction is journaled before dispatch and replayed after a crash.
INTEGRATION_SIM: real ``BtApiBroker``/Strategy/SDK ledger, fake Store, temp SQLite.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py.strategy_ledger")

import backtrader as bt  # noqa: E402

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import test_iter60_notification_recovery as rec  # noqa: E402


class _Listener:
    def __init__(self):
        self.calls = []

    def notify_fee_correction(self, order, trade, delta, currency):
        self.calls.append((order.ref, None if trade is None else trade.commission, delta, currency))


@pytest.fixture
def stack(tmp_path):
    t, ledger, broker, data, (a, b) = rec._stack(tmp_path, "strategy-a", "strategy-b")
    t._seed(ledger, "seed-a", "strategy-a", "2")
    t._seed(ledger, "seed-b", "strategy-b", "3")
    try:
        yield SimpleNamespace(t=t, ledger=ledger, broker=broker, data=data, a=a, b=b, tmp=tmp_path)
    finally:
        broker.close_strategy_notification_recovery()
        ledger.close()


def _fill_update(stack, order, *, fee, currency="CNY", quantity="2", price="1500", fill="f1"):
    return {
        "kind": "trade",
        "bt_order_ref": order.ref,
        "trade_id": fill,
        "side": "buy" if order.isbuy() else "sell",
        "quantity": quantity,
        "price": price,
        "fee": fee,
        "fee_currency": currency,
        "fee_unit": "currency",
        "data_name": stack.t.INSTRUMENT,
    }


def _deliver(stack, strategy):
    rec._cycle(stack.broker, [strategy])


def _hand_over(stack):
    """Cerebro's hand-over only: fee corrections are applied in _addnotification."""
    while (notification := stack.broker.get_notification()) is not None:
        notification.owner._addnotification(notification, quicknotify=False)


# -- service-recovery cumulative entry -------------------------------------------


@pytest.fixture
def recovered(stack):
    order = rec._place(stack.broker, stack.ledger, stack.a, stack.data, 2)
    stack.broker._record_provider_fee(order, {"fee_currency": "CNY"}, 1.5)
    order.addinfo(cumulative_commission_currency="CNY")
    stack.t._fill(stack.broker, order, 2)
    order.executed.comm = 1.5
    stack.a._addnotification(order)  # the Strategy builds its Trade from the fill
    trades = [t for ts in stack.a._trades[stack.data].values() for t in ts]
    listener = _Listener()
    stack.a.analyzers = [listener]
    return stack, order, trades, listener


def test_late_fee_moves_order_ledger_and_trade_once(recovered):
    stack, order, trades, listener = recovered
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
def test_lower_foreign_or_invalid_fees_keep_the_fence(recovered, fee, currency):
    stack, order, _trades, listener = recovered
    with pytest.raises(RuntimeError, match="recovery projection unavailable"):
        stack.broker._apply_fee_only_correction(order, fee, currency)
    assert order.info.get("execution_commission_unavailable") is True
    assert order.executed.comm == 1.5 and listener.calls == []


def test_service_recovery_cumulative_report_applies_the_correction(recovered, monkeypatch):
    stack, order, _trades, listener = recovered
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
    order = rec._place(stack.broker, stack.ledger, stack.a, stack.data, 1)
    stack.t._fill(stack.broker, order, 1)
    order.executed.comm = 0.0
    listener = _Listener()
    stack.a.analyzers = [listener]
    assert stack.broker._apply_fee_only_correction(order, "0.8", "CNY") == "corrected"
    stack.a._apply_fee_corrections(order)
    assert listener.calls == [(order.ref, None, pytest.approx(0.8), "CNY")]


# -- direct: an applied fill re-reported with its corrected fee --------------------


def test_direct_repeated_fill_with_higher_fee_is_a_fee_only_correction(stack):
    listener = _Listener()
    stack.a.analyzers = [listener]
    order = rec._place(stack.broker, stack.ledger, stack.a, stack.data, 2)
    update = _fill_update(stack, order, fee="1.5")
    assert stack.broker._apply_trade_update(dict(update), defer_unmatched=False) == "applied"
    _hand_over(stack)
    trade = stack.a._order_last_trade()[order.ref]
    assert trade.commission == pytest.approx(1.5)
    corrected = dict(update, fee="2.25")
    assert (
        stack.broker._apply_trade_update(dict(corrected), defer_unmatched=False) == "fee_corrected"
    )
    assert order.executed.size == -2 and len(order.executed.exbits) == 1  # no fill fabricated
    assert order.executed.comm == pytest.approx(2.25)
    _hand_over(stack)
    assert trade.commission == pytest.approx(2.25)
    assert trade.pnlcomm == pytest.approx(trade.pnl - 2.25)
    assert listener.calls == [(order.ref, pytest.approx(2.25), pytest.approx(0.75), "CNY")]
    assert dict(stack.ledger.snapshot("strategy-a").fees_since_baseline) == {"CNY": Decimal("2.25")}
    # The same corrected fee again: an idempotent duplicate.
    assert stack.broker._apply_trade_update(dict(corrected), defer_unmatched=False) == "ignored"
    _hand_over(stack)
    assert len(listener.calls) == 1 and order.executed.comm == pytest.approx(2.25)
    assert dict(stack.ledger.snapshot("strategy-a").fees_since_baseline) == {"CNY": Decimal("2.25")}
    assert stack.broker._trading_enabled is not False


@pytest.mark.parametrize(
    "fee, currency, reason",
    [("1.0", "CNY", "fee_regressed"), ("3.0", "USD", "fee_currency_or_basis_mismatch")],
)
def test_direct_regressed_or_foreign_fee_is_fenced(stack, fee, currency, reason):
    frozen = []
    stack.broker.store.freeze_openings = frozen.append
    listener = _Listener()
    stack.a.analyzers = [listener]
    order = rec._place(stack.broker, stack.ledger, stack.a, stack.data, 2)
    update = _fill_update(stack, order, fee="1.5")
    stack.broker._apply_trade_update(dict(update), defer_unmatched=False)
    result = stack.broker._apply_trade_update(
        dict(update, fee=fee, fee_currency=currency), defer_unmatched=False
    )
    assert result == "fee_fenced"
    assert order.info["pnl_status"] == "PNL_INCOMPLETE"
    assert order.info["fee_correction_error"] == reason
    assert stack.broker._trading_enabled is False and frozen
    assert order.executed.comm == pytest.approx(1.5) and listener.calls == []
    assert dict(stack.ledger.snapshot("strategy-a").fees_since_baseline) == {"CNY": Decimal("1.5")}


def test_direct_duplicate_with_other_quantity_is_never_a_fill_or_fee(stack):
    order = rec._place(stack.broker, stack.ledger, stack.a, stack.data, 2)
    update = _fill_update(stack, order, fee="1.5", quantity="1")
    stack.broker._apply_trade_update(dict(update), defer_unmatched=False)
    again = dict(update, quantity="2", fee="9")
    assert stack.broker._apply_trade_update(again, defer_unmatched=False) == "ignored"
    assert order.executed.size == -1 and order.executed.comm == pytest.approx(1.5)


class _CorrectingTradeAnalyzer(bt.analyzers.TradeAnalyzer):
    """A TradeAnalyzer-style consumer that folds corrections into closed totals."""

    def notify_fee_correction(self, order, trade, delta, currency):
        if trade is not None and trade.isclosed:
            self.rets.pnl.net.total -= delta


def test_trade_analyzer_style_consumer_sees_the_correction(stack):
    """A closed Trade already counted is corrected through the hook, not re-notified."""

    analyzer = _CorrectingTradeAnalyzer.__new__(_CorrectingTradeAnalyzer)
    analyzer.rets = bt.AutoOrderedDict()
    analyzer.rets.pnl.net.total = 0.0
    stack.a.analyzers = [analyzer]
    buy = bt.BuyOrder(
        owner=stack.a,
        data=stack.data,
        size=2,
        price=1500.0,
        exectype=bt.Order.Limit,
        simulated=False,
    )
    buy.addcomminfo(stack.broker.getcommissioninfo(stack.data))
    buy.submit(stack.broker)
    stack.broker.orders[buy.ref] = buy
    buy.accept(stack.broker)
    sell = rec._place(stack.broker, stack.ledger, stack.a, stack.data, 2)
    for order, fill, price in ((buy, "fb", "1500"), (sell, "fs", "1510")):
        stack.broker._apply_trade_update(
            dict(_fill_update(stack, order, fee="1", price=price, fill=fill)),
            defer_unmatched=False,
        )
    stack.a._trades.clear()
    stack.a._order_last_trade().clear()
    # Build the round trip in the Strategy and count it like TradeAnalyzer would.
    while (notification := stack.broker.get_notification()) is not None:
        notification.owner._addnotification(notification, quicknotify=False)
    closed = [t for t in stack.a._tradespending if t.isclosed]
    assert closed, "the round trip closes a trade"
    analyzer.rets.pnl.net.total = sum(t.pnlcomm for t in closed)
    counted = analyzer.rets.pnl.net.total
    corrected = dict(_fill_update(stack, sell, fee="1.4", price="1510", fill="fs"))
    assert stack.broker._apply_trade_update(corrected, defer_unmatched=False) == "fee_corrected"
    while (notification := stack.broker.get_notification()) is not None:
        notification.owner._addnotification(notification, quicknotify=False)
    assert analyzer.rets.pnl.net.total == pytest.approx(counted - 0.4)


# -- durable: the correction is journaled before dispatch, replayed after a crash ------


def test_fee_correction_is_journaled_and_replayed_after_a_crash(stack, monkeypatch):
    calls = []

    def notify_fee_correction(self, order, trade, delta, currency):
        calls.append(
            (
                getattr(order, "recovered", False),
                delta,
                currency,
                None if trade is None else trade.commission,
            )
        )
        raise RuntimeError("crash inside the correction callback")

    cls = type(stack.a)
    monkeypatch.setattr(cls, "notify_fee_correction", notify_fee_correction, raising=False)
    monkeypatch.setattr(cls, "notify_order", lambda self, order: None)
    if True:
        stack.broker.bind_strategy_notification_recovery(
            stack.a, stack.tmp / "rec", deployment_ref="dep"
        )
        order = rec._place(stack.broker, stack.ledger, stack.a, stack.data, 2)
        update = _fill_update(stack, order, fee="1.5")
        stack.broker._apply_trade_update(dict(update), defer_unmatched=False)
        _deliver(stack, stack.a)
        stack.broker._apply_trade_update(dict(update, fee="2"), defer_unmatched=False)
        with pytest.raises(RuntimeError, match="crash inside"):
            _deliver(stack, stack.a)
        journal = stack.broker._strategy_notification_recovery[id(stack.a)].journal
        kinds = [entry.kind for entry in journal.pending()]
        assert "fee_correction" in kinds
        stack.broker.close_strategy_notification_recovery()
        # "Restart": a new Broker/Strategy on the same ledger and journal.
        t, broker2 = stack.t, stack.t.BtApiBroker(store=stack.t._Store())
        (a2,) = t._strategies(broker2, t._data(), "strategy-a")
        broker2.bind_direct_strategy_ledger(a2, stack.ledger, unreconciled=True)
        monkeypatch.setattr(
            cls,
            "notify_fee_correction",
            lambda self, order, trade, delta, currency: calls.append(
                (
                    getattr(order, "recovered", False),
                    delta,
                    currency,
                    None if trade is None else trade.commission,
                )
            ),
        )
        delivered = broker2.bind_strategy_notification_recovery(
            a2, stack.tmp / "rec", deployment_ref="dep"
        )
        assert delivered >= 1
        assert calls[0] == (False, pytest.approx(0.5), "CNY", pytest.approx(2.0))
        assert calls[-1] == (True, pytest.approx(0.5), "CNY", pytest.approx(2.0))
        broker2.close_strategy_notification_recovery()
