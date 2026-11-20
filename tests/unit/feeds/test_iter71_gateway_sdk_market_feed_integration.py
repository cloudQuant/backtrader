"""Local cross-repository composition of the real SDK market lease and BT Feed.

Only the SDK transport/provider leaves are in-memory. The strategy runtime,
Gateway owner, market client, Gateway facade, and Backtrader Feed are real.
"""

from __future__ import annotations

from dataclasses import replace
from queue import Empty, Queue
from types import SimpleNamespace
from uuid import uuid4
import os
import threading

import backtrader as bt
import pytest
from backtrader.feeds.btapifeed import BtApiFeed
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.service_protocol import (
    WireEnvelope,
    WireIdentity,
    WireMessageKind,
    WireRole,
    WireScope,
)
from bt_api_py.gateway_api import GatewayBtApi
from bt_api_py.gateway_direct_client import GatewayClientRoute
from bt_api_py.gateway_strategy_client import GatewayStrategyClientSession
from bt_api_py.gateway_strategy_market import (
    GatewayMarketClientSettings,
    GatewayMarketSubscriptionSettings,
    ZmqMarketTransportFactory,
)
from bt_api_py.service_config import parse_client_config
from bt_api_py.service_registry import (
    PrincipalGrant,
    ResourceGrant,
    ServiceCapability,
    ServiceRegistry,
)
from bt_api_py.service_runtime import ClientCurveKeys, ZmqTransportFactory
from bt_api_py.service_runtime_thread import ThreadedRuntimeError
from tests.unit.feeds.test_iter63_gateway_market_feed import (
    PEER,
    _gateway_store,
    frame,
    payload as market_payload,
)
from tests.unit.feeds.test_market_tick_adapter_baseline import SOURCE, SUBSCRIPTION


_DOMAIN = "paper:gateway-market"
_CLIENT = WireIdentity(WireRole.STRATEGY_CLIENT, "market-client", "market-strategy")
_ACCOUNT = "market-account"
_INSTANCE = "gateway-local"
_SCOPE_REF = "market-scope-v1"
_TRANSPORT_REF = "market-local"
_DIRECT_OPS = frozenset({"direct.command_status"})
_MARKET_OPS = frozenset(
    {
        "market.subscribe",
        "market.unsubscribe",
        "market.snapshot",
        "market.head",
        "market.read_after",
    }
)


class _LocalRpcTransport:
    def __init__(self, registry, principal):
        self.registry = registry
        self.principal = principal
        self.closed = False

    def request(self, request, *, timeout):
        assert not self.closed
        result = self.registry.handle(self.principal, request)
        return WireEnvelope(
            replace(
                request.header,
                kind=WireMessageKind.REPLY,
                message_id="reply-" + request.header.message_id,
                correlation_id=request.header.message_id,
                identity=PEER,
            ),
            result,
        )

    def close(self):
        self.closed = True


class _LocalSubscriber:
    def __init__(self):
        self.events = Queue()
        self.closed = False
        self.last_receive_receipt = None

    def receive(self, timeout=0):
        if self.closed:
            return None
        try:
            return self.events.get_nowait()
        except Empty:
            return None

    def close(self):
        self.closed = True


