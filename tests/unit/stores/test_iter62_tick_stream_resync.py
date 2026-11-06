"""Iteration 62, D62-38 point 7 (continuity-7): the Store resyncs a restarted tick stream.

SimNow 2026-11-06: after the CTP market-data front disconnected, a long-running
direct process never received another tick. With bt_api_ctp ``1b45673`` the
provider re-logs in and, once its new MD session ticks, declares
``PROVIDER_RESYNC_REQUIRED`` (kept by the SDK owner since ``dec197d4``); the
SDK still needs the consumer's explicit ``accept_resync(acknowledge_data_loss=
True)``. Nothing in Backtrader called it, so the stream stayed in
RECOVERY_REQUIRED for good.

``BtApiStore`` now acknowledges exactly that provider-declared restart for a
tick channel, with a per-symbol backoff (immediately, then 1, 2, 5, 10, 30 s),
never for another recovery code, never on a non-consuming pump and never after
stop. The Feed sees the new epoch as a new scope: the open bar is invalidated
and the first fresh, valid tick of the new session is tradable (D62-38).

The SDK side is real: ``ProviderMarketStreamOwner`` (state machine, recovery
codes, ``accept_resync``) and ``MarketStreamSession`` (the Store's binding
registry). Only the provider session is a scripted stub, and the facade is a
route-only stand-in. Evidence level: UNIT/FAKE (in process, injected clocks;
no CTP library, front, account or network).
"""

from __future__ import annotations

import collections
import dataclasses
import datetime as dt
import logging

import pytest

pytest.importorskip("bt_api_py.service_market_stream_owner")
pytest.importorskip("bt_api_py.market_tick_contracts")

import backtrader as bt  # noqa: E402
from bt_api_base.market_protocol import MarketSourceDescriptor, MarketSubscriptionKey  # noqa: E402
from bt_api_base.market_stream_protocol import MarketStreamState  # noqa: E402
from bt_api_base.market_stream_provider_protocol import (  # noqa: E402
    MarketStreamChannelCapability,
    MarketStreamProviderBinding,
    MarketStreamProviderChannelBinding,
    MarketStreamProviderContractError,
)
from bt_api_base.market_tick_protocol import MarketEventCursor, bind_market_tick_event  # noqa: E402
from bt_api_py.market_stream_session import MarketStreamSession  # noqa: E402
from bt_api_py.service_market_stream_owner import ProviderMarketStreamOwner  # noqa: E402

from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402
from backtrader.stores import btapistore as btapistore_module  # noqa: E402
from backtrader.stores._tick_stream_resync import (  # noqa: E402
    RESYNC_BACKOFF_SECONDS,
    TickStreamResyncPolicy,
)
from backtrader.stores.btapistore import BtApiStore  # noqa: E402
from tests.unit.feeds import test_market_tick_adapter_baseline as typed  # noqa: E402

ROUTE = "CTP___FUTURE"
SYMBOL = typed.INSTRUMENT.native_symbol  # SA609
T0 = dt.datetime(2026, 11, 2, 2, 0, tzinfo=dt.timezone.utc)
MONO0 = 5_000_000_000_000
NS = 1_000_000_000
LATENCY = 0.1
BASELINE = dict(volume_complete=False, volume_quality="BASELINE", delta_volume=0.0)


def _utc_text(moment):
    return moment.isoformat().replace("+00:00", "Z")


def _payload(second, *, generation, price=1500.0, **values):
    """One neutral tick payload of the MD session ``generation`` at ``T0 + second``."""
    event_time = T0 + dt.timedelta(seconds=second)
    fields = dict(
        last_price=price,
        provider_event_time_utc=_utc_text(event_time),
        received_at_utc=_utc_text(event_time + dt.timedelta(seconds=LATENCY)),
        received_monotonic_ns=MONO0 + int((second + LATENCY) * NS),
        provider_sequence=int(second * 10),
        provider_connection_generation=generation,
        provider_subscription_epoch=1,
    )
    fields.update(values)
    return typed._payload(**fields)


class _Channel:
    def __init__(self, binding):
        self.binding = binding
        self.awaiting_resync = False
        self.sequence = 0
        self.payloads = collections.deque()


