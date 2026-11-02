"""Focused contracts for bounded live bar cohort validation and delivery."""

import datetime as dt
import math
from decimal import Decimal
from types import MappingProxyType

import pytest

from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveCohortCapacityError,
    LiveCohortError,
    LiveCohortFrozenError,
    LiveCohortValidationError,
    LiveFirstBucketIncomplete,
    LiveInputBinding,
    _SAVED_HISTORY_ANCHOR_EVENT_KEY,
    _SAVED_HISTORY_RECORD_SOURCE_ROLE_EVENT_KEY,
    _VERIFIED_HISTORY_PROOF_EVENT_KEY,
    _make_verified_saved_history_journal_anchor,
)


UTC = dt.timezone.utc
BASE = dt.datetime(2026, 10, 20, 9, 30, tzinfo=UTC)
RAW_FIELDS = ("open", "high", "low", "close", "volume", "openinterest")
LINE_FIELDS = ("open", "high", "low", "close", "volume")


def make_calendar(count=3, *, epoch_id=1, start=BASE, version="v1"):
    slots = tuple(
        LiveCalendarSlot(
            slot_id="slot-{}".format(index),
            bucket_start=start + dt.timedelta(minutes=index),
            close_time=start + dt.timedelta(minutes=index + 1),
            trading_day="2026-10-20",
            session_segment="regular",
        )
        for index in range(count)
    )
    return LiveCohortCalendar(
        calendar_id="XNYS-1m",
        version=version,
        epoch_id=epoch_id,
        frequency="1m",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="source-clock-A",
        session_semantics="XNYS-regular-v1",
        slots=slots,
    )


def make_cohort(
    member_count=2,
    *,
    count=3,
    epoch_id=1,
    cohort_id="cohort-A",
    wait_timeout_ns=100,
    max_pending_slots=None,
    max_window_bars=None,
):
    cohort = LiveBarCohort(
        cohort_id,
        make_calendar(count, epoch_id=epoch_id),
        max_pending_slots=max(count, 1) if max_pending_slots is None else max_pending_slots,
        max_window_bars=(min(max(count, 1), 16) if max_window_bars is None else max_window_bars),
        wait_timeout_ns=wait_timeout_ns,
    )
    feeds = {}
    for index in range(member_count):
        feed = object()
        member_id = "asset-{}".format(index)
        feeds[member_id] = feed
        cohort.register_member(
            member_id,
            feed,
            instrument="SYM{}".format(index),
            source_ref="provider-feed-{}".format(index),
            line_fields=LINE_FIELDS,
            raw_fields=RAW_FIELDS,
        )
    cohort.seal()
    return cohort, feeds


def make_event(
    member_id,
    slot_index,
    *,
    source_role="live",
    sequence=None,
    close=None,
    origin_partition=None,
):
    start = BASE + dt.timedelta(minutes=slot_index)
    end = start + dt.timedelta(minutes=1)
    close_value = float(100 + slot_index if close is None else close)
    event = {
        "instrument": "SYM{}".format(member_id.rsplit("-", 1)[1]),
        "symbol": "SYM{}".format(member_id.rsplit("-", 1)[1]),
        "timestamp": end.timestamp(),
        "bucket_start": start,
        "bucket_end": end,
        "available_at": end + dt.timedelta(seconds=2),
        "trading_day": "2026-10-20",
        "session_segment": "regular",
        "timezone_id": "UTC",
        "clock_domain_id": "source-clock-A",
        "connection_generation": "gen-{}".format(source_role),
        "bar_sequence": slot_index + 1 if sequence is None else sequence,
        "bar_id": "{}:{}:{}".format(member_id, source_role, slot_index),
        "open": close_value - 0.5,
        "high": close_value + 0.5,
        "low": close_value - 1.0,
        "close": close_value,
        "volume": float(slot_index + 10),
        "openinterest": 0.0,
        "complete": True,
        "quality": "GOOD",
        "quality_flags": (),
        "source": "test-source",
        "received_monotonic_ns": 10_000 + slot_index,
    }
    if origin_partition is not None:
        event["origin_partition"] = origin_partition
    return event


def capture_slot(cohort, feeds, slot_index, *, role="live", sequences=None):
    for member_id, feed in feeds.items():
        sequence = None if sequences is None else sequences[member_id]
        cohort.capture_bar(
            feed,
            make_event(member_id, slot_index, source_role=role, sequence=sequence),
            source_role=role,
        )


def deliver_prepared(cohort, feeds, now_ns):
    result = cohort.prepare_round(now_ns, source_time_utc=BASE + dt.timedelta(minutes=10))
    assert result.status == "READY"
    prepared = result.prepared
    for member_id, feed in feeds.items():
        envelope = prepared.envelopes[member_id]
        values = cohort.preflight_delivery(feed, envelope)
        assert values["close"] == envelope.raw_values["close"]
        cohort.record_delivery(feed, envelope, delivered_close_time=envelope.close_time)
    return cohort.current_batch()


def test_complete_batch_publishes_only_after_every_exact_feed_delivery():
    cohort, feeds = make_cohort(member_count=3, count=2)
    assert cohort.current_batch() is None
    capture_slot(cohort, feeds, 0)
    prepared = cohort.prepare_round(20_000, source_time_utc=BASE + dt.timedelta(minutes=2)).prepared
    assert prepared is not None
    first_id, first_feed = next(iter(feeds.items()))
    first_envelope = prepared.envelopes[first_id]
    receipt = cohort.record_delivery(
        first_feed,
        first_envelope,
        delivered_close_time=first_envelope.close_time,
    )
    assert receipt.feed_ref is first_feed
    assert cohort.current_batch() is None
    assert cohort.current_delivery(first_feed) is None
    for member_id, feed in list(feeds.items())[1:]:
        envelope = prepared.envelopes[member_id]
        cohort.record_delivery(feed, envelope, delivered_close_time=envelope.close_time)
    batch = cohort.current_batch()
    assert batch is not None
    assert set(batch.members) == set(feeds)
    assert batch.close_time == BASE + dt.timedelta(minutes=1)
    assert batch.available_at == BASE + dt.timedelta(minutes=1, seconds=2)
    assert batch.receipt_for_feed(first_feed) is receipt
    assert cohort.current_delivery(first_feed) is receipt
    assert cohort.prepared_envelope(first_feed) is None


def test_record_delivery_batch_publishes_all_member_receipts_once():
    cohort, feeds = make_cohort(member_count=3, count=1)
    capture_slot(cohort, feeds, 0)
    result = cohort.prepare_round(20_000, source_time_utc=BASE + dt.timedelta(minutes=2))
    assert result.status == "READY"
    prepared = result.prepared
    deliveries = tuple(
        (feed, prepared.envelopes[member_id], prepared.envelopes[member_id].close_time)
        for member_id, feed in reversed(tuple(feeds.items()))
    )

    batch = cohort.record_delivery_batch(deliveries)

    assert batch is cohort.current_batch()
    assert batch.status == "COMPLETE"
    assert set(batch.members) == set(feeds)
    for member_id, feed in feeds.items():
        receipt = batch.receipt_for_feed(feed)
        assert receipt is not None
        assert receipt is cohort.current_delivery(feed)
        assert receipt.envelope is prepared.envelopes[member_id]
    assert cohort._prepared is None
    assert cohort._delivered == {}
    assert cohort._next_slot_index == 1
    assert all(len(cohort._window_receipts[member_id]) == 1 for member_id in feeds)


