"""R71-140: supported time buckets for BtApiFeed tick aggregation."""

from __future__ import annotations

import datetime as dt

import pytest

pytest.importorskip("bt_api_py.market_tick_contracts")

import backtrader as bt  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402
from backtrader.feeds.market_tick_adapter import adapt_market_tick_event  # noqa: E402
from tests.unit.feeds import test_market_tick_adapter_baseline as typed  # noqa: E402


UTC = dt.timezone.utc


class _AggregationDriver:
    """Drive the same typed-tick aggregation path used by the live feed."""

    def __init__(self, *, timeframe, compression):
        self.feed = BtApiFeed(
            dataname="SA609",
            store=None,
            timeframe=timeframe,
            compression=compression,
            price_tick=1.0,
            event_time_max_age=1e9,
            receive_time_max_age=1e9,
            bar_watermark_ms=0,
        )
        self.bars = []
        self.feed._enqueue_bar_event = lambda event, when, **_kw: self.bars.append(
            (
                when,
                event.open,
                event.high,
                event.low,
                event.close,
                event.volume,
            )
        )
        self.sequence = 7

    def tick(self, when, price):
        self.sequence += 1
        stamp = when.isoformat().replace("+00:00", "Z")
        event = typed.bind_market_tick_event(
            typed._payload(
                last_price=price,
                delta_volume=1.0,
                provider_event_time_utc=stamp,
                received_at_utc=stamp,
                provider_sequence=self.sequence,
            ),
            typed.SOURCE,
            typed.MarketEventCursor(
                stream_id=typed.SOURCE.stream_id,
                epoch=typed.SOURCE.epoch,
                sequence=self.sequence,
            ),
        )
        tick = adapt_market_tick_event(event)
        self.feed._prepare_tick(tick)
        assert not self.feed._handle_event_health(tick)
        self.feed._ingest_tick(tick)
        self.feed._flush_ready_bars(reason="tick")


def test_day_compression_two_uses_unix_epoch_aligned_calendar_buckets():
    feed = BtApiFeed(
        dataname="SA609",
        store=None,
        timeframe=bt.TimeFrame.Days,
        compression=2,
    )

    before_epoch = dt.datetime(1969, 12, 31, 23, 59, 59)
    epoch = dt.datetime(1970, 1, 1, 17, 30)
    second_day = dt.datetime(1970, 1, 2, 9, 0)
    next_bucket = dt.datetime(1970, 1, 3, 9, 0)

    assert feed._get_bucket_start(before_epoch) == dt.datetime(1969, 12, 30)
    assert feed._get_bucket_start(epoch) == dt.datetime(1970, 1, 1)
    assert feed._get_bucket_start(second_day) == dt.datetime(1970, 1, 1)
    assert feed._get_bucket_start(next_bucket) == dt.datetime(1970, 1, 3)
    assert feed._get_bucket_end(dt.datetime(1970, 1, 1)) == dt.datetime(1970, 1, 3)
    shanghai = dt.timezone(dt.timedelta(hours=8))
    assert feed._get_bucket_start(dt.datetime(1970, 1, 2, 7, tzinfo=shanghai)) == dt.datetime(
        1970, 1, 1, 8, tzinfo=shanghai
    )


def test_day_buckets_use_utc_epoch_through_dst_and_leap_day():
    zoneinfo = pytest.importorskip("zoneinfo")
    try:
        eastern = zoneinfo.ZoneInfo("America/New_York")
    except zoneinfo.ZoneInfoNotFoundError:
        pytest.skip("IANA time-zone data unavailable")
    feed = BtApiFeed(
        dataname="SA609",
        store=None,
        timeframe=bt.TimeFrame.Days,
        compression=2,
    )
    dst_tick = dt.datetime(2026, 3, 8, 12, tzinfo=eastern)
    dst_start = dt.datetime(2026, 3, 8, 0, tzinfo=UTC)
    leap_day = dt.datetime(2024, 2, 29, 12)

    assert feed._get_bucket_start(dst_tick).astimezone(UTC) == dst_start
    assert feed._get_tick_bucket_end(feed._get_bucket_start(dst_tick)).astimezone(UTC) == (
        dst_start + dt.timedelta(days=2)
    )
    assert feed._get_bucket_start(leap_day) == dt.datetime(2024, 2, 29)
    assert feed._get_bucket_start(dt.datetime(2024, 3, 1, 12)) == dt.datetime(2024, 2, 29)
    assert feed._get_bucket_start(dt.datetime(2024, 3, 2, 12)) == dt.datetime(2024, 3, 2)