class _MarketState:
    def __init__(self, *, epoch="epoch-1"):
        self.epoch = epoch
        self.events = []
        self.subscribers = []
        self.release_calls = 0

    @property
    def head(self):
        return self.events[-1].header.sequence if self.events else 0

    def handlers(self):
        return {
            "market.subscribe": self.subscribe,
            "market.unsubscribe": self.unsubscribe,
            "market.snapshot": self.snapshot,
            "market.head": self.head_reply,
            "market.read_after": self.read_after,
        }

    def subscribe(self, _context, _arguments):
        return {
            "stream_id": SUBSCRIPTION.stream_id,
            "epoch": self.epoch,
            "head": self.head,
            "oldest_sequence": 1,
            "already_subscribed": False,
            "source_descriptor": replace(SOURCE, epoch=self.epoch).to_dict(),
        }

    def unsubscribe(self, _context, _arguments):
        self.release_calls += 1
        return {
            "stream_id": SUBSCRIPTION.stream_id,
            "epoch": self.epoch,
            "head": self.head,
            "upstream_released": True,
        }

    def snapshot(self, _context, _arguments):
        event = self.events[-1] if self.events else None
        return {
            "snapshot_kind": "latest_event",
            "complete": False,
            "stream_id": SUBSCRIPTION.stream_id,
            "epoch": self.epoch,
            "head": self.head,
            "event": None if event is None else _envelope_mapping(event),
        }

    def head_reply(self, _context, _arguments):
        return {
            "stream_id": SUBSCRIPTION.stream_id,
            "epoch": self.epoch,
            "head": self.head,
            "oldest_sequence": 1,
            "latest_observed_at_utc": None,
        }

    def read_after(self, _context, arguments):
        after, limit = arguments["after"], arguments["limit"]
        events = [event for event in self.events if event.header.sequence > after]
        page = events[:limit]
        next_after = page[-1].header.sequence if page else after
        return {
            "stream_id": SUBSCRIPTION.stream_id,
            "epoch": self.epoch,
            "head": self.head,
            "oldest_sequence": 1,
            "after": after,
            "next_after": next_after,
            "limit": limit,
            "has_more": len(events) > limit,
            "gap": False,
            "gap_reason": None,
            "events": [_envelope_mapping(event) for event in page],
        }

    def publish(self, event):
        self.events.append(event)
        for subscriber in tuple(self.subscribers):
            if not subscriber.closed:
                subscriber.events.put(event)


def _envelope_mapping(event):
    from bt_api_base.service_protocol import envelope_to_wire_mapping

    return envelope_to_wire_mapping(event)


def _client_config():
    raw = {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": _CLIENT.actor_ref},
        "clients": {
            "gateway": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "broker.direct_write",
                            "service_id": PEER.actor_ref,
                            "instance_id": _INSTANCE,
                            "scope_ref": _SCOPE_REF,
                            "account_ref": _ACCOUNT,
                            "transport_ref": _TRANSPORT_REF,
                        },
                        {
                            "mount": "store.market",
                            "service_id": PEER.actor_ref,
                            "instance_id": _INSTANCE,
                            "scope_ref": _SCOPE_REF,
                            "transport_ref": _TRANSPORT_REF,
                        },
                    ],
                    "options": {"request_timeout_ms": 500},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _TRANSPORT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {
                        "rpc_connect": "tcp://127.0.0.1:7611",
                        "market_connect": "tcp://127.0.0.1:7612",
                    },
                    "security_profile_ref": "security",
                    "options": {"market_wire_version": 2},
                }
            },
        },
    }
    return parse_client_config(raw)


def _environment(tmp_path, *, name, epoch="epoch-1"):
    service_identity = PEER
    client_identity = _CLIENT
    direct_cap = ServiceCapability(_INSTANCE, "service.direct_write", _DIRECT_OPS)
    market_cap = ServiceCapability(
        _INSTANCE, "service.market_source", _MARKET_OPS, market_wire_version=2
    )
    scope = WireScope(_DOMAIN, account_ref=_ACCOUNT, strategy_ref=_CLIENT.actor_ref)
    resources = (
        ResourceGrant(_INSTANCE, "service.direct_write", _SCOPE_REF, scope, _DIRECT_OPS),
        ResourceGrant(_INSTANCE, "service.market_source", _SCOPE_REF, scope, _MARKET_OPS),
    )
    registry = ServiceRegistry(
        tmp_path / (name + ".sqlite"),
        service_id=service_identity.actor_ref,
        capabilities=(direct_cap, market_cap),
        grants={client_identity.principal_ref: (PrincipalGrant(client_identity, resources),)},
        policy_version="local-policy-v1",
        requirements_version="local-requirements-v1",
    )
    market = _MarketState(epoch=epoch)
    for operation, handler in market.handlers().items():
        registry.register_handler(_INSTANCE, operation, handler)
    for operation in _DIRECT_OPS:
        registry.register_handler(_INSTANCE, operation, lambda _context, _args: {})

    key_bytes = (name.encode("ascii") * 40)[:40]
    curve = ClientCurveKeys(key_bytes, key_bytes, key_bytes)
    return {
        "registry": registry,
        "market": market,
        "curve": curve,
        "rpc": "memory://" + name + "/rpc",
    }


