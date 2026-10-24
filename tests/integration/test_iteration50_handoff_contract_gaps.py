"""Narrow Iteration 50 handoff regressions on the production composition path.

The provider client is deterministic, while Cerebro, BtApiFeed, BtApiStore,
LiveBarCohort and the production Alpha003/FactorSpec bindings remain real.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

import backtrader as bt
import pytest

from backtrader.errors import ResearchConfigError
from backtrader.research import FactorIndicator, FactorSpec, LiveFactorPlan, LiveFactorSet
from backtrader.research.alpha101 import get_alpha
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveCohortValidationError,
)
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store, make_tick
from tests.integration.test_live_factor_cohort_composition import _alpha003_run


UTC = timezone.utc
START = datetime(2025, 1, 2, 9, 30, tzinfo=UTC)
_MISSING_PRICE = object()
_FACTOR_CALLS: list[float] = []


class ReplayClock:
    def __init__(self, now: datetime):
        self.now = now
        self.monotonic = 1_000_000_000

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        return self.monotonic

    def wait(self, timeout_seconds):
        elapsed = max(0.0, float(timeout_seconds))
        self.now += timedelta(seconds=elapsed)
        self.monotonic += max(1, int(elapsed * 1_000_000_000))


class CloseValue(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self._close_lines = self.field_lines("close")

    def next(self):
        for data, close in zip(self.datas, self._close_lines):
            value = float(close[0])
            _FACTOR_CALLS.append(value)
            self.outputs[data].factor[0] = value

    @classmethod
    def build(cls, ctx, **_params):
        return ctx.close


class CaptureStrategy(bt.Strategy):
    params = (("cohort", None), ("plan", None))

    def __init__(self):
        self.live_factors = LiveFactorSet.bind(
            self.p.plan,
            {data._name: data for data in self.datas},
            cohort=self.p.cohort,
        )
        self.tick_events = []
        self.rows = []

    def notify_tick(self, tick):
        self.tick_events.append(tick)

    def next(self):
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        feed = self.data
        receipt = batch.receipt_for_feed(feed)
        snapshot = self.live_factors.snapshot()
        self.rows.append(
            {
                "batch": batch,
                "receipt": receipt,
                "snapshot": snapshot,
                "latest_tick": self.tick_events[-1],
            }
        )


class FiniteTickClient(FakeBtApiClient):
    def __init__(self, *, ticks, final_watermark):
        super().__init__(live_ticks={"A": ticks})
        self.final_watermark = final_watermark
        self.observed_ticks = []

    def poll_tick(self, dataname):
        tick = super().poll_tick(dataname)
        if tick is not None:
            self.observed_ticks.append(tick)
        return tick

    def is_source_exhausted(self, _symbol):
        return not self.live_ticks.get("A")

    def get_source_event_time_watermark(self, _symbol):
        return self.final_watermark


def _tick(event_time: datetime, *, sequence: int, price):
    tick = make_tick(0, price, volume=2.0, symbol="A")
    tick.timestamp = event_time.timestamp()
    tick.local_time = event_time.timestamp()
    tick.datetime = event_time.replace(tzinfo=None)
    tick.event_time_utc = event_time
    tick.recv_time_utc = event_time + timedelta(milliseconds=50)
    tick.recv_monotonic_ns = 2_000_000_000 + sequence
    tick.clock_domain_id = "clock-50-test"
    tick.connection_generation = "generation-1"
    tick.ingest_seq = sequence
    tick.sequence = sequence
    tick.event_id = "A-tick-{}".format(sequence)
    tick.schema_version = "backtrader.tick.v1"
    tick.volume_semantics = "delta"
    tick.delta_volume = 2.0
    tick.volume_complete = True
    tick.trading_day = "2025-01-02"
    tick.session_segment = "regular"
    tick.source = "deterministic-fake-provider"
    return tick


def _single_member_calendar(slot_count: int):
    member_sessions = {"member-A": LiveCalendarMemberSession("2025-01-02", "regular")}
    slots = tuple(
        LiveCalendarSlot(
            slot_id="slot-{}".format(index),
            bucket_start=START + timedelta(minutes=index),
            close_time=START + timedelta(minutes=index + 1),
            trading_day="2025-01-02",
            session_segment="regular",
            member_sessions=member_sessions,
        )
        for index in range(slot_count)
    )
    return LiveCohortCalendar(
        calendar_id="calendar-50-test",
        version="v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="clock-50-test",
        session_semantics="session-50-test",
        slots=slots,
    )


def _tick_composition(*, ticks, slot_count: int, quote_capture: bool = False):
    calendar = _single_member_calendar(slot_count)
    cohort = LiveBarCohort(
        "cohort-50-test",
        calendar,
        max_pending_slots=2,
        max_window_bars=8,
        wait_timeout_ns=5_000_000_000,
    )
    final_watermark = calendar.slots[-1].close_time
    client = FiniteTickClient(ticks=ticks, final_watermark=final_watermark)
    store = make_store(api=client, provider="okx", preserve_raw_bars=True)
    clock = ReplayClock(calendar.slots[0].close_time)
    feed_kwargs = {"closed_bar_quote_capture": True} if quote_capture else {}
    feed = bt.feeds.BtApiFeed(
        dataname="A",
        store=store,
        cohort_source_mode=True,
        backfill_start=False,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        bar_watermark_ms=0,
        dispatch_ticks=True,
        clock=clock,
        **feed_kwargs,
    )
    cohort.register_member(
        "member-A",
        feed,
        instrument="A",
        source_ref="feed-A",
        line_fields=("open", "high", "low", "close", "volume", "openinterest"),
        raw_fields=("open", "high", "low", "close", "volume", "openinterest"),
        numeric_fields=("open", "high", "low", "close", "volume", "openinterest"),
    )
    plan = LiveFactorPlan(
        targets=("A",),
        groups={"A": "portfolio"},
        factors={
            "close_value": FactorSpec(
                name="close_value",
                indicator=CloseValue,
                panel_line="factor",
                field_bindings={"close": "feed:target:close"},
            )
        },
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=1,
        max_pending_slots=2,
        max_window_bars=8,
        wait_timeout_ns=5_000_000_000,
    )
    cerebro = bt.Cerebro(stdstats=False, exactbars=3, preload=False, runonce=False)
    cerebro.adddata(feed, name="A")
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(CaptureStrategy, cohort=cohort, plan=plan)
    return cerebro, cohort, feed, client, calendar


@pytest.mark.integration
@pytest.mark.parametrize(
    "bad_price, expected_category",
    [
        ("not-a-number", "wrong_type"),
        (math.inf, "non_finite"),
        (math.nan, "nan"),
        (0.0, "non_positive"),
        (None, "missing"),
        (_MISSING_PRICE, "missing"),
    ],
    ids=("string", "infinity", "nan", "zero", "none", "missing"),
)
def test_tick_builder_reports_bad_raw_price_before_normalization_or_bar_publication(
    bad_price, expected_category
):
    _FACTOR_CALLS.clear()
    valid = _tick(START + timedelta(seconds=10), sequence=1, price=100.0)
    invalid = _tick(START + timedelta(seconds=20), sequence=2, price=100.0)
    if bad_price is _MISSING_PRICE:
        invalid = dict(vars(invalid))
        invalid.pop("price")
    else:
        invalid.price = bad_price
    raw_before = dict(invalid) if isinstance(invalid, dict) else vars(invalid).copy()
    cerebro, cohort, feed, client, _calendar = _tick_composition(
        ticks=(valid, invalid), slot_count=1
    )

    with pytest.raises(LiveCohortValidationError) as exc_info:
        cerebro.run()

    error = exc_info.value
    assert str(error) == "raw tick price rejected: LAST_PRICE_INVALID"
    assert error.code == "LAST_PRICE_INVALID"
    report = error.report
    assert report == {
        "source": "BtApiFeed.tick",
        "instrument": "A",
        "field": "price",
        "category": expected_category,
        "generation": "generation-1",
        "sequence": 2,
        "reason": "LAST_PRICE_INVALID",
    }
    with pytest.raises(TypeError):
        report["reason"] = "changed"

    observed_invalid = client.observed_ticks[-1]
    raw_after = (
        dict(observed_invalid)
        if isinstance(observed_invalid, dict)
        else vars(observed_invalid).copy()
    )
    assert raw_after == raw_before
    if bad_price is _MISSING_PRICE:
        assert "price" not in observed_invalid
    elif isinstance(bad_price, float) and math.isnan(bad_price):
        assert type(observed_invalid.price) is float
        assert math.isnan(observed_invalid.price)
    else:
        assert type(observed_invalid.price) is type(bad_price)
        assert observed_invalid.price == bad_price
    assert cohort.frozen is True
    assert cohort.frozen_reason == "invalid_source_tick_price"
    assert cohort.current_batch() is None
    assert len(feed) == 0
    assert _FACTOR_CALLS == []


@pytest.mark.integration
def test_alpha003_business_membership_excludes_a_source_present_member_independently():
    cerebro, cohort, feeds, _clock, calendar = _alpha003_run(
        slot_count=1,
        gap_index=-1,
        source="direct",
    )
    feeds["GAP"]._factor_research_alignment_v2 = {"present": (False,)}

    [strategy] = cerebro.run()

    batch = cohort.current_batch()
    assert batch is not None and batch.close_time == calendar.slots[0].close_time
    receipt = batch.receipt_for_feed(feeds["GAP"])
    assert receipt.present is True and receipt.complete is True
    assert feeds["GAP"]._factor_research_alignment_v2["present"] == (False,)
    ranks = strategy.open_ranks[batch.close_time]
    assert ranks["A"] == pytest.approx(0.5)
    assert ranks["B"] == pytest.approx(1.0)
    assert math.isnan(ranks["GAP"])
    assert "cohort_gap_present" not in strategy.snapshots[0].readiness_reasons


@pytest.mark.integration
def test_alpha003_source_absence_is_distinct_from_business_membership():
    cerebro, cohort, feeds, _clock, calendar = _alpha003_run(
        slot_count=1,
        gap_index=0,
        source="direct",
    )
    # All three assets are business members; the explicit source gap below is
    # the only reason GAP must be excluded from this cross-section.
    for feed in feeds.values():
        feed._factor_research_alignment_v2 = {"present": (True,)}

    [strategy] = cerebro.run()

    batch = cohort.current_batch()
    assert batch is not None and batch.close_time == calendar.slots[0].close_time
    receipt = batch.receipt_for_feed(feeds["GAP"])
    assert feeds["GAP"]._factor_research_alignment_v2["present"] == (True,)
    assert receipt.present is False and receipt.complete is True
    assert receipt.missing_fields == ("close",)
    ranks = strategy.open_ranks[batch.close_time]
    assert ranks["A"] == pytest.approx(0.5)
    assert ranks["B"] == pytest.approx(1.0)
    assert math.isnan(ranks["GAP"])
    assert "cohort_gap_present" in strategy.snapshots[0].readiness_reasons


@pytest.mark.integration
def test_alpha003_rejects_an_unknown_formula_field_binding():
    with pytest.raises(ResearchConfigError, match="unknown_price.*not declared in formula_fields"):
        FactorSpec(
            name="alpha003",
            indicator=get_alpha(3),
            panel_line="factor",
            field_bindings={
                "open": "feed:target:open",
                "volume": "feed:target:volume",
                "unknown_price": "feed:target:close",
            },
        )


@pytest.mark.integration
def test_later_fresh_execution_quote_does_not_rewrite_the_sealed_prior_bar():
    _FACTOR_CALLS.clear()
    ticks = (
        _tick(START + timedelta(seconds=30), sequence=1, price=100.0),
        _tick(START + timedelta(minutes=1, seconds=1), sequence=2, price=101.0),
        _tick(START + timedelta(minutes=1, seconds=30), sequence=3, price=102.0),
    )
    cerebro, cohort, feed, _client, calendar = _tick_composition(
        ticks=ticks,
        slot_count=2,
        quote_capture=True,
    )

    [strategy] = cerebro.run()

    assert len(strategy.rows) == 2
    first = strategy.rows[0]
    first_slot = calendar.slots[0]
    envelope = first["receipt"].envelope
    sealed_event = envelope.event_ref
    assert first["batch"].slot_index == 0
    assert envelope.close_time == first_slot.close_time
    assert envelope.available_at > envelope.close_time
    assert envelope.raw_values["close"] == 100.0
    assert sealed_event.close == 100.0
    assert tuple(item["ingest_seq"] for item in sealed_event.quote_events) == (1,)
    assert first["snapshot"].close_time == first_slot.close_time
    assert first["snapshot"].factors["close_value"].values["A"].value == 100.0

    # The next tick arrived after the first bar close and is available through
    # the real Strategy tick callback, while the prior bar keeps its own close
    # and quote cutoff sequence.
    assert first["latest_tick"].ingest_seq == 3
    assert first["latest_tick"].price == 102.0
    latest_event_time = datetime.fromtimestamp(first["latest_tick"].timestamp, UTC)
    assert latest_event_time > first_slot.close_time
    assert sealed_event.quote_cutoff_seq == 1

    # Processing/delivering the later slot must leave the earlier event and
    # envelope untouched, even though the feed's current line has advanced.
    assert len(feed) == 2
    assert feed.close[0] == 102.0
    assert envelope.raw_values["close"] == 100.0
    assert sealed_event.close == 100.0
    assert sealed_event.quote_cutoff_seq == 1
    assert tuple(item["ingest_seq"] for item in sealed_event.quote_events) == (1,)
    assert _FACTOR_CALLS == [100.0, 102.0]
