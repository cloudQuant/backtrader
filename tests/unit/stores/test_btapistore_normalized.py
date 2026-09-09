"""Framework glue over the only public SDK client; execution tests live in bt_api_py."""

import hashlib
import itertools
import threading
import time
from collections import defaultdict, deque
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import backtrader as bt
import pytest

from backtrader.order import OrderBase
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
from tests.fixtures.fake_btapi import make_bar

OKX = "OKX___SWAP"
BINANCE = "BINANCE___SWAP"
CTP = "CTP___FUTURE"
MT5 = "MT5___FOREX"
ROUTES = {"BTC-USDT-SWAP": OKX, "BTCUSDT": BINANCE}


class FakeSdk:
    """Only the public BtApi contract, without another execution implementation."""

    _fence_sequence = itertools.count(1)

    def __init__(self, *, exchange_kwargs=None, execution_config=None, **kwargs):
        self.exchange_kwargs = dict(exchange_kwargs or {v: {} for v in ROUTES.values()})
        self.execution_config = execution_config
        self.kwargs = kwargs
        self.calls = []
        self.events = defaultdict(deque)
        self.positions = defaultdict(list)
        self.open_orders = defaultdict(list)
        self.closed = False
        self.submit_result = None
        self.cancel_result = None
        self.on_submit = None
        self.metadata = {}
        self.sequence = 100
        self.fencing_epoch = next(self._fence_sequence)

    def configure_execution(self, config):
        self.execution_config = config
        self.calls.append(("configure_execution", config))

    def close(self):
        self.closed = True

    def new_client_order_id(self, venue):
        self.sequence += 1
        return str(self.sequence)

    def get_execution_identity(self, venue):
        account_ids = (self.execution_config or {}).get("account_ids", {})
        provider = venue.partition("___")[0]
        if provider in {"OKX", "BINANCE"}:
            fingerprint = hashlib.sha256(f"fixture:{venue}".encode()).hexdigest()
            account_id = f"{provider.lower()}-credential-{fingerprint}"
            authority = "credential_fingerprint"
        else:
            fingerprint = ""
            account_id = account_ids.get(venue, "")
            authority = "declared_account_id"
        identity = {
            "provider": venue.partition("___")[0],
            "environment": self.exchange_kwargs[venue].get("environment", "production"),
            "account_id": account_id,
            "account_authority": authority,
            "exchange_name": venue,
            "strategy_id": (self.execution_config or {}).get("strategy_id", "default"),
            "fencing_epoch": self.fencing_epoch,
        }
        if fingerprint:
            identity["credential_fingerprint"] = fingerprint
        else:
            identity["account_alias"] = account_id
        return identity

    def get_all_balances(self, *, normalized=False):
        assert normalized
        self.calls.append(("get_all_balances",))
        return {
            v: {
                "cash": 0 if v == OKX else 900,
                "value": 1200 if v == OKX else 990,
                "currency": "USDT",
                "exchange_name": v,
            }
            for v in self.exchange_kwargs
        }

    def get_portfolio_balance(self, *, venue_balances):
        self.calls.append(("get_portfolio_balance", deepcopy(venue_balances)))
        return {key: sum(row[key] for row in venue_balances.values()) for key in ("cash", "value")}

    def get_position(self, venue, symbol, *, normalized=False):
        assert normalized
        self.calls.append(("get_position", venue, symbol))
        return deepcopy(self.positions[venue])

    def get_open_orders(self, venue, symbol, *, normalized=False):
        assert normalized
        self.calls.append(("get_open_orders", venue, symbol))
        return deepcopy(self.open_orders[venue])

    def get_position_mode(self, venue, *, normalized=False):
        assert normalized
        return {"exchange_name": venue, "position_mode": "dual_side" if venue == CTP else "net"}

    def get_account_config(self, venue, *, normalized=False):
        assert normalized
        self.calls.append(("get_account_config", venue))
        return {
            "exchange_name": venue,
            "position_mode": "dual_side" if venue == CTP else "net",
            "can_trade": True,
            "trading_permissions": ["trade"],
        }

    def get_environment_info(self, venue):
        environment = self.exchange_kwargs[venue].get("environment", "production")
        return {
            "exchange_name": venue,
            "environment": environment,
            "simulated": environment in {"demo", "testnet"},
            "transport_mode": "direct",
            "verified": True,
        }

    def get_exchange_info(self, venue, symbol, *, normalized=False):
        assert normalized
        return {"symbol": symbol, "exchange_name": venue, **self.metadata.get(symbol, {})}

    def get_funding_rate(self, venue, symbol, *, normalized=False):
        assert normalized
        return {"symbol": symbol, "rate": 0.0001, "next_funding_time": 1788600000}

    def get_order_readiness(
        self,
        venue,
        symbol,
        quantity_native,
        *,
        margin_mode="cross",
        position_mode=None,
        normalized=False,
    ):
        assert normalized
        self.calls.append(
            (
                "get_order_readiness",
                venue,
                symbol,
                quantity_native,
                margin_mode,
                position_mode,
            )
        )
        return {
            "ready": True,
            "definite_failure": False,
            "reasons": [],
            "execution_unproven": True,
            "exchange_name": venue,
            "symbol": symbol,
            "requested_quantity_native": float(quantity_native),
            "position_mode": position_mode,
            "instrument_state": "live",
            "max_buy": 100.0,
            "max_sell": 80.0,
        }

    def subscribe(self, name, topics):
        self.calls.append(("subscribe", name, topics))

    def poll_event(self, venue):
        if not self.events[venue]:
            return None
        event = deepcopy(self.events[venue].popleft())
        event.setdefault("received_monotonic_ns", time.monotonic_ns())
        event.setdefault("clock_domain_id", "fake-sdk-process-monotonic")
        return event

    def make_order(self, venue, request, *, normalized=False):
        assert normalized
        self.calls.append(("make_order", venue, request))
        if self.on_submit:
            self.on_submit(venue, request)
        return {
            "kind": "order",
            "symbol": request.symbol,
            "exchange_name": venue,
            "order_id": "123",
            "client_order_id": request.client_order_id,
            "status": "accepted",
            "filled": 0,
            "terminal_confirmed": False,
            "execution_unknown": False,
            **(self.submit_result or {}),
        }

    async def async_make_order(self, venue, request, *, normalized=False):
        return self.make_order(venue, request, normalized=normalized)

    def cancel_order(self, venue, request, *, normalized=False):
        assert normalized
        self.calls.append(("cancel_order", venue, request))
        return {
            "kind": "order",
            "symbol": request.symbol,
            "exchange_name": venue,
            "order_id": request.order_id,
            "client_order_id": request.client_order_id,
            "status": "submitted",
            "execution_unknown": True,
            "terminal_confirmed": False,
            **(self.cancel_result or {}),
        }

    async def async_cancel_order(self, venue, request, *, normalized=False):
        return self.cancel_order(venue, request, normalized=normalized)

    async def async_query_order(self, venue, request, *, normalized=False):
        assert normalized
        self.calls.append(("async_query_order", venue, request))
        return {
            "kind": "order",
            "symbol": request.symbol,
            "exchange_name": venue,
            "order_id": request.order_id,
            "client_order_id": request.client_order_id,
            "status": "accepted",
            "terminal_confirmed": False,
        }

    def query_order(self, *args, **kwargs):
        raise AssertionError("Store must not implement the SDK pending-order scheduler")

    def get_execution_summary(self):
        return {
            "session_enabled": True,
            "submit_calls": 5,
            "unknown_ids": [],
            "active_orders": 0,
            "trading_blocked": False,
            "fee_unresolved_orders": [],
            "funding_unresolved_orders": [],
            "reconciliation_errors": {},
            "evidence_complete": True,
            "evidence_errors": [],
        }


