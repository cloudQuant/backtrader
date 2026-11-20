"""Regression tests for Iteration 71 Batch 2b:
R71-127, R71-128, R71-129, R71-130, R71-134, R71-135.
"""

from __future__ import annotations

import datetime as _dt
import gc
import types
import weakref
from decimal import Decimal

import pytest

pytest.importorskip("bt_api_py", reason="BtApiBroker tests require bt_api_py")

import backtrader as bt
from backtrader.brokers._btapi_direct_mode import _DIRECT_APPLIED_TRADES_TRUNCATED_SENTINEL
from backtrader.brokers.btapibroker import (
    BtApiBroker,
    _BoundedAppliedFillFees,
    _BoundedTradeKeySet,
)
from backtrader.order import BuyOrder, OrderBase
from backtrader.position import POSITION_MODE_DUAL_SIDE, Position
from tests.unit.brokers.direct._fakes import (
    SYMBOL,
    TODAY,
    Env,
    crash,
    drain,
    order_event,
    position,
    trade_event,
)


class _DummyDt:
    def __init__(self, dt_val):
        self._dt = dt_val

    def __getitem__(self, _idx):
        return self._dt

    def datetime(self, _idx=0):
        return _dt.datetime(2026, 11, 20, 10, 0, 0)


class _DummyData:
    def __init__(self, name="BTC-USDT", dt_val=739000.0, close=100.0):
        self._name = name
        self._dt = dt_val
        self.close = [close]
        self.datetime = _DummyDt(dt_val)
        self.p = types.SimpleNamespace(sessionend=_dt.time(23, 59, 59))

    def __len__(self):
        return 1

    def date2num(self, _val):
        return self._dt

    def num2date(self, _val):
        return _dt.datetime(2026, 11, 20, 10, 0, 0)


class _DummyStore:
    def __init__(self, *, sdk_mode=False, managed_execution_active=False):
        self._sdk_mode = sdk_mode
        self.managed_execution_active = managed_execution_active
        self.frozen_reasons = []
        self.evidence_loss_reasons = []
        self.reconcile_requests = []

    def freeze_openings(self, reason):
        self.frozen_reasons.append(reason)

    def latch_execution_evidence_loss(self, reason):
        self.evidence_loss_reasons.append(reason)

    def enqueue_order_reconciliation(self, order_ref):
        self.reconcile_requests.append(order_ref)
        return {"queued": True, "receipt_id": f"rec-{order_ref}"}


def _make_broker(*, position_mode="net", sdk_mode=False, managed=False):
    store = _DummyStore(sdk_mode=sdk_mode, managed_execution_active=managed)
    broker = BtApiBroker(store=store, position_mode=position_mode)
    return broker, store


def _make_buy_order(broker, data, size=2.0, *, position_side=None, offset=None, ext_id="EX-1"):
    order = BuyOrder(
        owner=types.SimpleNamespace(),
        data=data,
        size=size,
        exectype=OrderBase.Market,
    )
    order.broker = broker
    order.addcomminfo(broker.getcommissioninfo(data))
    info = {"external_order_id": ext_id}
    if position_side is not None:
        info["position_side"] = position_side
    if offset is not None:
        info["offset"] = offset
    order.addinfo(**info)
    order.submit(broker)
    order.accept(broker)
    broker.orders[order.ref] = order
    broker._orders_by_external_id[ext_id] = order
    return order