class _RestartingSession:
    """Scripted provider session shaped like the CTP direct adapter (1b45673).

    ``restart()`` is a confirmed native source restart: the next poll fails
    once, ``channel_recovery_code`` then declares PROVIDER_RESYNC_REQUIRED
    (unless ``declare`` is False) and the channel is held until ``resync``
    binds it to the new MD session (``generation``) under a new epoch whose
    cursor starts again at 1.
    """

    def __init__(self):
        self.generation = 1
        self.channels = {}
        self.restart_pending = False
        self.declare = True
        self.resync_failures = 0
        self.resync_calls = 0
        self.inject = None
        self.bootstrap = None
        self.outage = False

    def _binding(self, request, key, token, epoch):
        source = MarketSourceDescriptor(
            key=key,
            stream_id=key.stream_id,
            epoch=epoch,
            provider="ctp",
            source="ctp.native.md",
            connection_generation=self.generation,
            clock_domain_id="clock-domain-1",
            clock_source_session_id="clock-session-1",
            clock_source="ctp.exchange",
        )
        return MarketStreamProviderChannelBinding(
            token=token,
            request=request,
            key=key,
            source=source,
            initial_cursor=None,
            initial_events=(),
            recovery_required=False,
        )

    def subscribe(self, request):
        key = MarketSubscriptionKey(
            source_ref="ctp.md.front",
            entitlement_ref="test-entitlement",
            instrument=request.instrument,
            channel="tick",
        )
        binding = self._binding(request, key, object(), "epoch-1")
        self.channels[binding.token] = _Channel(binding)
        return binding

    def push(self, payload):
        for channel in self.channels.values():
            channel.payloads.append(payload)

    def lose(self):
        """The source was lost and is being replaced (bt_api_ctp, SimNow 2026-11-07).

        Every poll fails and nothing is declared until ``restart`` (the SDK
        owner reports ``PROVIDER_POLL_FAILED``, which is never resynced).
        """
        self.outage = True
        for channel in self.channels.values():
            channel.payloads.clear()

    def restart(self):
        """The provider confirmed a new MD session (CTP: re-login after 4097)."""
        self.generation += 1
        self.restart_pending = True
        self.outage = False

    def poll(self, *, timeout_ms, max_events):
        if self.inject is not None:
            inject, self.inject = self.inject, None
            return inject(self)
        if self.outage:
            raise MarketStreamProviderContractError("MARKET_STREAM_PROVIDER_EVENT_INVALID")
        if self.restart_pending:
            self.restart_pending = False
            for channel in self.channels.values():
                channel.awaiting_resync = True
                channel.payloads.clear()  # nothing of the lost session survives
            raise MarketStreamProviderContractError("MARKET_STREAM_PROVIDER_EVENT_INVALID")
        events = []
        for channel in self.channels.values():
            while not channel.awaiting_resync and channel.payloads and len(events) < max_events:
                payload = channel.payloads.popleft()
                channel.sequence += 1
                source = channel.binding.source
                events.append(
                    bind_market_tick_event(
                        payload,
                        source,
                        MarketEventCursor(source.stream_id, source.epoch, channel.sequence),
                    )
                )
        return tuple(events)

    def channel_recovery_code(self, binding):
        channel = self.channels.get(getattr(binding, "token", None))
        if channel is None or channel.binding is not binding or not self.declare:
            return None
        return "PROVIDER_RESYNC_REQUIRED" if channel.awaiting_resync else None

    def resync(self, binding, *, acknowledge_data_loss):
        assert acknowledge_data_loss is True
        self.resync_calls += 1
        if self.resync_failures:
            self.resync_failures -= 1  # still recovering: no current source
            raise MarketStreamProviderContractError("MARKET_STREAM_PROVIDER_SESSION_INVALID")
        channel = self.channels[binding.token]
        rebound = self._binding(
            binding.request, binding.key, binding.token, f"epoch-{self.resync_calls + 1}"
        )
        channel.sequence = 0
        if self.bootstrap is not None:
            source = rebound.source
            cursor = MarketEventCursor(source.stream_id, source.epoch, 1)
            event = bind_market_tick_event(self.bootstrap, source, cursor)
            self.bootstrap = None
            rebound = dataclasses.replace(rebound, initial_cursor=cursor, initial_events=(event,))
            channel.sequence = 1
        channel.binding = rebound
        channel.awaiting_resync = False
        return rebound

    def unsubscribe(self, binding):
        return True

    def close(self):
        return True