def _patch_transport_leaves(monkeypatch, environments):
    by_secret = {item["curve"].secret_key: item for item in environments}

    def rpc_factory_call(self, profile, _expected_peer, *, _pending=None):
        del _pending
        key = self._profiles[profile["security_profile_ref"]]
        env = by_secret[key.secret_key]
        return _LocalRpcTransport(env["registry"], _CLIENT.principal_ref)

    def market_factory_topic2(self, _binding, _scope, _key):
        key = next(iter(self._profiles.values()))
        subscriber = _LocalSubscriber()
        by_secret[key.secret_key]["market"].subscribers.append(subscriber)
        return subscriber

    monkeypatch.setattr(ZmqTransportFactory, "__call__", rpc_factory_call)
    monkeypatch.setattr(ZmqMarketTransportFactory, "create_topic_v2", market_factory_topic2)


def _api(environment):
    scope = WireScope(
        _DOMAIN,
        account_ref=_ACCOUNT,
        strategy_ref=_CLIENT.actor_ref,
        run_id=uuid4().hex,
    )
    session = GatewayStrategyClientSession(
        _client_config(),
        binding=GatewayCommandBinding("journal-local", _ACCOUNT, _CLIENT.actor_ref, _CLIENT.principal_ref),
        route=GatewayClientRoute("broker.direct_write", PEER.actor_ref, _INSTANCE, _SCOPE_REF, scope, _CLIENT),
        peer=PEER,
        security_profiles={"security": environment["curve"]},
        host=SimpleNamespace(
            save_intent=lambda *_args: None,
            load_intent=lambda *_args: None,
            save_record=lambda *_args: None,
            load_record=lambda *_args: None,
            commit_pre_dispatch=lambda *_args: "marker",
            save_release=lambda *_args: None,
            load_release=lambda *_args: None,
        ),
        requested_operations=_DIRECT_OPS,
        market_settings=GatewayMarketClientSettings(
            {"main": GatewayMarketSubscriptionSettings(SUBSCRIPTION, require_source_descriptor=True)},
            requested_operations=_MARKET_OPS,
        ),
    )
    return GatewayBtApi(session, exchange_name="test", owns_session=True)


def _feed(api):
    store = _gateway_store(None)
    store.gateway_api = api
    store._gateway_strategy_config = store.gateway_strategy_config
    store._gateway_session_generation = 0
    store.gateway_session_generation = 0
    store.is_connected = True
    store.start = lambda data=None: None
    feed = BtApiFeed(
        dataname=SUBSCRIPTION.instrument.instrument_id,
        store=store,
        timeframe=bt.TimeFrame.Ticks,
        backfill_start=False,
        price_tick=1.0,
        qcheck=0.0,
    )
    return store, feed


class _ReconnectStore(SimpleNamespace):
    @property
    def gateway_api(self):
        return self._api

    @gateway_api.setter
    def gateway_api(self, value):
        self._api = value

    @property
    def gateway_session_generation(self):
        return self._gateway_session_generation

    @property
    def is_connected(self):
        return self._connected and self._api is not None

    def gateway_session_state(self):
        if self._force_lost_api is self._api:
            return "LOST"
        return "CONNECTED" if self.is_connected else "UNAVAILABLE"


def _reconnect_store(api):
    base = _gateway_store(None)
    store = _ReconnectStore(
        gateway_strategy_config=base.gateway_strategy_config,
        _gateway_strategy_config=base.gateway_strategy_config,
        _api=api,
        _gateway_session_generation=0,
        _gateway_mode=True,
        _gateway_pid=os.getpid(),
        _connected=True,
        _started=True,
        _gateway_closed=False,
        _gateway_run_lock=SimpleNamespace(held=True),
        _gateway_owns_run_lock=False,
        _gateway_composition_uncertain=False,
        _gateway_reconnect_attempt=0,
        _gateway_reconnect_next=0.0,
        _gateway_reconnect_reason=None,
        _command_shutdown_timeout=2.0,
        _force_lost_api=api,
        _shutdown_state=None,
    )
    store.start = lambda data=None: None
    return store