# ---------------------------------------------------------------------------
# R71-127: Recovery V2 fill emits canonical keys (quantity/price/fee/fee_currency/fee_unit)
# ---------------------------------------------------------------------------
def test_r71_127_recovery_v2_fill_uses_canonical_keys_without_fencing():
    broker, _ = _make_broker(position_mode="net", sdk_mode=False)
    data = _DummyData("BTC-USDT")
    order = BuyOrder(owner=types.SimpleNamespace(), data=data, size=2.0, exectype=OrderBase.Market)
    order.broker = broker
    comminfo = broker.getcommissioninfo(data)
    order.addcomminfo(comminfo)
    order.addinfo(
        managed_intent_id="intent-v2-1",
        managed_instrument="BTC-USDT",
        managed_position_effect="OPEN",
        reduce_only=False,
        service_execution_recovery_managed=True,
    )
    broker.orders[order.ref] = order

    comminfo_ctx = broker._service_recovery_comminfo_context(comminfo)
    dt_hex = float(739000.5).hex()
    as_of_ns = 1_763_632_800_000_000_000
    match_ns = as_of_ns + 1_000_000

    fill = {
        "fill_id": "fill-v2-1",
        "intent_id": "intent-v2-1",
        "provider_order_id": "prov-v2-1",
        "instrument": "BTC-USDT",
        "side": "BUY",
        "quantity": "2",
        "price": "100.5",
        "commission": "1.25",
        "commission_currency": "USDT",
        "match_time_ns": match_ns,
        "quote_source_ref": "qref-1",
        "quote_generation": 1,
        "quote_cursor": 42,
    }
    quote_binding = {
        "source_ref": "qref-1",
        "generation": 1,
        "cursor": 42,
        "instrument": "BTC-USDT",
        "as_of_ns": as_of_ns,
        "data_name": "BTC-USDT",
        "bar_index": 1,
        "datetime_hex": dt_hex,
    }
    intent_context = {
        "feed": {"data_name": "BTC-USDT", "instrument": "BTC-USDT"},
        "comminfo": comminfo_ctx,
        "quote_binding": quote_binding,
    }
    event_context = {
        "data_name": "BTC-USDT",
        "instrument": "BTC-USDT",
        "bar_index": 1,
        "datetime_hex": dt_hex,
        "comminfo": comminfo_ctx,
        "commission_currency": "USDT",
        "quote_source_ref": "qref-1",
        "quote_generation": 1,
        "quote_cursor": 42,
        "quote_instrument": "BTC-USDT",
        "quote_as_of_ns": as_of_ns,
    }
    manifest = {
        "recovery_binding": {"data_name": "BTC-USDT", "tradeid": order.tradeid},
        "submit_payload": {
            "instrument": "BTC-USDT",
            "side": "BUY",
            "position_effect": "OPEN",
            "order_type": "MARKET",
            "time_in_force": "FOK",
            "price": None,
            "reduce_only": False,
            "quantity": "2",
        },
    }
    event = {
        "intent_id": "intent-v2-1",
        "event_type": "provider_observation",
        "state": "FILLED",
        "details": {
            "source": "provider",
            "provider_order_id": "prov-v2-1",
            "filled_quantity": "2",
            "average_price": "100.5",
            "cumulative_commission": "1.25",
            "cumulative_commission_currency": "USDT",
        },
    }
    projection = {
        "status": "READY_TO_PROJECT",
        "reason": None,
        "trade_state": None,
        "trade_notification": None,
        "fill": fill,
        "intent_context": intent_context,
        "event_context": event_context,
    }

    class _FakeAdapter:
        def recovery_manifest(self, intent_id):
            assert intent_id == "intent-v2-1"
            return manifest

        def recovery_intent_execution_context(self, intent_id):
            assert intent_id == "intent-v2-1"
            return intent_context

        def recovery_baseline(self):
            return {"cash_by_currency": {"USDT": "10000"}, "positions": {}}

    broker._service_execution_session = types.SimpleNamespace(adapter=_FakeAdapter())
    broker.positions["BTC-USDT"] = Position()

    # Patch the SDK shape/identity match helpers only if fill fields differ across SDK versions.
    import bt_api_py.service_recovery as sr
    import bt_api_py.service_recovery_quote as srq

    mp = pytest.MonkeyPatch()
    mp.setattr(sr, "paper_recovery_fill_shape_matches", lambda f: f is fill)
    mp.setattr(sr, "paper_recovery_fill_identity_matches", lambda f, e, iid: True)
    mp.setattr(srq, "recovery_quote_fill_matches", lambda qb, f: True)
    try:
        result_order = broker._apply_service_execution_recovery_v2_event(
            order, "receipt-v2-1", event, projection
        )
    finally:
        mp.undo()

    assert result_order is order
    assert order.status == order.Completed
    assert len(order.executed.exbits) == 1
    assert order.executed.size == pytest.approx(2.0)
    assert order.executed.price == pytest.approx(100.5)
    assert order.executed.comm == pytest.approx(1.25)
    assert order.info["provider_fee_totals"] == {"USDT": "1.25"}
    assert order.info["service_execution_recovery_state"] == "FILLED"
    assert not order.info.get("ledger_mismatch", False)


