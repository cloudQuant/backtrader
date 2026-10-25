"""Keep CTP exchange days compact through live cohort capture and ISO on tape."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
import time

import pytest

import backtrader as bt
from backtrader.events import BarEvent
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCohortCalendar,
    LiveCohortValidationError,
)
from tests.integration import test_ctp_live_midnight_trading_day as ctp_fixture
from tests.unit.test_alpha003_simnow_runner import RUNNER


def _active_fixture(monkeypatch, *, trading_day=None):
    planned_minute, _next_minute = ctp_fixture._planned_night_closes()
    planned_member = planned_minute.members[0]
    compact_day = planned_member.trading_day.strftime("%Y%m%d")
    slots = RUNNER._calendar_slots(
        SimpleNamespace(minutes=(planned_minute,)), ctp_trading_days=True
    )
    calendar = LiveCohortCalendar(
        calendar_id="synthetic-ctp-calendar",
        version="fixture-v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="Asia/Shanghai",
        clock_domain_id="synthetic-ctp-clock",
        session_semantics="fixture-ctp-session",
        slots=slots,
    )
    cohort = LiveBarCohort("synthetic-ctp-date-cohort", calendar, max_pending_slots=1)
    store = ctp_fixture._store(monkeypatch)
    day = compact_day if trading_day is None else trading_day
    feed = bt.feeds.BtApiFeed(
        dataname=ctp_fixture._SYMBOL,
        store=store,
        backfill_start=False,
        cohort_source_mode=True,
        historical_bars=(),
        live_bars=(),
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        bar_watermark_ms=0,
        price_tick=0.2,
        dispatch_ticks=True,
    )
    member_id = "{}.{}".format(planned_member.product.exchange_id, planned_member.product.product_id)
    rules_hash = "a" * 64
    cohort.register_member(
        member_id,
        feed,
        instrument=ctp_fixture._SYMBOL,
        source_ref="synthetic://ctp-date-feed",
        line_fields=("open", "high", "low", "close", "volume"),
        raw_fields=("open", "high", "low", "close", "volume"),
        clock_domain_id="synthetic-ctp-clock",
        timezone_id="Asia/Shanghai",
        session_semantics="fixture-ctp-session",
        rules_hash=rules_hash,
    )
    provenance = {
        "clock_domain_id": "synthetic-ctp-clock",
        "rules_hash": rules_hash,
        "session_segment": planned_member.session_id,
    }
    store._api_kwargs["live_tick_provenance"] = provenance
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.adddata(feed)
    cerebro.add_live_bar_cohort(
        cohort,
        clock=SimpleNamespace(
            utc_now=lambda: slots[0].close_time,
            monotonic_ns=time.monotonic_ns,
            wait=lambda _timeout: False,
        ),
    )
    cerebro._activate_live_bar_cohort()
    # Start the real RegisteredSimStore and its real CTP wrapper. The only
    # substituted components are the provider SDK leaves from _store().
    # Cerebro's real dispatcher is present so the Store does not mark source
    # ticks as undelivered continuity gaps.
    feed._start()
    api = store._api
    assert type(api).__mro__[1].__name__ == "RegisteredSimWrapper"
    assert api.live_tick_provenance == provenance
    source_ticks = []
    poll_tick = store.poll_tick

    def capture_source_tick(symbol):
        event = poll_tick(symbol)
        if event is not None:
            source_ticks.append(event)
        return event

    monkeypatch.setattr(store, "poll_tick", capture_source_tick)
    return feed, store, api, cohort, slots[0], planned_member, day, source_ticks


def _dispatch_first_complete_bar(api, trading_day):
    md = api.md_client
    source_day = ctp_fixture._TRADING_DAY if trading_day is None else trading_day
    for local_text, cumulative, price in (
        ("2026-10-21T23:59:05", 1000, 100.0),
        ("2026-10-21T23:59:35", 1030, 100.5),
        ("2026-10-22T00:00:05", 1036, 101.0),
        ("2026-10-22T00:00:35", 1041, 102.0),
        ("2026-10-22T00:01:05", 1042, 101.5),
    ):
        local_time = ctp_fixture.datetime.fromisoformat(local_text).replace(
            tzinfo=ctp_fixture._CHINA
        )
        payload = ctp_fixture._ctp_tick(local_time, cumulative, price)
        payload.TradingDay = source_day
        md.dispatch_tick(payload)


def test_live_ctp_compact_day_survives_wrapper_aggregation_and_cohort_capture(monkeypatch):
    feed, store, api, cohort, slot, member, _day, source_ticks = _active_fixture(monkeypatch)
    try:
        _dispatch_first_complete_bar(api, None)
        health = store.get_stream_health(feed._dataname)
        assert health["stale"] is False, health
        assert feed._drain_live_ticks(limit=8, stop_after_queued_bar=False) is True
        event = feed._cohort_completed_lookahead
        assert isinstance(event, BarEvent)
        assert feed._cohort_capture_source(event, "live", time.monotonic_ns(), 0) is True
        prepared = cohort.prepare_round(
            time.monotonic_ns(),
            source_time_utc=slot.close_time + timedelta(minutes=2),
        )
        assert prepared.status == "READY"
        envelope = prepared.prepared.envelope_for_feed(feed)
        assert event.trading_day == "20261022"
        assert [tick.ctp_raw_tick["TradingDay"] for tick in source_ticks] == [
            "20261022"
        ] * 5
        assert len(source_ticks) == 5
        assert event.quality == "GOOD"
        assert event.volume == 11.0

        assert envelope.trading_day == "20261022"
        assert envelope.session_segment == member.session_id
        assert envelope.close_time == slot.close_time
        assert slot.trading_day == "20261022"
        assert cohort.frozen is False
    finally:
        feed.stop()
        store.stop()


def test_live_ctp_invalid_compact_day_fails_in_the_existing_raw_guard(monkeypatch):
    feed, store, api, cohort, _slot, _member, _day, _source_ticks = _active_fixture(
        monkeypatch, trading_day="20261032"
    )
    try:
        local_time = ctp_fixture.datetime.fromisoformat("2026-10-21T23:59:05").replace(
            tzinfo=ctp_fixture._CHINA
        )
        payload = ctp_fixture._ctp_tick(local_time, 1000, 100.0)
        payload.TradingDay = "20261032"
        api.md_client.dispatch_tick(payload)
        with pytest.raises(LiveCohortValidationError) as exc_info:
            feed._drain_live_ticks(limit=1)
        assert exc_info.value.code == "TRADING_DAY_INVALID"
        assert cohort.frozen is True
        assert cohort.frozen_reason == "invalid_source_trading_day"
    finally:
        feed.stop()
        store.stop()


def test_valid_but_wrong_compact_day_still_fails_the_exact_planned_slot(monkeypatch):
    feed, store, api, cohort, _slot, _member, _day, source_ticks = _active_fixture(
        monkeypatch, trading_day="20261023"
    )
    try:
        _dispatch_first_complete_bar(api, "20261023")
        assert feed._drain_live_ticks(limit=8, stop_after_queued_bar=False) is True
        assert len(source_ticks) == 5
        assert [tick.ctp_raw_tick["TradingDay"] for tick in source_ticks] == [
            "20261023"
        ] * 5
        event = feed._cohort_completed_lookahead
        assert isinstance(event, BarEvent)
        assert event.trading_day == "20261023"
        with pytest.raises(LiveCohortValidationError, match="trading day/session"):
            feed._cohort_capture_source(event, "live", time.monotonic_ns(), 0)
        assert cohort.frozen is True
        assert cohort.frozen_reason == "invalid_source_bar"
    finally:
        feed.stop()
        store.stop()


def test_replay_calendar_defaults_to_iso_and_tape_accepts_both_day_forms():
    planned_minute, _next_minute = ctp_fixture._planned_night_closes()
    grid = SimpleNamespace(minutes=(planned_minute,))
    iso_day = planned_minute.members[0].trading_day.isoformat()
    compact_day = planned_minute.members[0].trading_day.strftime("%Y%m%d")

    assert RUNNER._calendar_slots(grid)[0].trading_day == iso_day
    assert RUNNER._calendar_slots(grid, ctp_trading_days=True)[0].trading_day == compact_day
    assert RUNNER._tape_trading_day(iso_day, "trading_day") == iso_day
    assert RUNNER._tape_trading_day(compact_day, "trading_day") == iso_day
    with pytest.raises(RUNNER.RunnerError, match="INPUT_DATE_INVALID"):
        RUNNER._tape_trading_day("20261032", "trading_day")
