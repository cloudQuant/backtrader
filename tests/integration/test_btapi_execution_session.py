"""Offline boundary tests using the real SDK execution session and native Backtrader.

Only transport feeds/backends are fixtures: public BtApi methods, normalization,
journaling, reconciliation, Store, Feed, and Broker all run their real code.
Run with the sibling bt_api_py source on PYTHONPATH during joint development.
"""

import datetime as dt
import json
import time
import uuid
from decimal import Decimal
from queue import Queue
from types import SimpleNamespace

import backtrader as bt
import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import BtApiStore

sdk = pytest.importorskip("bt_api_py")

OKX = "OKX___SWAP"
BINANCE = "BINANCE___SWAP"
INSTRUMENTS = {
    OKX: ("BTC-USDT-SWAP", Decimal("0.01"), Decimal("0.2"), "dual_side"),
    BINANCE: ("BTCUSDT", Decimal("1"), Decimal("0.002"), "dual_side"),
}
ACTUAL_FEE_RATE = Decimal("0.0007")


class TransportFeed:
    """Replace HTTP metadata/configuration responses, without replacing BtApi."""

    def __init__(self, venue):
        self.venue = venue

    def get_exchange_info(self, symbol, **kwargs):
        _, multiplier, _, _ = INSTRUMENTS[self.venue]
        return {
            "symbol": symbol,
            "base_currency": "BTC",
            "quote_currency": "USDT",
            "contract_value": str(multiplier),
            "contract_multiplier": "1",
            "quantity_unit": "contracts" if self.venue == OKX else "base",
            "multiplier": str(multiplier),
            "lot_size": "0.01" if self.venue == OKX else "0.001",
            "quantity_step": "0.01" if self.venue == OKX else "0.001",
            "min_size": "0.01" if self.venue == OKX else "0.001",
            "min_quantity": "0.01" if self.venue == OKX else "0.001",
            "min_notional": 0 if self.venue == OKX else 100,
            "tick_size": "0.01",
            "price_tick": "0.01",
            "status": "live" if self.venue == OKX else "TRADING",
            "settlement_currency": "USDT",
            "margin_rate": "1",
            # Deliberately differs from the actual fee in the fill response.
            "commission_rate": "0.0005",
        }

    def get_position_mode(self, **kwargs):
        return {"position_mode": INSTRUMENTS[self.venue][3]}

    def get_environment_info(self):
        result = {
            "exchange_name": self.venue,
            "environment": "demo",
            "simulated": True,
            "verified": True,
        }
        if self.venue == OKX:
            result["api_region"] = "global"
        return result

    def get_account_config(self, **kwargs):
        mode = INSTRUMENTS[self.venue][3]
        if self.venue == OKX:
            return {
                "position_mode": mode,
                "posMode": "long_short_mode",
                "acctLv": "2",
                "can_trade": True,
                "perm": "read_only,trade",
            }
        return {
            "position_mode": mode,
            "dualSidePosition": True,
            "canTrade": True,
        }

    def disconnect(self):
        pass