# ---------------------------------------------------------------------------
# R71-128: Dual-side trade update records provider fee totals & avoids duplicates
# ---------------------------------------------------------------------------
def test_r71_128_dual_side_records_provider_fee_before_notify_and_dedupes():
    broker, _ = _make_broker(position_mode=POSITION_MODE_DUAL_SIDE, sdk_mode=False)
    data = _DummyData("rb2610")
    order = _make_buy_order(
        broker, data, size=3.0, position_side="long", offset="open", ext_id="EX-DUAL-1"
    )

    observed_totals_at_notify = []
    orig_notify = broker.notify

    def _capture_notify(o):
        observed_totals_at_notify.append(dict(o.info.get("provider_fee_totals") or {}))
        return orig_notify(o)

    broker.notify = _capture_notify

    fill_1 = {
        "kind": "trade",
        "trade_id": "T-DUAL-1",
        "external_order_id": "EX-DUAL-1",
        "bt_order_ref": order.ref,
        "data_name": "rb2610",
        "side": "buy",
        "position_side": "long",
        "offset": "open",
        "quantity": "1",
        "price": "3500.0",
        "fee": "2.5",
        "fee_currency": "CNY",
        "fee_unit": "currency",
    }
    fill_2 = {
        "kind": "trade",
        "trade_id": "T-DUAL-2",
        "external_order_id": "EX-DUAL-1",
        "bt_order_ref": order.ref,
        "data_name": "rb2610",
        "side": "buy",
        "position_side": "long",
        "offset": "open",
        "quantity": "2",
        "price": "3510.0",
        "fee": "5.0",
        "fee_currency": "CNY",
        "fee_unit": "currency",
    }

    assert broker._apply_trade_update(fill_1, defer_unmatched=False) == "applied"
    assert observed_totals_at_notify[-1] == {"CNY": "2.5"}

    # Replaying fill_1 must NOT double-book fees or position.
    assert broker._apply_trade_update(dict(fill_1), defer_unmatched=False) == "ignored"
    assert order.info["provider_fee_totals"] == {"CNY": "2.5"}
    assert order.executed.size == pytest.approx(1.0)

    # Second partial fill accumulates provider_fee_totals cleanly.
    assert broker._apply_trade_update(fill_2, defer_unmatched=False) == "applied"
    assert observed_totals_at_notify[-1] == {"CNY": "7.5"}
    assert order.info["provider_fee_totals"] == {"CNY": "7.5"}
    assert order.executed.size == pytest.approx(3.0)
    assert order.executed.comm == pytest.approx(7.5)
    assert broker.long_positions["rb2610"].size == pytest.approx(3.0)

    # Late fee correction on fill_2 increments provider_fee_totals by delta only.
    corrected_fill_2 = dict(fill_2, fee="6.25")
    assert broker._apply_trade_update(corrected_fill_2, defer_unmatched=False) == "fee_corrected"
    assert order.info["provider_fee_totals"] == {"CNY": "8.75"}
    assert order.executed.comm == pytest.approx(8.75)


# ---------------------------------------------------------------------------
# R71-129: cancel_rejected clears execution_unknown ONLY when cancel-only
# ---------------------------------------------------------------------------
def test_r71_129_cancel_rejected_clears_cancel_only_unknown_in_order_update_and_managed():
    # Path 1: _apply_order_update("cancel_rejected") after cancel-only unknown.
    broker, _ = _make_broker()
    data = _DummyData("BTC-USDT")
    order = _make_buy_order(broker, data, size=1.0, ext_id="EX-CXL-1")

    broker._mark_cancel_execution_unknown(
        order,
        cancel_requested_remote=True,
        cancel_intent_active=True,
        cancel_error_code="cancel_confirmation_timeout",
    )
    assert order.info["execution_unknown"] is True
    assert order.info["cancel_execution_unknown"] is True
    assert order.info["execution_unknown_from_cancel_only"] is True

    broker._apply_order_update(
        {
            "kind": "order",
            "external_order_id": "EX-CXL-1",
            "bt_order_ref": order.ref,
            "status": "cancel_rejected",
            "error_code": "order_already_matched",
            "status_msg": "Cancel rejected",
        }
    )
    assert order.info["cancel_execution_unknown"] is False
    assert order.info["execution_unknown"] is False
    assert order.info["cancel_requested_remote"] is False
    assert order.info["cancel_intent_active"] is False

    # Path 2: _apply_managed_cancel_projection(rejected) after managed cancel unknown.
    order2 = _make_buy_order(broker, data, size=1.0, ext_id="EX-CXL-2")
    broker._apply_managed_cancel_projection(
        order2, {"execution_unknown": True, "error_code": "timeout"}
    )
    assert order2.info["execution_unknown"] is True
    assert order2.info["cancel_execution_unknown"] is True
    assert order2.info["execution_unknown_from_cancel_only"] is True

    broker._apply_managed_cancel_projection(
        order2, {"status": "rejected", "execution_unknown": False, "error_code": "cannot_cancel"}
    )
    assert order2.info["cancel_execution_unknown"] is False
    assert order2.info["execution_unknown"] is False


