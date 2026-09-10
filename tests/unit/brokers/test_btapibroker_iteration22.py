"""Iteration 22 fail-closed CTP broker contracts."""

import collections
import datetime as dt
import threading
import time
from copy import deepcopy
from types import SimpleNamespace

import backtrader as bt
import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from tests.fixtures.fake_btapi import FakeBtApiClient, make_bar, make_store

SYMBOL = "SA609"


class TypedQueryClient(FakeBtApiClient):
    def __init__(self):
        super().__init__(
            balance={"cash": 1_000_000.0, "value": 1_000_000.0},
            history={SYMBOL: [make_bar(0, 1500.0, 1510.0, 1490.0, 1500.0)]},
        )
        self.request_id = 0
        self.ctp_query_min_interval_seconds = 0.0
        self.session_generation = 3
        self.session_fingerprint = "acct-sha256"
        self.trading_day = "20260909"
        self.request_counts = {
            "settlement_confirm": 0,
            "order_insert": 0,
            "order_action": 0,
        }
        self.incomplete = set()
        self.timeout_submit = False
        self.unknown_ids = []
        self.unmatched_trade_count = 0
        self.query_rows = {
            "account": [{"Balance": 1_000_000.0, "Available": 1_000_000.0}],
            "positions": [],
            "orders": [],
            "trades": [],
            "instruments": [
                {
                    "InstrumentID": SYMBOL,
                    "ExchangeID": "CZCE",
                    "IsTrading": 1,
                    "PriceTick": 1.0,
                    "LowerLimitPrice": 1200.0,
                    "UpperLimitPrice": 1800.0,
                }
            ],
            "margin_rate": [{"InstrumentID": SYMBOL, "LongMarginRatioByMoney": 0.1}],
            "commission_rate": [{"InstrumentID": SYMBOL, "OpenRatioByMoney": 0.0001}],
        }

    def get_session_state(self):
        return {
            "connected": True,
            "ready": True,
            "read_only_ready": True,
            "auto_settlement_confirm": False,
            "connection_generation": self.session_generation,
            "account_fingerprint": self.session_fingerprint,
            "trading_day": self.trading_day,
            "request_counts": dict(self.request_counts),
        }

    def _query(self, name):
        self.request_id += 1
        self.request_counts[name] = self.request_counts.get(name, 0) + 1
        complete = name not in self.incomplete
        return {
            "request_type": name,
            "request_id": self.request_id,
            "connection_generation": self.session_generation,
            "account_fingerprint": self.session_fingerprint,
            "started_at_utc": dt.datetime(2026, 9, 9, tzinfo=dt.timezone.utc).isoformat(),
            "completed_at_utc": (
                dt.datetime(2026, 9, 9, 0, 0, 1, tzinfo=dt.timezone.utc).isoformat()
                if complete
                else None
            ),
            "is_last_seen": complete,
            "error_code": None,
            "error_message": "" if complete else "timeout",
            "timed_out": not complete,
            "complete": complete,
            "records": list(self.query_rows[name]) if complete else [],
            "late_callback_count": 0,
            "unsupported": False,
        }

    def query_account_result(self, **_kwargs):
        return self._query("account")

    def query_positions_result(self, **_kwargs):
        return self._query("positions")

    def query_orders_result(self, **_kwargs):
        return self._query("orders")

    def query_trades_result(self, **_kwargs):
        return self._query("trades")

    def query_instruments_result(self, **_kwargs):
        return self._query("instruments")

    def query_instrument_margin_rate_result(self, **_kwargs):
        return self._query("margin_rate")

    def query_instrument_commission_rate_result(self, **_kwargs):
        return self._query("commission_rate")

    def submit_order(self, payload):
        self.submitted_orders.append(dict(payload))
        if self.timeout_submit:
            raise TimeoutError("ambiguous submit")
        return {"id": f"btapi-{len(self.submitted_orders)}"}

    def get_execution_summary(self):
        return {
            "unknown_ids": list(self.unknown_ids),
            "active_orders": 0,
            "unmatched_trade_count": self.unmatched_trade_count,
        }


class ManagedAsyncCtpClient(TypedQueryClient):
    def __init__(self):
        super().__init__()
        self.exchange_kwargs = {"CTP___FUTURE": {"auto_settlement_confirm": False}}
        self.query_threads = []

    def get_ctp_session_state(self, exchange_name="CTP___FUTURE"):
        assert exchange_name == "CTP___FUTURE"
        return self.get_session_state()

    def get_all_balances(self, normalized=True):
        assert normalized is True
        return {"CTP___FUTURE": {"available": 1_000_000.0, "equity": 1_000_000.0}}

    def get_portfolio_balance(self, venue_balances=None):
        assert "CTP___FUTURE" in (venue_balances or {})
        return {"cash": 1_000_000.0, "value": 1_000_000.0}

    def poll_event(self, _exchange_name):
        return None

    def query_ctp_result(self, exchange_name, query_type, **kwargs):
        assert exchange_name == "CTP___FUTURE"
        self.query_threads.append(threading.get_ident())
        methods = {
            "account": self.query_account_result,
            "positions": self.query_positions_result,
            "orders": self.query_orders_result,
            "trades": self.query_trades_result,
            "instruments": self.query_instruments_result,
            "margin_rate": self.query_instrument_margin_rate_result,
            "commission_rate": self.query_instrument_commission_rate_result,
        }
        return methods[query_type](**kwargs)

    async def async_make_order(self, *_args, **_kwargs):
        return {}

    async def async_cancel_order(self, *_args, **_kwargs):
        return {}

    async def async_query_order(self, *_args, **_kwargs):
        return {}

    def close(self):
        self.connected = False