class TransportBackend:
    """Deterministic raw transport responses, with no execution/session logic."""

    def __init__(self, journal):
        self.journal = journal
        self.placed = []
        self.queried = []
        self.receipts = {}
        self.private_events = {}
        self.price = Decimal("60000")
        self.timeout_next = False

    def make_order(self, venue, request):
        # The real SDK must persist the intent before reaching the network edge.
        intent = json.loads(self.journal.read_text().splitlines()[-1])
        assert intent["event"] == "intent"
        assert intent["client_order_id"] == request.client_order_id
        assert "bt_order_ref" not in intent
        self.placed.append((venue, request))
        fee = request.quantity * INSTRUMENTS[venue][1] * self.price * ACTUAL_FEE_RATE
        receipt = {
            "symbol": request.symbol,
            "order_id": str(len(self.placed)),
            "client_order_id": request.client_order_id,
            "status": "filled",
            "filled": str(request.quantity),
            "avg_price": str(self.price),
            "side": request.side.value,
            "position_side": request.position_side,
            "offset": request.offset,
            "cumulative_commission": str(fee),
            "commission_currency": "USDT",
        }
        self.receipts[(venue, request.client_order_id)] = receipt
        if self.timeout_next:
            self.timeout_next = False
            # The venue filled the order but its HTTP response was lost.
            raise TimeoutError("response lost after dispatch")
        # A successful REST response is only an ACK.  Model the independent
        # private order stream that authoritatively reports the fill.
        self.private_events[venue].put({"kind": "order", **receipt})
        return dict(receipt)

    def query_order(self, venue, request, **kwargs):
        self.queried.append((venue, request))
        return dict(self.receipts[(venue, request.client_order_id)])

    def get_account_config(self, venue, **kwargs):
        mode = INSTRUMENTS[venue][3]
        if venue == OKX:
            return {
                "data": [
                    {
                        "posMode": "long_short_mode",
                        "acctLv": "2",
                        "can_trade": True,
                        "perm": "read_only,trade",
                    }
                ]
            }
        return {"position_mode": mode, "dualSidePosition": True, "canTrade": True}

    def get_exchange_info(self, venue, symbol, **kwargs):
        return TransportFeed(venue).get_exchange_info(symbol)

    def get_position_mode(self, venue, **kwargs):
        return {"position_mode": INSTRUMENTS[venue][3]}

    def get_account_instruments(self, venue, symbol, **kwargs):
        step = "0.01" if venue == OKX else "0.001"
        return {
            "data": [
                {
                    "symbol": symbol,
                    "instrument_state": "live",
                    "lot_size": step,
                    "min_size": step,
                }
            ]
        }

    def get_leverage_info(self, venue, symbol, *, margin_mode, **kwargs):
        return {
            "data": [
                {
                    "symbol": symbol,
                    "margin_mode": margin_mode,
                    "position_side": side,
                    "leverage": "10",
                }
                for side in ("long", "short")
            ]
        }

    def get_max_size(self, venue, symbol, *, margin_mode, **kwargs):
        return {
            "data": [
                {
                    "symbol": symbol,
                    "margin_mode": margin_mode,
                    "max_buy": "1000",
                    "max_sell": "1000",
                }
            ]
        }

    def get_account(self, venue, *, symbol, **kwargs):
        assert symbol == "USDT"
        return {"currency": "USDT", "cash": "5000", "value": "5000"}

    def get_position(self, venue, **kwargs):
        return []

    def get_open_orders(self, venue, **kwargs):
        return []


