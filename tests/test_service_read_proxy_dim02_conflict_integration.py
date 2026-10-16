"""DIM02: a live correction reaches the production read-only Feed path."""

from __future__ import annotations

import multiprocessing
import time

import pytest
import zmq

import backtrader as bt
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_py.service_account import ServiceAccountClient
from bt_api_py.service_market import ServiceMarketClient, ZmqMarketTransportFactory
from bt_api_py.service_runtime import ClientCurveKeys, ServiceClientRuntime, ZmqTransportFactory
from backtrader import TimeFrame
from backtrader.stores.btapistore import BtApiStore
from backtrader.stores.service_read_proxy import (
    ServiceFeedBinding,
    ServiceReadProxy,
    ServiceReadProxyError,
)
from tests import test_service_read_proxy_integration as _fixture


def _conflicting_bar():
    original = _fixture._HISTORY_BARS[1]
    return _fixture.MarketBar(
        original.open_time_utc,
        original.close_time_utc,
        original.open,
        original.high,
        original.low,
        "101.75",
        original.volume,
    )


def _conflict_market_service_process(
    control,
    raw_config,
    registry_path,
    server_keys,
    client_key,
) -> None:
    """Reuse the accepted real host fixture with one changed live bar."""
    original_bars = _fixture._LIVE_BARS
    _fixture._LIVE_BARS = (_conflicting_bar(), *original_bars[1:])
    try:
        _fixture._market_service_process(
            control,
            raw_config,
            registry_path,
            server_keys,
            client_key,
        )
    finally:
        _fixture._LIVE_BARS = original_bars


def _current_feed_bar(feed) -> tuple[float, ...]:
    return tuple(
        float(getattr(feed, line_name)[0])
        for line_name in ("datetime", "open", "high", "low", "close", "volume")
    )


