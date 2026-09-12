"""Cumulative order checkpoints and incremental trades never share fill identity."""

import backtrader as bt
import pytest

from backtrader.order import SellOrder
from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store

CTP = "CTP___FUTURE"


@pytest.fixture(params=[("net", "long"), ("dual_side", "long"), ("dual_side", "short")])
def stack(request):
    mode, side = request.param
    client = FakeBtApiClient(history={DEFAULT_SYMBOL: [make_bar(0, 100, 151, 99, 110)]})
    store = make_store(api=client, config={"supports_dual_side": True})
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker(
        position_mode=mode,
        validation_enabled=False,
        force_refresh_queries=False,
        account_refresh_interval=3600,
        positions_refresh_interval=3600,
        open_orders_refresh_interval=3600,
    )
    data._start()
    assert data.load()
    broker.start()
    yield client, store, data, broker, side
    broker.stop()


def submit(stack, size=4):
    _, _, data, broker, side = stack
    method = broker.buy if side == "long" else broker.sell
    return method(
        None,
        data,
        size=size,
        price=150,
        exectype=bt.Order.Limit,
        position_side=side,
        offset="open",
    )


def emit(stack, order, **fields):
    stack[0].push_broker_update(
        {
            "bt_order_ref": order.ref,
            "data_name": DEFAULT_SYMBOL,
            "side": "buy" if order.isbuy() else "sell",
            **fields,
        }
    )
    stack[3].next()


def checkpoint(stack, order, quantity, average, status="partial", **extra):
    emit(
        stack,
        order,
        kind="order",
        status=status,
        filled=quantity,
        avg_price=average,
        cumulative_commission=quantity * average * 0.001,
        **extra,
    )


def trade(stack, order, trade_id, price):
    emit(
        stack, order, kind="trade", trade_id=trade_id, size=1, price=price, commission=price * 0.001
    )


def accepted_ctp_pending_order(broker, data, size):
    """Build an already accepted framework order for normalized event tests.

    The CTP Store is intentionally observation-only in this fixture, so the
    test must not arm or submit an order merely to exercise the order/trade
    projection.  This creates the post-acceptance framework state and binds
    the normalized client identity; all subsequent facts still enter through
    the real Store/Feed update path.
    """
    order = SellOrder(
        owner=None,
        data=data,
        size=size,
        price=4000,
        exectype=bt.Order.Limit,
        simulated=True,
    )
    order.addinfo(
        position_side="short",
        offset="open",
        position_mode="dual_side",
        client_order_id="123",
        quantity_unit="contracts",
    )
    order.submit(broker)
    order.addcomminfo(broker.getcommissioninfo(data))
    order.accept(broker)
    order.addinfo(ctp_order_ref="123", external_order_id=f"{CTP}:123")
    broker.orders[order.ref] = order
    broker._orders_by_external_id[f"{CTP}:123"] = order
    broker._remember_client_ref(
        order,
        "123",
        {"exchange_name": CTP, "symbol": "IF2609", "client_order_id": "123"},
    )
    broker._freeze_order_execution_contract(order, replace=True)
    return order


def assert_accounted(stack, order, quantity, average, commission):
    assert abs(order.executed.size) == pytest.approx(quantity)
    assert order.executed.price == pytest.approx(average)
    assert order.executed.comm == pytest.approx(commission)
    _, _, data, broker, side = stack
    position = (
        broker.getposition(data, side=side)
        if broker.p.position_mode == "dual_side"
        else broker.getposition(data)
    )
    assert abs(position.size) == pytest.approx(quantity)
    assert position.price == pytest.approx(average)


