"""Gateway subscription projection and BT feed checks using synthetic facts."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
import backtrader as bt
from backtrader.feeds.btapifeed import BtApiFeed
from bt_api_base.market_protocol import MARKET_EVENT_OPERATION, MARKET_EVENT_SCHEMA, MARKET_EVENT_SCHEMA_VERSION
from bt_api_base.market_tick_protocol import MarketClockQuality, MarketFreshnessStatus
from bt_api_base.service_protocol import WIRE_PROTOCOL_VERSION, WireEnvelope, WireHeader, WireIdentity, WireMessageKind, WireRole, WireScope
from bt_api_py.gateway_market_projection import GatewayMarketProjectionError, GatewayMarketTickProjector
from bt_api_py.gateway_strategy_market import GatewayMarketReceivedEvent, GatewayMarketSubscriptionClient, GatewayMarketSubscriptionSettings
from bt_api_py.service_market import MarketBootstrap
from tests.unit.feeds.test_market_tick_adapter_baseline import INSTRUMENT, SOURCE, SUBSCRIPTION, _payload

SCOPE = WireScope('paper:gateway-market')
PEER = WireIdentity(WireRole.SERVICE, 'market-principal', 'market-service')


def payload(**changes):
    return _payload(source_clock_quality=MarketClockQuality.UNKNOWN,
        receive_clock_quality=MarketClockQuality.UNKNOWN, source_clock_error_ms=None,
        receive_clock_error_ms=None, freshness_status=MarketFreshnessStatus.UNAVAILABLE,
        freshness_reason_codes=('GENERIC_EVENT_TIME_NOT_BOUND', 'SOURCE_CLOCK_CALIBRATION_NOT_PROVIDED'),
        execution_eligible=False, **changes)


def frame(sequence, value=None, *, source=SOURCE):
    h = WireHeader(protocol_version=WIRE_PROTOCOL_VERSION, kind=WireMessageKind.EVENT,
        message_id=uuid4().hex, correlation_id=None, identity=PEER, scope=SCOPE,
        operation=MARKET_EVENT_OPERATION, schema_id=MARKET_EVENT_SCHEMA,
        schema_version=MARKET_EVENT_SCHEMA_VERSION, sent_at_utc='2026-11-02T02:00:00Z',
        stream_id=source.stream_id, stream_epoch=source.epoch, sequence=sequence)
    return WireEnvelope(h, {'key': SUBSCRIPTION.to_dict(), 'data': (value or payload()).to_dict()})


def client_with(monkeypatch, frames):
    client = GatewayMarketSubscriptionClient(None, 'main')
    boot = MarketBootstrap(None, 'latest_event', False, False, SOURCE.stream_id,
                           SOURCE.epoch, 0, SOURCE.epoch, 0, False, SOURCE)
    status = {'healthy': True, 'recovery_required': False, 'resync_required': False,
        'authorization_interrupted': None, 'authorization_generation': 1, 'queue_count': 0,
        'queue_bytes': 0, 'unsubscription_uncertain': False, 'local_result_gap': False,
        'last_bootstrap': boot, 'source_descriptor': SOURCE}
    monkeypatch.setattr(client, 'start', lambda **kw: boot)
    monkeypatch.setattr(client, 'status', lambda **kw: dict(status))
    monkeypatch.setattr(client, 'poll', lambda **kw: frames.pop(0) if frames else None)
    def poll_with_receipt(**kw):
        event = client.poll(**kw)
        return None if event is None else GatewayMarketReceivedEvent(event, None)
    monkeypatch.setattr(client, 'poll_with_receipt', poll_with_receipt)
    return client, status


def test_gateway_projection_preserves_unknown_clock_and_rejects_discontinuity(monkeypatch):
    client, _ = client_with(monkeypatch, [frame(1), frame(3)])
    projector = GatewayMarketTickProjector(client, key=SUBSCRIPTION, scope=SCOPE, peer=PEER)
    projector.start()
    event = projector.poll()
    assert event.data.last_price == 1500
    assert event.clock.freshness_status is MarketFreshnessStatus.UNAVAILABLE
    assert not event.data.execution_eligible
    with pytest.raises(GatewayMarketProjectionError, match='GATEWAY_MARKET_FRAME_INVALID'):
        projector.poll()


def test_gateway_projection_rejects_self_claimed_freshness(monkeypatch):
    client, _ = client_with(monkeypatch, [frame(1, _payload())])
    projector = GatewayMarketTickProjector(client, key=SUBSCRIPTION, scope=SCOPE, peer=PEER)
    projector.start()
    with pytest.raises(GatewayMarketProjectionError, match='GATEWAY_MARKET_FRAME_INVALID'):
        projector.poll()


def test_gateway_clock_feed_write_boundary_and_race(monkeypatch):
    """Synthetic qualifier tests BT binding; SDK separately proves clock facts."""
    import time
    import os
    import threading
    from bt_api_py.clock_verification import ClockVerifier, GatewayClockVerifier, GatewayTradeClockQualification
    from bt_api_py.service_market import MarketReceiveReceipt

    client, status = client_with(monkeypatch, [frame(1)])
    store = _gateway_store(client)
    store._gateway_strategy_config = store.gateway_strategy_config
    store.start = lambda data=None: None
    verifier = GatewayClockVerifier(ClockVerifier(servers=('synthetic.invalid',)))
    feed = BtApiFeed(dataname='SA609', store=store, timeframe=bt.TimeFrame.Ticks,
                     backfill_start=False, price_tick=1.0, qcheck=0.0,
                     gateway_clock_verification=verifier)
    feed._start()
    try:
        assert feed.load() is True
        adapter = feed._gateway_market_adapter
        event = feed._gateway_last_data_event
        assert event is not None
        now = time.monotonic_ns()
        receipt = MarketReceiveReceipt('pub', event.cursor.stream_id, event.cursor.epoch,
            event.cursor.sequence, uuid4().hex, time.time_ns(), now, os.getpid(), threading.get_ident())
        adapter._latest_event, adapter._latest_receipt = event, receipt
        feed._live_notified = True
        feed._continuity_degraded = False
        result = GatewayTradeClockQualification(True, None, '2026-11-02T02:00:00Z', now,
            '2026-11-02T02:00:00Z', 0.1, 1.0, 1.0, now + 1_000_000_000)
        calls = []
        def qualify(e, r):
            calls.append((e, r))
            return result
        monkeypatch.setattr(adapter._qualifier, 'qualify', qualify)
        good = BtApiFeed.gateway_trade_qualification(feed, expected_store=store, expected_instrument=INSTRUMENT)
        assert good.ok and good.live and calls == [(event, receipt)]
        assert good.expires_monotonic_ns == result.expires_monotonic_ns
        ref = good.dispatch_market_ref
        assert ref['key'] == SUBSCRIPTION.to_dict()
        assert (ref['epoch'], ref['sequence'], ref['message_id']) == (
            receipt.stream_epoch, receipt.sequence, receipt.message_id)
        with pytest.raises(TypeError):
            ref['sequence'] = 2
        with pytest.raises(TypeError):
            ref['key']['instrument']['venue'] = 'other'
        bad = BtApiFeed.gateway_trade_qualification(feed, expected_store=store,
            expected_instrument=replace(INSTRUMENT, venue='other'))
        assert not bad.ok and len(calls) == 1
        def race(e, r):
            adapter._latest_receipt = object()
            return result
        monkeypatch.setattr(adapter._qualifier, 'qualify', race)
        assert not BtApiFeed.gateway_trade_qualification(feed, expected_store=store,
                                                         expected_instrument=INSTRUMENT).ok
        adapter._latest_receipt = replace(receipt, source='replay')
        assert not BtApiFeed.gateway_trade_qualification(feed, expected_store=store,
                                                         expected_instrument=INSTRUMENT).ok
        adapter._latest_receipt = replace(receipt, sequence=receipt.sequence + 1)
        assert not BtApiFeed.gateway_trade_qualification(feed, expected_store=store,
                                                         expected_instrument=INSTRUMENT).ok
        adapter._latest_receipt = receipt
        status['healthy'] = False
        monkeypatch.setattr(adapter._qualifier, 'qualify', qualify)
        assert not BtApiFeed.gateway_trade_qualification(feed, expected_store=store,
                                                         expected_instrument=INSTRUMENT).ok
    finally:
        feed.stop()
    assert not verifier._stop.is_set()  # borrowed verifier is not stopped


def test_gateway_clock_explicit_servers_and_owned_lifecycle(monkeypatch):
    from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
    from bt_api_py.clock_verification import GatewayClockVerifier

    client, _ = client_with(monkeypatch, [])
    feed = SimpleNamespace(p=SimpleNamespace(event_time_max_age=2.0))
    store = _gateway_store(client)
    for value in (True, {}, {'servers': []}, {'servers': ['x'], 'surprise': 1}):
        with pytest.raises(ValueError):
            GatewayMarketAdapter(store, 'SA609', feed, clock_verification=value)
    calls = []
    monkeypatch.setattr(GatewayClockVerifier, 'start_background_refresh', lambda self, interval: calls.append(('start', interval)))
    monkeypatch.setattr(GatewayClockVerifier, 'stop_background_refresh', lambda self, **kw: calls.append(('stop', kw['timeout_seconds'])) or True)
    adapter = GatewayMarketAdapter(store, 'SA609', feed,
        clock_verification={'servers': ['synthetic.invalid'], 'refresh_interval_seconds': 10})
    adapter.start()
    adapter.close()
    assert calls == [('start', 10), ('stop', 5)]


def test_gateway_clock_shutdown_pending_preserves_owner(monkeypatch):
    from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
    from bt_api_py.clock_verification import GatewayClockVerifier

    client, _ = client_with(monkeypatch, [])
    feed = SimpleNamespace(p=SimpleNamespace(event_time_max_age=2.0))
    store = _gateway_store(client)
    monkeypatch.setattr(GatewayClockVerifier, 'start_background_refresh', lambda self, interval: None)
    outcomes = iter([False, True])
    monkeypatch.setattr(GatewayClockVerifier, 'stop_background_refresh', lambda self, **kw: next(outcomes))
    adapter = GatewayMarketAdapter(store, 'SA609', feed,
        clock_verification={'servers': ['synthetic.invalid']})
    adapter.start()
    with pytest.raises(RuntimeError, match='GATEWAY_CLOCK_SHUTDOWN_PENDING'):
        adapter.close()
    assert adapter._clock_started and adapter.matches(store, feed, INSTRUMENT)
    adapter.close()
    assert not adapter._clock_started and not adapter.matches(store, feed, INSTRUMENT)


def test_feed_consumes_gateway_tick_without_direct_store_poll(monkeypatch):
    client, status = client_with(monkeypatch, [frame(1)])
    setting = GatewayMarketSubscriptionSettings(SUBSCRIPTION, require_source_descriptor=True)
    config = SimpleNamespace(market_settings=SimpleNamespace(subscriptions={'main': setting}),
        instruments_by_ref={'main': INSTRUMENT}, exchange_name='test', peer=PEER,
        route=SimpleNamespace(scope=SimpleNamespace(execution_domain_ref=SCOPE.execution_domain_ref)))
    class Api:
        def market_subscription(self, route, name):
            assert (route, name) == ('test', 'main')
            return client
    class Store:
        _gateway_strategy_config = config
        gateway_strategy_config = config
        gateway_api = Api()
        def start(self, data=None):
            assert data._gateway_market_enabled_for_store(self)
        def poll_tick(self, *_):
            raise AssertionError('legacy poll is forbidden')
        def poll_live(self, *_):
            raise AssertionError('legacy poll is forbidden')
        def poll_orderbook(self, *_args, **_kwargs):
            raise AssertionError('legacy poll is forbidden')
    store = Store()
    feed = BtApiFeed(dataname='SA609', store=store, timeframe=bt.TimeFrame.Ticks,
                     backfill_start=False, price_tick=1.0, qcheck=0.0)
    feed._start()
    try:
        assert feed.load() is True
        assert feed.close[0] == 1500
        assert feed.trade_qualification().ok is False
        bound = BtApiFeed.gateway_trade_qualification(
            feed, expected_store=store, expected_instrument=INSTRUMENT)
        assert bound.ok is False
        assert "GATEWAY_FEED_BINDING_MISMATCH" not in bound.reasons
        wrong = BtApiFeed.gateway_trade_qualification(
            feed, expected_store=store, expected_instrument=replace(INSTRUMENT, venue='other'))
        assert wrong.ok is False and "GATEWAY_FEED_BINDING_MISMATCH" in wrong.reasons
        status['healthy'] = False
        assert feed.load() is None
        assert feed._gateway_market_adapter.recovery_reason() == 'RECOVERY_REQUIRED'
    finally:
        feed.stop()


def test_gateway_feed_without_qcheck_pauses_after_an_empty_poll(monkeypatch):
    # SimNow 2026-11-10: the 007_ctp Gateway example configures no qcheck. Its
    # live loop asked the SDK owner again at once after every empty poll and
    # kept one core busy (95-100 % CPU for an idle strategy).
    import backtrader.feeds.btapifeed as module

    client, status = client_with(monkeypatch, [frame(1)])
    store = _gateway_store(client)
    store._gateway_strategy_config = store.gateway_strategy_config
    store.start = lambda data=None: None
    feed = BtApiFeed(dataname='SA609', store=store, timeframe=bt.TimeFrame.Ticks,
                     backfill_start=False, price_tick=1.0)
    assert feed.p.qcheck == 0.0 and feed._gateway_market_enabled_for_store(store)
    feed._start()
    sleeps = []
    monkeypatch.setattr(module._time, 'sleep', sleeps.append)
    try:
        assert feed.load() is True and sleeps == []  # a delivered tick is never delayed
        assert feed.load() is None
        assert sleeps == [module._GATEWAY_IDLE_POLL_SECONDS] and 0 < sleeps[0] <= 0.05
        feed._qcheck = 0.3  # a configured qcheck (set per loop by Cerebro) takes precedence
        assert feed.load() is None and sleeps[-1] == 0.3 and len(sleeps) == 2
    finally:
        feed.stop()

    # A bar feed: a tick that was consumed into an unfinished bar yields no
    # line either, but more ticks may be queued, so that turn does not pause.
    client, status = client_with(monkeypatch, [frame(1)])
    store = _gateway_store(client)
    store._gateway_strategy_config = store.gateway_strategy_config
    store.start = lambda data=None: None
    bars = BtApiFeed(dataname='SA609', store=store, timeframe=bt.TimeFrame.Minutes, compression=1,
                     backfill_start=False, price_tick=1.0)
    bars._start()
    del sleeps[:]
    try:
        assert bars.load() is None and sleeps == []
        assert bars.load() is None and sleeps == [module._GATEWAY_IDLE_POLL_SECONDS]
    finally:
        bars.stop()


def _gateway_store(client):
    setting = GatewayMarketSubscriptionSettings(SUBSCRIPTION, require_source_descriptor=True)
    config = SimpleNamespace(market_settings=SimpleNamespace(subscriptions={'main': setting}),
        instruments_by_ref={'main': INSTRUMENT}, exchange_name='test', peer=PEER,
        route=SimpleNamespace(scope=SimpleNamespace(execution_domain_ref=SCOPE.execution_domain_ref)))
    return SimpleNamespace(gateway_strategy_config=config,
        gateway_api=SimpleNamespace(market_subscription=lambda route, name: client))


def test_provider_resync_after_recovery_keeps_unverified_clock(monkeypatch):
    from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
    from bt_api_py.service_runtime_thread import OwnerOperationError
    client, status = client_with(monkeypatch, [])
    source2 = replace(SOURCE, epoch='epoch-2')
    boot2 = MarketBootstrap(None, 'latest_event', False, False, source2.stream_id,
                            source2.epoch, 0, source2.epoch, 0, False, source2)
    calls = []
    def poll(**kw):
        if not calls:
            calls.append('lost')
            raise OwnerOperationError('PROVIDER_RESYNC_REQUIRED')
        return frame(1, source=source2)
    def resync(**kw):
        assert kw['acknowledge_data_loss'] is True
        status['source_descriptor'] = source2
        calls.append('resync')
        return boot2
    monkeypatch.setattr(client, 'poll', poll)
    monkeypatch.setattr(client, 'accept_resync', resync)
    adapter = GatewayMarketAdapter(_gateway_store(client), 'SA609', object())
    adapter.start()
    assert adapter.poll() is None
    assert adapter.recovery_reason() == 'PROVIDER_RESYNC_REQUIRED'
    event = adapter.poll()
    assert calls == ['lost', 'resync']
    assert event.cursor.epoch == 'epoch-2'
    assert event.clock.freshness_status is MarketFreshnessStatus.UNAVAILABLE
    assert event.data.execution_eligible is False


def test_timeout_retries_exact_pending_poll_without_status_overtaking(monkeypatch):
    from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
    from bt_api_py.service_runtime_thread import ThreadedRuntimeError
    client, _ = client_with(monkeypatch, [])
    calls = []
    def poll(**kw):
        calls.append('poll')
        if len(calls) == 1:
            raise ThreadedRuntimeError('OWNER_TIMEOUT_RUNNING')
        return frame(1)
    monkeypatch.setattr(client, 'poll', poll)
    adapter = GatewayMarketAdapter(_gateway_store(client), 'SA609', object())
    adapter.start()
    assert adapter.poll() is None
    assert adapter.recovery_reason() == 'OWNER_TIMEOUT_RUNNING'
    assert adapter.poll().cursor.sequence == 1
    assert calls == ['poll', 'poll']


@pytest.mark.parametrize('code', ['OWNER_OPERATION_PENDING', 'OWNER_TIMEOUT_QUEUED'])
def test_owner_pending_slot_is_transient_not_terminal(monkeypatch, code):
    # SimNow 63.09: OWNER_OPERATION_PENDING (another call still holds the
    # client's single slot) left the feed unavailable for the process lifetime.
    from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
    from bt_api_py.service_runtime_thread import ThreadedRuntimeError
    client, _ = client_with(monkeypatch, [])
    calls = []
    def poll(**kw):
        calls.append('poll')
        if len(calls) <= 2:
            raise ThreadedRuntimeError(code)
        return frame(1)
    monkeypatch.setattr(client, 'poll', poll)
    adapter = GatewayMarketAdapter(_gateway_store(client), 'SA609', object())
    adapter.start()
    assert adapter.poll() is None and adapter.recovery_reason() == code
    adapter._next_retry = 0
    assert adapter.poll() is None and adapter.recovery_reason() == code
    adapter._next_retry = 0
    assert adapter.poll().cursor.sequence == 1
    assert adapter.recovery_reason() is None and calls == ['poll', 'poll', 'poll']


def test_stopped_feed_cannot_reuse_stale_subscription_cursor(monkeypatch):
    from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
    client, _ = client_with(monkeypatch, [])
    store = _gateway_store(client)
    adapter = GatewayMarketAdapter(store, 'SA609', object())
    adapter.start()
    adapter.close()
    with pytest.raises(ValueError, match='ALREADY_CLAIMED'):
        GatewayMarketAdapter(store, 'SA609', object())


def test_recover_reports_required_resync_before_accepting_new_epoch(monkeypatch):
    from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
    from bt_api_py.service_runtime_thread import OwnerOperationError
    client, status = client_with(monkeypatch, [])
    source2 = replace(SOURCE, epoch='epoch-2')
    pending = MarketBootstrap(None, 'latest_event', False, False, source2.stream_id,
                              source2.epoch, 0, source2.epoch, 0, True, source2)
    restored = replace(pending, resync_required=False)
    calls = []
    def poll(**kw):
        if not calls:
            calls.append('poll-unavailable')
            raise OwnerOperationError('RECOVERY_REQUIRED')
        return frame(1, source=source2)
    def recover(**kw):
        calls.append('recover')
        return pending
    def resync(**kw):
        calls.append('resync')
        status['source_descriptor'] = source2
        return restored
    monkeypatch.setattr(client, 'poll', poll)
    monkeypatch.setattr(client, 'recover', recover)
    monkeypatch.setattr(client, 'accept_resync', resync)
    adapter = GatewayMarketAdapter(_gateway_store(client), 'SA609', object())
    adapter.start()
    assert adapter.poll() is None
    assert adapter.recovery_reason() == 'RECOVERY_REQUIRED'
    assert adapter.poll() is None
    assert adapter.recovery_reason() == 'PROVIDER_RESYNC_REQUIRED'
    # Simulate elapsed backoff without sleeping in a unit test.
    adapter._next_retry = 0
    event = adapter.poll()
    assert calls == ['poll-unavailable', 'recover', 'resync']
    assert event.cursor.epoch == source2.epoch
    assert event.data.execution_eligible is False


def test_timed_out_initial_start_resumes_same_owner_operation(monkeypatch):
    from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
    from bt_api_py.service_runtime_thread import ThreadedRuntimeError
    client, _ = client_with(monkeypatch, [frame(1)])
    boot = MarketBootstrap(None, 'latest_event', False, False, SOURCE.stream_id,
                           SOURCE.epoch, 0, SOURCE.epoch, 0, False, SOURCE)
    calls = []
    def start(**kw):
        calls.append('start')
        if len(calls) == 1:
            raise ThreadedRuntimeError('OWNER_TIMEOUT_RUNNING')
        return boot
    monkeypatch.setattr(client, 'start', start)
    adapter = GatewayMarketAdapter(_gateway_store(client), 'SA609', object())
    adapter.start()
    assert adapter.recovery_reason() == 'OWNER_TIMEOUT_RUNNING'
    assert adapter.poll().cursor.sequence == 1
    assert calls == ['start', 'start']


def test_client_receive_receipt_must_match_exact_wire_event(monkeypatch):
    import os
    import threading
    import time
    from bt_api_py.service_market import MarketReceiveReceipt
    first, second = frame(1), frame(2)
    client, _ = client_with(monkeypatch, [])
    receipt = MarketReceiveReceipt('pub', first.header.stream_id, first.header.stream_epoch,
        first.header.sequence, first.header.message_id, time.time_ns(), time.monotonic_ns(),
        os.getpid(), threading.get_ident())
    deliveries = [GatewayMarketReceivedEvent(first, receipt), GatewayMarketReceivedEvent(second, receipt)]
    monkeypatch.setattr(client, 'poll_with_receipt', lambda **kw: deliveries.pop(0))
    projector = GatewayMarketTickProjector(client, key=SUBSCRIPTION, scope=SCOPE, peer=PEER)
    projector.start()
    assert projector.poll().cursor.sequence == 1
    assert projector.last_receipt == receipt
    with pytest.raises(GatewayMarketProjectionError, match='GATEWAY_MARKET_FRAME_INVALID'):
        projector.poll()
    assert projector.last_receipt is None


def test_source_health_transition_invalidates_old_receipt(monkeypatch):
    import os
    import threading
    import time
    from bt_api_py.service_market import MarketReceiveReceipt
    first = frame(1)
    client, status = client_with(monkeypatch, [])
    receipt = MarketReceiveReceipt('pub', first.header.stream_id, first.header.stream_epoch,
        first.header.sequence, first.header.message_id, time.time_ns(), time.monotonic_ns(),
        os.getpid(), threading.get_ident())
    monkeypatch.setattr(client, 'poll_with_receipt', lambda **kw: GatewayMarketReceivedEvent(first, receipt))
    projector = GatewayMarketTickProjector(client, key=SUBSCRIPTION, scope=SCOPE, peer=PEER)
    projector.start()
    assert projector.poll().cursor.sequence == 1
    assert projector.last_receipt is receipt
    status['healthy'] = False
    status['recovery_required'] = True
    assert projector.status()['recovery_required']
    assert projector.last_receipt is None


def test_one_gateway_subscription_cannot_be_claimed_by_two_threads(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
    client, _ = client_with(monkeypatch, [])
    store = _gateway_store(client)
    barrier = threading.Barrier(2)
    def claim():
        barrier.wait(timeout=2)
        try:
            return GatewayMarketAdapter(store, 'SA609', object())
        except ValueError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    adapters = [item for item in results if isinstance(item, GatewayMarketAdapter)]
    assert len(adapters) == 1
    assert sum(item == 'GATEWAY_MARKET_SUBSCRIPTION_ALREADY_CLAIMED' for item in results) == 1
    adapters[0].close()


def test_sdk_failure_while_gateway_unreachable_recovers_after_backoff(monkeypatch):
    # SimNow 63.09 (I63-E112): pausing the Gateway made the SDK fail a poll
    # with a code the adapter had no retry for (here RUNTIME_MAINTENANCE_FAILED);
    # the feed then stayed dead after the Gateway resumed. The adapter now
    # re-reads the SDK status after backoff and recovers as it says.
    from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
    from bt_api_py.service_market import ServiceMarketError
    client, status = client_with(monkeypatch, [])
    boot = MarketBootstrap(None, 'latest_event', False, False, SOURCE.stream_id,
                           SOURCE.epoch, 0, SOURCE.epoch, 0, False, SOURCE)
    calls = []
    def poll(**kw):
        if not calls:
            calls.append('poll-failed')
            status['recovery_required'] = True
            raise ServiceMarketError('RUNTIME_MAINTENANCE_FAILED')
        calls.append('poll')
        return frame(1)
    def recover(**kw):
        calls.append('recover')
        status['recovery_required'] = False
        return boot
    monkeypatch.setattr(client, 'poll', poll)
    monkeypatch.setattr(client, 'recover', recover)
    adapter = GatewayMarketAdapter(_gateway_store(client), 'SA609', object())
    adapter.start()
    assert adapter.poll() is None
    assert adapter.recovery_reason() == 'RUNTIME_MAINTENANCE_FAILED'
    adapter._next_retry = 0  # elapsed backoff
    assert adapter.poll() is None
    assert adapter.recovery_reason() == 'RECOVERY_REQUIRED'
    adapter._next_retry = 0
    event = adapter.poll()
    assert event is not None and adapter.recovery_reason() is None
    assert calls == ['poll-failed', 'recover', 'poll']


def test_failing_status_while_unreachable_is_retried_not_terminal(monkeypatch):
    from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
    from bt_api_py.service_runtime_thread import ThreadedRuntimeError
    client, status = client_with(monkeypatch, [frame(1)])
    adapter = GatewayMarketAdapter(_gateway_store(client), 'SA609', object())
    adapter.start()
    healthy_status = client.status
    def unreachable(**kw):
        raise ThreadedRuntimeError('NOT_READY')
    monkeypatch.setattr(client, 'poll', lambda **kw: (_ for _ in ()).throw(ThreadedRuntimeError('NOT_READY')))
    assert adapter.poll() is None and adapter.recovery_reason() == 'NOT_READY'
    monkeypatch.setattr(client, 'status', unreachable)
    adapter._next_retry = 0
    assert adapter.poll() is None and adapter.recovery_reason() == 'NOT_READY'
    # The Gateway is back: the next status read clears the reason and polling resumes.
    monkeypatch.setattr(client, 'status', healthy_status)
    frames = [frame(1)]
    monkeypatch.setattr(client, 'poll', lambda **kw: frames.pop(0) if frames else None)
    adapter._next_retry = 0
    assert adapter.poll() is not None and adapter.recovery_reason() is None


def test_projection_failure_stays_terminal(monkeypatch):
    from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
    client, status = client_with(monkeypatch, [])
    adapter = GatewayMarketAdapter(_gateway_store(client), 'SA609', object())
    adapter.start()
    def bad(**kw):
        raise GatewayMarketProjectionError('GATEWAY_MARKET_SOURCE_CHANGED')
    monkeypatch.setattr(adapter._projector, 'poll', bad)
    status_calls = []
    monkeypatch.setattr(client, 'status', lambda **kw: status_calls.append(1) or dict(status))
    assert adapter.poll() is None
    adapter._next_retry = 0
    assert adapter.poll() is None
    assert adapter.recovery_reason() == 'GATEWAY_MARKET_SOURCE_CHANGED' and status_calls == []


def test_adapter_follows_the_store_to_a_newly_registered_session(monkeypatch):
    # D63-03: after a Gateway restart the Store registers a new SDK session.
    # The old subscription client is dead; the adapter must start the new
    # one from its bootstrap instead of polling the old client forever.
    from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
    old_client, _ = client_with(monkeypatch, [frame(1)])
    store = _gateway_store(old_client)
    store.is_connected = True
    feed = object()
    adapter = GatewayMarketAdapter(store, 'SA609', feed)
    adapter.start()
    assert adapter.poll() is not None
    old_api = store.gateway_api
    new_client, _ = client_with(monkeypatch, [frame(1), frame(2)])
    starts = []
    real_start = new_client.start
    monkeypatch.setattr(new_client, 'start', lambda **kw: starts.append(1) or real_start(**kw))
    offered = []
    def subscription(route, name):
        offered.append((route, name))
        if broken[0]:
            raise RuntimeError('GATEWAY_FACADE_CLOSED')
        return new_client
    broken = [True]
    store.gateway_api = SimpleNamespace(market_subscription=subscription)
    store.is_connected = False
    # Replaced but not usable yet: wait, and never deliver through the old client.
    assert adapter.poll() is None and adapter.recovery_reason() == 'GATEWAY_SESSION_REPLACED'
    assert adapter.latest_realtime() is None and offered == []
    assert adapter._api is old_api and adapter._projector._client is old_client
    store.is_connected = True
    assert adapter.poll() is None and adapter.recovery_reason() == 'GATEWAY_SESSION_REPLACED'
    assert offered == [('test', 'main')] and adapter._projector._client is old_client
    broken[0] = False
    event = adapter.poll()
    assert event is not None and event.cursor.sequence == 1 and starts == [1]
    assert adapter._api is store.gateway_api and adapter._projector._client is new_client
    assert adapter.recovery_reason() is None
    assert adapter.poll().cursor.sequence == 2 and starts == [1]
    assert adapter.matches(store, feed, INSTRUMENT)