def _feed_on_store(store):
    feed = BtApiFeed(
        dataname=SUBSCRIPTION.instrument.instrument_id,
        store=store,
        timeframe=bt.TimeFrame.Ticks,
        backfill_start=False,
        price_tick=1.0,
        qcheck=0.0,
    )
    return feed


def _start(api):
    snapshot = api.start(timeout_seconds=3)
    assert snapshot.state == "running" and snapshot.healthy is True
    return snapshot


def _close(environment, api):
    try:
        api.close(timeout_seconds=3)
    finally:
        environment["registry"].close()


def _assert_feed_tick_loaded(feed, expected_price, *, expected_sequence, expected_epoch):
    assert feed.load() is True
    event = feed._gateway_last_data_event
    assert event.cursor.sequence == expected_sequence
    assert event.cursor.epoch == expected_epoch
    assert event.data.last_price == expected_price
    assert feed.lines.open[0] == expected_price
    assert feed.lines.high[0] == expected_price
    assert feed.lines.low[0] == expected_price
    assert feed.lines.close[0] == expected_price
    assert feed.lines.volume[0] == 3.0
    assert feed.lines.datetime[0] > 0


def _assert_trade_unavailable_without_receipt(feed):
    adapter = feed._gateway_market_adapter
    assert adapter._last_receipt is None
    verdict = feed.trade_qualification()
    assert verdict.ok is False
    assert verdict.reasons == ("GATEWAY_REALTIME_UNAVAILABLE",)


def test_real_sdk_lease_and_feed_same_generation_stop_reacquire(tmp_path, monkeypatch):
    env = _environment(tmp_path, name="same-generation")
    _patch_transport_leaves(monkeypatch, [env])
    api = _api(env)
    _start(api)
    store, feed = _feed(api)

    try:
        feed._start()
        first_adapter = feed._gateway_market_adapter
        first_lease = first_adapter._lease_client
        first_owner_client = api._market._leases["main"]
        assert first_lease is not None
        assert first_lease._lease_manager is api._market
        assert first_owner_client is first_lease

        env["market"].publish(frame(1, source=SOURCE))
        _assert_feed_tick_loaded(
            feed, 1500.0, expected_sequence=1, expected_epoch="epoch-1"
        )
        # The fake subscriber deliberately supplies no receive receipt. The
        # payload also has unknown source/receive clocks, so data-line delivery
        # cannot establish the Gateway's receipt/clock qualification contract.
        _assert_trade_unavailable_without_receipt(feed)
        assert first_adapter._projector._client is first_lease
        first_subscriber = env["market"].subscribers[-1]
        first_generation = store._gateway_session_generation

        feed.stop()
        assert first_lease._lease_state == "released"
        assert "main" not in api._market._leases
        with pytest.raises(ThreadedRuntimeError, match="MARKET_LEASE_RELEASED"):
            first_lease.poll()

        feed._start()
        second_adapter = feed._gateway_market_adapter
        second_lease = second_adapter._lease_client
        assert store.gateway_api is api
        assert store._gateway_session_generation == first_generation
        assert second_lease is not first_lease
        assert second_adapter._projector._client is second_lease
        assert api._market._leases["main"] is second_lease
        assert env["market"].subscribers[-1] is not first_subscriber
        assert first_subscriber.closed

        env["market"].publish(
            frame(
                2,
                value=market_payload(
                    last_price=1501.0,
                    bid_price=1500.0,
                    ask_price=1502.0,
                ),
                source=SOURCE,
            )
        )
        # The new SDK cursor first exposes the latest snapshot from before
        # restart, then the post-restart event on its next Feed load.
        _assert_feed_tick_loaded(
            feed, 1500.0, expected_sequence=1, expected_epoch="epoch-1"
        )
        _assert_feed_tick_loaded(
            feed, 1501.0, expected_sequence=2, expected_epoch="epoch-1"
        )
        _assert_trade_unavailable_without_receipt(feed)
        assert second_adapter._projector._client is second_lease
        assert second_lease._lease_state == "active"
    finally:
        feed.stop()
        _close(env, api)