def _terminal_order_row(order_ref):
    return {
        "OrderRef": str(order_ref),
        "OrderSysID": f"SYS-{order_ref}",
        "FrontID": 1,
        "SessionID": 2,
        "ExchangeID": "CZCE",
        "InstrumentID": SYMBOL,
        "TradingDay": "20260909",
        "status": "canceled",
        "remaining": 0,
    }


def _started_typed_ctp_stack(*, require_complete_ctp_evidence=False):
    client = TypedQueryClient()
    store = make_store(
        api=client,
        provider="ctp_gateway",
        auto_settlement_confirm=False,
        contract_metadata={
            SYMBOL: {
                "price_tick": 1.0,
                "multiplier": 20.0,
                "margin_rate": 0.1,
                "lower_limit_price": 1200.0,
                "upper_limit_price": 1800.0,
            }
        },
    )
    data = store.getdata(
        dataname=SYMBOL,
        historical_bars=[make_bar(0, 1500.0, 1510.0, 1490.0, 1500.0)],
    )
    broker = store.getbroker(
        account_refresh_interval=60.0,
        positions_refresh_interval=60.0,
        require_complete_ctp_evidence=require_complete_ctp_evidence,
    )
    data._start()
    assert data.load() is True
    broker.start()
    return client, store, data, broker


def _started_ctp_stack(*, positions=None, require_complete_ctp_evidence=False):
    client = FakeBtApiClient(
        balance={"cash": 1_000_000.0, "value": 1_000_000.0},
        positions=positions or [],
        history={SYMBOL: [make_bar(0, 1500.0, 1510.0, 1490.0, 1500.0)]},
    )
    store = make_store(
        api=client,
        provider="ctp_gateway",
        contract_metadata={
            SYMBOL: {
                "price_tick": 1.0,
                "multiplier": 20.0,
                "margin_rate": 0.1,
                "lower_limit_price": 1200.0,
                "upper_limit_price": 1800.0,
            }
        },
    )
    data = store.getdata(dataname=SYMBOL)
    broker = store.getbroker(
        account_refresh_interval=60.0,
        positions_refresh_interval=60.0,
        require_complete_ctp_evidence=require_complete_ctp_evidence,
    )
    data._start()
    assert data.load() is True
    broker.start()
    return client, store, data, broker


def test_ctp_order_defaults_to_explicit_gfd_and_routes_it():
    """The frozen first-version CTP order contract is explicit GFD."""
    client, store, data, broker = _started_ctp_stack()
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Accepted
        assert order.info["time_in_force"] == "GFD"
        assert client.submitted_orders[0]["time_in_force"] == "GFD"
    finally:
        broker.stop()
        store.stop()


def test_ctp_ioc_is_rejected_before_remote_submission():
    """Unsupported IOC semantics must never be silently accepted as GFD."""
    client, store, data, broker = _started_ctp_stack()
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
            time_in_force="IOC",
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "unsupported_time_in_force"
        assert client.submitted_orders == []
    finally:
        broker.stop()
        store.stop()


def test_ctp_unknown_order_blocks_reopen_but_allows_risk_reduction():
    """An unresolved order identity blocks new exposure on the synchronous CTP route."""
    positions = [
        {
            "instrument": SYMBOL,
            "direction": "long",
            "volume": 1,
            "price": 1500.0,
        }
    ]
    client, store, data, broker = _started_ctp_stack(positions=positions)
    try:
        unknown = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
        )
        assert unknown.status == bt.Order.Accepted
        unknown.addinfo(execution_unknown=True)

        blocked = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
        )
        assert blocked.status == bt.Order.Rejected
        assert blocked.info["error_code"] == "unknown_execution_exposure"
        assert len(client.submitted_orders) == 1

        flatten = broker.sell(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
            offset="close",
        )
        assert flatten.status == bt.Order.Accepted
        assert flatten.info["offset"] == "close"
        assert len(client.submitted_orders) == 2
    finally:
        broker.stop()
        store.stop()


def test_incomplete_typed_ctp_query_blocks_opening_even_when_records_are_empty():
    client, store, data, broker = _started_typed_ctp_stack()
    client.incomplete.add("orders")
    try:
        snapshot = store.get_ctp_preflight_snapshot(SYMBOL)
        assert snapshot["orders"] == []
        assert snapshot["evidence_complete"] is False

        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
        )
        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "ctp_query_evidence_incomplete"
        assert client.submitted_orders == []
    finally:
        broker.stop()
        store.stop()


def test_unknown_ctp_order_requires_two_complete_identical_reconciliation_rounds():
    client, store, data, broker = _started_typed_ctp_stack()
    try:
        assert store.get_ctp_preflight_snapshot(SYMBOL)["evidence_complete"] is True
        client.timeout_submit = True
        unknown = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
        )
        assert unknown.status == bt.Order.Accepted
        assert unknown.info["execution_unknown"] is True
        client.query_rows["orders"] = [_terminal_order_row(unknown.ref)]

        first = broker.reconcile_ctp_execution(timeout=0)
        assert first["complete"] is False
        assert first["consecutive_complete_rounds"] == 1

        still_blocked = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
        )
        assert still_blocked.status == bt.Order.Rejected
        assert still_blocked.info["error_code"] == "ctp_reconciliation_required"

        second = broker.reconcile_ctp_execution(timeout=0)
        assert second["complete"] is True
        assert unknown.status == bt.Order.Canceled

        client.timeout_submit = False
        reopened = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
        )
        assert reopened.status == bt.Order.Accepted
    finally:
        broker.stop()
        store.stop()


