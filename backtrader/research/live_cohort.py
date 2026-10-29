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
from dataclasses import dataclass, field, replace
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Deque, Dict, Iterable, Mapping, Optional, Tuple


_UTC = _datetime.timezone.utc
_COHORT_FIELD_MISSING = object()
_REQUIRED_OHLCV = ("open", "high", "low", "close", "volume")
_DEFAULT_NUMERIC_FIELDS = frozenset(_REQUIRED_OHLCV)
# Finite calendars may include both factor warm-up and evaluation history.
# Keep a hard ceiling above 100k bars while still making exhaustion explicit;
# this does not imply a rolling or infinite future calendar.
_MAX_CALENDAR_SLOTS = 200_000
_MAX_COHORT_MEMBERS = 512
_MAX_PENDING_SLOTS = 64
_MAX_WINDOW_BARS = 4096
_MAX_RESTART_GAP_SLOTS = _MAX_CALENDAR_SLOTS
_RESTART_GAP_FACTORY_TOKEN = object()
_SOURCE_ORIGIN_PARTITION_SCHEMA = "backtrader.execution_source_origin_partition.v1"
_SOURCE_ORIGIN_PARTITION_FIELDS = frozenset(
    {
        "schema",
        "cohort_id",
        "epoch_id",
        "member_id",
        "source_ref",
        "source_role",
        "connection_generation",
    }
)
_VERIFIED_HISTORY_PROOF_EVENT_KEY = "_verified_saved_history_origin_proof"
_SAVED_HISTORY_ANCHOR_EVENT_KEY = "_saved_history_tape_anchor"
_SAVED_HISTORY_RECORD_SOURCE_ROLE_EVENT_KEY = "_saved_history_record_source_role"
_VERIFIED_HISTORY_ANCHOR_FIELDS = frozenset(
    {
        "decision_id",
        "receipt_sha256",
        "tape_file_id",
        "tape_record_id",
        "tape_record_index",
        "batch_id",
        "source_cohort_id",
        "source_epoch_id",
        "calendar_id",
        "calendar_version",
        "calendar_fingerprint",
        "slot_index",
        "slot_id",
        "close_time",
        "member_receipt",
        "origin_partition",
    }
)


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


def _trading_day_key(value: Any) -> Any:
    """Canonicalize the compact and ISO-8601 TradingDay spellings.

    Source receipts and saved tapes keep an ISO date while the exchange
    calendar and CTP wire form use YYYYMMDD. Both denote the same day; compare
    the canonical value and leave every other identity field exact.
    """
    if type(value) is str:
        return value.replace("-", "")
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