def store_for(sdk=None, **config):
    settings = {
        "exchange_kwargs": {venue: {"environment": "demo"} for venue in ROUTES.values()},
        "symbol_routes": ROUTES,
        **config,
    }
    account_ids = {
        venue: f"fixture-{venue.lower().replace('___', '-')}-account"
        for venue in settings["exchange_kwargs"]
        if venue.partition("___")[0] not in {"OKX", "BINANCE"}
    }
    if account_ids and "account_ids" not in settings:
        settings["account_ids"] = account_ids
    if sdk is not None:
        sdk.exchange_kwargs = settings["exchange_kwargs"]
    return BtApiStore(provider="btapi", api=sdk, api_cls=FakeSdk, config=settings)


def order(symbol="BTC-USDT-SWAP", size=2, client_id="client123", ref=42, **info):
    return SimpleNamespace(
        data=SimpleNamespace(_name=symbol),
        ref=ref,
        size=size,
        price=60000.0,
        created=SimpleNamespace(price=60000.0),
        pricelimit=None,
        valid=None,
        exectype=OrderBase.Limit,
        tradeid=1,
        isbuy=lambda: True,
        info={"time_in_force": "IOC", "reduce_only": True, "client_order_id": client_id, **info},
    )


def command_response(store, receipt, *, expected_success=True):
    """Wait for one async SDK receipt and return its normalized response."""
    assert receipt["queued"] is True
    assert store.wait_for_commands(1)
    while True:
        completion = store.poll_broker_update()
        assert completion is not None
        if completion.get("receipt_id") == receipt["receipt_id"]:
            assert completion["success"] is expected_success
            return completion["response"]


def test_venue_account_cache_uses_completion_time_and_force_reads(monkeypatch):
    clock = [100.0]
    calls = []
    monkeypatch.setattr("backtrader.stores.btapistore.time.monotonic", lambda: clock[0])

    def get_balances():
        calls.append(clock[0])
        clock[0] += 3.0
        return {"venue": {"currency": "USD", "cash": len(calls), "value": len(calls)}}

    store = BtApiStore(provider="btapi", account_cache_ttl=5)
    monkeypatch.setattr(
        store, "_ensure_api_ready", lambda: SimpleNamespace(get_venue_balances=get_balances)
    )
    first = store.get_venue_balances()
    first["venue"]["cash"] = -1
    clock[0] = 107.0
    assert store.get_venue_balances()["venue"]["cash"] == 1
    assert len(calls) == 1
    assert store.get_venue_balances(force=True)["venue"]["cash"] == 2
    clock[0] += 6
    assert store.get_venue_balances()["venue"]["cash"] == 3


def test_public_source_stop_callback_hook_does_not_expose_the_private_client():
    callbacks = []
    api = SimpleNamespace(set_stop_callback=callbacks.append)
    store = BtApiStore(provider="btapi", api=api)
    callback = lambda: None

    assert store.set_source_stop_callback(callback) is True
    assert callbacks == [callback]
    assert BtApiStore(provider="btapi").set_source_stop_callback(callback) is False


def test_store_holds_the_supplied_sdk_directly_and_configures_execution(tmp_path):
    sdk = FakeSdk()
    journal = str(tmp_path / "orders.jsonl")
    store = store_for(sdk, order_journal=journal, account_currency="USDT")
    store.start()
    assert store._api is sdk
    assert sdk.execution_config == {"order_journal": journal, "account_currency": "USDT"}
    assert not hasattr(store, "_orders") and not hasattr(store, "_journal")
    store.stop()
    assert sdk.closed


def test_stopped_owned_sdk_summary_does_not_reconnect_and_returns_a_copy():
    store = store_for()
    store.start()
    api = store._api
    expected = api.get_execution_summary()
    store.stop()
    summary = store.get_execution_summary()
    assert summary == expected and api.closed and store._api is None
    summary["unknown_ids"].clear()
    assert store.get_execution_summary() == expected
    assert store._api is None and not store.is_connected