def test_two_day_ticks_publish_non_overlapping_ohlcv_bars():
    driver = _AggregationDriver(timeframe=bt.TimeFrame.Days, compression=2)
    for day in range(1, 8):
        driver.tick(dt.datetime(1970, 1, day, 10, tzinfo=UTC), 100.0 + day)

    assert driver.bars == [
        (dt.datetime(1970, 1, 1), 101.0, 102.0, 101.0, 102.0, 2.0),
        (dt.datetime(1970, 1, 3), 103.0, 104.0, 103.0, 104.0, 2.0),
        (dt.datetime(1970, 1, 5), 105.0, 106.0, 105.0, 106.0, 2.0),
    ]


@pytest.mark.parametrize(
    "compression, times, expected_starts",
    [
        (
            240,
            (
                dt.datetime(1970, 1, 1, 8, 10),
                dt.datetime(1970, 1, 1, 11, 59),
                dt.datetime(1970, 1, 1, 12, 1),
                dt.datetime(1970, 1, 1, 15, 59),
                dt.datetime(1970, 1, 1, 16, 1),
            ),
            (dt.datetime(1970, 1, 1, 8), dt.datetime(1970, 1, 1, 12)),
        ),
        (
            360,
            (
                dt.datetime(1970, 1, 1, 6, 10),
                dt.datetime(1970, 1, 1, 11, 59),
                dt.datetime(1970, 1, 1, 12, 1),
                dt.datetime(1970, 1, 1, 17, 59),
                dt.datetime(1970, 1, 1, 18, 1),
            ),
            (dt.datetime(1970, 1, 1, 6), dt.datetime(1970, 1, 1, 12)),
        ),
        (
            480,
            (
                dt.datetime(1970, 1, 1, 8, 10),
                dt.datetime(1970, 1, 1, 15, 59),
                dt.datetime(1970, 1, 1, 16, 1),
                dt.datetime(1970, 1, 1, 23, 59),
                dt.datetime(1970, 1, 2, 0, 1),
            ),
            (dt.datetime(1970, 1, 1, 8), dt.datetime(1970, 1, 1, 16)),
        ),
    ],
)
def test_large_minute_compressions_aggregate_across_hour_boundaries(
    compression, times, expected_starts
):
    driver = _AggregationDriver(timeframe=bt.TimeFrame.Minutes, compression=compression)
    for index, when in enumerate(times, start=1):
        driver.tick(when.replace(tzinfo=UTC), 100.0 + index)

    assert driver.bars == [
        (expected_starts[0], 101.0, 102.0, 101.0, 102.0, 2.0),
        (expected_starts[1], 103.0, 104.0, 103.0, 104.0, 2.0),
    ]


@pytest.mark.parametrize(
    "timeframe, compression, stamp, expected_start, expected_end",
    [
        (
            bt.TimeFrame.Seconds,
            15,
            dt.datetime(2026, 11, 20, 9, 12, 34, 900000),
            dt.datetime(2026, 11, 20, 9, 12, 30),
            dt.datetime(2026, 11, 20, 9, 12, 45),
        ),
        (
            bt.TimeFrame.Minutes,
            15,
            dt.datetime(2026, 11, 20, 9, 47, 34, 900000),
            dt.datetime(2026, 11, 20, 9, 45),
            dt.datetime(2026, 11, 20, 10, 0),
        ),
        (
            bt.TimeFrame.Days,
            1,
            dt.datetime(2026, 11, 20, 9, 47, 34, 900000),
            dt.datetime(2026, 11, 20),
            dt.datetime(2026, 11, 21),
        ),
        (
            bt.TimeFrame.Seconds,
            90,
            dt.datetime(1970, 1, 1, 0, 2, 30),
            dt.datetime(1970, 1, 1, 0, 1, 30),
            dt.datetime(1970, 1, 1, 0, 3),
        ),
        (
            bt.TimeFrame.Minutes,
            7,
            dt.datetime(1970, 1, 1, 1, 0),
            dt.datetime(1970, 1, 1, 0, 56),
            dt.datetime(1970, 1, 1, 1, 3),
        ),
        (
            bt.TimeFrame.Minutes,
            120,
            dt.datetime(1970, 1, 1, 3, 35),
            dt.datetime(1970, 1, 1, 2),
            dt.datetime(1970, 1, 1, 4),
        ),
        (
            bt.TimeFrame.Minutes,
            240,
            dt.datetime(2026, 11, 20, 15, 35),
            dt.datetime(2026, 11, 20, 12),
            dt.datetime(2026, 11, 20, 16),
        ),
        (
            bt.TimeFrame.Minutes,
            360,
            dt.datetime(2026, 11, 20, 15, 35),
            dt.datetime(2026, 11, 20, 12),
            dt.datetime(2026, 11, 20, 18),
        ),
        (
            bt.TimeFrame.Minutes,
            480,
            dt.datetime(2026, 11, 20, 15, 35),
            dt.datetime(2026, 11, 20, 8),
            dt.datetime(2026, 11, 20, 16),
        ),
    ],
)
def test_supported_tick_bucket_compressions_keep_exact_boundaries(
    timeframe, compression, stamp, expected_start, expected_end
):
    feed = BtApiFeed(
        dataname="SA609",
        store=None,
        timeframe=timeframe,
        compression=compression,
    )

    bucket_start = feed._get_bucket_start(stamp)
    assert bucket_start == expected_start
    assert feed._get_tick_bucket_end(bucket_start) == expected_end


