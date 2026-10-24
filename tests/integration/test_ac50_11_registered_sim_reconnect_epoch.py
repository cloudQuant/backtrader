"""Reconnect CTP generation callbacks into a freshly rebuilt live-factor epoch."""

from __future__ import annotations

import collections
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest

from backtrader.research.live import LiveFactorReadiness
from backtrader.research.live_cohort import LiveBarCohort, LiveCohortFrozenError
from backtrader.stores.registered_sim import RegisteredSimStore
from tests.integration import test_ac50_07a_raw_cold_start_alpha003 as cold_start
from tests.integration import test_live_alpha003_parity as parity


_UTC = timezone.utc
_TARGETS = cold_start._TARGETS
_FIELDS = cold_start._FIELDS
_BAR_COUNT = cold_start._BAR_COUNT


class _FirstBatchColdStartStrategy(cold_start._ColdStartStrategy):
    """Retain the exact first published batch while using normal factor flow."""

    def __init__(self):
        self.first_batch = None
        super().__init__()

    def _evaluate_batch(self):
        if self.first_batch is None:
            self.first_batch = self.p.cohort.current_batch()
        super()._evaluate_batch()


class _GenerationMdClient:
    """Fake SDK leaf that invokes the same generation-aware callback slots."""

    def __init__(self, *, clock, source, **_kwargs):
        self._state_lock = threading.RLock()
        self._connection_generation = 1
        self.on_tick = None
        self.on_tick_with_generation = None
        self.on_disconnect = None
        self.on_disconnect_with_generation = None
        self.on_error = None
        self._clock = clock
        self._source = source
        self.subscriptions = []
        source.client = self
        clock.source = source

    @property
    def connection_generation(self):
        with self._state_lock:
            return self._connection_generation

    def start(self, block=False):
        assert block is False
        self._source.emit_until(self._clock.utc_now())

    def wait_ready(self, timeout=20):
        return True

    def subscribe(self, instruments):
        with self._state_lock:
            generation = self._connection_generation
            self.subscriptions.append((generation, tuple(sorted(instruments))))

    def capture_tick_callback(self, payload):
        """Capture callback and generation as the SDK SPI does under its lock."""
        with self._state_lock:
            callback = self.on_tick_with_generation
            generation = self._connection_generation
        assert callable(callback)
        return lambda: callback(payload, generation)

    def dispatch_tick(self, payload, generation):
        with self._state_lock:
            callback = self.on_tick_with_generation
        assert callable(callback)
        callback(payload, generation)

    def dispatch_disconnect(self, reason, generation):
        with self._state_lock:
            callback = self.on_disconnect_with_generation
        assert callable(callback)
        callback(reason, generation)

    def reconnect_and_resubscribe(self, generation):
        with self._state_lock:
            assert generation > self._connection_generation
            self._connection_generation = generation
            instruments = tuple(
                sorted({instrument for _prior, batch in self.subscriptions for instrument in batch})
            )
        # CTP's SDK owns automatic subscription restoration after login. This
        # fake leaf records that same public subscribe call at the new epoch.
        if instruments:
            self.subscribe(instruments)

    def stop(self):
        return None


class _GenerationSource:
    def __init__(self, events):
        self.events = tuple(events)
        self.index = 0
        self.client = None
        self.queue_depth_reader = None
        self.queue_depth_before_disconnect = None

    @property
    def next_event_time(self):
        if self.index >= len(self.events):
            return None
        return self.events[self.index][0]

    def emit_until(self, utc_time):
        while self.next_event_time is not None and self.next_event_time <= utc_time:
            _when, kind, generation, payload = self.events[self.index]
            self.index += 1
            if kind == "tick":
                self.client.dispatch_tick(payload, generation)
            else:
                if self.queue_depth_reader is not None:
                    self.queue_depth_before_disconnect = self.queue_depth_reader()
                self.client.dispatch_disconnect(payload, generation)


class _GenerationTraderClient:
    is_ready = False

    def __init__(self, **_kwargs):
        self.on_login = None
        self.on_order = None
        self.on_trade = None
        self.on_error = None

    def start(self, block=False):
        assert block is False

    def wait_ready(self, timeout=20):
        return True

    def get_session_state(self):
        return {
            "connected": True,
            "ready": False,
            "auth_state": "unknown",
            "login_state": "unknown",
        }

    def stop(self):
        return None