def test_record_delivery_batch_later_validation_failure_preserves_previous_batch():
    cohort, feeds = make_cohort(member_count=2, count=2)
    capture_slot(cohort, feeds, 0)
    first_batch = deliver_prepared(cohort, feeds, 20_000)
    assert first_batch is cohort.current_batch()

    capture_slot(cohort, feeds, 1)
    result = cohort.prepare_round(20_001, source_time_utc=BASE + dt.timedelta(minutes=3))
    assert result.status == "READY"
    prepared = result.prepared
    prior_window = {key: tuple(value) for key, value in cohort._window_receipts.items()}
    prior_signatures = dict(cohort._recent_signatures)
    prior_signature_order = tuple(cohort._recent_signature_order)
    prior_history = dict(cohort._history_last_close)
    prior_first_live = dict(cohort._first_live_receipt)
    prior_pending = cohort._pending[prepared.slot_index]
    deliveries = [
        (feed, prepared.envelopes[member_id], prepared.envelopes[member_id].close_time)
        for member_id, feed in feeds.items()
    ]
    last_feed, last_envelope, _ = deliveries[-1]
    deliveries[-1] = (last_feed, last_envelope, last_envelope.close_time + dt.timedelta(seconds=1))

    with pytest.raises(LiveCohortValidationError, match="line datetime"):
        cohort.record_delivery_batch(tuple(deliveries))

    assert cohort.current_batch() is first_batch
    assert cohort._prepared is prepared
    assert cohort._delivered == {}
    assert cohort._next_slot_index == 1
    assert cohort._pending[prepared.slot_index] is prior_pending
    assert {key: tuple(value) for key, value in cohort._window_receipts.items()} == prior_window
    assert cohort._recent_signatures == prior_signatures
    assert tuple(cohort._recent_signature_order) == prior_signature_order
    assert cohort._history_last_close == prior_history
    assert cohort._first_live_receipt == prior_first_live


@pytest.mark.parametrize("failure_point", ["before_publish", "during_publish"])
def test_record_delivery_batch_rolls_back_injected_publish_failure(monkeypatch, failure_point):
    cohort, feeds = make_cohort(member_count=2, count=3, max_window_bars=1)
    capture_slot(cohort, feeds, 0)
    capture_slot(cohort, feeds, 1)
    capture_slot(cohort, feeds, 2)
    first_batch = deliver_prepared(cohort, feeds, 20_000)
    result = cohort.prepare_round(20_001, source_time_utc=BASE + dt.timedelta(minutes=3))
    assert result.status == "READY"
    prepared = result.prepared
    prior_window = {key: tuple(value) for key, value in cohort._window_receipts.items()}
    prior_signatures = dict(cohort._recent_signatures)
    prior_signature_order = tuple(cohort._recent_signature_order)
    prior_pending = cohort._pending[prepared.slot_index]
    prior_history = dict(cohort._history_last_close)
    prior_first_live = dict(cohort._first_live_receipt)
    prior_pending_order = tuple(cohort._pending.items())
    deliveries = tuple(
        (feed, prepared.envelopes[member_id], prepared.envelopes[member_id].close_time)
        for member_id, feed in feeds.items()
    )
    original_remember = cohort._remember_signature
    original_setattr = type(cohort).__setattr__
    if failure_point == "before_publish":

        def fail_before_signature(slot_index, member_id, signature):
            raise RuntimeError("injected before signature publication")

        monkeypatch.setattr(cohort, "_remember_signature", fail_before_signature)
    else:
        triggered = False

        def fail_at_batch_commit(instance, name, value):
            nonlocal triggered
            if (
                instance is cohort
                and name == "_current_batch"
                and value is not first_batch
                and not triggered
            ):
                triggered = True
                raise RuntimeError("injected before batch commit")
            original_setattr(instance, name, value)

        monkeypatch.setattr(LiveBarCohort, "__setattr__", fail_at_batch_commit)
    with pytest.raises(RuntimeError, match="injected"):
        cohort.record_delivery_batch(deliveries)

    assert cohort.current_batch() is first_batch
    assert cohort._prepared is prepared
    assert cohort._delivered == {}
    assert cohort._next_slot_index == 1
    assert cohort._pending[prepared.slot_index] is prior_pending
    assert tuple(cohort._pending.items()) == prior_pending_order
    assert {key: tuple(value) for key, value in cohort._window_receipts.items()} == prior_window
    assert cohort._recent_signatures == prior_signatures
    assert tuple(cohort._recent_signature_order) == prior_signature_order
    assert cohort._history_last_close == prior_history
    assert cohort._first_live_receipt == prior_first_live

    monkeypatch.setattr(cohort, "_remember_signature", original_remember)
    monkeypatch.setattr(LiveBarCohort, "__setattr__", original_setattr)
    retried = cohort.record_delivery_batch(deliveries)
    assert retried is cohort.current_batch()
    assert retried.slot_index == 1


def test_member_sessions_accept_heterogeneous_exchange_day_and_segment_metadata():
    sessions = {
        "asset-0": LiveCalendarMemberSession("2026-10-20", "XSHG-day"),
        "asset-1": LiveCalendarMemberSession("2026-10-21", "CME-overnight"),
    }
    slot = LiveCalendarSlot(
        slot_id="heterogeneous-slot",
        bucket_start=BASE,
        close_time=BASE + dt.timedelta(minutes=1),
        trading_day="shared-legacy-day",
        session_segment="shared-legacy-segment",
        member_sessions=sessions,
    )
    calendar = LiveCohortCalendar(
        calendar_id="multi-exchange-1m",
        version="v1",
        epoch_id=3,
        frequency="1m",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="source-clock-A",
        session_semantics="per-exchange-v1",
        slots=(slot,),
    )
    cohort = LiveBarCohort("multi-exchange", calendar, max_window_bars=2)
    feeds = {}
    for index, member_id in enumerate(("asset-0", "asset-1")):
        feed = object()
        feeds[member_id] = feed
        cohort.register_member(
            member_id,
            feed,
            instrument="SYM{}".format(index),
            source_ref="provider-feed-{}".format(index),
            line_fields=LINE_FIELDS,
            raw_fields=RAW_FIELDS,
        )

    cohort.seal()
    assert isinstance(slot.member_sessions, MappingProxyType)
    with pytest.raises(TypeError):
        slot.member_sessions["asset-2"] = LiveCalendarMemberSession("2026-10-22", "other")

    for member_id, feed in feeds.items():
        event = make_event(member_id, 0)
        expected = slot.member_sessions[member_id]
        event["trading_day"] = expected.trading_day
        event["session_segment"] = expected.session_segment
        cohort.capture_bar(feed, event, source_role="live")

    prepared = cohort.prepare_round(20_000, source_time_utc=BASE + dt.timedelta(minutes=5)).prepared
    assert prepared is not None
    for member_id, feed in feeds.items():
        envelope = prepared.envelopes[member_id]
        cohort.record_delivery(feed, envelope, delivered_close_time=envelope.close_time)
    batch = cohort.current_batch()
    assert batch is not None and batch.status == "COMPLETE"
    assert cohort.is_final_batch(batch)
    assert calendar.fingerprint == calendar.calendar_fingerprint

    legacy_calendar = LiveCohortCalendar(
        calendar_id="multi-exchange-1m",
        version="v1",
        epoch_id=3,
        frequency="1m",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="source-clock-A",
        session_semantics="per-exchange-v1",
        slots=(
            LiveCalendarSlot(
                slot_id="heterogeneous-slot",
                bucket_start=BASE,
                close_time=BASE + dt.timedelta(minutes=1),
                trading_day="shared-legacy-day",
                session_segment="shared-legacy-segment",
            ),
        ),
    )
    assert calendar.fingerprint != legacy_calendar.fingerprint


