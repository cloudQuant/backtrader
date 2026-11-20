"""Generation-gated reuse of closed Gateway market feed claims."""

from __future__ import annotations

import pytest

from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
from tests.unit.feeds.test_iter63_gateway_market_feed import (
    INSTRUMENT,
    _gateway_store,
    client_with,
    frame,
)


class _Api:
    def __init__(self, client):
        self.client = client

    def market_subscription(self, route, name):
        assert (route, name) == ("test", "main")
        return self.client


def _store(monkeypatch):
    old_client, old_status = client_with(monkeypatch, [frame(1)])
    store = _gateway_store(old_client)
    store.gateway_api = _Api(old_client)
    store.gateway_session_generation = 0
    store.is_connected = True
    feed = object()
    adapter = GatewayMarketAdapter(store, "SA609", feed)
    adapter.start()
    return store, feed, adapter, old_client, old_status


def test_closed_claim_reopens_only_after_new_healthy_store_generation(monkeypatch):
    store, old_feed, old_adapter, old_client, old_status = _store(monkeypatch)
    old_poll = old_client.poll
    poll_calls = []

    def count_old_poll(**kwargs):
        poll_calls.append(True)
        return old_poll(**kwargs)

    monkeypatch.setattr(old_client, "poll", count_old_poll)
    assert old_adapter.poll() is not None
    assert len(poll_calls) == 1

    # The SDK has no per-subscription close on this facade. Keep remote
    # unsubscription uncertainty visible; replacing a local cursor does not
    # claim that the old Gateway registration has already disappeared.
    old_status["unsubscription_uncertain"] = True
    old_adapter.close()
    assert old_client.status()["unsubscription_uncertain"] is True
    assert store._gateway_market_feed_claims["main"] is None
    assert old_adapter._closed is True

    new_client, _new_status = client_with(monkeypatch, [frame(1)])
    new_api = _Api(new_client)
    store.gateway_api = new_api
    store.gateway_session_generation = 1
    store.is_connected = True

    new_feed = object()
    new_adapter = GatewayMarketAdapter(store, "SA609", new_feed)
    assert new_adapter._projector._client is new_client
    assert store._gateway_market_feed_claims["main"] is new_adapter
    assert "main" not in store._gateway_market_feed_claim_tombstones

    new_adapter.start()
    new_event = new_adapter.poll()
    assert new_event is not None and new_event.cursor.sequence == 1

    # A stale reference to the closed adapter cannot adopt the new API or
    # poll the new consumer after the tombstone has been transferred.
    assert old_adapter.poll() is None
    with pytest.raises(RuntimeError, match="GATEWAY_MARKET_ADAPTER_CLOSED"):
        old_adapter.start()
    assert old_adapter.latest_realtime() is None
    assert old_adapter.receipt_for(new_event) is None
    assert old_adapter.matches(store, old_feed, INSTRUMENT) is False
    assert len(poll_calls) == 1


@pytest.mark.parametrize(
    "replacement",
    ("same_api", "same_generation", "disconnected", "missing_generation", "bool_generation"),
)
def test_tombstone_stays_fail_closed_without_complete_reconnect_proof(
    monkeypatch, replacement
):
    store, _feed, adapter, _client, _status = _store(monkeypatch)
    adapter.close()

    new_client, _new_status = client_with(monkeypatch, [])
    if replacement == "same_api":
        store.gateway_session_generation = 1
    elif replacement == "same_generation":
        store.gateway_api = _Api(new_client)
    elif replacement == "disconnected":
        store.gateway_api = _Api(new_client)
        store.gateway_session_generation = 1
        store.is_connected = False
    elif replacement == "missing_generation":
        store.gateway_api = _Api(new_client)
        del store.gateway_session_generation
    else:
        store.gateway_api = _Api(new_client)
        store.gateway_session_generation = True

    with pytest.raises(ValueError, match="GATEWAY_MARKET_SUBSCRIPTION_ALREADY_CLAIMED"):
        GatewayMarketAdapter(store, "SA609", object())

    assert store._gateway_market_feed_claims["main"] is None
    assert store._gateway_market_feed_claim_tombstones["main"][2] is True