def test_r71_129_cancel_rejected_preserves_order_level_unknown_fail_closed():
    broker, _ = _make_broker()
    data = _DummyData("BTC-USDT")

    # Case A: Submit was already execution_unknown before cancel became unknown.
    order_a = _make_buy_order(broker, data, size=1.0, ext_id="EX-UNK-A")
    broker._accept_unknown_submission(order_a, TimeoutError("submit timeout"), "submit_unknown")
    assert order_a.info["execution_unknown"] is True
    assert order_a.info["execution_unknown_from_cancel_only"] is False

    broker._mark_cancel_execution_unknown(
        order_a, cancel_requested_remote=True, cancel_intent_active=True
    )
    assert order_a.info["execution_unknown_from_cancel_only"] is False

    broker._apply_order_update(
        {
            "kind": "order",
            "external_order_id": "EX-UNK-A",
            "bt_order_ref": order_a.ref,
            "status": "cancel_rejected",
            "error_code": "rejected",
        }
    )
    assert order_a.info["cancel_execution_unknown"] is False
    assert order_a.info["execution_unknown"] is True  # MUST remain True!

    # Case B: Cancel became unknown first, then an order-level status=unknown arrived.
    order_b = _make_buy_order(broker, data, size=1.0, ext_id="EX-UNK-B")
    broker._apply_managed_cancel_projection(
        order_b, {"execution_unknown": True, "error_code": "cancel_timeout"}
    )
    assert order_b.info["execution_unknown_from_cancel_only"] is True

    broker._apply_order_update(
        {
            "kind": "order",
            "external_order_id": "EX-UNK-B",
            "bt_order_ref": order_b.ref,
            "status": "unknown",
            "execution_unknown": True,
        }
    )
    assert order_b.info["execution_unknown_from_cancel_only"] is False

    broker._apply_managed_cancel_projection(
        order_b, {"status": "rejected", "execution_unknown": False, "error_code": "cannot_cancel"}
    )
    assert order_b.info["cancel_execution_unknown"] is False
    assert order_b.info["execution_unknown"] is True  # MUST remain True!


# ---------------------------------------------------------------------------
# R71-130: Non-cumulative fill missing trade_id/fill_id fails closed (no double-book)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad_trade_id", [None, "", "   ", True])
def test_r71_130_missing_or_invalid_trade_id_fails_closed_no_execution(bad_trade_id):
    broker, store = _make_broker()
    data = _DummyData("BTC-USDT")
    order = _make_buy_order(broker, data, size=2.0, ext_id="EX-NO-TID")

    update = {
        "kind": "trade",
        "external_order_id": "EX-NO-TID",
        "bt_order_ref": order.ref,
        "data_name": "BTC-USDT",
        "side": "buy",
        "quantity": "1",
        "price": "100.0",
        "fee": "0.1",
        "fee_currency": "USDT",
        "fee_unit": "currency",
    }
    if bad_trade_id is not None:
        update["trade_id"] = bad_trade_id

    outcome1 = broker._apply_trade_update(dict(update), defer_unmatched=False)
    assert outcome1 == "mismatch"
    assert order.executed.size == 0
    assert order.info["execution_unknown"] is True
    assert order.info["ledger_mismatch"] is True
    assert order.info["error_code"] == "trade_id_unavailable"
    assert store.evidence_loss_reasons == ["trade_id_unavailable"]

    # Replay also stays quarantined and never executes.
    outcome2 = broker._apply_trade_update(dict(update), defer_unmatched=False)
    assert outcome2 == "quarantined"
    assert order.executed.size == 0


def test_r71_130_cumulative_status_fill_still_allowed_without_trade_id():
    broker, _ = _make_broker()
    data = _DummyData("BTC-USDT")
    order = _make_buy_order(broker, data, size=2.0, ext_id="EX-CUM-1")

    update = {
        "kind": "trade",
        "external_order_id": "EX-CUM-1",
        "bt_order_ref": order.ref,
        "data_name": "BTC-USDT",
        "side": "buy",
        "quantity": "2",
        "price": "100.0",
        "fee": "0.2",
        "fee_currency": "USDT",
        "fee_unit": "currency",
    }
    assert (
        broker._apply_trade_update(update, defer_unmatched=False, from_cumulative_status=True)
        == "applied"
    )
    assert order.executed.size == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# R71-134: Bounded _seen_trade_ids and weak-ref bounded _applied_fill_fees