class _Adapter:
    def __init__(self, session):
        self.session = session

    def capabilities(self):
        return (MarketStreamChannelCapability(channel="tick", max_depth=None),)

    def open_session(self, *, wake_callback):
        return self.session


class _Router:
    def __init__(self, session):
        self.session = session

    def resolve_request(self, route, request):
        binding = MarketStreamProviderBinding(
            instrument=route.instrument, adapter=_Adapter(self.session)
        )
        return binding, binding.adapter.capabilities()[0]


class _Facade:
    """Route-only facade stand-in: one pinned CTP route and the SDK stream owner."""

    def __init__(self):
        self.route_client = object()
        self.exchange_feeds = {ROUTE: self.route_client}
        self._selected_route_clients = {ROUTE: self.route_client}
        self._market_runtime_factory = None
        self.owner = None

    def _selected_provider_route(self, exchange_name):
        return (self.exchange_feeds[exchange_name], None)

    def market_stream(self):
        return self.owner


class _Mono:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def env(request, monkeypatch):
    """A real BtApiStore, its SDK binding registry and the real SDK stream owner.

    Indirect parameter ``"gateway"``: the Store is configured with a Gateway
    market runtime factory (the factory itself is never used here).
    """
    session = _RestartingSession()
    api = _Facade()
    api.owner = ProviderMarketStreamOwner(api, router=_Router(session))
    options = {}
    if getattr(request, "param", None) == "gateway":
        options["market_runtime_factory"] = object()
    store = BtApiStore(config={"exchange_kwargs": {ROUTE: {}}}, autostart=False, **options)
    # Route facts come from the configured Store in production; fixed here.
    store._market_stream_adapter = MarketStreamSession(
        store._market_stream_queue_size,
        configured_orderbook_depth=None,
        error_type=btapistore_module.BtApiStoreError,
        missing_dependency_error_type=btapistore_module.BtApiMissingDependencyError,
        resolve_route_context=lambda _api, _symbol: (ROUTE, typed.INSTRUMENT),
        assert_route_current=lambda _api: None,
        mark_unavailable=store._mark_market_stream_unavailable,
        observe_queue_depth=store._observe_market_stream_queue_depth,
        on_binding_closed=store._project_market_stream_binding_closed,
        on_close_failure=store._project_market_stream_close_failure,
        sanitize_exception=store.sanitize_exception,
        safe_exception_code=store._safe_exception_code,
    )
    mono = _Mono()
    # Keep the Store's own enable decision; only the clock is injected.
    configured = getattr(store, "_tick_stream_resync", None)
    store._tick_stream_resync = TickStreamResyncPolicy(
        enabled=getattr(configured, "enabled", True), monotonic=mono
    )
    store._api = api
    store._connected = True
    store._started = True
    monkeypatch.setattr(store, "_ensure_api_ready", lambda: api)
    assert store._market_stream_adapter.start_subscription(SYMBOL, channel="tick", api=api)
    records = []

    class _Records(logging.Handler):
        def emit(self, record):
            records.append((record.levelno, record.getMessage()))

    handler = _Records(level=logging.DEBUG)
    logger = btapistore_module.logger
    monkeypatch.setattr(logger, "level", logging.DEBUG)
    logger.addHandler(handler)
    yield store, session, mono, records
    logger.removeHandler(handler)


def _health(store):
    return store.get_stream_health(SYMBOL)


def _warnings(records):
    return [message for level, message in records if level >= logging.WARNING]


# -- the Store ----------------------------------------------------------------


