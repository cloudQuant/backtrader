"""Iteration 60 (acceptance report P0-2/P0-3): direct strategy books on a ledger.

Product path under test: a real ``BtApiBroker`` gated by the SDK
``SqliteStrategyLedger`` (no bt_api_execution). Orders enter through
``Strategy.buy/sell/close`` -> ``BtApiBroker.submit`` -> Store; the ledger
admits each order before dispatch and follows notifications. Shared account:
strategy A owns 2, strategy B owns 3 of one instrument (account total 5).
"""

from __future__ import annotations

import datetime as dt
import itertools
import threading
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

pytest.importorskip("bt_api_py.strategy_ledger")

import backtrader as bt  # noqa: E402
from backtrader.brokers.btapibroker import BtApiBroker  # noqa: E402
from backtrader.metabase import OwnerContext  # noqa: E402
from backtrader.service.service_strategy_account_book import (  # noqa: E402
    ServiceStrategyAccountBookError,
)
from bt_api_py.strategy_ledger import (  # noqa: E402
    LedgerIntent,
    SqliteStrategyLedger,
    StrategyBudget,
)

INSTRUMENT = "PAPER:SIM:SA2701"
ACCOUNT = "account-direct"


class _Store:
    """Minimal SDK-shaped Store: verified preflight, verified acknowledgements."""

    _sdk_mode = False

    def __init__(self):
        self.sent = []
        self.lock = threading.Lock()
        self.fail_with = None

    def evaluate_order_rules(self, order, **_kwargs):
        return SimpleNamespace(
            status="accepted",
            normalized_offset="open",
            normalized_position_side="long",
            normalized_time_in_force="GTC",
        )

    def verify_order_rules(self, order, rules):
        return True

    def evaluate_order_economics(self, order, rules):
        return SimpleNamespace(status="accepted")

    def verify_order_economics(self, order, economics):
        return True

    def prepare_order_correlation(self, order):
        return {"ref": order.ref}

    def verify_order_response(self, correlation, response):
        return True

    def submit_order(self, order):
        with self.lock:
            self.sent.append(order.ref)
        if self.fail_with is not None:
            raise self.fail_with
        return {
            "kind": "verified_order_ack",
            "verified_order_ack": True,
            "operation": "submit",
            "status": "accepted",
            "id": f"provider-{order.ref}",
        }


class _IdentifiedStrategy(bt.Strategy):
    params = (("strategy_ref", None), ("account_ref", None))


def _data():
    frame = pd.DataFrame(
        {"open": [1500.0], "high": [1501.0], "low": [1499.0], "close": [1500.0], "volume": [1.0]},
        index=pd.to_datetime(["2026-11-03 09:00"]),
    )
    data = bt.feeds.PandasData(dataname=frame, name=INSTRUMENT)
    data._start()
    assert data.load()
    return data


def _strategies(broker, data, *refs):
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    cerebro.stcount = itertools.count()
    cerebro.datas = [data]
    cerebro.datasbyname = {INSTRUMENT: data}
    result = []
    with OwnerContext.set_owner(cerebro):
        for ref in refs:
            strategy = _IdentifiedStrategy.__new__(
                _IdentifiedStrategy, strategy_ref=ref, account_ref=ACCOUNT
            )
            strategy.datas = [data]
            strategy.data = data
            result.append(strategy)
    return result


def _seed(ledger, intent_id, strategy_ref, quantity):
    intent = LedgerIntent(
        intent_id, strategy_ref, INSTRUMENT, "BUY", Decimal(quantity), Decimal("1500")
    )
    ledger.reserve(intent)
    ledger.apply_execution(intent_id, cumulative_quantity=Decimal(quantity), average_price=1500)


def _fill(broker, order, size, price=1500.0):
    """Report an execution of ``size`` more units through the Broker."""
    signed = size if order.isbuy() else -size
    order.execute(dt.datetime(2026, 11, 3, 9, 1), signed, price, 0, 0.0, 0.0, signed, 0.0, 0.0,
                  0.0, 0.0, 0, 0.0)
    if abs(order.executed.size) < abs(order.size):
        order.partial()
    else:
        order.completed()
    broker.notify(order)