def _ctp_reconciliation_snapshot(*, trades=None, execution_summary=None, generation=7):
    """Small local-only CTP snapshot fixture with independent query evidence."""
    trades = list(trades or [])
    summary = {
        "unknown_ids": [],
        "market_data_only": True,
        "armed": False,
        "submit_calls": 0,
        "unmatched_trade_count": 0,
        **(execution_summary or {}),
    }
    return {
        "schema_version": "backtrader.ctp.reconciliation.v1",
        "evidence_complete": True,
        "flat": True,
        "account_fingerprint": "a" * 64,
        "connection_generation": generation,
        "reconciliation_fingerprint": "b" * 64,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
        "orders": [],
        "trades": trades,
        "execution_summary": summary,
        "query_results": {
            name: {
                "request_id": index,
                "complete": True,
                "is_last_seen": True,
                "records": list(trades) if name == "trades" else [],
            }
            for index, name in enumerate(("account", "positions", "orders", "trades"), 1)
        },
    }


def _ctp_trade_row(order_sys_id="SYS-123", order_ref="123", trade_id="T-1", generation=7):
    return {
        "TradeID": trade_id,
        "OrderSysID": order_sys_id,
        "OrderRef": order_ref,
        "ConnectionGeneration": generation,
        "ExchangeID": "CZCE",
        "InstrumentID": "IF2609",
        "TradingDay": "20260909",
    }


def _terminal_local_ctp_order(stack, *, generation=7, external_id="SYS-123", order_ref="123"):
    _, _, data, broker, _ = stack
    order = accepted_ctp_pending_order(broker, data, size=1)
    order.addinfo(
        external_order_id=external_id,
        ctp_order_ref=order_ref,
        connection_generation=generation,
        instrument_id="IF2609",
    )
    broker._orders_by_external_id[external_id] = order
    broker._remember_client_ref(order, order_ref)
    order.completed()
    return order


def test_ctp_reconciliation_allows_only_proven_prestart_missing_unmatched_count(stack):
    _, _, _, broker, _ = stack
    broker._begin_ctp_reconciliation("test")
    snapshot = _ctp_reconciliation_snapshot(execution_summary={"unmatched_trade_count": None})
    snapshot["execution_summary"].pop("unmatched_trade_count", None)
    snapshot.pop("unmatched_trade_count", None)

    first = broker.record_ctp_reconciliation(snapshot)
    second = broker.record_ctp_reconciliation({**snapshot, "reconciliation_fingerprint": "c" * 64})

    assert first["complete"] is False
    assert second["complete"] is False
    assert second["reason"] == "awaiting_second_complete_snapshot"


def test_ctp_reconciliation_accepts_a_complete_known_trade_after_two_rounds(stack):
    _, _, _, broker, _ = stack
    _terminal_local_ctp_order(stack)
    snapshot = _ctp_reconciliation_snapshot(trades=[_ctp_trade_row()])
    broker._begin_ctp_reconciliation("test")

    first = broker.record_ctp_reconciliation(snapshot)
    second_snapshot = dict(snapshot)
    second_snapshot["query_results"] = {
        name: {**result, "request_id": result["request_id"] + 10}
        for name, result in snapshot["query_results"].items()
    }
    second = broker.record_ctp_reconciliation(second_snapshot)

    assert first["complete"] is False
    assert second["complete"] is True


def test_ctp_reconciliation_derives_missing_unmatched_count_only_from_bound_trade(stack):
    _, _, _, broker, _ = stack
    _terminal_local_ctp_order(stack)
    snapshot = _ctp_reconciliation_snapshot(
        trades=[_ctp_trade_row()],
        execution_summary={"market_data_only": False, "armed": True, "submit_calls": 1},
    )
    snapshot.pop("unmatched_trade_count", None)
    snapshot["execution_summary"].pop("unmatched_trade_count", None)
    broker._begin_ctp_reconciliation("test")

    first = broker.record_ctp_reconciliation(snapshot)
    second_snapshot = dict(snapshot)
    second_snapshot["query_results"] = {
        name: {**result, "request_id": result["request_id"] + 10}
        for name, result in snapshot["query_results"].items()
    }
    second = broker.record_ctp_reconciliation(second_snapshot)

    assert first["reason"] == "strict_bound_trade_reconciliation_awaiting_second_snapshot"
    assert second["complete"] is True
    assert second["reason"] == "two_complete_snapshots_agree_strict_bound_trades"


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (_ctp_trade_row(order_sys_id="FOREIGN"), "foreign_trade_row"),
        (_ctp_trade_row(generation=8), "trade_row_generation_mismatch"),
    ],
)
def test_ctp_reconciliation_blocks_foreign_or_generation_mismatched_trade(stack, row, reason):
    _, _, _, broker, _ = stack
    _terminal_local_ctp_order(stack)
    broker._begin_ctp_reconciliation("test")
    state = broker.record_ctp_reconciliation(_ctp_reconciliation_snapshot(trades=[row]))
    assert state["complete"] is False
    assert state["reason"] == reason