def test_declared_restart_is_resynced_once_and_ticks_resume_on_a_new_epoch(env):
    store, session, _mono, records = env
    session.push(_payload(10, generation=1))
    first = store.poll_tick(SYMBOL)
    assert first.cursor.epoch == "epoch-1" and first.source.connection_generation == 1

    session.restart()
    assert store.poll_tick(SYMBOL) is None  # the restart's failed poll: resynced at once
    assert session.resync_calls == 1
    health = _health(store)
    assert health["tick_sdk_resyncs"] == 1
    assert health.get("tick_sdk_resync_failures", 0) == 0
    # The Store's loss evidence is cumulative; the resync does not clear it.
    assert health["stale"] is True
    assert health["stale_reason"] == "sdk_market_stream_resync_required"

    session.push(_payload(20, generation=2, **BASELINE))
    tick = store.poll_tick(SYMBOL)
    assert tick is not None
    assert tick.cursor.epoch != "epoch-1" and tick.cursor.sequence == 1
    assert tick.source.connection_generation == 2

    for second in (21, 22):
        session.push(_payload(second, generation=2))
        assert store.poll_tick(SYMBOL) is not None
    assert session.resync_calls == 1  # exactly once for one restart
    assert _health(store)["tick_sdk_resyncs"] == 1
    warnings = _warnings(records)
    assert len(warnings) == 1
    assert SYMBOL in warnings[0] and "PROVIDER_RESYNC_REQUIRED" in warnings[0]


def test_a_bootstrap_tick_delivered_with_the_resync_is_returned(env):
    store, session, _mono, _records = env
    session.bootstrap = _payload(20, generation=2, **BASELINE)
    session.restart()
    tick = store.poll_tick(SYMBOL)  # the resync result carries the new epoch's first tick
    assert session.resync_calls == 1
    assert tick is not None and tick.cursor.sequence == 1
    assert tick.source.connection_generation == 2
    health = _health(store)
    assert health["tick_sdk_resyncs"] == 1
    assert health["tick_ingress"] == 1
    assert health["tick_last_enqueued_event_id"].endswith(":1")


def _skip_a_sequence(session):
    channel = next(iter(session.channels.values()))
    source = channel.binding.source
    payload = _payload(30, generation=session.generation)
    channel.sequence += 2  # a cursor gap inside the same epoch
    return (
        bind_market_tick_event(
            payload, source, MarketEventCursor(source.stream_id, source.epoch, channel.sequence)
        ),
    )


def _foreign_source(session):
    channel = next(iter(session.channels.values()))
    source = dataclasses.replace(channel.binding.source, epoch="epoch-foreign")
    return (
        bind_market_tick_event(
            _payload(30, generation=session.generation),
            source,
            MarketEventCursor(source.stream_id, source.epoch, 1),
        ),
    )


def _undeclared_restart(session):
    session.declare = False
    session.restart_pending = True
    return session.poll(timeout_ms=0, max_events=1)


@pytest.mark.parametrize(
    ("inject", "code"),
    [
        (_undeclared_restart, "PROVIDER_POLL_FAILED"),
        (_skip_a_sequence, "MARKET_CURSOR_DISCONTINUITY"),
        (_foreign_source, "EVENT_SOURCE_MISMATCH"),
    ],
)
def test_other_recovery_codes_are_never_resynced(env, inject, code):
    store, session, mono, records = env
    session.push(_payload(10, generation=1))
    assert store.poll_tick(SYMBOL) is not None
    session.inject = inject
    store.poll_tick(SYMBOL)
    stream = store._market_stream_adapter._find_binding(SYMBOL, "tick")
    result = stream["stream"].poll(stream["subscription"], timeout_ms=0, max_events=1)
    assert result.state is MarketStreamState.RECOVERY_REQUIRED
    assert result.recovery_code == code
    for _ in range(5):
        mono.now += 60.0
        assert store.poll_tick(SYMBOL) is None
    assert session.resync_calls == 0
    health = _health(store)
    assert health["stale"] is True and health["continuity_status"] == "gap"
    assert "tick_sdk_resyncs" not in health
    assert _warnings(records) == []