def _origin_partition_values(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _SOURCE_ORIGIN_PARTITION_FIELDS:
        raise LiveCohortValidationError("source origin partition schema is invalid")
    generation = value["connection_generation"]
    if (
        value["schema"] != _SOURCE_ORIGIN_PARTITION_SCHEMA
        or type(value["epoch_id"]) is not int
        or value["epoch_id"] < 1
        or type(value["source_role"]) is not str
        or value["source_role"] not in ("history", "live")
        or type(generation) not in (str, int)
        or (type(generation) is str and (not generation or len(generation) > 256))
        or (type(generation) is int and generation <= 0)
    ):
        raise LiveCohortValidationError("source origin partition schema is invalid")
    for name, limit in (("cohort_id", 512), ("member_id", 256), ("source_ref", 2048)):
        text = value[name]
        if type(text) is not str or not text or text != text.strip() or len(text) > limit:
            raise LiveCohortValidationError("source origin partition identity is invalid")
    return MappingProxyType({name: value[name] for name in _SOURCE_ORIGIN_PARTITION_FIELDS})


def _origin_partition_identity(value: Mapping[str, Any]) -> Tuple[Any, ...]:
    return tuple(
        value[name]
        for name in (
            "cohort_id",
            "epoch_id",
            "member_id",
            "source_ref",
            "source_role",
            "connection_generation",
        )
    )


def _origin_partition_follows(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    if _origin_partition_identity(previous) == _origin_partition_identity(current):
        return True
    if current["epoch_id"] > previous["epoch_id"]:
        return current["cohort_id"] != previous["cohort_id"]
    return bool(
        current["epoch_id"] == previous["epoch_id"]
        and current["cohort_id"] == previous["cohort_id"]
        and current["member_id"] == previous["member_id"]
        and current["source_ref"] == previous["source_ref"]
        and previous["source_role"] == "history"
        and current["source_role"] == "live"
    )


def _proof_scalar(value: Any, name: str) -> Any:
    """Encode one bounded source value for the transient history proof digest."""
    if isinstance(value, _datetime.datetime):
        return {"datetime_utc": _aware_utc(value, name).isoformat().replace("+00:00", "Z")}
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LiveCohortValidationError("{} must be finite for history proof".format(name))
        return {"float_hex": value.hex()}
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if type(value) in (tuple, list):
        return [_proof_scalar(item, name) for item in value]
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise LiveCohortValidationError("{} keys must be text for history proof".format(name))
        return {key: _proof_scalar(value[key], name) for key in sorted(value)}
    raise LiveCohortValidationError("{} has an unsupported history proof value".format(name))


def _saved_history_event_sha256(event: Any, member: "LiveCohortMember", source_role: str) -> str:
    """Commit the normalized source facts that a saved-history event can deliver."""
    names = (
        "instrument",
        "symbol",
        "exchange",
        "timestamp",
        "datetime",
        "bucket_start",
        "bucket_end",
        "available_at",
        "trading_day",
        "session_segment",
        "timezone_id",
        "clock_domain_id",
        "connection_generation",
        "bar_sequence",
        "bar_id",
        "source_ref",
        "origin_partition",
        "present",
        "complete",
        "quality",
        "quality_flags",
        "missing_fields",
        "source",
        "rules_hash",
        "received_monotonic_ns",
    ) + tuple(member.raw_fields)
    payload = {
        "member_id": member.member_id,
        "source_ref": member.source_ref,
        "source_role": source_role,
        "clock_domain_id": member.clock_domain_id,
        "timezone_id": member.timezone_id,
        "session_semantics": member.session_semantics,
        "raw_fields": tuple(member.raw_fields),
        "event": {
            name: _proof_scalar(_read(event, name, None), name) for name in names
        },
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class _VerifiedSavedHistoryJournalAnchor:
    """One bounded journal receipt row already matched to a tape row by the runner.

    This is transient in-process evidence.  It is not serialized into a tape and
    does not authenticate a caller running with the same Python privileges.
    """

    facts: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.facts, Mapping) or set(self.facts) != _VERIFIED_HISTORY_ANCHOR_FIELDS:
            raise LiveCohortValidationError("verified saved-history anchor shape is invalid")
        values = dict(self.facts)
        for name in (
            "decision_id",
            "receipt_sha256",
            "tape_file_id",
            "tape_record_id",
            "batch_id",
            "source_cohort_id",
            "calendar_id",
            "calendar_version",
            "calendar_fingerprint",
            "slot_id",
        ):
            _nonempty_text(values[name], "verified anchor " + name)
        if (
            len(values["receipt_sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in values["receipt_sha256"])
            or len(values["calendar_fingerprint"]) != 64
            or any(char not in "0123456789abcdef" for char in values["calendar_fingerprint"])
            or type(values["source_epoch_id"]) is not int
            or values["source_epoch_id"] < 1
            or type(values["slot_index"]) is not int
            or values["slot_index"] < 0
            or type(values["tape_record_index"]) is not int
            or values["tape_record_index"] < 1
            or not isinstance(values["member_receipt"], Mapping)
            or (
                values["origin_partition"] is not None
                and not isinstance(values["origin_partition"], Mapping)
            )
        ):
            raise LiveCohortValidationError("verified saved-history anchor identity is invalid")
        values["close_time"] = _aware_utc(values["close_time"], "verified anchor close_time")
        member_receipt = dict(values["member_receipt"])
        if member_receipt.get("origin_partition") is not None:
            member_receipt["origin_partition"] = _origin_partition_values(
                member_receipt["origin_partition"]
            )
        for name in ("missing_fields", "quality_flags"):
            if name in member_receipt:
                member_receipt[name] = tuple(member_receipt[name])
        values["member_receipt"] = MappingProxyType(member_receipt)
        if values["origin_partition"] is not None:
            values["origin_partition"] = _origin_partition_values(values["origin_partition"])
        object.__setattr__(self, "facts", MappingProxyType(values))


@dataclass(frozen=True)
class _VerifiedSavedHistoryOriginProof:
    """Exact, transient authorization to merge one journal-anchored old origin."""

    owner_token: Any = field(compare=False, repr=False)
    member_identity: int
    feed_identity: int
    receiver_cohort_id: str
    receiver_epoch_id: int
    receiver_calendar_id: str
    receiver_calendar_version: str
    receiver_calendar_fingerprint: str
    origin_identity: Tuple[Any, ...]
    source_role: str
    generation: Any
    feed_sequence: int
    bar_id: str
    slot_index: int
    slot_id: str
    close_time: _datetime.datetime
    bucket_start: _datetime.datetime
    available_at: _datetime.datetime
    trading_day: str
    session_segment: str
    content_sha256: str
    tape_anchor_identity: Tuple[Any, ...]
    tape_source_role: str
    decision_id: str
    receipt_sha256: str


def _make_verified_saved_history_journal_anchor(**facts: Any) -> _VerifiedSavedHistoryJournalAnchor:
    """Build a transient anchor only after the runner has checked its full tail."""
    return _VerifiedSavedHistoryJournalAnchor(facts)


def _history_receipt_time(value: Any) -> str:
    if isinstance(value, str):
        parse_text = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            value = _datetime.datetime.fromisoformat(parse_text)
        except ValueError as error:
            raise LiveCohortValidationError("saved history receipt time is invalid") from error
    return _aware_utc(value, "saved history receipt time").isoformat().replace("+00:00", "Z")


def _verified_history_anchor_identity(facts: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        facts["tape_file_id"],
        facts["tape_record_id"],
        facts["tape_record_index"],
        facts["batch_id"],
        facts["source_cohort_id"],
        facts["source_epoch_id"],
        facts["calendar_id"],
        facts["calendar_version"],
        facts["calendar_fingerprint"],
        facts["slot_index"],
        facts["slot_id"],
        facts["close_time"],
    )


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
class LiveFieldContract:
    """Adapter-declared provenance identity and unit for one feed line."""

    source_ref: str
    unit: str
    delivery_mode: str
    validity_seconds: Optional[float] = None

    def __post_init__(self) -> None:
        _nonempty_text(self.source_ref, "field source_ref")
        _nonempty_text(self.unit, "field unit")
        if self.delivery_mode not in ("co_delivered", "independent"):
            raise LiveCohortValidationError(
                "field delivery_mode must be co_delivered or independent"
            )
        if self.delivery_mode == "co_delivered":
            if type(self.validity_seconds) not in (int, float):
                raise LiveCohortValidationError(
                    "co-delivered field contracts require finite validity_seconds"
                )
            validity = float(self.validity_seconds)
            if not math.isfinite(validity) or validity <= 0.0:
                raise LiveCohortValidationError(
                    "co-delivered validity_seconds must be finite and positive"
                )
            object.__setattr__(self, "validity_seconds", validity)
        elif self.validity_seconds is not None:
            raise LiveCohortValidationError(
                "independent field validity belongs to each observation"
            )


@dataclass(frozen=True)
class LiveFieldObservation:
    """Immutable point-in-time facts supplied by the field's actual adapter."""

    source_ref: str
    unit: str
    effective_at: _datetime.datetime
    available_at: _datetime.datetime
    revision: Any
    valid_until: _datetime.datetime

    def __post_init__(self) -> None:
        _nonempty_text(self.source_ref, "field observation source_ref")
        _nonempty_text(self.unit, "field observation unit")
        object.__setattr__(
            self, "effective_at", _aware_utc(self.effective_at, "field effective_at")
        )
        object.__setattr__(
            self, "available_at", _aware_utc(self.available_at, "field available_at")
        )
        object.__setattr__(self, "valid_until", _aware_utc(self.valid_until, "field valid_until"))
        revision = _frozen_scalar(self.revision, "field revision")
        if (
            revision is None
            or isinstance(revision, bool)
            or revision == ""
            or revision == b""
            or revision == 0
            or (isinstance(revision, tuple) and not revision)
        ):
            raise LiveCohortValidationError("field revision must be an explicit non-empty value")
        object.__setattr__(self, "revision", revision)
        if self.available_at < self.effective_at:
            raise LiveCohortValidationError("field available_at cannot precede effective_at")
        if self.valid_until < self.effective_at:
            raise LiveCohortValidationError("field valid_until cannot precede effective_at")


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
class LiveCohortJournalMemberHighWater:
    """One member's exact old-run event identity at a durable journal cursor.

    ``source_role`` preserves the role stored in the old journal. A replay of
    that high-water event in the new epoch must independently use ``history``.
    """

    member_id: str
    source_ref: str
    source_role: str
    connection_generation: Any
    feed_sequence: int
    bar_id: str
    close_time: _datetime.datetime
    trading_day: str
    session_segment: str

    def __post_init__(self) -> None:
        for name in ("member_id", "source_ref", "bar_id", "trading_day", "session_segment"):
            _nonempty_text(getattr(self, name), name)
        if type(self.source_role) is not str or self.source_role not in ("history", "live"):
            raise LiveCohortValidationError(
                "high-water source_role must preserve its original history/live role"
            )
        generation = self.connection_generation
        if (
            isinstance(generation, bool)
            or not isinstance(generation, (str, int))
            or generation in ("", 0)
        ):
            raise LiveCohortValidationError("high-water connection generation must be explicit")
        _positive_int(self.feed_sequence, "high-water feed_sequence")
        object.__setattr__(self, "close_time", _aware_utc(self.close_time, "close_time"))


@dataclass(frozen=True)
class LiveCohortJournalHighWater:
    """Bounded identity for the prior journal's last complete history batch."""

    cohort_id: str
    calendar_id: str
    calendar_version: str
    calendar_fingerprint: str
    epoch_id: int
    slot_index: int
    slot_id: str
    close_time: _datetime.datetime
    batch_id: str
    members: Mapping[str, LiveCohortJournalMemberHighWater]

    def __post_init__(self) -> None:
        for name in ("cohort_id", "calendar_id", "calendar_version", "slot_id", "batch_id"):
            _nonempty_text(getattr(self, name), name)
        _positive_int(self.epoch_id, "high-water epoch_id")
        if type(self.slot_index) is not int or self.slot_index < 0:
            raise LiveCohortValidationError("high-water slot_index must be a non-negative integer")
        fingerprint = self.calendar_fingerprint
        if (
            type(fingerprint) is not str
            or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise LiveCohortValidationError("high-water calendar fingerprint must be SHA-256")
        object.__setattr__(self, "close_time", _aware_utc(self.close_time, "close_time"))
        if not isinstance(self.members, Mapping) or not self.members:
            raise LiveCohortValidationError("high-water members must be a non-empty mapping")
        if len(self.members) > _MAX_COHORT_MEMBERS:
            raise LiveCohortCapacityError("high-water member limit exceeded")
        members = {}
        for member_id, member in self.members.items():
            _nonempty_text(member_id, "high-water member id")
            if type(member) is not LiveCohortJournalMemberHighWater:
                raise LiveCohortValidationError(
                    "high-water members must be LiveCohortJournalMemberHighWater values"
                )
            if member.member_id != member_id or member.close_time != self.close_time:
                raise LiveCohortValidationError("high-water member identity differs from its batch")
            members[member_id] = member
        expected_batch_id = "{}:{}:{}:{}:{}".format(
            self.cohort_id,
            self.calendar_id,
            self.epoch_id,
            self.calendar_version,
            self.slot_index,
        )
        if self.batch_id != expected_batch_id:
            raise LiveCohortValidationError("high-water batch_id is not its canonical slot identity")
        object.__setattr__(self, "members", MappingProxyType(members))


@dataclass(frozen=True)
class LiveCohortRestartGap:
    """Immutable proof of the exact planned slots omitted at process restart."""

    full_original_calendar_fingerprint: str
    original_scope_first_slot_id: str
    original_scope_last_slot_id: str
    original_scope_slot_count: int
    journal_highwater: LiveCohortJournalHighWater
    history_highwater_original_slot_index: int
    omitted_start_original_slot_index: int
    omitted_end_original_slot_index: int
    omitted_slot_count: int
    omitted_first_slot_id: str
    omitted_last_slot_id: str
    omitted_elapsed_slot_count: int
    omitted_partial_slot_id: Optional[str]
    startup_time_utc: _datetime.datetime
    first_live_original_slot_index: int
    first_live_cohort_slot_index: int
    first_live_slot_id: str
    first_live_bucket_start: _datetime.datetime
    first_live_close_time: _datetime.datetime
    first_live_member_sessions: Mapping[str, LiveCalendarMemberSession]
    _fingerprint: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        fingerprint = self.full_original_calendar_fingerprint
        if (
            type(fingerprint) is not str
            or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise LiveCohortValidationError("original calendar fingerprint must be SHA-256")
        if type(self.journal_highwater) is not LiveCohortJournalHighWater:
            raise LiveCohortValidationError("restart gap requires a typed journal high-water")
        for name in (
            "original_scope_first_slot_id",
            "original_scope_last_slot_id",
            "omitted_first_slot_id",
            "omitted_last_slot_id",
            "first_live_slot_id",
        ):
            _nonempty_text(getattr(self, name), name)
        for name in (
            "original_scope_slot_count",
            "omitted_slot_count",
            "first_live_original_slot_index",
            "first_live_cohort_slot_index",
        ):
            _positive_int(getattr(self, name), name)
        for name in (
            "history_highwater_original_slot_index",
            "omitted_start_original_slot_index",
            "omitted_end_original_slot_index",
            "omitted_elapsed_slot_count",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise LiveCohortValidationError("{} must be a non-negative integer".format(name))
        if (
            self.omitted_slot_count > _MAX_RESTART_GAP_SLOTS
            or self.omitted_end_original_slot_index - self.omitted_start_original_slot_index
            != self.omitted_slot_count
            or self.omitted_start_original_slot_index
            != self.history_highwater_original_slot_index + 1
            or self.first_live_original_slot_index != self.omitted_end_original_slot_index
            or self.history_highwater_original_slot_index >= self.original_scope_slot_count
            or self.omitted_end_original_slot_index >= self.original_scope_slot_count
            or self.first_live_cohort_slot_index
            != self.history_highwater_original_slot_index + 1
            or self.omitted_elapsed_slot_count > self.omitted_slot_count
        ):
            raise LiveCohortValidationError("restart gap slot range is inconsistent or unbounded")
        if self.omitted_partial_slot_id is not None:
            _nonempty_text(self.omitted_partial_slot_id, "omitted_partial_slot_id")
            if (
                self.omitted_elapsed_slot_count + 1 != self.omitted_slot_count
                or self.omitted_partial_slot_id != self.omitted_last_slot_id
            ):
                raise LiveCohortValidationError("only the final omitted slot may be partial")
        elif self.omitted_elapsed_slot_count != self.omitted_slot_count:
            raise LiveCohortValidationError("every omitted slot must be elapsed or one partial slot")
        startup = _aware_utc(self.startup_time_utc, "startup_time_utc")
        object.__setattr__(self, "startup_time_utc", startup)
        first_start = _aware_utc(self.first_live_bucket_start, "first_live_bucket_start")
        first_close = _aware_utc(self.first_live_close_time, "first_live_close_time")
        object.__setattr__(self, "first_live_bucket_start", first_start)
        object.__setattr__(self, "first_live_close_time", first_close)
        if first_start < startup or first_close <= first_start:
            raise LiveCohortValidationError("first live slot must begin at or after restart startup")
        if not isinstance(self.first_live_member_sessions, Mapping) or not self.first_live_member_sessions:
            raise LiveCohortValidationError("first live member sessions must be explicit")
        sessions = {}
        for member_id, session in self.first_live_member_sessions.items():
            _nonempty_text(member_id, "first live member id")
            if type(session) is not LiveCalendarMemberSession:
                raise LiveCohortValidationError(
                    "first live member sessions must use LiveCalendarMemberSession values"
                )
            sessions[member_id] = session
        if set(sessions) != set(self.journal_highwater.members):
            raise LiveCohortValidationError(
                "restart high-water and first-live slots must cover the same members"
            )
        object.__setattr__(self, "first_live_member_sessions", MappingProxyType(sessions))
        digest = hashlib.sha256()
        _update_calendar_fingerprint(digest, _restart_gap_fingerprint_payload(self))
        object.__setattr__(self, "_fingerprint", digest.hexdigest())

    @property
    def fingerprint(self) -> str:
        return self._fingerprint


def _restart_gap_fingerprint_payload(gap: LiveCohortRestartGap) -> Mapping[str, Any]:
    highwater = gap.journal_highwater
    return {
        "full_original_calendar_fingerprint": gap.full_original_calendar_fingerprint,
        "original_scope_first_slot_id": gap.original_scope_first_slot_id,
        "original_scope_last_slot_id": gap.original_scope_last_slot_id,
        "original_scope_slot_count": gap.original_scope_slot_count,
        "journal_highwater": {
            "cohort_id": highwater.cohort_id,
            "calendar_id": highwater.calendar_id,
            "calendar_version": highwater.calendar_version,
            "calendar_fingerprint": highwater.calendar_fingerprint,
            "epoch_id": highwater.epoch_id,
            "slot_index": highwater.slot_index,
            "slot_id": highwater.slot_id,
            "close_time": highwater.close_time.isoformat(),
            "batch_id": highwater.batch_id,
            "members": {
                member_id: {
                    "source_ref": member.source_ref,
                    "source_role": member.source_role,
                    "connection_generation": member.connection_generation,
                    "feed_sequence": member.feed_sequence,
                    "bar_id": member.bar_id,
                    "close_time": member.close_time.isoformat(),
                    "trading_day": member.trading_day,
                    "session_segment": member.session_segment,
                }
                for member_id, member in sorted(highwater.members.items())
            },
        },
        "history_highwater_original_slot_index": gap.history_highwater_original_slot_index,
        "omitted_start_original_slot_index": gap.omitted_start_original_slot_index,
        "omitted_end_original_slot_index": gap.omitted_end_original_slot_index,
        "omitted_slot_count": gap.omitted_slot_count,
        "omitted_first_slot_id": gap.omitted_first_slot_id,
        "omitted_last_slot_id": gap.omitted_last_slot_id,
        "omitted_elapsed_slot_count": gap.omitted_elapsed_slot_count,
        "omitted_partial_slot_id": gap.omitted_partial_slot_id,
        "startup_time_utc": gap.startup_time_utc.isoformat(),
        "first_live_original_slot_index": gap.first_live_original_slot_index,
        "first_live_cohort_slot_index": gap.first_live_cohort_slot_index,
        "first_live_slot_id": gap.first_live_slot_id,
        "first_live_bucket_start": gap.first_live_bucket_start.isoformat(),
        "first_live_close_time": gap.first_live_close_time.isoformat(),
        "first_live_member_sessions": {
            member_id: {
                "trading_day": session.trading_day,
                "session_segment": session.session_segment,
            }
            for member_id, session in sorted(gap.first_live_member_sessions.items())
        },
    }


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
    restart_gap: Optional[LiveCohortRestartGap] = field(default=None, repr=False, compare=False)
    _restart_gap_factory_token: Any = field(default=None, repr=False, compare=False)
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
        gap = self.restart_gap
        if gap is not None:
            if (
                type(gap) is not LiveCohortRestartGap
                or self._restart_gap_factory_token is not _RESTART_GAP_FACTORY_TOKEN
            ):
                raise LiveCohortValidationError(
                    "restart-gap calendars must be produced from a validated full calendar"
                )
            if (
                len(slots) != gap.original_scope_slot_count - gap.omitted_slot_count
                or gap.history_highwater_original_slot_index >= len(slots)
                or gap.first_live_cohort_slot_index >= len(slots)
                or slots[gap.history_highwater_original_slot_index].slot_id
                != gap.journal_highwater.slot_id
                or slots[gap.first_live_cohort_slot_index].slot_id != gap.first_live_slot_id
            ):
                raise LiveCohortValidationError("restart-gap calendar does not match its proof")
        elif self._restart_gap_factory_token is not None:
            raise LiveCohortValidationError("restart-gap factory token has no proof")
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
        if gap is not None:
            _update_calendar_fingerprint(
                digest,
                {"restart_gap": gap.fingerprint},
            )
        object.__setattr__(self, "_fingerprint", digest.hexdigest())

    @classmethod
    def with_restart_gap(
        cls,
        full_calendar: "LiveCohortCalendar",
        *,
        startup_time_utc: _datetime.datetime,
        journal_highwater: LiveCohortJournalHighWater,
        first_live_slot_id: str,
    ) -> "LiveCohortCalendar":
        """Bind one exact restart omission before building the new cohort.

        The caller supplies the validated finite calendar from its retained
        history scope through the remaining live plan. Only the contiguous
        slots after the durable history high-water and before the first live
        slot may be omitted. The original scope hash is named explicitly; it
        is not a factor-plan grid-semantics hash.
        """
        if type(full_calendar) is not cls or full_calendar.restart_gap is not None:
            raise LiveCohortValidationError(
                "restart-gap factory requires an unmodified full finite calendar"
            )
        if type(journal_highwater) is not LiveCohortJournalHighWater:
            raise LiveCohortValidationError("restart-gap factory requires a typed journal high-water")
        startup = _aware_utc(startup_time_utc, "startup_time_utc")
        first_live_slot_id = _nonempty_text(first_live_slot_id, "first_live_slot_id")
        ids = {slot.slot_id: index for index, slot in enumerate(full_calendar.slots)}
        highwater_index = ids.get(journal_highwater.slot_id)
        first_live_index = ids.get(first_live_slot_id)
        if highwater_index is None or first_live_index is None:
            raise LiveCohortValidationError("restart anchors must be slots in the full calendar")
        highwater_slot = full_calendar.slots[highwater_index]
        if (
            highwater_slot.close_time != journal_highwater.close_time
            or startup < highwater_slot.close_time
        ):
            raise LiveCohortValidationError("journal high-water does not match the full calendar")
        if first_live_index <= highwater_index + 1:
            raise LiveCohortValidationError("restart gap must omit at least one planned slot")
        omitted = full_calendar.slots[highwater_index + 1 : first_live_index]
        if not omitted or len(omitted) > _MAX_RESTART_GAP_SLOTS:
            raise LiveCohortCapacityError("restart omission is empty or exceeds its finite bound")
        first_live_slot = full_calendar.slots[first_live_index]
        if first_live_slot.bucket_start < startup:
            raise LiveCohortValidationError("restart omission cannot skip a current or future live slot")
        elapsed_count = 0
        partial_slot_id = None
        for index, slot in enumerate(omitted):
            if slot.close_time <= startup:
                if partial_slot_id is not None:
                    raise LiveCohortValidationError("elapsed slots cannot follow a partial omitted slot")
                elapsed_count += 1
            elif slot.bucket_start < startup < slot.close_time:
                if partial_slot_id is not None or index != len(omitted) - 1:
                    raise LiveCohortValidationError(
                        "only the final omitted slot may be in progress at restart"
                    )
                partial_slot_id = slot.slot_id
            else:
                raise LiveCohortValidationError("restart gap contains a future unelapsed slot")
        highwater_sessions = highwater_slot.member_sessions
        if highwater_sessions and set(highwater_sessions) != set(journal_highwater.members):
            raise LiveCohortValidationError("journal high-water member set differs from its slot")
        for member_id, member in journal_highwater.members.items():
            session = highwater_sessions.get(member_id)
            expected_day = highwater_slot.trading_day if session is None else session.trading_day
            expected_segment = (
                highwater_slot.session_segment if session is None else session.session_segment
            )
            if (
                _trading_day_key(member.trading_day) != _trading_day_key(expected_day)
                or member.session_segment != expected_segment
            ):
                raise LiveCohortValidationError(
                    "journal high-water session identity differs from the full calendar"
                )
        first_sessions = {}
        for member_id in journal_highwater.members:
            session = first_live_slot.member_sessions.get(member_id)
            first_sessions[member_id] = session or LiveCalendarMemberSession(
                first_live_slot.trading_day, first_live_slot.session_segment
            )
        proof = LiveCohortRestartGap(
            full_original_calendar_fingerprint=full_calendar.fingerprint,
            original_scope_first_slot_id=full_calendar.slots[0].slot_id,
            original_scope_last_slot_id=full_calendar.slots[-1].slot_id,
            original_scope_slot_count=len(full_calendar.slots),
            journal_highwater=journal_highwater,
            history_highwater_original_slot_index=highwater_index,
            omitted_start_original_slot_index=highwater_index + 1,
            omitted_end_original_slot_index=first_live_index,
            omitted_slot_count=len(omitted),
            omitted_first_slot_id=omitted[0].slot_id,
            omitted_last_slot_id=omitted[-1].slot_id,
            omitted_elapsed_slot_count=elapsed_count,
            omitted_partial_slot_id=partial_slot_id,
            startup_time_utc=startup,
            first_live_original_slot_index=first_live_index,
            first_live_cohort_slot_index=highwater_index + 1,
            first_live_slot_id=first_live_slot.slot_id,
            first_live_bucket_start=first_live_slot.bucket_start,
            first_live_close_time=first_live_slot.close_time,
            first_live_member_sessions=first_sessions,
        )
        return cls(
            calendar_id=full_calendar.calendar_id,
            version=full_calendar.version,
            epoch_id=full_calendar.epoch_id,
            frequency=full_calendar.frequency,
            frequency_seconds=full_calendar.frequency_seconds,
            timezone_id=full_calendar.timezone_id,
            clock_domain_id=full_calendar.clock_domain_id,
            session_semantics=full_calendar.session_semantics,
            slots=full_calendar.slots[: highwater_index + 1]
            + full_calendar.slots[first_live_index:],
            restart_gap=proof,
            _restart_gap_factory_token=_RESTART_GAP_FACTORY_TOKEN,
        )

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
class LiveSourceOrigin:
    # Adapter-declared first row of its supplied series, not exchange completeness.
    # It binds one member, epoch and exact source event. It states only that the
    # supplied prefix begins at this adapter's declared origin.

    member_id: str
    epoch_id: int
    source_ref: str
    source_role: str
    connection_generation: Any
    bar_id: str
    feed_sequence: int
    close_time: _datetime.datetime
    origin_partition: Optional[Mapping[str, Any]] = field(default=None, compare=True)

    def __post_init__(self) -> None:
        _nonempty_text(self.member_id, "member_id")
        _positive_int(self.epoch_id, "epoch_id")
        _nonempty_text(self.source_ref, "source_ref")
        if self.source_role not in ("history", "live"):
            raise LiveCohortValidationError("origin source_role must be history or live")
        generation = self.connection_generation
        if (
            isinstance(generation, bool)
            or not isinstance(generation, (str, int))
            or generation in ("", 0)
        ):
            raise LiveCohortValidationError("origin generation must be explicit")
        _nonempty_text(self.bar_id, "bar_id")
        _positive_int(self.feed_sequence, "feed_sequence")
        object.__setattr__(self, "close_time", _aware_utc(self.close_time, "close_time"))
        if self.origin_partition is not None:
            partition = _origin_partition_values(self.origin_partition)
            if (
                partition["member_id"] != self.member_id
                or partition["source_ref"] != self.source_ref
                or partition["connection_generation"] != self.connection_generation
            ):
                raise LiveCohortValidationError(
                    "source origin partition does not bind its origin"
                )
            object.__setattr__(self, "origin_partition", partition)


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
    source_origin: Optional[LiveSourceOrigin] = field(default=None, compare=False, repr=False)
    field_contracts: Mapping[str, LiveFieldContract] = field(default_factory=dict, compare=False)
    rules_hash: Optional[str] = None

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
        if self.rules_hash is not None:
            _nonempty_text(self.rules_hash, "rules_hash")
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
        if self.source_origin is not None and type(self.source_origin) is not LiveSourceOrigin:
            raise LiveCohortValidationError(
                "source_origin must be an immutable LiveSourceOrigin declaration"
            )
        if self.source_origin is not None and (
            self.source_origin.member_id != self.member_id
            or self.source_origin.source_ref != self.source_ref
        ):
            raise LiveCohortValidationError("source_origin does not match the member identity")
        if not set(numeric_fields).issubset(raw_fields):
            raise LiveCohortValidationError("numeric_fields must be declared in raw_fields")
        if not set(line_fields).issubset(numeric_fields):
            raise LiveCohortValidationError(
                "every exposed feed line must map to a validated numeric raw field"
            )
        if not isinstance(self.field_contracts, Mapping):
            raise LiveCohortValidationError("field_contracts must be a mapping")
        contracts = {}
        for name, contract in self.field_contracts.items():
            if name not in line_fields:
                raise LiveCohortValidationError("field contract must name a declared feed line")
            if type(contract) is not LiveFieldContract:
                raise LiveCohortValidationError("field contracts must be LiveFieldContract values")
            contracts[name] = contract
        object.__setattr__(self, "line_fields", line_fields)
        object.__setattr__(self, "raw_fields", raw_fields)
        object.__setattr__(self, "numeric_fields", numeric_fields)
        object.__setattr__(self, "field_contracts", MappingProxyType(contracts))


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
    line_values: Mapping[str, Any] = field(default_factory=dict, compare=False)
    field_observations: Mapping[str, LiveFieldObservation] = field(default_factory=dict)
    field_gaps: Mapping[str, str] = field(default_factory=dict)
    field_evaluated_at: Optional[_datetime.datetime] = None
    quality_flags: Tuple[str, ...] = ()
    event_source: str = ""
    received_monotonic_ns: Optional[int] = None
    event_ref: Any = field(default=None, compare=False, repr=False)
    evidence_ref: Any = field(default=None, compare=False, repr=False)
    rules_hash: Optional[str] = None
    origin_partition: Optional[Mapping[str, Any]] = field(default=None, compare=True)

    def __post_init__(self) -> None:
        object.__setattr__(self, "bucket_start", _aware_utc(self.bucket_start, "bucket_start"))
        if self.rules_hash is not None:
            _nonempty_text(self.rules_hash, "rules_hash")
        object.__setattr__(self, "close_time", _aware_utc(self.close_time, "close_time"))
        object.__setattr__(self, "available_at", _aware_utc(self.available_at, "available_at"))
        if self.field_evaluated_at is not None:
            object.__setattr__(
                self,
                "field_evaluated_at",
                _aware_utc(self.field_evaluated_at, "field_evaluated_at"),
            )
        missing = tuple(self.missing_fields)
        gaps = MappingProxyType(dict(self.field_gaps))
        allow_nan = set(missing).union(gaps)
        object.__setattr__(
            self, "raw_values", _frozen_mapping(self.raw_values, allow_nan_names=missing)
        )
        object.__setattr__(
            self, "line_values", _frozen_mapping(self.line_values, allow_nan_names=allow_nan)
        )
        if not isinstance(self.field_observations, Mapping):
            raise LiveCohortValidationError("field_observations must be a mapping")
        observations = dict(self.field_observations)
        if any(type(value) is not LiveFieldObservation for value in observations.values()):
            raise LiveCohortValidationError(
                "field observations must be LiveFieldObservation values"
            )
        object.__setattr__(self, "field_observations", MappingProxyType(observations))
        object.__setattr__(self, "field_gaps", gaps)
        object.__setattr__(self, "missing_fields", missing)
        object.__setattr__(self, "quality_flags", tuple(self.quality_flags))
        if self.origin_partition is not None:
            object.__setattr__(self, "origin_partition", _origin_partition_values(self.origin_partition))


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
    line_values: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        missing = tuple(self.missing_fields)
        gaps = getattr(self.envelope, "field_gaps", {})
        allow_nan = set(missing).union(gaps)
        object.__setattr__(
            self,
            "raw_values",
            _frozen_mapping(self.raw_values, allow_nan_names=missing),
        )
        object.__setattr__(
            self,
            "line_values",
            _frozen_mapping(self.line_values, allow_nan_names=allow_nan),
        )
        object.__setattr__(self, "missing_fields", missing)


@dataclass(frozen=True)
class LiveHistoryContinuity:
    # Bounded proof that delivered rows stayed contiguous from one origin.

    cohort_id: str
    member_id: str
    epoch_id: int
    source_ref: str
    qualified: bool
    reason: Optional[str]
    last_receipt: LiveDeliveryReceipt = field(compare=False, repr=False)
    origin_receipt: Optional[LiveDeliveryReceipt] = field(default=None, compare=False, repr=False)


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
    restart_gap_fingerprint: Optional[str] = None


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
    history_continuity: Mapping[str, LiveHistoryContinuity] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "members", MappingProxyType(dict(self.members)))
        object.__setattr__(self, "cutovers", MappingProxyType(dict(self.cutovers)))
        object.__setattr__(
            self, "history_continuity", MappingProxyType(dict(self.history_continuity))
        )

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
    origin_partition: Tuple[Any, ...]


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
        self._field_policies: Dict[Tuple[str, str], Tuple[str, float]] = {}
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
        self._last_origin_partition: Dict[str, Mapping[str, Any]] = {}
        self._last_partition_sequence: Dict[str, int] = {}
        self._last_role: Dict[str, Optional[str]] = {}
        self._history_last_close: Dict[str, _datetime.datetime] = {}
        self._first_live_receipt: Dict[str, LiveDeliveryReceipt] = {}
        self._history_continuity: Dict[str, LiveHistoryContinuity] = {}
        self._history_proof_owner_token = object()
        self._lock = threading.RLock()

    @property
    def calendar(self):
        """The immutable cohort calendar (read-only inspection accessor)."""
        return self._calendar

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
    def restart_gap(self) -> Optional[LiveCohortRestartGap]:
        return self._calendar.restart_gap

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

    def capacity_facts(self) -> Mapping[str, Any]:
        """Return a count-only snapshot of bounded cohort retention.

        All mutable fields are read under the same lock used by capture and
        delivery.  No source rows, member identifiers, or receipt contents are
        returned.
        """
        with self._lock:
            member_count = len(self._members)
            pending_slot_count = len(self._pending)
            pending_bar_count = sum(len(rows) for rows in self._pending.values())
            window_receipt_count = sum(len(rows) for rows in self._window_receipts.values())
            window_receipt_limits = tuple(
                rows.maxlen if isinstance(rows, deque) else None
                for rows in self._window_receipts.values()
            )
            recent_signature_limit = self.max_window_bars * max(member_count, 1)
            gap_limit = self._gaps.maxlen if isinstance(self._gaps, deque) else None
            gap_count = len(self._gaps)
            signature_count = len(self._recent_signatures)
            signature_order_count = len(self._recent_signature_order)
            window_limits_match = len(window_receipt_limits) == member_count and all(
                limit == self.max_window_bars for limit in window_receipt_limits
            )
            limits_respected = (
                pending_slot_count <= self.max_pending_slots
                and pending_bar_count <= self.max_pending_bars
                and window_receipt_count <= self.max_window_bars * member_count
                and signature_count <= recent_signature_limit
                and signature_order_count <= recent_signature_limit
                and gap_limit is not None
                and gap_count <= gap_limit
                and window_limits_match
            )
            return {
                "schema": "backtrader.live_cohort_capacity.v1",
                "status": "OBSERVED" if limits_respected else "OVER_CAPACITY_OR_UNAVAILABLE",
                "member_count": member_count,
                "pending_slot_count": pending_slot_count,
                "pending_bar_count": pending_bar_count,
                "max_pending_slots": self.max_pending_slots,
                "max_pending_bars": self.max_pending_bars,
                "window_receipt_count": window_receipt_count,
                "window_receipt_limit": self.max_window_bars * member_count,
                "window_receipt_member_limit": self.max_window_bars,
                "window_receipt_member_limits_match": window_limits_match,
                "recent_signature_count": signature_count,
                "recent_signature_order_count": signature_order_count,
                "recent_signature_limit": recent_signature_limit,
                "diagnostic_gap_count": gap_count,
                "diagnostic_gap_limit": gap_limit,
                "limits_respected": limits_respected,
            }

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
        source_origin: Optional[LiveSourceOrigin] = None,
        field_contracts: Optional[Mapping[str, LiveFieldContract]] = None,
        rules_hash: Optional[str] = None,
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
                source_origin=source_origin,
                field_contracts={} if field_contracts is None else field_contracts,
                rules_hash=rules_hash,
            )
            if member.source_origin is not None and member.source_origin.epoch_id != self.epoch_id:
                raise LiveCohortValidationError("source_origin epoch does not match the cohort")
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
            if self._sealed:
                return
            if not self._members:
                raise LiveCohortValidationError("cohort requires at least one registered member")
            expected_members = set(self._members)
            gap = self.restart_gap
            if gap is not None:
                highwater_members = set(gap.journal_highwater.members)
                if highwater_members != expected_members:
                    raise LiveCohortValidationError(
                        "restart journal high-water must cover every registered member"
                    )
                if set(gap.first_live_member_sessions) != expected_members:
                    raise LiveCohortValidationError(
                        "restart first-live session proof must cover every registered member"
                    )
                for member_id, member in self._members.items():
                    highwater = gap.journal_highwater.members[member_id]
                    if highwater.source_ref != member.source_ref:
                        raise LiveCohortValidationError(
                            "restart high-water source identity differs from the member"
                        )
                    expected_session = gap.first_live_member_sessions[member_id]
                    first_slot_session = self._calendar.slots[
                        gap.first_live_cohort_slot_index
                    ].member_sessions.get(member_id)
                    if first_slot_session is None:
                        first_slot_session = LiveCalendarMemberSession(
                            self._calendar.slots[gap.first_live_cohort_slot_index].trading_day,
                            self._calendar.slots[gap.first_live_cohort_slot_index].session_segment,
                        )
                    if expected_session != first_slot_session:
                        raise LiveCohortValidationError(
                            "restart first-live session proof differs from the retained calendar"
                        )
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

    def _issue_verified_saved_history_origin_proof(
        self,
        feed_ref: Any,
        event: Any,
        anchor: _VerifiedSavedHistoryJournalAnchor,
    ) -> _VerifiedSavedHistoryOriginProof:
        """Authorize one old-origin row after the runner verified its full journal anchor.

        The runner is the sole production caller and calls this only after the
        entire bounded tail passed journal checks.  The transient object is an
        in-process capability against plain tape mappings and accidental proof
        reuse; it is not a cryptographic boundary against same-privilege code.
        """
        with self._lock:
            if type(anchor) is not _VerifiedSavedHistoryJournalAnchor:
                raise LiveCohortValidationError("saved history requires a verified journal anchor")
            member = self.member_for_feed(feed_ref)
            if member is None or member.feed_ref is not feed_ref:
                raise LiveCohortValidationError("saved history anchor names another feed member")
            if self._next_slot_index or self._pending or self._prepared is not None:
                raise LiveCohortValidationError("saved history proofs must bind before capture")
            facts = anchor.facts
            if facts["origin_partition"] is None:
                raise LiveCohortValidationError("saved history origin partition is unproven")
            partition = _origin_partition_values(_read(event, "origin_partition", None))
            if (
                partition["epoch_id"] >= self.epoch_id
                or partition["cohort_id"] == self.cohort_id
                or partition["member_id"] != member.member_id
                or partition["source_ref"] != member.source_ref
                or facts["origin_partition"] is None
                or _origin_partition_identity(partition)
                != _origin_partition_identity(facts["origin_partition"])
                or partition["connection_generation"]
                != _read(event, "connection_generation", None)
                or _read(event, _SAVED_HISTORY_ANCHOR_EVENT_KEY, None)
                != _verified_history_anchor_identity(facts)
            ):
                raise LiveCohortValidationError("saved history journal anchor does not bind the row")
            member_receipt = facts["member_receipt"]
            if (
                member_receipt.get("member_id") != member.member_id
                or member_receipt.get("source_ref") != member.source_ref
                or _read(event, "source_ref", None) != member.source_ref
                or (
                    member_receipt.get("origin_partition") is not None
                    and _origin_partition_identity(
                        _origin_partition_values(member_receipt["origin_partition"])
                    )
                    != _origin_partition_identity(partition)
                )
                or (
                    member_receipt.get("origin_partition") is None
                    and (
                        member_receipt.get("source_role") != "live"
                        or partition["cohort_id"] != facts["source_cohort_id"]
                        or partition["epoch_id"] != facts["source_epoch_id"]
                        or partition["source_role"] != "live"
                    )
                )
                or member_receipt.get("connection_generation")
                != _read(event, "connection_generation", None)
                or member_receipt.get("feed_sequence") != _read(event, "bar_sequence", None)
                or member_receipt.get("bar_id") != _read(event, "bar_id", None)
                or member_receipt.get("source_role")
                != _read(event, _SAVED_HISTORY_RECORD_SOURCE_ROLE_EVENT_KEY, None)
                or member_receipt.get("complete") != _read(event, "complete", None)
                or member_receipt.get("quality") != _read(event, "quality", None)
                or member_receipt.get("present") != _read(event, "present", None)
                or tuple(member_receipt.get("missing_fields", ()))
                != _read(event, "missing_fields", None)
                or tuple(member_receipt.get("quality_flags", ()))
                != _read(event, "quality_flags", None)
                or member_receipt.get("event_source") != _read(event, "source", None)
                or member_receipt.get("received_monotonic_ns")
                != _read(event, "received_monotonic_ns", None)
                or member_receipt.get("rules_hash") != _read(event, "rules_hash", None)
                or member_receipt.get("bucket_start")
                != _history_receipt_time(_read(event, "bucket_start", None))
                or member_receipt.get("close_time")
                != _history_receipt_time(_read(event, "bucket_end", None))
                or member_receipt.get("available_at")
                != _history_receipt_time(_read(event, "available_at", None))
                or _trading_day_key(member_receipt.get("trading_day"))
                != _trading_day_key(_read(event, "trading_day", None))
                or member_receipt.get("session_segment")
                != _read(event, "session_segment", None)
                or member_receipt.get("timezone_id") != member.timezone_id
                or member_receipt.get("clock_domain_id") != member.clock_domain_id
            ):
                raise LiveCohortValidationError("saved history receipt member does not bind the row")
            receiver_slot_index = self._slot_index(
                _aware_utc(_read(event, "bucket_end", None), "saved history close_time")
            )
            if receiver_slot_index is None:
                raise LiveCohortValidationError("saved history row is outside the receiver calendar")
            receiver_slot = self._calendar.slots[receiver_slot_index]
            if (
                receiver_slot.bucket_start
                != _aware_utc(_read(event, "bucket_start", None), "saved history bucket_start")
                or _trading_day_key(receiver_slot.trading_day)
                != _trading_day_key(_read(event, "trading_day", None))
                or receiver_slot.session_segment
                != _read(event, "session_segment", None)
            ):
                raise LiveCohortValidationError("saved history row session differs from receiver slot")
            return _VerifiedSavedHistoryOriginProof(
                owner_token=self._history_proof_owner_token,
                member_identity=id(member),
                feed_identity=id(feed_ref),
                receiver_cohort_id=self.cohort_id,
                receiver_epoch_id=self.epoch_id,
                receiver_calendar_id=self.calendar_id,
                receiver_calendar_version=self.calendar_version,
                receiver_calendar_fingerprint=self.calendar_fingerprint,
                origin_identity=_origin_partition_identity(partition),
                source_role="history",
                generation=_read(event, "connection_generation", None),
                feed_sequence=_read(event, "bar_sequence", None),
                bar_id=_read(event, "bar_id", None),
                slot_index=receiver_slot_index,
                slot_id=receiver_slot.slot_id,
                close_time=receiver_slot.close_time,
                bucket_start=receiver_slot.bucket_start,
                available_at=_aware_utc(
                    _read(event, "available_at", None), "saved history available_at"
                ),
                trading_day=_read(event, "trading_day", None),
                session_segment=_read(event, "session_segment", None),
                content_sha256=_saved_history_event_sha256(event, member, "history"),
                tape_anchor_identity=_verified_history_anchor_identity(facts),
                tape_source_role=member_receipt["source_role"],
                decision_id=facts["decision_id"],
                receipt_sha256=facts["receipt_sha256"],
            )

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

    def bind_factor_field_policy(
        self, feed_ref: Any, line_name: str, *, unit: str, max_age_seconds: float
    ) -> None:
        """Bind a factor's exact field policy before the first source capture."""
        with self._lock:
            self._require_open()
            member = self.member_for_feed(feed_ref)
            if member is None or member.feed_ref is not feed_ref:
                raise LiveCohortValidationError("PIT field feed is not an exact cohort member")
            if line_name not in member.line_fields:
                raise LiveCohortValidationError("PIT field is not a declared member line")
            contract = member.field_contracts.get(line_name)
            if contract is None or contract.unit != unit:
                raise LiveCohortValidationError("PIT field lacks a matching adapter unit contract")
            if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, numbers.Real):
                raise LiveCohortValidationError("PIT max_age_seconds must be finite numeric")
            age = float(max_age_seconds)
            if not math.isfinite(age) or age <= 0.0:
                raise LiveCohortValidationError("PIT max_age_seconds must be finite and positive")
            if self._next_slot_index or self._pending or self._prepared is not None:
                raise LiveCohortValidationError("PIT policies must bind before source capture")
            key = (member.member_id, line_name)
            policy = (unit, age)
            prior = self._field_policies.get(key)
            if prior is not None and prior != policy:
                raise LiveCohortValidationError("conflicting PIT policies bind one exact field")
            self._field_policies[key] = policy

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
            rules_hash = self._validate_revision_notices(member, event)
            try:
                envelope = self._build_envelope(
                    member, event, source_role, received_monotonic_ns, rules_hash
                )
            except LiveCohortValidationError:
                self._freeze("invalid_source_bar")
                raise
            slot_index = envelope.slot_index
            existing = self._pending.get(slot_index, {}).get(member.member_id)
            if existing is not None:
                same_capture = (
                    self._data_signature(existing) == self._data_signature(envelope)
                    and existing.source_role == envelope.source_role
                )
                if same_capture and (
                    existing.connection_generation != envelope.connection_generation
                ):
                    self._freeze("connection_generation_changed")
                    raise LiveCohortFrozenError(
                        "duplicate bar came from a different connection generation"
                    )
                if same_capture and existing.origin_partition != envelope.origin_partition:
                    self._freeze("source_origin_partition_changed")
                    raise LiveCohortFrozenError(
                        "duplicate bar came from a different source origin partition"
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
                same_capture = (
                    signature is not None
                    and signature.data == candidate_signature.data
                    and signature.source_role == candidate_signature.source_role
                )
                if same_capture and (
                    signature.connection_generation != candidate_signature.connection_generation
                ):
                    self._freeze("connection_generation_changed")
                    raise LiveCohortFrozenError(
                        "late duplicate came from a different connection generation"
                    )
                if same_capture and signature.origin_partition != candidate_signature.origin_partition:
                    self._freeze("source_origin_partition_changed")
                    raise LiveCohortFrozenError(
                        "late duplicate came from a different source origin partition"
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

    def _validate_revision_notices(self, member: LiveCohortMember, event: Any) -> Optional[str]:
        raw_rules_hash = _read(event, "rules_hash", _COHORT_FIELD_MISSING)
        if (
            raw_rules_hash is _COHORT_FIELD_MISSING
            or raw_rules_hash is None
            or (isinstance(raw_rules_hash, str) and raw_rules_hash == "")
        ):
            rules_hash = None
        elif isinstance(raw_rules_hash, str) and raw_rules_hash.strip() == raw_rules_hash:
            rules_hash = raw_rules_hash
        else:
            self._freeze("invalid_rules_revision_notice")
            raise LiveCohortFrozenError("source rules revision notice is malformed")
        if member.rules_hash is not None and rules_hash != member.rules_hash:
            self._freeze("member_rules_revision_changed")
            raise LiveCohortFrozenError("member rules revision changed; rebuild the cohort epoch")

        calendar_revision = _read(event, "calendar_revision", _COHORT_FIELD_MISSING)
        if calendar_revision is not _COHORT_FIELD_MISSING and calendar_revision is not None:
            if type(calendar_revision) is not LiveCohortCalendar:
                self._freeze("invalid_calendar_revision_notice")
                raise LiveCohortFrozenError("source calendar revision notice is malformed")
            expected = self._calendar
            observed_identity = (
                calendar_revision.calendar_id,
                calendar_revision.version,
                calendar_revision.fingerprint,
            )
            expected_identity = (expected.calendar_id, expected.version, expected.fingerprint)
            original_identity = (
                expected.calendar_id,
                expected.version,
                None
                if expected.restart_gap is None
                else expected.restart_gap.full_original_calendar_fingerprint,
            )
            if observed_identity != expected_identity and observed_identity != original_identity:
                self._freeze("calendar_revision_changed")
                raise LiveCohortFrozenError("calendar revision changed; rebuild the cohort epoch")
        return rules_hash

    def _build_envelope(
        self,
        member: LiveCohortMember,
        event: Any,
        source_role: str,
        received_monotonic_ns: Optional[int],
        rules_hash: Optional[str],
    ) -> BarEnvelope:
        if source_role not in ("history", "live"):
            raise LiveCohortValidationError("source_role must be exactly 'history' or 'live'")
        stale = _read(event, "stale", _COHORT_FIELD_MISSING)
        if stale is not _COHORT_FIELD_MISSING:
            if type(stale) is not bool:
                raise LiveCohortValidationError("bar stale marker must be an exact boolean")
            if stale:
                raise LiveCohortValidationError("stale source bars cannot enter a live cohort")
        continuity = _read(event, "continuity_status", _COHORT_FIELD_MISSING)
        if continuity is _COHORT_FIELD_MISSING:
            continuity = _read(event, "continuity", _COHORT_FIELD_MISSING)
        if continuity is not _COHORT_FIELD_MISSING and continuity is not None:
            if type(continuity) is not str:
                raise LiveCohortValidationError("bar continuity status must be text")
            if continuity.lower() in {
                "gap",
                "stale",
                "disconnected",
                "checksum_failed",
                "out_of_order",
                "invalid",
            }:
                raise LiveCohortValidationError(
                    "non-continuous source bars cannot enter a live cohort"
                )
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
        restart_gap = self.restart_gap
        if restart_gap is not None:
            history_index = restart_gap.history_highwater_original_slot_index
            first_live_index = restart_gap.first_live_cohort_slot_index
            if slot_index <= history_index and source_role != "history":
                raise LiveCohortValidationError(
                    "restart history prefix cannot contain live-role bars"
                )
            if slot_index >= first_live_index and source_role != "live":
                raise LiveCohortValidationError(
                    "restart live tail cannot contain history-role bars"
                )

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
        origin_partition = _read(event, "origin_partition", None)
        if origin_partition is None:
            origin_partition = MappingProxyType(
                {
                    "schema": _SOURCE_ORIGIN_PARTITION_SCHEMA,
                    "cohort_id": self.cohort_id,
                    "epoch_id": self.epoch_id,
                    "member_id": member.member_id,
                    "source_ref": member.source_ref,
                    "source_role": source_role,
                    "connection_generation": generation,
                }
            )
        else:
            origin_partition = _origin_partition_values(origin_partition)
        proof = _read(event, _VERIFIED_HISTORY_PROOF_EVENT_KEY, None)
        if origin_partition["epoch_id"] > self.epoch_id:
            raise LiveCohortValidationError("source origin partition is from a future epoch")
        if origin_partition["epoch_id"] < self.epoch_id:
            if source_role != "history":
                raise LiveCohortValidationError(
                    "an older source origin partition must enter as history"
                )
            if type(proof) is not _VerifiedSavedHistoryOriginProof:
                raise LiveCohortValidationError(
                    "saved history requires a verified journal anchor"
                )
        if (
            origin_partition["member_id"] != member.member_id
            or origin_partition["source_ref"] != member.source_ref
            or origin_partition["connection_generation"] != generation
            or (
                origin_partition["epoch_id"] == self.epoch_id
                and (
                    origin_partition["cohort_id"] != self.cohort_id
                    or origin_partition["source_role"] != source_role
                )
            )
            or (
                origin_partition["epoch_id"] < self.epoch_id
                and origin_partition["cohort_id"] == self.cohort_id
            )
            or (
                source_role == "live"
                and (
                    origin_partition["cohort_id"] != self.cohort_id
                    or origin_partition["epoch_id"] != self.epoch_id
                    or origin_partition["source_role"] != "live"
                )
            )
            or (
                source_role == "history"
                and origin_partition["epoch_id"] == self.epoch_id
                and origin_partition["source_role"] != "history"
            )
        ):
            raise LiveCohortValidationError("source origin partition does not match the bar")
        sequence = _positive_int(_read(event, "bar_sequence", None), "bar_sequence")
        bar_id = _nonempty_text(_read(event, "bar_id", None), "bar_id")
        trading_day = _nonempty_text(_read(event, "trading_day", None), "trading_day")
        session_segment = _nonempty_text(_read(event, "session_segment", None), "session_segment")
        if origin_partition["epoch_id"] == self.epoch_id and proof is not None:
            raise LiveCohortValidationError("current source row cannot carry a saved history proof")
        if origin_partition["epoch_id"] < self.epoch_id:
            proof_matches = (
                proof.owner_token is self._history_proof_owner_token
                and proof.member_identity == id(member)
                and proof.feed_identity == id(member.feed_ref)
                and proof.receiver_cohort_id == self.cohort_id
                and proof.receiver_epoch_id == self.epoch_id
                and proof.receiver_calendar_id == self.calendar_id
                and proof.receiver_calendar_version == self.calendar_version
                and proof.receiver_calendar_fingerprint == self.calendar_fingerprint
                and proof.origin_identity == _origin_partition_identity(origin_partition)
                and proof.source_role == source_role
                and proof.generation == generation
                and proof.feed_sequence == sequence
                and proof.bar_id == bar_id
                and proof.slot_index == slot_index
                and proof.slot_id == slot.slot_id
                and proof.close_time == close_time
                and proof.bucket_start == slot_start
                and proof.available_at == available_at
                and proof.trading_day == trading_day
                and proof.session_segment == session_segment
                and proof.tape_anchor_identity
                == _read(event, _SAVED_HISTORY_ANCHOR_EVENT_KEY, None)
                and proof.tape_source_role
                == _read(event, _SAVED_HISTORY_RECORD_SOURCE_ROLE_EVENT_KEY, None)
                and proof.content_sha256 == _saved_history_event_sha256(event, member, source_role)
            )
            if not proof_matches:
                raise LiveCohortValidationError("saved history proof does not bind the exact row")
        expected_session = slot.member_sessions.get(member.member_id)
        expected_trading_day = (
            expected_session.trading_day if expected_session is not None else slot.trading_day
        )
        expected_session_segment = (
            expected_session.session_segment
            if expected_session is not None
            else slot.session_segment
        )
        if (
            _trading_day_key(trading_day) != _trading_day_key(expected_trading_day)
            or session_segment != expected_session_segment
        ):
            raise LiveCohortValidationError(
                "bar trading day/session does not match the planned slot"
            )
        if (
            restart_gap is not None
            and slot_index == restart_gap.history_highwater_original_slot_index
        ):
            highwater = restart_gap.journal_highwater.members.get(member.member_id)
            # The journal role is preserved as old-run identity; replay still
            # enters this epoch through the explicit history source role.
            if (
                highwater is None
                or highwater.source_ref != member.source_ref
                or source_role != "history"
                or highwater.connection_generation != generation
                or highwater.feed_sequence != sequence
                or highwater.bar_id != bar_id
                or highwater.close_time != close_time
                or _trading_day_key(highwater.trading_day) != _trading_day_key(trading_day)
                or highwater.session_segment != session_segment
            ):
                raise LiveCohortValidationError(
                    "restart history high-water differs from the exact replayed bar"
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
        field_observations = {}
        field_gaps = {}
        line_values = dict(raw_values)
        member_policies = tuple(
            (field_name, unit, max_age_seconds)
            for (member_id, field_name), (unit, max_age_seconds) in self._field_policies.items()
            if member_id == member.member_id
        )
        if member_policies:
            supplied = _read(event, "field_observations", None)
            if supplied is None:
                supplied = {}
            elif type(supplied) is not type(MappingProxyType({})):
                raise LiveCohortValidationError(
                    "PIT field_observations must be an immutable mapping"
                )
            for field_name, observation in supplied.items():
                contract = member.field_contracts.get(field_name)
                if contract is None:
                    raise LiveCohortValidationError(
                        "PIT observation names a field without an adapter contract"
                    )
                if field_name in missing_fields:
                    raise LiveCohortValidationError(
                        "a declared missing field cannot carry an observation"
                    )
                if type(observation) is not LiveFieldObservation:
                    raise LiveCohortValidationError(
                        "field observations must be immutable LiveFieldObservation values"
                    )
                if (
                    observation.source_ref != contract.source_ref
                    or observation.unit != contract.unit
                ):
                    raise LiveCohortValidationError(
                        "PIT field source or unit differs from the adapter contract"
                    )
                if observation.effective_at > close_time:
                    raise LiveCohortValidationError("PIT field becomes effective after bar close")
                if observation.available_at > available_at:
                    raise LiveCohortValidationError(
                        "PIT field was not available by the enclosing bar availability"
                    )
                if contract.delivery_mode == "co_delivered":
                    if (
                        contract.source_ref != member.source_ref
                        or _read(event, "source_ref", None) != contract.source_ref
                        or observation.effective_at != close_time
                        or observation.available_at != available_at
                        or observation.revision != (generation, sequence, bar_id)
                    ):
                        raise LiveCohortValidationError(
                            "co-delivered PIT provenance does not match this exact bar event"
                        )
                    if observation.valid_until > close_time + _datetime.timedelta(
                        seconds=contract.validity_seconds
                    ):
                        raise LiveCohortValidationError(
                            "co-delivered PIT valid_until exceeds adapter validity"
                        )
            for field_name, unit, max_age_seconds in member_policies:
                contract = member.field_contracts.get(field_name)
                if contract is None or contract.unit != unit:
                    raise LiveCohortValidationError("PIT field contract changed after binding")
                if field_name in missing_fields:
                    field_gaps[field_name] = "field_missing"
                    line_values[field_name] = float("nan")
                    continue
                observation = supplied.get(field_name)
                if observation is None and contract.delivery_mode == "co_delivered":
                    if (
                        contract.source_ref != member.source_ref
                        or _read(event, "source_ref", None) != contract.source_ref
                    ):
                        raise LiveCohortValidationError(
                            "co-delivered PIT source differs from the exact bar member"
                        )
                    observation = LiveFieldObservation(
                        source_ref=contract.source_ref,
                        unit=contract.unit,
                        effective_at=close_time,
                        available_at=available_at,
                        revision=(generation, sequence, bar_id),
                        valid_until=close_time
                        + _datetime.timedelta(seconds=contract.validity_seconds),
                    )
                if type(observation) is not LiveFieldObservation:
                    raise LiveCohortValidationError(
                        "required PIT field lacks an immutable field observation"
                    )
                if (
                    observation.source_ref != contract.source_ref
                    or observation.unit != contract.unit
                ):
                    raise LiveCohortValidationError(
                        "PIT field source or unit differs from the adapter contract"
                    )
                if observation.effective_at > close_time:
                    raise LiveCohortValidationError("PIT field becomes effective after bar close")
                if observation.available_at > available_at:
                    raise LiveCohortValidationError(
                        "PIT field was not available by the enclosing bar availability"
                    )
                if contract.delivery_mode == "co_delivered" and (
                    contract.source_ref != member.source_ref
                    or _read(event, "source_ref", None) != contract.source_ref
                    or observation.effective_at != close_time
                    or observation.available_at != available_at
                    or observation.revision != (generation, sequence, bar_id)
                ):
                    raise LiveCohortValidationError(
                        "co-delivered PIT provenance does not match this exact bar event"
                    )
                age = (close_time - observation.effective_at).total_seconds()
                if observation.valid_until < close_time or age > max_age_seconds:
                    field_gaps[field_name] = (
                        "field_expired" if observation.valid_until < close_time else "field_stale"
                    )
                    line_values[field_name] = float("nan")
                field_observations[field_name] = observation
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
            line_values=line_values,
            field_observations=field_observations,
            field_gaps=field_gaps,
            field_evaluated_at=(close_time if field_observations or field_gaps else None),
            quality_flags=tuple(sorted(flags)),
            event_source=source or "",
            received_monotonic_ns=received_monotonic_ns,
            event_ref=event,
            evidence_ref=evidence,
            rules_hash=rules_hash,
            origin_partition=origin_partition,
        )

    def _validate_member_sequence(self, member: LiveCohortMember, envelope: BarEnvelope) -> None:
        role = self._last_role[member.member_id]
        if role == "live" and envelope.source_role == "history":
            self._freeze("history_after_live")
            raise LiveCohortFrozenError("history bars cannot follow live bars within an epoch")
        partition = envelope.origin_partition
        if partition is None:
            self._freeze("source_origin_partition_missing")
            raise LiveCohortFrozenError("source origin partition is required")
        previous_partition = self._last_origin_partition.get(member.member_id)
        previous_sequence = self._last_partition_sequence.get(member.member_id)
        if previous_partition is not None:
            if not _origin_partition_follows(previous_partition, partition):
                self._freeze("source_origin_partition_order_invalid")
                raise LiveCohortFrozenError("source origin partition moved backwards or changed")
            same_partition = (
                _origin_partition_identity(previous_partition)
                == _origin_partition_identity(partition)
            )
            if same_partition and previous_sequence is not None and envelope.feed_sequence <= previous_sequence:
                self._freeze("non_monotone_feed_sequence")
                raise LiveCohortFrozenError("feed sequence must increase within source partition")
            if role == "live" and envelope.source_role == "live" and not same_partition:
                self._freeze("source_origin_partition_order_invalid")
                raise LiveCohortFrozenError("live source cannot switch origin partitions")
        self._last_origin_partition[member.member_id] = partition
        self._last_partition_sequence[member.member_id] = envelope.feed_sequence
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
            envelope.rules_hash,
            tuple(
                (
                    name,
                    obs.source_ref,
                    obs.unit,
                    obs.effective_at,
                    obs.available_at,
                    obs.revision,
                    obs.valid_until,
                )
                for name, obs in sorted(envelope.field_observations.items())
            ),
        )

    @classmethod
    def _signature_for(cls, envelope: BarEnvelope) -> _BarSignature:
        return _BarSignature(
            data=cls._data_signature(envelope),
            source_role=envelope.source_role,
            connection_generation=envelope.connection_generation,
            feed_sequence=envelope.feed_sequence,
            bar_id=envelope.bar_id,
            origin_partition=(
                ()
                if envelope.origin_partition is None
                else _origin_partition_identity(envelope.origin_partition)
            ),
        )

    @staticmethod
    def _signature_is_duplicate(prior: _BarSignature, candidate: _BarSignature) -> bool:
        if prior.data != candidate.data:
            return False
        if prior.source_role == candidate.source_role:
            return (
                prior.origin_partition == candidate.origin_partition
                and
                prior.connection_generation == candidate.connection_generation
                and prior.feed_sequence == candidate.feed_sequence
                and prior.bar_id == candidate.bar_id
            )
        return {prior.source_role, candidate.source_role} == {"history", "live"}

    @classmethod
    def _is_duplicate(cls, prior: BarEnvelope, candidate: BarEnvelope) -> bool:
        return cls._signature_is_duplicate(cls._signature_for(prior), cls._signature_for(candidate))

    def _project_fields_at_scheduler_boundary(
        self, envelope: BarEnvelope, decision_time: _datetime.datetime
    ) -> BarEnvelope:
        """Seal any newly stale field as NaN before the normal feed write."""
        decision_time = _aware_utc(decision_time, "field decision_time")
        policies = tuple(
            (field_name, unit, max_age_seconds)
            for (member_id, field_name), (unit, max_age_seconds) in self._field_policies.items()
            if member_id == envelope.member_id
        )
        if not policies:
            return envelope
        line_values = dict(envelope.line_values)
        field_gaps = dict(envelope.field_gaps)
        changed = envelope.field_evaluated_at != decision_time
        for field_name, unit, max_age_seconds in policies:
            if field_name in envelope.missing_fields:
                continue
            observation = envelope.field_observations.get(field_name)
            if observation is None or observation.unit != unit:
                self._freeze("pit_observation_lost_before_delivery")
                raise LiveCohortFrozenError(
                    "PIT field observation changed before the prepared feed write"
                )
            if observation.available_at > decision_time:
                self._freeze("pit_field_not_available_at_scheduler_boundary")
                raise LiveCohortFrozenError(
                    "PIT field was not available at the scheduler delivery boundary"
                )
            age = (decision_time - observation.effective_at).total_seconds()
            gap = (
                "field_expired"
                if observation.valid_until < decision_time
                else "field_stale"
                if age > max_age_seconds
                else None
            )
            if gap is not None and field_gaps.get(field_name) not in (
                "field_missing",
                "field_expired",
                "field_stale",
            ):
                field_gaps[field_name] = gap
                line_values[field_name] = float("nan")
                changed = True
        if not changed:
            return envelope
        return replace(
            envelope,
            line_values=line_values,
            field_gaps=field_gaps,
            field_evaluated_at=decision_time,
        )

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
                max(
                    [envelope.available_at for envelope in rows.values()]
                    + [
                        observation.available_at
                        for envelope in rows.values()
                        for observation in envelope.field_observations.values()
                    ]
                )
                if not missing
                else None
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
            for member_id, envelope in tuple(rows.items()):
                projected = self._project_fields_at_scheduler_boundary(envelope, source_now)
                rows[member_id] = projected
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
                latest_available_at = max(
                    [row.available_at for row in rows.values()]
                    + [
                        observation.available_at
                        for row in rows.values()
                        for observation in row.field_observations.values()
                    ]
                )

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
            if not set(member.line_fields).issubset(envelope.line_values):
                self._freeze("prepared_raw_schema_changed")
                raise LiveCohortFrozenError("prepared envelope lacks a declared feed line")
            return MappingProxyType(dict(envelope.line_values))

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
            or set(envelope.line_values) != set(member.raw_fields)
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
        if any(name not in member.line_fields for name in envelope.field_gaps):
            return False
        blocked_fields = set(missing).union(envelope.field_gaps)
        for name in member.raw_fields:
            projected = envelope.line_values.get(name)
            if name in blocked_fields:
                if not isinstance(projected, float) or not math.isnan(projected):
                    return False
            elif projected != envelope.raw_values.get(name):
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
                raw_values=envelope.raw_values,
                line_values=raw_values,
            )
            self._delivered[member.member_id] = receipt
            if len(self._delivered) == len(self._members):
                self._publish_complete_batch()
            return receipt

    def _advance_history_continuity(
        self,
        member: LiveCohortMember,
        receipt: LiveDeliveryReceipt,
        prior: Optional[LiveHistoryContinuity],
    ) -> LiveHistoryContinuity:
        # Advance one bounded origin/continuity fact; failures stay permanent.
        complete = (
            receipt.complete is True
            and receipt.quality == "GOOD"
            and receipt.present is True
            and not receipt.missing_fields
            and not receipt.envelope.field_gaps
            and set(member.line_fields).issubset(receipt.raw_values)
        )
        if prior is None:
            origin = member.source_origin
            expected_origin_partition = (
                None
                if origin is None
                else origin.origin_partition
                or MappingProxyType(
                    {
                        "schema": _SOURCE_ORIGIN_PARTITION_SCHEMA,
                        "cohort_id": self.cohort_id,
                        "epoch_id": origin.epoch_id,
                        "member_id": origin.member_id,
                        "source_ref": origin.source_ref,
                        "source_role": origin.source_role,
                        "connection_generation": origin.connection_generation,
                    }
                )
            )
            exact_origin = (
                origin is not None
                and origin.member_id == member.member_id
                and origin.epoch_id == self.epoch_id
                and origin.source_ref == member.source_ref == receipt.source_ref
                and origin.source_role == receipt.source_role
                and origin.connection_generation == receipt.envelope.connection_generation
                and origin.bar_id == receipt.envelope.bar_id
                and origin.feed_sequence == receipt.feed_sequence
                and origin.close_time == receipt.close_time
                and receipt.envelope.origin_partition is not None
                and expected_origin_partition is not None
                and _origin_partition_identity(expected_origin_partition)
                == _origin_partition_identity(receipt.envelope.origin_partition)
            )
            qualified = bool(exact_origin and complete)
            reason = (
                None
                if qualified
                else ("history_prefix_incomplete" if exact_origin else "history_origin_unverified")
            )
            return LiveHistoryContinuity(
                cohort_id=self.cohort_id,
                member_id=member.member_id,
                epoch_id=self.epoch_id,
                source_ref=member.source_ref,
                qualified=qualified,
                reason=reason,
                origin_receipt=receipt if exact_origin else None,
                last_receipt=receipt,
            )

        if not prior.qualified:
            return LiveHistoryContinuity(
                cohort_id=self.cohort_id,
                member_id=member.member_id,
                epoch_id=self.epoch_id,
                source_ref=member.source_ref,
                qualified=False,
                reason=prior.reason or "history_reconstruction_discontinuous",
                origin_receipt=prior.origin_receipt,
                last_receipt=receipt,
            )

        previous = prior.last_receipt
        restart_gap = self.restart_gap
        if (
            restart_gap is not None
            and previous.source_role == "history"
            and receipt.source_role == "live"
            and previous.slot_index == restart_gap.history_highwater_original_slot_index
            and receipt.slot_index == restart_gap.first_live_cohort_slot_index
            and previous.close_time == restart_gap.journal_highwater.close_time
            and receipt.envelope.slot_id == restart_gap.first_live_slot_id
        ):
            return LiveHistoryContinuity(
                cohort_id=self.cohort_id,
                member_id=member.member_id,
                epoch_id=self.epoch_id,
                source_ref=member.source_ref,
                qualified=False,
                reason="history_restart_gap",
                origin_receipt=prior.origin_receipt,
                last_receipt=receipt,
            )
        # Current role remains the feed contract. Origin partitions disambiguate
        # historical rows merged from successive, journal-anchored sessions.
        previous_partition = previous.envelope.origin_partition
        current_partition = receipt.envelope.origin_partition
        same_partition = bool(
            previous_partition is not None
            and current_partition is not None
            and _origin_partition_identity(previous_partition)
            == _origin_partition_identity(current_partition)
        )
        if previous.source_role == receipt.source_role:
            role_continuous = bool(
                previous_partition is not None
                and current_partition is not None
                and _origin_partition_follows(previous_partition, current_partition)
                and (not same_partition or receipt.feed_sequence > previous.feed_sequence)
            )
        else:
            role_continuous = bool(
                previous.source_role == "history"
                and receipt.source_role == "live"
                and previous_partition is not None
                and current_partition is not None
                and _origin_partition_follows(previous_partition, current_partition)
            )
        continuous = (
            complete
            and receipt.cohort_id == prior.cohort_id == self.cohort_id
            and receipt.member_id == prior.member_id == member.member_id
            and receipt.epoch_id == prior.epoch_id == self.epoch_id
            and receipt.source_ref == prior.source_ref == member.source_ref
            and receipt.slot_index == previous.slot_index + 1
            and role_continuous
        )
        return LiveHistoryContinuity(
            cohort_id=self.cohort_id,
            member_id=member.member_id,
            epoch_id=self.epoch_id,
            source_ref=member.source_ref,
            qualified=continuous,
            reason=None if continuous else "history_reconstruction_discontinuous",
            origin_receipt=prior.origin_receipt,
            last_receipt=receipt,
        )

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
                if not set(member.line_fields).issubset(envelope.line_values):
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
                    line_values=envelope.line_values,
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
                            "restart_gap_to_live"
                            if self.restart_gap is not None
                            else "history_to_live"
                            if history_last is not None
                            else "live_cold_start"
                        ),
                        crossed_live=True,
                        first_live_receipt=first_live,
                        restart_gap_fingerprint=(
                            None if self.restart_gap is None else self.restart_gap.fingerprint
                        ),
                    )

            continuity_updates = {
                member_id: self._advance_history_continuity(
                    self._members[member_id], receipt, self._history_continuity.get(member_id)
                )
                for member_id, receipt in receipts.items()
            }
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
                history_continuity=continuity_updates,
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
            old_history_continuity = dict(self._history_continuity)
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
                self._history_continuity.update(continuity_updates)
                self._next_slot_index = prepared.slot_index + 1
                self._prepared = None
                self._delivered = {}
                self._wait_started_ns = None
                self._wait_missing_member_ids = ()
                # This is the sole public commit point for the completed batch.
                self._current_batch = batch
            except BaseException:
                self._current_batch = old_current_batch
                self._history_continuity = old_history_continuity
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
        continuity_updates = {
            member_id: self._advance_history_continuity(
                self._members[member_id], receipt, self._history_continuity.get(member_id)
            )
            for member_id, receipt in receipts.items()
        }
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
            history_continuity=continuity_updates,
        )
        self._history_continuity.update(continuity_updates)
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

    def history_continuity_for_feed(self, feed_ref: Any) -> Optional[LiveHistoryContinuity]:
        # Return the current bounded reconstruction fact for an exact feed.
        with self._lock:
            member = self.member_for_feed(feed_ref)
            if member is None:
                return None
            return self._history_continuity.get(member.member_id)

    def owns_history_continuity(self, proof: Any) -> bool:
        # Check exact issuance and current identity of a continuity fact.
        with self._lock:
            return (
                type(proof) is LiveHistoryContinuity
                and self._history_continuity.get(proof.member_id) is proof
            )

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
                or any(name in row.envelope.field_gaps for name in names)
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

    def complete_live_window_bars(
        self,
        feed_ref: Any,
        line_names: Iterable[str],
        count: int,
        *,
        current_receipt: Optional[LiveDeliveryReceipt] = None,
    ) -> Tuple[LiveDeliveryReceipt, ...]:
        """Return an exact bounded GOOD window delivered wholly after a restart gap."""
        with self._lock:
            gap = self.restart_gap
            if gap is None:
                return ()
            member = self.member_for_feed(feed_ref)
            if member is None:
                raise LiveCohortValidationError("window feed is not an exact registered member")
            window = self.complete_window_bars(feed_ref, line_names, count)
            if not window:
                return ()
            batch = self._current_batch
            current = None if batch is None else batch.members.get(member.member_id)
            if current_receipt is None:
                current_receipt = current
            if (
                current is None
                or current is not current_receipt
                or current.feed_ref is not feed_ref
                or self.current_delivery(feed_ref) is not current
                or current.slot_index < gap.first_live_cohort_slot_index
                or window[-1] is not current
            ):
                return ()
            if any(
                row.source_role != "live"
                or row.source_ref != member.source_ref
                or row.feed_ref is not feed_ref
                or row.slot_index < gap.first_live_cohort_slot_index
                or row.epoch_id != self.epoch_id
                or row.envelope.connection_generation
                != window[0].envelope.connection_generation
                for row in window
            ):
                return ()
            if any(
                right.feed_sequence <= left.feed_sequence
                for left, right in zip(window, window[1:])
            ):
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
            transition_kind=(
                "restart_gap_to_live"
                if self.restart_gap is not None
                else "history_to_live"
                if history_last is not None
                else "live_cold_start"
            ),
            crossed_live=True,
            first_live_receipt=first_live,
            restart_gap_fingerprint=(
                None if self.restart_gap is None else self.restart_gap.fingerprint
            ),
        )

    def _require_open(self) -> None:
        if self._frozen_reason is not None:
            raise LiveCohortFrozenError("cohort is frozen: {}".format(self._frozen_reason))

    def _freeze(self, reason: str) -> None:
        if self._frozen_reason is None:
            self._frozen_reason = reason