@pytest.mark.parametrize(
    "timeframe",
    [
        bt.TimeFrame.Weeks,
        bt.TimeFrame.Months,
        bt.TimeFrame.Years,
        bt.TimeFrame.MicroSeconds,
        bt.TimeFrame.NoTimeFrame,
    ],
)
def test_calendar_periods_without_a_tick_bucket_contract_are_rejected(timeframe):
    feed = BtApiFeed(
        dataname="SA609",
        store=None,
        timeframe=timeframe,
        compression=1,
    )

    with pytest.raises(ValueError, match="BTAPI_FEED_TIMEFRAME_UNSUPPORTED_FOR_TICK_AGGREGATION"):
        feed._get_bucket_start(dt.datetime(2026, 11, 20, 9, 0))


@pytest.mark.parametrize(
    "timeframe, compression",
    [
        (bt.TimeFrame.Seconds, 0),
        (bt.TimeFrame.Seconds, -1),
        (bt.TimeFrame.Seconds, True),
        (bt.TimeFrame.Minutes, 0),
        (bt.TimeFrame.Minutes, -1),
        (bt.TimeFrame.Days, 0),
        (bt.TimeFrame.Days, 1.5),
    ],
)
def test_nonpositive_or_nonintegral_compressions_are_rejected(timeframe, compression):
    feed = BtApiFeed(
        dataname="SA609",
        store=None,
        timeframe=timeframe,
        compression=compression,
    )

    with pytest.raises(ValueError, match="BTAPI_FEED_COMPRESSION_UNSUPPORTED_FOR_TICK_AGGREGATION"):
        feed._get_bucket_start(dt.datetime(2026, 11, 20, 9, 0))


@pytest.mark.parametrize(
    "timeframe, compression",
    [
        (bt.TimeFrame.Weeks, 1),
        (bt.TimeFrame.Months, 1),
        (bt.TimeFrame.Years, 1),
        (bt.TimeFrame.Minutes, 120),
        (bt.TimeFrame.Minutes, 240),
        (bt.TimeFrame.Minutes, 360),
    ],
)
def test_provider_bars_keep_provider_timeframes_and_compressions(timeframe, compression):
    when = dt.datetime(2026, 11, 20, 9, 0)
    bar = {
        "datetime": when,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 10.0,
        "openinterest": 0.0,
        "bar_final": True,
    }
    feed = BtApiFeed(
        dataname="SA609",
        store=None,
        timeframe=timeframe,
        compression=compression,
        historical_bars=(bar,),
        backfill_start=False,
    )
    feed.lines.datetime.forward()
    for name in ("open", "high", "low", "close", "volume", "openinterest"):
        getattr(feed.lines, name).forward()

    feed.start()
    assert feed._load_history() is True
    assert feed.lines.close[0] == 100.5
    feed.stop()


class _StartTrackingStore:
    _market_channels = ("tick",)

    def __init__(self):
        self.calls = []

    def start(self, **_kwargs):
        self.calls.append("start")

    def register(self, _feed):
        self.calls.append("register")

    def subscribe(self, *_args, **_kwargs):
        self.calls.append("subscribe")


def test_unsupported_tick_timeframe_is_rejected_before_store_start_or_subscribe():
    store = _StartTrackingStore()
    feed = BtApiFeed(
        dataname="SA609",
        store=store,
        timeframe=bt.TimeFrame.Weeks,
        compression=1,
    )

    with pytest.raises(ValueError, match="BTAPI_FEED_TIMEFRAME_UNSUPPORTED_FOR_TICK_AGGREGATION"):
        feed.start()

    assert store.calls == []