def test_owned_sdk_start_failure_retains_execution_audit_without_reconnecting():
    expected = {
        "submit_calls": 0,
        "cancel_calls": 0,
        "unknown_ids": [],
        "active_orders": 0,
        "trading_blocked": False,
    }

    class AccountFailureSdk(FakeSdk):
        instances = []

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.__class__.instances.append(self)

        def get_all_balances(self, *, normalized=False):
            assert normalized
            raise ValueError("account readiness failed")

        def get_execution_summary(self):
            return deepcopy(expected)

        def close(self):
            self.closed = True
            raise RuntimeError("close must not mask account failure")

    store = BtApiStore(
        provider="btapi",
        api_cls=AccountFailureSdk,
        config={
            "exchange_kwargs": {venue: {"environment": "demo"} for venue in ROUTES.values()},
            "symbol_routes": ROUTES,
        },
    )

    with pytest.raises(ValueError, match="account readiness failed"):
        store.start()

    assert len(AccountFailureSdk.instances) == 1
    assert AccountFailureSdk.instances[0].closed is True
    assert store._api is None
    assert store._sdk_configured is False
    assert not store.is_connected and not store._started
    health = store.get_command_health()
    assert health["shutdown_state"] == "FAIL"
    assert health["close_failures"] == 1
    summary = store.get_execution_summary()
    assert summary == expected
    summary["unknown_ids"].append("mutation")
    assert store.get_execution_summary() == expected
    assert len(AccountFailureSdk.instances) == 1


def test_owned_sdk_account_readiness_failure_records_safe_local_close():
    class RegionMismatchSdk(FakeSdk):
        instances = []

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.__class__.instances.append(self)

        def get_all_balances(self, *, normalized=False):
            assert normalized
            raise ValueError("50119 region mismatch")

    store = BtApiStore(
        provider="btapi",
        api_cls=RegionMismatchSdk,
        config={
            "exchange_kwargs": {venue: {"environment": "demo"} for venue in ROUTES.values()},
            "symbol_routes": ROUTES,
        },
    )

    with pytest.raises(ValueError, match="50119 region mismatch"):
        store.start()

    failed_api = RegionMismatchSdk.instances[0]
    health = store.get_command_health()
    assert failed_api.closed is True
    assert store._api is None and store._sdk_configured is False
    assert health["shutdown_state"] == "PASS"
    assert health.get("close_failures", 0) == 0
    assert health.get("close_timeouts", 0) == 0


def test_owned_sdk_partial_connect_failure_is_boundedly_closed_by_stop():
    class ConnectFailureSdk(FakeSdk):
        instances = []

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.close_calls = 0
            self.__class__.instances.append(self)

        def connect(self):
            raise RuntimeError("startup transport failed")

        def close(self):
            self.close_calls += 1
            super().close()

    store = BtApiStore(
        provider="btapi",
        api_cls=ConnectFailureSdk,
        config={
            "exchange_kwargs": {venue: {"environment": "demo"} for venue in ROUTES.values()},
            "symbol_routes": ROUTES,
        },
    )

    with pytest.raises(RuntimeError, match="startup transport failed"):
        store.start()

    failed_api = ConnectFailureSdk.instances[0]
    assert store._api is failed_api
    assert not store.is_connected and not store._started

    health = store.stop(timeout=0.1)

    assert failed_api.closed is True and failed_api.close_calls == 1
    assert store._api is None and store._sdk_configured is False
    assert health["shutdown_state"] == "PASS"
    assert health.get("close_failures", 0) == 0
    assert health.get("close_timeouts", 0) == 0


def test_owned_sdk_partial_connect_failure_close_error_is_failed_and_not_reused():
    class CloseFailureSdk(FakeSdk):
        instances = []

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.__class__.instances.append(self)

        def connect(self):
            if len(self.__class__.instances) == 1:
                raise RuntimeError("original startup failure")

        def close(self):
            self.closed = True
            if self is self.__class__.instances[0]:
                raise RuntimeError("close failure")

    store = BtApiStore(
        provider="btapi",
        api_cls=CloseFailureSdk,
        config={
            "exchange_kwargs": {venue: {"environment": "demo"} for venue in ROUTES.values()},
            "symbol_routes": ROUTES,
        },
    )

    with pytest.raises(RuntimeError, match="original startup failure"):
        store.start()
    failed_api = CloseFailureSdk.instances[0]

    health = store.stop(timeout=0.1)

    assert failed_api.closed is True
    assert health["shutdown_state"] == "FAIL"
    assert health["close_failures"] == 1
    assert store._api is None and store._sdk_configured is False
    try:
        store.start()
        assert store._api is not failed_api
    finally:
        store.stop()


def test_owned_sdk_partial_connect_failure_close_timeout_blocks_reuse():
    close_started = threading.Event()
    release_close = threading.Event()

    class SlowCloseSdk(FakeSdk):
        instances = []

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.__class__.instances.append(self)

        def connect(self):
            if len(self.__class__.instances) == 1:
                raise RuntimeError("original startup timeout failure")

        def close(self):
            if self is self.__class__.instances[0]:
                close_started.set()
                release_close.wait(1)
            self.closed = True

    store = BtApiStore(
        provider="btapi",
        api_cls=SlowCloseSdk,
        config={
            "exchange_kwargs": {venue: {"environment": "demo"} for venue in ROUTES.values()},
            "symbol_routes": ROUTES,
            "command_shutdown_timeout": 0.01,
        },
    )

    with pytest.raises(RuntimeError, match="original startup timeout failure"):
        store.start()
    failed_api = SlowCloseSdk.instances[0]

    health = store.stop(timeout=0.01)

    assert close_started.is_set()
    assert health["shutdown_state"] == "INCOMPLETE"
    assert health["close_timeouts"] == 1
    assert health["restart_blocked_by_close"] is True
    assert health["close_thread_alive"] is True
    assert store._api is None
    with pytest.raises(BtApiStoreError, match="close callback"):
        store.start()

    release_close.set()
    deadline = time.monotonic() + 1
    while store.get_command_health()["close_thread_alive"] and time.monotonic() < deadline:
        time.sleep(0.001)
    try:
        store.start()
        assert store._api is not failed_api
    finally:
        release_close.set()
        store.stop()


