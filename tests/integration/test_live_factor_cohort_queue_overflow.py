"""Cohort fail-closed coverage for bounded BtApiStore tick loss."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from types import SimpleNamespace

import pytest

from backtrader.research.live_cohort import LiveCohortFrozenError
from backtrader.stores.btapistore import BtApiStore
from tests.integration.test_live_factor_cohort_composition import (
    START,
    _bar_event,
    _compose_run,
)
from tests.integration.test_live_factor_cohort_epoch_rebuild import (
    CohortStrategy as EpochCohortStrategy,
    _compose_epoch,
)
from tests.unit.stores.test_btapistore_iteration21 import (
    AsyncSdk,
    SYMBOL,
    VENUE,
    optional_sdk,
)


def _attach_sdk_store(cerebro, feed, *, queue_size=2):
    optional_sdk()
    api = AsyncSdk()
    store = BtApiStore(
        provider="btapi",
        api=api,
        config={
            "exchange_kwargs": api.exchange_kwargs,
            "symbol_routes": {SYMBOL: VENUE},
            "book_queue_size": queue_size,
            "event_batch_size": 16,
        },
        preserve_raw_bars=True,
    )
    feed.store = store
    cerebro.addstore(store)
    return api, store


def _tick_row(index):
    event_time = START + timedelta(seconds=5 + index)
    return {
        "kind": "tick",
        "symbol": SYMBOL,
        "exchange": VENUE,
        "asset_type": "futures",
        "timestamp": event_time.timestamp(),
        "local_time": event_time.timestamp(),
        "clock_domain_id": "clock-replay",
        "sequence": index + 1,
        "previous_sequence": index,
        "ingest_seq": index + 1,
        "connection_generation": "generation-1",
        "subscription_epoch": 1,
        "received_monotonic_ns": 1000 + index,
        "event_id": "overflow-tick-{}".format(index + 1),
        "trade_id": "overflow-trade-{}".format(index + 1),
        "price": 10.0 + index,
        "volume": 1.0,
        "delta_volume": 1.0,
        "volume_semantics": "delta",
        "direction": "buy",
        "snapshot_or_delta": "delta",
        "continuity_status": "continuous",
        "schema_version": "backtrader.tick.v1",
        "trading_day": "2025-01-02",
    }


def test_real_cerebro_freezes_overflow_epoch_then_requires_a_full_new_epoch_rebuild(
    monkeypatch,
):
    names = (SYMBOL, "B")
    cerebro, cohort, feeds, _clock, _sessions, slot = _compose_run(
        names,
        source_by_member={SYMBOL: "tick"},
    )
    api, store = _attach_sdk_store(cerebro, feeds[SYMBOL])
    api.events[VENUE].extend(_tick_row(index) for index in range(3))

    health_reads = []
    read_health = store.get_stream_health

    def observe_health(dataname=None):
        result = read_health(dataname)
        health_reads.append(result)
        return result

    store.get_stream_health = observe_health

    with pytest.raises(LiveCohortFrozenError, match="tick queue continuity changed"):
        cerebro.run()

    assert any(
        isinstance(reading, dict)
        and reading.get("tick_queue_overflow_count") == 1
        and reading.get("stale") is True
        for reading in health_reads
    )
    assert cohort.frozen is True
    assert cohort.frozen_reason == "store_tick_queue_overflow"
    assert cohort.current_batch() is None
    assert all(len(feed) == 0 for feed in feeds.values())

    original_notify_bar = EpochCohortStrategy.notify_bar

    def notify_live_mapping(strategy, bar):
        if isinstance(bar, Mapping):
            bar = SimpleNamespace(symbol=bar["symbol"])
        original_notify_bar(strategy, bar)

    monkeypatch.setattr(EpochCohortStrategy, "notify_bar", notify_live_mapping)
    prior_state = (
        cohort.frozen,
        cohort.current_batch(),
        tuple(len(feed) for feed in feeds.values()),
    )
    new_start = slot.close_time + timedelta(minutes=4)
    new_cerebro, new_cohort, new_calendar, new_feeds = _compose_epoch(
        monkeypatch,
        cohort_id="cohort-after-store-overflow",
        calendar_id="calendar-after-store-overflow",
        version="rebuilt-v1",
        epoch_id=cohort.epoch_id + 1,
        start=new_start,
        generations=("generation-2", "generation-2"),
    )
    new_strategy = new_cerebro.run()[0]

    assert prior_state == (
        cohort.frozen,
        cohort.current_batch(),
        tuple(len(feed) for feed in feeds.values()),
    )
    assert new_calendar.epoch_id == new_cohort.epoch_id == cohort.epoch_id + 1
    assert new_cohort.frozen is False
    assert len(new_strategy.snapshots) == 2
    assert all(snapshot.readiness.value == "LIVE_READY" for snapshot in new_strategy.snapshots)
    assert all(len(feed) == 2 for feed in new_feeds.values())


def test_real_cerebro_rejects_stale_bars_from_btapistore_before_cohort_capture():
    names = (SYMBOL, "B")
    cerebro, cohort, feeds, _clock, sessions, slot = _compose_run(
        names,
        source_by_member={SYMBOL: "store"},
    )
    api, store = _attach_sdk_store(cerebro, feeds[SYMBOL])
    stale_bar = dict(
        _bar_event(
            slot,
            SYMBOL,
            1,
            11.0,
            trading_day=sessions["member-" + SYMBOL].trading_day,
            session_segment=sessions["member-" + SYMBOL].session_segment,
        )
    )
    stale_bar.update(
        {
            "kind": "bar",
            "sequence": 1,
            "event_id": "stale-bar-1",
            "stale": True,
            "stale_reason": "provider_gap",
            "continuity_status": "gap",
        }
    )
    api.events[VENUE].append(stale_bar)

    with pytest.raises(LiveCohortFrozenError, match="stale Store stream"):
        cerebro.run()

    assert cohort.frozen is True
    assert cohort.current_batch() is None
    assert all(len(feed) == 0 for feed in feeds.values())