@pytest.mark.parametrize(
    "member_sessions, expected_fragment",
    [
        (
            {"asset-0": LiveCalendarMemberSession("2026-10-20", "day")},
            "missing=('asset-1',)",
        ),
        (
            {
                "asset-0": LiveCalendarMemberSession("2026-10-20", "day"),
                "asset-1": LiveCalendarMemberSession("2026-10-21", "night"),
                "unregistered": LiveCalendarMemberSession("2026-10-22", "extra"),
            },
            "extra=('unregistered',)",
        ),
    ],
)
def test_seal_rejects_missing_or_extra_member_session_evidence(member_sessions, expected_fragment):
    slot = LiveCalendarSlot(
        slot_id="coverage-slot",
        bucket_start=BASE,
        close_time=BASE + dt.timedelta(minutes=1),
        trading_day="legacy-day",
        session_segment="legacy-segment",
        member_sessions=member_sessions,
    )
    calendar = LiveCohortCalendar(
        calendar_id="coverage-calendar",
        version="v1",
        epoch_id=1,
        frequency="1m",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="source-clock-A",
        session_semantics="shared-session-contract",
        slots=(slot,),
    )
    cohort = LiveBarCohort("coverage-cohort", calendar, max_window_bars=2)
    for index in range(2):
        cohort.register_member(
            "asset-{}".format(index),
            object(),
            instrument="SYM{}".format(index),
            source_ref="source-{}".format(index),
            line_fields=LINE_FIELDS,
            raw_fields=RAW_FIELDS,
        )

    with pytest.raises(LiveCohortValidationError) as raised:
        cohort.seal()
    assert expected_fragment in str(raised.value)
    assert cohort._sealed is False


def test_successful_seal_is_idempotent_across_capture_and_prepare():
    session = LiveCalendarMemberSession("2026-10-20", "regular")
    calendar = LiveCohortCalendar(
        calendar_id="seal-calendar",
        version="v1",
        epoch_id=1,
        frequency="1m",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="source-clock-A",
        session_semantics="XNYS-regular-v1",
        slots=(
            LiveCalendarSlot(
                slot_id="slot-0",
                bucket_start=BASE,
                close_time=BASE + dt.timedelta(minutes=1),
                trading_day="2026-10-20",
                session_segment="regular",
                member_sessions={"asset-0": session, "asset-1": session},
            ),
        ),
    )

    class CountingSlots(tuple):
        def __new__(cls, values):
            result = super().__new__(cls, values)
            result.iterations = 0
            return result

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

    slots = CountingSlots(calendar.slots)
    object.__setattr__(calendar, "slots", slots)
    cohort = LiveBarCohort("seal-cohort", calendar, max_window_bars=2)
    slots.iterations = 0

    feeds = {member_id: object() for member_id in ("asset-0", "asset-1")}
    cohort.register_member(
        "asset-0",
        feeds["asset-0"],
        instrument="SYM0",
        source_ref="source-0",
        line_fields=LINE_FIELDS,
        raw_fields=RAW_FIELDS,
    )
    with pytest.raises(LiveCohortValidationError, match=r"extra=\('asset-1',\)"):
        cohort.seal()
    assert slots.iterations == 1
    assert cohort._sealed is False

    cohort.register_member(
        "asset-1",
        feeds["asset-1"],
        instrument="SYM1",
        source_ref="source-1",
        line_fields=LINE_FIELDS,
        raw_fields=RAW_FIELDS,
    )
    slots.iterations = 0
    cohort.seal()
    assert slots.iterations == 1

    slots.iterations = 0
    cohort.seal()
    for member_id, feed in feeds.items():
        cohort.capture_bar(feed, make_event(member_id, 0), source_role="live")
    prepared = cohort.prepare_round(
        20_000, source_time_utc=BASE + dt.timedelta(minutes=5)
    )
    assert prepared.status == "READY"
    assert slots.iterations == 0

    with pytest.raises(LiveCohortError, match="registration is sealed"):
        cohort.register_member(
            "asset-2",
            object(),
            instrument="SYM2",
            source_ref="source-2",
            line_fields=LINE_FIELDS,
            raw_fields=RAW_FIELDS,
        )
    assert cohort.member_ids == ("asset-0", "asset-1")


def test_capture_rejects_another_slot_members_future_session_metadata():
    slots = (
        LiveCalendarSlot(
            "slot-0",
            BASE,
            BASE + dt.timedelta(minutes=1),
            "legacy-day-0",
            "legacy-session-0",
            {
                "asset-0": LiveCalendarMemberSession("2026-10-20", "day-0"),
                "asset-1": LiveCalendarMemberSession("2026-10-21", "night-0"),
            },
        ),
        LiveCalendarSlot(
            "slot-1",
            BASE + dt.timedelta(minutes=1),
            BASE + dt.timedelta(minutes=2),
            "legacy-day-1",
            "legacy-session-1",
            {
                "asset-0": LiveCalendarMemberSession("2026-10-20", "day-1"),
                "asset-1": LiveCalendarMemberSession("2026-10-21", "night-1"),
            },
        ),
    )
    calendar = LiveCohortCalendar(
        calendar_id="future-metadata-calendar",
        version="v1",
        epoch_id=1,
        frequency="1m",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="source-clock-A",
        session_semantics="exchange-session-v1",
        slots=slots,
    )
    cohort = LiveBarCohort("future-metadata-cohort", calendar, max_window_bars=2)
    feed = object()
    cohort.register_member(
        "asset-0",
        feed,
        instrument="SYM0",
        source_ref="source-0",
        line_fields=LINE_FIELDS,
        raw_fields=RAW_FIELDS,
    )
    cohort.register_member(
        "asset-1",
        object(),
        instrument="SYM1",
        source_ref="source-1",
        line_fields=LINE_FIELDS,
        raw_fields=RAW_FIELDS,
    )
    cohort.seal()

    event = make_event("asset-0", 0)
    event["trading_day"] = slots[1].member_sessions["asset-0"].trading_day
    event["session_segment"] = slots[1].member_sessions["asset-0"].session_segment
    with pytest.raises(LiveCohortValidationError, match="planned slot"):
        cohort.capture_bar(feed, event, source_role="live")
    assert cohort.frozen_reason == "invalid_source_bar"


def test_is_final_batch_requires_exact_current_batch_at_finite_epoch_end():
    cohort, feeds = make_cohort(member_count=1, count=2)
    assert cohort.is_final_batch(None) is False

    capture_slot(cohort, feeds, 0)
    first_batch = deliver_prepared(cohort, feeds, 20_000)
    assert first_batch is not None
    assert cohort.is_final_batch(first_batch) is False

    capture_slot(cohort, feeds, 1)
    final_batch = deliver_prepared(cohort, feeds, 20_001)
    assert final_batch is not None
    assert cohort.is_final_batch(final_batch) is True
    assert cohort.is_final_batch(first_batch) is False
    assert cohort.is_final_batch(object()) is False


