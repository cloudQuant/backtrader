"""Bounded, source-bound delivery of complete live bar cohorts.

This module owns bar-envelope validation and cohort batch receipts.  It does
not schedule indicators and does not grant strategy or order readiness.  The
normal Cerebro loop remains responsible for advancing feed lines and their
registered indicators.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import itertools
import json
import math
import numbers
import threading
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Deque, Dict, Iterable, Mapping, Optional, Tuple


_UTC = _datetime.timezone.utc
_REQUIRED_OHLCV = ("open", "high", "low", "close", "volume")
_DEFAULT_NUMERIC_FIELDS = frozenset(_REQUIRED_OHLCV)
# Finite calendars may include both factor warm-up and evaluation history.
# Keep a hard ceiling above 100k bars while still making exhaustion explicit;
# this does not imply a rolling or infinite future calendar.
_MAX_CALENDAR_SLOTS = 200_000
_MAX_COHORT_MEMBERS = 512
_MAX_PENDING_SLOTS = 64
_MAX_WINDOW_BARS = 4096


class LiveCohortError(RuntimeError):
    """Base error for invalid or unsafe live cohort state transitions."""


class LiveCohortValidationError(LiveCohortError, ValueError):
    """A source bar or calendar does not satisfy its registered contract."""


class LiveCohortFrozenError(LiveCohortError):
    """The cohort has frozen after a gap, conflict, or invalid transition."""


class LiveCohortCapacityError(LiveCohortError):
    """A bounded source or preparation limit would be exceeded."""


def _nonempty_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise LiveCohortValidationError("{} must be a non-empty exact string".format(name))
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LiveCohortValidationError("{} must be a positive integer".format(name))
    return value


def _aware_utc(value: Any, name: str) -> _datetime.datetime:
    if not isinstance(value, _datetime.datetime):
        raise LiveCohortValidationError("{} must be a timezone-aware datetime".format(name))
    if value.tzinfo is None or value.utcoffset() is None:
        raise LiveCohortValidationError("{} must be timezone-aware".format(name))
    return value.astimezone(_UTC)


def _read(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _frozen_scalar(value: Any, name: str) -> Any:
    """Keep envelope data immutable and serialization-friendly."""
    if isinstance(value, float) and not math.isfinite(value):
        raise LiveCohortValidationError("{} must be finite".format(name))
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return value
    if isinstance(value, _datetime.datetime):
        return _aware_utc(value, name)
    if isinstance(value, tuple):
        return tuple(_frozen_scalar(item, name) for item in value)
    raise LiveCohortValidationError("{} must be an immutable scalar or tuple".format(name))


def _frozen_mapping(
    values: Mapping[str, Any], *, allow_nan_names: Iterable[str] = ()
) -> Mapping[str, Any]:
    if not isinstance(values, Mapping):
        raise LiveCohortValidationError("raw_values must be a mapping")
    allow_nan = set(allow_nan_names)
    frozen = {}
    for key, value in values.items():
        if key in allow_nan and isinstance(value, float) and math.isnan(value):
            frozen[key] = value
        else:
            frozen[key] = _frozen_scalar(value, key)
    return MappingProxyType(frozen)


@dataclass(frozen=True)
class LiveCalendarMemberSession:
    """One member's exchange-local day and session identity for a slot."""

    trading_day: str
    session_segment: str

    def __post_init__(self) -> None:
        _nonempty_text(self.trading_day, "trading_day")
        _nonempty_text(self.session_segment, "session_segment")


@dataclass(frozen=True)
class LiveCalendarSlot:
    """One explicitly planned bar interval in UTC."""

    slot_id: str
    bucket_start: _datetime.datetime
    close_time: _datetime.datetime
    trading_day: str
    session_segment: str
    member_sessions: Mapping[str, LiveCalendarMemberSession] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _nonempty_text(self.slot_id, "slot_id")
        _nonempty_text(self.trading_day, "trading_day")
        _nonempty_text(self.session_segment, "session_segment")
        start = _aware_utc(self.bucket_start, "bucket_start")
        close = _aware_utc(self.close_time, "close_time")
        if close <= start:
            raise LiveCohortValidationError("calendar slot close_time must follow bucket_start")
        if not isinstance(self.member_sessions, Mapping):
            raise LiveCohortValidationError("member_sessions must be a mapping")
        member_sessions = {}
        for member_id, session in self.member_sessions.items():
            _nonempty_text(member_id, "member_sessions member_id")
            if type(session) is not LiveCalendarMemberSession:
                raise LiveCohortValidationError(
                    "member_sessions values must be LiveCalendarMemberSession values"
                )
            member_sessions[member_id] = session
        object.__setattr__(self, "bucket_start", start)
        object.__setattr__(self, "close_time", close)
        object.__setattr__(self, "member_sessions", MappingProxyType(member_sessions))


@dataclass(frozen=True)
class LiveCohortCalendar:
    """A finite calendar epoch. Exhaustion never implies an infinite grid."""

    calendar_id: str
    version: str
    epoch_id: int
    frequency: str
    frequency_seconds: int
    timezone_id: str
    clock_domain_id: str
    session_semantics: str
    slots: Tuple[LiveCalendarSlot, ...]
    _fingerprint: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name in (
            "calendar_id",
            "version",
            "frequency",
            "timezone_id",
            "clock_domain_id",
            "session_semantics",
        ):
            _nonempty_text(getattr(self, name), name)
        _positive_int(self.epoch_id, "epoch_id")
        _positive_int(self.frequency_seconds, "frequency_seconds")
        slots = tuple(self.slots)
        if not slots:
            raise LiveCohortValidationError("calendar epoch must contain at least one planned slot")
        if len(slots) > _MAX_CALENDAR_SLOTS:
            raise LiveCohortCapacityError("calendar epoch exceeds the finite slot limit")
        prior = None
        seen_ids = set()
        for slot in slots:
            if not isinstance(slot, LiveCalendarSlot):
                raise LiveCohortValidationError("calendar slots must be LiveCalendarSlot values")
            if slot.slot_id in seen_ids:
                raise LiveCohortValidationError("calendar slot_id values must be unique")
            seen_ids.add(slot.slot_id)
            if (slot.close_time - slot.bucket_start).total_seconds() != self.frequency_seconds:
                raise LiveCohortValidationError("calendar slot duration does not match frequency")
            if prior is not None:
                if slot.bucket_start < prior.close_time:
                    raise LiveCohortValidationError(
                        "calendar slots must be ordered and non-overlapping"
                    )
                if slot.close_time <= prior.close_time:
                    raise LiveCohortValidationError(
                        "calendar close_time values must strictly increase"
                    )
            prior = slot
        object.__setattr__(self, "slots", slots)
        digest = hashlib.sha256()
        header = {
            "calendar_id": self.calendar_id,
            "version": self.version,
            "epoch_id": self.epoch_id,
            "frequency": self.frequency,
            "frequency_seconds": self.frequency_seconds,
            "timezone_id": self.timezone_id,
            "clock_domain_id": self.clock_domain_id,
            "session_semantics": self.session_semantics,
        }
        _update_calendar_fingerprint(digest, header)
        for slot in slots:
            _update_calendar_fingerprint(
                digest,
                {
                    "slot_id": slot.slot_id,
                    "bucket_start": slot.bucket_start.isoformat(),
                    "close_time": slot.close_time.isoformat(),
                    "trading_day": slot.trading_day,
                    "session_segment": slot.session_segment,
                    "member_sessions": {
                        member_id: {
                            "trading_day": session.trading_day,
                            "session_segment": session.session_segment,
                        }
                        for member_id, session in sorted(slot.member_sessions.items())
                    },
                },
            )
        object.__setattr__(self, "_fingerprint", digest.hexdigest())

    @property
    def fingerprint(self) -> str:
        """Stable digest of the finite calendar, including member session evidence."""
        return self._fingerprint

    @property
    def calendar_fingerprint(self) -> str:
        """Explicitly named alias for :attr:`fingerprint`."""
        return self._fingerprint


def _update_calendar_fingerprint(digest: Any, value: Mapping[str, Any]) -> None:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")
    digest.update(len(encoded).to_bytes(8, byteorder="big", signed=False))
    digest.update(encoded)


