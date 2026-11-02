"""Backtrader Feed staging and dispatch for complete live bar cohorts.

SDK/provider components own upstream market data; this mixin owns only
framework cohort, Feed line and Cerebro delivery bindings.
"""
from __future__ import annotations

import collections
import copy
import datetime as _dt
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..channel import EventPriority
from ..utils import date2num

_UTC = _dt.timezone.utc
_COHORT_MISSING = object()
_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_LIVE_COHORT_EXTRA_LINES = (
    "vwap",
    "cap",
    "sector",
    "industry",
    "subindustry",
    "dollar_volume",
)


@dataclass(frozen=True)
class _PreparedLiveBarCohortActivation:
    """Validated, side-effect-free feed state staged by Cerebro."""

    feed_ref: object
    cohort: object
    clock: object
    history_iter: object
    live_iter: object
    slot_index_by_close: object
    stream_health_baseline: object


@dataclass(frozen=True)
class _PreparedLiveBarCohortDelivery:
    """Read-only, validated values staged before any batch member advances."""

    feed_ref: object
    envelope: object
    raw_values: object
    close_time: object
    datetime_value: float


def _raw_tick_field(tick, names):
    """Read the first explicitly present raw tick alias without normalizing it."""
    first_null = None
    for name in names:
        if isinstance(tick, Mapping):
            if name in tick:
                value = tick[name]
                if value is not None:
                    return name, value, True
                if first_null is None:
                    first_null = (name, value)
            continue
        value = getattr(tick, name, _COHORT_MISSING)
        if value is not _COHORT_MISSING:
            if value is not None:
                return name, value, True
            if first_null is None:
                first_null = (name, value)
    if first_null is not None:
        return first_null[0], first_null[1], True
    return names[0], _COHORT_MISSING, False


def _tick_value(tick, *names, default=None):
    if isinstance(tick, Mapping):
        for name in names:
            if name in tick and tick[name] is not None:
                return tick[name]
        return default

    for name in names:
        value = getattr(tick, name, None)
        if value is not None:
            return value
    return default