def test_next_wait_timeout_starts_missing_deadline_only_after_planned_close():
    cohort, feeds = make_cohort(member_count=1, count=1, wait_timeout_ns=5_000_000_000)
    close_time = BASE + dt.timedelta(minutes=1)

    before_close = cohort.next_wait_timeout(BASE + dt.timedelta(seconds=30), 10_000)
    assert before_close.status == "WAITING"
    assert before_close.timeout_seconds == 30.0
    assert before_close.reason == "planned_slot_not_closed"
    assert cohort._wait_started_ns is None

    at_close_before_prepare = cohort.next_wait_timeout(close_time, 20_000)
    assert at_close_before_prepare.status == "WAITING"
    assert at_close_before_prepare.timeout_seconds == 0.0
    assert at_close_before_prepare.reason == "due_wait_not_started"

    prepared = cohort.prepare_round(20_000, source_time_utc=close_time)
    assert prepared.status == "WAITING"
    assert cohort._wait_started_ns == 20_000
    after_one_second = cohort.next_wait_timeout(BASE, 1_000_020_000)
    assert after_one_second.status == "WAITING"
    assert after_one_second.timeout_seconds == 4.0

    deadline = 5_000_020_000
    at_deadline = cohort.next_wait_timeout(close_time, deadline)
    assert at_deadline.status == "WAITING"
    assert at_deadline.timeout_seconds == 0.0
    assert at_deadline.reason == "cohort_wait_deadline_reached"
    assert cohort.prepare_round(deadline, source_time_utc=close_time).status == "GAP"
    frozen = cohort.next_wait_timeout(close_time, deadline)
    assert frozen.status == "FROZEN"
    assert frozen.timeout_seconds is None


def test_next_wait_timeout_uses_latest_availability_and_returns_ready_immediately():
    cohort, feeds = make_cohort(member_count=1, count=1, wait_timeout_ns=5_000_000_000)
    close_time = BASE + dt.timedelta(minutes=1)
    available_at = close_time + dt.timedelta(seconds=2)
    event = make_event("asset-0", 0)
    event["available_at"] = available_at
    cohort.capture_bar(feeds["asset-0"], event, source_role="live")

    before_close = cohort.next_wait_timeout(close_time - dt.timedelta(seconds=30), 10_000)
    assert before_close.status == "WAITING"
    assert before_close.timeout_seconds == 30.0
    assert cohort._wait_started_ns is None

    at_close_before_prepare = cohort.next_wait_timeout(close_time, 20_000)
    assert at_close_before_prepare.status == "WAITING"
    assert at_close_before_prepare.timeout_seconds == 0.0
    waiting = cohort.prepare_round(20_000, source_time_utc=close_time)
    assert waiting.status == "WAITING_AVAILABILITY"

    after_one_second = cohort.next_wait_timeout(close_time, 1_000_020_000)
    assert after_one_second.status == "WAITING"
    assert after_one_second.timeout_seconds == 2.0
    assert after_one_second.reason == "bar_not_yet_available"
    before_availability = cohort.next_wait_timeout(
        close_time + dt.timedelta(seconds=1.25), 1_250_020_000
    )
    assert before_availability.timeout_seconds == 0.75

    available = cohort.next_wait_timeout(available_at, 2_000_020_000)
    assert available.status == "READY"
    assert available.timeout_seconds == 0.0
    prepared = cohort.prepare_round(2_000_020_000, source_time_utc=available_at)
    assert prepared.status == "READY"
    assert cohort.next_wait_timeout(available_at, 2_000_020_000).status == "READY"


def test_next_wait_timeout_caps_future_availability_by_monotonic_deadline():
    cohort, feeds = make_cohort(member_count=1, count=1, wait_timeout_ns=2_000_000_000)
    close_time = BASE + dt.timedelta(minutes=1)
    available_at = close_time + dt.timedelta(seconds=5)
    event = make_event("asset-0", 0)
    event["available_at"] = available_at
    cohort.capture_bar(feeds["asset-0"], event, source_role="live")

    assert cohort.prepare_round(50_000, source_time_utc=close_time).status == (
        "WAITING_AVAILABILITY"
    )
    after_one_second = cohort.next_wait_timeout(close_time + dt.timedelta(seconds=1), 1_000_050_000)
    assert after_one_second.status == "WAITING"
    assert after_one_second.timeout_seconds == 1.0
    deadline = 2_000_050_000
    assert cohort.next_wait_timeout(available_at, deadline).timeout_seconds == 0.0
    assert cohort.prepare_round(
        deadline, source_time_utc=close_time + dt.timedelta(seconds=2)
    ).status == ("AVAILABILITY_TIMEOUT")


def test_next_wait_timeout_reports_finite_exhaustion_and_frozen_state():
    cohort, feeds = make_cohort(member_count=1, count=1)
    capture_slot(cohort, feeds, 0)
    batch = deliver_prepared(cohort, feeds, 20_000)
    assert batch is not None
    exhausted = cohort.next_wait_timeout(BASE + dt.timedelta(minutes=10), 30_000)
    assert exhausted.status == "EXHAUSTED"
    assert exhausted.timeout_seconds is None
    assert exhausted.reason == "finite_calendar_exhausted"

    frozen_cohort, frozen_feeds = make_cohort(member_count=1, count=1)
    invalid = make_event("asset-0", 0)
    invalid["close"] = float("inf")
    with pytest.raises(LiveCohortValidationError):
        frozen_cohort.capture_bar(frozen_feeds["asset-0"], invalid, source_role="live")
    frozen = frozen_cohort.next_wait_timeout(BASE, 40_000)
    assert frozen.status == "FROZEN"
    assert frozen.timeout_seconds is None
    assert frozen.reason == "invalid_source_bar"


def test_factor_binding_is_cached_and_tied_to_exact_registered_feed():
    cohort, feeds = make_cohort(member_count=1, count=1)
    feed = feeds["asset-0"]
    binding = cohort.require_factor_field(feed, "close")
    assert isinstance(binding, LiveInputBinding)
    assert binding.feed_ref is feed
    assert cohort.require_factor_field(feed, "close") is binding
    assert cohort.owns_factor_binding(binding)
    assert not cohort.owns_factor_binding(object())
    assert cohort.member_for_feed(object()) is None
    with pytest.raises(LiveCohortValidationError):
        cohort.require_factor_field(object(), "close")


def test_history_live_overlap_deduplicates_without_replacing_source_receipt():
    cohort, feeds = make_cohort(member_count=1, count=2)
    feed = feeds["asset-0"]
    history = make_event("asset-0", 0, source_role="history", sequence=1)
    live_overlap = dict(history)
    live_overlap["bar_id"] = "live-overlap-same-content"
    live_overlap["connection_generation"] = "gen-live"
    live_overlap["bar_sequence"] = 50
    first = cohort.capture_bar(feed, history, source_role="history")
    overlap = cohort.capture_bar(feed, live_overlap, source_role="live")
    assert first.duplicate is False
    assert overlap.duplicate is True
    assert overlap.envelope is first.envelope
    batch = deliver_prepared(cohort, feeds, 30_000)
    assert batch.members["asset-0"].source_role == "history"
    assert cohort.epoch_cutover(feed) is None