@pytest.fixture
def stack(tmp_path):
    ledger = SqliteStrategyLedger(
        tmp_path / "ledger.sqlite3", account_ref=ACCOUNT, contract_multipliers={INSTRUMENT: 10}
    )
    _seed(ledger, "seed-a", "strategy-a", "2")
    _seed(ledger, "seed-b", "strategy-b", "3")
    store = _Store()
    broker = BtApiBroker(store=store)
    data = _data()
    a, b = _strategies(broker, data, "strategy-a", "strategy-b")
    broker.bind_direct_strategy_ledger(a, ledger)
    broker.bind_direct_strategy_ledger(b, ledger)
    try:
        yield SimpleNamespace(ledger=ledger, store=store, broker=broker, data=data, a=a, b=b,
                              path=tmp_path / "ledger.sqlite3")
    finally:
        ledger.close()


def _code(order):
    return order.info.get("error_code")


# -- scoped reads (P0-2) on the product binding -----------------------------------


def test_each_strategy_reads_its_own_position(stack):
    assert stack.a.getposition(stack.data).size == 2.0
    assert stack.b.getposition(stack.data).size == 3.0
    assert stack.a.getpositionbyname(INSTRUMENT).size == 2.0
    assert stack.a.getpositions()[stack.data].size == 2.0


def test_reader_with_provider_positions_fails_closed_on_residual(stack, tmp_path):
    other = BtApiBroker(store=_Store())
    (c,) = _strategies(other, stack.data, "strategy-a")
    view = other.bind_direct_strategy_ledger(c, stack.ledger, account_positions=lambda: {INSTRUMENT: 6})
    with pytest.raises(ServiceStrategyAccountBookError) as info:
        view.getposition(stack.data)
    assert info.value.code == "STRATEGY_BOOK_RECONCILIATION_RESIDUAL"


# -- admission through the product entry (P0-3) ------------------------------------


def test_explicit_over_close_is_rejected_before_dispatch(stack):
    # Strategy.close guards first ...
    with pytest.raises(ValueError, match="exceeds"):
        stack.a.close(data=stack.data, size=5)
    # ... and a raw sell through the Broker is refused by the ledger.
    order = stack.a.sell(data=stack.data, size=5, price=1500.0, exectype=bt.Order.Limit)
    assert order.status == order.Rejected
    assert _code(order) == "strategy_ledger_position_flip_refused"
    assert stack.store.sent == []
    assert stack.b.getposition(stack.data).size == 3.0


def test_a_second_close_cannot_reuse_pending_capacity(stack):
    first = stack.a.close(data=stack.data, price=1500.0, exectype=bt.Order.Limit)
    assert first.status == first.Accepted
    second = stack.a.sell(data=stack.data, size=1, price=1500.0, exectype=bt.Order.Limit)
    assert _code(second) == "strategy_ledger_close_capacity_exceeded"
    # B can still close its own 3.
    third = stack.b.close(data=stack.data, price=1500.0, exectype=bt.Order.Limit)
    assert third.status == third.Accepted
    assert stack.store.sent == [first.ref, third.ref]  # each dispatched exactly once


def test_concurrent_closes_dispatch_at_most_one(stack):
    results = []
    barrier = threading.Barrier(4)

    def attempt():
        barrier.wait()
        results.append(stack.a.sell(data=stack.data, size=2, price=1500.0, exectype=bt.Order.Limit))

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    accepted = [o for o in results if o.status == o.Accepted]
    assert len(accepted) == 1 and stack.store.sent == [accepted[0].ref]


def test_unbound_strategy_cannot_trade_on_a_gated_account(stack):
    (stranger,) = _strategies(stack.broker, stack.data, "strategy-c")
    order = stranger.buy(data=stack.data, size=1, price=1500.0, exectype=bt.Order.Limit)
    assert _code(order) == "strategy_ledger_unbound"
    assert stack.store.sent == []


def test_partial_fill_and_cancel_follow_the_ledger(stack):
    order = stack.a.close(data=stack.data, price=1500.0, exectype=bt.Order.Limit)
    _fill(stack.broker, order, 1)
    assert stack.a.getposition(stack.data).size == 1.0
    assert stack.ledger.intent_state(order.info["strategy_ledger_intent_id"]) == "PARTIALLY_FILLED"
    order.cancel()
    stack.broker.notify(order)
    assert stack.ledger.intent_state(order.info["strategy_ledger_intent_id"]) == "CANCELLED"
    rest = stack.a.close(data=stack.data, price=1500.0, exectype=bt.Order.Limit)
    assert rest.status == rest.Accepted and abs(rest.size) == 1.0
    _fill(stack.broker, rest, 1)
    assert stack.a.getposition(stack.data).size == 0.0
    assert stack.b.getposition(stack.data).size == 3.0


