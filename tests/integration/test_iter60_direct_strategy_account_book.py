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
from pathlib import Path
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
    AccountPositionReport,
    InstrumentTerms,
    LedgerIntent,
    SqliteStrategyLedger,
    StrategyBudget,
)

INSTRUMENT = "PAPER:SIM:SA2701"
ACCOUNT = "account-direct"
TERMS = {INSTRUMENT: InstrumentTerms(Decimal("10"), "CNY", "futures")}


def _ledger(path, **kwargs):
    # Opening always needs a budget (G4); a wide default keeps other rules in focus.
    kwargs.setdefault(
        "budgets",
        {
            ref: StrategyBudget(Decimal("1000000000"), "CNY")
            for ref in ("strategy-a", "strategy-b", "strategy-c")
        },
    )
    return SqliteStrategyLedger(path, account_ref=ACCOUNT, instruments=TERMS, **kwargs)


def _report(positions, *, complete=True):
    import time

    return AccountPositionReport(ACCOUNT, "provider:fake", time.time_ns(), complete, positions)


OWNER_ROUTE = "provider:fake-route"


class _RevokedSessions:
    """Fake provider confirmation that the old session is revoked."""

    def verify_session_revocation(self, evidence):
        return True


def _bound_handoff(path, initial_owner):
    """Account-bound coordination handoff (synthetic route, per-test host registry)."""

    from bt_api_py.account_coordination import AccountCoordinationBinding, HostAccountRegistry
    from bt_api_py.account_owner_handoff import AccountOwnerHandoff

    return AccountOwnerHandoff(
        path,
        ACCOUNT,
        initial_owner=initial_owner,
        binding=AccountCoordinationBinding(ACCOUNT, OWNER_ROUTE),
        revocation_verifier=_RevokedSessions(),
        host_registry=HostAccountRegistry(Path(path).parent / "owner-host"),
    )


def _owner(broker, path):
    """Bind ``broker`` as the current account owner (required on a shared account)."""

    handoff = _bound_handoff(path, "direct")
    handoff.hold_owner_lock("direct", provider_session_ref="fake-session-direct")
    broker.bind_account_owner(handoff, "direct")
    return handoff


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
    ledger = _ledger(tmp_path / "ledger.sqlite3")
    _seed(ledger, "seed-a", "strategy-a", "2")
    _seed(ledger, "seed-b", "strategy-b", "3")
    store = _Store()
    broker = BtApiBroker(store=store)
    handoff = _owner(broker, tmp_path / "owner.sqlite3")
    data = _data()
    a, b = _strategies(broker, data, "strategy-a", "strategy-b")
    broker.bind_direct_strategy_ledger(a, ledger, unreconciled=True)
    broker.bind_direct_strategy_ledger(b, ledger, unreconciled=True)
    try:
        yield SimpleNamespace(ledger=ledger, store=store, broker=broker, data=data, a=a, b=b,
                              path=tmp_path / "ledger.sqlite3", owner_path=tmp_path / "owner.sqlite3",
                              owner=handoff)
    finally:
        handoff.close()
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
    view = other.bind_direct_strategy_ledger(
        c, stack.ledger, account_positions=lambda: _report({INSTRUMENT: 6})
    )
    with pytest.raises(ServiceStrategyAccountBookError) as info:
        view.getposition(stack.data)
    assert info.value.code == "STRATEGY_BOOK_RECONCILIATION_RESIDUAL"


def test_binding_needs_a_reconciliation_source_or_an_explicit_opt_out(stack):
    other = BtApiBroker(store=_Store())  # not an SDK-mode Store
    (c,) = _strategies(other, stack.data, "strategy-a")
    with pytest.raises(ValueError, match="needs account positions"):
        other.bind_direct_strategy_ledger(c, stack.ledger)
    with pytest.raises(ValueError, match="cannot be combined"):
        other.bind_direct_strategy_ledger(
            c, stack.ledger, account_positions=lambda: _report({}), unreconciled=True
        )