def test_unproved_old_and_future_origin_partitions_are_rejected():
    malformed_cohort, malformed_feeds = make_cohort(member_count=1, count=1)
    malformed = make_event("asset-0", 0)
    malformed["origin_partition"] = {
        "schema": "backtrader.execution_source_origin_partition.v1",
        "cohort_id": "cohort-A",
        "epoch_id": 1,
        "member_id": "asset-0",
        "source_ref": "provider-feed-forged",
        "source_role": "live",
        "connection_generation": "gen-live",
    }
    with pytest.raises(LiveCohortValidationError, match="does not match the bar"):
        malformed_cohort.capture_bar(
            malformed_feeds["asset-0"], malformed, source_role="live"
        )

    cohort, feeds = make_cohort(
        member_count=1, count=3, epoch_id=3, cohort_id="cohort-current"
    )

    def origin(cohort_id, epoch_id):
        return {
            "schema": "backtrader.execution_source_origin_partition.v1",
            "cohort_id": cohort_id,
            "epoch_id": epoch_id,
            "member_id": "asset-0",
            "source_ref": "provider-feed-0",
            "source_role": "live",
            "connection_generation": "same-generation-label",
        }

    def history_event(slot_index, origin_partition):
        event = make_event(
            "asset-0",
            slot_index,
            source_role="history",
            origin_partition=origin_partition,
        )
        event["connection_generation"] = "same-generation-label"
        return event

    with pytest.raises(LiveCohortValidationError, match="verified journal anchor"):
        cohort.capture_bar(
            feeds["asset-0"],
            history_event(0, origin("cohort-1", 1)),
            source_role="history",
        )
    future_cohort, future_feeds = make_cohort(
        member_count=1, count=3, epoch_id=3, cohort_id="cohort-current"
    )
    with pytest.raises(LiveCohortValidationError, match="future epoch"):
        future_cohort.capture_bar(
            future_feeds["asset-0"],
            history_event(0, origin("cohort-4", 4)),
            source_role="history",
        )

    current_history = history_event(0, origin("cohort-current", 3))
    current_history["origin_partition"]["source_role"] = "history"
    current_cohort, current_feeds = make_cohort(
        member_count=1, count=1, epoch_id=3, cohort_id="cohort-current"
    )
    current_cohort.capture_bar(
        current_feeds["asset-0"], current_history, source_role="history"
    )

    mutations = (
        ("cohort_id", "cohort-other", None),
        ("member_id", "asset-other", None),
        ("source_ref", "provider-other", None),
        ("source_role", "live", None),
        ("connection_generation", "other-generation", None),
        (None, None, "2026-10-21"),
    )
    for partition_field, value, trading_day in mutations:
        invalid_cohort, invalid_feeds = make_cohort(
            member_count=1, count=1, epoch_id=3, cohort_id="cohort-current"
        )
        invalid_partition = origin("cohort-current", 3)
        invalid_partition["source_role"] = "history"
        invalid_event = history_event(0, invalid_partition)
        if partition_field is not None:
            invalid_event["origin_partition"][partition_field] = value
        if trading_day is not None:
            invalid_event["trading_day"] = trading_day
        with pytest.raises(LiveCohortValidationError):
            invalid_cohort.capture_bar(
                invalid_feeds["asset-0"], invalid_event, source_role="history"
            )


def _verified_saved_history_row(cohort, feed, member_id="asset-0", *, slot_index=0):
    member = cohort.member_for_feed(feed)
    origin = {
        "schema": "backtrader.execution_source_origin_partition.v1",
        "cohort_id": "cohort-prior-1",
        "epoch_id": 1,
        "member_id": member.member_id,
        "source_ref": member.source_ref,
        "source_role": "live",
        "connection_generation": "saved-generation",
    }
    event = make_event(
        member_id,
        slot_index,
        source_role="history",
        origin_partition=origin,
    )
    event.update(
        {
            "connection_generation": "saved-generation",
            "source_ref": member.source_ref,
            "present": True,
            "missing_fields": (),
            "rules_hash": None,
        }
    )
    tape_anchor = (
        "tape-file-1",
        "tape-record-{}".format(slot_index),
        slot_index + 1,
        "saved-batch-{}".format(slot_index),
        origin["cohort_id"],
        origin["epoch_id"],
        "XNYS-1m",
        "v1",
        "a" * 64,
        slot_index,
        "saved-slot-{}".format(slot_index),
        event["bucket_end"],
    )
    event[_SAVED_HISTORY_ANCHOR_EVENT_KEY] = tape_anchor
    event[_SAVED_HISTORY_RECORD_SOURCE_ROLE_EVENT_KEY] = "live"
    time_value = lambda value: value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    member_receipt = {
        "member_id": member.member_id,
        "source_ref": member.source_ref,
        "source_role": "live",
        "connection_generation": event["connection_generation"],
        "feed_sequence": event["bar_sequence"],
        "bar_id": event["bar_id"],
        "bucket_start": time_value(event["bucket_start"]),
        "close_time": time_value(event["bucket_end"]),
        "available_at": time_value(event["available_at"]),
        "trading_day": event["trading_day"],
        "session_segment": event["session_segment"],
        "timezone_id": member.timezone_id,
        "clock_domain_id": member.clock_domain_id,
        "complete": True,
        "quality": "GOOD",
        "present": True,
        "missing_fields": (),
        "quality_flags": (),
        "event_source": event["source"],
        "received_monotonic_ns": event["received_monotonic_ns"],
        "rules_hash": None,
        "origin_partition": origin,
    }
    anchor = _make_verified_saved_history_journal_anchor(
        decision_id="decision-{}".format(slot_index),
        receipt_sha256="b" * 64,
        tape_file_id=tape_anchor[0],
        tape_record_id=tape_anchor[1],
        tape_record_index=tape_anchor[2],
        batch_id=tape_anchor[3],
        source_cohort_id=tape_anchor[4],
        source_epoch_id=tape_anchor[5],
        calendar_id=tape_anchor[6],
        calendar_version=tape_anchor[7],
        calendar_fingerprint=tape_anchor[8],
        slot_index=tape_anchor[9],
        slot_id=tape_anchor[10],
        close_time=tape_anchor[11],
        member_receipt=member_receipt,
        origin_partition=origin,
    )
    proof = cohort._issue_verified_saved_history_origin_proof(feed, event, anchor)
    event[_VERIFIED_HISTORY_PROOF_EVENT_KEY] = proof
    return event


def test_verified_history_proof_rejects_cross_owner_member_and_single_byte_tamper():
    cohort, feeds = make_cohort(
        member_count=2, count=3, epoch_id=3, cohort_id="cohort-current"
    )
    proof_event = _verified_saved_history_row(cohort, feeds["asset-0"])

    other_owner, other_owner_feeds = make_cohort(
        member_count=2, count=3, epoch_id=3, cohort_id="cohort-current"
    )
    with pytest.raises(LiveCohortValidationError, match="proof does not bind"):
        other_owner.capture_bar(
            other_owner_feeds["asset-0"], proof_event, source_role="history"
        )

    member_cohort, member_feeds = make_cohort(
        member_count=2, count=3, epoch_id=3, cohort_id="cohort-current"
    )
    other_member = _verified_saved_history_row(
        member_cohort, member_feeds["asset-1"], member_id="asset-1"
    )
    member_zero = _verified_saved_history_row(member_cohort, member_feeds["asset-0"])
    copied_proof = dict(other_member)
    copied_proof[_VERIFIED_HISTORY_PROOF_EVENT_KEY] = member_zero[
        _VERIFIED_HISTORY_PROOF_EVENT_KEY
    ]
    with pytest.raises(LiveCohortValidationError, match="proof does not bind"):
        member_cohort.capture_bar(
            member_feeds["asset-1"], copied_proof, source_role="history"
        )

    tamper_cohort, tamper_feeds = make_cohort(
        member_count=1, count=3, epoch_id=3, cohort_id="cohort-current"
    )
    tamper_event = _verified_saved_history_row(tamper_cohort, tamper_feeds["asset-0"])
    changed_byte = dict(tamper_event)
    changed_byte["source"] = "test-sourcf"
    with pytest.raises(LiveCohortValidationError, match="proof does not bind"):
        tamper_cohort.capture_bar(
            tamper_feeds["asset-0"], changed_byte, source_role="history"
        )


def test_exact_repeat_is_idempotent_but_connection_generation_change_is_not():
    cohort, feeds = make_cohort(member_count=1, count=1)
    feed = feeds["asset-0"]
    original = make_event("asset-0", 0)
    first = cohort.capture_bar(feed, original, source_role="live")
    duplicate = cohort.capture_bar(feed, dict(original), source_role="live")
    assert duplicate.duplicate is True
    assert duplicate.envelope is first.envelope

    changed_generation = dict(original)
    changed_generation["connection_generation"] = "reconnected-live"
    with pytest.raises(LiveCohortFrozenError):
        cohort.capture_bar(feed, changed_generation, source_role="live")
    assert cohort.frozen_reason == "connection_generation_changed"