# ---------------------------------------------------------------------------
def test_r71_134_bounded_trade_key_set_lru_eviction():
    seen = _BoundedTradeKeySet(maxsize=3)
    for idx in range(5):
        seen.add(("ord", "BTC-USDT", f"t-{idx}"))
    assert len(seen) == 3
    assert ("ord", "BTC-USDT", "t-0") not in seen
    assert ("ord", "BTC-USDT", "t-1") not in seen
    assert ("ord", "BTC-USDT", "t-2") in seen
    assert ("ord", "BTC-USDT", "t-4") in seen

    # Re-adding an existing key refreshes its recency.
    seen.add(("ord", "BTC-USDT", "t-2"))
    seen.add(("ord", "BTC-USDT", "t-5"))
    assert ("ord", "BTC-USDT", "t-2") in seen
    assert ("ord", "BTC-USDT", "t-3") not in seen


def test_r71_134_applied_fill_fees_bounded_and_allows_order_gc():
    broker, _ = _make_broker()
    assert isinstance(broker._seen_trade_ids, _BoundedTradeKeySet)
    assert isinstance(broker._quarantined_trade_ids, _BoundedTradeKeySet)
    assert isinstance(broker._applied_fill_fees, _BoundedAppliedFillFees)

    broker._seen_trade_ids = _BoundedTradeKeySet(maxsize=4)
    broker._applied_fill_fees = _BoundedAppliedFillFees(maxsize=3)

    data = _DummyData("BTC-USDT")
    order = _make_buy_order(broker, data, size=1.0, ext_id="EX-GC-1")
    order_ref = weakref.ref(order)

    update = {
        "kind": "trade",
        "trade_id": "T-GC-1",
        "external_order_id": "EX-GC-1",
        "bt_order_ref": order.ref,
        "data_name": "BTC-USDT",
        "side": "buy",
        "quantity": "1",
        "price": "50.0",
        "fee": "0.5",
        "fee_currency": "USDT",
        "fee_unit": "currency",
    }
    assert broker._apply_trade_update(update, defer_unmatched=False) == "applied"
    key = broker._trade_dedupe_key(update, order=order)
    assert key in broker._applied_fill_fees

    # Drop all external strong references to the terminal order (including broker maps/notifs).
    broker.orders.clear()
    broker.notifs.clear()
    broker._orders_by_external_id.clear()
    broker._orders_by_client_ref.clear()
    del order
    gc.collect()

    assert order_ref() is None
    assert broker._applied_fill_fees.get(key) is None
    assert len(broker._applied_fill_fees) == 0

    # Verify maxsize bound when strong refs to live orders remain.
    live_orders = []
    for idx in range(5):
        o = _make_buy_order(broker, data, size=1.0, ext_id=f"EX-CAP-{idx}")
        live_orders.append(o)
        broker._applied_fill_fees[("ord", "BTC-USDT", f"t-{idx}")] = (
            o,
            Decimal("1"),
            Decimal("10"),
            Decimal("0.1"),
            "USDT",
        )
    assert len(broker._applied_fill_fees) == 3
    assert ("ord", "BTC-USDT", "t-0") not in broker._applied_fill_fees
    assert ("ord", "BTC-USDT", "t-4") in broker._applied_fill_fees