def test_broker_update_between_ctp_snapshots_restarts_two_round_barrier():
    client, store, data, broker = _started_typed_ctp_stack()
    try:
        assert store.get_ctp_preflight_snapshot(SYMBOL)["evidence_complete"] is True
        client.timeout_submit = True
        unknown = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
        )
        client.query_rows["orders"] = [_terminal_order_row(unknown.ref)]
        assert broker.reconcile_ctp_execution(timeout=0)["consecutive_complete_rounds"] == 1

        client.push_broker_update({"kind": "heartbeat"})
        broker._drain_store_updates()
        restarted = broker.reconcile_ctp_execution(timeout=0)
        assert restarted["consecutive_complete_rounds"] == 1
        assert restarted["complete"] is False

        assert broker.reconcile_ctp_execution(timeout=0)["complete"] is True
    finally:
        broker.stop()
        store.stop()


def test_late_trade_after_complete_ctp_reconciliation_relatches_barrier():
    client, store, data, broker = _started_typed_ctp_stack()
    try:
        broker._begin_ctp_reconciliation("test")
        assert broker.reconcile_ctp_execution(timeout=0)["complete"] is False
        assert broker.reconcile_ctp_execution(timeout=0)["complete"] is True

        client.push_broker_update(
            {
                "kind": "trade",
                "external_order_id": "late-unknown-order",
                "trade_id": "late-trade-1",
                "data_name": SYMBOL,
                "side": "buy",
                "size": 1,
                "price": 1500.0,
            }
        )
        broker._drain_store_updates()

        state = broker.get_ctp_reconciliation_state()
        assert state["required"] is True
        assert state["consecutive_complete_rounds"] == 0
        blocked = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
        )
        assert blocked.status == bt.Order.Rejected
        assert blocked.info["error_code"] == "ctp_reconciliation_required"
    finally:
        broker.stop()
        store.stop()


def test_late_reconcile_completion_with_exposure_relatches_barrier():
    client, store, data, broker = _started_typed_ctp_stack()
    try:
        broker._begin_ctp_reconciliation("test")
        assert broker.reconcile_ctp_execution(timeout=0)["complete"] is False
        assert broker.reconcile_ctp_execution(timeout=0)["complete"] is True

        client.push_broker_update(
            {
                "kind": "command_completion",
                "command": "reconcile",
                "success": True,
                "response": {
                    "positions": [
                        {
                            "data_name": SYMBOL,
                            "quantity": 1,
                            "direction": "long",
                            "entry_price": 1500.0,
                        }
                    ],
                    "open_orders": [],
                },
            }
        )
        broker._drain_store_updates()

        state = broker.get_ctp_reconciliation_state()
        assert state["required"] is True
        assert state["consecutive_complete_rounds"] == 0
        assert broker.positions[SYMBOL].size == 1
    finally:
        broker.stop()
        store.stop()


def test_replaying_the_same_complete_snapshot_cannot_unlock_reconciliation():
    client, store, data, broker = _started_typed_ctp_stack()
    try:
        assert store.get_ctp_preflight_snapshot(SYMBOL)["evidence_complete"] is True
        client.timeout_submit = True
        unknown = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
        )
        client.query_rows["orders"] = [_terminal_order_row(unknown.ref)]
        snapshot = store.get_ctp_reconciliation_snapshot(timeout=0)

        first = broker.record_ctp_reconciliation(snapshot)
        replayed = broker.record_ctp_reconciliation(deepcopy(snapshot))

        assert first["consecutive_complete_rounds"] == 1
        assert replayed["consecutive_complete_rounds"] == 1
        assert replayed["complete"] is False
        assert replayed["reason"] == "query_snapshot_replayed"
        assert broker.reconcile_ctp_execution(timeout=0)["complete"] is True
    finally:
        broker.stop()
        store.stop()


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("unknown_intent_count", None, "execution_summary_incomplete"),
        ("unmatched_trade_count", None, "execution_summary_incomplete"),
        ("unknown_intent_count", 1, "execution_summary_not_clear"),
        ("unmatched_trade_count", 1, "execution_summary_not_clear"),
    ],
)
def test_reconciliation_never_unlocks_without_zero_execution_counts(field, value, reason):
    _client, store, data, broker = _started_typed_ctp_stack()
    try:
        broker._begin_ctp_reconciliation("test")
        snapshot = store.get_ctp_reconciliation_snapshot(timeout=0)
        snapshot[field] = value

        first = broker.record_ctp_reconciliation(snapshot)
        second = broker.record_ctp_reconciliation(deepcopy(snapshot))

        assert first["complete"] is False
        assert second["complete"] is False
        assert second["consecutive_complete_rounds"] == 0
        assert second["reason"] == reason
    finally:
        broker.stop()
        store.stop()


def test_strict_ctp_broker_blocks_when_typed_query_capability_is_absent():
    client, store, data, broker = _started_ctp_stack(require_complete_ctp_evidence=True)
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "ctp_query_capability_unavailable"
        assert client.submitted_orders == []
    finally:
        broker.stop()
        store.stop()


def test_ctp_market_order_is_rejected_before_remote_submission():
    client, store, data, broker = _started_ctp_stack()
    try:
        # CTP Market prohibition is a safety invariant, so neither disabling
        # generic validation nor permissive metadata may override it.
        broker.p.validation_enabled = False
        store.contract_metadata[SYMBOL]["supported_order_types"] = ["market", "limit"]
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            exectype=bt.Order.Market,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "unsupported_order_type"
        assert client.submitted_orders == []
    finally:
        broker.stop()
        store.stop()