def test_late_same_data_from_old_connection_generation_is_rejected():
    cohort, feeds = make_cohort(member_count=1, count=1)
    feed = feeds["asset-0"]
    original = make_event("asset-0", 0)
    cohort.capture_bar(feed, original, source_role="live")
    deliver_prepared(cohort, feeds, 20_000)

    stale_generation = dict(original)
    stale_generation["connection_generation"] = "old-live-generation"
    with pytest.raises(LiveCohortFrozenError):
        cohort.capture_bar(feed, stale_generation, source_role="live")
    assert cohort.frozen_reason == "connection_generation_changed"


def test_live_cutover_and_complete_window_are_receipt_backed():
    cohort, feeds = make_cohort(member_count=1, count=3)
    feed = feeds["asset-0"]
    capture_slot(cohort, feeds, 0, role="history")
    deliver_prepared(cohort, feeds, 20_000)
    capture_slot(cohort, feeds, 1, role="history")
    deliver_prepared(cohort, feeds, 20_001)
    assert cohort.epoch_cutover(feed) is None
    capture_slot(cohort, feeds, 2, role="live", sequences={"asset-0": 1})
    batch = deliver_prepared(cohort, feeds, 20_002)
    cutover = cohort.epoch_cutover(feed)
    assert cutover is not None
    assert cutover.cohort_id == cohort.cohort_id
    assert cutover.epoch_id == 1
    assert cutover.transition_kind == "history_to_live"
    assert cutover.crossed_live is True
    assert cutover.history_last_close_time == BASE + dt.timedelta(minutes=2)
    assert cutover.first_live_close_time == BASE + dt.timedelta(minutes=3)
    assert batch.cutovers["asset-0"].first_live_receipt is cutover.first_live_receipt
    window = cohort.complete_window_bars(feed, ("close",), 3)
    assert tuple(receipt.slot_index for receipt in window) == (0, 1, 2)
    with pytest.raises(LiveCohortCapacityError):
        cohort.complete_window_bars(feed, ("close",), 4)


def test_invalid_raw_value_freezes_before_any_envelope_can_be_prepared():
    cohort, feeds = make_cohort(member_count=1, count=1)
    event = make_event("asset-0", 0)
    event["close"] = float("nan")
    with pytest.raises(LiveCohortValidationError):
        cohort.capture_bar(feeds["asset-0"], event, source_role="live")
    assert cohort.frozen is True
    with pytest.raises(LiveCohortFrozenError):
        cohort.prepare_round(20_000, source_time_utc=BASE + dt.timedelta(minutes=2))


def _gap_event(member_id, slot_index, field_name="close"):
    event = make_event(member_id, slot_index)
    event[field_name] = float("nan")
    event.update(
        {
            "quality": "MISSING",
            "present": False,
            "missing_fields": (field_name,),
            "quality_flags": ("MISSING_FIELDS",),
        }
    )
    return event


def test_declared_nan_gap_is_sealed_delivered_and_blocks_windows_until_it_rolls_out():
    cohort, feeds = make_cohort(member_count=1, count=4)
    feed = feeds["asset-0"]

    capture_slot(cohort, feeds, 0)
    first_batch = deliver_prepared(cohort, feeds, 20_000)
    assert first_batch.receipt_for_feed(feed).present is True

    gap = _gap_event("asset-0", 1)
    captured = cohort.capture_bar(feed, gap, source_role="live")
    envelope = captured.envelope
    assert envelope.complete is True
    assert envelope.quality == "MISSING"
    assert envelope.present is False
    assert envelope.missing_fields == ("close",)
    assert envelope.quality_flags == ("MISSING_FIELDS",)
    assert math.isnan(envelope.raw_values["close"])

    result = cohort.prepare_round(20_001, source_time_utc=BASE + dt.timedelta(minutes=10))
    assert result.status == "READY"
    cohort.record_delivery(feed, envelope, delivered_close_time=envelope.close_time)
    batch = cohort.current_batch()
    receipt = batch.receipt_for_feed(feed)
    assert batch.status == "COMPLETE"
    assert receipt.envelope is envelope
    assert receipt.present is False
    assert receipt.quality == "MISSING"
    assert receipt.missing_fields == ("close",)
    assert math.isnan(receipt.raw_values["close"])
    assert cohort.complete_window_bars(feed, ("close",), 2) == ()

    capture_slot(cohort, feeds, 2)
    deliver_prepared(cohort, feeds, 20_002)
    assert cohort.complete_window_bars(feed, ("close",), 2) == ()
    capture_slot(cohort, feeds, 3)
    deliver_prepared(cohort, feeds, 20_003)
    recovered = cohort.complete_window_bars(feed, ("close",), 2)
    assert tuple(row.slot_index for row in recovered) == (2, 3)


@pytest.mark.parametrize(
    "mutate, message",
    (
        (lambda event: event.update(close=float("inf")), "must be finite"),
        (lambda event: event.update(close="nan"), "supported numeric type"),
        (
            lambda event: event.update(
                missing_fields=(), quality="GOOD", present=True, quality_flags=()
            ),
            "NaN without declared",
        ),
        (lambda event: event.update(present=True), "must explicitly declare present=False"),
        (lambda event: event.update(quality="GOOD"), "quality='MISSING'"),
        (lambda event: event.update(missing_fields=("high", "close")), "sorted and unique"),
        (lambda event: event.update(missing_fields=("openinterest",)), "only declared numeric"),
        (lambda event: event.update(close=100.0), "must contain NaN"),
        (lambda event: event.update(missing_fields=("close", "unknown")), "only declared numeric"),
        (lambda event: event.update(missing_fields=("close", "close")), "sorted and unique"),
        (lambda event: event.update(quality_flags=()), "MISSING_FIELDS"),
    ),
)
def test_declared_gap_metadata_rejects_inconsistent_raw_event(mutate, message):
    cohort, feeds = make_cohort(member_count=1, count=1)
    event = _gap_event("asset-0", 0)
    mutate(event)

    with pytest.raises(LiveCohortValidationError, match=message):
        cohort.capture_bar(feeds["asset-0"], event, source_role="live")
    assert cohort.frozen_reason == "invalid_source_bar"


@pytest.mark.parametrize("present", (0, "false", None))
def test_explicit_present_metadata_must_be_exact_bool(present):
    cohort, feeds = make_cohort(member_count=1, count=1)
    event = make_event("asset-0", 0)
    event["present"] = present

    with pytest.raises(LiveCohortValidationError, match="present must be an exact bool"):
        cohort.capture_bar(feeds["asset-0"], event, source_role="live")
    assert cohort.frozen_reason == "invalid_source_bar"


def test_gap_semantics_freeze_requires_exact_current_batch_with_real_gap_receipt():
    cohort, feeds = make_cohort(member_count=1, count=2)
    feed = feeds["asset-0"]
    capture_slot(cohort, feeds, 0)
    good_batch = deliver_prepared(cohort, feeds, 20_000)
    with pytest.raises(LiveCohortValidationError, match="missing-field receipt"):
        cohort.freeze_unsupported_gap_semantics(good_batch)
    assert cohort.frozen is False

    gap = _gap_event("asset-0", 1)
    envelope = cohort.capture_bar(feed, gap, source_role="live").envelope
    cohort.prepare_round(20_001, source_time_utc=BASE + dt.timedelta(minutes=10))
    cohort.record_delivery(feed, envelope, delivered_close_time=envelope.close_time)
    gap_batch = cohort.current_batch()
    assert gap_batch is not good_batch
    with pytest.raises(LiveCohortValidationError, match="exact current cohort batch"):
        cohort.freeze_unsupported_gap_semantics(good_batch)
    assert cohort.freeze_unsupported_gap_semantics(gap_batch) == "unsupported_factor_gap_semantics"
    assert cohort.frozen is True