def test_concurrent_reopen_after_reconnect_admits_one_new_feed(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    store, _feed, adapter, _old_client, _status = _store(monkeypatch)
    adapter.close()
    new_client, _new_status = client_with(monkeypatch, [])
    store.gateway_api = _Api(new_client)
    store.gateway_session_generation = 1
    store.is_connected = True

    barrier = threading.Barrier(3)

    def construct():
        barrier.wait()
        try:
            return GatewayMarketAdapter(store, "SA609", object())
        except ValueError as error:
            assert str(error) == "GATEWAY_MARKET_SUBSCRIPTION_ALREADY_CLAIMED"
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(construct) for _ in range(2)]
        barrier.wait()
        adapters = [future.result() for future in futures]

    assert sum(adapter is not None for adapter in adapters) == 1
    winner = next(adapter for adapter in adapters if adapter is not None)
    assert store._gateway_market_feed_claims["main"] is winner


def test_same_feed_cannot_create_second_adapter_while_active_or_same_session_after_close(
    monkeypatch,
):
    store, feed, adapter, _client, _status = _store(monkeypatch)

    with pytest.raises(ValueError, match="GATEWAY_MARKET_SUBSCRIPTION_ALREADY_CLAIMED"):
        GatewayMarketAdapter(store, "SA609", feed)
    assert store._gateway_market_feed_claims["main"] is adapter

    adapter.close()
    tombstone = store._gateway_market_feed_claim_tombstones["main"]
    with pytest.raises(ValueError, match="GATEWAY_MARKET_SUBSCRIPTION_ALREADY_CLAIMED"):
        GatewayMarketAdapter(store, "SA609", feed)
    assert store._gateway_market_feed_claims["main"] is None
    assert store._gateway_market_feed_claim_tombstones["main"] is tombstone


def test_orphaned_same_session_tombstone_cannot_be_bypassed_by_missing_claim(monkeypatch):
    store, _feed, adapter, _client, _status = _store(monkeypatch)
    adapter.close()
    tombstone = store._gateway_market_feed_claim_tombstones["main"]
    del store._gateway_market_feed_claims["main"]

    with pytest.raises(ValueError, match="GATEWAY_MARKET_SUBSCRIPTION_ALREADY_CLAIMED"):
        GatewayMarketAdapter(store, "SA609", object())

    assert "main" not in store._gateway_market_feed_claims
    assert store._gateway_market_feed_claim_tombstones["main"] is tombstone


def test_concurrent_construction_with_same_feed_admits_only_one_adapter(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    client, _status = client_with(monkeypatch, [])
    store = _gateway_store(client)
    store.gateway_api = _Api(client)
    feed = object()
    barrier = threading.Barrier(3)

    def construct():
        barrier.wait()
        try:
            return GatewayMarketAdapter(store, "SA609", feed)
        except ValueError as error:
            assert str(error) == "GATEWAY_MARKET_SUBSCRIPTION_ALREADY_CLAIMED"
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(construct) for _ in range(2)]
        barrier.wait()
        adapters = [future.result() for future in futures]

    assert sum(adapter is not None for adapter in adapters) == 1
    winner = next(adapter for adapter in adapters if adapter is not None)
    assert winner._feed is feed
    assert store._gateway_market_feed_claims["main"] is winner
    winner.close()


def test_adapter_operations_fail_closed_after_claim_ownership_is_lost(monkeypatch):
    client, _status = client_with(monkeypatch, [])
    store = _gateway_store(client)
    store.gateway_api = _Api(client)
    feed = object()
    adapter = GatewayMarketAdapter(store, "SA609", feed)
    unexpected_owner = object()
    store._gateway_market_feed_claims["main"] = unexpected_owner
    poll_calls = []
    start_calls = []
    monkeypatch.setattr(client, "start", lambda **kwargs: start_calls.append(kwargs))
    monkeypatch.setattr(client, "poll", lambda **kwargs: poll_calls.append(kwargs))

    with pytest.raises(RuntimeError, match="GATEWAY_MARKET_SUBSCRIPTION_CLAIM_LOST"):
        adapter.start()
    assert adapter.poll() is None
    assert adapter.matches(store, feed, INSTRUMENT) is False
    assert adapter.recovery_reason() == "GATEWAY_MARKET_SUBSCRIPTION_CLAIM_LOST"
    assert poll_calls == [] and start_calls == []

    adapter.close()
    assert store._gateway_market_feed_claims["main"] is unexpected_owner
    assert "main" not in store._gateway_market_feed_claim_tombstones


