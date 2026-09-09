"""Iteration 22 oracle tests for authoritative CTP tick-to-minute causality."""

import datetime as dt

import backtrader as bt
import pytest

from backtrader.events import TickEvent
from backtrader.stores.btapistore import BtApiStoreError
from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_store


class ManualClock:
    def __init__(self):
        self.value_ns = 1

    def monotonic_ns(self):
        return self.value_ns

    def advance(self, seconds):
        self.value_ns += int(seconds * 1_000_000_000)


class ReplayClock:
    def __init__(self):
        self.value = 0.000000001

    def monotonic_now(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def ctp_tick(second, *, price=100.0, delta=1.0, cumulative=101.0, ingest_seq=1):
    base = dt.datetime(2026, 9, 9, 1, 0, tzinfo=dt.timezone.utc)
    timestamp = (base + dt.timedelta(seconds=second)).timestamp()
    event = TickEvent(
        timestamp=timestamp,
        symbol=DEFAULT_SYMBOL,
        exchange="CZCE",
        asset_type="futures",
        local_time=timestamp,
        price=price,
        volume=delta,
        direction="buy",
        bid_price=price - 1.0,
        ask_price=price + 1.0,
        bid_volume=3.0,
        ask_volume=4.0,
    )
    event.datetime = base.replace(tzinfo=None) + dt.timedelta(seconds=second)
    event.schema_version = "ctp.quote.v2"
    event.volume_semantics = "delta"
    event.cum_volume = cumulative
    event.cumulative_volume = cumulative
    event.delta_volume = delta
    event.volume_complete = True
    event.volume_quality = "ok"
    event.trading_day = "20260909"
    event.action_day = "20260909"
    event.event_time_utc = base + dt.timedelta(seconds=second)
    event.recv_time_utc = base + dt.timedelta(seconds=second)
    event.recv_monotonic_ns = event.received_monotonic_ns
    event.connection_generation = 7
    event.ingest_seq = ingest_seq
    event.quality_flags = ()
    event.event_time_source = "action_day_update_time"
    return event


def minute_feed(ticks, clock=None):
    client = FakeBtApiClient(live_ticks={DEFAULT_SYMBOL: ticks})
    store = make_store(api=client)
    feed = store.getdata(
        dataname=DEFAULT_SYMBOL,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        backfill_start=False,
        qcheck=0,
        price_tick=1.0,
        clock=clock,
    )
    return client, store, feed


def tick_feed(ticks, clock=None):
    client = FakeBtApiClient(live_ticks={DEFAULT_SYMBOL: ticks})
    store = make_store(api=client)
    feed = store.getdata(
        dataname=DEFAULT_SYMBOL,
        timeframe=bt.TimeFrame.Ticks,
        compression=1,
        backfill_start=False,
        qcheck=0,
        price_tick=1.0,
        clock=clock,
    )
    return client, store, feed


def test_declared_delta_is_consumed_once_even_when_cumulative_volume_is_present():
    first = ctp_tick(1, delta=7.0, cumulative=107.0, ingest_seq=1)
    second = ctp_tick(61, price=101.0, delta=4.0, cumulative=111.0, ingest_seq=2)
    _, _, feed = minute_feed([first, second])

    feed._start()
    feed._check()

    assert len(feed._live) == 1
    assert feed._live[0]["volume"] == pytest.approx(7.0)
    assert feed.load() is True
    assert feed.volume[0] == pytest.approx(7.0)


def test_tick_timeframe_keeps_multiple_ordered_ctp_ticks_in_one_minute_eligible():
    first = ctp_tick(1, price=100.0, ingest_seq=1)
    second = ctp_tick(2, price=101.0, cumulative=102.0, ingest_seq=2)
    _, _, feed = tick_feed([first, second])
    delivered = []

    class Env:
        _tradingcal = None

        def dispatch_channel_event(self, item):
            if item.channel_type == "tick":
                delivered.append(item.data)

    feed.setenvironment(Env())
    feed._start()
    feed._check()

    assert [item.bar_eligible for item in delivered] == [True, True]
    assert all("LATE_AFTER_WATERMARK" not in item.quality_flags for item in delivered)
    assert all("BUCKET_ALREADY_CLOSED" not in item.quality_flags for item in delivered)
    assert feed.load() is True
    assert feed.close[0] == pytest.approx(100.0)
    assert feed.load() is True
    assert feed.close[0] == pytest.approx(101.0)


def test_declared_cumulative_without_sdk_delta_is_not_differenced_by_feed():
    event = ctp_tick(1, delta=107.0, cumulative=107.0)
    event.volume_semantics = "cumulative"
    del event.delta_volume
    _, _, feed = minute_feed([event])
    delivered = []

    class Env:
        _tradingcal = None

        def dispatch_channel_event(self, item):
            delivered.append(item.data)

    feed.setenvironment(Env())
    feed._start()
    feed._check()

    assert not feed._bar_builders
    assert delivered[0].delta_volume == 0.0
    assert "DELTA_VOLUME_MISSING" in delivered[0].quality_flags
    assert delivered[0].bar_eligible is False


def test_quote_only_snapshot_never_fabricates_trade_ohlc():
    quote = ctp_tick(1, price=100.0, delta=0.0, cumulative=100.0)
    _, _, feed = minute_feed([quote])

    feed._start()
    feed._check()

    assert not feed._bar_builders
    assert not feed._live


def test_minute_bucket_closes_at_end_plus_500ms_and_carries_causal_identity():
    clock = ManualClock()
    trade = ctp_tick(59.999, delta=2.0, cumulative=102.0, ingest_seq=10)
    boundary_quote = ctp_tick(60.0, delta=0.0, cumulative=102.0, ingest_seq=11)
    _, _, feed = minute_feed([trade, boundary_quote], clock=clock)
    bars = []

    class Env:
        _tradingcal = None

        def dispatch_channel_event(self, item):
            if item.channel_type == "bar":
                bars.append(item.data)

    feed.setenvironment(Env())
    feed._start()
    feed._check()

    assert not feed._live
    clock.advance(0.499)
    feed._check()
    assert not feed._live
    clock.advance(0.001)
    feed._check()

    assert len(feed._live) == 1
    assert len(bars) == 1
    bar = bars[0]
    assert bar.bucket_start.isoformat() == "2026-09-09T01:00:00+00:00"
    assert bar.bucket_end.isoformat() == "2026-09-09T01:01:00+00:00"
    assert bar.available_at.isoformat() == "2026-09-09T01:01:00.500000+00:00"
    assert bar.first_ingest_seq == bar.last_ingest_seq == 10
    assert bar.complete is True
    assert bar.quality == "GOOD"
    assert bar.bar_id == bar.decision_version


def test_late_trade_after_watermark_cannot_mutate_delivered_bar():
    clock = ManualClock()
    trade = ctp_tick(59.0, delta=2.0, cumulative=102.0, ingest_seq=10)
    quote = ctp_tick(60.0, delta=0.0, cumulative=102.0, ingest_seq=11)
    client, _, feed = minute_feed([trade, quote], clock=clock)
    delivered = []

    class Env:
        _tradingcal = None

        def dispatch_channel_event(self, item):
            if item.channel_type == "tick":
                delivered.append(item.data)

    feed.setenvironment(Env())
    feed._start()
    feed._check()
    clock.advance(0.5)
    feed._check()
    original = dict(feed._live[0])
    assert feed.load() is True

    client.live_ticks[DEFAULT_SYMBOL].append(
        ctp_tick(59.5, price=99.0, delta=3.0, cumulative=105.0, ingest_seq=12)
    )
    feed._check()

    assert not feed._live
    assert feed.open[0] == pytest.approx(original["open"])
    assert feed.high[0] == pytest.approx(original["high"])
    assert feed.low[0] == pytest.approx(original["low"])
    assert feed.close[0] == pytest.approx(original["close"])
    assert feed.volume[0] == pytest.approx(original["volume"])
    assert "LATE_AFTER_WATERMARK" in delivered[-1].quality_flags
    assert delivered[-1].bar_eligible is False


def test_ctp_crossed_or_off_grid_book_is_dispatched_but_not_bar_eligible():
    event = ctp_tick(1, price=100.5, delta=1.0)
    event.bid_price = 101.0
    event.ask_price = 100.0
    _, _, feed = minute_feed([event])
    delivered = []

    class Env:
        _tradingcal = None

        def dispatch_channel_event(self, item):
            delivered.append(item.data)

    feed.setenvironment(Env())
    feed._start()
    feed._check()

    assert "CROSSED_BOOK" in delivered[0].quality_flags
    assert "LAST_PRICE_OFF_GRID" in delivered[0].quality_flags
    assert delivered[0].execution_eligible is False
    assert delivered[0].bar_eligible is False
    assert not feed._bar_builders


def test_store_rejects_a_second_destructive_tick_consumer_for_same_symbol():
    ticks = [ctp_tick(1)]
    _, store, first = minute_feed(ticks)
    second = store.getdata(
        dataname=DEFAULT_SYMBOL,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        backfill_start=False,
    )

    subscribe_calls = []
    original_subscribe = store.subscribe

    def recording_subscribe(symbol):
        subscribe_calls.append(symbol)
        return original_subscribe(symbol)

    store.subscribe = recording_subscribe
    first._start()
    with pytest.raises(BtApiStoreError, match="authoritative Feed consumer"):
        second._start()
    assert subscribe_calls == [DEFAULT_SYMBOL]


def test_feed_releases_new_tick_claim_when_subscription_fails():
    _, store, feed = minute_feed([])

    def failing_subscribe(_symbol):
        raise RuntimeError("subscription failed")

    store.subscribe = failing_subscribe
    with pytest.raises(RuntimeError, match="subscription failed"):
        feed._start()

    assert DEFAULT_SYMBOL not in store._tick_consumers
    assert feed._tick_consumer_claimed is False


@pytest.mark.parametrize("missing", ["event_time_utc", "recv_time_utc", "recv_monotonic_ns"])
def test_ctp_v2_missing_required_clock_field_is_fail_closed(missing):
    event = ctp_tick(1)
    delattr(event, missing)
    _, _, feed = minute_feed([event])
    delivered = []

    class Env:
        _tradingcal = None

        def dispatch_channel_event(self, item):
            delivered.append(item.data)

    feed.setenvironment(Env())
    feed._start()
    feed._check()

    assert delivered[0].bar_eligible is False
    assert delivered[0].execution_eligible is False
    assert not feed._bar_builders
    assert any("MISSING" in flag for flag in delivered[0].quality_flags)


def test_ctp_v2_conflicting_timestamp_cannot_select_the_bar_bucket():
    event = ctp_tick(1)
    event.timestamp += 60.0
    _, _, feed = minute_feed([event])
    delivered = []

    class Env:
        _tradingcal = None

        def dispatch_channel_event(self, item):
            delivered.append(item)

    feed.setenvironment(Env())
    feed._start()
    feed._check()

    assert delivered[0].timestamp == event.event_time_utc.timestamp()
    assert "EVENT_TIME_CONFLICT" in delivered[0].data.quality_flags
    assert delivered[0].data.bar_eligible is False
    assert not feed._bar_builders


def test_bad_volume_snapshot_invalidates_an_existing_bucket_before_rejection():
    clock = ManualClock()
    trade = ctp_tick(1, delta=2.0, cumulative=102.0, ingest_seq=1)
    gap = ctp_tick(2, delta=0.0, cumulative=109.0, ingest_seq=2)
    gap.quality_flags = ("VOLUME_GAP",)
    boundary = ctp_tick(60, delta=0.0, cumulative=109.0, ingest_seq=3)
    _, _, feed = minute_feed([trade, gap, boundary], clock=clock)
    bars = []

    class Env:
        _tradingcal = None

        def dispatch_channel_event(self, item):
            if item.channel_type == "bar":
                bars.append(item.data)

    feed.setenvironment(Env())
    feed._start()
    feed._check()
    clock.advance(0.5)
    feed._check()

    assert len(bars) == 1
    assert bars[0].complete is False
    assert "VOLUME_GAP" in bars[0].quality_flags
    assert not feed._live


def test_incomplete_positive_delta_invalidates_the_existing_minute_bucket():
    clock = ManualClock()
    trade = ctp_tick(1, delta=2.0, cumulative=102.0, ingest_seq=1)
    incomplete = ctp_tick(2, delta=3.0, cumulative=105.0, ingest_seq=2)
    incomplete.volume_complete = False
    boundary = ctp_tick(60, delta=0.0, cumulative=105.0, ingest_seq=3)
    _, _, feed = minute_feed([trade, incomplete, boundary], clock=clock)
    bars = []

    class Env:
        _tradingcal = None

        def dispatch_channel_event(self, item):
            if item.channel_type == "bar":
                bars.append(item.data)

    feed.setenvironment(Env())
    feed._start()
    feed._check()
    clock.advance(0.5)
    feed._check()

    assert len(bars) == 1
    assert bars[0].complete is False
    assert "VOLUME_INCOMPLETE" in bars[0].quality_flags
    assert not feed._live


def test_replay_clock_monotonic_now_drives_watermark_without_host_clock():
    clock = ReplayClock()
    trade = ctp_tick(59.0, delta=2.0, cumulative=102.0, ingest_seq=1)
    quote = ctp_tick(60.0, delta=0.0, cumulative=102.0, ingest_seq=2)
    _, _, feed = minute_feed([trade, quote], clock=clock)

    feed._start()
    feed._check()
    assert not feed._live
    clock.advance(0.5)
    feed._check()

    assert len(feed._live) == 1
    assert feed._live[0]["volume"] == pytest.approx(2.0)


def test_finite_tick_source_pairs_each_bar_callback_with_the_next_line_turn():
    base = dt.datetime(2026, 9, 9, 1, 0, tzinfo=dt.timezone.utc)

    class FiniteClient(FakeBtApiClient):
        def is_source_exhausted(self, _symbol):
            return not self.live_ticks.get(DEFAULT_SYMBOL)

        def get_source_event_time_watermark(self, _symbol):
            return base + dt.timedelta(seconds=180.5)

    ticks = [
        ctp_tick(0, price=100.0, ingest_seq=1),
        ctp_tick(61, price=101.0, cumulative=102.0, ingest_seq=2),
        ctp_tick(121, price=102.0, cumulative=103.0, ingest_seq=3),
    ]
    client = FiniteClient(live_ticks={DEFAULT_SYMBOL: ticks})
    store = make_store(api=client)
    feed = store.getdata(
        dataname=DEFAULT_SYMBOL,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        backfill_start=False,
        qcheck=0,
        price_tick=1.0,
    )
    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    cerebro.setbroker(store.getbroker())
    cerebro.adddata(feed)

    class CausalStrategy(bt.Strategy):
        def __init__(self):
            self.bar_events = []
            self.next_pairs = []

        def notify_bar(self, bar):
            self.bar_events.append(bar)

        def next(self):
            # Exactly one newly completed callback must correspond to this
            # line advance; a future bar callback cannot run first.
            assert len(self.bar_events) == len(self.next_pairs) + 1
            bar = self.bar_events[-1]
            self.next_pairs.append((bar.bar_id, self.data.datetime.datetime(0)))

    cerebro.addstrategy(CausalStrategy)
    [strategy] = cerebro.run(preload=False, runonce=False)

    assert len(strategy.bar_events) == len(strategy.next_pairs) == 3
    assert [item[1] for item in strategy.next_pairs] == [
        base.replace(tzinfo=None),
        (base + dt.timedelta(minutes=1)).replace(tzinfo=None),
        (base + dt.timedelta(minutes=2)).replace(tzinfo=None),
    ]
    assert not feed._bar_builders


def test_override_only_invalid_buckets_are_pruned_by_the_watermark():
    ticks = [ctp_tick(index * 60 + 1, price=100.5, ingest_seq=index + 1) for index in range(250)]
    _, _, feed = minute_feed(ticks)

    feed._start()
    feed._check()

    assert not feed._bar_builders
    assert len(feed._bar_quality_overrides) <= 1


def test_generation_change_invalidates_the_entire_shared_minute_bucket():
    first = ctp_tick(1, price=100.0, ingest_seq=1)
    changed = ctp_tick(2, price=101.0, ingest_seq=2)
    changed.connection_generation = 8
    same_bucket = ctp_tick(3, price=102.0, ingest_seq=3)
    same_bucket.connection_generation = 8
    next_bucket = ctp_tick(61, price=103.0, ingest_seq=4)
    next_bucket.connection_generation = 8
    watermark = ctp_tick(121, price=104.0, ingest_seq=5)
    watermark.connection_generation = 8
    _, _, feed = minute_feed([first, changed, same_bucket, next_bucket, watermark])
    bars = []

    class Env:
        _tradingcal = None

        def dispatch_channel_event(self, item):
            if item.channel_type == "bar":
                bars.append(item.data)

    feed.setenvironment(Env())
    feed._start()
    for _ in range(5):
        feed._check()

    shared_bucket = [
        bar for bar in bars if bar.bucket_start.isoformat() == "2026-09-09T01:00:00+00:00"
    ]
    assert len(shared_bucket) == 1
    assert shared_bucket[0].complete is False
    assert "CONNECTION_GENERATION_CHANGED" in shared_bucket[0].quality_flags
    assert all(item["datetime"] != dt.datetime(2026, 9, 9, 1, 0) for item in feed._live)