@pytest.fixture
def execution_stack(monkeypatch, tmp_path):
    # Empty construction avoids plugin connections. Subscription handlers are
    # also transport boundaries; real BtApi.subscribe still parses/routs topics.
    monkeypatch.setattr("bt_api_py.bt_api._ensure_plugins_loaded", lambda: None)
    subscriptions = []

    def subscribe(data_queue, exchange_params, topics, api):
        subscriptions.extend(topics)

    monkeypatch.setattr(
        "bt_api_py.bt_api.ExchangeRegistry.get_stream_class", lambda *args: subscribe
    )
    # Keep the test transport-free while satisfying the SDK's real pre-network
    # private-credential gate with unique fixture-only values. The SDK ledger
    # registry deliberately persists beyond pytest temp-directory cleanup, so a
    # reused synthetic account identity would collide with a prior test run.
    monkeypatch.setattr("bt_api_py.bt_api.BtApi.init_exchange", lambda self, settings: None)
    journal = tmp_path / "sdk-execution.jsonl"
    fixture_identity = uuid.uuid4().hex
    account_ids = {
        venue: f"offline-{fixture_identity}-{index}" for index, venue in enumerate(INSTRUMENTS)
    }
    exchange_settings = {
        OKX: {
            "environment": "demo",
            "api_region": "global",
            "api_key": f"fixture-okx-public-{fixture_identity}",
            "api_secret": "fixture-okx-secret",
            "passphrase": "fixture-okx-passphrase",
        },
        BINANCE: {
            "environment": "demo",
            "api_key": f"fixture-binance-public-{fixture_identity}",
            "api_secret": "fixture-binance-secret",
        },
    }
    api = sdk.BtApi(
        exchange_kwargs=exchange_settings,
        debug=False,
        execution_config={
            "order_journal": journal,
            "account_currency": "USDT",
            "order_poll_interval": 0.05,
            "required_environments": dict.fromkeys(INSTRUMENTS, "demo"),
            "account_ids": account_ids,
        },
    )
    backend = TransportBackend(journal)
    api._backend = backend
    for venue in INSTRUMENTS:
        api.exchange_kwargs[venue] = dict(exchange_settings[venue])
        api.exchange_feeds[venue] = TransportFeed(venue)
        api.data_queues[venue] = Queue()
    backend.private_events = api.data_queues
    store = BtApiStore(
        api=api,
        config={
            "exchange_kwargs": api.exchange_kwargs,
            "symbol_routes": {row[0]: venue for venue, row in INSTRUMENTS.items()},
            "require_account_risk": True,
        },
    )
    feeds = {}
    broker = None
    try:
        for venue, (symbol, _, _, _) in INSTRUMENTS.items():
            data = store.getdata(
                dataname=symbol,
                historical_bars=[
                    {
                        "datetime": dt.datetime(2026, 9, 1),
                        "open": 60000,
                        "high": 60000,
                        "low": 60000,
                        "close": 60000,
                        "volume": 1,
                        "openinterest": 0,
                    }
                ],
            )
            data._start()
            assert data.load() and data.close[0] == 60000
            assert isinstance(data, BtApiFeed)
            feeds[venue] = data
        broker = store.getbroker(
            position_mode="dual_side",
            position_sync_policy="startup",
            force_refresh_queries=False,
            account_refresh_interval=3600,
            positions_refresh_interval=3600,
            open_orders_refresh_interval=3600,
        )
        broker.start()
        assert isinstance(broker, BtApiBroker)
        assert store._api is api
        assert {row["symbol"] for row in subscriptions} == {row[0] for row in INSTRUMENTS.values()}
        yield SimpleNamespace(api=api, store=store, broker=broker, feeds=feeds, backend=backend)
    finally:
        if broker is not None:
            broker.stop()
        store.stop()
        api.close()


def submit(stack, venue, position_side, offset):
    _, _, quantity, _ = INSTRUMENTS[venue]
    buy = (position_side == "long") == (offset == "open")
    return (stack.broker.buy if buy else stack.broker.sell)(
        None,
        stack.feeds[venue],
        size=float(quantity),
        price=float(stack.backend.price),
        exectype=bt.Order.Limit,
        time_in_force="IOC",
        position_side=position_side,
        offset=offset,
        reduce_only=offset == "close",
    )