def test_strict_ctp_broker_rejects_preflight_from_an_old_session():
    client, store, data, broker = _started_typed_ctp_stack(require_complete_ctp_evidence=True)
    try:
        assert store.get_ctp_preflight_snapshot(SYMBOL, timeout=0)["evidence_complete"] is True
        client.session_generation = 4

        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "ctp_query_evidence_incomplete"
        assert client.submitted_orders == []
    finally:
        broker.stop()
        store.stop()


def test_strict_ctp_broker_rejects_non_tradable_instrument_evidence():
    client, store, data, broker = _started_typed_ctp_stack(require_complete_ctp_evidence=True)
    try:
        client.query_rows["instruments"][0]["IsTrading"] = 0
        assert store.get_ctp_preflight_snapshot(SYMBOL, timeout=0)["evidence_complete"] is True

        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == "ctp_instrument_state_unproven"
        assert client.submitted_orders == []
    finally:
        broker.stop()
        store.stop()


@pytest.mark.parametrize(
    ("unknown_ids", "unmatched_trade_count", "expected_error"),
    [
        (["intent-1"], 0, "ctp_execution_summary_not_clear"),
        ([], 1, "ctp_execution_summary_not_clear"),
        ([], None, "ctp_execution_summary_incomplete"),
    ],
)
def test_strict_ctp_broker_blocks_unresolved_execution_summary(
    unknown_ids, unmatched_trade_count, expected_error
):
    client, store, data, broker = _started_typed_ctp_stack(require_complete_ctp_evidence=True)
    try:
        client.unknown_ids = unknown_ids
        client.unmatched_trade_count = unmatched_trade_count
        assert store.get_ctp_preflight_snapshot(SYMBOL)["evidence_complete"] is True

        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=1500.0,
            exectype=bt.Order.Limit,
        )

        assert order.status == bt.Order.Rejected
        assert order.info["error_code"] == expected_error
        assert client.submitted_orders == []
    finally:
        broker.stop()
        store.stop()


def test_async_ctp_reconciliation_queries_off_thread_and_callbacks_on_broker_next():
    main_thread = threading.get_ident()
    client = ManagedAsyncCtpClient()
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
        symbol_routes={SYMBOL: "CTP___FUTURE"},
    )
    broker = store.getbroker()
    callbacks = []

    def notify_reconciliation(snapshot):
        callbacks.append((threading.get_ident(), snapshot))

    try:
        receipt = broker.request_ctp_reconciliation(notify_reconciliation, timeout=0)
        assert receipt["queued"] is True
        assert store.wait_for_commands(2.0) is True
        assert callbacks == []

        broker.next()

        assert len(callbacks) == 1
        callback_thread, first = callbacks[0]
        assert callback_thread == main_thread
        assert client.query_threads
        assert all(thread_id != main_thread for thread_id in client.query_threads)
        assert first["complete"] is True
        assert first["unknown_intent_count"] == 0
        assert first["unmatched_trade_count"] == 0
        assert first["broker_reconciliation_state"]["consecutive_complete_rounds"] == 1

        broker.cerebro = SimpleNamespace(
            runningstrats=[SimpleNamespace(notify_reconciliation=notify_reconciliation)]
        )
        assert broker.request_ctp_reconciliation(timeout=0)["queued"]
        assert store.wait_for_commands(2.0) is True
        broker.next()

        assert len(callbacks) == 2
        assert callbacks[-1][1]["broker_reconciliation_state"]["consecutive_complete_rounds"] == 2
        assert callbacks[0][1]["request_id"] != callbacks[1][1]["request_id"]
    finally:
        store.stop(timeout=2.0)


def _fresh_ctp_quote(*, stale_seconds=0.0, event_age_seconds=0.0, quality="GOOD"):
    recv_time = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=stale_seconds)
    return SimpleNamespace(
        schema_version="ctp.quote.v2",
        symbol=SYMBOL,
        bid_price=1499.0,
        ask_price=1501.0,
        bid_volume=10,
        ask_volume=10,
        recv_monotonic_ns=time.monotonic_ns() - int(stale_seconds * 1_000_000_000),
        recv_time_utc=recv_time.isoformat(),
        event_time_utc=(recv_time - dt.timedelta(seconds=event_age_seconds)).isoformat(),
        connection_generation=3,
        continuity_status="ok",
        stale=False,
        quality=quality,
        quality_flags=(),
    )


@pytest.mark.parametrize(
    ("position_size", "expected_side", "expected_price"),
    [(1.0, "sell", 1498.0), (-1.0, "buy", 1502.0)],
)
def test_ctp_shutdown_uses_fresh_opponent_limit_with_one_tick_protection(
    position_size, expected_side, expected_price
):
    client, store, _data, broker = _started_typed_ctp_stack()
    try:
        assert store.get_ctp_preflight_snapshot(SYMBOL, timeout=0)["evidence_complete"] is True
        client.positions = [
            {
                "instrument": SYMBOL,
                "direction": "long" if position_size > 0 else "short",
                "volume": abs(position_size),
                "price": 1500.0,
            }
        ]
        broker._sync_positions(force=True, raise_errors=True)
        client.live_ticks[SYMBOL] = collections.deque([_fresh_ctp_quote()])
        assert store.poll_tick(SYMBOL) is not None

        orders, missing = broker._submit_known_position_closes()

        assert missing == []
        assert len(orders) == 1
        payload = client.submitted_orders[-1]
        assert payload["side"] == expected_side
        assert payload["order_type"] == "limit"
        assert payload["price"] == pytest.approx(expected_price)
        assert payload["time_in_force"] == "GFD"
        assert payload["offset"] == "close"
    finally:
        broker.stop()
        store.stop()