def test_explicit_restart_replaces_previous_execution_summary():
    store = store_for()
    store.start()
    first_api = store._api
    first_api.get_execution_summary = lambda: {
        "submit_calls": 17,
        "unknown_ids": ["original-unknown"],
        "active_orders": 1,
    }
    store.stop()
    assert store.get_execution_summary()["submit_calls"] == 17
    try:
        store.start()
        assert store._api is not first_api
        assert store.get_execution_summary() == store._api.get_execution_summary()
        assert store.get_execution_summary()["submit_calls"] == 5
    finally:
        store.stop()


def test_owned_sdk_restart_discards_session_local_order_bindings_and_queues():
    store = store_for()
    first = command_response(store, store.submit_order(order(client_id=None, ref=1)))
    assert first["client_order_id"] == "101" and first["bt_order_ref"] == 1
    assert store._sdk_client_refs and store._sdk_venue_refs and store._sdk_local_refs
    store._sdk_books["BTC-USDT-SWAP"].append(object())
    store._sdk_ticks["BTC-USDT-SWAP"].append(object())
    store._append_sdk_update({"kind": "order"})
    store._sdk_book_drops["BTC-USDT-SWAP"] = 3

    store.stop()

    assert not store._sdk_client_refs
    assert not store._sdk_venue_refs
    assert not store._sdk_local_refs
    assert not store._sdk_books and not store._sdk_ticks and not store._sdk_updates
    assert store.get_orderbook_drop_counts() == {}

    try:
        store.start()
        second = command_response(store, store.submit_order(order(client_id=None, ref=2)))
        assert second["client_order_id"] == "101" and second["bt_order_ref"] == 2
    finally:
        store.stop()


def test_close_failure_keeps_original_execution_audit_readable(monkeypatch):
    sdk = FakeSdk()
    store = store_for(sdk)
    store.start()
    expected = sdk.get_execution_summary()

    def failed_close():
        sdk.closed = True
        raise RuntimeError("transport close failed")

    with monkeypatch.context() as patch:
        patch.setattr(sdk, "close", failed_close)
        health = store.stop()
        assert health["shutdown_state"] == "FAIL"
        assert health["close_failures"] == 1
        assert not store.is_connected and not store._started
        patch.setattr(sdk, "get_execution_summary", lambda: pytest.fail("must use stop snapshot"))
        assert store.get_execution_summary() == expected
    store.stop()


def test_owned_sdk_close_failure_discards_half_closed_api_and_can_restart(monkeypatch):
    store = store_for()
    store.start()
    failed_api = store._api

    def failed_close():
        failed_api.closed = True
        raise RuntimeError("transport close failed")

    with monkeypatch.context() as patch:
        patch.setattr(failed_api, "close", failed_close)
        health = store.stop()
        assert health["shutdown_state"] == "FAIL"
        assert health["close_failures"] == 1

    assert not store.is_connected and not store._started
    assert store._api is None and store._sdk_configured is False
    try:
        store.start()
        assert store.is_connected and store._api is not failed_api
    finally:
        store.stop()


def test_store_constructs_the_only_sdk_with_public_execution_configuration(tmp_path):
    journal = str(tmp_path / "orders.jsonl")
    store = store_for(
        order_journal=journal,
        market_data_only=True,
        order_poll_interval=0.3,
        account_currencies={OKX: "USDT"},
        account_risk_max_age_seconds="2.5",
        book_queue_size=1,
    )
    store.start()
    assert isinstance(store._api, FakeSdk)
    assert store._api.execution_config == {
        "order_journal": journal,
        "market_data_only": True,
        "order_poll_interval": 0.3,
        "account_currencies": {OKX: "USDT"},
        "account_risk_max_age_seconds": "2.5",
    }
    assert "symbol_routes" not in store._api.kwargs
    assert "book_queue_size" not in store._api.kwargs


def test_broker_and_venue_accounts_share_one_sdk_snapshot():
    sdk = FakeSdk()
    store = store_for(sdk)
    store._account_cache_ttl = 5
    store.get_venue_balances()
    assert sum(c[0] == "get_all_balances" for c in sdk.calls) == 1
    assert store.get_balance() == {"cash": 900, "value": 2190}
    assert sum(c[0] == "get_all_balances" for c in sdk.calls) == 1
    store.get_balance(force=True)
    store.get_venue_balances()
    assert sum(c[0] == "get_all_balances" for c in sdk.calls) == 2
    assert sdk.calls[-1][0] == "get_portfolio_balance"


def test_broker_cash_validation_uses_the_order_venue_instead_of_portfolio_cash():
    sdk = FakeSdk()
    store = store_for(sdk)
    store._account_cache_ttl = 60
    for symbol in ROUTES:
        store.set_history(symbol, [make_bar(0, 100, 101, 99, 100)])
    okx_data = store.getdata(dataname="BTC-USDT-SWAP")
    binance_data = store.getdata(dataname="BTCUSDT")
    broker = store.getbroker(force_refresh_queries=False)
    for symbol in ROUTES:
        broker.addcommissioninfo(
            bt.ComminfoFuturesPercent(commission=0, mult=1, margin=1),
            name=symbol,
        )

    okx_data._start()
    binance_data._start()
    assert okx_data.load() and binance_data.load()
    broker.start()
    balance_calls_before_orders = sum(call[0] == "get_all_balances" for call in sdk.calls)
    try:
        # Portfolio cash is 900, but all of it belongs to Binance.
        assert broker.getcash() == 900
        assert store.get_venue_balance("BTC-USDT-SWAP")["cash"] == 0
        assert store.get_venue_balance("BTCUSDT")["cash"] == 900

        okx_order = broker.buy(
            None,
            okx_data,
            size=1,
            price=100,
            exectype=bt.Order.Limit,
            offset="open",
            reduce_only=False,
        )
        assert okx_order.status == bt.Order.Rejected
        assert okx_order.info["error_code"] == "insufficient_cash"
        assert not any(call[0] == "make_order" for call in sdk.calls)

        binance_order = broker.buy(
            None,
            binance_data,
            size=1,
            price=100,
            exectype=bt.Order.Limit,
            offset="open",
            reduce_only=False,
        )
        assert binance_order.status == bt.Order.Submitted
        assert store.wait_for_commands(1)
        submissions = [call for call in sdk.calls if call[0] == "make_order"]
        assert len(submissions) == 1 and submissions[0][1] == BINANCE
        assert (
            sum(call[0] == "get_all_balances" for call in sdk.calls) == balance_calls_before_orders
        )
    finally:
        broker.stop()