class LiveBarCohortFeedMixin:
    """Stage and deliver exact cohort members to Backtrader lines."""

    def _prepare_live_bar_cohort_activation(self, cohort, clock):
        """Validate and stage cohort state without changing this feed."""
        if self.p.cohort_source_mode is not True:
            raise ValueError("live cohort requires cohort_source_mode=True")
        if self.p.backfill_start:
            raise ValueError("live cohort raw source mode requires backfill_start=False")
        self._validate_cohort_store_raw_mode(self.store)
        if self._live_bar_cohort is not None:
            raise ValueError("BtApiFeed is already bound to a live bar cohort")
        member = cohort.member_for_feed(self)
        if member is None or member.feed_ref is not self:
            raise ValueError("live bar cohort does not own this exact BtApiFeed")
        if self.p.cohort_source_origin is not member.source_origin:
            raise ValueError("feed and cohort do not share the exact source-origin declaration")
        feed_lines = set(self.getlinealiases())
        unsupported_lines = tuple(name for name in member.line_fields if name not in feed_lines)
        if unsupported_lines:
            raise ValueError(
                "live cohort member declares unsupported BtApiFeed line fields: {!r}".format(
                    unsupported_lines
                )
            )
        if self._cohort_history_source is None or self._cohort_live_source is None:
            raise ValueError(
                "live cohort explicit bar sources must be replayable tuple/list values"
            )
        if (
            type(self._cohort_history_source) is not tuple
            or type(self._cohort_live_source) is not tuple
        ):
            raise ValueError("live cohort explicit bar sources must use immutable tuples")
        if any(
            type(event) is not _MAPPING_PROXY_TYPE
            for source in (self._cohort_history_source, self._cohort_live_source)
            for event in source
        ):
            raise ValueError(
                "live cohort saved bar events must be immutable MappingProxyType mappings"
            )
        calendar_slots = cohort._calendar.slots
        if len(self._cohort_history_source) + len(self._cohort_live_source) > (
            len(calendar_slots) + cohort.max_pending_slots
        ):
            raise ValueError("live cohort saved source exceeds the finite calendar bound")
        # Creating iterators is side-effect-free.  Cerebro stages every exact
        # member before asking any feed to publish this state or clear its
        # legacy, provenance-free queues.
        return _PreparedLiveBarCohortActivation(
            feed_ref=self,
            cohort=cohort,
            clock=clock,
            history_iter=iter(self._cohort_history_source),
            live_iter=iter(self._cohort_live_source),
            # Cohort owns this immutable-after-construction lookup. Reuse it
            # rather than building another calendar-sized dictionary/feed.
            slot_index_by_close=cohort._slot_indices_by_close,
            stream_health_baseline=self._read_cohort_stream_health(),
        )

    def _read_cohort_stream_health(self):
        """Read the optional exact Store health counters used by cohort feeds."""
        store = self.store
        reader = getattr(store, "get_stream_health", None) if store is not None else None
        if not callable(reader):
            # Direct tuple-based synthetic sources do not need a Store health API.
            return None
        health = reader(self._dataname)
        if not isinstance(health, Mapping):
            raise ValueError("cohort Store stream health must be a mapping")
        generation = health.get("stream_generation", _COHORT_MISSING)
        if generation is not _COHORT_MISSING and (type(generation) is not int or generation < 0):
            raise ValueError("cohort Store stream generation is invalid")
        overflow_count = health.get("tick_queue_overflow_count", _COHORT_MISSING)
        if overflow_count is not _COHORT_MISSING and (
            type(overflow_count) is not int or overflow_count < 0
        ):
            raise ValueError("cohort Store tick overflow count is invalid")
        live_bar_overflow_count = health.get("live_bar_queue_overflow_count", _COHORT_MISSING)
        if live_bar_overflow_count is not _COHORT_MISSING and (
            type(live_bar_overflow_count) is not int or live_bar_overflow_count < 0
        ):
            raise ValueError("cohort Store live-bar overflow count is invalid")
        if (
            overflow_count is not _COHORT_MISSING or live_bar_overflow_count is not _COHORT_MISSING
        ) and generation is _COHORT_MISSING:
            raise ValueError("cohort Store health omits its stream generation")
        if overflow_count is _COHORT_MISSING and callable(getattr(store, "poll_tick", None)):
            raise ValueError("cohort Store health omits its tick queue overflow count")
        if live_bar_overflow_count is _COHORT_MISSING and callable(
            getattr(store, "poll_live", None)
        ):
            raise ValueError("cohort Store health omits its live-bar queue overflow count")
        stale = health.get("stale", False)
        if type(stale) is not bool:
            raise ValueError("cohort Store stale state must be an exact boolean")
        return (
            None if generation is _COHORT_MISSING else generation,
            None if overflow_count is _COHORT_MISSING else overflow_count,
            None if live_bar_overflow_count is _COHORT_MISSING else live_bar_overflow_count,
            stale,
        )

    def _freeze_cohort_source_state(self, reason):
        """Freeze this epoch without replacing the active source exception."""
        cohort = self._live_bar_cohort
        if cohort is not None:
            cohort._freeze(reason)
            self._cohort_delivery_failed = True

    def _freeze_cohort_source(self, reason, message):
        """Freeze this epoch before an unsafe source event can be captured."""
        self._freeze_cohort_source_state(reason)
        from ..research.live_cohort import LiveCohortFrozenError

        raise LiveCohortFrozenError(message)

    def _check_cohort_stream_health(self):
        """Reject Store drops, restarts, or stale state within this cohort epoch."""
        cohort = self._live_bar_cohort
        if cohort is None:
            return
        baseline = self._cohort_stream_health_baseline
        if baseline is None:
            return
        try:
            current = self._read_cohort_stream_health()
        except Exception:
            self._freeze_cohort_source(
                "store_stream_health_invalid", "cohort Store stream health became invalid"
            )
        if current is None:
            self._freeze_cohort_source(
                "store_stream_health_unavailable",
                "cohort Store stream health became unavailable",
            )
        if current[0] != baseline[0]:
            self._freeze_cohort_source(
                "store_stream_generation_changed",
                "cohort Store stream generation changed",
            )
        if current[1] != baseline[1]:
            reason = (
                "store_tick_queue_overflow"
                if (
                    isinstance(current[1], int)
                    and not isinstance(current[1], bool)
                    and isinstance(baseline[1], int)
                    and not isinstance(baseline[1], bool)
                    and current[1] > baseline[1]
                )
                else "store_tick_overflow_counter_reset"
            )
            self._freeze_cohort_source(reason, "cohort Store tick queue continuity changed")
        if current[2] != baseline[2]:
            reason = (
                "store_live_bar_queue_overflow"
                if (
                    isinstance(current[2], int)
                    and not isinstance(current[2], bool)
                    and isinstance(baseline[2], int)
                    and not isinstance(baseline[2], bool)
                    and current[2] > baseline[2]
                )
                else "store_live_bar_overflow_counter_reset"
            )
            self._freeze_cohort_source(reason, "cohort Store live-bar queue continuity changed")
        if current[3]:
            self._freeze_cohort_source(
                "store_stream_stale", "stale Store stream cannot feed a live cohort"
            )

    def _validate_cohort_source_continuity(self, event):
        """Reject an explicitly stale or non-continuous source bar before capture."""
        _field_name, stale, stale_present = _raw_tick_field(event, ("stale",))
        if stale_present:
            if type(stale) is not bool:
                self._freeze_cohort_source(
                    "invalid_source_stale_marker", "cohort source stale marker is invalid"
                )
            if stale:
                self._freeze_cohort_source(
                    "stale_source_bar", "stale source bar cannot enter a live cohort"
                )
        _field_name, continuity, continuity_present = _raw_tick_field(
            event, ("continuity_status", "continuity")
        )
        if continuity_present and continuity is not None:
            if type(continuity) is not str:
                self._freeze_cohort_source(
                    "invalid_source_continuity", "cohort source continuity status is invalid"
                )
            if continuity.lower() in {
                "gap",
                "stale",
                "disconnected",
                "checksum_failed",
                "out_of_order",
                "invalid",
            }:
                self._freeze_cohort_source(
                    "non_continuous_source_bar",
                    "non-continuous source bar cannot enter a live cohort",
                )

    @staticmethod
    def _validate_cohort_store_raw_mode(store):
        """Require Store bars to remain raw until cohort capture."""
        if store is None or not callable(getattr(store, "poll_live", None)):
            return
        if getattr(store, "preserve_raw_bars", None) is not True:
            raise ValueError("live cohort Store polling requires preserve_raw_bars=True")

    def _live_bar_cohort_activation_snapshot(self):
        """Capture mutable feed state so Cerebro can roll back a failed commit."""
        return (
            self._live_bar_cohort,
            self._cohort_clock,
            self._cohort_history_iter,
            self._cohort_live_iter,
            self._cohort_history_exhausted,
            self._cohort_live_exhausted,
            self._cohort_history_lookahead,
            self._cohort_live_lookahead,
            self._cohort_store_lookahead,
            self._cohort_completed_lookahead,
            self._cohort_slot_index_by_close,
            self._cohort_last_delivered_slot_index,
            self._cohort_armed_envelope,
            self._cohort_staged_delivery,
            self._cohort_delivery_failed,
            self._cohort_stream_health_baseline,
            self._history,
            self._live,
        )

    def _commit_live_bar_cohort_activation(self, prepared):
        """Publish previously validated state; Cerebro calls this in phase two."""
        self._live_bar_cohort = prepared.cohort
        self._cohort_clock = prepared.clock
        self._cohort_history_iter = prepared.history_iter
        self._cohort_live_iter = prepared.live_iter
        self._cohort_slot_index_by_close = prepared.slot_index_by_close
        self._cohort_stream_health_baseline = prepared.stream_health_baseline
        # Swap in empty queues only after every feed was validated. Keeping the
        # prior deque objects in Cerebro's rollback snapshot avoids copying up
        # to a full finite history merely to make activation reversible.
        self._history = collections.deque()
        self._live = collections.deque()

    def _restore_live_bar_cohort_activation(self, snapshot):
        """Restore the exact pre-activation feed state after a commit failure."""
        (
            self._live_bar_cohort,
            self._cohort_clock,
            self._cohort_history_iter,
            self._cohort_live_iter,
            self._cohort_history_exhausted,
            self._cohort_live_exhausted,
            self._cohort_history_lookahead,
            self._cohort_live_lookahead,
            self._cohort_store_lookahead,
            self._cohort_completed_lookahead,
            self._cohort_slot_index_by_close,
            self._cohort_last_delivered_slot_index,
            self._cohort_armed_envelope,
            self._cohort_staged_delivery,
            self._cohort_delivery_failed,
            self._cohort_stream_health_baseline,
            self._history,
            self._live,
        ) = snapshot

    def _cohort_source_is_exhausted(self):
        """Report EOF only for finite sources with an explicit end contract."""
        if self._live_bar_cohort is None:
            return False
        if not self._cohort_history_exhausted or not self._cohort_live_exhausted:
            return False
        if self._cohort_history_lookahead is not _COHORT_MISSING:
            return False
        if self._cohort_live_lookahead is not _COHORT_MISSING:
            return False
        if self._cohort_store_lookahead is not _COHORT_MISSING:
            return False
        if self._cohort_completed_lookahead is not _COHORT_MISSING:
            return False
        if self._bar_builders:
            return False

        store = self.store
        if store is None:
            return True
        source_exhausted = getattr(store, "is_source_exhausted", None)
        if callable(source_exhausted):
            try:
                return bool(source_exhausted(self._dataname))
            except TypeError:
                return bool(source_exhausted())
        # A store with a polling API is live unless it explicitly declares
        # exhaustion.  A store used only for startup/backfill is finite.
        return not any(
            callable(getattr(store, name, None))
            for name in ("poll_live", "poll_tick", "poll_orderbook")
        )

    def _cohort_event_slot_index(self, event):
        close_time = _tick_value(event, "bucket_end", default=None)
        if not isinstance(close_time, _dt.datetime):
            return None
        if close_time.tzinfo is None or close_time.utcoffset() is None:
            return None
        return self._cohort_slot_index_by_close.get(close_time.astimezone(_UTC))

    def _cohort_max_collect_slot(self):
        next_slot = self._cohort_last_delivered_slot_index + 1
        return next_slot + self._live_bar_cohort.max_pending_slots - 1

    def _cohort_capture_source(self, event, source_role, received_monotonic_ns, max_slot):
        self._check_cohort_stream_health()
        self._validate_cohort_source_continuity(event)
        slot_index = self._cohort_event_slot_index(event)
        if slot_index is not None and slot_index > max_slot:
            return False
        if (
            source_role == "live"
            and slot_index == 0
            and _tick_value(event, "complete", default=None) is not True
        ):
            # A cold start observed only the tail of its first planned bucket.
            # Reject that one bucket explicitly and continue with the next
            # complete bucket; never promote the partial bar.
            close = _tick_value(event, "bucket_end", default=None)
            if isinstance(close, _dt.datetime) and self._live_bar_cohort.note_cold_start_skipped_slot(
                close
            ):
                return False
        self._live_bar_cohort.capture_bar(
            self,
            event,
            source_role=source_role,
            received_monotonic_ns=received_monotonic_ns,
        )
        return True

    def _cohort_prepare_deadline_expired(self, deadline_ns):
        if deadline_ns is None:
            return False
        clock = self._cohort_clock
        monotonic_ns = getattr(clock, "monotonic_ns", None)
        if not callable(monotonic_ns):
            raise RuntimeError("live cohort feed has no monotonic clock")
        now_ns = monotonic_ns()
        if type(now_ns) is not int or now_ns <= 0:
            raise ValueError("live cohort clock returned an invalid monotonic sample")
        return now_ns >= deadline_ns

    def _cohort_next_source_item(self, role):
        if role == "history":
            lookahead_name = "_cohort_history_lookahead"
            iterator_name = "_cohort_history_iter"
            exhausted_name = "_cohort_history_exhausted"
        else:
            lookahead_name = "_cohort_live_lookahead"
            iterator_name = "_cohort_live_iter"
            exhausted_name = "_cohort_live_exhausted"
        lookahead = getattr(self, lookahead_name)
        if lookahead is not _COHORT_MISSING:
            setattr(self, lookahead_name, _COHORT_MISSING)
            return lookahead
        if getattr(self, exhausted_name):
            return _COHORT_MISSING
        try:
            return next(getattr(self, iterator_name))
        except StopIteration:
            setattr(self, exhausted_name, True)
            return _COHORT_MISSING

    def _cohort_collect_source(self, now_monotonic_ns, *, deadline_ns=None):
        """Capture a bounded prefix without advancing lines.

        The deadline is cooperative: one provider poll/normalization call cannot
        be preempted, but consumed events finish validation/capture before this
        method yields so they are never silently dropped.
        """
        cohort = self._live_bar_cohort
        if cohort is None:
            return 0
        if self._cohort_delivery_failed or cohort.frozen:
            return 0
        self._check_cohort_stream_health()

        max_slot = self._cohort_max_collect_slot()
        budget = cohort.max_pending_slots
        collected = 0

        # Preserve history-before-live ordering so overlap deduplication can
        # only move from history to live, never back across the cutover.
        for source_role in ("history", "live"):
            while collected < budget:
                if self._cohort_prepare_deadline_expired(deadline_ns):
                    return collected
                event = self._cohort_next_source_item(source_role)
                if event is _COHORT_MISSING:
                    break
                expired_after_read = self._cohort_prepare_deadline_expired(deadline_ns)
                slot_index = self._cohort_event_slot_index(event)
                if slot_index is not None and slot_index > max_slot:
                    lookahead_name = (
                        "_cohort_history_lookahead"
                        if source_role == "history"
                        else "_cohort_live_lookahead"
                    )
                    setattr(self, lookahead_name, event)
                    if expired_after_read:
                        return collected
                    break
                self._cohort_capture_source(event, source_role, now_monotonic_ns, max_slot)
                collected += 1
                if expired_after_read or self._cohort_prepare_deadline_expired(deadline_ns):
                    return collected
            if collected >= budget:
                return collected
            if source_role == "history" and not self._cohort_history_exhausted:
                # Do not let live ticks overtake historical prewarm rows.
                return collected

        # Aggregated bar events are captured in _enqueue_bar_event. Keep that
        # queue bounded to one lookahead when the calendar window is full.
        if self._cohort_completed_lookahead is not _COHORT_MISSING:
            if self._cohort_prepare_deadline_expired(deadline_ns):
                return collected
            event = self._cohort_completed_lookahead
            slot_index = self._cohort_event_slot_index(event)
            if slot_index is not None and slot_index > max_slot:
                return collected
            self._cohort_completed_lookahead = _COHORT_MISSING
            self._cohort_capture_source(event, "live", now_monotonic_ns, max_slot)
            collected += 1
            if self._cohort_prepare_deadline_expired(deadline_ns):
                return collected

        if collected >= budget:
            return collected

        # Drain a fixed amount per engine round. Feed._check remains a strict
        # no-consumption path, and no per-feed sleep occurs here.
        drained = self._drain_live_ticks(limit=64, deadline_ns=deadline_ns)
        expired_after_ticks = self._cohort_prepare_deadline_expired(deadline_ns)
        if not expired_after_ticks:
            self._drain_live_orderbooks(limit=64, deadline_ns=deadline_ns)
        if not self._cohort_prepare_deadline_expired(deadline_ns):
            self._flush_ready_bars(reason="cohort")
        if len(self._bar_builders) > cohort.max_pending_slots:
            cohort._freeze("feed_bar_builder_capacity_exceeded")
            self._cohort_delivery_failed = True
            raise RuntimeError("BtApiFeed cohort bar-builder capacity exceeded")
        if self._bar_builders and not self._cohort_prepare_deadline_expired(deadline_ns):
            self._handle_source_exhaustion()
        if drained:
            self._mark_live()
        if self._cohort_completed_lookahead is not _COHORT_MISSING:
            # Tick aggregation can finish a bar during this collection pass.
            # Capture that exact event now, before the engine starts a shared
            # missing-member wait; otherwise the next pass may arrive only at
            # the deadline and lose to the cohort's timeout check. Preserve
            # the same collection budget and calendar lookahead bound used by
            # the source queues above.
            event = self._cohort_completed_lookahead
            slot_index = self._cohort_event_slot_index(event)
            if slot_index is not None and slot_index > max_slot:
                return collected
            self._cohort_completed_lookahead = _COHORT_MISSING
            self._cohort_capture_source(event, "live", now_monotonic_ns, max_slot)
            collected += 1
        if collected >= budget or self._cohort_prepare_deadline_expired(deadline_ns):
            return collected

        # Direct completed-bar sources retain their original event schema.
        while collected < budget and self.store is not None:
            if self._cohort_prepare_deadline_expired(deadline_ns):
                return collected
            if self._cohort_store_lookahead is not _COHORT_MISSING:
                event = self._cohort_store_lookahead
                self._cohort_store_lookahead = _COHORT_MISSING
            else:
                poll_live = getattr(self.store, "poll_live", None)
                if not callable(poll_live):
                    break
                event = poll_live(self._dataname)
                self._check_cohort_stream_health()
            if event is None:
                break
            expired_after_poll = self._cohort_prepare_deadline_expired(deadline_ns)
            slot_index = self._cohort_event_slot_index(event)
            if slot_index is not None and slot_index > max_slot:
                self._cohort_store_lookahead = event
                if expired_after_poll:
                    return collected
                break
            self._cohort_capture_source(event, "live", now_monotonic_ns, max_slot)
            collected += 1
            self._mark_live()
            if expired_after_poll or self._cohort_prepare_deadline_expired(deadline_ns):
                return collected
        return collected

    def _prepare_live_bar_cohort_delivery(self, envelope):
        """Preflight one exact envelope without mutating feed or line state."""
        cohort = self._live_bar_cohort
        if cohort is None or self._cohort_delivery_failed:
            raise RuntimeError("BtApiFeed is not ready for cohort delivery")
        if cohort.prepared_envelope(self) is not envelope:
            raise ValueError("Cerebro supplied a non-prepared cohort envelope")
        raw_values = cohort.preflight_delivery(self, envelope)
        close_time = envelope.close_time
        datetime_value = date2num(close_time.replace(tzinfo=None))
        return _PreparedLiveBarCohortDelivery(
            feed_ref=self,
            envelope=envelope,
            raw_values=raw_values,
            close_time=close_time,
            datetime_value=datetime_value,
        )

    def _arm_live_bar_cohort_envelope(self, envelope, prepared):
        """Bind an exact preflight result for the following normal feed load."""
        if (
            type(prepared) is not _PreparedLiveBarCohortDelivery
            or prepared.feed_ref is not self
            or prepared.envelope is not envelope
        ):
            raise ValueError("Cerebro supplied a mismatched prepared cohort delivery")
        if self._cohort_armed_envelope is not None or self._cohort_staged_delivery is not None:
            raise RuntimeError("BtApiFeed already has an armed cohort delivery")
        cohort = self._live_bar_cohort
        if cohort is None or self._cohort_delivery_failed:
            raise RuntimeError("BtApiFeed is not ready for cohort delivery")
        if cohort.prepared_envelope(self) is not envelope:
            raise ValueError("Cerebro supplied a non-prepared cohort envelope")
        self._cohort_armed_envelope = envelope
        self._cohort_staged_delivery = prepared

    def _preflight_live_bar_cohort_delivery_commit(self, envelope, prepared):
        """Validate staged line state before the cohort commits receipts atomically."""
        cohort = self._live_bar_cohort
        if (
            cohort is None
            or self._cohort_delivery_failed
            or self._cohort_armed_envelope is not envelope
            or self._cohort_staged_delivery is not prepared
            or type(prepared) is not _PreparedLiveBarCohortDelivery
            or prepared.feed_ref is not self
            or prepared.envelope is not envelope
        ):
            self._cohort_delivery_failed = True
            raise ValueError("BtApiFeed cohort delivery stage changed before commit")
        if cohort.prepared_envelope(self) is not envelope:
            self._cohort_delivery_failed = True
            raise ValueError("BtApiFeed cohort envelope changed before commit")
        line_values = (
            ("datetime", self.lines.datetime[0], prepared.datetime_value),
            ("open", self.lines.open[0], prepared.raw_values["open"]),
            ("high", self.lines.high[0], prepared.raw_values["high"]),
            ("low", self.lines.low[0], prepared.raw_values["low"]),
            ("close", self.lines.close[0], prepared.raw_values["close"]),
            ("volume", self.lines.volume[0], prepared.raw_values["volume"]),
            (
                "openinterest",
                self.lines.openinterest[0],
                prepared.raw_values.get("openinterest", 0.0),
            ),
        )
        member = cohort.member_for_feed(self)
        if member is None or member.feed_ref is not self:
            self._cohort_delivery_failed = True
            raise ValueError("BtApiFeed is no longer the exact live cohort member")
        declared_lines = set(member.line_fields)
        line_values += tuple(
            (
                name,
                getattr(self.lines, name)[0],
                prepared.raw_values[name] if name in declared_lines else math.nan,
            )
            for name in _LIVE_COHORT_EXTRA_LINES
        )

        def values_match(actual, expected):
            if actual == expected:
                return True
            try:
                return math.isnan(float(actual)) and math.isnan(float(expected))
            except (TypeError, ValueError, OverflowError):
                return False

        if any(not values_match(actual, expected) for _name, actual, expected in line_values):
            self._cohort_delivery_failed = True
            raise ValueError("BtApiFeed line values differ from staged cohort delivery")
        return True

    def _commit_live_bar_cohort_delivery(self, envelope, prepared):
        """Publish local feed metadata after the cohort atomically records receipts."""
        # Cerebro preflights every feed and calls LiveBarCohort's batch commit
        # before entering this assignment-only phase. Keeping receipt mutation
        # out of this method prevents a failure on one feed from publishing a
        # partial cohort batch.
        self._cohort_last_delivered_slot_index = envelope.slot_index
        self._cohort_armed_envelope = None
        self._cohort_staged_delivery = None
        return True

    def _abort_live_bar_cohort_delivery(self):
        """Discard staged state after Cerebro rolls back a failed batch write."""
        self._cohort_armed_envelope = None
        self._cohort_staged_delivery = None
        self._cohort_delivery_failed = True

    def _load_live_bar_cohort_envelope(self):
        cohort = self._live_bar_cohort
        envelope = self._cohort_armed_envelope
        prepared = self._cohort_staged_delivery
        if self._cohort_delivery_failed:
            return None
        if envelope is None or prepared is None:
            return None
        if (
            cohort.prepared_envelope(self) is not envelope
            or prepared.feed_ref is not self
            or prepared.envelope is not envelope
        ):
            self._cohort_delivery_failed = True
            raise ValueError("armed cohort delivery is no longer the prepared object")
        try:
            raw_values = prepared.raw_values
            self.lines.datetime[0] = prepared.datetime_value
            self.lines.open[0] = raw_values["open"]
            self.lines.high[0] = raw_values["high"]
            self.lines.low[0] = raw_values["low"]
            self.lines.close[0] = raw_values["close"]
            self.lines.volume[0] = raw_values["volume"]
            self.lines.openinterest[0] = raw_values.get("openinterest", 0.0)
            member = cohort.member_for_feed(self)
            if member is None or member.feed_ref is not self:
                self._cohort_delivery_failed = True
                raise ValueError("BtApiFeed is no longer the exact live cohort member")
            declared_lines = set(member.line_fields)
            for name in _LIVE_COHORT_EXTRA_LINES:
                value = raw_values[name] if name in declared_lines else math.nan
                getattr(self.lines, name)[0] = value
            return True
        except Exception:
            self._cohort_delivery_failed = True
            raise

    def _dispatch_live_bar_cohort_envelope(self, envelope):
        """Dispatch notify_bar only after Cerebro verifies a complete batch."""
        if envelope.feed_ref is not self:
            return False
        if envelope.source_role == "live":
            # Status notification can append to a user-visible notification
            # queue and therefore may fail. Run it only after Cerebro has
            # committed every member's lines and local delivery metadata.
            self._mark_live()
        if envelope.source_role != "live":
            return False
        if not self.p.dispatch_bars:
            return False
        event = envelope.event_ref
        if event is None:
            raise ValueError("live cohort envelope lost its source event")
        if isinstance(event, Mapping):
            event = dict(event)
            event.update(dict(envelope.raw_values))
            event.update(
                {
                    "datetime": envelope.close_time,
                    "timestamp": envelope.close_time.timestamp(),
                    "bucket_start": envelope.bucket_start,
                    "bucket_end": envelope.close_time,
                    "available_at": envelope.available_at,
                    "trading_day": envelope.trading_day,
                    "session_segment": envelope.session_segment,
                    "connection_generation": envelope.connection_generation,
                    "bar_sequence": envelope.feed_sequence,
                    "bar_id": envelope.bar_id,
                    "complete": envelope.complete,
                    "quality": envelope.quality,
                    "quality_flags": envelope.quality_flags,
                }
            )
        else:
            event = copy.copy(event)
            for name, value in envelope.raw_values.items():
                setattr(event, name, value)
            for name, value in (
                ("datetime", envelope.close_time),
                ("timestamp", envelope.close_time.timestamp()),
                ("bucket_start", envelope.bucket_start),
                ("bucket_end", envelope.close_time),
                ("available_at", envelope.available_at),
                ("trading_day", envelope.trading_day),
                ("session_segment", envelope.session_segment),
                ("connection_generation", envelope.connection_generation),
                ("bar_sequence", envelope.feed_sequence),
                ("bar_id", envelope.bar_id),
                ("complete", envelope.complete),
                ("quality", envelope.quality),
                ("quality_flags", envelope.quality_flags),
            ):
                setattr(event, name, value)
        self._dispatch_event(
            channel_type="bar",
            priority=EventPriority.BAR,
            event_data=event,
        )
        return True