def test_ctp_shutdown_sends_nothing_when_opponent_quote_is_stale():
    client, store, _data, broker = _started_typed_ctp_stack()
    try:
        assert store.get_ctp_preflight_snapshot(SYMBOL, timeout=0)["evidence_complete"] is True
        client.positions = [
            {
                "instrument": SYMBOL,
                "direction": "short",
                "volume": 1.0,
                "price": 1500.0,
            }
        ]
        broker._sync_positions(force=True, raise_errors=True)
        client.live_ticks[SYMBOL] = collections.deque([_fresh_ctp_quote(stale_seconds=3.0)])
        assert store.poll_tick(SYMBOL) is not None

        orders, missing = broker._submit_known_position_closes()

        assert orders == []
        assert missing == [(SYMBOL, None, "ctp_close_quote_unproven")]
        assert client.submitted_orders == []
    finally:
        broker.stop()
        store.stop()


@pytest.mark.parametrize(
    "quote",
    [
        _fresh_ctp_quote(event_age_seconds=3.0),
        _fresh_ctp_quote(quality="INVALID"),
    ],
)
def test_ctp_shutdown_sends_nothing_when_quote_quality_is_unproven(quote):
    client, store, _data, broker = _started_typed_ctp_stack()
    try:
        assert store.get_ctp_preflight_snapshot(SYMBOL, timeout=0)["evidence_complete"] is True
        client.positions = [
            {
                "instrument": SYMBOL,
                "direction": "short",
                "volume": 1.0,
                "price": 1500.0,
            }
        ]
        broker._sync_positions(force=True, raise_errors=True)
        client.live_ticks[SYMBOL] = collections.deque([quote])
        assert store.poll_tick(SYMBOL) is not None

        orders, missing = broker._submit_known_position_closes()

        assert orders == []
        assert missing == [(SYMBOL, None, "ctp_close_quote_unproven")]
        assert client.submitted_orders == []
    finally:
        broker.stop()
        store.stop()


def test_ctp_shutdown_rejects_ctp_extreme_price_tick_sentinel():
    client, store, _data, broker = _started_typed_ctp_stack()
    try:
        client.query_rows["instruments"][0]["PriceTick"] = 1.0e100
        store.contract_metadata[SYMBOL]["price_tick"] = 1.0e100
        assert store.get_ctp_preflight_snapshot(SYMBOL, timeout=0)["evidence_complete"] is True
        client.positions = [
            {
                "instrument": SYMBOL,
                "direction": "short",
                "volume": 1.0,
                "price": 1500.0,
            }
        ]
        broker._sync_positions(force=True, raise_errors=True)
        client.live_ticks[SYMBOL] = collections.deque([_fresh_ctp_quote()])
        assert store.poll_tick(SYMBOL) is not None

        orders, missing = broker._submit_known_position_closes()

        assert orders == []
        assert missing == [(SYMBOL, None, "ctp_close_quote_unproven")]
        assert client.submitted_orders == []
    finally:
        broker.stop()
        store.stop()


class _ManagedRecoveryOrder:
    def __init__(self, *, size=-1.0, **changes):
        self.data = SimpleNamespace(_name=SYMBOL)
        self.size = size
        self.info = {
            "position_side": "long",
            "offset": "close",
            "exchange_id": "CZCE",
            "quantity_unit": "contracts",
            "execution_cycle_id": "sdk-cycle-1",
            "execution_role": "recovery_exit",
        }
        self.info.update(changes)

    def addinfo(self, **values):
        self.info.update(values)

    def isbuy(self):
        return self.size > 0


def _broker_recovery_plan():
    return {
        "status": "RECOVERABLE",
        "execution_cycle_id": "sdk-cycle-1",
        "recovery_token_sha256": "9" * 64,
        "allowed_cancels": [],
        "allowed_closes": [
            {
                "execution_cycle_id": "sdk-cycle-1",
                "symbol": SYMBOL,
                "exchange_id": "CZCE",
                "position_side": "long",
                "side": "sell",
                "offset": "close",
                "quantity": "1",
                "quantity_unit": "contracts",
            }
        ],
    }


def test_broker_routes_only_the_exact_sdk_recovery_close_identity():
    store = SimpleNamespace(get_strategy_identity_sha256=lambda: "8" * 64)
    broker = BtApiBroker(
        store=store,
        position_mode="dual_side",
        execution_recovery=_broker_recovery_plan(),
    )
    exact = _ManagedRecoveryOrder()

    assert broker._managed_execution_order_error(exact) is None
    assert exact.info["strategy_identity_sha256"] == "8" * 64

    wrong_quantity = _ManagedRecoveryOrder(size=-2.0)
    assert broker._managed_execution_order_error(wrong_quantity)[0] == (
        "execution_recovery_action_mismatch"
    )
    wrong_offset = _ManagedRecoveryOrder(offset="close_today")
    assert broker._managed_execution_order_error(wrong_offset)[0] == "execution_role_mismatch"
    broker._execution_recovery_close_attempted = True
    assert broker._managed_execution_order_error(exact)[0] == "execution_recovery_close_consumed"