@pytest.mark.parametrize(
    "sdk_method,store_method,error_text",
    [
        ("get_position", "get_positions", "positions"),
        ("get_open_orders", "fetch_open_orders", "open orders"),
    ],
)
def test_sdk_account_query_attribute_errors_fail_closed(sdk_method, store_method, error_text):
    def broken_adapter(*_args, **_kwargs):
        raise AttributeError("normalized adapter bug")

    sdk = FakeSdk()
    setattr(sdk, sdk_method, broken_adapter)
    store = store_for(sdk)
    try:
        with pytest.raises(BtApiStoreError, match=error_text):
            getattr(store, store_method)(force=True, raise_errors=True)
    finally:
        store.stop()

    startup_sdk = FakeSdk()
    healthy_method = getattr(startup_sdk, sdk_method)
    setattr(startup_sdk, sdk_method, broken_adapter)
    startup_store = store_for(startup_sdk)
    broker = startup_store.getbroker()
    try:
        with pytest.raises(BtApiStoreError, match=error_text):
            broker.start()
        assert broker._live_started is False
        setattr(startup_sdk, sdk_method, healthy_method)
        broker.start()
        assert broker._live_started is True
    finally:
        broker.stop()


def test_broker_start_account_failure_rolls_back_live_state_and_can_retry():
    sdk = FakeSdk()
    store = store_for(sdk)
    store.start()
    healthy_get_balances = sdk.get_all_balances

    def failed_get_balances(*, normalized=False):
        assert normalized
        raise RuntimeError("account service unavailable")

    sdk.get_all_balances = failed_get_balances
    broker = store.getbroker()
    try:
        with pytest.raises(RuntimeError, match="account service unavailable"):
            broker.start()
        assert broker._live_started is False

        sdk.get_all_balances = healthy_get_balances
        broker.start()
        assert broker._live_started is True
    finally:
        broker.stop()


def test_public_metadata_funding_position_mode_and_summary_pass_through():
    sdk = FakeSdk()
    sdk.metadata["BTC-USDT-SWAP"] = {"quantity_unit": "contracts", "multiplier": 0.01}
    store = store_for(sdk)
    assert store.get_symbol_info("BTC-USDT-SWAP")["multiplier"] == 0.01
    assert store.get_contract_metadata("BTC-USDT-SWAP")["quantity_unit"] == "contracts"
    account_config = store.get_account_config("BTCUSDT")
    assert account_config["position_mode"] == "net"
    assert account_config["can_trade"] is True
    assert ("get_account_config", BINANCE) in sdk.calls
    assert store.get_environment_info("BTCUSDT") == {
        "exchange_name": BINANCE,
        "environment": "demo",
        "simulated": True,
        "transport_mode": "direct",
        "verified": True,
    }
    assert store.get_funding_rate("BTCUSDT")["next_funding_time"] == 1788600000
    assert store.get_execution_summary() == sdk.get_execution_summary()


def test_order_readiness_is_a_thin_routed_sdk_call():
    sdk = FakeSdk()
    store = store_for(sdk)

    result = store.get_order_readiness(
        "BTC-USDT-SWAP",
        2,
        margin_mode="cross",
        position_mode="dual_side",
    )

    assert result["ready"] is True
    assert result["requested_quantity_native"] == 2.0
    assert sdk.calls[-1] == (
        "get_order_readiness",
        OKX,
        "BTC-USDT-SWAP",
        2,
        "cross",
        "dual_side",
    )


@pytest.mark.parametrize(
    "venue,symbol,quantity,unit",
    [
        (OKX, "BTC-USDT-SWAP", 2, "contracts"),
        (BINANCE, "BTCUSDT", 0.02, "base"),
        (CTP, "IF2609", 2, "contracts"),
        (MT5, "EURUSD", 0.2, "lots"),
    ],
)
def test_order_conversion_preserves_native_units_and_all_position_fields(
    venue, symbol, quantity, unit
):
    sdk = FakeSdk()
    store = store_for(sdk, exchange_kwargs={venue: {}}, symbol_routes={symbol: venue})
    result = command_response(
        store,
        store.submit_order(
            order(
                symbol,
                quantity,
                quantity_unit=unit,
                position_side="short",
                offset="close_yesterday",
                position_id="ticket",
                exchange_id="X",
            )
        ),
    )
    request = next(c[2] for c in sdk.calls if c[0] == "make_order")
    assert request.quantity == Decimal(str(quantity)) and request.quantity_unit == unit
    assert request.time_in_force == "IOC" and request.reduce_only
    assert request.position_side == "short" and request.offset == "close_yesterday"
    assert request.position_id == "ticket" and request.exchange_id == "X"
    assert result["external_order_id"] == venue + ":123" and result["bt_order_ref"] == 42


