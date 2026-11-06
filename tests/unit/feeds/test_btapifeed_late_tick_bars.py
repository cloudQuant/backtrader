"""Iteration 60 (D60-15, acceptance report G7): BT-derived bars are publish-once.

A Backtrader-aggregated bar is identified by feed + bucket start. Once the
event-time watermark has closed a bucket and its bar is published, a late
tick for that bucket is blocked (``BUCKET_ALREADY_CLOSED`` /
``LATE_AFTER_WATERMARK``) and never builds a second bar or rewrites the first.
Typed SDK ticks go through the feed's own pipeline (prepare -> health ->
ingest -> flush).
"""

from __future__ import annotations

import datetime as dt

import pytest

pytest.importorskip("bt_api_py.market_tick_contracts")

import backtrader as bt  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402
from backtrader.feeds.market_tick_adapter import adapt_market_tick_event  # noqa: E402
from tests.unit.feeds import test_market_tick_adapter_baseline as typed  # noqa: E402

T0 = dt.datetime(2026, 11, 2, 2, 0, tzinfo=dt.timezone.utc)


class _Driver:
    def __init__(self):
        self.feed = BtApiFeed(
            dataname="SA609",
            store=None,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            price_tick=1.0,
            event_time_max_age=1e9,  # historical timestamps in a unit test
            receive_time_max_age=1e9,
        )
        self.bars = []
        self.feed._enqueue_bar_event = lambda event, when, **_kw: self.bars.append(
            (when, event.close)
        )
        self.sequence = 7

    def tick(self, minute, second, price):
        self.sequence += 1
        stamp = (T0 + dt.timedelta(minutes=minute, seconds=second)).isoformat()
        stamp = stamp.replace("+00:00", "Z")
        event = typed.bind_market_tick_event(
            typed._payload(
                last_price=price,
                provider_event_time_utc=stamp,
                received_at_utc=stamp,
                provider_sequence=self.sequence,
            ),
            typed.SOURCE,
            typed.MarketEventCursor(
                stream_id=typed.SOURCE.stream_id, epoch=typed.SOURCE.epoch, sequence=self.sequence
            ),
        )
        tick = adapt_market_tick_event(event)
        self.feed._prepare_tick(tick)
        # A tick behind the latest event time is dropped by the drain loop
        # (D62-38); any other unhealthy tick stops here as before.
        if getattr(tick, "event_time_regressed", False) or self.feed._handle_event_health(tick):
            return set(getattr(tick, "quality_flags", ()) or ())
        self.feed._ingest_tick(tick)
        self.feed._flush_ready_bars(reason="tick")
        return None


def test_late_tick_never_rewrites_a_published_bar():
    driver = _Driver()
    assert driver.tick(0, 10, 1500) is None
    assert driver.tick(1, 10, 1501) is None
    assert driver.tick(2, 10, 1502) is None
    published = list(driver.bars)
    minute0 = T0.replace(tzinfo=None)
    assert (minute0, 1500.0) in published
    flags = driver.tick(0, 30, 1999)  # late: its minute is already published
    assert {"BUCKET_ALREADY_CLOSED", "LATE_AFTER_WATERMARK"} <= flags
    assert driver.tick(3, 10, 1503) is None
    assert driver.bars[: len(published)] == published  # nothing rewritten
    assert [when for when, _ in driver.bars].count(minute0) == 1  # no second bar
    assert all(close != 1999 for _, close in driver.bars)