def test_ctp_reconciliation_blocks_ambiguous_trade_binding(stack):
    _, _, _, broker, _ = stack
    _terminal_local_ctp_order(stack)
    second = _terminal_local_ctp_order(stack)
    second.addinfo(external_order_id="SYS-123", ctp_order_ref="123", connection_generation=7)
    broker._begin_ctp_reconciliation("test")
    state = broker.record_ctp_reconciliation(
        _ctp_reconciliation_snapshot(trades=[_ctp_trade_row()])
    )
    assert state["complete"] is False
    assert state["reason"] == "ambiguous_trade_row"


def test_ctp_reconciliation_blocks_missing_local_expected_trade(stack):
    _, _, _, broker, _ = stack
    order = _terminal_local_ctp_order(stack)
    order.addinfo(execution_pending_trades=True)
    broker._begin_ctp_reconciliation("test")
    state = broker.record_ctp_reconciliation(_ctp_reconciliation_snapshot())
    assert state["complete"] is False
    assert state["reason"] == "missing_local_expected_trade"


def test_native_ctp_identity_is_cached_only_from_complete_update_values(stack):
    order = submit(stack)
    emit(
        stack,
        order,
        kind="trade",
        trade_id="T-REAL",
        OrderSysID="SYS-REAL",
        OrderRef=str(order.ref),
        ConnectionGeneration=9,
        size=1,
        price=100,
    )
    assert order.info.trade_id == "T-REAL"
    assert order.info.order_sys_id == "SYS-REAL"
    assert order.info.connection_generation == 9

    missing = submit(stack)
    emit(stack, missing, kind="trade", size=1, price=100)
    assert missing.info.get("trade_id") is None
    assert missing.info.get("order_sys_id") is None
    assert missing.info.get("connection_generation") is None


def test_normalized_trade_rebate_keeps_signed_cost_in_execution_accounting(stack):
    order = submit(stack, size=1)
    emit(
        stack,
        order,
        kind="trade",
        trade_id="rebate",
        size=1,
        price=100,
        commission=-0.05,
        commission_normalized=True,
        exchange="OKX",
    )
    assert order.status == bt.Order.Completed
    assert_accounted(stack, order, 1, 100, -0.05)


@pytest.mark.parametrize("total_commission", [-0.05, 0.04])
def test_cumulative_commission_adjustment_keeps_negative_increment(stack, total_commission):
    order = submit(stack, size=2)
    for filled, commission, status in [(1, 0.1, "partial"), (2, total_commission, "completed")]:
        emit(
            stack,
            order,
            kind="order",
            status=status,
            filled=filled,
            avg_price=100,
            cumulative_commission=commission,
            commission_normalized=True,
        )
    assert order.status == bt.Order.Completed
    assert_accounted(stack, order, 2, 100, total_commission)
    assert list(order.executed.exbits)[-1].comm == pytest.approx(total_commission - 0.1)


@pytest.mark.parametrize("status", ["partial", "canceled", "expired"])
def test_aggregate_checkpoint_covers_late_individual_trades_without_price_matching(stack, status):
    order = submit(stack)
    checkpoint(stack, order, 2, 110, status)
    trade(stack, order, "first", 100)
    trade(stack, order, "second", 120)
    trade(stack, order, "first", 100)
    assert_accounted(stack, order, 2, 110, 0.22)
    assert (
        order.status
        == {
            "partial": bt.Order.Partial,
            "canceled": bt.Order.Canceled,
            "expired": bt.Order.Expired,
        }[status]
    )
    assert len(order.executed.exbits) == 1
    assert order.info.execution_fill_source == "cumulative"