def test_sdk_allocated_client_id_is_bound_before_sending_and_unknown_is_unchanged():
    sdk = FakeSdk()
    sdk.submit_result = {
        "order_id": None,
        "status": "submitted",
        "execution_unknown": True,
        "error_code": "timeout",
    }
    store = store_for(sdk)

    def during_send(venue, request):
        assert store._sdk_client_refs[(venue, request.client_order_id)]["bt_order_ref"] == 42

    sdk.on_submit = during_send
    response = command_response(
        store,
        store.submit_order(order(client_id=None)),
        expected_success=False,
    )
    assert response["execution_unknown"] and response["status"] == "submitted"
    assert response["client_order_id"] == "101" and response["error_code"] == "timeout"
    assert response["external_order_id"] is None and response["bt_order_ref"] == 42
    assert store.poll_broker_update() is None
    assert sum(c[0] == "make_order" for c in sdk.calls) == 1


def test_sdk_allocated_client_id_is_attached_before_unknown_exception():
    class UnknownSubmitError(RuntimeError):
        code = "transport_timeout"
        execution_unknown = True

    sdk = FakeSdk()
    store = store_for(sdk)
    local_order = order(client_id=None)

    def fail_after_accepting(_venue, _request, *, normalized=False):
        assert normalized
        assert local_order.info["client_order_id"] == "101"
        raise UnknownSubmitError("credential=must-not-be-logged")

    sdk.make_order = fail_after_accepting
    receipt = store.submit_order(local_order)
    assert store.wait_for_commands(1)
    completion = store.poll_broker_update()
    assert completion["receipt_id"] == receipt["receipt_id"]
    assert completion["success"] is False
    assert completion["execution_unknown"] is True, completion
    assert completion["error_code"] == "transport_timeout"

    events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
    assert all("must-not-be-logged" not in repr(event) for event in events)


def test_ctp_order_ref_session_and_front_are_preserved_for_cancel_without_exchange_id():
    sdk = FakeSdk()
    sdk.submit_result = {
        "order_id": None,
        "order_ref": "123",
        "front_id": 10,
        "session_id": 20,
        "exchange_id": "CFFEX",
    }
    store = store_for(sdk, exchange_kwargs={CTP: {}}, symbol_routes={"IF2609": CTP})
    response = command_response(store, store.submit_order(order("IF2609", client_id="123")))
    assert response["external_order_id"] is None
    canceled = command_response(
        store,
        store.cancel_order_ref("42", dataname="IF2609"),
        expected_success=False,
    )
    request = next(c[2] for c in sdk.calls if c[0] == "cancel_order")
    assert request.order_id is None and request.order_ref == request.client_order_id == "123"
    assert (request.exchange_id, request.front_id, request.session_id) == ("CFFEX", 10, 20)
    assert canceled["execution_unknown"] and not canceled["terminal_confirmed"]


def test_two_venues_can_share_a_client_and_exchange_order_id_without_cross_routing():
    sdk = FakeSdk()
    store = store_for(sdk)
    command_response(store, store.submit_order(order("BTC-USDT-SWAP", ref=1)))
    command_response(store, store.submit_order(order("BTCUSDT", ref=2)))
    command_response(
        store,
        store.cancel_order_ref(BINANCE + ":123", dataname="BTCUSDT"),
        expected_success=False,
    )
    assert sdk.calls[-1][1] == BINANCE
    sdk.events[OKX].append(
        {
            "kind": "trade",
            "symbol": "BTC-USDT-SWAP",
            "order_id": "123",
            "client_order_id": "client123",
            "trade_id": "1",
            "price": 60001,
            "size": 1,
            "side": "buy",
        }
    )
    sdk.events[BINANCE].append(
        {
            "kind": "trade",
            "symbol": "BTCUSDT",
            "order_id": "123",
            "client_order_id": "client123",
            "trade_id": "1",
            "price": 60002,
            "size": 0.01,
            "side": "buy",
        }
    )
    assert store.poll_broker_update()["bt_order_ref"] == 1
    assert store.poll_broker_update()["bt_order_ref"] == 2
    with pytest.raises(BtApiStoreError, match="unambiguous"):
        store.cancel_order_ref("client123")


def test_positions_keep_all_dual_side_lots_and_native_detail_rows():
    sdk = FakeSdk()
    sdk.positions[CTP] = [
        {
            "symbol": "IF2609",
            "quantity": 2,
            "position_side": "long",
            "price": 4000,
            "today": 2,
            "yesterday": 0,
            "position_id": "today",
            "multiplier": 300,
        },
        {
            "symbol": "IF2609",
            "quantity": 3,
            "position_side": "long",
            "price": 3990,
            "today": 0,
            "yesterday": 3,
            "position_id": "yesterday",
            "multiplier": 300,
        },
        {
            "symbol": "IF2609",
            "quantity": 1,
            "position_side": "short",
            "price": 4010,
            "today": 1,
            "yesterday": 0,
            "position_id": "short",
            "multiplier": 300,
        },
    ]
    store = store_for(sdk, exchange_kwargs={CTP: {}}, symbol_routes={"IF2609": CTP})
    positions = store.get_positions(force=True)
    assert [p["size"] for p in positions] == [2, 3, -1]
    assert [p["position_id"] for p in positions] == ["today", "yesterday", "short"]
    assert positions[1]["yesterday"] == 3 and all(p["multiplier"] == 300 for p in positions)


def test_legacy_ctp_declared_account_identity_remains_valid_without_execution_arm():
    account_id = "fixture-ctp-future-account"
    execution = {"account_ids": {CTP: account_id}}
    sdk = FakeSdk(exchange_kwargs={CTP: {}}, execution_config=execution)
    store = store_for(
        sdk,
        exchange_kwargs={CTP: {}},
        symbol_routes={"IF2609": CTP},
        account_ids={CTP: account_id},
    )

    identity = store._validated_sdk_identity(CTP)

    assert "market_data_only" not in store._sdk_execution_config
    assert identity["account_authority"] == "declared_account_id"
    assert identity["account_id"] == account_id