@pytest.mark.parametrize(
    "invalid_number", ["100.5", type("FloatLike", (), {"__float__": lambda self: 100.5})()]
)
def test_numeric_fields_reject_coercible_non_numeric_types(invalid_number):
    cohort, feeds = make_cohort(member_count=1, count=1)
    event = make_event("asset-0", 0)
    event["open"] = invalid_number
    with pytest.raises(LiveCohortValidationError, match="supported numeric type"):
        cohort.capture_bar(feeds["asset-0"], event, source_role="live")
    assert cohort.frozen_reason == "invalid_source_bar"


def test_explicit_decimal_is_an_accepted_numeric_input_type():
    cohort, feeds = make_cohort(member_count=1, count=1)
    event = make_event("asset-0", 0)
    event["open"] = Decimal("99.5")
    captured = cohort.capture_bar(feeds["asset-0"], event, source_role="live")
    assert captured.envelope.raw_values["open"] == 99.5


def test_partial_line_delivery_does_not_publish_or_consume_prepared_batch():
    cohort, feeds = make_cohort(member_count=2, count=2, wait_timeout_ns=10)
    capture_slot(cohort, feeds, 0)
    result = cohort.prepare_round(100, source_time_utc=BASE + dt.timedelta(minutes=2))
    assert result.status == "READY"
    prepared = result.prepared
    first_id, first_feed = next(iter(feeds.items()))
    first = prepared.envelopes[first_id]
    cohort.record_delivery(first_feed, first, delivered_close_time=first.close_time)
    assert cohort.current_batch() is None
    assert (
        cohort.prepare_round(101, source_time_utc=BASE + dt.timedelta(minutes=2)).prepared
        is prepared
    )
    with pytest.raises(LiveCohortValidationError):
        cohort.record_delivery(first_feed, first, delivered_close_time=first.close_time)


def test_gap_is_detected_before_any_line_delivery_when_a_member_is_missing():
    cohort, feeds = make_cohort(member_count=2, count=2, wait_timeout_ns=10)
    member_id, feed = next(iter(feeds.items()))
    cohort.capture_bar(feed, make_event(member_id, 0), source_role="live")
    assert (
        cohort.prepare_round(100, source_time_utc=BASE + dt.timedelta(minutes=2)).status
        == "WAITING"
    )
    result = cohort.prepare_round(110, source_time_utc=BASE + dt.timedelta(minutes=2))
    assert result.status == "GAP"
    assert result.missing_member_ids == (list(feeds)[1],)
    assert cohort.gaps[0].slot_index == 0
    assert cohort.gaps[0].close_time == BASE + dt.timedelta(minutes=1)
    assert cohort.frozen_reason == "planned_gap_requires_rebuild"
    with pytest.raises(LiveCohortFrozenError):
        cohort.prepare_round(111, source_time_utc=BASE + dt.timedelta(minutes=2))


def test_member_arriving_after_monotonic_gap_deadline_cannot_rescue_the_slot():
    cohort, feeds = make_cohort(member_count=2, count=1, wait_timeout_ns=10)
    first_id, first_feed = next(iter(feeds.items()))
    cohort.capture_bar(first_feed, make_event(first_id, 0), source_role="live")
    assert (
        cohort.prepare_round(100, source_time_utc=BASE + dt.timedelta(minutes=1)).status
        == "WAITING"
    )

    second_id, second_feed = list(feeds.items())[1]
    cohort.capture_bar(second_feed, make_event(second_id, 0), source_role="live")
    result = cohort.prepare_round(110, source_time_utc=BASE + dt.timedelta(minutes=1, seconds=2))
    assert result.status == "GAP"
    assert result.missing_member_ids == (second_id,)
    assert cohort.current_batch() is None
    assert cohort.frozen_reason == "planned_gap_requires_rebuild"


def test_arrived_member_waiting_for_causal_availability_does_not_become_a_gap():
    cohort, feeds = make_cohort(member_count=2, count=1, wait_timeout_ns=10)
    first_id, first_feed = next(iter(feeds.items()))
    close_time = BASE + dt.timedelta(minutes=1)
    first_capture = cohort.capture_bar(first_feed, make_event(first_id, 0), source_role="live")
    assert not first_capture.duplicate
    first_wait = cohort.prepare_round(100, source_time_utc=close_time)
    assert first_wait.status == "WAITING"
    assert first_wait.missing_member_ids == (list(feeds)[1],)

    second_id, second_feed = list(feeds.items())[1]
    future_event = make_event(second_id, 0)
    future_event["available_at"] = close_time + dt.timedelta(seconds=2)
    cohort.capture_bar(second_feed, future_event, source_role="live")

    result = cohort.prepare_round(110, source_time_utc=close_time + dt.timedelta(seconds=1))
    assert result.status == "AVAILABILITY_TIMEOUT"
    assert result.reason == "bar_availability_deadline_exceeded"
    assert result.missing_member_ids == ()
    assert cohort.gaps == ()
    assert cohort.frozen_reason == "bar_availability_deadline_exceeded"


def test_conflicting_duplicate_and_late_rewrite_freeze_without_replacing_rows():
    cohort, feeds = make_cohort(member_count=1, count=2)
    feed = feeds["asset-0"]
    original = make_event("asset-0", 0)
    cohort.capture_bar(feed, original, source_role="live")
    conflict = dict(original)
    conflict["close"] += 1
    conflict["high"] += 1
    with pytest.raises(LiveCohortFrozenError):
        cohort.capture_bar(feed, conflict, source_role="live")
    assert cohort.frozen_reason == "conflicting_duplicate_bar"

    cohort2, feeds2 = make_cohort(member_count=1, count=2)
    feed2 = feeds2["asset-0"]
    capture_slot(cohort2, feeds2, 0)
    deliver_prepared(cohort2, feeds2, 20_000)
    late = make_event("asset-0", 0, sequence=99, close=123.0)
    late["high"] = 124.0
    with pytest.raises(LiveCohortFrozenError):
        cohort2.capture_bar(feed2, late, source_role="live")
    assert cohort2.frozen_reason == "late_bar_after_seal"


def test_pending_source_window_is_bounded():
    cohort, feeds = make_cohort(member_count=1, count=4, max_pending_slots=1)
    feed = feeds["asset-0"]
    with pytest.raises(LiveCohortCapacityError):
        cohort.capture_bar(feed, make_event("asset-0", 2), source_role="live")
    assert cohort.frozen_reason == "pending_slot_window_exceeded"


def test_preclose_poll_does_not_start_or_spend_missing_member_timeout():
    cohort, feeds = make_cohort(member_count=2, count=1, wait_timeout_ns=10)
    first_id, first_feed = next(iter(feeds.items()))
    cohort.capture_bar(first_feed, make_event(first_id, 0), source_role="live")

    before_close = cohort.prepare_round(100, source_time_utc=BASE + dt.timedelta(seconds=30))
    assert before_close.status == "NOT_DUE"
    assert before_close.reason == "planned_slot_not_closed"
    assert cohort.gaps == ()

    due = cohort.prepare_round(200, source_time_utc=BASE + dt.timedelta(minutes=1))
    assert due.status == "WAITING"
    assert cohort.gaps == ()
    assert (
        cohort.prepare_round(209, source_time_utc=BASE + dt.timedelta(minutes=1)).status
        == "WAITING"
    )
    timed_out = cohort.prepare_round(210, source_time_utc=BASE + dt.timedelta(minutes=1))
    assert timed_out.status == "GAP"
    assert timed_out.missing_member_ids == (list(feeds)[1],)


