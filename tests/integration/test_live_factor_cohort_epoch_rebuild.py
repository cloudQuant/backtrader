"""Real Cerebro coverage for freezing and rebuilding a live-factor epoch."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from types import MappingProxyType, SimpleNamespace

import backtrader as bt
import pytest

from backtrader.research import FactorHistoryContract, FactorSpec, LiveFactorPlan
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveCohortFrozenError,
)
from tests.unit.feeds.test_btapifeed_cohort_runnext import (
    CohortClose,
    CohortStrategy,
    FakeClock,
    START,
    _event,
)


_FIELDS = ("open", "high", "low", "close", "volume", "openinterest")
_MEMBERS = ("A", "B")


class FiniteHistoryCohortClose(CohortClose):
    history_contract = FactorHistoryContract.finite_window(span_bars=1)


def _compose_epoch(monkeypatch, *, cohort_id, calendar_id, version, epoch_id, start, generations):
    slots = tuple(
        LiveCalendarSlot(
            "slot-%d" % index,
            start + timedelta(minutes=index),
            start + timedelta(minutes=index + 1),
            "2025-01-02",
            "regular",
        )
        for index in range(2)
    )
    calendar = LiveCohortCalendar(
        calendar_id=calendar_id,
        version=version,
        epoch_id=epoch_id,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="clock-replay",
        session_semantics="session-v1",
        slots=slots,
    )
    cohort = LiveBarCohort(
        cohort_id,
        calendar,
        max_pending_slots=1,
        max_window_bars=8,
        wait_timeout_ns=5_000_000_000,
    )
    feeds = {}
    for member_index, name in enumerate(_MEMBERS):
        bars = []
        for slot_index, slot in enumerate(slots):
            event = _event(
                slot,
                name,
                slot_index + 1,
                10.0 + member_index + slot_index,
            )
            event["connection_generation"] = generations[slot_index]
            bars.append(MappingProxyType(event))
        feed = bt.feeds.BtApiFeed(
            dataname=name,
            historical_bars=(),
            live_bars=tuple(bars),
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
        )
        feeds[name] = feed
        cohort.register_member(
            "member-" + name,
            feed,
            instrument=name,
            source_ref="source-" + name,
            line_fields=_FIELDS,
            raw_fields=_FIELDS,
            numeric_fields=_FIELDS,
        )

    plan = LiveFactorPlan(
        targets=_MEMBERS,
        factors={
            "close_value": FactorSpec(
                name="close_value",
                indicator=FiniteHistoryCohortClose,
                panel_line="factor",
                mode="native",
                field_bindings={"close": "feed:target:close"},
            )
        },
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=1,
        max_pending_slots=1,
        max_window_bars=8,
        wait_timeout_ns=5_000_000_000,
    )
    clock = FakeClock(slots[-1].close_time)
    cerebro = bt.Cerebro(stdstats=False, preload=False, runonce=False)
    for name in _MEMBERS:
        cerebro.adddata(feeds[name], name=name)
    cerebro.addstrategy(CohortStrategy, cohort=cohort, plan=plan)
    cerebro.add_live_bar_cohort(cohort, clock=clock)

    return cerebro, cohort, calendar, feeds


@pytest.mark.integration
def test_resubscribe_generation_change_freezes_then_new_calendar_epoch_rebuilds_group(
    monkeypatch,
):
    # The production Feed sends live bar mappings to notify_bar; the shared
    # strategy helper predates that payload shape and expects an attribute.
    original_notify_bar = CohortStrategy.notify_bar

    def notify_live_mapping(strategy, bar):
        if isinstance(bar, Mapping):
            bar = SimpleNamespace(symbol=bar["symbol"])
        original_notify_bar(strategy, bar)

    monkeypatch.setattr(CohortStrategy, "notify_bar", notify_live_mapping)
    strategies = []
    original_next = CohortStrategy.next

    def record_strategy_next(strategy):
        original_next(strategy)
        strategies.append(strategy)

    monkeypatch.setattr(CohortStrategy, "next", record_strategy_next)

    old_cerebro, old_cohort, old_calendar, old_feeds = _compose_epoch(
        monkeypatch,
        cohort_id="cohort-old-connection",
        calendar_id="calendar-rules-v1",
        version="rules-v1",
        epoch_id=1,
        start=START,
        generations=("connection-1", "connection-2"),
    )
    with pytest.raises(LiveCohortFrozenError, match="connection generation changed"):
        old_cerebro.run()

    old_strategy = strategies[-1]
    old_batch = old_cohort.current_batch()
    assert old_batch is not None and old_batch.status == "COMPLETE"
    assert old_batch.epoch_id == 1 and old_batch.slot_index == 0
    assert old_cohort.frozen is True
    assert old_cohort.frozen_reason == "connection_generation_changed"
    assert old_strategy.strategy_batches == [old_batch.batch_id]
    assert len(old_strategy.snapshots) == 1
    assert [len(old_feeds[name]) for name in _MEMBERS] == [1, 1]
    frozen_state = (
        tuple(old_strategy.strategy_batches),
        tuple(len(old_feeds[name]) for name in _MEMBERS),
        tuple(tuple(old_feeds[name].close.array) for name in _MEMBERS),
        old_cohort.current_batch(),
    )

    new_start = old_calendar.slots[-1].close_time + timedelta(minutes=4)
    new_cerebro, new_cohort, new_calendar, new_feeds = _compose_epoch(
        monkeypatch,
        cohort_id="cohort-resubscribed",
        calendar_id="calendar-rules-v2",
        version="rules-v2",
        epoch_id=2,
        start=new_start,
        generations=("connection-2", "connection-2"),
    )
    new_strategy = new_cerebro.run()[0]

    assert old_cohort.frozen and old_cohort.epoch_id == 1
    assert new_calendar.epoch_id == new_cohort.epoch_id == 2
    assert new_calendar.fingerprint != old_calendar.fingerprint
    assert new_cohort.cohort_id != old_cohort.cohort_id
    assert new_cohort.frozen is False
    assert tuple(new_strategy.strategy_batches) == (
        "cohort-resubscribed:calendar-rules-v2:2:rules-v2:0",
        "cohort-resubscribed:calendar-rules-v2:2:rules-v2:1",
    )
    assert len(new_strategy.snapshots) == 2
    assert [len(new_feeds[name]) for name in _MEMBERS] == [2, 2]
    assert new_cohort.current_batch().status == "COMPLETE"
    assert new_cohort.current_batch().slot_index == 1
    assert all(snapshot.readiness.value == "LIVE_READY" for snapshot in new_strategy.snapshots), [
        (snapshot.readiness.value, snapshot.readiness_reasons)
        for snapshot in new_strategy.snapshots
    ]
    assert [
        tuple(snapshot.factors["close_value"].values[name].value for name in _MEMBERS)
        for snapshot in new_strategy.snapshots
    ] == [(10.0, 11.0), (11.0, 12.0)]
    assert frozen_state == (
        tuple(old_strategy.strategy_batches),
        tuple(len(old_feeds[name]) for name in _MEMBERS),
        tuple(tuple(old_feeds[name].close.array) for name in _MEMBERS),
        old_cohort.current_batch(),
    )