def test_live_conflict_fails_closed_through_service_read_proxy_feed(tmp_path):
    """A same-open-time live revision cannot replace the loaded history bar."""
    context = multiprocessing.get_context("spawn")
    account_rpc, market_rpc, market_pub = _fixture._free_endpoints(3)
    account_server_keys = zmq.curve_keypair()
    market_server_keys = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    guard_directory = tmp_path / "account-session-guard"
    guard_directory.mkdir(parents=True, exist_ok=True)

    raw_account_service = _fixture._service_config(
        service_id=_fixture._ACCOUNT_SERVICE_ID,
        scope_ref=_fixture._ACCOUNT_SCOPE_REF,
        transport_ref=_fixture._ACCOUNT_TRANSPORT_REF,
        instance_id=_fixture._ACCOUNT_INSTANCE_ID,
        bind_ports=["service.account_read", "service.provider_session"],
        options={
            "role": "account_session_worker",
            "account_session_ref": "synthetic-account-session-v1",
        },
        rpc_bind=account_rpc,
        security_ref=_fixture._ACCOUNT_SECURITY_REF,
    )
    raw_market_service = _fixture._service_config(
        service_id=_fixture._MARKET_SERVICE_ID,
        scope_ref=_fixture._MARKET_SCOPE_REF,
        transport_ref=_fixture._MARKET_TRANSPORT_REF,
        instance_id=_fixture._MARKET_INSTANCE_ID,
        bind_ports=["service.market_source"],
        options={"role": "market_hub"},
        rpc_bind=market_rpc,
        security_ref=_fixture._MARKET_SECURITY_REF,
        market_bind=market_pub,
    )

    account_service = None
    market_service = None
    runtime = None
    proxy = None
    store = None
    feed = None
    forced_cleanup: list[str] = []
    cleanup_failures: list[str] = []
    try:
        account_service = _fixture._start_process(
            context,
            _fixture._account_service_process,
            (
                raw_account_service,
                str(tmp_path / "account-registry.sqlite3"),
                str(tmp_path / "account-journal.sqlite3"),
                str(guard_directory),
                account_server_keys,
                client_public,
            ),
            "dim02-conflict-account-service-host",
        )
        account_ready = _fixture._receive(account_service["pipe"])
        assert account_ready[0] == "ready", account_ready
        assert account_ready[1] == account_rpc

        market_service = _fixture._start_process(
            context,
            _conflict_market_service_process,
            (
                raw_market_service,
                str(tmp_path / "market-registry.sqlite3"),
                market_server_keys,
                client_public,
            ),
            "dim02-conflict-market-service-host",
        )
        market_ready = _fixture._receive(market_service["pipe"])
        assert market_ready[0] == "ready", market_ready
        assert market_ready[1:3] == (market_rpc, market_pub)

        config = _fixture.parse_client_config(
            _fixture._client_config(account_rpc, market_rpc, market_pub)
        )
        identity = WireIdentity(
            WireRole.STRATEGY_CLIENT,
            _fixture._CLIENT_PRINCIPAL,
            _fixture._STRATEGY_REF,
        )
        scope_by_ref = {
            _fixture._ACCOUNT_SCOPE_REF: WireScope(
                _fixture._DOMAIN_REF,
                account_ref=_fixture._ACCOUNT_REF,
                strategy_ref=_fixture._STRATEGY_REF,
            ),
            _fixture._MARKET_SCOPE_REF: WireScope(
                _fixture._DOMAIN_REF,
                strategy_ref=_fixture._STRATEGY_REF,
            ),
        }
        peer_by_service = {
            _fixture._ACCOUNT_SERVICE_ID: WireIdentity(
                WireRole.SERVICE,
                "principal-account-service",
                _fixture._ACCOUNT_SERVICE_ID,
            ),
            _fixture._MARKET_SERVICE_ID: WireIdentity(
                WireRole.SERVICE,
                "principal-market-service",
                _fixture._MARKET_SERVICE_ID,
            ),
        }
        account_client_keys = ClientCurveKeys(
            account_server_keys[0],
            client_public,
            client_secret,
        )
        market_client_keys = ClientCurveKeys(
            market_server_keys[0],
            client_public,
            client_secret,
        )
        runtime = ServiceClientRuntime(
            config,
            identity=identity,
            scope_resolver=lambda scope_ref: scope_by_ref[scope_ref],
            peer_resolver=lambda service_id: peer_by_service[service_id],
            transport_factory=ZmqTransportFactory(
                {
                    _fixture._ACCOUNT_SECURITY_REF: account_client_keys,
                    _fixture._MARKET_SECURITY_REF: market_client_keys,
                }
            ),
            requested_operations={
                "store.account": _fixture._ACCOUNT_OPERATIONS,
                "store.market": _fixture._MARKET_OPERATIONS,
            },
        )
        runtime.start()
        account_client = ServiceAccountClient(
            runtime,
            "store.account",
            account_ref=_fixture._ACCOUNT_REF,
            expected_account=_fixture._ACCOUNT_KEY,
            required_coverage=(_fixture._RESOURCE,),
            require_open_orders=True,
        )
        market_client = ServiceMarketClient(
            runtime,
            "store.market",
            _fixture._MARKET_KEY,
            subscriber_factory=ZmqMarketTransportFactory(
                {_fixture._MARKET_SECURITY_REF: market_client_keys}
            ),
            stream_scope=WireScope(_fixture._DOMAIN_REF),
            head_check_interval_seconds=0.25,
        )
        proxy = ServiceReadProxy(
            account_client,
            {
                _fixture._SYMBOL: ServiceFeedBinding(
                    market_client,
                    _fixture._RESOURCE,
                    "unit",
                    "1m",
                    history_start_utc=_fixture._HISTORY_START,
                    history_end_utc=_fixture._HISTORY_END,
                )
            },
            valuation_currency="USD",
            position_mode="net",
            default_history_limit=3,
            clock=lambda: _fixture._PROXY_CLOCK,
        )
        store = BtApiStore(api=proxy)
        feed = store.getdata(
            dataname=_fixture._SYMBOL,
            timeframe=TimeFrame.Minutes,
            compression=1,
            backfill_start=True,
            dispatch_ticks=False,
            dispatch_orderbooks=False,
        )
        cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
        cerebro.adddata(feed, name=_fixture._SYMBOL)
        # Run the normal Feed wrapper so its timezone/run fields are initialized.
        feed._start()

        assert feed.load() is True
        assert feed.load() is True
        assert len(feed) == 2
        assert feed.close[0] == 101.5
        assert not feed._history

        history_before = dict(proxy._history_by_open[_fixture._SYMBOL])
        emitted_open_before = proxy._last_emitted_open[_fixture._SYMBOL]
        emitted_identity_before = proxy._last_emitted_identity[_fixture._SYMBOL]
        pending_before = dict(proxy._pending_bars)
        sequence_before = proxy._last_sequences[_fixture._SYMBOL]
        feed_bar_before = _current_feed_bar(feed)
        assert sequence_before == 0

        conflict = _conflicting_bar()
        history_latest = _fixture._HISTORY_BARS[-1]
        assert conflict.open_time_utc == history_latest.open_time_utc
        assert conflict.close != history_latest.close
        time.sleep(0.4)  # Match the accepted fixture's PUB/SUB join bound.
        published = _fixture._host_command(market_service, "publish", 0)
        assert published == ("published", 0, 1), published

        deadline = time.monotonic() + 8.0
        while True:
            try:
                loaded = feed._load()
            except ServiceReadProxyError as error:
                assert error.code == "HISTORY_LIVE_CONFLICT"
                break
            assert loaded is None, f"conflicting bar was projected: {loaded!r}"
            if time.monotonic() >= deadline:
                pytest.fail("SDK-published conflict did not reach the ServiceReadProxy Feed")
            time.sleep(0.01)

        assert _current_feed_bar(feed) == feed_bar_before
        assert len(feed) == 2
        assert proxy._history_by_open[_fixture._SYMBOL] == history_before
        assert proxy._last_emitted_open[_fixture._SYMBOL] == emitted_open_before
        assert proxy._last_emitted_identity[_fixture._SYMBOL] == emitted_identity_before
        assert proxy._pending_bars == pending_before
        # The valid conflict event is consumed from the ordered stream even
        # though none of its bar values enter the projected history/feed.
        assert proxy._last_sequences[_fixture._SYMBOL] == sequence_before + 1

        feed.stop()
        store.stop()
        assert proxy.is_connected is False
        assert market_client.healthy is False
        assert account_client.healthy is False
        runtime.close()
        assert runtime.state == "closed"
        assert runtime.cleanup_failures == 0
        assert runtime.unregister_uncertainties == 0

        market_status = _fixture._host_command(market_service, "status")
        assert market_status[1]["source_starts"] == 1
        assert market_status[1]["source_stops"] == 1
        assert market_status[1]["readiness"]["active_upstreams"] == 0
        assert market_status[1]["readiness"]["active_registrations"] == 0
        market_closed = _fixture._close_host_normally(market_service)
        assert market_closed[1]["host"] == "closed"
        assert market_closed[1]["source_starts"] == 1
        assert market_closed[1]["source_stops"] == 1

        account_closed = _fixture._close_host_normally(account_service)
        assert account_closed[1]["host"] == "closed"
        assert account_closed[1]["close_calls"] == 1
    finally:
        if feed is not None:
            try:
                feed.stop()
            except Exception as exc:
                cleanup_failures.append(f"feed_stop:{type(exc).__name__}")
        if store is not None:
            try:
                store.stop(timeout=5.0)
            except Exception as exc:
                cleanup_failures.append(f"store_stop:{type(exc).__name__}")
        if proxy is not None:
            try:
                proxy.close()
            except Exception as exc:
                cleanup_failures.append(f"proxy_close:{type(exc).__name__}")
        if runtime is not None and runtime.state != "closed":
            try:
                runtime.close()
            except Exception as exc:
                cleanup_failures.append(f"runtime_close:{type(exc).__name__}")
        for record in (market_service, account_service):
            if record is not None:
                _fixture._bounded_reap_test_process(record, forced_cleanup, cleanup_failures)
        if forced_cleanup or cleanup_failures:
            raise AssertionError(
                "DIM02 integration cleanup was not normal: "
                f"forced={tuple(forced_cleanup)}, failures={tuple(cleanup_failures)}"
            )
