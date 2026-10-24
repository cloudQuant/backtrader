"""Focused contracts for bounded live bar cohort validation and delivery."""

import datetime as dt
from decimal import Decimal

import pytest

from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveCohortCapacityError,
    LiveCohortFrozenError,
    LiveCohortValidationError,
    LiveInputBinding,
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


def make_cohort(member_count=2, *, count=3, wait_timeout_ns=100, max_pending_slots=None):
    cohort = LiveBarCohort(
        "cohort-A",
        make_calendar(count),
        max_pending_slots=max(count, 1) if max_pending_slots is None else max_pending_slots,
        max_window_bars=min(max(count, 1), 16),
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


def make_event(member_id, slot_index, *, source_role="live", sequence=None, close=None):
    start = BASE + dt.timedelta(minutes=slot_index)
    end = start + dt.timedelta(minutes=1)
    close_value = float(100 + slot_index if close is None else close)
    return {
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