def test_same_price_new_cumulative_increment_is_not_a_duplicate_trade(stack):
    order = submit(stack, size=2)
    checkpoint(stack, order, 1, 100, trade_id="snapshot-last-fill")
    checkpoint(stack, order, 2, 100, "completed", trade_id="snapshot-last-fill")
    assert_accounted(stack, order, 2, 100, 0.2)
    assert order.status == bt.Order.Completed
    assert len(order.executed.exbits) == 2


def test_trade_first_checkpoint_books_only_unaccounted_quantity_and_new_average(stack):
    order = submit(stack)
    trade(stack, order, "first", 100)
    trade(stack, order, "first", 100)
    checkpoint(stack, order, 2, 110)
    trade(stack, order, "second", 120)
    assert_accounted(stack, order, 2, 110, 0.22)
    assert [bit.price for bit in order.executed.exbits] == pytest.approx([100, 120])


def test_trade_only_source_accepts_distinct_trades_until_priced_checkpoint_arrives(stack):
    order = submit(stack)
    trade(stack, order, "first", 100)
    trade(stack, order, "second", 120)
    trade(stack, order, "first", 100)
    assert_accounted(stack, order, 2, 110, 0.22)
    assert order.info.execution_fill_source == "trade"
    checkpoint(stack, order, 2, 110)
    trade(stack, order, "third", 140)
    # The third event could overlap an out-of-order checkpoint. No quantity/
    # price heuristic decides that question: wait for cumulative confirmation.
    assert_accounted(stack, order, 2, 110, 0.22)
    checkpoint(stack, order, 3, 120)
    trade(stack, order, "third", 140)
    assert_accounted(stack, order, 3, 120, 0.36)
    assert [bit.price for bit in order.executed.exbits] == pytest.approx([100, 120, 140])


def test_stale_checkpoint_does_not_displace_newer_trade_accounting(stack):
    order = submit(stack)
    trade(stack, order, "first", 100)
    trade(stack, order, "second", 120)
    checkpoint(stack, order, 1, 100)
    assert order.info.execution_fill_source == "trade"
    trade(stack, order, "third", 140)
    assert_accounted(stack, order, 3, 120, 0.36)


@pytest.mark.parametrize("status", ["canceled", "expired"])
def test_unpriced_remote_terminal_status_keeps_late_true_trade_fills_terminal(stack, status):
    order = submit(stack)
    # A CTP-style order status has cumulative volume but no execution price.
    emit(stack, order, kind="order", status=status, filled=2)
    trade(stack, order, "first", 100)
    trade(stack, order, "second", 120)
    assert_accounted(stack, order, 2, 110, 0.22)
    assert order.status == (bt.Order.Canceled if status == "canceled" else bt.Order.Expired)
    assert order.info.execution_fill_source == "trade"
    assert not order.alive()


@pytest.mark.parametrize("status", ["completed", "canceled", "expired"])
def test_trade_source_terminal_report_waits_until_all_reported_deals_are_accounted(stack, status):
    order = submit(stack, size=2 if status == "completed" else 4)
    stack[3].notifs.clear()
    emit(stack, order, kind="order", status=status, filled=2, execution_source="trades")
    assert order.alive()
    assert order.executed.size == 0
    assert not order.info.execution_unknown
    assert order.info.execution_pending_trades
    assert all(notification.alive() for notification in stack[3].notifs)
    trade(stack, order, "first", 100)
    assert order.alive()
    assert order.info.execution_pending_trades
    assert abs(order.executed.size) == 1
    assert all(notification.alive() for notification in stack[3].notifs)
    trade(stack, order, "second", 120)
    assert_accounted(stack, order, 2, 110, 0.22)
    assert (
        order.status
        == {
            "completed": bt.Order.Completed,
            "canceled": bt.Order.Canceled,
            "expired": bt.Order.Expired,
        }[status]
    )
    assert not order.info.execution_pending_trades
    assert not order.alive()