def _store(monkeypatch, clock, source):
    ctp_client = pytest.importorskip("bt_api_ctp.ctp.client")

    class FakeMdClient(_GenerationMdClient):
        def __init__(self, **kwargs):
            super().__init__(clock=clock, source=source, **kwargs)

    monkeypatch.setattr(ctp_client, "MdClient", FakeMdClient)
    monkeypatch.setattr(ctp_client, "TraderClient", _GenerationTraderClient)
    monkeypatch.delenv("BT_CTP_EXECUTION_AUTHORIZATION_KEY_ID", raising=False)
    monkeypatch.delenv("BT_CTP_EXECUTION_AUTHORIZATION_SECRET", raising=False)
    store = RegisteredSimStore(
        provider="ctp",
        backend="direct",
        preserve_raw_bars=True,
        broker_id="test-broker",
        user_id="test-user",
        investor_id="test-user",
        password="test-password",
        md_front="tcp://127.0.0.1:1",
        td_front="tcp://127.0.0.1:2",
        auto_settlement_confirm=False,
        live_tick_provenance={
            "source": "ac50-11-reconnect-fixture",
            "clock_domain_id": "alpha003-replay-clock-v1",
            # The authenticated SDK generation must override this adapter
            # decoration rather than being rewritten to it.
            "generation": 7,
            "rules_hash": "ac50-11-fixture-rules-v1",
            "session_segment": "regular",
        },
    )
    return store


def _epoch(calendar_day, epoch_id):
    grid = pd.date_range(
        "{} 01:32:00".format(calendar_day), periods=_BAR_COUNT, freq="min", tz="UTC"
    )
    calendar, member_ids = parity._calendar(_TARGETS, grid)
    calendar = replace(calendar, epoch_id=epoch_id)
    cohort = LiveBarCohort(
        "ac50-11-reconnect-epoch-{}".format(epoch_id),
        calendar,
        max_pending_slots=2,
        max_window_bars=_BAR_COUNT,
        wait_timeout_ns=15_000_000_000,
    )
    cerebro = bt.Cerebro(stdstats=False, exactbars=0, preload=False, runonce=False)
    feeds = {}
    for target in _TARGETS:
        feed = bt.feeds.BtApiFeed(
            dataname=target,
            store=None,
            historical_bars=(),
            live_bars=(),
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            bar_watermark_ms=0,
        )
        feeds[target] = feed
        cerebro.adddata(feed, name=target)
    for target in _TARGETS:
        feeds[target].store = None
    # Store assignment occurs before Cerebro activation so each feed remains
    # bound to the same actual Store instance during normal feed startup.
    return cerebro, cohort, feeds, member_ids, grid