@dataclass(frozen=True)
class LiveCohortMember:
    """Frozen schema for one exact feed object registered with a cohort."""

    member_id: str
    feed_ref: Any = field(compare=False, repr=False)
    instrument: str = ""
    source_ref: str = ""
    line_fields: Tuple[str, ...] = ()
    raw_fields: Tuple[str, ...] = ()
    clock_domain_id: str = ""
    timezone_id: str = "UTC"
    session_semantics: str = ""
    numeric_fields: Tuple[str, ...] = tuple(_REQUIRED_OHLCV)

    def __post_init__(self) -> None:
        for name in (
            "member_id",
            "instrument",
            "source_ref",
            "clock_domain_id",
            "timezone_id",
            "session_semantics",
        ):
            _nonempty_text(getattr(self, name), name)
        if self.feed_ref is None:
            raise LiveCohortValidationError("feed_ref is required")
        line_fields = tuple(self.line_fields)
        raw_fields = tuple(self.raw_fields)
        numeric_fields = tuple(self.numeric_fields)
        for name, values in (
            ("line_fields", line_fields),
            ("raw_fields", raw_fields),
            ("numeric_fields", numeric_fields),
        ):
            if not values or any(not isinstance(value, str) or not value for value in values):
                raise LiveCohortValidationError(
                    "{} must contain non-empty field names".format(name)
                )
            if len(set(values)) != len(values):
                raise LiveCohortValidationError("{} must not contain duplicates".format(name))
        if not set(_REQUIRED_OHLCV).issubset(raw_fields):
            raise LiveCohortValidationError("raw_fields must declare open/high/low/close/volume")
        if not set(_REQUIRED_OHLCV).issubset(numeric_fields):
            raise LiveCohortValidationError(
                "numeric_fields must declare finite numeric open/high/low/close/volume"
            )
        if not set(line_fields).issubset(raw_fields):
            raise LiveCohortValidationError("every exposed line field must be raw-validated")
        if not set(numeric_fields).issubset(raw_fields):
            raise LiveCohortValidationError("numeric_fields must be declared in raw_fields")
        if not set(line_fields).issubset(numeric_fields):
            raise LiveCohortValidationError(
                "every exposed feed line must map to a validated numeric raw field"
            )
        object.__setattr__(self, "line_fields", line_fields)
        object.__setattr__(self, "raw_fields", raw_fields)
        object.__setattr__(self, "numeric_fields", numeric_fields)


@dataclass(frozen=True)
class BarEnvelope:
    """Validated immutable view of one provider/source bar."""

    cohort_id: str
    calendar_id: str
    epoch_id: int
    slot_index: int
    slot_id: str
    member_id: str
    feed_ref: Any = field(compare=False, repr=False)
    instrument: str = ""
    source_ref: str = ""
    source_role: str = ""
    connection_generation: Any = None
    feed_sequence: int = 0
    bucket_start: _datetime.datetime = field(default=None)  # type: ignore[assignment]
    close_time: _datetime.datetime = field(default=None)  # type: ignore[assignment]
    available_at: _datetime.datetime = field(default=None)  # type: ignore[assignment]
    trading_day: str = ""
    session_segment: str = ""
    timezone_id: str = ""
    clock_domain_id: str = ""
    bar_id: str = ""
    complete: bool = False
    quality: str = ""
    present: bool = False
    missing_fields: Tuple[str, ...] = ()
    raw_values: Mapping[str, Any] = field(default_factory=dict, compare=False)
    quality_flags: Tuple[str, ...] = ()
    event_source: str = ""
    received_monotonic_ns: Optional[int] = None
    event_ref: Any = field(default=None, compare=False, repr=False)
    evidence_ref: Any = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "bucket_start", _aware_utc(self.bucket_start, "bucket_start"))
        object.__setattr__(self, "close_time", _aware_utc(self.close_time, "close_time"))
        object.__setattr__(self, "available_at", _aware_utc(self.available_at, "available_at"))
        object.__setattr__(
            self,
            "raw_values",
            _frozen_mapping(self.raw_values, allow_nan_names=self.missing_fields),
        )
        object.__setattr__(self, "missing_fields", tuple(self.missing_fields))
        object.__setattr__(self, "quality_flags", tuple(self.quality_flags))


@dataclass(frozen=True)
class CaptureResult:
    """Result of validating and queueing a source bar."""

    envelope: BarEnvelope
    duplicate: bool
    slot_index: int


@dataclass(frozen=True)
class LiveInputBinding:
    """Cohort-issued proof that one factor input belongs to an exact feed."""

    cohort_id: str
    member_id: str
    feed_ref: Any = field(compare=False, repr=False)
    source_ref: str = ""
    line_name: str = ""
    raw_field: str = ""
    calendar_id: str = ""
    frequency: str = ""


@dataclass(frozen=True)
class LiveDeliveryReceipt:
    """Read-only proof that one validated envelope advanced one exact feed."""

    cohort_id: str
    calendar_id: str
    epoch_id: int
    batch_id: str
    slot_index: int
    member_id: str
    feed_ref: Any = field(compare=False, repr=False)
    source_ref: str = ""
    envelope: BarEnvelope = field(default=None)  # type: ignore[assignment]
    feed_sequence: int = 0
    close_time: _datetime.datetime = field(default=None)  # type: ignore[assignment]
    available_at: _datetime.datetime = field(default=None)  # type: ignore[assignment]
    source_role: str = ""
    complete: bool = False
    quality: str = ""
    present: bool = False
    missing_fields: Tuple[str, ...] = ()
    raw_values: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "raw_values",
            _frozen_mapping(self.raw_values, allow_nan_names=self.missing_fields),
        )
        object.__setattr__(self, "missing_fields", tuple(self.missing_fields))


@dataclass(frozen=True)
class LiveEpochCutover:
    """Observed per-feed transition into delivered live bars for one epoch."""

    cohort_id: str
    member_id: str
    epoch_id: int
    history_last_close_time: Optional[_datetime.datetime]
    first_live_close_time: _datetime.datetime
    transition_kind: str
    crossed_live: bool
    first_live_receipt: LiveDeliveryReceipt = field(compare=False, repr=False)


@dataclass(frozen=True)
class LiveCohortBatch:
    """A complete all-member batch, published after every feed line write."""

    batch_id: str
    cohort_id: str
    calendar_id: str
    calendar_version: str
    epoch_id: int
    slot_index: int
    close_time: _datetime.datetime
    available_at: _datetime.datetime
    members: Mapping[str, LiveDeliveryReceipt] = field(default_factory=dict)
    cutovers: Mapping[str, LiveEpochCutover] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "members", MappingProxyType(dict(self.members)))
        object.__setattr__(self, "cutovers", MappingProxyType(dict(self.cutovers)))

    @property
    def status(self) -> str:
        """A published object exists only after every registered member delivered."""
        return "COMPLETE"

    def receipt_for_feed(self, feed_ref: Any) -> Optional[LiveDeliveryReceipt]:
        for receipt in self.members.values():
            if receipt.feed_ref is feed_ref:
                return receipt
        return None


@dataclass(frozen=True)
class PreparedBarBatch:
    """Validated immutable envelopes ready for one normal feed advance."""

    cohort_id: str
    calendar_id: str
    calendar_version: str
    epoch_id: int
    slot_index: int
    batch_id: str
    close_time: _datetime.datetime
    envelopes: Mapping[str, BarEnvelope] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "envelopes", MappingProxyType(dict(self.envelopes)))

    def envelope_for_feed(self, feed_ref: Any) -> Optional[BarEnvelope]:
        for envelope in self.envelopes.values():
            if envelope.feed_ref is feed_ref:
                return envelope
        return None


@dataclass(frozen=True)
class PrepareResult:
    """Bounded result of one preparation attempt."""

    status: str
    prepared: Optional[PreparedBarBatch] = None
    missing_member_ids: Tuple[str, ...] = ()
    reason: Optional[str] = None


@dataclass(frozen=True)
class LiveCohortWait:
    """Read-only engine wait recommendation for the current cohort slot."""

    status: str
    timeout_seconds: Optional[float]
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in ("WAITING", "READY", "EXHAUSTED", "FROZEN"):
            raise LiveCohortValidationError("unknown cohort wait status")
        if self.status in ("WAITING", "READY"):
            if (
                isinstance(self.timeout_seconds, bool)
                or not isinstance(self.timeout_seconds, numbers.Real)
                or not math.isfinite(float(self.timeout_seconds))
                or self.timeout_seconds < 0
            ):
                raise LiveCohortValidationError(
                    "active cohort wait requires a finite non-negative timeout"
                )
            if self.status == "READY" and self.timeout_seconds != 0.0:
                raise LiveCohortValidationError("READY cohort wait must be immediate")
        elif self.timeout_seconds is not None:
            raise LiveCohortValidationError("terminal cohort wait cannot carry a timeout")


@dataclass(frozen=True)
class LiveCohortGap:
    """A planned slot that did not receive all required members by deadline."""

    cohort_id: str
    calendar_id: str
    epoch_id: int
    slot_index: int
    slot_id: str
    close_time: _datetime.datetime
    missing_member_ids: Tuple[str, ...]
    first_wait_monotonic_ns: int
    deadline_monotonic_ns: int
    reason: str


