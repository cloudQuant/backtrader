"""Real feed/Cerebro revision notices freeze the old cohort before line writes."""

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


_MEMBERS = ("A", "B")
_FIELDS = ("open", "high", "low", "close", "volume", "openinterest")
_MISSING = object()


class _FiniteClose(CohortClose):
    history_contract = FactorHistoryContract.finite_window(span_bars=1)


class _RevisionStrategy(CohortStrategy):
    instances = []

    def __init__(self):
        self.delivered_batch_objects = []
        super().__init__()
        type(self).instances.append(self)

    def next(self):
        super().next()
        self.delivered_batch_objects.append(self.p.cohort.current_batch())


def _calendar(
    *,
    calendar_id="revision-calendar",
    version="v1",
    epoch_id=1,
    start=START,
    session_semantics="session-v1",
):
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
    return LiveCohortCalendar(
        calendar_id=calendar_id,
        version=version,
        epoch_id=epoch_id,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="clock-replay",
        session_semantics=session_semantics,
        slots=slots,
    )


def _same_calendar_identity(calendar):
    return LiveCohortCalendar(
        calendar_id=calendar.calendar_id,
        version=calendar.version,
        epoch_id=calendar.epoch_id,
        frequency=calendar.frequency,
        frequency_seconds=calendar.frequency_seconds,
        timezone_id=calendar.timezone_id,
        clock_domain_id=calendar.clock_domain_id,
        session_semantics=calendar.session_semantics,
        slots=calendar.slots,
    )


def _install_mapping_notifications(monkeypatch):
    original = CohortStrategy.notify_bar

    def notify_bar(strategy, bar):
        if isinstance(bar, Mapping):
            bar = SimpleNamespace(symbol=bar["symbol"])
        original(strategy, bar)

    monkeypatch.setattr(CohortStrategy, "notify_bar", notify_bar)