def test_failed_resync_keeps_the_gap_and_retries_with_backoff(env):
    store, session, mono, records = env
    session.resync_failures = 3  # the new MD session is not yet usable
    session.restart()
    start = mono.now
    store.poll_tick(SYMBOL)
    assert session.resync_calls == 1  # immediately
    attempts_at = [0.0]
    for offset in (0.5, 0.99, 1.0, 2.9, 3.0, 7.9, 8.0):
        mono.now = start + offset
        store.poll_tick(SYMBOL)
        if session.resync_calls > len(attempts_at):
            attempts_at.append(offset)
        if session.resync_calls < 4:
            health = _health(store)
            assert health["stale"] is True
            assert health["stale_reason"] == "sdk_market_stream_resync_required"
            assert health["continuity_status"] == "gap"
    # immediate, then 1 s, 2 s and 5 s after the previous attempt.
    assert attempts_at == [0.0, 1.0, 3.0, 8.0]
    assert session.resync_calls == 4
    health = _health(store)
    assert health["tick_sdk_resync_failures"] == 3
    assert health["tick_sdk_resyncs"] == 1
    assert len(_warnings(records)) == 1  # one WARNING for the restart
    failures = [message for level, message in records if "failed" in message]
    assert len(failures) == 3 and all("retry_in=" in message for message in failures)

    # A later restart starts from an immediate attempt again (reset on success).
    session.restart()
    store.poll_tick(SYMBOL)
    assert session.resync_calls == 5
    assert len(_warnings(records)) == 2


def test_backoff_schedule_is_capped_at_thirty_seconds():
    mono = _Mono()
    policy = TickStreamResyncPolicy(monotonic=mono)
    delays = []
    assert policy.due(SYMBOL, "PROVIDER_RESYNC_REQUIRED") is True
    for _ in range(8):
        policy.begin_attempt(SYMBOL)
        delays.append(policy.retry_in(SYMBOL))
        mono.now += delays[-1]
        assert policy.due(SYMBOL, "PROVIDER_RESYNC_FAILED") is True
    assert delays == [1.0, 2.0, 5.0, 10.0, 30.0, 30.0, 30.0, 30.0]
    assert RESYNC_BACKOFF_SECONDS == (0.0, 1.0, 2.0, 5.0, 10.0, 30.0)
    # PROVIDER_RESYNC_FAILED alone (no declared restart of this symbol) never qualifies.
    assert policy.due("OTHER", "PROVIDER_RESYNC_FAILED") is False
    # Another code ends the open restart.
    assert policy.due(SYMBOL, "CONSUMER_QUEUE_OVERFLOW") is False
    assert policy.due(SYMBOL, "PROVIDER_RESYNC_FAILED") is False


def test_stop_fences_the_resync_until_a_new_start(env, monkeypatch):
    store, session, _mono, _records = env
    stopped = []
    monkeypatch.setattr(
        btapistore_module, "_stop_store", lambda target, timeout, **_k: stopped.append(target)
    )
    store.stop()
    assert stopped == [store]
    session.restart()
    store.poll_tick(SYMBOL)
    store.poll_tick(SYMBOL)
    assert session.resync_calls == 0
    store._reset_sdk_stream_generation()  # what a new start does
    store.poll_tick(SYMBOL)
    assert session.resync_calls == 1


@pytest.mark.parametrize("env", ["gateway"], indirect=True)
def test_a_gateway_market_runtime_store_never_resyncs(env):
    store, session, mono, records = env
    assert store._tick_stream_resync.enabled is False
    session.restart()
    for _ in range(3):
        store.poll_tick(SYMBOL)
        mono.now += 60.0
    assert session.resync_calls == 0
    assert _health(store)["stale"] is True
    assert _warnings(records) == []


def test_no_resync_while_the_store_is_not_started(env):
    store, session, _mono, _records = env
    store._started = False
    session.restart()
    store.poll_tick(SYMBOL)
    store.poll_tick(SYMBOL)
    assert session.resync_calls == 0
    store._started = True
    store.poll_tick(SYMBOL)
    assert session.resync_calls == 1


def test_a_non_consuming_pump_never_resyncs(env):
    store, session, _mono, _records = env
    session.restart()
    assert store.has_pending_tick(SYMBOL) is False
    assert store.has_pending_tick(SYMBOL) is False
    assert session.resync_calls == 0
    store.poll_tick(SYMBOL)
    assert session.resync_calls == 1