class _SubscribingStore(_Store):
    """SDK-mode Store with the real subscription wiring and a counted REST read."""

    _sdk_mode = True
    provider = "sim"
    _account_position_subscription = None

    def __init__(self, quantity="5"):
        super().__init__()
        self.quantity = quantity
        self.reads = 0

    from backtrader.stores.btapistore import BtApiStore as _Real

    subscribe_account_positions = _Real.subscribe_account_positions
    del _Real

    def get_positions(self):
        self.reads += 1
        return [
            {
                "data_name": INSTRUMENT,
                "side": "net",
                "quantity": self.quantity,
                "observed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
        ]


def test_default_direct_subscription_is_unverified_without_a_stream_watermark(stack):
    store = _SubscribingStore()
    other = BtApiBroker(store=store)
    (c,) = _strategies(other, stack.data, "strategy-a")
    view = other.bind_direct_strategy_ledger(c, stack.ledger)
    assert store._account_position_subscription is not None and store.reads == 1  # baseline
    for _ in range(5):
        with pytest.raises(ServiceStrategyAccountBookError) as info:
            view.getposition(stack.data)
        assert info.value.code == "STRATEGY_BOOK_RECONCILIATION_UNVERIFIED"
    assert store.reads == 1  # reads never query the provider


def test_position_pushes_and_disconnects_move_the_evidence(stack):
    store = _SubscribingStore()
    other = BtApiBroker(store=store)
    (c,) = _strategies(other, stack.data, "strategy-a")
    view = other.bind_direct_strategy_ledger(c, stack.ledger)
    subscription = store._account_position_subscription
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    subscription.on_position_event(
        {"symbol": INSTRUMENT, "position_side": "net", "quantity": 7, "exchange_time": now}
    )
    with pytest.raises(ServiceStrategyAccountBookError) as info:
        view.getposition(stack.data)  # someone else moved the account to 7
    assert info.value.code == "STRATEGY_BOOK_RECONCILIATION_UNVERIFIED"
    subscription.on_disconnect()
    with pytest.raises(ServiceStrategyAccountBookError) as info:
        view.getposition(stack.data)  # a plain snapshot cannot prove stream continuity
    assert info.value.code == "STRATEGY_BOOK_RECONCILIATION_UNVERIFIED"
    assert store.reads == 2
    subscription.on_position_event({"symbol": INSTRUMENT, "quantity_known": False})
    store.quantity = "9"
    with pytest.raises(ServiceStrategyAccountBookError):
        view.getposition(stack.data)  # still unverified after a new unsequenced snapshot


def test_failed_baseline_keeps_the_book_closed(stack):
    class _Broken(_SubscribingStore):
        def get_positions(self):
            raise RuntimeError("provider down")

    other = BtApiBroker(store=_Broken())
    (c,) = _strategies(other, stack.data, "strategy-a")
    view = other.bind_direct_strategy_ledger(c, stack.ledger)
    with pytest.raises(ServiceStrategyAccountBookError) as info:
        view.getposition(stack.data)
    assert info.value.code == "STRATEGY_BOOK_RECONCILIATION_UNVERIFIED"


def test_store_event_dispatch_routes_position_and_disconnect_events():
    from backtrader.service.store_event_dispatch import drain_store_sdk_events_locked

    calls = []

    class _Subscription:
        def on_position_event(self, event):
            calls.append(("position", event["quantity"]))

        def on_disconnect(self, event):
            calls.append(("disconnect", event.get("kind")))

    class _Api:
        def poll_events(self, venue, **_kwargs):
            return [
                {"kind": "position", "symbol": INSTRUMENT, "quantity": 3},
                {"kind": "disconnect"},
            ]

    store = SimpleNamespace(
        _sdk_exchanges=["SIM"],
        _api=_Api(),
        _sdk_event_batch_size=10,
        _sdk_coalesce_market_snapshots=(),
        uses_async_commands=False,
        _account_position_subscription=_Subscription(),
        emit_runtime_event=lambda *a, **k: None,
        _mark_stream_disconnected=lambda venue, event: calls.append(("store-disconnect", venue)),
        _subscribed_datanames=set(),
    )
    drain_store_sdk_events_locked(store, error_type=RuntimeError, missing_dependency_error_type=ImportError)
    assert calls == [("position", 3), ("disconnect", "disconnect"), ("store-disconnect", "SIM")]


def test_explicit_store_snapshot_mode_remains_unverified(stack):
    store = _SubscribingStore()
    other = BtApiBroker(store=store)
    (c,) = _strategies(other, stack.data, "strategy-a")
    view = other.bind_direct_strategy_ledger(c, stack.ledger, account_positions="store_snapshot")
    for _ in range(2):
        with pytest.raises(ServiceStrategyAccountBookError) as error:
            view.getposition(stack.data)
        assert error.value.code == "STRATEGY_BOOK_RECONCILIATION_UNVERIFIED"
    assert store.reads == 2 and store._account_position_subscription is None


def test_store_report_marks_old_rows_and_bad_rows(stack):
    from backtrader.brokers._btapi_strategy_ledger import store_account_position_report

    class _Rows(_Store):
        _sdk_mode = True

        def __init__(self, rows):
            super().__init__()
            self.rows = rows

        def get_positions(self):
            return self.rows

    old = "2026-01-01T00:00:00Z"
    report = store_account_position_report(
        _Rows([{"data_name": INSTRUMENT, "side": "short", "quantity": "2", "observed_at_utc": old}]),
        ACCOUNT,
    )
    assert report.positions == {INSTRUMENT: Decimal("-2")} and not report.complete
    assert stack.ledger.reconcile(report).reason == "REPORT_INCOMPLETE"
    empty = store_account_position_report(_Rows([]), "unrelated-account")
    assert empty.positions == {} and not empty.complete
    with pytest.raises(ValueError, match="not usable evidence"):
        store_account_position_report(
            _Rows([{"data_name": INSTRUMENT, "side": "both", "quantity": "2", "observed_at_utc": old}]),
            ACCOUNT,
        )


def test_ledger_gated_orders_need_the_owner_fence(tmp_path):
    ledger = _ledger(tmp_path / "nofence.sqlite3")
    try:
        store = _Store()
        broker = BtApiBroker(store=store)
        data = _data()
        (a,) = _strategies(broker, data, "strategy-a")
        broker.bind_direct_strategy_ledger(a, ledger, unreconciled=True)
        order = a.buy(data=data, size=1, price=1500.0, exectype=bt.Order.Limit)
        assert _code(order) == "account_owner_unbound" and store.sent == []
    finally:
        ledger.close()


def test_provider_fees_reach_the_ledger_per_currency(stack):
    order = stack.a.close(data=stack.data, price=1500.0, exectype=bt.Order.Limit)
    # The Broker keeps the provider's running fee per currency for each fill.
    stack.broker._record_provider_fee(order, {"fee_currency": "CNY"}, 1.5)
    _fill(stack.broker, order, 1)
    stack.broker._record_provider_fee(order, {"fee_currency": "CNY"}, 2.0)
    stack.broker._record_provider_fee(order, {"fee_currency": "BNB"}, 0.01)
    stack.broker._record_provider_fee(order, {}, 9.0)  # no currency: never booked
    _fill(stack.broker, order, 1)
    fees = stack.ledger.snapshot("strategy-a").fees_since_baseline
    assert dict(fees) == {"CNY": Decimal("3.5"), "BNB": Decimal("0.01")}
    stack.broker.notify(order)  # redelivery does not double count
    assert dict(stack.ledger.snapshot("strategy-a").fees_since_baseline) == dict(fees)


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
    ledger = _ledger(stack.path)
    try:
        assert ledger.intent_state(intent_id) == "UNKNOWN"
        stack.owner.release_owner_lock()  # the old owner process exits (host lock freed)
        broker = BtApiBroker(store=_Store())
        owner = _owner(broker, stack.owner_path)
        (a,) = _strategies(broker, stack.data, "strategy-a")
        broker.bind_direct_strategy_ledger(a, ledger, unreconciled=True)
        again = a.sell(data=stack.data, size=1, price=1500.0, exectype=bt.Order.Limit)
        assert _code(again) == "strategy_ledger_close_capacity_exceeded"
        owner.close()
    finally:
        ledger.close()
    stack.ledger = _ledger(stack.path)  # fixture teardown


def test_budget_refuses_unknown_inputs_through_the_product_entry(tmp_path):
    ledger = SqliteStrategyLedger(
        tmp_path / "budget.sqlite3",
        account_ref=ACCOUNT,
        budgets={"strategy-a": StrategyBudget(Decimal("100000"), "CNY")},
    )
    try:
        store = _Store()
        broker = BtApiBroker(store=store)
        owner = _owner(broker, tmp_path / "owner.sqlite3")
        data = _data()
        a, b = _strategies(broker, data, "strategy-a", "strategy-b")
        broker.bind_direct_strategy_ledger(a, ledger, unreconciled=True)
        broker.bind_direct_strategy_ledger(b, ledger, unreconciled=True)
        order = a.buy(data=data, size=1, price=1500.0, exectype=bt.Order.Limit)
        assert _code(order) == "strategy_ledger_instrument_terms_unknown"
        # B has no budget: refused, not unlimited (acceptance report F3).
        unbudgeted = b.buy(data=data, size=1, price=1500.0, exectype=bt.Order.Limit)
        assert _code(unbudgeted) == "strategy_ledger_budget_unconfigured"
        assert store.sent == []
        owner.close()
    finally:
        ledger.close()


# -- binding rules -------------------------------------------------------------------


def test_binding_rejects_identity_mismatch_double_binding_and_second_ledger(stack, tmp_path):
    (a2,) = _strategies(stack.broker, stack.data, "strategy-a")
    with pytest.raises(ValueError, match="already bound to another strategy"):
        stack.broker.bind_direct_strategy_ledger(a2, stack.ledger, unreconciled=True)
    with pytest.raises(ValueError, match="already has"):
        stack.broker.bind_direct_strategy_ledger(stack.a, stack.ledger, unreconciled=True)
    other = SqliteStrategyLedger(tmp_path / "other.sqlite3", account_ref=ACCOUNT)
    try:
        (c,) = _strategies(stack.broker, stack.data, "strategy-c")
        with pytest.raises(ValueError, match="another strategy ledger"):
            stack.broker.bind_direct_strategy_ledger(c, other, unreconciled=True)
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
    with pytest.raises(ServiceStrategyAccountBookError):  # no capital, unreconciled: no cash
        sizer.getsizing(stack.data, True)


# -- account-owner dispatch fence (acceptance report P0-1) ---------------------------


def _handoff(path, *, owner_lock=False):
    handoff = _bound_handoff(path, "direct-old")
    if owner_lock:
        handoff.hold_owner_lock("direct-old", provider_session_ref="fake-session-old")
    return handoff


def test_owner_fence_blocks_writes_when_handoff_recovery_is_unverified(tmp_path):
    import time

    from bt_api_py.account_owner_handoff import HandoffError
    from bt_api_py.provider_session_revocation import ProviderSessionRevocationEvidence

    path = tmp_path / "owner.sqlite3"
    data = _data()
    old_store, new_store = _Store(), _Store()
    old_broker, new_broker = BtApiBroker(store=old_store), BtApiBroker(store=new_store)
    old_handoff, new_handoff = _handoff(path, owner_lock=True), _handoff(path)
    try:
        assert old_broker.bind_account_owner(old_handoff, "direct-old") == 1
        with pytest.raises(ValueError, match="not the current account owner"):
            new_broker.bind_account_owner(new_handoff, "gateway-new")
        (a_old,) = _strategies(old_broker, data, "strategy-a")
        live = a_old.buy(data=data, size=1, price=1500.0, exectype=bt.Order.Limit)
        assert live.status == live.Accepted and old_store.sent == [live.ref]

        new_handoff.begin(from_owner="direct-old", to_owner="gateway-new")
        blocked = a_old.buy(data=data, size=1, price=1500.0, exectype=bt.Order.Limit)
        assert _code(blocked) == "account_owner_fenced"
        old_broker.cancel(live)
        assert live.info.get("cancel_error_code") == "account_owner_fenced"
        assert old_store.sent == [live.ref]  # nothing else reached the provider

        new_handoff.fence(
            to_owner="gateway-new",
            evidence=ProviderSessionRevocationEvidence(
                ACCOUNT,
                OWNER_ROUTE,
                1,
                "fake-session-old",
                "PROVIDER_LOGOUT_RECEIPT",
                time.time_ns(),
                "logout-1",
            ),
        )
        new_handoff.restore(to_owner="gateway-new", ledger_cut="cut-1")
        new_handoff.sync(to_owner="gateway-new", provider_snapshot_ref="snap-1")
        with pytest.raises(HandoffError) as error:
            new_handoff.reconcile(to_owner="gateway-new", reconciliation_state="BALANCED")
        assert error.value.code == "HANDOFF_NO_GO_RECOVERY_UNVERIFIED"
        with pytest.raises(HandoffError) as error:
            new_handoff.ready(to_owner="gateway-new")
        assert error.value.code == "HANDOFF_STAGE_OUT_OF_ORDER"
        with pytest.raises(ValueError, match="not the current account owner"):
            new_broker.bind_account_owner(new_handoff, "gateway-new")
        assert new_store.sent == []
        stale = a_old.buy(data=data, size=1, price=1500.0, exectype=bt.Order.Limit)
        assert _code(stale) == "account_owner_fenced"
        assert old_store.sent == [live.ref]
    finally:
        old_handoff.close()
        new_handoff.close()


def test_unreadable_owner_fence_blocks_dispatch(tmp_path):
    data = _data()
    store = _Store()
    broker = BtApiBroker(store=store)
    handoff = _handoff(tmp_path / "owner.sqlite3", owner_lock=True)
    broker.bind_account_owner(handoff, "direct-old")
    handoff.close()  # the fence can no longer be read
    (a,) = _strategies(broker, data, "strategy-a")
    order = a.buy(data=data, size=1, price=1500.0, exectype=bt.Order.Limit)
    assert _code(order) == "account_owner_fenced" and store.sent == []


# -- owner fence at the provider exit (acceptance report G2) --------------------------


def _adapter_dispatch(owner_fence, calls):
    import asyncio

    from backtrader.execution.sdk_correlated_order_adapter import SdkCorrelatedOrderAdapter

    class _Error(RuntimeError):
        pass

    adapter = SdkCorrelatedOrderAdapter(error_type=_Error, bindings=object())

    def route(**_kwargs):
        calls.append("route")

    with pytest.raises(_Error) as info:
        asyncio.run(
            adapter.dispatch_command(
                "submit",
                {"request": object()},
                api=object(),
                authorization=object(),
                current_authorization=lambda: None,
                assert_write_route_identity=route,
                validate_approval_lease_command=lambda command: None,
                sanitize_exception=lambda error: None,
                owner_fence=owner_fence,
            )
        )
    return info.value


def test_worker_rechecks_the_owner_fence_before_any_write():
    calls = []
    error = _adapter_dispatch(lambda: False, calls)
    assert error.code == "account_owner_fenced" and error.definite_reject is True
    assert calls == []  # nothing past the fence ran

    def unreadable():
        raise OSError("fence store gone")

    error = _adapter_dispatch(unreadable, calls)
    assert error.code == "account_owner_fenced" and calls == []


def test_binding_the_owner_installs_the_fence_in_the_store(tmp_path):
    from backtrader.stores.btapistore import BtApiStore

    class _FencedStore(_Store):
        bind_account_owner_fence = BtApiStore.bind_account_owner_fence
        _account_owner_fence = None

    store = _FencedStore()
    broker = BtApiBroker(store=store)
    handoff = _owner(broker, tmp_path / "owner.sqlite3")
    try:
        fence = store._account_owner_fence
        assert fence() is True
        handoff.begin(from_owner="direct", to_owner="gateway-new")
        assert fence() is False  # a command already queued is now refused at the exit
        with pytest.raises(ValueError, match="already bound"):
            store.bind_account_owner_fence(lambda: True)
    finally:
        handoff.close()


def test_async_store_without_an_exit_fence_cannot_be_bound(tmp_path, monkeypatch):
    broker = BtApiBroker(store=_Store())
    monkeypatch.setattr(broker, "_uses_async_commands", lambda: True)
    handoff = _bound_handoff(tmp_path / "owner.sqlite3", "direct")
    handoff.hold_owner_lock("direct", provider_session_ref="fake-session-direct")
    try:
        with pytest.raises(ValueError, match="holds dispatch leases"):
            broker.bind_account_owner(handoff, "direct")
    finally:
        handoff.close()


def test_sync_provider_write_runs_under_an_owner_dispatch_lease(stack):
    """G1: a synchronous Store write holds an SDK lease; UNKNOWN is carried."""

    done = stack.a.close(data=stack.data, price=1500.0, exectype=bt.Order.Limit)
    assert done.status == done.Accepted and stack.owner.unresolved_dispatches() == ()
    stack.store.fail_with = TimeoutError("timed out")
    lost = stack.a.buy(data=stack.data, size=1, price=1500.0, exectype=bt.Order.Limit)
    intent_id = lost.info["strategy_ledger_intent_id"]
    (unresolved,) = stack.owner.unresolved_dispatches()
    assert (unresolved.intent_id, unresolved.state) == (intent_id, "UNKNOWN")


# -- G6: the direct strategy-ledger path never needs bt_api_execution ----------------


def test_direct_ledger_path_runs_with_bt_api_execution_unavailable(tmp_path):
    """Import-blocked, not an isolated install: see the delivery notes for G8."""

    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(
        f"""
        import sys

        class _Block:
            def find_spec(self, name, path=None, target=None):
                if name == "bt_api_execution" or name.startswith("bt_api_execution."):
                    raise ImportError("bt_api_execution is not installed (test)")
                return None

        sys.meta_path.insert(0, _Block())
        sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
        import test_iter60_direct_strategy_account_book as t
        import backtrader as bt
        from pathlib import Path as _P

        ledger = t._ledger(_P({str(tmp_path)!r}) / "noexec.sqlite3")
        t._seed(ledger, "seed-a", "strategy-a", "2")
        broker = t.BtApiBroker(store=t._Store())
        owner = t._owner(broker, _P({str(tmp_path)!r}) / "owner.sqlite3")
        data = t._data()
        (a,) = t._strategies(broker, data, "strategy-a")
        broker.bind_direct_strategy_ledger(a, ledger, unreconciled=True)
        order = a.close(data=data, price=1500.0, exectype=bt.Order.Limit)
        assert order.status == order.Accepted, order.info.get("error_code")
        assert a.getposition(data).size == 2.0
        loaded = sorted(n for n in sys.modules if n.startswith("bt_api_execution"))
        assert not loaded, loaded
        owner.close()
        ledger.close()
        print("ok")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=180, check=False
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().endswith("ok")