def _compose_epoch(
    *,
    cohort_id,
    calendar,
    member_rules,
    rule_overrides=None,
    calendar_notices=None,
):
    rule_overrides = {} if rule_overrides is None else rule_overrides
    calendar_notices = {} if calendar_notices is None else calendar_notices
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
        for slot_index, slot in enumerate(calendar.slots):
            event = _event(slot, name, slot_index + 1, 10.0 + member_index + slot_index)
            event["connection_generation"] = "revision-test-generation"
            event["bar_id"] = "%s-%d" % (name, slot_index + 1)
            rules_hash = rule_overrides.get((name, slot_index), member_rules.get(name))
            if rules_hash is not _MISSING and rules_hash is not None:
                event["rules_hash"] = rules_hash
            notice = calendar_notices.get((name, slot_index), _MISSING)
            if notice is not _MISSING:
                event["calendar_revision"] = notice
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
            rules_hash=member_rules.get(name),
        )

    plan = LiveFactorPlan(
        targets=_MEMBERS,
        factors={
            "close_value": FactorSpec(
                name="close_value",
                indicator=_FiniteClose,
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
    cerebro = bt.Cerebro(stdstats=False, preload=False, runonce=False)
    for name in _MEMBERS:
        cerebro.adddata(feeds[name], name=name)
    cerebro.addstrategy(_RevisionStrategy, cohort=cohort, plan=plan)
    cerebro.add_live_bar_cohort(cohort, clock=FakeClock(calendar.slots[-1].close_time))
    return cerebro, cohort, feeds


def _assert_epoch_ready(strategy, cohort):
    assert len(strategy.snapshots) == 2
    assert all(snapshot.readiness.value == "LIVE_READY" for snapshot in strategy.snapshots), [
        (snapshot.readiness.value, snapshot.readiness_reasons) for snapshot in strategy.snapshots
    ]
    assert cohort.current_batch() is strategy.delivered_batch_objects[-1]
    assert cohort.current_batch().status == "COMPLETE"


@pytest.mark.integration
@pytest.mark.parametrize("change", ("missing", "different"))
def test_claimed_member_rules_revision_freezes_before_write_then_rebuilds(monkeypatch, change):
    _install_mapping_notifications(monkeypatch)
    _RevisionStrategy.instances.clear()
    old_calendar = _calendar()
    claimed = {"A": "rules-A-v1", "B": "rules-B-v1"}
    changed_value = _MISSING if change == "missing" else "rules-A-v2"
    old_cerebro, old_cohort, old_feeds = _compose_epoch(
        cohort_id="rules-old-cohort",
        calendar=old_calendar,
        member_rules=claimed,
        rule_overrides={("A", 1): changed_value},
    )

    with pytest.raises(LiveCohortFrozenError, match="member rules revision changed"):
        old_cerebro.run()

    old_strategy = _RevisionStrategy.instances[-1]
    completed = old_cohort.current_batch()
    assert completed is old_strategy.delivered_batch_objects[0]
    assert completed.slot_index == 0
    assert completed.members["member-A"].envelope.rules_hash == "rules-A-v1"
    assert old_cohort.frozen_reason == "member_rules_revision_changed"
    assert old_strategy.strategy_batches == [completed.batch_id]
    assert [len(old_feeds[name]) for name in _MEMBERS] == [1, 1]
    frozen_lines = {name: tuple(old_feeds[name].close.array) for name in _MEMBERS}
    assert frozen_lines == {name: (10.0 + index,) for index, name in enumerate(_MEMBERS)}
    assert old_cohort.current_batch() is completed

    new_calendar = _calendar(
        calendar_id="revision-calendar",
        version="v1",
        epoch_id=2,
        start=old_calendar.slots[-1].close_time + timedelta(minutes=4),
    )
    new_claims = {"A": "rules-A-v2", "B": "rules-B-v1"}
    new_cerebro, new_cohort, _new_feeds = _compose_epoch(
        cohort_id="rules-rebuilt-cohort",
        calendar=new_calendar,
        member_rules=new_claims,
    )
    new_strategy = new_cerebro.run()[0]
    _assert_epoch_ready(new_strategy, new_cohort)
    assert new_cohort.member_for_feed(_new_feeds["A"]).rules_hash == "rules-A-v2"


@pytest.mark.integration
@pytest.mark.parametrize("change", ("calendar_id", "version", "fingerprint"))
def test_calendar_revision_notice_freezes_then_new_calendar_epoch_runs(monkeypatch, change):
    _install_mapping_notifications(monkeypatch)
    _RevisionStrategy.instances.clear()
    old_calendar = _calendar()
    same_identity_copy = _same_calendar_identity(old_calendar)
    changes = {
        "calendar_id": {"calendar_id": "revision-calendar-next"},
        "version": {"version": "v2"},
        # Keep ID and version fixed while changing the immutable calendar body.
        "fingerprint": {"session_semantics": "session-v2"},
    }
    revised_options = dict(changes[change])
    revised_options["start"] = START
    revised_calendar = _calendar(**revised_options)
    notices = {(name, 0): same_identity_copy for name in _MEMBERS}
    notices.update({(name, 1): revised_calendar for name in _MEMBERS})
    old_cerebro, old_cohort, old_feeds = _compose_epoch(
        cohort_id="calendar-old-cohort",
        calendar=old_calendar,
        member_rules={"A": None, "B": None},
        calendar_notices=notices,
    )

    with pytest.raises(LiveCohortFrozenError, match="calendar revision changed"):
        old_cerebro.run()

    old_strategy = _RevisionStrategy.instances[-1]
    completed = old_cohort.current_batch()
    assert completed is old_strategy.delivered_batch_objects[0]
    assert completed.slot_index == 0
    assert old_cohort.frozen_reason == "calendar_revision_changed"
    assert old_strategy.strategy_batches == [completed.batch_id]
    assert [len(old_feeds[name]) for name in _MEMBERS] == [1, 1]
    assert old_cohort.current_batch() is completed

    new_calendar = _calendar(
        calendar_id=revised_calendar.calendar_id,
        version=revised_calendar.version,
        epoch_id=2,
        start=old_calendar.slots[-1].close_time + timedelta(minutes=4),
        session_semantics=revised_calendar.session_semantics,
    )
    new_notices = {
        (name, slot_index): _same_calendar_identity(new_calendar)
        for name in _MEMBERS
        for slot_index in range(2)
    }
    new_cerebro, new_cohort, _new_feeds = _compose_epoch(
        cohort_id="calendar-rebuilt-cohort",
        calendar=new_calendar,
        member_rules={"A": None, "B": None},
        calendar_notices=new_notices,
    )
    new_strategy = new_cerebro.run()[0]
    _assert_epoch_ready(new_strategy, new_cohort)
    assert new_cohort.calendar_version == revised_calendar.version
    assert new_cohort.calendar_id == revised_calendar.calendar_id


@pytest.mark.integration
def test_unclaimed_rules_revision_keeps_legacy_cohort_admission_unqualified(monkeypatch):
    _install_mapping_notifications(monkeypatch)
    _RevisionStrategy.instances.clear()
    calendar = _calendar()
    cerebro, cohort, feeds = _compose_epoch(
        cohort_id="legacy-unclaimed-rules-cohort",
        calendar=calendar,
        member_rules={"A": None, "B": None},
    )

    strategy = cerebro.run()[0]

    _assert_epoch_ready(strategy, cohort)
    assert all(cohort.member_for_feed(feeds[name]).rules_hash is None for name in _MEMBERS)
    assert all(
        receipt.envelope.rules_hash is None for receipt in cohort.current_batch().members.values()
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("override", "calendar_notice", "reason", "message"),
    (
        (123, _MISSING, "invalid_rules_revision_notice", "rules revision notice is malformed"),
        (
            _MISSING,
            "calendar-v2",
            "invalid_calendar_revision_notice",
            "calendar revision notice is malformed",
        ),
    ),
)
def test_malformed_revision_notice_freezes_before_any_line_write(
    monkeypatch, override, calendar_notice, reason, message
):
    _install_mapping_notifications(monkeypatch)
    _RevisionStrategy.instances.clear()
    calendar = _calendar()
    rule_overrides = {} if override is _MISSING else {("A", 1): override}
    calendar_notices = {} if calendar_notice is _MISSING else {("A", 1): calendar_notice}
    cerebro, cohort, feeds = _compose_epoch(
        cohort_id="malformed-revision-cohort",
        calendar=calendar,
        member_rules={"A": "rules-A-v1", "B": "rules-B-v1"},
        rule_overrides=rule_overrides,
        calendar_notices=calendar_notices,
    )

    with pytest.raises(LiveCohortFrozenError, match=message):
        cerebro.run()

    strategy = _RevisionStrategy.instances[-1]
    completed = cohort.current_batch()
    assert completed is strategy.delivered_batch_objects[0]
    assert cohort.frozen_reason == reason
    assert strategy.strategy_batches == [completed.batch_id]
    assert [len(feeds[name]) for name in _MEMBERS] == [1, 1]
    assert cohort.current_batch() is completed
