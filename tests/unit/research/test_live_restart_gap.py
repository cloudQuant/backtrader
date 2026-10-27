"""Restart-gap admission and post-gap warm-up use the ordinary live cohort."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import backtrader as bt
import pytest

from backtrader.research import (
    FactorHistoryContract,
    FactorIndicator,
    FactorSpec,
    LiveFactorPlan,
    LiveFactorReadiness,
    LiveFactorSet,
)
from backtrader.research.alpha101 import get_alpha
from backtrader.research.live import _executed_graph_span
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveCohortJournalHighWater,
    LiveCohortJournalMemberHighWater,
    LiveCohortValidationError,
    LiveSourceOrigin,
)


UTC = timezone.utc
START = datetime(2026, 10, 27, 9, 30, tzinfo=UTC)
HISTORY_LAST_INDEX = 17
FIRST_LIVE_ORIGINAL_INDEX = 21
LIVE_BAR_COUNT = 14
SLOT_COUNT = FIRST_LIVE_ORIGINAL_INDEX + LIVE_BAR_COUNT
MEMBER_ID = "member-A"
SOURCE_REF = "feed-A"
INSTRUMENT = "SYM"
OLD_CONNECTION_GENERATION = "old-live-generation-7"
HISTORY_REPLAY_GENERATION = OLD_CONNECTION_GENERATION
LINE_FIELDS = ("open", "high", "low", "close", "volume", "openinterest")


class ReplayClock:
    """Advance source time only as the finite synthetic feed becomes available."""

    def __init__(self, available_times, *, now):
        self.now = now
        self.monotonic = 1_000
        self.available_times = tuple(sorted(available_times))

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        return self.monotonic

    def wait(self, timeout_seconds):
        future = [value for value in self.available_times if value > self.now]
        elapsed = (
            min((future[0] - self.now).total_seconds(), timeout_seconds)
            if future
            else timeout_seconds
        )
        self.now += timedelta(seconds=elapsed)
        self.monotonic += max(1, int(elapsed * 1_000_000_000))


class SnapshotStrategy(bt.Strategy):
    params = (("plan", None), ("cohort", None))

    def __init__(self):
        self.live_factors = LiveFactorSet.bind(
            self.p.plan,
            {data._name: data for data in self.datas},
            cohort=self.p.cohort,
        )
        self.snapshots = []

    def _record_snapshot(self):
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        self.snapshots.append(self.live_factors.snapshot())

    def next(self):
        self._record_snapshot()


class RecursiveCloseSum(FactorIndicator):
    """A real recursive graph must keep its old source-origin proof unqualified."""

    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0
    history_contract = FactorHistoryContract.replay_from_source_origin()

    def __init__(self):
        super().__init__()
        self._result_lines = self.field_lines("close")
        self._sum = 0.0

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self._sum += result[0]
            self.outputs[data].factor[0] = self._sum


def _full_calendar():
    slots = tuple(
        LiveCalendarSlot(
            slot_id="slot-%d" % index,
            bucket_start=START + timedelta(minutes=index),
            close_time=START + timedelta(minutes=index + 1),
            trading_day=START.date().isoformat(),
            session_segment="regular",
            member_sessions={
                MEMBER_ID: LiveCalendarMemberSession(START.date().isoformat(), "regular")
            },
        )
        for index in range(SLOT_COUNT)
    )
    calendar = LiveCohortCalendar(
        calendar_id="calendar-A",
        version="v2",
        epoch_id=8,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="clock-A",
        session_semantics="session-v1",
        slots=slots,
    )
    return calendar, slots


def _old_highwater(slots):
    slot = slots[HISTORY_LAST_INDEX]
    member = LiveCohortJournalMemberHighWater(
        member_id=MEMBER_ID,
        source_ref=SOURCE_REF,
        source_role="live",
        connection_generation=OLD_CONNECTION_GENERATION,
        feed_sequence=HISTORY_LAST_INDEX + 1,
        bar_id="history-%d" % (HISTORY_LAST_INDEX + 1),
        close_time=slot.close_time,
        trading_day=slot.trading_day,
        session_segment=slot.session_segment,
    )
    return LiveCohortJournalHighWater(
        cohort_id="cohort-old",
        calendar_id="calendar-A",
        calendar_version="v1",
        calendar_fingerprint="a" * 64,
        epoch_id=7,
        slot_index=HISTORY_LAST_INDEX,
        slot_id=slot.slot_id,
        close_time=slot.close_time,
        batch_id="cohort-old:calendar-A:7:v1:%d" % HISTORY_LAST_INDEX,
        members={MEMBER_ID: member},
    )


def _event(slot, sequence, *, role, generation):
    close = 100.0 + sequence * 0.25
    return MappingProxyType(
        {
            "instrument": INSTRUMENT,
            "symbol": INSTRUMENT,
            "timestamp": slot.close_time.timestamp(),
            "datetime": slot.close_time,
            "bucket_start": slot.bucket_start,
            "bucket_end": slot.close_time,
            "available_at": slot.close_time,
            "trading_day": slot.trading_day,
            "session_segment": slot.session_segment,
            "timezone_id": "UTC",
            "clock_domain_id": "clock-A",
            "connection_generation": generation,
            "bar_sequence": sequence,
            "bar_id": "%s-%d" % (role, sequence),
            "open": close - 0.5,
            "high": close + 0.5,
            "low": close - 1.0,
            "close": close,
            "volume": float(sequence),
            "openinterest": 0.0,
            "present": True,
            "complete": True,
            "quality": "GOOD",
            "quality_flags": (),
            "source": "synthetic-%s" % role,
        }
    )


def _restart_setup(*, indicator=None, mode="native"):
    full_calendar, original_slots = _full_calendar()
    startup = original_slots[20].bucket_start + timedelta(seconds=30)
    highwater = _old_highwater(original_slots)
    calendar = LiveCohortCalendar.with_restart_gap(
        full_calendar,
        startup_time_utc=startup,
        journal_highwater=highwater,
        first_live_slot_id=original_slots[FIRST_LIVE_ORIGINAL_INDEX].slot_id,
    )
    history = tuple(
        _event(slot, index + 1, role="history", generation=HISTORY_REPLAY_GENERATION)
        for index, slot in enumerate(original_slots[: HISTORY_LAST_INDEX + 1])
    )
    live = tuple(
        _event(
            original_slots[index],
            index - FIRST_LIVE_ORIGINAL_INDEX + 1,
            role="live",
            generation="live-generation-8",
        )
        for index in range(FIRST_LIVE_ORIGINAL_INDEX, SLOT_COUNT)
    )
    first_history = history[0]
    origin = LiveSourceOrigin(
        member_id=MEMBER_ID,
        epoch_id=calendar.epoch_id,
        source_ref=SOURCE_REF,
        source_role="history",
        connection_generation=first_history["connection_generation"],
        bar_id=first_history["bar_id"],
        feed_sequence=first_history["bar_sequence"],
        close_time=first_history["bucket_end"],
    )
    feed = bt.feeds.BtApiFeed(
        dataname=INSTRUMENT,
        historical_bars=history,
        live_bars=live,
        cohort_source_mode=True,
        cohort_source_origin=origin,
        backfill_start=False,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cohort = LiveBarCohort(
        "cohort-new",
        calendar,
        max_pending_slots=2,
        max_window_bars=LIVE_BAR_COUNT,
        wait_timeout_ns=60_000_000_000,
    )
    cohort.register_member(
        MEMBER_ID,
        feed,
        instrument=INSTRUMENT,
        source_ref=SOURCE_REF,
        line_fields=LINE_FIELDS,
        raw_fields=LINE_FIELDS,
        numeric_fields=LINE_FIELDS,
        source_origin=origin,
    )
    cerebro = bt.Cerebro(stdstats=False, exactbars=3, preload=False, runonce=False)
    cerebro.adddata(feed, name="A")
    if indicator is None:
        indicator = get_alpha(3)
    factor_name = "alpha003" if getattr(indicator, "alpha_id", None) == 3 else "recursive_sum"
    field_bindings = {field: "feed:target:%s" % field for field in indicator.formula_fields}
    spec = FactorSpec(
        name=factor_name,
        indicator=indicator,
        panel_line="factor",
        field_bindings=field_bindings,
        direction=-1,
        mode=mode,
    )
    plan = LiveFactorPlan(
        targets=("A",),
        groups={"A": "primary"},
        factors={factor_name: spec},
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=1,
        max_pending_slots=2,
        max_window_bars=LIVE_BAR_COUNT,
        wait_timeout_ns=60_000_000_000,
        max_live_bar_age_seconds=60.0,
        max_future_skew_seconds=0.0,
    )
    clock = ReplayClock(
        [row["available_at"] for row in history + live],
        now=startup,
    )
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(SnapshotStrategy, plan=plan, cohort=cohort)
    return cerebro, cohort, full_calendar, original_slots, history, startup, plan, factor_name


def _bare_cohort(calendar, origin=None, *, wait_timeout_ns=5_000_000_000):
    feed = bt.feeds.BtApiFeed(
        dataname=INSTRUMENT,
        historical_bars=(),
        live_bars=(),
        cohort_source_mode=True,
        cohort_source_origin=origin,
        backfill_start=False,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cohort = LiveBarCohort(
        "cohort-new",
        calendar,
        max_pending_slots=2,
        wait_timeout_ns=wait_timeout_ns,
    )
    cohort.register_member(
        MEMBER_ID,
        feed,
        instrument=INSTRUMENT,
        source_ref=SOURCE_REF,
        line_fields=LINE_FIELDS,
        raw_fields=LINE_FIELDS,
        numeric_fields=LINE_FIELDS,
        source_origin=origin,
    )
    return cohort, feed


@pytest.mark.parametrize("mode", ("native", "build"))
def test_alpha003_restart_gap_requires_a_full_new_live_window_before_ready(mode):
    (
        cerebro,
        cohort,
        full_calendar,
        original_slots,
        _history,
        startup,
        plan,
        factor_name,
    ) = _restart_setup(mode=mode)

    strategy = cerebro.run()[0]
    gap = cohort.restart_gap
    assert gap is not None
    assert gap.full_original_calendar_fingerprint == full_calendar.fingerprint
    assert gap.original_scope_first_slot_id == original_slots[0].slot_id
    assert gap.original_scope_last_slot_id == original_slots[-1].slot_id
    assert gap.history_highwater_original_slot_index == HISTORY_LAST_INDEX
    assert gap.omitted_start_original_slot_index == 18
    assert gap.omitted_end_original_slot_index == FIRST_LIVE_ORIGINAL_INDEX
    assert gap.omitted_slot_count == 3
    assert gap.omitted_elapsed_slot_count == 2
    assert gap.omitted_partial_slot_id == original_slots[20].slot_id
    assert gap.startup_time_utc == startup
    assert gap.first_live_slot_id == original_slots[FIRST_LIVE_ORIGINAL_INDEX].slot_id
    old_highwater_member = gap.journal_highwater.members[MEMBER_ID]
    assert old_highwater_member.source_role == "live"
    assert old_highwater_member.connection_generation == OLD_CONNECTION_GENERATION
    assert cohort.calendar_fingerprint != full_calendar.fingerprint
    assert not any(
        row.slot_id in {slot.slot_id for slot in original_slots[18:21]}
        for row in cohort._calendar.slots
    )

    replayed_highwater = [
        snapshot
        for snapshot in strategy.snapshots
        if snapshot.close_time == old_highwater_member.close_time
    ]
    assert len(replayed_highwater) == 1
    replayed_highwater_value = replayed_highwater[0].factors[factor_name].values["A"]
    assert replayed_highwater_value.source_role == "history"
    assert replayed_highwater_value.generation == old_highwater_member.connection_generation
    assert replayed_highwater_value.sequence == old_highwater_member.feed_sequence

    instance = strategy.live_factors.factor_instances[factor_name]["primary"]
    required_count = max(1, instance._minperiod, _executed_graph_span(instance))
    live_snapshots = [
        snapshot
        for snapshot in strategy.snapshots
        if snapshot.factors[factor_name].values["A"].source_role == "live"
    ]
    assert len(live_snapshots) == LIVE_BAR_COUNT
    assert required_count <= LIVE_BAR_COUNT
    for snapshot in live_snapshots[: required_count - 1]:
        assert snapshot.readiness is LiveFactorReadiness.WARMUP
        assert "restart_gap_rewarming" in snapshot.readiness_reasons
    assert live_snapshots[required_count - 1].readiness is LiveFactorReadiness.LIVE_READY
    assert all(
        snapshot.readiness is LiveFactorReadiness.LIVE_READY
        for snapshot in live_snapshots[required_count - 1 :]
    )


def test_recursive_factor_history_remains_unqualified_after_restart_gap():
    cerebro, cohort, _full, _slots, _history, _startup, _plan, factor_name = _restart_setup(
        indicator=RecursiveCloseSum
    )

    strategy = cerebro.run()[0]
    live_snapshots = [
        snapshot
        for snapshot in strategy.snapshots
        if snapshot.factors[factor_name].values["A"].source_role == "live"
    ]
    assert len(live_snapshots) == LIVE_BAR_COUNT
    assert all(snapshot.readiness is not LiveFactorReadiness.LIVE_READY for snapshot in live_snapshots)
    assert all("history_restart_gap" in snapshot.readiness_reasons for snapshot in live_snapshots)
    proof = cohort.current_batch().history_continuity[MEMBER_ID]
    assert proof.qualified is False
    assert proof.reason == "history_restart_gap"
    assert proof.origin_receipt is not None
    assert proof.origin_receipt.close_time == START + timedelta(minutes=1)


def test_restart_factory_rejects_future_omissions_and_replayed_highwater_tampering():
    full_calendar, slots = _full_calendar()
    highwater = _old_highwater(slots)
    with pytest.raises(LiveCohortValidationError, match="future unelapsed"):
        LiveCohortCalendar.with_restart_gap(
            full_calendar,
            startup_time_utc=slots[18].bucket_start,
            journal_highwater=highwater,
            first_live_slot_id=slots[FIRST_LIVE_ORIGINAL_INDEX].slot_id,
        )

    startup = slots[20].bucket_start + timedelta(seconds=30)
    member = replace(highwater.members[MEMBER_ID], feed_sequence=highwater.members[MEMBER_ID].feed_sequence - 1)
    tampered_highwater = replace(highwater, members={MEMBER_ID: member})
    calendar = LiveCohortCalendar.with_restart_gap(
        full_calendar,
        startup_time_utc=startup,
        journal_highwater=tampered_highwater,
        first_live_slot_id=slots[FIRST_LIVE_ORIGINAL_INDEX].slot_id,
    )
    cohort, feed = _bare_cohort(calendar)
    actual_highwater_event = _event(
        slots[HISTORY_LAST_INDEX],
        HISTORY_LAST_INDEX + 1,
        role="history",
        generation=HISTORY_REPLAY_GENERATION,
    )
    with pytest.raises(LiveCohortValidationError, match="high-water differs"):
        cohort.capture_bar(feed, actual_highwater_event, source_role="history")
    assert cohort.frozen is True


def test_restart_factory_rejects_bucket_at_exact_start_as_unelapsed():
    full_calendar, slots = _full_calendar()
    highwater = _old_highwater(slots)

    with pytest.raises(LiveCohortValidationError, match="future unelapsed"):
        LiveCohortCalendar.with_restart_gap(
            full_calendar,
            startup_time_utc=slots[HISTORY_LAST_INDEX + 1].bucket_start,
            journal_highwater=highwater,
            first_live_slot_id=slots[HISTORY_LAST_INDEX + 2].slot_id,
        )


@pytest.mark.parametrize(
    ("slot_index", "source_role", "message"),
    (
        (18, "history", "explicit planned calendar slot"),
        (HISTORY_LAST_INDEX, "live", "restart history prefix"),
        (FIRST_LIVE_ORIGINAL_INDEX + 1, "history", "restart live tail"),
    ),
)
def test_restart_calendar_rejects_omitted_slots_and_role_order_violations(
    slot_index, source_role, message
):
    _full, slots = _full_calendar()
    highwater = _old_highwater(slots)
    calendar = LiveCohortCalendar.with_restart_gap(
        _full,
        startup_time_utc=slots[20].bucket_start + timedelta(seconds=30),
        journal_highwater=highwater,
        first_live_slot_id=slots[FIRST_LIVE_ORIGINAL_INDEX].slot_id,
    )
    cohort, feed = _bare_cohort(calendar)
    generation = (
        OLD_CONNECTION_GENERATION if slot_index == HISTORY_LAST_INDEX else "live-generation-8"
    )
    event = _event(slots[slot_index], slot_index + 1, role=source_role, generation=generation)
    with pytest.raises(LiveCohortValidationError, match=message):
        cohort.capture_bar(feed, event, source_role=source_role)
    assert cohort.frozen is True


def test_active_planned_slot_timeout_still_freezes_with_gap_receipt():
    full_calendar, slots = _full_calendar()
    cohort, _feed = _bare_cohort(full_calendar, wait_timeout_ns=10)
    cohort.seal()
    first = cohort.prepare_round(1, source_time_utc=slots[0].close_time)
    assert first.status == "WAITING"
    timed_out = cohort.prepare_round(
        11,
        source_time_utc=slots[0].close_time,
    )
    assert timed_out.status == "GAP"
    assert timed_out.reason == "planned_gap_requires_rebuild"
    assert cohort.frozen is True
    assert cohort.frozen_reason == "planned_gap_requires_rebuild"
