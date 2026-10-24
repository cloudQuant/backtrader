"""Bound completed BtApiStore bars without silent loss in live cohorts."""

from __future__ import annotations

import pytest

from backtrader.research.live_cohort import LiveCohortFrozenError
from backtrader.stores.btapistore import BtApiStore
from tests.fixtures.fake_btapi import FakeBtApiClient
from tests.integration.test_live_factor_cohort_composition import (
    _calendar,
    _bar_event,
    _compose_run,
)
from tests.unit.stores.test_btapistore_iteration21 import AsyncSdk, SYMBOL, VENUE, optional_sdk


def _store_bar_event(slot, session, sequence):
    row = dict(
        _bar_event(
            slot,
            SYMBOL,
            sequence,
            10.0 + sequence,
            trading_day=session.trading_day,
            session_segment=session.session_segment,
        )
    )
    row.update(
        {
            "kind": "bar",
            "exchange": VENUE,
            "asset_type": "futures",
            "local_time": slot.close_time.timestamp(),
            "clock_domain_id": "clock-replay",
            "sequence": sequence,
            "previous_sequence": sequence - 1,
            "snapshot_or_delta": "snapshot",
            "continuity_status": "continuous",
            "event_id": "bar-{}".format(sequence),
            "connection_generation": "generation-1",
        }
    )
    return row


def _attach_sdk_store(cerebro, feed, *, api, live_bars=None):
    optional_sdk()
    store = BtApiStore(
        provider="btapi",
        api=api,
        config={
            "exchange_kwargs": api.exchange_kwargs,
            "symbol_routes": {SYMBOL: VENUE},
            "book_queue_size": 4,
            "live_bar_queue_size": 2,
            "event_batch_size": 16,
            "market_drop_record_limit": 8,
        },
        live_bars=live_bars,
        preserve_raw_bars=True,
    )
    feed.store = store
    cerebro.addstore(store)
    return store


@pytest.mark.integration
def test_real_cerebro_freezes_when_bounded_sdk_live_bar_queue_overflows():
    names = (SYMBOL, "B")
    cerebro, cohort, feeds, _clock, sessions, slot = _compose_run(
        names,
        source_by_member={SYMBOL: "store"},
    )
    api = AsyncSdk()
    store = _attach_sdk_store(cerebro, feeds[SYMBOL], api=api)
    api.events[VENUE].extend(
        _store_bar_event(slot, sessions["member-" + SYMBOL], sequence) for sequence in (1, 2, 3)
    )

    with pytest.raises(LiveCohortFrozenError, match="live-bar queue continuity changed"):
        cerebro.run()

    health = store.get_stream_health(SYMBOL)
    assert health["live_bar_queue_capacity"] == 2
    assert health["live_bar_queue_depth"] == 2
    assert health["live_bar_queue_overflow_count"] == 1
    assert health["stale"] is True
    assert health["stale_reason"] == "store_live_bar_queue_overflow"
    assert any(
        row["reason"] == "store_live_bar_queue_overflow" for row in health["market_drop_records"]
    )
    assert cohort.frozen is True
    assert cohort.frozen_reason == "store_live_bar_queue_overflow"
    assert cohort.current_batch() is None
    assert all(len(feed) == 0 for feed in feeds.values())


@pytest.mark.integration
def test_seed_overflow_survives_startup_baseline_and_freezes_before_any_batch():
    names = (SYMBOL, "B")
    cerebro, cohort, feeds, _clock, sessions, slot = _compose_run(
        names,
        source_by_member={SYMBOL: "store"},
    )
    seed = tuple(
        _store_bar_event(slot, sessions["member-" + SYMBOL], sequence) for sequence in (1, 2, 3)
    )
    api = AsyncSdk()
    store = _attach_sdk_store(cerebro, feeds[SYMBOL], api=api, live_bars={SYMBOL: seed})

    seeded_health = store.get_stream_health(SYMBOL)
    assert seeded_health["live_bar_queue_capacity"] == 2
    assert seeded_health["live_bar_queue_depth"] == 2
    assert seeded_health["live_bar_queue_overflow_count"] == 1
    assert seeded_health["stale"] is True
    assert any(
        row["reason"] == "store_live_bar_queue_overflow"
        for row in seeded_health["market_drop_records"]
    )

    with pytest.raises(LiveCohortFrozenError, match="already degraded at startup"):
        cerebro.run()

    started_health = store.get_stream_health(SYMBOL)
    assert started_health["stream_generation"] == 1
    assert started_health["live_bar_queue_overflow_count"] == 1
    assert started_health["stale"] is True
    assert cohort.frozen is True
    assert cohort.current_batch() is None
    assert all(len(feed) == 0 for feed in feeds.values())


def test_legacy_seed_and_push_queues_are_bounded_and_report_each_eviction():
    _calendar_value, sessions = _calendar((SYMBOL,))
    slot = _calendar_value.slots[0]
    session = sessions["member-" + SYMBOL]
    seed = tuple(_store_bar_event(slot, session, sequence) for sequence in range(1, 258))
    store = BtApiStore(
        provider="okx",
        api=FakeBtApiClient(),
        config={"market_drop_record_limit": 8},
        live_bars={SYMBOL: seed},
        preserve_raw_bars=True,
    )

    seed_health = store.get_stream_health(SYMBOL)
    assert seed_health["live_bar_queue_capacity"] == 256
    assert seed_health["live_bar_queue_depth"] == 256
    assert seed_health["live_bar_queue_overflow_count"] == 1
    assert seed_health["stale"] is True

    push_store = BtApiStore(
        provider="okx",
        api=FakeBtApiClient(),
        config={"market_drop_record_limit": 8},
        preserve_raw_bars=True,
    )
    for row in seed:
        push_store.push_live_bar(SYMBOL, row)
    push_health = push_store.get_stream_health(SYMBOL)
    assert push_health["live_bar_queue_capacity"] == 256
    assert push_health["live_bar_queue_depth"] == 256
    assert push_health["live_bar_queue_overflow_count"] == 1
    assert push_health["stale"] is True
    assert any(
        row["reason"] == "store_live_bar_queue_overflow"
        for row in push_health["market_drop_records"]
    )