def test_explicit_ctp_execution_arm_requires_account_fingerprint_authority():
    account_id = "fixture-ctp-future-account"
    execution = {"account_ids": {CTP: account_id}, "market_data_only": False}
    sdk = FakeSdk(exchange_kwargs={CTP: {}}, execution_config=execution)
    store = store_for(
        sdk,
        exchange_kwargs={CTP: {}},
        symbol_routes={"IF2609": CTP},
        account_ids={CTP: account_id},
        market_data_only=False,
    )

    with pytest.raises(BtApiStoreError, match="execution_identity_account_authority_mismatch"):
        store._validated_sdk_identity(CTP)


@pytest.mark.parametrize("position_mode", ["net", "dual_side"])
def test_broker_start_ignores_unrouted_zero_positions_before_feeds_start(position_mode):
    sdk = FakeSdk()
    if position_mode == "dual_side":
        sdk.get_account_config = lambda venue, normalized=False: {
            "exchange_name": venue,
            "position_mode": "dual_side",
            "can_trade": True,
            "trading_permissions": ["trade"],
        }
    sdk.positions[BINANCE] = [
        {
            "symbol": "ETHUSDT",
            "exchange_name": BINANCE,
            "quantity": 0,
            "position_side": "net",
            "price": 0,
        }
    ]
    store = store_for(sdk)
    feeds = [store.getdata(dataname=symbol) for symbol in ROUTES]
    broker = store.getbroker(position_mode=position_mode, position_sync_policy="startup")
    try:
        # Cerebro starts its broker before Feed.start registers the data names.
        broker.start()
        assert store.get_positions(force=True) == []
        assert "ETHUSDT" not in broker.positions
        assert "ETHUSDT" not in broker.long_positions
        assert "ETHUSDT" not in broker.short_positions
        assert all(data not in store._data_feeds for data in feeds)
    finally:
        store.stop()


def test_unrouted_nonzero_position_remains_visible_to_account_preflight():
    sdk = FakeSdk()
    sdk.positions[BINANCE] = [
        {
            "symbol": "ETHUSDT",
            "exchange_name": BINANCE,
            "quantity": 0.001,
            "position_side": "short",
            "position_id": "external-position",
            "price": 2000,
        }
    ]
    store = store_for(sdk)
    try:
        rows = store.get_positions(force=True, raise_errors=True)
        assert len(rows) == 1
        assert rows[0]["symbol"] == "ETHUSDT" and rows[0]["size"] == -0.001
        assert rows[0]["position_id"] == "external-position"
    finally:
        store.stop()
    assert store.supports_position_mode("dual_side")


def test_framework_retains_sdk_trade_source_state_and_canonical_fee_without_interpretation():
    sdk = FakeSdk()
    store = store_for(sdk, exchange_kwargs={CTP: {}}, symbol_routes={"IF2609": CTP})
    command_response(store, store.submit_order(order("IF2609", client_id="123")))
    events = [
        {
            "kind": "order",
            "symbol": "IF2609",
            "client_order_id": "123",
            "order_id": "123",
            "status": "completed",
            "filled": 2,
            "avg_price": None,
            "execution_source": "trades",
            "execution_unknown": False,
            "terminal_confirmed": True,
        },
        {
            "kind": "trade",
            "symbol": "IF2609",
            "client_order_id": "123",
            "order_id": "123",
            "trade_id": "T1",
            "size": 2,
            "price": 59998,
            "position_side": "short",
            "offset": "open",
            "commission": -0.05,
            "commission_normalized": True,
            "commission_currency": "USDT",
        },
    ]
    sdk.events[CTP].extend(deepcopy(events))
    for expected in events:
        actual = store.poll_broker_update()
        assert all(actual[key] == value for key, value in expected.items())
        assert actual["bt_order_ref"] == 42


def test_noncrypto_mixed_events_become_native_objects_and_keep_queue_order():
    sdk = FakeSdk()
    store = store_for(
        sdk, exchange_kwargs={MT5: {}}, symbol_routes={"EURUSD": MT5}, book_queue_size=1
    )
    store.start()
    store.subscribe("EURUSD")
    sdk.events[MT5].extend(
        [
            {
                "kind": "tick",
                "symbol": "EURUSD",
                "timestamp": 1788600000.1,
                "exchange": "MT5",
                "asset_type": "forex",
                "price": 1.1,
                "volume": 0.2,
            },
            {
                "kind": "bar",
                "symbol": "EURUSD",
                "timestamp": 1788600000.2,
                "open": 1.1,
                "high": 1.12,
                "low": 1.09,
                "close": 1.11,
                "volume": 2,
            },
            {
                "kind": "orderbook",
                "symbol": "EURUSD",
                "timestamp": 1788600000.3,
                "bids": [(1.1, 0.2)],
                "asks": [(1.11, 0.3)],
                "sequence": 1,
                "snapshot_or_delta": "snapshot",
                "continuity_status": "continuous",
            },
            {
                "kind": "orderbook",
                "symbol": "EURUSD",
                "timestamp": 1788600000.4,
                "bids": [(1.11, 0.2)],
                "asks": [(1.12, 0.3)],
                "sequence": 2,
                "snapshot_or_delta": "snapshot",
                "continuity_status": "continuous",
            },
        ]
    )
    book = store.poll_orderbook("EURUSD")
    assert book.timestamp == 1788600000.4 and book.bids == [(1.11, 0.2)]
    assert store.poll_tick("EURUSD").asset_type == "forex"
    assert store.poll_live("EURUSD")["close"] == 1.11
    assert (
        "subscribe",
        "MT5___FOREX___EURUSD",
        [{"topic": "depth", "symbol": "EURUSD"}],
    ) in sdk.calls


def test_open_order_identity_supports_native_cancellation_without_local_order():
    sdk = FakeSdk()
    sdk.open_orders[CTP] = [
        {
            "kind": "order",
            "symbol": "IF2609",
            "order_id": "sys1",
            "client_order_id": "123",
            "order_ref": "123",
            "front_id": 10,
            "session_id": 20,
            "exchange_id": "CFFEX",
            "status": "accepted",
        }
    ]
    store = store_for(sdk, exchange_kwargs={CTP: {}}, symbol_routes={"IF2609": CTP})
    assert store.fetch_open_orders(force=True)[0]["external_order_id"] == CTP + ":sys1"
    command_response(
        store,
        store.cancel_order_ref(CTP + ":sys1", dataname="IF2609"),
        expected_success=False,
    )
    request = sdk.calls[-1][2]
    assert request.order_id == "sys1" and request.order_ref == "123" and request.front_id == 10