@pytest.mark.parametrize(
    ("channel", "cleanup_unverified", "connected"),
    [("orderbook", False, True), ("tick", True, True), ("tick", False, False)],
    ids=["orderbook_channel", "cleanup_unverified", "store_disconnected"],
)
def test_declared_restart_outside_a_connected_tick_channel_is_not_resynced(
    env, monkeypatch, channel, cleanup_unverified, connected
):
    store, session, _mono, _records = env
    session.restart()
    adapter = store._market_stream_adapter
    stream = adapter._find_binding(SYMBOL, "tick")
    recovery = stream["stream"].poll(stream["subscription"], timeout_ms=0, max_events=1)
    assert recovery.recovery_code == "PROVIDER_RESYNC_REQUIRED"
    monkeypatch.setattr(
        adapter,
        "poll_result",
        lambda *_a, **_k: (recovery, ROUTE, False, cleanup_unverified, recovery.dropped_events),
    )
    store._connected = connected
    depth = 5 if channel == "orderbook" else None
    store._poll_sdk_market_stream(SYMBOL, store._api, channel=channel, depth=depth)
    assert session.resync_calls == 0


def test_a_stream_recovered_elsewhere_closes_the_open_restart(env):
    store, session, mono, _records = env
    session.resync_failures = 1
    session.restart()
    store.poll_tick(SYMBOL)
    assert session.resync_calls == 1  # failed; the next attempt waits 1 s
    # An explicit operator acknowledgement recovers the stream meanwhile.
    store.accept_market_stream_resync(SYMBOL, "tick", acknowledge_data_loss=True)
    assert session.resync_calls == 2
    session.push(_payload(20, generation=2))
    assert store.poll_tick(SYMBOL) is not None  # active again
    # A new restart in the same second is a new restart: an immediate attempt.
    session.restart()
    store.poll_tick(SYMBOL)
    assert session.resync_calls == 3
    assert mono.now == 1_000.0


# -- the Feed over the Store ----------------------------------------------------


class _FeedClock:
    def __init__(self):
        self.mono = MONO0

    def monotonic_ns(self):
        return self.mono


class _FeedStore:
    """The Feed's Store surface; ticks come from the real ``BtApiStore.poll_tick``."""

    def __init__(self, store):
        self.store = store

    def start(self, data=None):
        pass

    def register(self, feed):
        pass

    def subscribe(self, *_args, **_kwargs):
        pass

    def poll_tick(self, name):
        return self.store.poll_tick(name)

    def tick_stream_recovery_reason(self, name):
        return self.store.tick_stream_recovery_reason(name)

    def poll_live(self, _name):
        return None

    def mark_feed_dropped(self, event, reason):
        self.store.mark_feed_dropped(event, reason)


def test_feed_drops_the_open_bar_and_trades_on_the_first_fresh_tick_after_resync(env):
    store, session, _mono, _records = env
    clock = _FeedClock()
    feed = BtApiFeed(
        dataname=SYMBOL,
        store=_FeedStore(store),
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        price_tick=1.0,
        backfill_start=False,
        clock=clock,
        qcheck=0.0,
    )
    feed._start()
    bars = []
    enqueue = feed._enqueue_bar_event

    def record(bar_event, bar_datetime, *, deliver_lines=True, bar_source=None):
        bars.append((bar_event, deliver_lines))
        return enqueue(bar_event, bar_datetime, deliver_lines=deliver_lines, bar_source=bar_source)

    feed._enqueue_bar_event = record

    def load(second=None, **values):
        if second is not None:
            session.push(_payload(second, generation=session.generation, **values))
            clock.mono = max(clock.mono, MONO0 + int((second + LATENCY) * NS))
        return feed.load()

    def statuses():
        return [status for status, _args, _kwargs in feed.get_notifications()]

    try:
        load(10)
        assert statuses() == [feed.LIVE]
        assert feed.trade_qualification().ok is True

        # Front disconnect: the provider restarts its MD session.
        session.restart()
        clock.mono = MONO0 + int(15 * NS)
        load()
        assert session.resync_calls == 1
        assert statuses() == []
        verdict = feed.trade_qualification()
        assert verdict.ok is False and "RECEIVE_TIME_STALE" in verdict.reasons

        # The first tick of the new session: a volume baseline, fresh and valid.
        load(20, **BASELINE)
        assert statuses() == []  # never DELAYED by the scope change
        assert feed._continuity_degraded is False
        verdict = feed.trade_qualification()
        assert (verdict.live, verdict.ok) == (True, True), verdict.reasons
        # The bar opened in the lost session is dropped as invalid, not on the lines.
        assert [(bar.complete, deliver) for bar, deliver in bars] == [(False, False)]
        assert "FORCED_INVALIDATION" in bars[0][0].quality_flags

        load(21)
        load(70)
        load(130)
        assert statuses() == []
        assert [(bar.complete, deliver) for bar, deliver in bars[1:]] == [(True, True)]
        assert session.resync_calls == 1
        assert _health(store)["tick_sdk_resyncs"] == 1
    finally:
        feed.stop()


