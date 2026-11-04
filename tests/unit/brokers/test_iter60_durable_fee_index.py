"""Applied-fill index for late fee corrections across a restart (iteration 60, post-acceptance).

Unit level (temp SQLite, in-process "restarts" on the same files): the
notification journal's v3 index (atomic batch writes, keep-existing fee
entries, tamper detection, bounded compaction, in-place v2 upgrade), the
Broker's durable fee path (fills without a provider/client order id are not
indexed; a ledger whose fee total diverged from the journal fails closed),
the SDK ledger's read-only ``execution_totals`` and the service-recovery path
(a terminal order's ``provider_commission_evidence`` reaches the Strategy's
``notify_fee_correction``). The process-restart matrix is in
``tests/integration/test_iter60_restart_fee_corrections.py``.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py.strategy_ledger")

import backtrader as bt  # noqa: E402
from backtrader.brokers._btapi_strategy_events import fill_index_key  # noqa: E402
from backtrader.execution.strategy_notification_outbox import (  # noqa: E402
    JournalIndexUpdate,
    NotificationOutboxError,
    NotificationScope,
    StrategyNotificationJournal,
)

_INTEGRATION = Path(__file__).resolve().parents[2] / "integration"
SCOPE = NotificationScope("account-a", "direct", "strategy-a", "run-1", "gen-1")


def _payload(value) -> bytes:
    return json.dumps({"n": value}, sort_keys=True, separators=(",", ":")).encode()


def _support():
    if str(_INTEGRATION) not in sys.path:
        sys.path.insert(0, str(_INTEGRATION))
    import iter60_gateway_execution_support as support

    return support


# -- journal v3 index ----------------------------------------------------------------


def test_entries_and_index_are_written_in_one_transaction(tmp_path):
    journal = StrategyNotificationJournal(tmp_path / "j.sqlite", SCOPE)
    index = JournalIndexUpdate(
        orders=(("intent:a", _payload("order")),),
        fills=(("fill-1", "intent:a", _payload("fill")),),
        links=(("intent:a", "trade-1"),),
        trades=(("trade-1", _payload("trade")),),
    )
    results = journal.append_many(
        (("f-1", "fee_correction", _payload(1), True), ("o-1", "order", _payload(2))),
        index=index,
    )
    assert [created for _entry, created in results] == [True, True]
    assert journal.indexed_fill("fill-1") == ("intent:a", _payload("fill"))
    assert journal.indexed_order("intent:a") == (_payload("order"), "trade-1", _payload("trade"))
    assert journal.index_stats() == {"orders": 1, "fills": 1, "trades": 1}
    # An invalid index key: nothing of the batch is written.
    bad = JournalIndexUpdate(fills=(("", "intent:a", _payload("fill")),))
    with pytest.raises(NotificationOutboxError, match="INDEX_KEY_INVALID"):
        journal.append_many((("o-2", "order", _payload(3)),), index=bad)
    assert [e.event_id for e in journal.pending()] == ["f-1", "o-1"]
    journal.close()


def test_a_fee_entry_keeps_its_first_snapshot_other_kinds_conflict(tmp_path):
    journal = StrategyNotificationJournal(tmp_path / "j.sqlite", SCOPE)
    journal.append("f-1", "fee_correction", _payload(1), keep_existing=True)
    entry, created = journal.append("f-1", "fee_correction", _payload(9), keep_existing=True)
    assert created is False and entry.payload == _payload(1)
    with pytest.raises(NotificationOutboxError, match="EVENT_ID_CONFLICT"):
        journal.append("f-1", "fee_correction", _payload(9))
    journal.append("o-1", "order", _payload(1))
    with pytest.raises(NotificationOutboxError, match="EVENT_ID_CONFLICT"):
        journal.append_many((("o-1", "order", _payload(2)),))
    journal.close()


def test_a_tampered_index_row_is_detected_on_read(tmp_path):
    path = tmp_path / "j.sqlite"
    journal = StrategyNotificationJournal(path, SCOPE)
    journal.update_index(
        JournalIndexUpdate(
            orders=(("intent:a", _payload("order")),),
            fills=(("fill-1", "intent:a", _payload("fill")),),
        )
    )
    journal.close()
    with sqlite3.connect(path) as db:
        db.execute("UPDATE journal_fill SET record=?", (_payload("other"),))
        db.execute("UPDATE journal_order SET record=?", (_payload("other"),))
    journal = StrategyNotificationJournal(path, SCOPE)
    with pytest.raises(NotificationOutboxError, match="STORE_CORRUPT"):
        journal.indexed_fill("fill-1")
    with pytest.raises(NotificationOutboxError, match="STORE_CORRUPT"):
        journal.indexed_order("intent:a")
    journal.close()


def test_index_is_bounded_by_the_most_recent_orders(tmp_path):
    path = tmp_path / "j.sqlite"
    journal = StrategyNotificationJournal(path, SCOPE, retain_orders=3)
    for n in range(600):
        journal.append_many(
            ((f"o-{n}", "order", _payload(n)),),
            index=JournalIndexUpdate(
                orders=((f"intent:{n}", _payload(n)),),
                fills=((f"fill-{n}", f"intent:{n}", _payload(n)),),
                links=((f"intent:{n}", f"trade-{n}"),),
                trades=((f"trade-{n}", _payload(n)),),
            ),
        )
        journal.acknowledge(f"o-{n}")
        stats = journal.index_stats()
        assert stats["orders"] <= 3 + 256 and stats["fills"] == stats["orders"]
    assert journal.indexed_fill("fill-599") is not None
    assert journal.indexed_fill("fill-0") is None  # compacted with its order
    journal.close()
    reopened = StrategyNotificationJournal(path, SCOPE, retain_orders=3)
    assert reopened.index_stats() == {"orders": 3, "fills": 3, "trades": 3}
    assert reopened.indexed_order("intent:599")[1] == "trade-599"
    reopened.close()


def test_a_version_2_journal_is_upgraded_in_place(tmp_path):
    path = tmp_path / "j.sqlite"
    journal = StrategyNotificationJournal(path, SCOPE)
    journal.append("o-1", "order", _payload(1))
    journal.close()
    with sqlite3.connect(path) as db:  # what iteration 60 R2/R3 wrote
        for table in ("journal_order", "journal_fill", "journal_link", "journal_trade"):
            db.execute(f"DROP TABLE {table}")
        db.execute("PRAGMA user_version=2")
    journal = StrategyNotificationJournal(path, SCOPE)
    assert [e.event_id for e in journal.pending()] == ["o-1"]
    journal.update_index(JournalIndexUpdate(orders=(("intent:a", _payload("order")),)))
    assert journal.index_stats()["orders"] == 1
    journal.close()
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (3,)


# -- SDK ledger accessor ----------------------------------------------------------


def test_ledger_execution_totals_reports_filled_quantity_and_fee_per_currency(tmp_path):
    from bt_api_py.strategy_ledger import LedgerIntent

    t = _support()
    ledger = t.ledger(tmp_path / "ledger.sqlite3")
    try:
        ledger.reserve(
            LedgerIntent("i-1", "strategy-a", t.INSTRUMENT, "SELL", Decimal("2"), Decimal("1500"))
        )
        assert ledger.execution_totals("i-1") == (Decimal("0"), {})
        ledger.apply_execution("i-1", cumulative_quantity=1, average_price=1500, fee="0.5",
                               fee_currency="CNY")
        filled, fees = ledger.execution_totals("i-1")
        assert filled == Decimal("1") and dict(fees) == {"CNY": Decimal("0.5")}
        with pytest.raises(TypeError):
            fees["CNY"] = Decimal("9")  # read-only
    finally:
        ledger.close()


# -- Broker durable fee path ------------------------------------------------------


def _trade_terminal(s, *, stable=True):
    """SELL 2 filled in two fills of 0.5 CNY, all delivered (direct mode)."""

    t = _support()
    order = t.place(s)
    t.cycle(s)
    for row in t.direct_rows(order):
        if row["kind"] == "trade":
            row.update(fee="0.5", fee_currency="CNY", fee_unit="currency")
            if not stable:
                for key in ("external_order_id", "order_id"):
                    row.pop(key)
        if not stable:
            row.pop("client_order_id", None)
        s.store.rows.append(row)
        s.broker.next()
        t.cycle(s)
    return order


def _close(s):
    s.broker.close_strategy_notification_recovery()
    s.ledger.close()


def _correction_row(t, fee="0.8"):
    return {
        "kind": "trade",
        "trade_id": "t-1",
        "external_order_id": "o-1",
        "order_id": "o-1",
        "side": "sell",
        "quantity": "1",
        "price": "1500",
        "quantity_unit": "contracts",
        "data_name": t.INSTRUMENT,
        "fee": fee,
        "fee_currency": "CNY",
        "fee_unit": "currency",
    }


def test_a_ledger_fee_that_diverged_from_the_journal_fails_closed(tmp_path):
    t = _support()
    s = t.stack(tmp_path, "direct")
    _trade_terminal(s)
    _close(s)
    ledger = t.ledger(tmp_path / "ledger.sqlite3")
    ledger.apply_execution("intent-sa-1", cumulative_quantity=2, fee="1.1", fee_currency="CNY")
    ledger.close()
    s = t.stack(tmp_path, "direct")
    calls = []
    s.a.notify_fee_correction = lambda *args: calls.append(args)
    frozen = []
    s.store.freeze_openings = frozen.append
    try:
        assert s.broker._apply_trade_update(_correction_row(t), defer_unmatched=False) == (
            "fee_fenced"
        )
        t.cycle(s)
        assert s.broker.fee_correction_fence() == "ledger_fee_diverged"
        assert s.broker._trading_enabled is False and frozen and calls == []
        assert dict(s.ledger.snapshot("strategy-a").fees_since_baseline) == {
            "CNY": Decimal("1.1")
        }
    finally:
        _close(s)


def test_fills_without_a_provider_or_client_order_id_are_not_indexed(tmp_path):
    t = _support()
    s = t.stack(tmp_path, "direct")
    try:
        _trade_terminal(s, stable=False)
        recovery = s.broker._strategy_notification_recovery[id(s.a)]
        # The order state is indexed (its ledger intent survives), its fills are not:
        # a per-process order ref does not identify a fill after a restart.
        assert recovery.journal.index_stats()["fills"] == 0
        key = ("1", t.INSTRUMENT, "t-1")
        assert s.broker._apply_durable_fill_fee(key, {"local_ref": 1}) is None
    finally:
        _close(s)


def test_a_restarted_correction_is_delivered_once_and_journaled_before_delivery(tmp_path):
    t = _support()
    s = t.stack(tmp_path, "direct")
    original = _trade_terminal(s)
    _close(s)
    s = t.stack(tmp_path, "direct")
    calls = []

    def notify_fee_correction(order, trade, delta, currency):
        recovery = s.broker._strategy_notification_recovery[id(s.a)]
        # Journaled before this callback, acknowledged after it.
        pending = [entry.kind for entry in recovery.journal.pending()]
        calls.append((order.ref, order.info["strategy_ledger_intent_id"], delta, pending))

    s.a.notify_fee_correction = notify_fee_correction
    try:
        assert s.broker._apply_trade_update(_correction_row(t), defer_unmatched=False) == (
            "fee_corrected"
        )
        assert calls == []  # delivered at Cerebro's hand-over, like any notification
        t.cycle(s)
        assert calls == [
            (original.ref, "intent-sa-1", pytest.approx(0.3), ["fee_correction", "order"])
        ]
        assert s.broker._strategy_notification_recovery[id(s.a)].journal.stats()["pending"] == 0
        assert s.broker._apply_trade_update(_correction_row(t), defer_unmatched=False) == "ignored"
        other = dict(_correction_row(t), quantity="2")
        assert s.broker._apply_trade_update(other, defer_unmatched=False) == "ignored"
        assert dict(s.ledger.snapshot("strategy-a").fees_since_baseline) == {
            "CNY": Decimal("1.3")
        }
    finally:
        _close(s)


# -- service recovery: terminal order fee evidence reaches the Strategy -------------


def test_service_recovery_terminal_fee_evidence_reaches_notify_fee_correction():
    t = _support()
    frozen = []
    broker = t.BtApiBroker(store=SimpleNamespace(freeze_openings=frozen.append))
    feed = t.data()
    (strategy,) = t.strategies(broker, feed, "strategy-a")
    calls = []
    strategy.notify_fee_correction = lambda order, trade, delta, currency: calls.append(
        (order.status, None if trade is None else trade.commission, delta, currency)
    )
    strategy.notify_order = lambda order: None
    order = bt.SellOrder(
        owner=strategy, data=feed, size=2, price=1500.0, exectype=bt.Order.Limit,
        simulated=False,
    )
    order.addcomminfo(broker.getcommissioninfo(feed))
    order.submit(broker)
    order.accept(broker)
    order.execute(0.0, -2, 1500.0, 0, 0.0, 0.0, -2, 3000.0, 1.0, 0.0, 0.0, -2, 1500.0)
    order.completed()
    order.addinfo(
        managed_intent_id="intent-a",
        service_execution_recovery_managed=True,
        cumulative_commission_currency="CNY",
    )
    broker.orders[order.ref] = order
    broker.notify(order)  # the Strategy builds its Trade from the fill
    while (notification := broker.get_notification()) is not None:
        notification.owner._addnotification(notification, quicknotify=False)
    assert strategy._order_last_trade()[order.ref].commission == pytest.approx(1.0)
    event = {
        "intent_id": "intent-a",
        "event_type": "provider_commission_evidence",
        "state": "FILLED",
        "sequence": 1,
        "event_id": "event-a",
        "details": {
            "filled_quantity": "2",
            "average_price": "1500",
            "cumulative_commission": "1.4",
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
    acked = []
    broker._service_execution_session = SimpleNamespace(
        recovery_journal=object(),
        adapter=SimpleNamespace(
            recovery_startup_cursor=0,
            recovery_history=lambda: (receipt,),
            claim_recovery_callback=lambda _rid: SimpleNamespace(
                receipt_id="receipt-a", sequence=1, intent_id="intent-a", event=event
            ),
            acknowledge_recovery_callback=acked.append,
        ),
    )
    broker._recovery_orders_by_intent["intent-a"] = order
    broker._process_service_execution_recovery()
    while (notification := broker.get_notification()) is not None:
        notification.owner._addnotification(notification, quicknotify=False)
    strategy._notify()
    assert not frozen and order.status == order.Completed
    assert order.executed.size == -2 and order.executed.comm == pytest.approx(1.4)
    assert calls == [(order.Completed, pytest.approx(1.4), pytest.approx(0.4), "CNY")]
    assert acked == ["receipt-a"]


def test_a_correction_queued_at_close_is_replayed_by_the_next_binding(tmp_path):
    t = _support()
    s = t.stack(tmp_path, "direct")
    _trade_terminal(s)
    _close(s)
    s = t.stack(tmp_path, "direct")
    try:
        assert s.broker._apply_trade_update(_correction_row(t), defer_unmatched=False) == (
            "fee_corrected"
        )
        assert len(s.broker.notifs) == 1
        s.broker.close_strategy_notification_recovery()
        assert len(s.broker.notifs) == 0  # never handed to an unwrapped Strategy
    finally:
        s.ledger.close()
    # Restart with the hook installed before notification recovery is bound.
    ledger = t.ledger(tmp_path / "ledger.sqlite3")
    broker = t.BtApiBroker(store=t.SdkStore())
    (strategy,) = t.strategies(broker, t.data(), "strategy-a")
    calls = []
    strategy.notify_fee_correction = lambda *args: calls.append(args)
    broker.bind_direct_strategy_ledger(strategy, ledger, unreconciled=True)
    try:
        replayed = broker.bind_strategy_notification_recovery(
            strategy, tmp_path / "recovery", deployment_ref="dep"
        )
        assert replayed == 2  # the correction and its order notification
        assert len(calls) == 1 and calls[0][0].replayed is True
        assert calls[0][2] == pytest.approx(0.3)
        assert dict(ledger.snapshot("strategy-a").fees_since_baseline) == {"CNY": Decimal("1.3")}
    finally:
        broker.close_strategy_notification_recovery()
        ledger.close()


def test_fills_stashed_after_their_notification_are_indexed_at_once(tmp_path):
    """Dual-side fills notify before they are remembered: they are flushed directly."""

    t = _support()
    s = t.stack(tmp_path, "direct")
    try:
        order = t.place(s)
        t.cycle(s)
        recovery = s.broker._strategy_notification_recovery[id(s.a)]
        before = recovery.journal.index_stats()["fills"]
        update = _correction_row(t, fee="0.5")
        s.broker._stash_durable_fill(
            ("o-1", t.INSTRUMENT, "t-9"), order, Decimal("1"), Decimal("1500"),
            Decimal("0.5"), "CNY", update,
        )
        s.broker._flush_durable_fills(order)
        assert recovery.journal.index_stats()["fills"] == before + 1
        assert not s.broker.__dict__["_durable_fill_rows"]
        order_key, fill = recovery.durable_fill(fill_index_key(("o-1", t.INSTRUMENT, "t-9")))
        assert order_key == "strategy_ledger_intent_id:intent-sa-1"
        assert (fill["fee"], fill["currency"]) == ("0.5", "CNY")
    finally:
        _close(s)