def test_redelivered_notifications_do_not_double_count(stack):
    order = stack.a.close(data=stack.data, price=1500.0, exectype=bt.Order.Limit)
    _fill(stack.broker, order, 2)
    stack.broker.notify(order)
    stack.broker.notify(order)
    assert stack.a.getposition(stack.data).size == 0.0


def test_unknown_dispatch_keeps_capacity_across_restart(stack):
    stack.store.fail_with = TimeoutError("timed out")
    order = stack.a.close(data=stack.data, price=1500.0, exectype=bt.Order.Limit)
    intent_id = order.info["strategy_ledger_intent_id"]
    assert stack.ledger.intent_state(intent_id) == "UNKNOWN"
    stack.ledger.close()  # restart
    ledger = SqliteStrategyLedger(stack.path, account_ref=ACCOUNT, contract_multipliers={INSTRUMENT: 10})
    try:
        assert ledger.intent_state(intent_id) == "UNKNOWN"
        broker = BtApiBroker(store=_Store())
        (a,) = _strategies(broker, stack.data, "strategy-a")
        broker.bind_direct_strategy_ledger(a, ledger)
        again = a.sell(data=stack.data, size=1, price=1500.0, exectype=bt.Order.Limit)
        assert _code(again) == "strategy_ledger_close_capacity_exceeded"
    finally:
        ledger.close()
    stack.ledger = SqliteStrategyLedger(stack.path, account_ref=ACCOUNT)  # fixture teardown


def test_budget_refuses_unknown_inputs_through_the_product_entry(tmp_path):
    ledger = SqliteStrategyLedger(
        tmp_path / "budget.sqlite3",
        account_ref=ACCOUNT,
        budgets={"strategy-a": StrategyBudget(Decimal("100000"), "CNY")},
    )
    try:
        store = _Store()
        broker = BtApiBroker(store=store)
        data = _data()
        (a,) = _strategies(broker, data, "strategy-a")
        broker.bind_direct_strategy_ledger(a, ledger)
        order = a.buy(data=data, size=1, price=1500.0, exectype=bt.Order.Limit)
        assert _code(order) == "strategy_ledger_multiplier_unknown"
        assert store.sent == []
    finally:
        ledger.close()


# -- binding rules -------------------------------------------------------------------


def test_binding_rejects_identity_mismatch_double_binding_and_second_ledger(stack, tmp_path):
    (a2,) = _strategies(stack.broker, stack.data, "strategy-a")
    with pytest.raises(ValueError, match="already bound to another strategy"):
        stack.broker.bind_direct_strategy_ledger(a2, stack.ledger)
    with pytest.raises(ValueError, match="already has"):
        stack.broker.bind_direct_strategy_ledger(stack.a, stack.ledger)
    other = SqliteStrategyLedger(tmp_path / "other.sqlite3", account_ref=ACCOUNT)
    try:
        (c,) = _strategies(stack.broker, stack.data, "strategy-c")
        with pytest.raises(ValueError, match="another strategy ledger"):
            stack.broker.bind_direct_strategy_ledger(c, other)
    finally:
        other.close()


def test_unbound_broker_keeps_backtest_semantics():
    broker = BtApiBroker(store=_Store())
    data = _data()
    (a,) = _strategies(broker, data, "strategy-a")
    order = a.buy(data=data, size=1, price=1500.0, exectype=bt.Order.Limit)
    assert order.status == order.Accepted
    assert "strategy_ledger_intent_id" not in order.info


def test_strategy_book_sizer_sells_only_the_strategy_position(stack):
    from backtrader.sizers.strategy_account_book import StrategyAccountBookPercentSizer

    sizer = StrategyAccountBookPercentSizer(currency="CNY")
    sizer.set(stack.a, stack.broker)
    assert sizer.getsizing(stack.data, False) == 2
    with pytest.raises(ServiceStrategyAccountBookError):  # strategy cash is unavailable
        sizer.getsizing(stack.data, True)