# -- an outage before the restart (SimNow 2026-11-07, D62-38 point 7) ----------


def test_an_outage_is_reported_and_never_resynced_until_the_restart(env):
    store, session, _mono, _records = env
    session.push(_payload(10, generation=1))
    assert store.poll_tick(SYMBOL) is not None
    assert store.tick_stream_recovery_reason(SYMBOL) is None

    session.lose()
    for _ in range(3):
        assert store.poll_tick(SYMBOL) is None
        assert store.tick_stream_recovery_reason(SYMBOL) == "PROVIDER_POLL_FAILED"
    assert session.resync_calls == 0  # an outage has nothing to resync

    session.restart()
    assert store.poll_tick(SYMBOL) is None  # the restart's failed poll: resynced at once
    assert session.resync_calls == 1
    assert store.tick_stream_recovery_reason(SYMBOL) is None
    session.push(_payload(20, generation=2, **BASELINE))
    assert store.poll_tick(SYMBOL) is not None
    assert store.tick_stream_recovery_reason(SYMBOL) is None


def test_a_failed_resync_keeps_the_restart_reason_until_it_succeeds(env):
    store, session, mono, _records = env
    session.push(_payload(10, generation=1))
    assert store.poll_tick(SYMBOL) is not None
    session.resync_failures = 1
    session.restart()
    assert store.poll_tick(SYMBOL) is None
    assert session.resync_calls == 1
    assert store.tick_stream_recovery_reason(SYMBOL) == "PROVIDER_RESYNC_REQUIRED"
    mono.now += 60.0  # past the backoff
    assert store.poll_tick(SYMBOL) is None
    assert session.resync_calls == 2
    assert store.tick_stream_recovery_reason(SYMBOL) is None


def test_feed_is_delayed_through_an_outage_and_live_on_the_first_fresh_tick(env):
    store, session, _mono, _records = env
    clock = _FeedClock()
    feed = BtApiFeed(
        dataname=SYMBOL,
        store=_FeedStore(store),
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        price_tick=1.0,
        backfill_start=False,
        clock=clock,
        qcheck=0.0,
    )
    feed._start()

    def load(second=None, **values):
        if second is not None:
            session.push(_payload(second, generation=session.generation, **values))
            clock.mono = max(clock.mono, MONO0 + int((second + LATENCY) * NS))
        return feed.load()

    def notifications():
        return [(status, kwargs) for status, _args, kwargs in feed.get_notifications()]

    try:
        load(10)
        assert [status for status, _ in notifications()] == [feed.LIVE]

        # The front disconnects: no tick arrives, the Store reports the outage.
        session.lose()
        clock.mono = MONO0 + int(15 * NS)
        load()
        delayed = notifications()
        assert [status for status, _ in delayed] == [feed.DELAYED]
        assert delayed[0][1]["stale_reason"] == "sdk_market_stream_recovery:PROVIDER_POLL_FAILED"
        verdict = feed.trade_qualification()
        assert verdict.live is False and "FEED_NOT_LIVE" in verdict.reasons
        load()
        assert notifications() == []  # one transition, not one per poll

        # The provider restarted its MD session: resynced, still no tick.
        session.restart()
        load()
        assert session.resync_calls == 1
        assert notifications() == []
        assert feed.trade_qualification().live is False

        # The first tick of the new session is fresh and valid: LIVE and tradable.
        load(20, **BASELINE)
        assert [status for status, _ in notifications()] == [feed.LIVE]
        verdict = feed.trade_qualification()
        assert (verdict.live, verdict.ok) == (True, True), verdict.reasons
    finally:
        feed.stop()