def test_broker_recovery_completion_is_delivered_on_broker_drain():
    callbacks = []
    queued = []
    plan = _broker_recovery_plan()
    store = SimpleNamespace(
        enqueue_execution_recovery_completion=lambda **kwargs: queued.append(kwargs)
        or {"queued": True, "receipt_id": 7}
    )
    broker = BtApiBroker(store=store, execution_recovery=plan)

    receipt = broker.request_execution_recovery_completion(
        callbacks.append,
        recovery_token_sha256=plan["recovery_token_sha256"],
    )
    assert receipt["queued"] is True
    assert queued == [{"recovery_token_sha256": "9" * 64}]
    assert callbacks == []

    broker._apply_command_completion(
        {
            "command": "execution_recovery_complete",
            "success": True,
            "response": {
                "completed": True,
                "armed": False,
                "market_data_only": True,
                "recovery_only": False,
                "requires_new_preflight": True,
                "recovery_token_sha256": "9" * 64,
            },
        }
    )

    assert callbacks == [{"completed": True, "status": "completed", "error_code": None}]
    assert broker._execution_recovery_completion_pending is False


def test_concurrent_broker_recovery_completion_queues_once_and_notifies_all():
    entered = threading.Event()
    release = threading.Event()
    queued = []

    def enqueue_once(**kwargs):
        queued.append(kwargs)
        entered.set()
        assert release.wait(2.0)
        return {"queued": True, "receipt_id": "recovery-receipt-1"}

    plan = _broker_recovery_plan()
    broker = BtApiBroker(
        store=SimpleNamespace(enqueue_execution_recovery_completion=enqueue_once),
        execution_recovery=plan,
    )
    callbacks = [[], []]
    results = []
    errors = []
    start = threading.Barrier(3)

    def request_completion(callback_results):
        try:
            start.wait(timeout=2.0)
            results.append(
                broker.request_execution_recovery_completion(
                    callback_results.append,
                    recovery_token_sha256=plan["recovery_token_sha256"],
                )
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [
        threading.Thread(target=request_completion, args=(callback_results,))
        for callback_results in callbacks
    ]
    for thread in threads:
        thread.start()
    start.wait(timeout=2.0)
    assert entered.wait(2.0)
    release.set()
    for thread in threads:
        thread.join(timeout=2.0)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert queued == [{"recovery_token_sha256": "9" * 64}]
    assert results == [results[0], results[0]]

    broker._apply_command_completion(
        {
            "command": "execution_recovery_complete",
            "success": True,
            "response": {
                "completed": True,
                "armed": False,
                "market_data_only": True,
                "recovery_only": False,
                "requires_new_preflight": True,
            },
        }
    )

    assert callbacks == [
        [{"completed": True, "status": "completed", "error_code": None}],
        [{"completed": True, "status": "completed", "error_code": None}],
    ]
    assert broker._execution_recovery_completion_pending is False


class _AliveRecoveryOrder(_ManagedRecoveryOrder):
    ref = 701

    def alive(self):
        return True

    def clone(self):
        return self


def _proven_abort(reason):
    return {
        "aborted": True,
        "market_data_only": True,
        "recovery_only": False,
        "reason": reason,
        "revocation_reason": reason,
        "revoked_generation": 3,
    }


def test_recovery_exit_generic_cancel_aborts_without_native_cancel_dispatch():
    aborts = []
    cancels = []
    store = SimpleNamespace(
        abort_execution_recovery=lambda reason: aborts.append(reason) or _proven_abort(reason),
        cancel_order=lambda order: cancels.append(order),
    )
    broker = BtApiBroker(store=store, execution_recovery=_broker_recovery_plan())
    order = _AliveRecoveryOrder()

    assert broker.cancel(order) is order

    assert aborts == ["execution_recovery_cancel_requires_refresh"]
    assert cancels == []
    assert order.info["cancel_requested_remote"] is False
    assert order.info["recovery_refresh_required"] is True
    assert broker._trading_enabled is False
    assert broker._strategy_paused is True


def test_broker_stop_aborts_recovery_without_cancel_or_flatten_dispatch(monkeypatch):
    aborts = []
    cancels = []
    freezes = []
    store = SimpleNamespace(
        uses_async_commands=True,
        is_connected=True,
        freeze_openings=lambda reason: freezes.append(reason),
        abort_execution_recovery=lambda reason: aborts.append(reason) or _proven_abort(reason),
        cancel_order=lambda order: cancels.append(order),
        enqueue_reconcile=lambda: {"queued": False, "status": "read_only"},
        stop=lambda timeout=None: {"shutdown_state": "INCOMPLETE"},
    )
    broker = BtApiBroker(store=store, execution_recovery=_broker_recovery_plan())
    broker._live_started = True
    order = _AliveRecoveryOrder()
    broker.orders[order.ref] = order
    monkeypatch.setattr(
        broker,
        "_submit_known_position_closes",
        lambda: pytest.fail("recovery stop must not dispatch a flatten order"),
    )

    summary = broker.stop()

    assert freezes == ["broker_stop"]
    assert aborts == ["execution_recovery_broker_stop"]
    assert cancels == []
    assert summary["cancel_requested"] == 0
    assert summary["close_requested"] == 0
    assert summary["status"] == "INCOMPLETE"


def test_broker_stop_cannot_pass_before_sdk_recovery_completion(monkeypatch):
    aborts = []
    broker_holder = {}
    reconcile = {
        "positions": [],
        "open_orders": [],
        "execution_summary": {"unknown_ids": [], "unmatched_trade_count": 0},
    }

    def enqueue_reconcile():
        broker_holder["broker"]._last_reconcile_result = reconcile
        return {"queued": True}

    store = SimpleNamespace(
        uses_async_commands=True,
        is_connected=True,
        freeze_openings=lambda _reason: None,
        abort_execution_recovery=lambda reason: aborts.append(reason) or _proven_abort(reason),
        enqueue_reconcile=enqueue_reconcile,
        wait_for_commands=lambda _timeout: True,
        poll_broker_update=lambda: None,
        stop=lambda timeout=None: {"shutdown_state": "PASS"},
    )
    broker = BtApiBroker(store=store, execution_recovery=_broker_recovery_plan())
    broker_holder["broker"] = broker
    broker._live_started = True
    monkeypatch.setattr(broker, "_reconcile_proves_flat", lambda _result: True)

    summary = broker.stop()

    assert aborts == ["execution_recovery_broker_stop"]
    assert summary["remote_flat_proven"] is True
    assert summary["recovery_completion_proven"] is False
    assert summary["status"] == "INCOMPLETE"
    assert summary["reason"] == "execution_recovery_completion_unproven"

    completed_broker = BtApiBroker(store=store, execution_recovery=_broker_recovery_plan())
    broker_holder["broker"] = completed_broker
    completed_broker._live_started = True
    monkeypatch.setattr(completed_broker, "_reconcile_proves_flat", lambda _result: True)
    completed_broker._last_execution_recovery_completion = {
        "completed": True,
        "status": "completed",
        "error_code": None,
    }

    completed_summary = completed_broker.stop()

    assert aborts == ["execution_recovery_broker_stop"]
    assert completed_summary["recovery_completion_proven"] is True
    assert completed_summary["status"] == "PASS"


class _ObservationOnlyStore:
    """Managed-SDK double with pre-existing external account state."""

    _sdk_mode = True
    uses_async_commands = False
    requires_account_risk = True
    contract_metadata = {}

    def __init__(self, *, uses_async_commands=False):
        self.is_connected = False
        self.uses_async_commands = uses_async_commands
        self._data_feeds = [SimpleNamespace(_name=SYMBOL)]
        self._subscribed_datanames = {SYMBOL}
        self.freeze_reasons = []
        self.submissions = []
        self.cancellations = []
        self.cancel_order_ref_calls = []
        self.fetch_open_orders_calls = 0
        self.risk_baseline_calls = 0
        self.reconcile_calls = 0
        self.enable_openings_calls = 0
        self.events = []
        self.stop_calls = []

    def start(self, broker=None):
        self.is_connected = True

    def get_balance(self, **_kwargs):
        return {"cash": 1_000_000.0, "value": 1_000_000.0}

    def get_positions(self, **_kwargs):
        return [
            {"data_name": SYMBOL, "volume": 2, "price": 1500.0},
            {"data_name": "EXTERNAL-ONLY", "volume": 3, "price": 2000.0},
        ]

    def fetch_open_orders(self, **_kwargs):
        self.fetch_open_orders_calls += 1
        return [{"id": "external-open-order", "data_name": "EXTERNAL-ONLY"}]

    def freeze_openings(self, reason):
        self.freeze_reasons.append(reason)

    def initialize_account_risk_baseline(self):
        self.risk_baseline_calls += 1
        pytest.fail("market-data-only startup must not initialize account-risk execution state")

    def get_reconcile_snapshot(self):
        self.reconcile_calls += 1
        pytest.fail("market-data-only startup must not require execution reconciliation")

    def enable_openings_after_account_risk(self):
        self.enable_openings_calls += 1
        pytest.fail("market-data-only startup must not enable opening orders")

    def submit_order(self, order):
        self.submissions.append(order)
        pytest.fail("market-data-only broker must not submit an order")

    def cancel_order(self, order):
        self.cancellations.append(order)
        pytest.fail("market-data-only broker must not cancel an order")

    def cancel_order_ref(self, order_ref, dataname=None):
        self.cancel_order_ref_calls.append({"order_ref": order_ref, "dataname": dataname})
        pytest.fail("market-data-only broker must not cancel a remote-only order")

    def emit_runtime_event(self, event_type, **kwargs):
        self.events.append((event_type, kwargs))

    def stop(self, timeout=None):
        self.stop_calls.append(timeout)
        self.is_connected = False
        return {"shutdown_state": "PASS"}


class _ObservationOnlyOrder:
    def __init__(self, ref, *, size=1.0):
        self.ref = ref
        self.data = SimpleNamespace(_name=SYMBOL)
        self.size = float(size)
        self.price = 1500.0
        self.created = SimpleNamespace(price=1500.0)
        self.info = {}
        self.status = bt.Order.Created

    def addinfo(self, **values):
        self.info.update(values)

    def alive(self):
        return self.status != bt.Order.Rejected

    def isbuy(self):
        return self.size > 0.0

    def reject(self, _broker):
        self.status = bt.Order.Rejected

    def clone(self):
        return self


class _EmptyCacheObservationOnlyStore(_ObservationOnlyStore):
    """Observation Store whose broker cache cannot see external account state."""

    def get_positions(self, **_kwargs):
        return []

    def fetch_open_orders(self, **_kwargs):
        self.fetch_open_orders_calls += 1
        return []


@pytest.mark.parametrize("uses_async_commands", (False, True))
def test_market_data_only_hydrates_external_state_and_never_mutates_account(
    monkeypatch, uses_async_commands
):
    store = _ObservationOnlyStore(uses_async_commands=uses_async_commands)
    broker = BtApiBroker(
        store=store,
        market_data_only=True,
        sdk_preflight=True,
        validation_enabled=False,
    )

    broker.start()

    cached = broker.get_cached_report_state()
    assert broker._startup_ready is True
    assert broker._trading_enabled is False
    assert cached["cash"] == pytest.approx(1_000_000.0)
    assert cached["positions"][SYMBOL].size == pytest.approx(2.0)
    # The observation cache keeps account positions even when no subscribed
    # feed owns that symbol, so a generic observer can report the full account.
    assert cached["positions"]["EXTERNAL-ONLY"].size == pytest.approx(3.0)
    assert broker._remote_open_orders_snapshot == [
        {"id": "external-open-order", "data_name": "EXTERNAL-ONLY"}
    ]
    assert store.risk_baseline_calls == 0
    assert store.reconcile_calls == 0
    assert store.enable_openings_calls == 0

    submitted = _ObservationOnlyOrder(8001)
    assert broker.submit(submitted) is submitted
    assert submitted.status == bt.Order.Rejected
    assert submitted.info["error_code"] == "market_data_only"

    cancellable = _ObservationOnlyOrder(8002)
    broker.orders[cancellable.ref] = cancellable
    assert broker.cancel(cancellable) is cancellable
    assert cancellable.info["cancel_requested_remote"] is False
    assert cancellable.info["error_code"] == "market_data_only"
    assert store.submissions == []
    assert store.cancellations == []

    broker.enable_trading("test")
    assert broker._trading_enabled is False
    monkeypatch.setattr(
        broker,
        "_submit_known_position_closes",
        lambda: pytest.fail("market-data-only shutdown must not flatten positions"),
    )

    summary = broker.stop()

    assert store.freeze_reasons == ["market_data_only", "market_data_only_stop"]
    assert store.stop_calls
    assert store.submissions == []
    assert store.cancellations == []
    assert summary["status"] == "OBSERVATION_ONLY_NONFLAT"
    assert summary["market_data_only"] is True
    assert summary["cancel_requested"] == 0
    assert summary["close_requested"] == 0
    assert summary["remote_flat_proven"] is False
    assert summary["observed_remote_open_order_count"] == 1
    assert broker.stop() == summary
    assert len(store.stop_calls) == 1


def test_market_data_only_rejects_execution_recovery_before_store_start():
    store = _ObservationOnlyStore()
    broker = BtApiBroker(
        store=store,
        market_data_only=True,
        execution_recovery=_broker_recovery_plan(),
    )

    with pytest.raises(ValueError, match="cannot be combined with execution_recovery"):
        broker.start()

    assert store.is_connected is False
    assert store.freeze_reasons == []
    assert broker._trading_enabled is False


def test_market_data_only_batch_cancel_does_not_refresh_or_cancel_remote_only_order():
    store = _ObservationOnlyStore()
    broker = BtApiBroker(store=store, market_data_only=True, validation_enabled=False)

    broker.start()
    assert broker.orders == {}
    assert broker._remote_open_orders_snapshot == [
        {"id": "external-open-order", "data_name": "EXTERNAL-ONLY"}
    ]
    assert store.fetch_open_orders_calls == 1

    assert broker.batch_cancel() == []

    assert store.fetch_open_orders_calls == 1
    assert store.cancel_order_ref_calls == []
    assert store.cancellations == []
    assert broker._trading_enabled is False
    assert any(event_type == "batch_cancel_rejected_local" for event_type, _kwargs in store.events)

    broker.stop()


@pytest.mark.parametrize(
    (
        "startup_account_state",
        "validation_status",
        "requires_nonflat",
        "expected_status",
        "expected_reason",
    ),
    (
        (
            {
                "nonzero_position_record_count": 2,
                "gross_position_lots": 3,
                "active_orders_count": 1,
            },
            "valid",
            True,
            "OBSERVATION_ONLY_NONFLAT",
            "market_data_only_startup_account_state_nonflat",
        ),
        (
            {
                "nonzero_position_record_count": 0,
                "gross_position_lots": None,
                "active_orders_count": 0,
            },
            "unknown",
            True,
            "OBSERVATION_ONLY_NONFLAT",
            "market_data_only_startup_account_state_unproven",
        ),
        (
            {
                "nonzero_position_record_count": "not-a-count",
                "gross_position_lots": 0,
                "active_orders_count": 0,
            },
            "malformed",
            True,
            "OBSERVATION_ONLY_NONFLAT",
            "market_data_only_startup_account_state_unproven",
        ),
        (
            {
                "nonzero_position_record_count": 0,
                "gross_position_lots": 0,
                "active_orders_count": 0,
            },
            "valid",
            False,
            "OBSERVATION_ONLY",
            "market_data_only_no_order_mutation",
        ),
    ),
)
def test_market_data_only_shutdown_uses_startup_account_state_without_writes(
    startup_account_state,
    validation_status,
    requires_nonflat,
    expected_status,
    expected_reason,
):
    store = _EmptyCacheObservationOnlyStore()
    broker = BtApiBroker(
        store=store,
        market_data_only=True,
        startup_account_state=startup_account_state,
        validation_enabled=False,
    )

    broker.start()

    assert broker.get_cached_report_state()["positions"] == {}
    assert broker._remote_open_orders_snapshot == []

    summary = broker.stop()
    evidence = summary["startup_account_state"]

    assert summary["status"] == expected_status
    assert summary["reason"] == expected_reason
    assert summary["startup_account_state_requires_nonflat"] is requires_nonflat
    assert summary["remote_flat_proven"] is False
    assert summary["remote_position_count"] is None
    assert evidence["provided"] is True
    assert evidence["validation_status"] == validation_status
    assert evidence["is_final_state"] is False
    assert evidence["requires_nonflat"] is requires_nonflat
    assert store.submissions == []
    assert store.cancellations == []
    assert store.cancel_order_ref_calls == []