def test_native_long_and_short_roundtrips_account_actual_fees(execution_stack):
    stack = execution_stack
    for venue, (symbol, multiplier, quantity, remote_mode) in INSTRUMENTS.items():
        for side in ("long", "short"):
            stack.backend.price = Decimal("60000")
            opening = submit(stack, venue, side, "open")
            assert stack.store.wait_for_commands(1)
            stack.broker.next()
            assert opening.status == bt.Order.Completed, dict(opening.info)
            assert stack.broker.getposition(stack.feeds[venue], side=side).size == pytest.approx(
                float(quantity)
            )
            stack.backend.price = Decimal("60010" if side == "long" else "59990")
            closing = submit(stack, venue, side, "close")
            assert stack.store.wait_for_commands(1)
            stack.broker.next()
            for order, offset in ((opening, "open"), (closing, "close")):
                assert order.status == bt.Order.Completed
                assert abs(order.executed.size) == pytest.approx(float(quantity))
                actual_fee = (
                    quantity * multiplier * Decimal(str(order.executed.price)) * ACTUAL_FEE_RATE
                )
                assert order.executed.comm == pytest.approx(float(actual_fee))
                assert len(order.executed.exbits) == 1
            assert closing.executed.pnl == pytest.approx(float(quantity * multiplier * 10))
            assert stack.broker.getposition(stack.feeds[venue], side=side).size == 0
            placed = stack.backend.placed[-2:]
            assert [request.side.value for _, request in placed] == (
                ["buy", "sell"] if side == "long" else ["sell", "buy"]
            )
            for (_, request), offset in zip(placed, ("open", "close")):
                assert request.symbol == symbol and request.quantity == quantity
                assert request.quantity_unit == ("contracts" if venue == OKX else "base")
                assert request.position_side == side and request.offset == offset
                assert request.position_mode == remote_mode
                assert request.time_in_force == "IOC"
                assert request.reduce_only is (offset == "close")
    summary = stack.store.get_execution_summary()
    assert summary["submit_calls"] == 8 and summary["active_orders"] == 0
    assert not summary["unknown_ids"] and not summary["fee_unresolved_orders"]
    assert len({request.client_order_id for _, request in stack.backend.placed}) == 8

    receipt = stack.broker.request_reconcile()
    assert receipt["queued"] is True
    assert stack.store.wait_for_commands(1)
    stack.broker.next()
    snapshot = stack.broker.get_last_reconcile_result()
    assert (
        snapshot["configured_venues"]
        == snapshot["reconciled_venues"]
        == [
            "binance",
            "okx",
        ]
    )
    assert snapshot["generation"] == snapshot["execution_summary"]["generation"]
    assert snapshot["fencing_epoch"] == snapshot["execution_summary"]["fencing_epoch"]
    assert snapshot["as_of_monotonic_ns"] > 0
    assert snapshot["evidence_complete"] is True
    public_summary = stack.broker.get_execution_summary()
    assert public_summary["generation"] == public_summary["session_generation"] > 0
    assert public_summary["fencing_epoch"] > 0


def test_timeout_reconciles_original_client_id_through_sdk_poll_without_double_fill(
    execution_stack,
):
    stack = execution_stack
    stack.backend.timeout_next = True
    order = submit(stack, OKX, "short", "open")
    assert order.status == bt.Order.Submitted
    assert stack.store.wait_for_commands(1)
    stack.broker.next()
    assert order.alive() and order.info.execution_unknown, dict(order.info)
    assert order.executed.size == 0
    client_id = stack.backend.placed[0][1].client_order_id
    assert stack.store.get_execution_summary()["unknown_ids"] == [client_id]

    # Let the actual SDK scheduler become due; no replacement poll method or
    # mutation of runtime state forces the transition.
    time.sleep(0.06)
    assert stack.store.wait_for_commands(1)
    stack.broker.next()
    assert len(stack.backend.queried) == 1
    venue, query = stack.backend.queried[0]
    assert venue == OKX and query.client_order_id == client_id and query.order_id is None
    assert order.status == bt.Order.Completed and not order.info.execution_unknown

    receipt = stack.backend.receipts[(OKX, client_id)]
    for _ in range(2):
        stack.api.data_queues[OKX].put({"kind": "order", **receipt})
    stack.broker.next()
    stack.broker.next()
    assert abs(order.executed.size) == pytest.approx(0.2)
    assert order.executed.comm == pytest.approx(0.084)
    assert len(order.executed.exbits) == 1
    assert stack.broker.getposition(stack.feeds[OKX], side="short").size == pytest.approx(0.2)
    assert len(stack.backend.placed) == len(stack.backend.queried) == 1
    summary = stack.store.get_execution_summary()
    assert summary["submit_calls"] == 1 and summary["active_orders"] == 0
    assert not summary["unknown_ids"] and not summary["trading_blocked"]
    assert not summary["fee_unresolved_orders"]