# ---------------------------------------------------------------------------
# R71-135: Direct mode applied_trades truncation fails closed on restart
# ---------------------------------------------------------------------------
def test_r71_135_direct_mode_applied_trades_truncation_fails_closed_no_double_book(tmp_path):
    env = Env(tmp_path)
    try:
        env.init_flat()
        broker = env.start()
        broker._direct_applied_trades_cap = 2  # small cap to exercise >cap truncation cleanly

        # Order 1 gets filled partially (1 of 2 lots) -> marker remains active in pending.json!
        o1 = broker.buy(
            env.strategy, env.feed, 2, price=3500.0, exectype=bt.Order.Limit, offset="open"
        )
        id1 = broker._direct_meta[o1.ref]["identity"]
        env.api.push(
            order_event(id1, "partially_filled", qty=2, filled=1, remaining=1, sys_id="SYS-1")
        )
        t1 = trade_event("TRD-1", qty=1, price=3500.0, sys_id="SYS-1")
        env.api.push(t1)
        broker.next()
        drain(broker)
        assert broker.getposition(env.feed, side="long").size == pytest.approx(1.0)

        # Orders 2 and 3 fill completely -> pushes total applied trades for TODAY to 3 > cap(2),
        # evicting TRD-1 from the bounded tail and persisting the truncation sentinel!
        for _idx, sys_id, trd_id in ((2, "SYS-2", "TRD-2"), (3, "SYS-3", "TRD-3")):
            o = broker.buy(
                env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
            )
            ident = broker._direct_meta[o.ref]["identity"]
            env.api.push(order_event(ident, "filled", qty=1, filled=1, remaining=0, sys_id=sys_id))
            env.api.push(trade_event(trd_id, qty=1, price=3500.0, sys_id=sys_id))
            broker.next()
            drain(broker)

        assert broker.getposition(env.feed, side="long").size == pytest.approx(3.0)
        saved_snap = env.state().snapshot.read()
        assert saved_snap["applied_trades"][TODAY][0] == _DIRECT_APPLIED_TRADES_TRUNCATED_SENTINEL
        assert len(saved_snap["applied_trades"][TODAY]) == 3  # sentinel + 2 retained keys

        # Crash and restart on the SAME trading day; venue reports the exact 3 lots and
        # Order 1 still working with its evicted trade TRD-1 in facts.trades.
        crash(broker)
        env.api.positions = [position("long", 3, 3, 0)]
        o1_live = order_event(id1, "partially_filled", qty=2, filled=1, remaining=1, sys_id="SYS-1")
        env.api.active_orders = [o1_live]
        env.api.orders = [o1_live]
        env.api.trades = [t1]

        broker2 = env.start()
        report = broker2.get_direct_reconcile_report()

        # CRITICAL Fail-Closed checks:
        # 1. TRD-1 was NOT double-booked onto long_positions (remains 3, NOT 4!).
        assert broker2.getposition(env.feed, side="long").size == pytest.approx(3.0)
        assert report["applied_missing_trades"] == 0
        # 2. Symbol is blocked fail-closed with applied_trades_truncated and marker reported.
        assert broker2.direct_writes_blocked()[SYMBOL] == "applied_trades_truncated"
        assert len(report["applied_trades_truncated_markers"]) == 1
        assert report["applied_trades_truncated_markers"][0] in report["unknown_markers"]
    finally:
        env.close()


def test_r71_135_direct_mode_retained_trade_on_truncated_day_not_false_blocked(tmp_path):
    env = Env(tmp_path)
    try:
        env.init_flat()
        broker = env.start()
        broker._direct_applied_trades_cap = 2

        # First two completed orders fill and get evicted/retained.
        for sys_id, trd_id in (("SYS-A", "TRD-A"), ("SYS-B", "TRD-B")):
            o = broker.buy(
                env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
            )
            ident = broker._direct_meta[o.ref]["identity"]
            env.api.push(order_event(ident, "filled", qty=1, filled=1, remaining=0, sys_id=sys_id))
            env.api.push(trade_event(trd_id, qty=1, price=3500.0, sys_id=sys_id))
            broker.next()
            drain(broker)

        # Order C is partially filled and its trade TRD-C IS within the retained tail (cap=2).
        oc = broker.buy(
            env.strategy, env.feed, 2, price=3500.0, exectype=bt.Order.Limit, offset="open"
        )
        idc = broker._direct_meta[oc.ref]["identity"]
        env.api.push(
            order_event(idc, "partially_filled", qty=2, filled=1, remaining=1, sys_id="SYS-C")
        )
        tc = trade_event("TRD-C", qty=1, price=3500.0, sys_id="SYS-C")
        env.api.push(tc)
        broker.next()
        drain(broker)

        crash(broker)
        env.api.positions = [position("long", 3, 3, 0)]
        oc_live = order_event(idc, "partially_filled", qty=2, filled=1, remaining=1, sys_id="SYS-C")
        env.api.active_orders = [oc_live]
        env.api.orders = [oc_live]
        env.api.trades = [tc]

        broker2 = env.start()
        report = broker2.get_direct_reconcile_report()

        # TRD-C is in the retained tail -> proven already applied -> no double-book, no false block!
        assert broker2.getposition(env.feed, side="long").size == pytest.approx(3.0)
        assert report["applied_missing_trades"] == 0
        assert broker2.direct_writes_blocked() == {}
        assert "applied_trades_truncated_markers" not in report
    finally:
        env.close()