def _attach_epoch(
    cerebro,
    cohort,
    feeds,
    member_ids,
    calendar,
    store,
    clock,
    strategy_cls=cold_start._ColdStartStrategy,
):
    for target, feed in feeds.items():
        feed.store = store
        cohort.register_member(
            member_ids[target],
            feed,
            instrument=target,
            source_ref="registered-sim-" + target,
            line_fields=_FIELDS,
            raw_fields=_FIELDS,
            numeric_fields=_FIELDS,
        )
    cohort.seal()
    plan = parity._live_alpha003_plan(
        _TARGETS,
        calendar=calendar,
        mode="native",
        max_pending_slots=cohort.max_pending_slots,
        max_window_bars=cohort.max_window_bars,
        wait_timeout_ns=cohort.wait_timeout_ns,
        max_future_skew_seconds=10.0,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(strategy_cls, cohort=cohort, plan=plan)
    cerebro.broker.setcash(100_000.0)
    assert isinstance(cerebro.broker, bt.brokers.BackBroker)
    return plan


def _shift_rows(rows, *, days, generation):
    shifted = []
    for event_time, instrument, _old_generation, payload in rows:
        shifted_time = event_time + timedelta(days=days)
        local_time = shifted_time.astimezone(cold_start._CTP_TZ)
        copied = SimpleNamespace(**vars(payload))
        copied.TradingDay = local_time.strftime("%Y%m%d")
        copied.ActionDay = local_time.strftime("%Y%m%d")
        copied.UpdateTime = local_time.strftime("%H:%M:%S")
        shifted.append((shifted_time, instrument, generation, copied))
    return tuple(shifted)


@pytest.mark.integration
def test_ctp_disconnect_fences_old_generation_and_rebuilt_epoch_warms_from_raw_ticks(monkeypatch):
    rows, _first_complete_volumes = cold_start._ticks()
    first_partial = tuple(
        (when, "tick", 1, payload) for when, _instrument, _generation, payload in rows[:3]
    )
    disconnect_at = rows[0][0] + timedelta(seconds=5)
    queued_payload, queued_at = cold_start._ctp_tick(_TARGETS[0], "SHFE", 30, 10, 1001, 100.1, 5)
    assert queued_at == disconnect_at
    old_events = first_partial + (
        (queued_at, "tick", 1, queued_payload),
        (disconnect_at, "disconnect", 1, "front_disconnected"),
    )

    clock = cold_start._ReplayClock(datetime(2026, 10, 23, 1, 30, 5, tzinfo=_UTC))
    old_source = _GenerationSource(old_events)
    store = _store(monkeypatch, clock, old_source)
    old_source.queue_depth_reader = lambda: sum(
        len(queue) for queue in store._api._tick_queues.values()
    )

    old_cerebro, old_cohort, old_feeds, old_member_ids, old_grid = _epoch("2026-10-23", 1)
    for feed in old_feeds.values():
        feed.store = store
    _old_calendar, _ = parity._calendar(_TARGETS, old_grid)
    _attach_epoch(
        old_cerebro,
        old_cohort,
        old_feeds,
        old_member_ids,
        _old_calendar,
        store,
        clock,
    )

    with pytest.raises(LiveCohortFrozenError):
        old_cerebro.run()

    assert old_source.queue_depth_before_disconnect >= 1
    assert old_cohort.frozen is True
    assert old_cohort.frozen_reason == "store_stream_generation_changed"
    assert old_cohort.current_batch() is None
    assert all(len(feed) == 0 for feed in old_feeds.values())
    old_health = store.get_stream_health(_TARGETS[0])
    assert old_health["stale"] is True
    assert old_health["source_generation"] == 1
    assert old_health["generation_callbacks_supported"] is True
    assert old_health["source_tick_drop_count"] >= 1
    assert old_health["source_tick_drop_reason"] == "ctp_front_disconnected"
    assert not any(store._api._tick_queues.values())
    store_generation_at_disconnect = old_health["stream_generation"]

    rows_next_day = _shift_rows(rows, days=1, generation=2)
    delayed_old_callback = store._api.md_client.capture_tick_callback(rows_next_day[0][3])
    old_queue_lengths = {target: len(store._api._tick_queues[target]) for target in _TARGETS}

    source_next_day = _GenerationSource(
        tuple(
            (when, "tick", generation, payload)
            for when, _target, generation, payload in rows_next_day
        )
    )
    source_next_day.client = store._api.md_client
    clock.source = source_next_day
    store._api.md_client.reconnect_and_resubscribe(2)

    # The SDK callback was captured while generation 1 held its source lock,
    # then arrives after the client has advanced to generation 2.
    delayed_old_callback()
    assert {
        target: len(store._api._tick_queues[target]) for target in _TARGETS
    } == old_queue_lengths
    assert all(len(feed) == 0 for feed in old_feeds.values())
    assert old_cohort.current_batch() is None

    first_reconnected_time = rows_next_day[0][0]
    clock.wait((first_reconnected_time - clock.utc_now()).total_seconds())
    healthy_generation = store.get_stream_health(_TARGETS[0])
    assert healthy_generation["stale"] is False
    assert healthy_generation["source_generation"] == 2
    assert healthy_generation["stream_generation"] > store_generation_at_disconnect
    assert any(generation == 2 for generation, _items in store._api.md_client.subscriptions)

    new_cerebro, new_cohort, new_feeds, new_member_ids, new_grid = _epoch("2026-10-24", 2)
    new_calendar, _ = parity._calendar(_TARGETS, new_grid)
    new_calendar = replace(new_calendar, epoch_id=2)
    for feed in new_feeds.values():
        feed.store = store
    _attach_epoch(
        new_cerebro,
        new_cohort,
        new_feeds,
        new_member_ids,
        new_calendar,
        store,
        clock,
        strategy_cls=_FirstBatchColdStartStrategy,
    )
    try:
        strategy = new_cerebro.run()[0]
    finally:
        store.stop()

    assert len(strategy.snapshots) == _BAR_COUNT
    assert strategy.first_batch is not None
    assert strategy.first_batch.slot_index == 0
    assert strategy.snapshots[0].readiness is LiveFactorReadiness.WARMUP
    assert all(
        receipt.envelope.connection_generation == 2 and receipt.source_role == "live"
        for receipt in strategy.first_batch.members.values()
    )
    assert all(snapshot.epoch_id == 2 for snapshot in strategy.snapshots)
    ready_index = next(
        index
        for index, snapshot in enumerate(strategy.snapshots)
        if snapshot.readiness is LiveFactorReadiness.LIVE_READY
    )
    assert ready_index >= 29
    assert all(
        snapshot.readiness is LiveFactorReadiness.WARMUP
        for snapshot in strategy.snapshots[:ready_index]
    )
    assert all(
        snapshot.readiness is LiveFactorReadiness.LIVE_READY
        for snapshot in strategy.snapshots[ready_index:]
    )
    assert len(strategy.buy_entries) == 1
    assert old_cohort.frozen is True
    assert old_cohort.current_batch() is None
    assert new_cohort.current_batch() is not None
    for feed in new_feeds.values():
        receipts = new_cohort.complete_window_bars(feed, _FIELDS, _BAR_COUNT)
        assert len(receipts) == _BAR_COUNT
        assert all(receipt.envelope.connection_generation == 2 for receipt in receipts)
        assert all(receipt.source_role == "live" for receipt in receipts)


def test_ctp_wrapper_keeps_legacy_noncohort_tick_polling():
    pytest.importorskip("bt_api_ctp.ctp.client")
    from backtrader.stores.btapistore import _create_ctp_wrapper_class

    wrapper = _create_ctp_wrapper_class()(
        md_address="tcp://127.0.0.1:1",
        td_address="tcp://127.0.0.1:2",
        broker_id="test-broker",
        investor_id="test-user",
        password="test-password",
        auto_settlement_confirm=False,
    )
    legacy_client = SimpleNamespace(on_tick=None, on_error=None, _connection_generation=7)
    wrapper.md_client = legacy_client
    wrapper._bind_md_client_callbacks(legacy_client)

    payload, _ = cold_start._ctp_tick(_TARGETS[0], "SHFE", 30, 5, 1000, 100.0, 0)
    legacy_client.on_tick(payload)

    assert wrapper._get_live_ctp_stream_health()["generation_callbacks_supported"] is False
    assert wrapper.has_pending_tick(_TARGETS[0]) is True
    tick = wrapper.poll_tick(_TARGETS[0])
    assert tick is not None
    assert tick.symbol == _TARGETS[0]
    assert tick.connection_generation == 7
    assert wrapper.has_pending_tick(_TARGETS[0]) is False


def test_ctp_generation_tick_pruning_stops_at_valid_queue_head():
    pytest.importorskip("bt_api_ctp.ctp.client")
    from backtrader.stores.btapistore import _create_ctp_wrapper_class

    class NoIterationDeque(collections.deque):
        def __iter__(self):
            raise AssertionError("healthy tick polling must not scan the queue")

    wrapper = _create_ctp_wrapper_class()(
        md_address="tcp://127.0.0.1:1",
        td_address="tcp://127.0.0.1:2",
        broker_id="test-broker",
        investor_id="test-user",
        password="test-password",
        auto_settlement_confirm=False,
    )
    wrapper._ctp_stream_generation_callbacks = True
    wrapper._ctp_stream_source_generation = 2
    wrapper._ctp_stream_stale = False
    head = SimpleNamespace(connection_generation=2, marker="head")
    stale_tail = SimpleNamespace(connection_generation=1, marker="tail")
    queue = NoIterationDeque((head, stale_tail))
    wrapper._tick_queues[_TARGETS[0]] = queue

    assert wrapper.has_pending_tick(_TARGETS[0]) is True
    assert wrapper.poll_tick(_TARGETS[0]) is head
    assert len(queue) == 1

    # Once the valid head is consumed, the now-exposed stale head is removed
    # without traversing or copying any remaining queue entries.
    assert wrapper.has_pending_tick(_TARGETS[0]) is False
    health = wrapper._get_live_ctp_stream_health()
    assert not queue
    assert health["stale_tick_drop_count"] == 1
    assert health["stale_tick_drop_reason"] == "ctp_tick_queue_generation_mismatch"