def test_future_available_at_waits_causally_without_becoming_a_gap():
    cohort, feeds = make_cohort(member_count=1, count=1, wait_timeout_ns=100)
    capture_slot(cohort, feeds, 0)

    before_available = cohort.prepare_round(100, source_time_utc=BASE + dt.timedelta(minutes=1))
    assert before_available.status == "WAITING_AVAILABILITY"
    assert before_available.reason == "bar_not_yet_available"
    assert cohort.current_batch() is None
    assert cohort.gaps == ()

    available = cohort.prepare_round(102, source_time_utc=BASE + dt.timedelta(minutes=1, seconds=2))
    assert available.status == "READY"
    assert available.prepared.envelopes["asset-0"].available_at == BASE + dt.timedelta(
        minutes=1, seconds=2
    )


def test_future_availability_timeout_freezes_without_inventing_a_market_gap():
    cohort, feeds = make_cohort(member_count=1, count=1, wait_timeout_ns=10)
    capture_slot(cohort, feeds, 0)
    assert (
        cohort.prepare_round(100, source_time_utc=BASE + dt.timedelta(minutes=1)).status
        == "WAITING_AVAILABILITY"
    )

    result = cohort.prepare_round(110, source_time_utc=BASE + dt.timedelta(minutes=1, seconds=1))
    assert result.status == "AVAILABILITY_TIMEOUT"
    assert cohort.gaps == ()
    assert cohort.frozen_reason == "bar_availability_deadline_exceeded"


def test_normal_calendar_break_does_not_start_missing_member_timeout_early():
    slots = (
        LiveCalendarSlot(
            slot_id="morning",
            bucket_start=BASE,
            close_time=BASE + dt.timedelta(minutes=1),
            trading_day="2026-10-20",
            session_segment="regular",
        ),
        LiveCalendarSlot(
            slot_id="afternoon",
            bucket_start=BASE + dt.timedelta(hours=1),
            close_time=BASE + dt.timedelta(hours=1, minutes=1),
            trading_day="2026-10-20",
            session_segment="regular",
        ),
    )
    calendar = LiveCohortCalendar(
        calendar_id="XNYS-1m",
        version="v-break",
        epoch_id=1,
        frequency="1m",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="source-clock-A",
        session_semantics="XNYS-regular-v1",
        slots=slots,
    )
    cohort = LiveBarCohort(
        "cohort-A", calendar, max_pending_slots=2, max_window_bars=2, wait_timeout_ns=10
    )
    feed = object()
    cohort.register_member(
        "asset-0",
        feed,
        instrument="SYM0",
        source_ref="provider-feed-0",
        line_fields=LINE_FIELDS,
        raw_fields=RAW_FIELDS,
    )
    cohort.seal()
    cohort.capture_bar(feed, make_event("asset-0", 0), source_role="live")
    deliver_prepared(cohort, {"asset-0": feed}, 20_000)

    break_poll = cohort.prepare_round(30_000, source_time_utc=BASE + dt.timedelta(minutes=30))
    assert break_poll.status == "NOT_DUE"
    assert cohort.gaps == ()

    next_session_due = cohort.prepare_round(
        30_100, source_time_utc=BASE + dt.timedelta(hours=1, minutes=1)
    )
    assert next_session_due.status == "WAITING"
    assert cohort.gaps == ()
    timed_out = cohort.prepare_round(
        30_110, source_time_utc=BASE + dt.timedelta(hours=1, minutes=1)
    )
    assert timed_out.status == "GAP"
    assert timed_out.missing_member_ids == ("asset-0",)


def test_finite_calendar_exhaustion_stops_without_in_place_epoch_rollover():
    first_calendar = make_calendar(count=1)
    cohort = LiveBarCohort("cohort-A", first_calendar, max_window_bars=4)
    feed = object()
    cohort.register_member(
        "asset-0",
        feed,
        instrument="SYM0",
        source_ref="provider-feed-0",
        line_fields=LINE_FIELDS,
        raw_fields=RAW_FIELDS,
    )
    cohort.seal()
    cohort.capture_bar(feed, make_event("asset-0", 0), source_role="live")
    batch = deliver_prepared(cohort, {"asset-0": feed}, 20_000)
    assert batch.epoch_id == 1
    result = cohort.prepare_round(20_001, source_time_utc=BASE + dt.timedelta(minutes=2))
    assert result.status == "EXHAUSTED"
    assert cohort.epoch_id == 1
    assert not hasattr(cohort, "append_next_epoch")


def test_naive_source_times_and_missing_raw_fields_are_rejected():
    cohort, feeds = make_cohort(member_count=1, count=1)
    feed = feeds["asset-0"]
    event = make_event("asset-0", 0)
    event["available_at"] = event["available_at"].replace(tzinfo=None)
    with pytest.raises(LiveCohortValidationError):
        cohort.capture_bar(feed, event, source_role="live")

    cohort2, feeds2 = make_cohort(member_count=1, count=1)
    event2 = make_event("asset-0", 0)
    del event2["close"]
    with pytest.raises(LiveCohortValidationError):
        cohort2.capture_bar(feeds2["asset-0"], event2, source_role="live")


def test_first_incomplete_live_bucket_is_rejected_with_fixed_code():
    cohort, feeds = make_cohort(member_count=1, count=2)
    event = make_event("asset-0", 0)
    event["complete"] = False
    with pytest.raises(LiveFirstBucketIncomplete) as excinfo:
        cohort.capture_bar(feeds["asset-0"], event, source_role="live")
    assert excinfo.value.code == "LIVE_FIRST_BUCKET_INCOMPLETE"
    assert cohort.frozen is True


def test_cold_start_partial_bucket_is_skipped_as_bounded_gap_and_run_continues():
    cohort, feeds = make_cohort(member_count=2, count=3)

    assert (
        cohort.note_cold_start_skipped_slot(BASE + dt.timedelta(minutes=1)) is True
    )
    # The next complete planned bucket is captured normally.
    capture_slot(cohort, feeds, 1)

    skipped = cohort.prepare_round(20_000, source_time_utc=BASE + dt.timedelta(minutes=2))
    assert skipped.status == "WAITING"
    assert skipped.reason == "first_partial_bucket_skipped"
    assert len(cohort.gaps) == 1
    gap = cohort.gaps[0]
    assert gap.reason == "first_partial_bucket_skipped"
    assert gap.slot_index == 0
    assert gap.slot_id == "slot-0"
    assert gap.missing_member_ids == ("asset-0", "asset-1")

    ready = cohort.prepare_round(20_001, source_time_utc=BASE + dt.timedelta(minutes=3))
    assert ready.status == "READY"
    assert ready.prepared.slot_index == 1
    assert set(ready.prepared.envelopes) == {"asset-0", "asset-1"}


def test_cold_start_notice_is_bounded_to_the_first_planned_slot():
    cohort, feeds = make_cohort(member_count=1, count=3)
    assert cohort.note_cold_start_skipped_slot(BASE + dt.timedelta(minutes=2)) is False
    assert cohort.gaps == ()
    # A later incomplete bucket keeps the ordinary validation error.
    capture_slot(cohort, feeds, 0)
    deliver_prepared(cohort, feeds, 20_000)
    event = make_event("asset-0", 1)
    event["complete"] = False
    with pytest.raises(LiveCohortValidationError) as excinfo:
        cohort.capture_bar(feeds["asset-0"], event, source_role="live")
    assert not isinstance(excinfo.value, LiveFirstBucketIncomplete)
    assert str(excinfo.value) == "bar must explicitly declare complete=True"
