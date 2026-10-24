"""Real Cerebro witness for bounded out-of-order cohort arrival."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from types import MappingProxyType, SimpleNamespace

import backtrader as bt
import pytest

from backtrader.research import FactorSpec, LiveFactorPlan
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


_RAW_FIELDS = ("open", "high", "low", "close", "volume", "openinterest")
_COHORT_ID = "cohort-bounded-reorder"
_CALENDAR_ID = "calendar-bounded-reorder"


def _make_two_slot_run(monkeypatch, *, source_role="history"):
    if source_role not in {"history", "live"}:
        raise ValueError("source_role must be history or live")
    slots = tuple(
        LiveCalendarSlot(
            "slot-%d" % index,
            START + timedelta(minutes=index),
            START + timedelta(minutes=index + 1),
            "2025-01-02",
            "regular",
        )
        for index in range(2)
    )
    calendar = LiveCohortCalendar(
        calendar_id=_CALENDAR_ID,
        version="v1",
        epoch_id=7,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="clock-replay",
        session_semantics="session-v1",
        slots=slots,
    )
    cohort = LiveBarCohort(
        _COHORT_ID,
        calendar,
        max_pending_slots=2,
        max_window_bars=8,
        wait_timeout_ns=5_000_000_000,
    )

    latest_close = slots[-1].close_time
    first_available = latest_close + timedelta(seconds=1)
    second_available = latest_close + timedelta(seconds=2)
    # A receives slot 1 before slot 0; B receives slot 0 before slot 1. Every
    # event becomes available after slot 1 has closed, and availability remains
    # monotone in each source tuple.
    source_events = {
        "A": (
            MappingProxyType(_event(slots[1], "A", 1, 11.0, available_at=first_available)),
            MappingProxyType(_event(slots[0], "A", 2, 10.0, available_at=second_available)),
        ),
        "B": (
            MappingProxyType(_event(slots[0], "B", 1, 20.0, available_at=first_available)),
            MappingProxyType(_event(slots[1], "B", 2, 21.0, available_at=second_available)),
        ),
    }
    feeds = {}
    for name in ("A", "B"):
        first, second = source_events[name]
        source_bars = (first, second, second)
        feeds[name] = bt.feeds.BtApiFeed(
            dataname=name,
            historical_bars=source_bars if source_role == "history" else (),
            live_bars=source_bars if source_role == "live" else (),
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
        )

    cerebro = bt.Cerebro(stdstats=False, preload=False, runonce=False)
    for name in ("A", "B"):
        feed = feeds[name]
        cerebro.adddata(feed, name=name)
        cohort.register_member(
            "member-" + name,
            feed,
            instrument=name,
            source_ref="source-" + name,
            line_fields=_RAW_FIELDS,
            raw_fields=_RAW_FIELDS,
            numeric_fields=_RAW_FIELDS,
        )

    plan = LiveFactorPlan(
        targets=("A", "B"),
        factors={
            "close_value": FactorSpec(
                name="close_value",
                indicator=CohortClose,
                panel_line="factor",
                mode="native",
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
    clock = FakeClock(second_available)
    cerebro.addstrategy(CohortStrategy, cohort=cohort, plan=plan)
    cerebro.add_live_bar_cohort(cohort, clock=clock)

    captured = []
    original_capture = cohort.capture_bar

    def record_capture(feed_ref, event, *, source_role, received_monotonic_ns=None):
        result = original_capture(
            feed_ref,
            event,
            source_role=source_role,
            received_monotonic_ns=received_monotonic_ns,
        )
        captured.append(
            (feed_ref._name, event["bar_id"], result.slot_index, result.duplicate, event)
        )
        return result

    monkeypatch.setattr(cohort, "capture_bar", record_capture)
    return cerebro, cohort, feeds, clock, slots, source_events, captured


def _run_two_slot_case(monkeypatch, *, source_role="history"):
    if source_role == "live":
        original_notify_bar = CohortStrategy.notify_bar

        def notify_live_mapping(strategy, bar):
            if isinstance(bar, Mapping):
                bar = SimpleNamespace(symbol=bar["symbol"])
            original_notify_bar(strategy, bar)

        monkeypatch.setattr(CohortStrategy, "notify_bar", notify_live_mapping)
    factor_advances = []
    original_next = CohortClose.next

    def count_factor_advance(indicator):
        factor_advances.append(indicator.datas[0].datetime.datetime(0))
        original_next(indicator)

    monkeypatch.setattr(CohortClose, "next", count_factor_advance)
    cerebro, cohort, feeds, clock, slots, source_events, captured = _make_two_slot_run(
        monkeypatch, source_role=source_role
    )
    strategy = cerebro.run()[0]
    return (
        strategy,
        cohort,
        feeds,
        clock,
        slots,
        source_events,
        captured,
        factor_advances,
    )


def _assert_two_planned_batches(result, *, source_role="history"):
    strategy, cohort, feeds, clock, slots, _events, captured, advances = result
    expected_ids = (
        "%s:%s:7:v1:0" % (_COHORT_ID, _CALENDAR_ID),
        "%s:%s:7:v1:1" % (_COHORT_ID, _CALENDAR_ID),
    )
    assert tuple(strategy.strategy_batches) == expected_ids
    assert [len(feeds[name]) for name in ("A", "B")] == [2, 2]
    assert len(strategy.snapshots) == 2
    assert len(advances) == 2
    assert clock.waits == []
    assert cohort.current_batch().status == "COMPLETE"
    assert cohort.current_batch().slot_index == 1
    assert cohort.current_batch().close_time == slots[1].close_time
    observed_values = [
        (
            snapshot.factors["close_value"].values["A"].value,
            snapshot.factors["close_value"].values["B"].value,
        )
        for snapshot in strategy.snapshots
    ]
    assert observed_values == [(10.0, 20.0), (11.0, 21.0)]

    accepted_by_feed = {"A": [], "B": []}
    duplicates_by_feed = {"A": [], "B": []}
    for name, _bar_id, slot_index, duplicate, event in captured:
        assert event["available_at"] > slots[1].close_time
        (duplicates_by_feed if duplicate else accepted_by_feed)[name].append(slot_index)
    assert accepted_by_feed == {"A": [1, 0], "B": [0, 1]}
    assert duplicates_by_feed == {"A": [0], "B": [1]}
    for name in ("A", "B"):
        receipts = cohort.complete_window_bars(feeds[name], ("close",), 2)
        assert tuple(receipt.source_role for receipt in receipts) == (source_role, source_role)


def test_real_cerebro_publishes_bounded_out_of_order_slots_in_plan_order_once(monkeypatch):
    result = _run_two_slot_case(monkeypatch)
    _assert_two_planned_batches(result)


def test_real_completed_cohort_does_not_rewrite_a_sealed_slot_on_conflict(monkeypatch):
    result = _run_two_slot_case(monkeypatch)
    _assert_two_planned_batches(result)
    _strategy, cohort, feeds, _clock, _slots, source_events, _captured, _advances = result
    prior_batch = cohort.current_batch()
    prior_lines = tuple(tuple(feeds[name].close.array) for name in ("A", "B"))
    prior_window = cohort.complete_window_bars(feeds["A"], ("close", "volume"), 2)
    assert [receipt.slot_index for receipt in prior_window] == [0, 1]
    assert [receipt.raw_values["volume"] for receipt in prior_window] == [2.0, 1.0]
    changed = dict(source_events["A"][1])
    changed["volume"] += 100.0

    with pytest.raises(LiveCohortFrozenError, match="late bar cannot rewrite"):
        cohort.capture_bar(feeds["A"], MappingProxyType(changed), source_role="history")

    assert cohort.frozen is True
    assert cohort.current_batch() is prior_batch
    assert tuple(tuple(feeds[name].close.array) for name in ("A", "B")) == prior_lines
    assert [receipt.raw_values["volume"] for receipt in prior_window] == [2.0, 1.0]


def test_real_completed_cohort_rejects_old_generation_for_a_sealed_slot(monkeypatch):
    result = _run_two_slot_case(monkeypatch)
    _assert_two_planned_batches(result)
    _strategy, cohort, feeds, _clock, _slots, source_events, _captured, _advances = result
    prior_batch = cohort.current_batch()
    prior_lines = tuple(tuple(feeds[name].close.array) for name in ("A", "B"))
    prior_window = cohort.complete_window_bars(feeds["A"], ("close",), 2)
    stale = dict(source_events["A"][1])
    stale["connection_generation"] = "generation-old"

    with pytest.raises(LiveCohortFrozenError, match="different connection generation"):
        cohort.capture_bar(feeds["A"], MappingProxyType(stale), source_role="history")

    assert cohort.frozen is True
    assert cohort.current_batch() is prior_batch
    assert tuple(tuple(feeds[name].close.array) for name in ("A", "B")) == prior_lines
    assert [receipt.slot_index for receipt in prior_window] == [0, 1]


def test_real_cerebro_publishes_bounded_out_of_order_live_slots_once(monkeypatch):
    result = _run_two_slot_case(monkeypatch, source_role="live")
    _assert_two_planned_batches(result, source_role="live")


def test_real_live_cohort_does_not_rewrite_a_sealed_slot_on_conflict(monkeypatch):
    result = _run_two_slot_case(monkeypatch, source_role="live")
    _assert_two_planned_batches(result, source_role="live")
    _strategy, cohort, feeds, _clock, _slots, source_events, _captured, _advances = result
    prior_batch = cohort.current_batch()
    prior_lines = tuple(tuple(feeds[name].close.array) for name in ("A", "B"))
    prior_window = cohort.complete_window_bars(feeds["A"], ("close", "volume"), 2)
    changed = dict(source_events["A"][1])
    changed["volume"] += 100.0

    with pytest.raises(LiveCohortFrozenError, match="late bar cannot rewrite"):
        cohort.capture_bar(feeds["A"], MappingProxyType(changed), source_role="live")

    assert cohort.frozen is True
    assert cohort.current_batch() is prior_batch
    assert tuple(tuple(feeds[name].close.array) for name in ("A", "B")) == prior_lines
    assert [receipt.raw_values["volume"] for receipt in prior_window] == [2.0, 1.0]


def test_real_live_cohort_rejects_old_generation_for_a_sealed_slot(monkeypatch):
    result = _run_two_slot_case(monkeypatch, source_role="live")
    _assert_two_planned_batches(result, source_role="live")
    _strategy, cohort, feeds, _clock, _slots, source_events, _captured, _advances = result
    prior_batch = cohort.current_batch()
    prior_lines = tuple(tuple(feeds[name].close.array) for name in ("A", "B"))
    prior_window = cohort.complete_window_bars(feeds["A"], ("close",), 2)
    stale = dict(source_events["A"][1])
    stale["connection_generation"] = "generation-old"

    with pytest.raises(LiveCohortFrozenError, match="different connection generation"):
        cohort.capture_bar(feeds["A"], MappingProxyType(stale), source_role="live")

    assert cohort.frozen is True
    assert cohort.current_batch() is prior_batch
    assert tuple(tuple(feeds[name].close.array) for name in ("A", "B")) == prior_lines
    assert [receipt.slot_index for receipt in prior_window] == [0, 1]