def test_explicit_trade_source_never_promotes_an_order_price_to_a_fill(stack):
    order = submit(stack)
    emit(
        stack,
        order,
        kind="order",
        status="partial",
        filled=2,
        avg_price=150,
        price=150,
        execution_source="trades",
    )
    assert order.executed.size == 0
    trade(stack, order, "first", 100)
    trade(stack, order, "second", 120)
    assert_accounted(stack, order, 2, 110, 0.22)
    assert order.info.execution_fill_source == "trade"


@pytest.mark.parametrize("status", ["canceled", "expired"])
def test_trade_source_zero_fill_terminal_does_not_wait_for_nonexistent_deals(stack, status):
    order = submit(stack)
    emit(stack, order, kind="order", status=status, filled=0, execution_source="trades")
    assert not order.alive()
    assert order.executed.size == 0
    assert not order.info.execution_pending_trades


def test_trade_source_partial_deal_before_terminal_waits_only_for_missing_quantity(stack):
    order = submit(stack)
    trade(stack, order, "first", 100)
    emit(stack, order, kind="order", status="canceled", filled=2, execution_source="trades")
    assert order.alive()
    trade(stack, order, "first", 100)
    assert order.alive()
    assert abs(order.executed.size) == 1
    trade(stack, order, "second", 120)
    assert_accounted(stack, order, 2, 110, 0.22)
    assert order.status == bt.Order.Canceled


@pytest.mark.parametrize("status", ["completed", "canceled"])
def test_normalized_ctp_store_and_native_feed_keep_order_alive_until_deals_arrive(tmp_path, status):
    from tests.unit.stores.test_btapistore_normalized import CTP, FakeSdk, store_for

    sdk = FakeSdk()
    store = store_for(
        sdk,
        exchange_kwargs={CTP: {}},
        symbol_routes={"IF2609": CTP},
        order_journal=tmp_path / "orders.jsonl",
    )
    store.set_history("IF2609", [make_bar(0, 4000, 4001, 3999, 4000)])
    data = store.getdata(dataname="IF2609")
    broker = store.getbroker(
        position_mode="dual_side",
        validation_enabled=False,
        force_refresh_queries=False,
        positions_refresh_interval=3600,
        account_refresh_interval=3600,
        open_orders_refresh_interval=3600,
    )
    data._start()
    assert data.load()
    broker.start()
    try:
        order = accepted_ctp_pending_order(broker, data, size=2 if status == "completed" else 4)
        broker.notifs.clear()
        identity = {"symbol": "IF2609", "client_order_id": "123", "order_id": "123"}
        sdk.events[CTP].append(
            {
                **identity,
                "kind": "order",
                "status": status,
                "filled": 2,
                "avg_price": None,
                "price": 4000,
                "terminal_confirmed": True,
                "execution_unknown": False,
                "execution_source": "trades",
            }
        )
        broker.next()
        assert order.alive() and order.executed.size == 0
        assert not order.info.execution_unknown
        assert all(notification.alive() for notification in broker.notifs)
        for number, price in enumerate((3998, 3996), 1):
            sdk.events[CTP].append(
                {
                    **identity,
                    "kind": "trade",
                    "trade_id": "T" + str(number),
                    "size": 1,
                    "price": price,
                    "side": "sell",
                    "offset": "open",
                    "position_side": "short",
                    "fee": 0.25,
                    "fee_currency": "CNY",
                }
            )
            broker.next()
            if number == 1:
                assert order.alive()
        assert order.status == (bt.Order.Completed if status == "completed" else bt.Order.Canceled)
        assert order.executed.size == -2
        assert order.executed.price == 3997
        assert order.executed.comm == 0.5
        assert broker.getposition(data, side="short").size == 2
        assert broker.getposition(data, side="long").size == 0
    finally:
        broker.stop()
