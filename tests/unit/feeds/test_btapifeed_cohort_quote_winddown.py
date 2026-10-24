"""Quote-only ticks remain available during bounded cohort winddown."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import backtrader as bt
import pytest

from backtrader.events import TickEvent
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveCohortFrozenError,
)


UTC = timezone.utc
START = datetime(2025, 1, 2, 9, 30, tzinfo=UTC)
FIELDS = ("open", "high", "low", "close", "volume", "openinterest")


class ReplayClock:
    def __init__(self, now):
        self.now = now
        self.monotonic = 1_000_000_000
        self.waits = []

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        return self.monotonic

    def wait(self, timeout_seconds):
        self.waits.append(timeout_seconds)
        elapsed_ns = max(1, round(timeout_seconds * 1_000_000_000))
        self.monotonic += elapsed_ns
        self.now += timedelta(microseconds=elapsed_ns / 1_000)


class QueueTickStore:
    """Small Store leaf with the same feed lifecycle and health surface."""

    def __init__(self):
        self.ticks = defaultdict(deque)
        self.poll_results = []
        self.started = []
        self.registered = []
        self.subscribed = []

    def start(self, data=None):
        self.started.append(data)

    def stop(self):
        pass

    def register(self, feed):
        self.registered.append(feed)

    def subscribe(self, symbol):
        self.subscribed.append(symbol)

    def get_notifications(self):
        return ()

    def get_stream_health(self, _symbol):
        return {
            "stream_generation": 1,
            "tick_queue_overflow_count": 0,
            "stale": False,
        }

    def poll_tick(self, symbol):
        event = self.ticks[symbol].popleft() if self.ticks[symbol] else None
        if event is not None:
            self.poll_results.append((symbol, event))
        return event

    def enqueue(self, symbol, event):
        self.ticks[symbol].append(event)


class CountingIndicator(bt.Indicator):
    lines = ("value",)

    def __init__(self):
        self.calls = 0

    def next(self):
        self.calls += 1
        self.lines.value[0] = self.data.close[0]


class PollingBroker(bt.brokers.BackBroker):
    next_without_bar = True

    def __init__(self):
        super().__init__()
        self.next_calls = 0

    def next(self):
        self.next_calls += 1
        return super().next()


class QuoteWinddownStrategy(bt.Strategy):
    params = (
        ("clock", None),
        ("store", None),
        ("symbols", ()),
        ("generation_rollover", False),
    )
    instances = []

    def __init__(self):
        type(self).instances.append(self)
        self.indicator = CountingIndicator(self.data0)
        self.next_calls = 0
        self.idle_calls = 0
        self.ticks = []
        self.tick_cutoff = None
        self.seeded = False
        self.shutdown_ready = False
        self.final_snapshot = None

    def next(self):
        self.next_calls += 1
        batch = self.cerebro.live_bar_cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        self.final_snapshot = {
            "lengths": tuple(len(data) for data in self.datas),
            "indicator_calls": self.indicator.calls,
            "feed_counters": tuple(
                (
                    data._test_check_calls,
                    data._test_last_calls,
                    data._test_ingest_calls,
                    data._test_flush_calls,
                )
                for data in self.datas
            ),
            "batch_id": batch.batch_id,
        }

    def notify_tick(self, tick):
        self.ticks.append(tick)

    def notify_idle(self):
        self.idle_calls += 1
        if not self.seeded:
            self.seeded = True
            self.tick_cutoff = self.p.clock.utc_now()
            # The event source time follows the latest facts-time observation
            # made by notify_idle; the Store and Feed retain that real time.
            for index, symbol in enumerate(self.p.symbols, start=1):
                self.p.store.enqueue(symbol, _quote_tick(symbol, self.p.clock, index))
                if self.p.generation_rollover and symbol == "B":
                    self.p.store.enqueue(
                        symbol,
                        _quote_tick(symbol, self.p.clock, index + 1, generation=2),
                    )
        if {tick.symbol for tick in self.ticks} == set(self.p.symbols):
            self.shutdown_ready = True
            self.cerebro.runstop()


def _bar_event(slot, symbol):
    close = 10.0 if symbol == "A" else 20.0
    return MappingProxyType(
        {
            "instrument": symbol,
            "symbol": symbol,
            "timestamp": slot.close_time.timestamp(),
            "datetime": slot.close_time,
            "bucket_start": slot.bucket_start,
            "bucket_end": slot.close_time,
            "available_at": slot.close_time,
            "trading_day": slot.trading_day,
            "session_segment": slot.session_segment,
            "timezone_id": "UTC",
            "clock_domain_id": "winddown-clock",
            "connection_generation": "generation-1",
            "bar_sequence": 1,
            "bar_id": f"{symbol}-1",
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1.0,
            "openinterest": 0.0,
            "present": True,
            "complete": True,
            "quality": "GOOD",
            "quality_flags": (),
            "source": "finite-winddown-replay",
        }
    )


def _quote_tick(
    symbol,
    clock,
    sequence,
    *,
    generation=1,
    stale=False,
    continuity="continuous",
):
    received = clock.utc_now()
    event_time = received + timedelta(milliseconds=5 * sequence)
    price = 100.0
    raw_ctp = {
        "InstrumentID": symbol,
        "ExchangeID": "CFFEX",
        "LastPrice": price,
        "Volume": sequence,
        "TradingDay": "20250102",
        "ActionDay": "20250102",
        "UpdateTime": event_time.strftime("%H:%M:%S"),
        "UpdateMillisec": event_time.microsecond // 1000,
        "connection_generation": generation,
    }
    tick = TickEvent(
        timestamp=event_time.timestamp(),
        symbol=symbol,
        exchange="CFFEX",
        asset_type="futures",
        local_time=received.timestamp(),
        price=price,
        volume=1.0,
        direction="buy",
        bid_price=99.99,
        ask_price=100.01,
        bid_volume=3.0,
        ask_volume=4.0,
        clock_domain_id="winddown-clock",
        sequence=sequence,
        continuity_status=continuity,
        stale=stale,
        stale_reason="feed stale" if stale else "",
        source="synthetic-provider-tick",
    )
    tick.datetime = event_time.replace(tzinfo=None)
    tick.schema_version = "ctp.quote.v2"
    tick.volume_semantics = "delta"
    tick.delta_volume = 1.0
    tick.cum_volume = float(sequence)
    tick.volume_complete = True
    tick.trading_day = "20250102"
    tick.action_day = "20250102"
    tick.event_time_utc = event_time
    tick.recv_time_utc = received
    tick.recv_monotonic_ns = clock.monotonic_ns()
    tick.clock_domain_id = "winddown-clock"
    tick.connection_generation = generation
    tick.ingest_seq = sequence
    tick.subscription_epoch = 1
    tick.source_clock_quality = "verified"
    tick.receive_clock_quality = "verified"
    tick.freshness_verified = True
    tick.execution_eligible = True
    tick.quality_flags = ()
    tick.ctp_raw_tick = raw_ctp
    return tick


def _build_run(
    monkeypatch,
    *,
    count_budget=1,
    first_tick_stale=False,
    generation_rollover=False,
):
    QuoteWinddownStrategy.instances.clear()
    slot = LiveCalendarSlot(
        "slot-0",
        START,
        START + timedelta(minutes=1),
        "2025-01-02",
        "regular",
    )
    calendar = LiveCohortCalendar(
        calendar_id="winddown-calendar",
        version="v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="winddown-clock",
        session_semantics="session-v1",
        slots=(slot,),
    )
    cohort = LiveBarCohort(
        "winddown-cohort",
        calendar,
        max_pending_slots=1,
        max_window_bars=1,
        wait_timeout_ns=1_000_000_000,
    )
    clock = ReplayClock(slot.close_time)
    store = QueueTickStore()
    feeds = []
    for symbol in ("A", "B"):
        feed = bt.feeds.BtApiFeed(
            dataname=symbol,
            store=store,
            historical_bars=(_bar_event(slot, symbol),),
            live_bars=(),
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            price_tick=0.01,
            clock=clock,
        )
        cohort.register_member(
            "member-" + symbol,
            feed,
            instrument=symbol,
            source_ref="source-" + symbol,
            line_fields=FIELDS,
            raw_fields=FIELDS,
            numeric_fields=FIELDS,
        )
        feeds.append(feed)

    for feed in feeds:
        feed._test_check_calls = 0
        feed._test_last_calls = 0
        feed._test_ingest_calls = 0
        feed._test_flush_calls = 0
        for name, attr in (
            ("_check", "_test_check_calls"),
            ("_last", "_test_last_calls"),
            ("_ingest_tick", "_test_ingest_calls"),
            ("_flush_ready_bars", "_test_flush_calls"),
        ):
            original = getattr(feed, name)

            def tracked(*args, _original=original, _attr=attr, _feed=feed, **kwargs):
                setattr(_feed, _attr, getattr(_feed, _attr) + 1)
                return _original(*args, **kwargs)

            setattr(feed, name, tracked)

    if first_tick_stale:
        original_enqueue = store.enqueue

        def enqueue(symbol, event):
            if symbol == "A":
                event.stale = True
                event.stale_reason = "feed stale"
                event.continuity_status = "gap"
            original_enqueue(symbol, event)

        store.enqueue = enqueue

    monkeypatch.setattr(
        "backtrader._cerebro.runnext._LIVE_COHORT_WINDDOWN_TICK_BUDGET", count_budget
    )
    cerebro = bt.Cerebro(stdstats=False, preload=False, runonce=False)
    for symbol, feed in zip(("A", "B"), feeds):
        cerebro.adddata(feed, name=symbol)
    cerebro.addstore(store)
    cerebro.addstrategy(
        QuoteWinddownStrategy,
        clock=clock,
        store=store,
        symbols=("A", "B"),
        generation_rollover=generation_rollover,
    )
    broker = PollingBroker()
    cerebro.setbroker(broker)
    cerebro.add_live_bar_cohort(cohort, clock=clock, winddown_timeout_seconds=2.0)
    return cerebro, cohort, feeds, clock, store, broker


def test_quote_only_winddown_delivers_fair_ticks_without_bar_or_factor_advance(monkeypatch):
    cerebro, cohort, feeds, _clock, store, broker = _build_run(monkeypatch, count_budget=1)

    strategy = cerebro.run()[0]

    assert cerebro.live_bar_cohort_winddown_status == "STOPPED"
    assert cohort.current_batch() is not None
    assert strategy.next_calls == 1
    assert strategy.shutdown_ready is True
    assert len(strategy.ticks) == 2
    assert {tick.symbol for tick in strategy.ticks} == {"A", "B"}
    assert [symbol for symbol, _tick in store.poll_results] == ["B", "A"]
    assert all(tick.execution_eligible is True for tick in strategy.ticks)
    assert all(tick.quality == "GOOD" for tick in strategy.ticks)
    assert all(tick.event_time_utc > strategy.tick_cutoff for tick in strategy.ticks)
    assert broker.next_calls >= 2
    assert strategy.idle_calls >= 2
    assert strategy.final_snapshot["lengths"] == (1, 1)
    assert tuple(len(feed) for feed in feeds) == strategy.final_snapshot["lengths"]
    assert strategy.indicator.calls == strategy.final_snapshot["indicator_calls"] == 1
    assert (
        tuple(
            (
                feed._test_check_calls,
                feed._test_last_calls,
                feed._test_ingest_calls,
                feed._test_flush_calls,
            )
            for feed in feeds
        )
        == strategy.final_snapshot["feed_counters"]
    )


def test_quote_only_winddown_freezes_on_stale_or_gapped_source_tick(monkeypatch):
    cerebro, cohort, feeds, _clock, _store, _broker = _build_run(
        monkeypatch,
        count_budget=1,
        first_tick_stale=True,
    )

    with pytest.raises(LiveCohortFrozenError, match="unhealthy tick"):
        cerebro.run()

    strategy = QuoteWinddownStrategy.instances[-1]
    assert cohort.frozen is True
    assert [tick.symbol for tick in strategy.ticks] == ["B"]
    assert strategy.ticks[0].execution_eligible is True
    assert strategy.final_snapshot["lengths"] == (1, 1)
    assert tuple(len(feed) for feed in feeds) == (1, 1)
    assert strategy.indicator.calls == strategy.final_snapshot["indicator_calls"] == 1


def test_quote_only_poll_failure_freezes_and_preserves_source_exception(monkeypatch):
    cerebro, cohort, feeds, clock, store, _broker = _build_run(monkeypatch, count_budget=1)
    poll_error = OSError("sentinel quote poll failure")
    poll_calls = []
    original_poll = store.poll_tick

    def poll_with_winddown_failure(symbol):
        poll_calls.append(symbol)
        strategy = QuoteWinddownStrategy.instances[-1] if QuoteWinddownStrategy.instances else None
        if strategy is not None and strategy.seeded:
            raise poll_error
        return original_poll(symbol)

    monkeypatch.setattr(store, "poll_tick", poll_with_winddown_failure)

    with pytest.raises(OSError) as raised:
        cerebro.run()

    assert raised.value is poll_error
    assert cohort.frozen is True
    assert cohort._frozen_reason == "winddown_quote_poll_failed"
    strategy = QuoteWinddownStrategy.instances[-1]
    assert strategy.seeded is True
    assert strategy.final_snapshot is not None
    assert [tick.symbol for tick in strategy.ticks] == []
    assert tuple(len(feed) for feed in feeds) == strategy.final_snapshot["lengths"] == (1, 1)
    assert strategy.indicator.calls == strategy.final_snapshot["indicator_calls"] == 1

    attempts_at_failure = len(poll_calls)
    deadline_ns = clock.monotonic_ns() + 1_000_000
    for feed in feeds:
        assert feed._cohort_drain_winddown_quotes(limit=1, deadline_ns=deadline_ns) == 0
    assert len(poll_calls) == attempts_at_failure


def test_quote_only_scope_change_keeps_quote_ineligible_without_flushing_bars(monkeypatch):
    cerebro, _cohort, feeds, _clock, _store, _broker = _build_run(
        monkeypatch,
        count_budget=64,
        generation_rollover=True,
    )

    strategy = cerebro.run()[0]

    b_ticks = [tick for tick in strategy.ticks if tick.symbol == "B"]
    assert len(b_ticks) == 2
    assert b_ticks[0].execution_eligible is True
    assert b_ticks[1].connection_generation == 2
    assert b_ticks[1].execution_eligible is False
    assert "CONNECTION_GENERATION_CHANGED" in b_ticks[1].quality_flags
    assert strategy.final_snapshot["lengths"] == tuple(len(feed) for feed in feeds) == (1, 1)
    assert (
        tuple(
            (
                feed._test_check_calls,
                feed._test_last_calls,
                feed._test_ingest_calls,
                feed._test_flush_calls,
            )
            for feed in feeds
        )
        == strategy.final_snapshot["feed_counters"]
    )