def test_failed_close_keeps_unique_claim_until_retry_and_new_generation(monkeypatch):
    from types import SimpleNamespace

    from bt_api_py.clock_verification import GatewayClockVerifier

    client, _status = client_with(monkeypatch, [])
    store = _gateway_store(client)
    store.gateway_api = _Api(client)
    store.gateway_session_generation = 0
    store.is_connected = True
    feed = SimpleNamespace(p=SimpleNamespace(event_time_max_age=2.0))
    monkeypatch.setattr(GatewayClockVerifier, "start_background_refresh", lambda self, interval: None)
    stop_results = iter((False, True))
    monkeypatch.setattr(
        GatewayClockVerifier,
        "stop_background_refresh",
        lambda self, **kwargs: next(stop_results),
    )
    adapter = GatewayMarketAdapter(
        store,
        "SA609",
        feed,
        clock_verification={"servers": ["synthetic.invalid"]},
    )
    adapter.start()

    with pytest.raises(RuntimeError, match="GATEWAY_CLOCK_SHUTDOWN_PENDING"):
        adapter.close()
    assert store._gateway_market_feed_claims["main"] is adapter
    assert "main" not in store._gateway_market_feed_claim_tombstones
    assert adapter.matches(store, feed, INSTRUMENT) is True
    with pytest.raises(ValueError, match="GATEWAY_MARKET_SUBSCRIPTION_ALREADY_CLAIMED"):
        GatewayMarketAdapter(store, "SA609", feed)

    adapter.close()
    assert store._gateway_market_feed_claims["main"] is None
    assert store._gateway_market_feed_claim_tombstones["main"][2] is True

    new_client, _new_status = client_with(monkeypatch, [])
    store.gateway_api = _Api(new_client)
    store.gateway_session_generation = 1
    store.is_connected = True
    new_adapter = GatewayMarketAdapter(store, "SA609", feed)
    assert store._gateway_market_feed_claims["main"] is new_adapter
    assert "main" not in store._gateway_market_feed_claim_tombstones
    new_adapter.close()


def test_real_store_reconnect_generation_allows_closed_claim_takeover(tmp_path, monkeypatch):
    import yaml

    from backtrader.live_state import StrategyStateDir
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
    from bt_api_py.service_runtime import ClientCurveKeys
    from tests.unit.stores.test_iter63_gateway_store_config import (
        ReconnectApi,
        _sdk_service_example,
        make_store,
    )
    from bt_api_py.gateway_strategy_config import GatewayStrategyConfig

    strategy_dir = tmp_path / "strategy"
    strategy_dir.mkdir()
    state = StrategyStateDir.initialize(strategy_dir)
    config = yaml.safe_load(
        _sdk_service_example("gateway-strategy-client.example.yaml").read_text(
            encoding="utf-8"
        )
    )
    binding = GatewayCommandBinding(**config["binding"])
    GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    GatewayPendingHost.upgrade_for_cancellation(state.strategy_dir, state.strategy_uuid, binding)
    GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir, state.strategy_uuid, binding, consumer_ref="gexec:" + "a" * 64
    )
    host = GatewayPendingHost.upgrade_for_order_state(
        state.strategy_dir, state.strategy_uuid, binding
    )
    keys = {"security": ClientCurveKeys(b"a" * 40, b"b" * 40, b"c" * 40)}

    old_client, _old_status = client_with(monkeypatch, [])
    new_client, _new_status = client_with(monkeypatch, [])

    class MarketApi(ReconnectApi):
        def __init__(self, client):
            super().__init__()
            self.client = client

        def market_subscription(self, route, name):
            assert (route, name) == ("CTP___FUTURE", "main")
            return self.client

    old_api, new_api = MarketApi(old_client), MarketApi(new_client)
    sessions = iter((old_api, new_api))
    monkeypatch.setattr(
        GatewayStrategyConfig,
        "create_api",
        lambda self, **kwargs: next(sessions),
    )
    store = make_store((config, host, keys))
    store.start()
    feed = object()
    old_adapter = GatewayMarketAdapter(store, "IF2612", feed)
    old_adapter.close()
    assert store._gateway_market_feed_claims["main"] is None

    old_api.state = "failed"
    assert store.gateway_reconnect() is True
    assert store.gateway_api is new_api
    assert store.gateway_session_generation == 1 and store.is_connected

    new_adapter = GatewayMarketAdapter(store, "IF2612", feed)
    assert store._gateway_market_feed_claims["main"] is new_adapter
    assert new_adapter._projector._client is new_client
    new_adapter.close()
    store.stop()