@dataclass(frozen=True)
class _BarSignature:
    """Bounded duplicate-detection facts without retaining provider objects."""

    data: Tuple[Any, ...]
    source_role: str
    connection_generation: Any
    feed_sequence: int
    bar_id: str


class LiveBarCohort:
    """Validate, seal, and deliver one finite multi-feed bar cohort.

    The cohort is an input coordinator, not a second indicator scheduler. A
    caller first captures validated source events, then lets Cerebro advance
    each member feed through its ordinary ``next``/``_load`` lifecycle. The
    last delivery publishes ``current_batch`` atomically for readers.
    """

    def __init__(
        self,
        cohort_id: str,
        calendar: LiveCohortCalendar,
        *,
        max_pending_slots: int = 8,
        max_window_bars: int = 512,
        wait_timeout_ns: int = 5_000_000_000,
    ) -> None:
        self.cohort_id = _nonempty_text(cohort_id, "cohort_id")
        if not isinstance(calendar, LiveCohortCalendar):
            raise LiveCohortValidationError("calendar must be a LiveCohortCalendar")
        if not 1 <= max_pending_slots <= _MAX_PENDING_SLOTS:
            raise LiveCohortValidationError("max_pending_slots is outside the bounded range")
        if not 1 <= max_window_bars <= _MAX_WINDOW_BARS:
            raise LiveCohortValidationError("max_window_bars is outside the bounded range")
        _positive_int(wait_timeout_ns, "wait_timeout_ns")
        self._calendar = calendar
        self._slot_indices_by_close = {
            slot.close_time: index for index, slot in enumerate(calendar.slots)
        }
        self._max_pending_slots = max_pending_slots
        self._max_window_bars = max_window_bars
        self._wait_timeout_ns = wait_timeout_ns
        self._members: Dict[str, LiveCohortMember] = {}
        self._feed_members: Dict[int, LiveCohortMember] = {}
        self._binding_cache: Dict[Tuple[str, str], LiveInputBinding] = {}
        self._sealed = False
        self._frozen_reason: Optional[str] = None
        self._next_slot_index = 0
        self._pending: Dict[int, Dict[str, BarEnvelope]] = {}
        self._prepared: Optional[PreparedBarBatch] = None
        self._delivered: Dict[str, LiveDeliveryReceipt] = {}
        self._current_batch: Optional[LiveCohortBatch] = None
        self._wait_started_ns: Optional[int] = None
        self._wait_missing_member_ids: Tuple[str, ...] = ()
        self._last_prepare_ns: Optional[int] = None
        self._gaps: Deque[LiveCohortGap] = deque(maxlen=64)
        self._recent_signatures: Dict[Tuple[int, str], _BarSignature] = {}
        self._recent_signature_order: Deque[Tuple[int, str]] = deque()
        self._window_receipts: Dict[str, Deque[LiveDeliveryReceipt]] = {}
        self._generation_by_role: Dict[Tuple[str, str], Any] = {}
        self._last_sequence: Dict[Tuple[str, str, Any], int] = {}
        self._last_role: Dict[str, Optional[str]] = {}
        self._history_last_close: Dict[str, _datetime.datetime] = {}
        self._first_live_receipt: Dict[str, LiveDeliveryReceipt] = {}
        self._lock = threading.RLock()

    @property
    def calendar_id(self) -> str:
        return self._calendar.calendar_id

    @property
    def calendar_version(self) -> str:
        return self._calendar.version

    @property
    def calendar_fingerprint(self) -> str:
        return self._calendar.fingerprint

    @property
    def epoch_id(self) -> int:
        return self._calendar.epoch_id

    @property
    def frequency(self) -> str:
        return self._calendar.frequency

    @property
    def frequency_seconds(self) -> int:
        return self._calendar.frequency_seconds

    @property
    def max_pending_slots(self) -> int:
        return self._max_pending_slots

    @property
    def max_window_bars(self) -> int:
        return self._max_window_bars

    @property
    def wait_timeout_ns(self) -> int:
        """Monotonic local wait cap; it is not a source-event watermark."""
        return self._wait_timeout_ns

    @property
    def max_pending_bars(self) -> int:
        return self._max_pending_slots * len(self._members)

    @property
    def frozen(self) -> bool:
        return self._frozen_reason is not None

    @property
    def frozen_reason(self) -> Optional[str]:
        return self._frozen_reason

    @property
    def gaps(self) -> Tuple[LiveCohortGap, ...]:
        return tuple(self._gaps)

    @property
    def member_ids(self) -> Tuple[str, ...]:
        return tuple(self._members)

    def register_member(
        self,
        member_id: str,
        feed_ref: Any,
        *,
        instrument: str,
        source_ref: str,
        line_fields: Iterable[str],
        raw_fields: Iterable[str],
        clock_domain_id: Optional[str] = None,
        timezone_id: Optional[str] = None,
        session_semantics: Optional[str] = None,
        numeric_fields: Iterable[str] = _REQUIRED_OHLCV,
    ) -> LiveCohortMember:
        with self._lock:
            if self._sealed:
                raise LiveCohortError("cohort member registration is sealed")
            if len(self._members) >= _MAX_COHORT_MEMBERS:
                raise LiveCohortCapacityError("cohort member limit exceeded")
            if member_id in self._members:
                raise LiveCohortValidationError("member_id is already registered")
            if feed_ref is None or id(feed_ref) in self._feed_members:
                raise LiveCohortValidationError("each exact feed object may be registered once")
            member = LiveCohortMember(
                member_id=member_id,
                feed_ref=feed_ref,
                instrument=instrument,
                source_ref=source_ref,
                line_fields=tuple(line_fields),
                raw_fields=tuple(raw_fields),
                clock_domain_id=clock_domain_id or self._calendar.clock_domain_id,
                timezone_id=timezone_id or self._calendar.timezone_id,
                session_semantics=session_semantics or self._calendar.session_semantics,
                numeric_fields=tuple(numeric_fields),
            )
            if member.clock_domain_id != self._calendar.clock_domain_id:
                raise LiveCohortValidationError("member clock domain does not match calendar")
            if member.timezone_id != self._calendar.timezone_id:
                raise LiveCohortValidationError("member timezone does not match calendar")
            if member.session_semantics != self._calendar.session_semantics:
                raise LiveCohortValidationError("member session semantics do not match calendar")
            self._members[member_id] = member
            self._feed_members[id(feed_ref)] = member
            self._window_receipts[member_id] = deque(maxlen=self.max_window_bars)
            self._last_role[member_id] = None
            return member

    def seal(self) -> None:
        with self._lock:
            if not self._members:
                raise LiveCohortValidationError("cohort requires at least one registered member")
            expected_members = set(self._members)
            for slot in self._calendar.slots:
                if not slot.member_sessions:
                    continue
                configured_members = set(slot.member_sessions)
                if configured_members != expected_members:
                    missing = tuple(sorted(expected_members - configured_members))
                    extra = tuple(sorted(configured_members - expected_members))
                    raise LiveCohortValidationError(
                        "calendar member_sessions must exactly cover registered members "
                        "(missing={!r}, extra={!r})".format(missing, extra)
                    )
            self._sealed = True

    def member_for_feed(self, feed_ref: Any) -> Optional[LiveCohortMember]:
        member = self._feed_members.get(id(feed_ref))
        if member is None or member.feed_ref is not feed_ref:
            return None
        return member

    def require_factor_field(self, feed_ref: Any, line_name: str) -> LiveInputBinding:
        with self._lock:
            self._require_open()
            self.seal()
            member = self.member_for_feed(feed_ref)
            if member is None:
                raise LiveCohortValidationError(
                    "factor feed is not an exact registered cohort member"
                )
            if not isinstance(line_name, str) or line_name not in member.line_fields:
                raise LiveCohortValidationError("factor field is not declared by this member")
            if line_name not in member.raw_fields:
                raise LiveCohortValidationError("factor field has no validated raw source field")
            key = (member.member_id, line_name)
            binding = self._binding_cache.get(key)
            if binding is None:
                binding = LiveInputBinding(
                    cohort_id=self.cohort_id,
                    member_id=member.member_id,
                    feed_ref=member.feed_ref,
                    source_ref=member.source_ref,
                    line_name=line_name,
                    raw_field=line_name,
                    calendar_id=self.calendar_id,
                    frequency=self.frequency,
                )
                self._binding_cache[key] = binding
            return binding

    def owns_factor_binding(self, receipt: Any) -> bool:
        if not isinstance(receipt, LiveInputBinding):
            return False
        if receipt.cohort_id != self.cohort_id:
            return False
        member = self.member_for_feed(receipt.feed_ref)
        if member is None or member.member_id != receipt.member_id:
            return False
        return self._binding_cache.get((member.member_id, receipt.line_name)) is receipt

    def capture_bar(
        self,
        feed_ref: Any,
        event: Any,
        *,
        source_role: str,
        received_monotonic_ns: Optional[int] = None,
    ) -> CaptureResult:
        """Validate and queue one source event without writing feed lines."""
        with self._lock:
            self._require_open()
            self.seal()
            member = self.member_for_feed(feed_ref)
            if member is None:
                self._freeze("unregistered_feed_event")
                raise LiveCohortValidationError("bar event came from an unregistered feed object")
            try:
                envelope = self._build_envelope(member, event, source_role, received_monotonic_ns)
            except LiveCohortValidationError:
                self._freeze("invalid_source_bar")
                raise
            slot_index = envelope.slot_index
            existing = self._pending.get(slot_index, {}).get(member.member_id)
            if existing is not None:
                if (
                    self._data_signature(existing) == self._data_signature(envelope)
                    and existing.source_role == envelope.source_role
                    and existing.connection_generation != envelope.connection_generation
                ):
                    self._freeze("connection_generation_changed")
                    raise LiveCohortFrozenError(
                        "duplicate bar came from a different connection generation"
                    )
                if self._is_duplicate(existing, envelope):
                    if existing.source_role != envelope.source_role:
                        self._validate_member_sequence(member, envelope)
                    return CaptureResult(existing, True, slot_index)
                self._freeze("conflicting_duplicate_bar")
                raise LiveCohortFrozenError("conflicting duplicate bar froze the cohort")
            if slot_index < self._next_slot_index:
                signature = self._recent_signatures.get((slot_index, member.member_id))
                candidate_signature = self._signature_for(envelope)
                if signature is not None and self._signature_is_duplicate(
                    signature, candidate_signature
                ):
                    if signature.source_role != envelope.source_role:
                        self._validate_member_sequence(member, envelope)
                    return CaptureResult(envelope, True, slot_index)
                if (
                    signature is not None
                    and signature.data == candidate_signature.data
                    and signature.source_role == envelope.source_role
                    and signature.connection_generation != envelope.connection_generation
                ):
                    self._freeze("connection_generation_changed")
                    raise LiveCohortFrozenError(
                        "late duplicate came from a different connection generation"
                    )
                self._freeze("late_bar_after_seal")
                raise LiveCohortFrozenError("late bar cannot rewrite a sealed cohort slot")
            if slot_index >= self._next_slot_index + self.max_pending_slots:
                self._freeze("pending_slot_window_exceeded")
                raise LiveCohortCapacityError("source bar exceeded the bounded pending slot window")
            pending_count = sum(len(rows) for rows in self._pending.values())
            if pending_count >= self.max_pending_slots * len(self._members):
                self._freeze("pending_bar_limit_exceeded")
                raise LiveCohortCapacityError("bounded pending bar limit exceeded")
            self._validate_member_sequence(member, envelope)
            self._pending.setdefault(slot_index, {})[member.member_id] = envelope
            return CaptureResult(envelope, False, slot_index)

    def _build_envelope(
        self,
        member: LiveCohortMember,
        event: Any,
        source_role: str,
        received_monotonic_ns: Optional[int],
    ) -> BarEnvelope:
        if source_role not in ("history", "live"):
            raise LiveCohortValidationError("source_role must be exactly 'history' or 'live'")
        slot_start = _aware_utc(_read(event, "bucket_start"), "bucket_start")
        close_time = _aware_utc(_read(event, "bucket_end"), "bucket_end")
        available_at = _aware_utc(_read(event, "available_at"), "available_at")
        if available_at < close_time:
            raise LiveCohortValidationError("available_at cannot precede close_time")
        slot_index = self._slot_index(close_time)
        if slot_index is None:
            raise LiveCohortValidationError(
                "bar close_time is not an explicit planned calendar slot"
            )
        slot = self._calendar.slots[slot_index]
        if slot.bucket_start != slot_start:
            raise LiveCohortValidationError("bar bucket_start does not match its planned slot")

        symbol = _read(event, "instrument", _read(event, "symbol", None))
        if symbol != member.instrument:
            raise LiveCohortValidationError("bar instrument does not match the exact feed member")
        event_clock = _read(event, "clock_domain_id", None)
        if event_clock != member.clock_domain_id:
            raise LiveCohortValidationError("bar clock domain does not match the member contract")
        generation = _read(event, "connection_generation", None)
        if (
            isinstance(generation, bool)
            or not isinstance(generation, (str, int))
            or generation in ("", 0)
        ):
            raise LiveCohortValidationError(
                "connection_generation must be an explicit non-empty value"
            )
        sequence = _positive_int(_read(event, "bar_sequence", None), "bar_sequence")
        bar_id = _nonempty_text(_read(event, "bar_id", None), "bar_id")
        trading_day = _nonempty_text(_read(event, "trading_day", None), "trading_day")
        session_segment = _nonempty_text(_read(event, "session_segment", None), "session_segment")
        expected_session = slot.member_sessions.get(member.member_id)
        expected_trading_day = (
            expected_session.trading_day if expected_session is not None else slot.trading_day
        )
        expected_session_segment = (
            expected_session.session_segment
            if expected_session is not None
            else slot.session_segment
        )
        if trading_day != expected_trading_day or session_segment != expected_session_segment:
            raise LiveCohortValidationError(
                "bar trading day/session does not match the planned slot"
            )
        event_timezone = _read(event, "timezone_id", member.timezone_id)
        if event_timezone != member.timezone_id:
            raise LiveCohortValidationError("bar timezone does not match the exact feed member")
        timestamp = _read(event, "timestamp", None)
        if timestamp is not None:
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                raise LiveCohortValidationError("bar timestamp must be numeric when present")
            if (
                not math.isfinite(float(timestamp))
                or abs(float(timestamp) - close_time.timestamp()) > 1.0e-6
            ):
                raise LiveCohortValidationError("bar timestamp does not match close_time")

        complete = _read(event, "complete", None)
        quality = _read(event, "quality", None)
        if complete is not True:
            raise LiveCohortValidationError("bar must explicitly declare complete=True")

        missing_fields = _read(event, "missing_fields", ())
        if type(missing_fields) is not tuple:
            raise LiveCohortValidationError("missing_fields must be an immutable tuple")
        if any(not isinstance(name, str) or not name for name in missing_fields):
            raise LiveCohortValidationError("missing_fields must contain non-empty field names")
        if (
            len(missing_fields) != len(set(missing_fields))
            or tuple(sorted(missing_fields)) != missing_fields
        ):
            raise LiveCohortValidationError("missing_fields must be sorted and unique")
        if not set(missing_fields).issubset(set(member.numeric_fields)):
            raise LiveCohortValidationError(
                "only declared numeric raw fields may be marked missing"
            )
        if missing_fields:
            if quality != "MISSING":
                raise LiveCohortValidationError(
                    "a missing-field bar must declare quality='MISSING'"
                )
        elif quality != "GOOD":
            raise LiveCohortValidationError("a complete bar without missing fields must be GOOD")

        raw_values = {}
        for field_name in member.raw_fields:
            value = _read(event, field_name, None)
            if value is None:
                raise LiveCohortValidationError(
                    "required raw field {!r} is missing".format(field_name)
                )
            if field_name in member.numeric_fields:
                if isinstance(value, bool):
                    raise LiveCohortValidationError(
                        "raw field {!r} cannot be boolean".format(field_name)
                    )
                if not isinstance(value, (numbers.Real, Decimal)):
                    raise LiveCohortValidationError(
                        "raw field {!r} must use a supported numeric type".format(field_name)
                    )
                try:
                    number = float(value)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise LiveCohortValidationError(
                        "raw field {!r} must be numeric".format(field_name)
                    ) from exc
                if math.isnan(number):
                    if field_name not in missing_fields:
                        raise LiveCohortValidationError(
                            "raw field {!r} is NaN without declared missing metadata".format(
                                field_name
                            )
                        )
                elif not math.isfinite(number):
                    raise LiveCohortValidationError(
                        "raw field {!r} must be finite".format(field_name)
                    )
                elif field_name in missing_fields:
                    raise LiveCohortValidationError(
                        "declared missing raw field {!r} must contain NaN".format(field_name)
                    )
                raw_values[field_name] = number
            else:
                raw_values[field_name] = _frozen_scalar(value, field_name)
        if any(name not in raw_values for name in missing_fields):
            raise LiveCohortValidationError("declared missing field has no raw value")
        if "volume" not in missing_fields and raw_values["volume"] < 0:
            raise LiveCohortValidationError("volume cannot be negative")
        finite_ohlc = {
            name: raw_values[name]
            for name in ("open", "high", "low", "close")
            if name not in missing_fields
        }
        body_values = [finite_ohlc[name] for name in ("open", "close") if name in finite_ohlc]
        if "high" in finite_ohlc and body_values and finite_ohlc["high"] < max(body_values):
            raise LiveCohortValidationError("high must contain open and close")
        if "low" in finite_ohlc and body_values and finite_ohlc["low"] > min(body_values):
            raise LiveCohortValidationError("low must contain open and close")
        if (
            "low" in finite_ohlc
            and "high" in finite_ohlc
            and finite_ohlc["low"] > finite_ohlc["high"]
        ):
            raise LiveCohortValidationError("low cannot exceed high")
        unspecified_present = object()
        explicit_present = _read(event, "present", unspecified_present)
        if explicit_present is not unspecified_present and type(explicit_present) is not bool:
            raise LiveCohortValidationError("present must be an exact bool when provided")
        present = not missing_fields
        if present and explicit_present is False:
            raise LiveCohortValidationError("present=False requires declared missing fields")
        if not present and explicit_present is not False:
            raise LiveCohortValidationError(
                "a missing-field bar must explicitly declare present=False"
            )
        flags = _read(event, "quality_flags", ()) or ()
        if not isinstance(flags, (list, tuple, set, frozenset)) or any(
            not isinstance(flag, str) or not flag for flag in flags
        ):
            raise LiveCohortValidationError("quality_flags must be immutable non-empty strings")
        if missing_fields:
            if tuple(sorted(flags)) != ("MISSING_FIELDS",):
                raise LiveCohortValidationError(
                    "missing-field bars require quality_flags=('MISSING_FIELDS',)"
                )
        elif set(flags).difference({"LEGACY_SCHEMA"}):
            raise LiveCohortValidationError("GOOD bars cannot carry blocking quality flags")
        if received_monotonic_ns is None:
            received_monotonic_ns = _read(event, "received_monotonic_ns", None)
        if received_monotonic_ns is not None:
            _positive_int(received_monotonic_ns, "received_monotonic_ns")
        evidence = _read(event, "closed_bar_evidence", None)
        source = _read(event, "source", "")
        if source is not None and not isinstance(source, str):
            raise LiveCohortValidationError("event source must be a string")
        return BarEnvelope(
            cohort_id=self.cohort_id,
            calendar_id=self.calendar_id,
            epoch_id=self.epoch_id,
            slot_index=slot_index,
            slot_id=slot.slot_id,
            member_id=member.member_id,
            feed_ref=member.feed_ref,
            instrument=member.instrument,
            source_ref=member.source_ref,
            source_role=source_role,
            connection_generation=generation,
            feed_sequence=sequence,
            bucket_start=slot_start,
            close_time=close_time,
            available_at=available_at,
            trading_day=trading_day,
            session_segment=session_segment,
            timezone_id=member.timezone_id,
            clock_domain_id=member.clock_domain_id,
            bar_id=bar_id,
            complete=complete,
            quality=quality,
            present=present,
            missing_fields=missing_fields,
            raw_values=raw_values,
            quality_flags=tuple(sorted(flags)),
            event_source=source or "",
            received_monotonic_ns=received_monotonic_ns,
            event_ref=event,
            evidence_ref=evidence,
        )

    def _validate_member_sequence(self, member: LiveCohortMember, envelope: BarEnvelope) -> None:
        role = self._last_role[member.member_id]
        if role == "live" and envelope.source_role == "history":
            self._freeze("history_after_live")
            raise LiveCohortFrozenError("history bars cannot follow live bars within an epoch")
        role_key = (member.member_id, envelope.source_role)
        prior_generation = self._generation_by_role.get(role_key)
        if prior_generation is not None and prior_generation != envelope.connection_generation:
            self._freeze("connection_generation_changed")
            raise LiveCohortFrozenError("connection generation changed within a cohort epoch")
        seq_key = (member.member_id, envelope.source_role, envelope.connection_generation)
        prior_sequence = self._last_sequence.get(seq_key)
        if prior_sequence is not None and envelope.feed_sequence <= prior_sequence:
            self._freeze("non_monotone_feed_sequence")
            raise LiveCohortFrozenError("feed sequence must increase within source generation")
        self._generation_by_role[role_key] = envelope.connection_generation
        self._last_sequence[seq_key] = envelope.feed_sequence
        self._last_role[member.member_id] = envelope.source_role

    def _slot_index(self, close_time: _datetime.datetime) -> Optional[int]:
        return self._slot_indices_by_close.get(close_time)

    @staticmethod
    def _data_signature(envelope: BarEnvelope) -> Tuple[Any, ...]:
        missing = set(envelope.missing_fields)
        raw_items = tuple(
            (
                name,
                ("MISSING_NAN", name) if name in missing else value,
            )
            for name, value in sorted(envelope.raw_values.items())
        )
        return (
            envelope.bucket_start,
            envelope.close_time,
            envelope.trading_day,
            envelope.session_segment,
            raw_items,
            envelope.complete,
            envelope.quality,
            envelope.present,
            envelope.missing_fields,
        )

    @classmethod
    def _signature_for(cls, envelope: BarEnvelope) -> _BarSignature:
        return _BarSignature(
            data=cls._data_signature(envelope),
            source_role=envelope.source_role,
            connection_generation=envelope.connection_generation,
            feed_sequence=envelope.feed_sequence,
            bar_id=envelope.bar_id,
        )

    @staticmethod
    def _signature_is_duplicate(prior: _BarSignature, candidate: _BarSignature) -> bool:
        if prior.data != candidate.data:
            return False
        if prior.source_role == candidate.source_role:
            return (
                prior.connection_generation == candidate.connection_generation
                and prior.feed_sequence == candidate.feed_sequence
                and prior.bar_id == candidate.bar_id
            )
        return {prior.source_role, candidate.source_role} == {"history", "live"}

    @classmethod
    def _is_duplicate(cls, prior: BarEnvelope, candidate: BarEnvelope) -> bool:
        return cls._signature_is_duplicate(cls._signature_for(prior), cls._signature_for(candidate))

    def prepare_round(
        self,
        now_monotonic_ns: int,
        *,
        source_time_utc: _datetime.datetime,
    ) -> PrepareResult:
        """Prepare one closed planned slot using explicit UTC and monotonic clocks.

        ``source_time_utc`` is the caller's explicit, provider-independent UTC
        clock mapping for deciding whether the calendar slot is due. It is not
        bar availability evidence or a provider watermark. The monotonic clock
        starts measuring the missing-member wait only after the slot is due.
        """
        with self._lock:
            self._require_open()
            self.seal()
            now = _positive_int(now_monotonic_ns, "now_monotonic_ns")
            source_now = _aware_utc(source_time_utc, "source_time_utc")
            if self._last_prepare_ns is not None and now < self._last_prepare_ns:
                self._freeze("monotonic_clock_regressed")
                raise LiveCohortFrozenError("prepare monotonic clock regressed")
            self._last_prepare_ns = now
            if self._prepared is not None:
                return PrepareResult("READY", self._prepared)
            if self._next_slot_index >= len(self._calendar.slots):
                return PrepareResult("EXHAUSTED", reason="finite_calendar_exhausted")
            slot_index = self._next_slot_index
            slot = self._calendar.slots[slot_index]
            if source_now < slot.close_time and self._wait_started_ns is None:
                return PrepareResult("NOT_DUE", reason="planned_slot_not_closed")
            rows = self._pending.get(slot_index, {})
            missing = tuple(member_id for member_id in self._members if member_id not in rows)
            latest_available_at = (
                max(envelope.available_at for envelope in rows.values()) if not missing else None
            )
            availability_waiting = (
                not missing and latest_available_at is not None and latest_available_at > source_now
            )
            if (
                self._wait_started_ns is not None
                and now - self._wait_started_ns >= self._wait_timeout_ns
            ):
                return self._wait_timeout_result(
                    slot_index, slot, missing=missing, availability_waiting=availability_waiting
                )
            if missing or availability_waiting:
                if self._wait_started_ns is None:
                    self._wait_started_ns = now
                    self._wait_missing_member_ids = missing
                elapsed = now - self._wait_started_ns
                if elapsed >= self._wait_timeout_ns:
                    return self._wait_timeout_result(
                        slot_index, slot, missing=missing, availability_waiting=availability_waiting
                    )
                if availability_waiting:
                    return PrepareResult("WAITING_AVAILABILITY", reason="bar_not_yet_available")
                return PrepareResult(
                    "WAITING", missing_member_ids=missing, reason="cohort_incomplete"
                )
            expected = set(self._members)
            if set(rows) != expected:
                self._freeze("cohort_member_set_mismatch")
                raise LiveCohortFrozenError("prepared member set differs from registered cohort")
            batch_id = "{}:{}:{}:{}:{}".format(
                self.cohort_id, self.calendar_id, self.epoch_id, self._calendar.version, slot_index
            )
            self._prepared = PreparedBarBatch(
                cohort_id=self.cohort_id,
                calendar_id=self.calendar_id,
                calendar_version=self._calendar.version,
                epoch_id=self.epoch_id,
                slot_index=slot_index,
                batch_id=batch_id,
                close_time=slot.close_time,
                envelopes=rows,
            )
            self._delivered.clear()
            self._wait_started_ns = None
            self._wait_missing_member_ids = ()
            return PrepareResult("READY", self._prepared)

    def next_wait_timeout(
        self,
        source_now_utc: _datetime.datetime,
        monotonic_now_ns: int,
    ) -> LiveCohortWait:
        """Return the next wait budget without changing cohort state.

        The UTC clock determines whether the planned slot is due and when a
        complete queued batch becomes available. The monotonic clock bounds a
        missing-member or availability wait only after a due ``prepare_round``
        has started that wait. A caller may invoke this before preparation; in
        that case a due but not-yet-started wait returns zero so preparation can
        start it immediately. The engine applies any independent broker poll
        deadline by taking the minimum with ``timeout_seconds``.
        """
        source_now = _aware_utc(source_now_utc, "source_now_utc")
        now = _positive_int(monotonic_now_ns, "monotonic_now_ns")
        with self._lock:
            if self._frozen_reason is not None:
                return LiveCohortWait("FROZEN", None, self._frozen_reason)
            if not self._sealed:
                raise LiveCohortValidationError(
                    "cohort must be sealed before computing a wait recommendation"
                )
            if self._prepared is not None:
                return LiveCohortWait("READY", 0.0, "batch_prepared")
            if self._next_slot_index >= len(self._calendar.slots):
                return LiveCohortWait("EXHAUSTED", None, "finite_calendar_exhausted")
            if self._last_prepare_ns is not None and now < self._last_prepare_ns:
                return LiveCohortWait("WAITING", 0.0, "monotonic_clock_regressed")

            slot_index = self._next_slot_index
            slot = self._calendar.slots[slot_index]
            if source_now < slot.close_time and self._wait_started_ns is None:
                return LiveCohortWait(
                    "WAITING",
                    max(0.0, (slot.close_time - source_now).total_seconds()),
                    "planned_slot_not_closed",
                )

            rows = self._pending.get(slot_index, {})
            expected_members = set(self._members)
            row_members = set(rows)
            if row_members - expected_members:
                return LiveCohortWait("FROZEN", None, "cohort_member_set_mismatch")
            missing = expected_members - row_members
            latest_available_at = None
            if not missing:
                if row_members != expected_members:
                    return LiveCohortWait("FROZEN", None, "cohort_member_set_mismatch")
                latest_available_at = max(row.available_at for row in rows.values())

            wait_started_ns = self._wait_started_ns
            if wait_started_ns is None:
                if missing:
                    return LiveCohortWait("WAITING", 0.0, "due_wait_not_started")
                if latest_available_at > source_now:
                    return LiveCohortWait("WAITING", 0.0, "due_availability_wait_not_started")
                return LiveCohortWait("READY", 0.0, "complete_batch_available")

            if now < wait_started_ns:
                return LiveCohortWait("WAITING", 0.0, "monotonic_clock_regressed")
            elapsed_ns = now - wait_started_ns
            if elapsed_ns >= self._wait_timeout_ns:
                return LiveCohortWait("WAITING", 0.0, "cohort_wait_deadline_reached")

            remaining_seconds = (self._wait_timeout_ns - elapsed_ns) / 1_000_000_000.0
            if missing:
                return LiveCohortWait("WAITING", remaining_seconds, "cohort_incomplete")
            if latest_available_at > source_now:
                availability_seconds = (latest_available_at - source_now).total_seconds()
                return LiveCohortWait(
                    "WAITING",
                    min(remaining_seconds, max(0.0, availability_seconds)),
                    "bar_not_yet_available",
                )
            return LiveCohortWait("READY", 0.0, "complete_batch_available")

    def _wait_timeout_result(
        self,
        slot_index: int,
        slot: LiveCalendarSlot,
        *,
        missing: Tuple[str, ...],
        availability_waiting: bool,
    ) -> PrepareResult:
        if availability_waiting or not self._wait_missing_member_ids:
            self._freeze("bar_availability_deadline_exceeded")
            return PrepareResult(
                "AVAILABILITY_TIMEOUT", reason="bar_availability_deadline_exceeded"
            )
        # Keep the existing bounded-wait rule for a row that arrives after the
        # missing-member deadline, while basing an active gap on the members
        # still absent at this check. A complete but not-yet-available batch is
        # an availability timeout, even if the first wait began with a gap.
        gap_missing = missing or self._wait_missing_member_ids
        gap = LiveCohortGap(
            cohort_id=self.cohort_id,
            calendar_id=self.calendar_id,
            epoch_id=self.epoch_id,
            slot_index=slot_index,
            slot_id=slot.slot_id,
            close_time=slot.close_time,
            missing_member_ids=gap_missing,
            first_wait_monotonic_ns=self._wait_started_ns,
            deadline_monotonic_ns=self._wait_started_ns + self._wait_timeout_ns,
            reason="planned_slot_incomplete",
        )
        self._gaps.append(gap)
        self._freeze("planned_gap_requires_rebuild")
        return PrepareResult(
            "GAP", missing_member_ids=gap_missing, reason="planned_gap_requires_rebuild"
        )

    def prepared_envelope(self, feed_ref: Any) -> Optional[BarEnvelope]:
        """Return this feed's immutable envelope unless it already delivered."""
        with self._lock:
            if self._prepared is None:
                return None
            member = self.member_for_feed(feed_ref)
            if member is None or member.member_id in self._delivered:
                return None
            return self._prepared.envelopes.get(member.member_id)

    def preflight_delivery(self, feed_ref: Any, envelope: BarEnvelope) -> Mapping[str, Any]:
        """Recheck exact member/envelope/raw schema before any feed line write."""
        with self._lock:
            self._require_open()
            member = self.member_for_feed(feed_ref)
            if member is None or self._prepared is None:
                raise LiveCohortValidationError("feed has no prepared cohort envelope")
            if self._prepared.envelopes.get(member.member_id) is not envelope:
                raise LiveCohortValidationError(
                    "delivery envelope is not the exact prepared object"
                )
            if member.member_id in self._delivered:
                raise LiveCohortValidationError("feed already delivered this prepared batch")
            if envelope.feed_ref is not feed_ref or envelope.member_id != member.member_id:
                raise LiveCohortValidationError("prepared envelope feed identity changed")
            if not self._envelope_presence_is_valid(member, envelope):
                self._freeze("prepared_envelope_quality_changed")
                raise LiveCohortFrozenError(
                    "prepared envelope lost its validated present/missing contract"
                )
            if not set(member.line_fields).issubset(envelope.raw_values):
                self._freeze("prepared_raw_schema_changed")
                raise LiveCohortFrozenError("prepared envelope lacks a declared feed line")
            return MappingProxyType(dict(envelope.raw_values))

    @staticmethod
    def _envelope_presence_is_valid(member: LiveCohortMember, envelope: BarEnvelope) -> bool:
        """Check that a sealed row's gap marker agrees with its validated raw values."""
        missing = envelope.missing_fields
        if (
            type(missing) is not tuple
            or tuple(sorted(missing)) != missing
            or len(missing) != len(set(missing))
            or not set(missing).issubset(set(member.numeric_fields))
            or set(envelope.raw_values) != set(member.raw_fields)
            or envelope.complete is not True
        ):
            return False
        if missing:
            if (
                envelope.quality != "MISSING"
                or envelope.present is not False
                or envelope.quality_flags != ("MISSING_FIELDS",)
            ):
                return False
        elif (
            envelope.quality != "GOOD"
            or envelope.present is not True
            or set(envelope.quality_flags).difference({"LEGACY_SCHEMA"})
        ):
            return False
        for name in member.numeric_fields:
            value = envelope.raw_values.get(name)
            if isinstance(value, bool) or not isinstance(value, (numbers.Real, Decimal)):
                return False
            number = float(value)
            if name in missing:
                if not math.isnan(number):
                    return False
            elif not math.isfinite(number):
                return False
        if any(envelope.raw_values.get(name) is None for name in member.raw_fields):
            return False
        return True

    def record_delivery(
        self,
        feed_ref: Any,
        envelope: BarEnvelope,
        *,
        delivered_close_time: _datetime.datetime,
    ) -> LiveDeliveryReceipt:
        """Record one successful normal feed line advance after its write."""
        with self._lock:
            self._require_open()
            raw_values = self.preflight_delivery(feed_ref, envelope)
            close_time = _aware_utc(delivered_close_time, "delivered_close_time")
            if close_time != envelope.close_time:
                self._freeze("line_close_time_mismatch")
                raise LiveCohortFrozenError("feed line datetime differs from prepared close_time")
            member = self.member_for_feed(feed_ref)
            receipt = LiveDeliveryReceipt(
                cohort_id=self.cohort_id,
                calendar_id=self.calendar_id,
                epoch_id=envelope.epoch_id,
                batch_id=self._prepared.batch_id,
                slot_index=envelope.slot_index,
                member_id=member.member_id,
                feed_ref=feed_ref,
                source_ref=member.source_ref,
                envelope=envelope,
                feed_sequence=envelope.feed_sequence,
                close_time=envelope.close_time,
                available_at=envelope.available_at,
                source_role=envelope.source_role,
                complete=envelope.complete,
                quality=envelope.quality,
                present=envelope.present,
                missing_fields=envelope.missing_fields,
                raw_values=raw_values,
            )
            self._delivered[member.member_id] = receipt
            if len(self._delivered) == len(self._members):
                self._publish_complete_batch()
            return receipt

    def record_delivery_batch(
        self,
        deliveries: Tuple[Tuple[Any, BarEnvelope, _datetime.datetime], ...],
    ) -> LiveCohortBatch:
        """Atomically publish receipts after every member's lines have advanced.

        Each item is ``(exact_feed, exact_prepared_envelope, line_close_time)``.
        Validation and receipt construction finish before any cohort state is
        changed. The bounded undo log covers the per-member window heads and
        the at-most-one-window of signature keys evicted by this slot; it never
        copies the full retained history on each batch.
        """

        with self._lock:
            self._require_open()
            prepared = self._prepared
            if prepared is None:
                raise LiveCohortValidationError("no prepared cohort batch to deliver")
            if self._delivered:
                raise LiveCohortValidationError(
                    "batch delivery cannot be mixed with individual delivery receipts"
                )
            if type(deliveries) not in (tuple, list) or len(deliveries) != len(self._members):
                raise LiveCohortValidationError(
                    "batch delivery must contain every registered member exactly once"
                )
            pending_rows = self._pending.get(prepared.slot_index)
            if (
                pending_rows is None
                or set(pending_rows) != set(self._members)
                or set(prepared.envelopes) != set(self._members)
                or any(
                    pending_rows.get(member_id) is not prepared.envelopes.get(member_id)
                    for member_id in self._members
                )
            ):
                raise LiveCohortValidationError("prepared slot contents changed before delivery")

            receipts: Dict[str, LiveDeliveryReceipt] = {}
            for item in deliveries:
                if type(item) is not tuple or len(item) != 3:
                    raise LiveCohortValidationError(
                        "each batch delivery must be an exact three-item tuple"
                    )
                feed_ref, envelope, delivered_close_time = item
                member = self.member_for_feed(feed_ref)
                if member is None:
                    raise LiveCohortValidationError(
                        "batch delivery feed is not an exact registered member"
                    )
                member_id = member.member_id
                if member_id in receipts:
                    raise LiveCohortValidationError("batch delivery repeats a cohort member")
                if prepared.envelopes.get(member_id) is not envelope:
                    raise LiveCohortValidationError(
                        "delivery envelope is not the exact prepared object"
                    )
                if envelope.feed_ref is not feed_ref or envelope.member_id != member_id:
                    raise LiveCohortValidationError("prepared envelope feed identity changed")
                if (
                    envelope.epoch_id != prepared.epoch_id
                    or envelope.slot_index != prepared.slot_index
                    or envelope.close_time != prepared.close_time
                ):
                    raise LiveCohortValidationError("prepared envelope slot identity changed")
                if not self._envelope_presence_is_valid(member, envelope):
                    raise LiveCohortValidationError(
                        "prepared envelope has inconsistent present/missing metadata"
                    )
                if not set(member.line_fields).issubset(envelope.raw_values):
                    raise LiveCohortValidationError("prepared envelope lacks a declared feed line")
                close_time = _aware_utc(delivered_close_time, "delivered_close_time")
                if close_time != envelope.close_time or close_time != prepared.close_time:
                    raise LiveCohortValidationError(
                        "feed line datetime differs from prepared close_time"
                    )
                receipts[member_id] = LiveDeliveryReceipt(
                    cohort_id=self.cohort_id,
                    calendar_id=self.calendar_id,
                    epoch_id=envelope.epoch_id,
                    batch_id=prepared.batch_id,
                    slot_index=envelope.slot_index,
                    member_id=member_id,
                    feed_ref=feed_ref,
                    source_ref=member.source_ref,
                    envelope=envelope,
                    feed_sequence=envelope.feed_sequence,
                    close_time=envelope.close_time,
                    available_at=envelope.available_at,
                    source_role=envelope.source_role,
                    complete=envelope.complete,
                    quality=envelope.quality,
                    present=envelope.present,
                    missing_fields=envelope.missing_fields,
                    raw_values=envelope.raw_values,
                )
            if set(receipts) != set(self._members):
                raise LiveCohortValidationError(
                    "batch delivery does not cover every registered member"
                )

            history_updates: Dict[str, _datetime.datetime] = {}
            first_live_updates: Dict[str, LiveDeliveryReceipt] = {}
            cutovers: Dict[str, LiveEpochCutover] = {}
            for member_id, receipt in receipts.items():
                if receipt.source_role == "history":
                    history_updates[member_id] = receipt.close_time
                elif member_id not in self._first_live_receipt:
                    first_live_updates[member_id] = receipt
                first_live = first_live_updates.get(
                    member_id, self._first_live_receipt.get(member_id)
                )
                if first_live is not None:
                    history_last = history_updates.get(
                        member_id, self._history_last_close.get(member_id)
                    )
                    cutovers[member_id] = LiveEpochCutover(
                        cohort_id=self.cohort_id,
                        member_id=member_id,
                        epoch_id=self.epoch_id,
                        history_last_close_time=history_last,
                        first_live_close_time=first_live.close_time,
                        transition_kind=(
                            "history_to_live" if history_last is not None else "live_cold_start"
                        ),
                        crossed_live=True,
                        first_live_receipt=first_live,
                    )

            available_at = max(receipt.available_at for receipt in receipts.values())
            batch = LiveCohortBatch(
                batch_id=prepared.batch_id,
                cohort_id=self.cohort_id,
                calendar_id=self.calendar_id,
                calendar_version=self._calendar.version,
                epoch_id=self.epoch_id,
                slot_index=prepared.slot_index,
                close_time=prepared.close_time,
                available_at=available_at,
                members=receipts,
                cutovers=cutovers,
            )
            signature_updates = tuple(
                (
                    member_id,
                    self._signature_for(receipt.envelope),
                )
                for member_id, receipt in receipts.items()
            )
            signature_keys = tuple(
                (prepared.slot_index, member_id) for member_id, _ in signature_updates
            )
            if any(key in self._recent_signatures for key in signature_keys):
                raise LiveCohortValidationError("prepared slot signature already exists")

            window_undo = {}
            for member_id, receipt in receipts.items():
                window = self._window_receipts.get(member_id)
                if window is None:
                    raise LiveCohortValidationError("member window is not initialized")
                evicted = window[0] if len(window) == window.maxlen else None
                window_undo[member_id] = (receipt, evicted)

            signature_limit = self.max_window_bars * max(len(self._members), 1)
            signature_evictions_expected = max(
                0, len(self._recent_signature_order) + len(signature_updates) - signature_limit
            )
            signature_evicted_prefix = tuple(
                itertools.islice(self._recent_signature_order, signature_evictions_expected)
            )
            if len(signature_evicted_prefix) != signature_evictions_expected:
                raise LiveCohortValidationError("signature history changed before publication")
            signature_evicted_values = {
                key: self._recent_signatures[key] for key in signature_evicted_prefix
            }

            missing = object()
            old_history = {
                member_id: self._history_last_close.get(member_id, missing)
                for member_id in history_updates
            }
            old_first_live = {
                member_id: self._first_live_receipt.get(member_id, missing)
                for member_id in first_live_updates
            }
            old_current_batch = self._current_batch
            old_prepared = self._prepared
            old_delivered = self._delivered
            old_next_slot_index = self._next_slot_index
            old_wait_started_ns = self._wait_started_ns
            old_wait_missing_member_ids = self._wait_missing_member_ids
            # Pending slots are explicitly bounded (at most _MAX_PENDING_SLOTS).
            # Preserve their insertion order if a publication step is interrupted.
            old_pending_items = tuple(self._pending.items())
            old_signature_order_length = len(self._recent_signature_order)

            try:
                self._history_last_close.update(history_updates)
                self._first_live_receipt.update(first_live_updates)
                for member_id, (receipt, _evicted) in window_undo.items():
                    self._window_receipts[member_id].append(receipt)
                for member_id, signature in signature_updates:
                    self._remember_signature(prepared.slot_index, member_id, signature)

                self._pending.pop(prepared.slot_index)
                self._next_slot_index = prepared.slot_index + 1
                self._prepared = None
                self._delivered = {}
                self._wait_started_ns = None
                self._wait_missing_member_ids = ()
                # This is the sole public commit point for the completed batch.
                self._current_batch = batch
            except BaseException:
                self._current_batch = old_current_batch
                self._prepared = old_prepared
                self._delivered = old_delivered
                self._next_slot_index = old_next_slot_index
                self._wait_started_ns = old_wait_started_ns
                self._wait_missing_member_ids = old_wait_missing_member_ids
                self._pending.clear()
                self._pending.update(old_pending_items)
                for member_id, prior in old_history.items():
                    if prior is missing:
                        self._history_last_close.pop(member_id, None)
                    else:
                        self._history_last_close[member_id] = prior
                for member_id, prior in old_first_live.items():
                    if prior is missing:
                        self._first_live_receipt.pop(member_id, None)
                    else:
                        self._first_live_receipt[member_id] = prior
                for member_id, (receipt, evicted) in window_undo.items():
                    window = self._window_receipts[member_id]
                    if window and window[-1] is receipt:
                        window.pop()
                        if evicted is not None:
                            window.appendleft(evicted)
                added_key_set = set(signature_keys)
                while (
                    self._recent_signature_order
                    and self._recent_signature_order[-1] in added_key_set
                ):
                    self._recent_signature_order.pop()
                for key in signature_keys:
                    self._recent_signatures.pop(key, None)
                evicted_count = old_signature_order_length - len(self._recent_signature_order)
                for key in reversed(signature_evicted_prefix[:evicted_count]):
                    self._recent_signature_order.appendleft(key)
                    self._recent_signatures[key] = signature_evicted_values[key]
                raise

            return batch

    def _publish_complete_batch(self) -> None:
        prepared = self._prepared
        if prepared is None or set(self._delivered) != set(self._members):
            self._freeze("incomplete_batch_publish")
            raise LiveCohortFrozenError("cannot publish a partial cohort batch")
        receipts = dict(self._delivered)
        cutovers = {}
        for member_id, receipt in receipts.items():
            if receipt.source_role == "history":
                self._history_last_close[member_id] = receipt.close_time
            elif member_id not in self._first_live_receipt:
                self._first_live_receipt[member_id] = receipt
            cutover = self._cutover_for_member(member_id)
            if cutover is not None:
                cutovers[member_id] = cutover
            self._window_receipts[member_id].append(receipt)
            self._remember_signature(
                receipt.slot_index, member_id, self._signature_for(receipt.envelope)
            )
        available_at = max(receipt.available_at for receipt in receipts.values())
        self._current_batch = LiveCohortBatch(
            batch_id=prepared.batch_id,
            cohort_id=self.cohort_id,
            calendar_id=self.calendar_id,
            calendar_version=self._calendar.version,
            epoch_id=self.epoch_id,
            slot_index=prepared.slot_index,
            close_time=prepared.close_time,
            available_at=available_at,
            members=receipts,
            cutovers=cutovers,
        )
        self._pending.pop(prepared.slot_index, None)
        self._next_slot_index += 1
        self._prepared = None
        self._delivered.clear()
        self._wait_started_ns = None

    def _remember_signature(
        self, slot_index: int, member_id: str, signature: _BarSignature
    ) -> None:
        key = (slot_index, member_id)
        if key in self._recent_signatures:
            self._recent_signatures[key] = signature
            return
        self._recent_signatures[key] = signature
        self._recent_signature_order.append(key)
        limit = self.max_window_bars * max(len(self._members), 1)
        while len(self._recent_signature_order) > limit:
            expired = self._recent_signature_order.popleft()
            self._recent_signatures.pop(expired, None)

    def current_delivery(self, feed_ref: Any) -> Optional[LiveDeliveryReceipt]:
        batch = self._current_batch
        if batch is None:
            return None
        return batch.receipt_for_feed(feed_ref)

    def delivered_for_feed(self, feed_ref: Any) -> Optional[LiveDeliveryReceipt]:
        return self.current_delivery(feed_ref)

    def current_batch(self) -> Optional[LiveCohortBatch]:
        return self._current_batch

    def freeze_unsupported_gap_semantics(self, batch: LiveCohortBatch) -> str:
        """Freeze only the exact current complete batch carrying a validated gap.

        ``LiveFactorSet`` uses this when a non-registry factor graph has no
        accepted NaN/presence contract. The caller cannot turn a healthy batch
        into a gap by passing a boolean or an alternate receipt projection.
        """
        with self._lock:
            if batch is not self._current_batch or batch is None:
                raise LiveCohortValidationError(
                    "gap-semantic freeze requires the exact current cohort batch"
                )
            if batch.status != "COMPLETE" or batch.cohort_id != self.cohort_id:
                raise LiveCohortValidationError("gap-semantic freeze requires a complete batch")
            if not any(
                receipt.present is False
                and receipt.quality == "MISSING"
                and bool(receipt.missing_fields)
                for receipt in batch.members.values()
            ):
                raise LiveCohortValidationError(
                    "gap-semantic freeze requires a validated missing-field receipt"
                )
            self._freeze("unsupported_factor_gap_semantics")
            return self._frozen_reason or "unsupported_factor_gap_semantics"

    def is_final_batch(self, batch: Any) -> bool:
        """Return whether this exact current batch is the finite epoch's last slot."""
        with self._lock:
            return bool(
                batch is not None
                and batch is self._current_batch
                and batch.cohort_id == self.cohort_id
                and batch.calendar_id == self.calendar_id
                and batch.calendar_version == self.calendar_version
                and batch.epoch_id == self.epoch_id
                and batch.slot_index == len(self._calendar.slots) - 1
                and batch.status == "COMPLETE"
            )

    def complete_window_bars(
        self,
        feed_ref: Any,
        line_names: Iterable[str],
        count: int,
    ) -> Tuple[LiveDeliveryReceipt, ...]:
        """Return only a contiguous, fully validated delivered window.

        The cohort retains at most ``max_window_bars`` receipts per member.
        Missing planned slots are never compressed into a longer window.
        """
        with self._lock:
            self._require_open()
            member = self.member_for_feed(feed_ref)
            if member is None:
                raise LiveCohortValidationError("window feed is not an exact registered member")
            names = tuple(line_names)
            if not names or any(name not in member.line_fields for name in names):
                raise LiveCohortValidationError("window fields must be declared member line fields")
            _positive_int(count, "count")
            if count > self.max_window_bars:
                raise LiveCohortCapacityError("requested window exceeds bounded receipt history")
            rows = tuple(self._window_receipts[member.member_id])
            if len(rows) < count:
                return ()
            window = rows[-count:]
            if any(
                not row.complete
                or row.quality != "GOOD"
                or not row.present
                or any(name not in row.raw_values for name in names)
                for row in window
            ):
                return ()
            if any(
                right.slot_index != left.slot_index + 1 for left, right in zip(window, window[1:])
            ):
                return ()
            if any(row.epoch_id != window[0].epoch_id for row in window):
                return ()
            return window

    def epoch_cutover(self, feed_ref: Any) -> Optional[LiveEpochCutover]:
        """Return a cutover fact only after the first live bar was delivered."""
        member = self.member_for_feed(feed_ref)
        if member is None:
            return None
        return self._cutover_for_member(member.member_id)

    def _cutover_for_member(self, member_id: str) -> Optional[LiveEpochCutover]:
        first_live = self._first_live_receipt.get(member_id)
        if first_live is None:
            return None
        history_last = self._history_last_close.get(member_id)
        return LiveEpochCutover(
            cohort_id=self.cohort_id,
            member_id=member_id,
            epoch_id=self.epoch_id,
            history_last_close_time=history_last,
            first_live_close_time=first_live.close_time,
            transition_kind="history_to_live" if history_last is not None else "live_cold_start",
            crossed_live=True,
            first_live_receipt=first_live,
        )

    def _require_open(self) -> None:
        if self._frozen_reason is not None:
            raise LiveCohortFrozenError("cohort is frozen: {}".format(self._frozen_reason))

    def _freeze(self, reason: str) -> None:
        if self._frozen_reason is None:
            self._frozen_reason = reason