def test_real_sdk_feed_unknown_release_retries_same_handle_then_reconnects(tmp_path, monkeypatch):
    old_env = _environment(tmp_path, name="reconnect-old", epoch="epoch-1")
    new_env = _environment(tmp_path, name="reconnect-new", epoch="epoch-2")
    _patch_transport_leaves(monkeypatch, [old_env, new_env])
    old_api = _api(old_env)
    new_api = _api(new_env)
    _start(old_api)
    store = _reconnect_store(old_api)
    feed = _feed_on_store(store)
    feed._start()
    adapter = feed._gateway_market_adapter
    old_lease = adapter._lease_client
    assert old_lease is old_api._market._leases["main"]
    adapter._timeout_seconds = 0.05

    release_entered = threading.Event()
    allow_release = threading.Event()
    release_finished = threading.Event()
    release_calls = []
    from bt_api_py.gateway_strategy_market import GatewayMarketOwner

    real_release = GatewayMarketOwner._release_market_lease

    def hold_release(owner, name, arguments):
        release_calls.append(name)
        if owner._clients.get(name) is not None:
            release_entered.set()
            if not allow_release.wait(3):
                raise TimeoutError("synthetic owner release barrier timed out")
        result = real_release(owner, name, arguments)
        release_finished.set()
        return result

    monkeypatch.setattr(GatewayMarketOwner, "_release_market_lease", hold_release)
    old_api_close = old_api.close
    close_calls = []

    def counted_close(*, timeout_seconds=5.0):
        close_calls.append(timeout_seconds)
        return old_api_close(timeout_seconds=timeout_seconds)

    old_api.close = counted_close
    try:
        assert not __import__("backtrader.service.gateway_config", fromlist=["x"]).reconnect_gateway_store(
            store, timeout=0.4
        )
        assert release_entered.is_set()
        assert close_calls == []
        assert store.gateway_api is old_api
        assert store.gateway_session_generation == 0
        assert old_api._market._leases["main"] is old_lease
        assert old_lease._lease_state == "closing"
        first_pending = old_lease._pending
        assert first_pending is not None and first_pending[0] == "release"

        allow_release.set()
        assert release_finished.wait(2)
        first_pending[2].result(timeout_seconds=2)
        assert old_lease._pending is first_pending
        store._gateway_reconnect_next = 0.0

        import backtrader.service.gateway_config as gateway_config

        monkeypatch.setattr(gateway_config, "_create_gateway_api", lambda _store: new_api)
        monkeypatch.setattr(gateway_config, "_verify_gateway_execution_parents", lambda *_args: None)
        assert gateway_config.reconnect_gateway_store(store, timeout=3.0)
        assert release_calls == ["main"]
        assert close_calls and store.gateway_api is new_api
        assert store.gateway_session_generation == 1
        assert old_lease._lease_state == "released"
        assert "main" not in old_api._market._leases
        with pytest.raises(ThreadedRuntimeError, match="MARKET_LEASE_RELEASED"):
            old_lease.poll()

        new_event = frame(
            1,
            value=market_payload(
                last_price=1502.0,
                bid_price=1501.0,
                ask_price=1503.0,
            ),
            source=replace(SOURCE, epoch="epoch-2"),
        )
        new_env["market"].publish(new_event)
        _assert_feed_tick_loaded(
            feed, 1502.0, expected_sequence=1, expected_epoch="epoch-2"
        )
        new_lease = adapter._lease_client
        assert new_lease is not None and new_lease is not old_lease
        assert new_lease is new_api._market._leases["main"]
        assert adapter._projector._client is new_lease
        assert new_env["market"].subscribers
        assert new_lease._lease_state == "active"
        _assert_trade_unavailable_without_receipt(feed)
    finally:
        allow_release.set()
        feed.stop()
        _close(new_env, new_api)
        # If the failed first drain did not proceed, the retry above closes old_api.
        if old_api.lifecycle_state != "closed":
            _close(old_env, old_api)
        else:
            old_env["registry"].close()