def test_supplied_sdk_configuration_is_preserved_when_store_does_not_override_it():
    execution = {"order_journal": "existing-session.orders", "account_currency": "CNY"}
    sdk = FakeSdk(exchange_kwargs={CTP: {}}, execution_config=execution)
    store = BtApiStore(provider="btapi", api=sdk)
    data = store.getdata(dataname="IF2609", backfill_start=False)
    assert data.islive() and store.supports_position_mode("dual_side")
    store.start()
    assert store._api is sdk and sdk.execution_config is execution
    assert not any(call[0] == "configure_execution" for call in sdk.calls)


def test_constructor_defaults_debug_off_without_overriding_an_explicit_choice():
    default = store_for()
    default.start()
    assert default._api.kwargs["debug"] is False
    enabled = store_for(debug=True)
    enabled.start()
    assert enabled._api.kwargs["debug"] is True


def test_orderbook_sequence_and_drop_count_survive_sdk_drain():
    sdk = FakeSdk()
    store = store_for(sdk, book_queue_size=1)
    store.start()
    store.subscribe("BTC-USDT-SWAP")
    sdk.events[OKX].extend(
        [
            {
                "kind": "orderbook",
                "symbol": "BTC-USDT-SWAP",
                "timestamp": 1788600000.3,
                "bids": [(100, 1)],
                "asks": [(101, 1)],
                "sequence": 11,
                "snapshot_or_delta": "snapshot",
                "continuity_status": "continuous",
            },
            {
                "kind": "orderbook",
                "symbol": "BTC-USDT-SWAP",
                "timestamp": 1788600000.4,
                "bids": [(100, 1)],
                "asks": [(101, 1)],
                "sequence": 12,
                "snapshot_or_delta": "snapshot",
                "continuity_status": "continuous",
            },
        ]
    )

    book = store.poll_orderbook("BTC-USDT-SWAP")

    assert book.sequence == 12
    assert store.get_orderbook_drop_counts() == {"BTC-USDT-SWAP": 1}


def test_sdk_batch_poll_drains_snapshot_and_requests_orderbook_coalescing():
    sdk = FakeSdk()
    calls = []

    def poll_events(venue, *, max_raw_items, coalesce_market_snapshots):
        calls.append((venue, max_raw_items, coalesce_market_snapshots))
        events = list(sdk.events[venue])
        sdk.events[venue].clear()
        for event in events:
            event.setdefault("received_monotonic_ns", time.monotonic_ns())
            event.setdefault("clock_domain_id", "fake-sdk-process-monotonic")
        return events

    sdk.poll_events = poll_events
    sdk.poll_event = lambda _venue: (_ for _ in ()).throw(
        AssertionError("batch-capable SDK must not use poll_event")
    )
    store = store_for(sdk, book_queue_size=1)
    store.start()
    store.subscribe("BTC-USDT-SWAP")
    sdk.events[OKX].append(
        {
            "kind": "orderbook",
            "symbol": "BTC-USDT-SWAP",
            "timestamp": 1788600000.4,
            "bids": [(100, 1)],
            "asks": [(101, 1)],
            "sequence": 12,
            "snapshot_or_delta": "snapshot",
            "continuity_status": "continuous",
        }
    )

    book = store.poll_orderbook("BTC-USDT-SWAP")

    assert book.sequence == 12
    assert calls == [
        (OKX, 1024, ()),
        (BINANCE, 1024, ()),
    ]


def test_account_push_refreshes_venue_balance_cache_without_rest():
    sdk = FakeSdk()
    # account_cache_ttl is a store constructor argument, not a config entry.
    store = BtApiStore(
        provider="btapi",
        api=sdk,
        api_cls=FakeSdk,
        config={
            "exchange_kwargs": {venue: {"environment": "demo"} for venue in ROUTES.values()},
            "symbol_routes": ROUTES,
        },
        account_cache_ttl=60,
    )
    store.start()
    store.subscribe("BTC-USDT-SWAP")
    stale = store.get_venue_balances()
    assert stale[OKX]["cash"] == 0 and stale[OKX]["value"] == 1200

    sdk.events[OKX].append(
        {
            "kind": "account",
            "exchange_name": OKX,
            "partial": True,
            "currency": "USDT",
            "cash": 500.0,
            "value": 1500.0,
            "balances": [{"currency": "USDT", "cash": 500.0, "value": 1500.0}],
        }
    )
    # WSS pushes are consumed by the market-data drain loop, not by reads.
    store.poll_orderbook("BTC-USDT-SWAP")

    refreshed = store.get_venue_balances()

    assert refreshed[OKX]["cash"] == 500.0 and refreshed[OKX]["value"] == 1500.0
    # Only the pushed venue changed; the other venue keeps its REST snapshot.
    assert refreshed[BINANCE]["cash"] == 900


def test_position_push_is_audited_without_touching_order_or_book_queues():
    sdk = FakeSdk()
    store = store_for(sdk)
    store.start()
    store.subscribe("BTC-USDT-SWAP")
    emitted = []
    store.emit_runtime_event = lambda *a, **k: emitted.append((a, k))

    sdk.events[OKX].append(
        {
            "kind": "position",
            "exchange_name": OKX,
            "symbol": "BTC-USDT-SWAP",
            "size": 1,
            "direction": "long",
        }
    )
    store.poll_orderbook("BTC-USDT-SWAP")

    assert emitted and emitted[0][0] == ("venue_position_update",)
    assert store.poll_broker_update() is None
    assert store.get_orderbook_drop_counts() == {}
