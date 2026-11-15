"""Orders created during a confirmed market closure, waiting for the next session.

``state/waiting_orders.json`` holds ``{"version": 2, "strategy_uuid",
"orders": {waiting_id: order}, "history": [order, ...]}`` (D62-30/31).  The
original order parameters and the *intent* of the validity (``valid_intent``)
are stored unchanged; a DAY validity is computed by the dispatcher at actual
submit time, never pre-computed here.  ``offset`` is stored exactly as the
strategy gave it (``close_today`` is never rewritten).

``target_session`` binds the target trading day and window to the versioned
``calendar_ref`` of the session answer that produced it (D67-15/17, INV67-08).
A new order without a usable calendar reference is refused.  Version-1
records (no ``calendar_ref``) are readable but stay explicitly unbound:
:meth:`WaitingOrderStore.record_calendar_disposition` records why they are not
resumed, and nothing here ever guesses the missing reference.

Migration and recovery (D67-17).  A version-1 file is readable as-is.  The
first *durable write* upgrades it to version 2, but only after

1. the exact original bytes were copied to ``state/backups/`` with the same
   atomic-write discipline and read back to compare the SHA-256 digest,
2. a marker at ``state/backups/waiting_migration.json`` recorded the backup
   file, digest, source/target version and record counts, and
3. an audit record recorded the digest, path and versions.

The upgrade keeps every record byte-for-byte in content (identity, original
target, local sequence, status, timestamps and facts are never rewritten) and
never truncates history during the migration write.  An interrupted migration
therefore leaves either the untouched original or the complete new file plus
an ``in_progress`` marker: :meth:`WaitingOrderStore.recover_migration`
converges it (finish, replay from the same backup, or restore the original)
without discarding records, and :meth:`WaitingOrderStore.rollback_migration`
verifies the backup digest and refuses when anything changed after the
upgrade, so post-upgrade order facts are never overwritten.  Unknown or newer
file versions are refused with ``state_corrupt``/``version_unsupported`` and
the file is left untouched.

A pause is sticky until an operator clears it:

:meth:`WaitingOrderStore.clear_calendar_pause` is the *only* path that removes
``facts.calendar_disposition``.  It requires current calendar evidence that
matches the original target (same trading day and window, with a versioned
``calendar_ref``) and refuses a record that was never calendar-bound.  Clearing
is not a trading authorization: it neither changes the status nor dispatches,
retries or re-sends anything, and the original target is never altered.

Each newly recorded pause also emits one typed, bounded notice through the
repository's :mod:`backtrader.notifications` layer (deduplicated per order,
reason and calendar version).  Notification failures are recorded as a finite
``facts.pause_notification_status`` and never change the order state.

Status machine (compare-and-set under ``state/waiting.lock``)::

    WAITING     -> DISPATCHING | CANCELLED | EXPIRED | REJECTED
    DISPATCHING -> DISPATCHED | WAITING | EXPIRED | REJECTED

``DISPATCHING -> WAITING`` / ``EXPIRED`` are only for a dispatch attempt that
definitively did not send; an uncertain send belongs to the pending-marker
UNKNOWN path.  A restart whose committed marker was absent from a complete
same-day order query ends ``DISPATCHING -> REJECTED``
(``restart_not_found_at_venue``, D63-38 a): it is never re-queued.  ``DISPATCHED``, ``CANCELLED``, ``EXPIRED`` and ``REJECTED`` are
terminal and move to a bounded history (last 500).
Such a restart-rejected order is re-notified to its strategy on every
restart until :meth:`WaitingOrderStore.record_takeover` noted the takeover
(``facts.taken_over_at_utc``).
"""

from __future__ import annotations

import copy
import hashlib
import os
from typing import Any, Callable, List, Mapping, Optional, Sequence

from ._common import (
    StatePaths,
    ensure_no_secret_keys,
    get_logger,
    is_finite_number,
    is_sha256_hex,
    is_strict_int,
    is_text,
    is_trading_day,
    is_uuid4,
    json_safe_copy,
    new_uuid4,
    parse_aware_iso,
    utc_compact,
    utc_now_iso,
)
from .atomic import (
    LiveStateCorrupt,
    LiveStateError,
    LiveStateIdentityMismatch,
    LiveStateNotInitialized,
    atomic_write_bytes,
    atomic_write_json,
    dumps_json,
    fsync_directory,
    read_json,
    read_json_bytes,
)
from .audit import append_audit
from .waiting_notify import (
    PAUSE_NOTIFICATION_STATUSES,
    build_pause_event,
    notify_pause_event,
)

__all__ = (
    "CALENDAR_DISPOSITIONS",
    "MIGRATION_STATUSES",
    "PAUSE_NOTIFICATION_STATUSES",
    "WAITING_STATUSES",
    "WAITING_VERSION",
    "WaitingOrderStore",
)

_log = get_logger(__name__)

WAITING_VERSION = 2
LEGACY_WAITING_VERSIONS = frozenset({1})
HISTORY_LIMIT = 500
_TRANSITIONS_LIMIT = 32

# D67-17 migration bookkeeping.  One marker per strategy directory; the audit
# log keeps the historical events (backup, complete, recovered, rollback).
BACKUPS_DIRNAME = "backups"
MIGRATION_MARKER_FILE = "waiting_migration.json"
MIGRATION_VERSION = 1
MIGRATION_STATUSES = ("in_progress", "complete", "rolled_back")
_PAUSE_NOTIFICATION_KEYS = 8

# An active order that cannot be scheduled/resumed keeps its status; this
# records why (D67-15).  The live path never rewrites the original target.
CALENDAR_DISPOSITIONS = frozenset(
    {
        "legacy_unbound",  # version-1 record: creation calendar version unknown
        "calendar_ref_missing",  # the record/session has no usable reference
        "calendar_ref_changed",  # the configured calendar differs from creation
        "calendar_unavailable",  # the current session answer cannot be read
    }
)

WAITING_STATUSES = ("WAITING", "DISPATCHING", "DISPATCHED", "CANCELLED", "EXPIRED", "REJECTED")
_TERMINAL = frozenset({"DISPATCHED", "CANCELLED", "EXPIRED", "REJECTED"})
_TRANSITIONS = {
    "WAITING": frozenset({"DISPATCHING", "CANCELLED", "EXPIRED", "REJECTED"}),
    "DISPATCHING": frozenset({"DISPATCHED", "WAITING", "EXPIRED", "REJECTED"}),
}

SIDES = frozenset({"buy", "sell"})
EXECTYPES = frozenset(
    {"Market", "Close", "Limit", "Stop", "StopLimit", "StopTrail", "StopTrailLimit"}
)
OFFSETS = frozenset({"open", "close", "close_today", "close_yesterday"})
POSITION_SIDES = frozenset({"long", "short", "net", "both"})
VALID_KINDS = frozenset({"unspecified", "day", "absolute", "timedelta"})

_REQUIRED = frozenset(
    {
        "local_seq",
        "symbol",
        "exchange_name",
        "side",
        "size",
        "exectype",
        "valid_intent",
        "target_session",
    }
)
_OPTIONAL = frozenset(
    {
        "waiting_id",
        "bt_ref",
        "price",
        "pricelimit",
        "offset",
        "position_side",
        "created_at_utc",
        "status",
        "extra",
    }
)
_STORED = _REQUIRED | _OPTIONAL | {"updated_at_utc", "facts", "transitions"}


def initial_waiting_state(strategy_uuid: str) -> dict:
    return {
        "version": WAITING_VERSION,
        "strategy_uuid": strategy_uuid,
        "orders": {},
        "history": [],
    }


_TARGET_SESSION_KEYS = frozenset({"trading_day", "continuous_start_utc", "session_end_utc"})
_TARGET_SESSION_BOUND_KEYS = _TARGET_SESSION_KEYS | {"calendar_ref"}
_CALENDAR_REF_MAX_LEN = 256


def _check_target_session(value: Any, path: str) -> None:
    """A target session is either old/unbound (version 1) or calendar-bound."""
    if not isinstance(value, dict):
        raise LiveStateCorrupt(path, "invalid_target_session")
    keys = set(value)
    if keys not in (_TARGET_SESSION_KEYS, _TARGET_SESSION_BOUND_KEYS):
        raise LiveStateCorrupt(path, "invalid_target_session")
    if "calendar_ref" in value and not is_text(
        value["calendar_ref"], max_len=_CALENDAR_REF_MAX_LEN
    ):
        raise LiveStateCorrupt(path, "invalid_calendar_ref")


def _check_stored(order: Any, path: str, *, terminal: bool) -> None:
    if not isinstance(order, dict) or set(order) != _STORED:
        raise LiveStateCorrupt(path, "invalid_waiting_order")
    if not is_uuid4(order["waiting_id"]):
        raise LiveStateCorrupt(path, "invalid_waiting_id")
    _check_target_session(order["target_session"], path)
    status = order["status"]
    if status not in WAITING_STATUSES or (status in _TERMINAL) != terminal:
        raise LiveStateCorrupt(path, "invalid_waiting_status")


def validate_waiting_state(raw: Any, path: str, strategy_uuid: Optional[str]) -> dict:
    if not isinstance(raw, dict):
        raise LiveStateCorrupt(path, "not_a_mapping")
    if set(raw) != {"version", "strategy_uuid", "orders", "history"}:
        raise LiveStateCorrupt(path, "unexpected_keys")
    supported = LEGACY_WAITING_VERSIONS | {WAITING_VERSION}
    if type(raw["version"]) is not int or raw["version"] not in supported:
        raise LiveStateCorrupt(path, "version_unsupported")
    if not is_uuid4(raw["strategy_uuid"]):
        raise LiveStateCorrupt(path, "invalid_field:strategy_uuid")
    if not isinstance(raw["orders"], dict) or not isinstance(raw["history"], list):
        raise LiveStateCorrupt(path, "invalid_structure")
    for waiting_id, order in raw["orders"].items():
        _check_stored(order, path, terminal=False)
        if order["waiting_id"] != waiting_id:
            raise LiveStateCorrupt(path, "waiting_key_mismatch")
    for order in raw["history"]:
        _check_stored(order, path, terminal=True)
    if strategy_uuid is not None and raw["strategy_uuid"] != strategy_uuid:
        raise LiveStateIdentityMismatch("strategy_uuid_mismatch", "waiting_orders.json")
    return raw


def is_pristine_waiting(raw: Any, path: str) -> bool:
    try:
        state = validate_waiting_state(raw, path, None)
    except LiveStateError:
        return False
    return not state["orders"] and not state["history"]


_MARKER_REQUIRED = frozenset(
    {
        "version",
        "strategy_uuid",
        "status",
        "source_version",
        "target_version",
        "backup_file",
        "backup_sha256",
        "started_at_utc",
        "orders_count",
        "history_count",
    }
)
_MARKER_OPTIONAL = frozenset(
    {
        "completed_at_utc",
        "restored_at_utc",
        "rolled_back_at_utc",
        "migrated_sha256",
        "operator",
        "reason",
    }
)


def _check_marker(raw: Any, path: str, strategy_uuid: Optional[str]) -> None:
    """Validate the D67-17 migration marker; never repair or guess."""
    if not isinstance(raw, dict) or not (
        _MARKER_REQUIRED <= set(raw) <= (_MARKER_REQUIRED | _MARKER_OPTIONAL)
    ):
        raise LiveStateCorrupt(path, "migration_marker_invalid")
    if type(raw["version"]) is not int or raw["version"] != MIGRATION_VERSION:
        raise LiveStateCorrupt(path, "migration_marker_invalid")
    if not is_uuid4(raw["strategy_uuid"]):
        raise LiveStateCorrupt(path, "migration_marker_invalid")
    if raw["status"] not in MIGRATION_STATUSES:
        raise LiveStateCorrupt(path, "migration_marker_invalid")
    if (
        type(raw["source_version"]) is not int
        or raw["source_version"] not in LEGACY_WAITING_VERSIONS
    ):
        raise LiveStateCorrupt(path, "migration_marker_invalid")
    if type(raw["target_version"]) is not int or raw["target_version"] != WAITING_VERSION:
        raise LiveStateCorrupt(path, "migration_marker_invalid")
    name = raw["backup_file"]
    if not is_text(name, max_len=200) or os.path.basename(name) != name or name in (".", ".."):
        raise LiveStateCorrupt(path, "migration_marker_invalid")
    if not is_sha256_hex(raw["backup_sha256"]):
        raise LiveStateCorrupt(path, "migration_marker_invalid")
    if parse_aware_iso(raw["started_at_utc"]) is None:
        raise LiveStateCorrupt(path, "migration_marker_invalid")
    for key in ("orders_count", "history_count"):
        if not is_strict_int(raw[key], minimum=0):
            raise LiveStateCorrupt(path, "migration_marker_invalid")
    if "migrated_sha256" in raw and not is_sha256_hex(raw["migrated_sha256"]):
        raise LiveStateCorrupt(path, "migration_marker_invalid")
    for key in ("completed_at_utc", "restored_at_utc", "rolled_back_at_utc"):
        if key in raw and parse_aware_iso(raw[key]) is None:
            raise LiveStateCorrupt(path, "migration_marker_invalid")
    if "operator" in raw and not is_text(raw["operator"], max_len=128):
        raise LiveStateCorrupt(path, "migration_marker_invalid")
    if "reason" in raw and not is_text(raw["reason"], max_len=512):
        raise LiveStateCorrupt(path, "migration_marker_invalid")
    if strategy_uuid is not None and raw["strategy_uuid"] != strategy_uuid:
        raise LiveStateIdentityMismatch("strategy_uuid_mismatch", MIGRATION_MARKER_FILE)


def _require_operator_reason(operator: Any, reason: Any) -> None:
    if not is_text(operator, max_len=128):
        raise LiveStateError("operator_required")
    if not is_text(reason, max_len=512):
        raise LiveStateError("reason_required")


def _read_file_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


class _LoadedState:
    """A validated waiting state together with its exact on-disk bytes."""

    __slots__ = ("state", "version", "raw")

    def __init__(self, state: dict, raw: bytes) -> None:
        self.state = state
        self.version = state["version"]
        self.raw = raw


def _bad(field: str) -> LiveStateError:
    return LiveStateError("waiting_invalid", field)


def _normalize_valid_intent(value: Any) -> dict:
    if not isinstance(value, Mapping) or set(value) != {"kind", "value"}:
        raise _bad("valid_intent")
    kind = value["kind"]
    raw = value["value"]
    if kind not in VALID_KINDS:
        raise _bad("valid_intent.kind")
    if kind in ("unspecified", "day"):
        if raw is not None:
            raise _bad("valid_intent.value")
    elif kind == "absolute":
        if parse_aware_iso(raw) is None:
            raise _bad("valid_intent.value")
    elif not is_finite_number(raw) or raw <= 0:
        raise _bad("valid_intent.value")
    return {"kind": kind, "value": raw}


def _normalize_target_session(value: Any) -> dict:
    if not isinstance(value, Mapping) or set(value) != _TARGET_SESSION_BOUND_KEYS:
        # A new order must carry the versioned calendar reference of the
        # session answer that produced its target; never fall back to a guess.
        raise _bad("target_session")
    if not is_trading_day(value["trading_day"]):
        raise _bad("target_session.trading_day")
    start = parse_aware_iso(value["continuous_start_utc"])
    end = parse_aware_iso(value["session_end_utc"])
    if start is None or end is None or not start < end:
        raise _bad("target_session.window")
    if not is_text(value["calendar_ref"], max_len=_CALENDAR_REF_MAX_LEN):
        raise _bad("target_session.calendar_ref")
    return {key: value[key] for key in sorted(_TARGET_SESSION_BOUND_KEYS)}


def normalize_waiting_order(order: Any) -> dict:
    """Validate a new waiting order; return the stored form (status WAITING)."""
    if not isinstance(order, Mapping):
        raise _bad("order")
    keys = set(order)
    missing = _REQUIRED - keys
    if missing:
        raise _bad(f"missing:{sorted(missing)[0]}")
    unknown = keys - _REQUIRED - _OPTIONAL
    if unknown:
        raise _bad(f"unknown:{sorted(unknown)[0]}")
    waiting_id = order.get("waiting_id")
    if waiting_id is None:
        waiting_id = new_uuid4()
    elif not is_uuid4(waiting_id):
        raise _bad("waiting_id")
    if order.get("status", "WAITING") != "WAITING":
        raise _bad("status")
    if not is_strict_int(order["local_seq"], minimum=1):
        raise _bad("local_seq")
    bt_ref = order.get("bt_ref")
    if bt_ref is not None and not is_strict_int(bt_ref, minimum=1):
        raise _bad("bt_ref")
    for key in ("symbol", "exchange_name"):
        if not is_text(order[key], max_len=128):
            raise _bad(key)
    if order["side"] not in SIDES:
        raise _bad("side")
    size = order["size"]
    if not is_finite_number(size) or size <= 0:
        raise _bad("size")
    exectype = order["exectype"]
    if exectype not in EXECTYPES:
        raise _bad("exectype")
    price = order.get("price")
    pricelimit = order.get("pricelimit")
    for key, value in (("price", price), ("pricelimit", pricelimit)):
        if value is not None and not is_finite_number(value):
            raise _bad(key)
    if exectype in ("Limit", "Stop", "StopLimit") and price is None:
        raise _bad("price_required")
    if exectype == "StopLimit" and pricelimit is None:
        raise _bad("pricelimit_required")
    offset = order.get("offset")
    if offset is not None and offset not in OFFSETS:
        raise _bad("offset")
    position_side = order.get("position_side")
    if position_side is not None and position_side not in POSITION_SIDES:
        raise _bad("position_side")
    created_at = order.get("created_at_utc")
    if created_at is None:
        created_at = utc_now_iso()
    elif parse_aware_iso(created_at) is None:
        raise _bad("created_at_utc")
    extra = order.get("extra")
    extra = {} if extra is None else json_safe_copy(extra, "extra")
    if not isinstance(extra, dict):
        raise _bad("extra")
    stored = {
        "waiting_id": waiting_id,
        "local_seq": order["local_seq"],
        "bt_ref": bt_ref,
        "symbol": order["symbol"],
        "exchange_name": order["exchange_name"],
        "side": order["side"],
        "size": size,
        "exectype": exectype,
        "price": price,
        "pricelimit": pricelimit,
        "offset": offset,
        "position_side": position_side,
        "valid_intent": _normalize_valid_intent(order["valid_intent"]),
        "target_session": _normalize_target_session(order["target_session"]),
        "created_at_utc": created_at,
        "updated_at_utc": created_at,
        "status": "WAITING",
        "extra": extra,
        "facts": {},
        "transitions": [],
    }
    ensure_no_secret_keys(stored, "waiting")
    return stored


class WaitingOrderStore:
    """Durable waiting orders of one strategy instance (no in-memory cache)."""

    def __init__(
        self,
        strategy_dir: Any,
        strategy_uuid: str,
        *,
        lock_timeout: float = 10.0,
        history_limit: int = HISTORY_LIMIT,
        pause_notifier: Optional[Callable[[dict], str]] = None,
    ) -> None:
        if not is_uuid4(strategy_uuid):
            raise LiveStateError("invalid_strategy_uuid")
        if not is_strict_int(history_limit, minimum=1):
            raise ValueError("history_limit must be a positive int")
        if pause_notifier is not None and not callable(pause_notifier):
            raise ValueError("pause_notifier must be callable")
        self.paths = StatePaths(strategy_dir)
        self.strategy_uuid = strategy_uuid
        self.lock_timeout = lock_timeout
        self.history_limit = history_limit
        self._pause_notifier = pause_notifier

    @property
    def path(self) -> str:
        return self.paths.waiting

    @property
    def backups_dir(self) -> str:
        """Directory of D67-17 migration backups, inside ``state/``."""
        return os.path.join(self.paths.state_dir, BACKUPS_DIRNAME)

    @property
    def migration_marker_path(self) -> str:
        """Marker file naming the current (or last) migration and its backup."""
        return os.path.join(self.backups_dir, MIGRATION_MARKER_FILE)

    def _lock(self):
        from .coordination import CoordinatedFileLock

        return CoordinatedFileLock(self.paths, self.paths.waiting_lock, timeout=self.lock_timeout)

    def _read(self) -> _LoadedState:
        """Read, validate and return the state plus the bytes that produced it."""
        try:
            raw_bytes, parsed = read_json_bytes(self.paths.waiting)
        except FileNotFoundError:
            raise LiveStateNotInitialized(self.paths.waiting) from None
        state = validate_waiting_state(parsed, self.paths.waiting, self.strategy_uuid)
        return _LoadedState(state, raw_bytes)

    def _load(self) -> dict:
        return self._read().state

    def _store(
        self,
        state: dict,
        *,
        source_version: Optional[int] = None,
        source_bytes: Optional[bytes] = None,
    ) -> None:
        """Persist ``state``; a legacy source is backed up and migrated first.

        A version-1 file is never rewritten without a verified backup
        (D67-17).  The migration write keeps every record and does not apply
        the history bound; later ordinary writes do.
        """
        if source_version is not None and source_version != WAITING_VERSION:
            self._run_migration(
                state,
                source_bytes,
                source_version=source_version,
                operator="automatic",
                reason="waiting_store_write",
            )
            return
        state["version"] = WAITING_VERSION
        overflow = len(state["history"]) - self.history_limit
        if overflow > 0:
            del state["history"][:overflow]
        atomic_write_json(self.paths.waiting, state)

    # -- D67-17 migration ---------------------------------------------------

    def _read_marker(self) -> Optional[dict]:
        path = self.migration_marker_path
        try:
            raw = read_json(path)
        except FileNotFoundError:
            return None
        _check_marker(raw, path, self.strategy_uuid)
        return raw

    def _write_marker(self, marker: dict) -> None:
        atomic_write_json(self.migration_marker_path, marker)

    def _backup_path(self, marker: Mapping[str, Any]) -> str:
        return os.path.join(self.backups_dir, marker["backup_file"])

    def _verify_backup(self, marker: Mapping[str, Any]) -> bytes:
        path = self._backup_path(marker)
        try:
            raw_bytes = _read_file_bytes(path)
        except FileNotFoundError:
            raise LiveStateCorrupt(path, "migration_backup_missing") from None
        if hashlib.sha256(raw_bytes).hexdigest() != marker["backup_sha256"]:
            raise LiveStateCorrupt(path, "migration_backup_digest_mismatch")
        return raw_bytes

    def _migration_summary(self, marker: Mapping[str, Any], **extra: Any) -> dict:
        view = {
            "status": marker["status"],
            "source_version": marker["source_version"],
            "target_version": marker["target_version"],
            "backup_file": marker["backup_file"],
            "backup_sha256": marker["backup_sha256"],
            "orders_count": marker["orders_count"],
            "history_count": marker["history_count"],
            "started_at_utc": marker["started_at_utc"],
        }
        for key in ("completed_at_utc", "restored_at_utc", "rolled_back_at_utc", "migrated_sha256"):
            if key in marker:
                view[key] = marker[key]
        view.update(extra)
        return view

    def _run_migration(
        self,
        state: dict,
        legacy_bytes: Optional[bytes],
        *,
        source_version: int,
        operator: str,
        reason: str,
    ) -> dict:
        """Back up, record and perform a version upgrade of ``state`` in place.

        The caller holds the waiting lock.  Any failure before the atomic
        replace leaves the original file untouched; the marker tells a later
        :meth:`recover_migration` what happened.
        """
        if type(legacy_bytes) is not bytes:
            raise LiveStateError("live_state_error", "migration_without_source_bytes")
        backup_sha256 = hashlib.sha256(legacy_bytes).hexdigest()
        backup_file = f"waiting_orders.v{source_version}.{utc_compact()}.{backup_sha256[:12]}.json"
        if not os.path.isdir(self.backups_dir):
            os.makedirs(self.backups_dir, mode=0o700, exist_ok=True)
            fsync_directory(self.paths.state_dir)
        backup_path = os.path.join(self.backups_dir, backup_file)
        atomic_write_bytes(backup_path, legacy_bytes)
        if hashlib.sha256(_read_file_bytes(backup_path)).hexdigest() != backup_sha256:
            raise LiveStateCorrupt(backup_path, "migration_backup_digest_mismatch")
        marker = {
            "version": MIGRATION_VERSION,
            "strategy_uuid": self.strategy_uuid,
            "status": "in_progress",
            "source_version": source_version,
            "target_version": WAITING_VERSION,
            "backup_file": backup_file,
            "backup_sha256": backup_sha256,
            "started_at_utc": utc_now_iso(),
            "orders_count": len(state["orders"]),
            "history_count": len(state["history"]),
            "operator": operator,
            "reason": reason,
        }
        self._write_marker(marker)
        append_audit(
            self.paths.strategy_dir,
            {
                "event": "waiting_migration_backup",
                "operator": operator,
                "reason": reason,
                "backup_file": backup_file,
                "backup_sha256": backup_sha256,
                "source_version": source_version,
                "target_version": WAITING_VERSION,
                "orders_count": marker["orders_count"],
                "history_count": marker["history_count"],
            },
        )
        migrated = dict(state, version=WAITING_VERSION)
        payload = dumps_json(migrated).encode("utf-8")
        try:
            atomic_write_bytes(self.paths.waiting, payload)
            written, parsed = read_json_bytes(self.paths.waiting)
            checked = validate_waiting_state(parsed, self.paths.waiting, self.strategy_uuid)
            if (
                checked["version"] != WAITING_VERSION
                or len(checked["orders"]) != len(migrated["orders"])
                or len(checked["history"]) != len(migrated["history"])
            ):
                raise LiveStateCorrupt(self.paths.waiting, "migration_verification_failed")
        except BaseException:
            self._audit_best_effort(
                {
                    "event": "waiting_migration_failed",
                    "operator": operator,
                    "reason": reason,
                    "backup_file": backup_file,
                    "backup_sha256": backup_sha256,
                }
            )
            raise
        marker["status"] = "complete"
        marker["completed_at_utc"] = utc_now_iso()
        marker["migrated_sha256"] = hashlib.sha256(written).hexdigest()
        self._write_marker(marker)
        append_audit(
            self.paths.strategy_dir,
            {
                "event": "waiting_migration_complete",
                "operator": operator,
                "reason": reason,
                "backup_sha256": backup_sha256,
                "migrated_sha256": marker["migrated_sha256"],
            },
        )
        return marker

    def _audit_best_effort(self, record: dict) -> None:
        try:
            append_audit(self.paths.strategy_dir, record)
        except Exception as exc:
            _log.warning(
                "waiting audit append failed: %s", getattr(exc, "code", type(exc).__name__)
            )

    def migration_status(self) -> Optional[dict]:
        """Read-only view of the migration marker, or ``None`` if never migrated."""
        marker = self._read_marker()
        return copy.deepcopy(marker) if marker is not None else None

    def migrate(self, *, operator: str, reason: str) -> dict:
        """Explicitly migrate a version-1 file (same backup path as a write).

        An already current file is reported, never rewritten.  Unknown or
        newer versions raise ``state_corrupt``/``version_unsupported`` and the
        file is left untouched.
        """
        _require_operator_reason(operator, reason)
        with self._lock():
            loaded = self._read()
            if loaded.version == WAITING_VERSION:
                return {
                    "status": "already_current",
                    "changed": False,
                    "migration": self.migration_status(),
                }
            marker = self._run_migration(
                loaded.state,
                loaded.raw,
                source_version=loaded.version,
                operator=operator,
                reason=reason,
            )
        return {"status": "complete", "changed": True, "migration": self._migration_summary(marker)}

    def recover_migration(self, *, operator: str, reason: str) -> dict:
        """Converge an interrupted migration without discarding records.

        ``in_progress`` is resolved to exactly one of: the completed new file
        (finalize the marker), the original replayed to version 2 from the
        verified backup, or the original restored because the state file was
        gone.  Any other situation - a corrupt backup, a changed or unreadable
        state file - is refused with a finite ``state_corrupt`` reason and
        nothing is modified.
        """
        _require_operator_reason(operator, reason)
        with self._lock():
            marker = self._read_marker()
            if marker is None:
                raise LiveStateError("marker_not_found", "waiting_migration")
            if marker["status"] != "in_progress":
                return {
                    "status": marker["status"],
                    "changed": False,
                    "recovery": "none",
                    "migration": self._migration_summary(marker),
                }
            backup_bytes = self._verify_backup(marker)
            try:
                current_bytes, parsed = read_json_bytes(self.paths.waiting)
            except FileNotFoundError:
                atomic_write_bytes(self.paths.waiting, backup_bytes)
                if (
                    hashlib.sha256(_read_file_bytes(self.paths.waiting)).hexdigest()
                    != marker["backup_sha256"]
                ):
                    raise LiveStateCorrupt(
                        self.paths.waiting, "migration_verification_failed"
                    ) from None
                marker["status"] = "rolled_back"
                marker["restored_at_utc"] = utc_now_iso()
                marker["operator"] = operator
                marker["reason"] = reason
                self._write_marker(marker)
                append_audit(
                    self.paths.strategy_dir,
                    {
                        "event": "waiting_migration_recovered",
                        "operator": operator,
                        "reason": reason,
                        "outcome": "restored",
                        "backup_sha256": marker["backup_sha256"],
                    },
                )
                return {
                    "status": "rolled_back",
                    "changed": True,
                    "recovery": "restored",
                    "migration": self._migration_summary(marker),
                }
            except LiveStateCorrupt:
                # Unreadable current file: refuse, change nothing.
                raise LiveStateCorrupt(self.paths.waiting, "migration_conflict") from None
            try:
                checked = validate_waiting_state(parsed, self.paths.waiting, self.strategy_uuid)
            except LiveStateCorrupt:
                raise LiveStateCorrupt(self.paths.waiting, "migration_conflict") from None
            if checked["version"] == WAITING_VERSION:
                marker["status"] = "complete"
                marker["completed_at_utc"] = utc_now_iso()
                marker["migrated_sha256"] = hashlib.sha256(current_bytes).hexdigest()
                marker["operator"] = operator
                marker["reason"] = reason
                self._write_marker(marker)
                append_audit(
                    self.paths.strategy_dir,
                    {
                        "event": "waiting_migration_recovered",
                        "operator": operator,
                        "reason": reason,
                        "outcome": "completed",
                        "migrated_sha256": marker["migrated_sha256"],
                    },
                )
                return {
                    "status": "complete",
                    "changed": True,
                    "recovery": "completed",
                    "migration": self._migration_summary(marker),
                }
            if (
                checked["version"] in LEGACY_WAITING_VERSIONS
                and hashlib.sha256(current_bytes).hexdigest() == marker["backup_sha256"]
            ):
                migrated = dict(checked, version=WAITING_VERSION)
                atomic_write_bytes(self.paths.waiting, dumps_json(migrated).encode("utf-8"))
                written, reparsed = read_json_bytes(self.paths.waiting)
                validate_waiting_state(reparsed, self.paths.waiting, self.strategy_uuid)
                marker["status"] = "complete"
                marker["completed_at_utc"] = utc_now_iso()
                marker["migrated_sha256"] = hashlib.sha256(written).hexdigest()
                marker["operator"] = operator
                marker["reason"] = reason
                self._write_marker(marker)
                append_audit(
                    self.paths.strategy_dir,
                    {
                        "event": "waiting_migration_recovered",
                        "operator": operator,
                        "reason": reason,
                        "outcome": "replayed",
                        "backup_sha256": marker["backup_sha256"],
                        "migrated_sha256": marker["migrated_sha256"],
                    },
                )
                return {
                    "status": "complete",
                    "changed": True,
                    "recovery": "replayed",
                    "migration": self._migration_summary(marker),
                }
            raise LiveStateCorrupt(self.paths.waiting, "migration_conflict")

    def rollback_migration(self, *, operator: str, reason: str) -> dict:
        """Restore the verified pre-migration file; refuse an unsafe rollback.

        Allowed only for a ``complete`` migration whose current file is still
        byte-identical to the migrated file recorded in the marker.  Any later
        write (a new order, a transition, facts) makes the rollback unsafe and
        it is refused with ``state_corrupt``/``rollback_unsafe`` so post-upgrade
        facts are never overwritten.  The restored file is the exact original
        version-1 bytes, which the old reader accepts.
        """
        _require_operator_reason(operator, reason)
        with self._lock():
            marker = self._read_marker()
            if marker is None:
                raise LiveStateError("marker_not_found", "waiting_migration")
            if marker["status"] == "rolled_back":
                return {
                    "status": "rolled_back",
                    "changed": False,
                    "rollback": "none",
                    "migration": self._migration_summary(marker),
                }
            if marker["status"] != "complete":
                raise LiveStateCorrupt(self.migration_marker_path, "migration_not_complete")
            backup_bytes = self._verify_backup(marker)
            try:
                current_bytes = _read_file_bytes(self.paths.waiting)
            except FileNotFoundError:
                raise LiveStateCorrupt(self.paths.waiting, "rollback_unsafe") from None
            if hashlib.sha256(current_bytes).hexdigest() != marker.get("migrated_sha256"):
                raise LiveStateCorrupt(self.paths.waiting, "rollback_unsafe")
            # The backup must be the readable version-1 file it claims to be.
            backup_state = validate_waiting_state(
                read_json(self._backup_path(marker)), self._backup_path(marker), self.strategy_uuid
            )
            if backup_state["version"] not in LEGACY_WAITING_VERSIONS:
                raise LiveStateCorrupt(self._backup_path(marker), "migration_backup_invalid")
            atomic_write_bytes(self.paths.waiting, backup_bytes)
            if (
                hashlib.sha256(_read_file_bytes(self.paths.waiting)).hexdigest()
                != marker["backup_sha256"]
            ):
                raise LiveStateCorrupt(self.paths.waiting, "migration_verification_failed")
            marker["status"] = "rolled_back"
            marker["rolled_back_at_utc"] = utc_now_iso()
            marker["operator"] = operator
            marker["reason"] = reason
            self._write_marker(marker)
            append_audit(
                self.paths.strategy_dir,
                {
                    "event": "waiting_migration_rollback",
                    "operator": operator,
                    "reason": reason,
                    "backup_file": marker["backup_file"],
                    "backup_sha256": marker["backup_sha256"],
                    "migrated_sha256": marker["migrated_sha256"],
                },
            )
        return {
            "status": "rolled_back",
            "changed": True,
            "rollback": "restored",
            "migration": self._migration_summary(marker),
        }

    def add(self, order: Mapping[str, Any]) -> str:
        """Durably add a WAITING order; return its ``waiting_id``.

        Raises ``LiveStateError("waiting_invalid")`` for invalid input,
        ``("waiting_duplicate")`` for a reused ``waiting_id`` or a
        ``local_seq`` that already has a non-terminal waiting order, and any
        lock/corruption/I/O error (nothing is stored then).
        """
        stored = normalize_waiting_order(order)
        with self._lock():
            loaded = self._read()
            state = loaded.state
            waiting_id = stored["waiting_id"]
            if waiting_id in state["orders"] or any(
                item["waiting_id"] == waiting_id for item in state["history"]
            ):
                raise LiveStateError("waiting_duplicate", "waiting_id")
            for item in state["orders"].values():
                if item["local_seq"] == stored["local_seq"]:
                    raise LiveStateError("waiting_duplicate", "local_seq")
            state["orders"][waiting_id] = stored
            self._store(state, source_version=loaded.version, source_bytes=loaded.raw)
        return waiting_id

    def transition(self, waiting_id: str, from_status: str, to_status: str, **facts: Any) -> bool:
        """Compare-and-set ``from_status -> to_status``; merge ``facts``.

        Returns ``False`` if the order is unknown or its current status is not
        ``from_status``.  Raises ``LiveStateError("waiting_transition_illegal")``
        for a pair outside the status machine, ``value_not_json_safe`` /
        ``secret_field_rejected`` for bad facts, and lock/corruption/I/O
        errors (the transition is then not durable).
        """
        allowed = _TRANSITIONS.get(from_status)
        if allowed is None or to_status not in allowed:
            raise LiveStateError("waiting_transition_illegal", f"{from_status}->{to_status}")
        cleaned = json_safe_copy(dict(facts), "facts")
        ensure_no_secret_keys(cleaned, "facts")
        with self._lock():
            loaded = self._read()
            state = loaded.state
            order = state["orders"].get(waiting_id)
            if order is None or order["status"] != from_status:
                return False
            now = utc_now_iso()
            order["status"] = to_status
            order["updated_at_utc"] = now
            order["facts"].update(cleaned)
            order["transitions"].append({"from": from_status, "to": to_status, "at_utc": now})
            del order["transitions"][:-_TRANSITIONS_LIMIT]
            if to_status in _TERMINAL:
                del state["orders"][waiting_id]
                state["history"].append(order)
            self._store(state, source_version=loaded.version, source_bytes=loaded.raw)
        return True

    def record_takeover(self, waiting_id: str) -> bool:
        """Durably note that the strategy took over a restart-rejected waiting order.

        Only a REJECTED order (``restart_not_found_at_venue``, D63-38 a) has
        a notice the host re-delivers on every restart until this fact
        (``facts.taken_over_at_utc``) exists.  The first time is kept
        (idempotent ``True``); ``False`` (never raises) for any other order
        or when the fact cannot be written.
        """
        try:
            with self._lock():
                loaded = self._read()
                state = loaded.state
                order = next(
                    (
                        item
                        for item in reversed(state["history"])
                        if item["waiting_id"] == waiting_id
                    ),
                    None,
                )
                if (
                    order is None
                    or order["status"] != "REJECTED"
                    or order["facts"].get("reason") != "restart_not_found_at_venue"
                ):
                    return False
                if order["facts"].get("taken_over_at_utc"):
                    return True
                order["facts"]["taken_over_at_utc"] = utc_now_iso()
                self._store(state, source_version=loaded.version, source_bytes=loaded.raw)
            return True
        except Exception as exc:
            _log.warning(
                "waiting notice takeover not recorded: %s",
                getattr(exc, "code", type(exc).__name__),
            )
            return False

    def record_calendar_disposition(
        self,
        waiting_id: str,
        disposition: str,
        *,
        observed_calendar_ref: Optional[str] = None,
    ) -> bool:
        """Durably record why an active waiting order is not resumed (D67-15).

        The status, original target and order identity are never changed.  An
        unknown reason raises ``LiveStateError("calendar_disposition_invalid")``;
        I/O, lock and corruption problems are logged and return ``False`` (the
        caller still refuses to dispatch in memory).  Repeating the same
        disposition keeps the first timestamp; ``True`` is returned then too.

        A newly recorded pause emits one typed, bounded notice (see
        :mod:`backtrader.live_state.waiting_notify`), deduplicated durably per
        order, reason and calendar version.  A notification problem is stored
        as a finite ``facts.pause_notification_status``; it never changes the
        order state and never raises.
        """
        if disposition not in CALENDAR_DISPOSITIONS:
            raise LiveStateError("calendar_disposition_invalid", disposition)
        if observed_calendar_ref is not None and not is_text(
            observed_calendar_ref, max_len=_CALENDAR_REF_MAX_LEN
        ):
            raise LiveStateError("calendar_disposition_invalid", "observed_calendar_ref")
        event = None
        try:
            with self._lock():
                loaded = self._read()
                state = loaded.state
                order = state["orders"].get(waiting_id)
                if order is None:
                    return False
                facts = order["facts"]
                if (
                    facts.get("calendar_disposition") == disposition
                    and facts.get("observed_calendar_ref") == observed_calendar_ref
                ):
                    return True
                now = utc_now_iso()
                facts["calendar_disposition"] = disposition
                facts["calendar_disposition_at_utc"] = now
                if observed_calendar_ref is not None:
                    facts["observed_calendar_ref"] = observed_calendar_ref
                event = self._plan_pause_notification(
                    order, disposition, observed_calendar_ref, now
                )
                order["updated_at_utc"] = now
                self._store(state, source_version=loaded.version, source_bytes=loaded.raw)
        except Exception as exc:
            _log.warning(
                "waiting calendar disposition not recorded: %s",
                getattr(exc, "code", type(exc).__name__),
            )
            return False
        if event is not None:
            # Outside the lock: a slow or broken notifier must not hold state.
            self._record_pause_notification(waiting_id, event)
        return True

    def _plan_pause_notification(
        self,
        order: dict,
        disposition: str,
        observed_calendar_ref: Optional[str],
        now: str,
    ) -> Optional[dict]:
        """Mark a new pause notice for sending; ``None`` when already notified."""
        event = build_pause_event(order, self.strategy_uuid, disposition, observed_calendar_ref)
        facts = order["facts"]
        recorded = facts.get("pause_notification_keys")
        keys = list(recorded) if isinstance(recorded, list) else []
        if event["dedup_key"] in keys:
            return None
        keys.append(event["dedup_key"])
        del keys[:-_PAUSE_NOTIFICATION_KEYS]
        facts["pause_notification_keys"] = keys
        facts["pause_notification_status"] = "pending"
        facts["pause_notification_at_utc"] = now
        return event

    def _record_pause_notification(self, waiting_id: str, event: dict) -> None:
        """Send one notice and store its finite status; never raises."""
        notifier = self._pause_notifier or notify_pause_event
        try:
            status = notifier(event)
        except Exception as exc:
            _log.warning(
                "waiting pause notification failed: %s", getattr(exc, "code", type(exc).__name__)
            )
            status = "error"
        if status not in PAUSE_NOTIFICATION_STATUSES or status == "pending":
            status = "error"
        try:
            with self._lock():
                loaded = self._read()
                order = loaded.state["orders"].get(waiting_id)
                if order is None:
                    return
                facts = order["facts"]
                if facts.get("pause_notification_status") != "pending":
                    return  # a newer pause already recorded its own notice
                facts["pause_notification_status"] = status
                order["updated_at_utc"] = utc_now_iso()
                self._store(loaded.state, source_version=loaded.version, source_bytes=loaded.raw)
        except Exception as exc:
            # The status stays "pending" in the durable file: visible, finite,
            # and deliberately not retried automatically.
            _log.warning(
                "waiting pause notification status not recorded: %s",
                getattr(exc, "code", type(exc).__name__),
            )

    def clear_calendar_pause(
        self,
        waiting_id: str,
        *,
        operator: str,
        reason: str,
        evidence: Sequence[str],
        calendar_ref: str,
        trading_day: str,
        continuous_start_utc: str,
        session_end_utc: str,
    ) -> dict:
        """Operator-only clear of a recorded calendar pause (D67-15).

        ``calendar_ref``/``trading_day``/``continuous_start_utc``/
        ``session_end_utc`` are the *current* calendar answer for the order's
        **original** target: they must name the same trading day and the same
        window instants, and carry a usable versioned reference.  A record
        with no original ``calendar_ref`` (legacy/unbound) can never be proven
        and is refused; nothing is guessed.

        Clearing is not a trading authorization and not a resend: the status,
        original target, identity, local sequence and transitions are
        untouched, and no pending marker or dispatch is created.  The caller
        still has to satisfy every other precondition before the order can be
        sent.  Without matching proof the order stays paused and the call
        raises a finite error (``operator_required``/``reason_required``/
        ``evidence_required``/``waiting_invalid``/
        ``calendar_disposition_invalid`` with a finite detail).
        """
        _require_operator_reason(operator, reason)
        if isinstance(evidence, (str, bytes)) or not isinstance(evidence, (list, tuple)):
            raise LiveStateError("evidence_required")
        items = list(evidence)
        if not items or any(not is_text(item, max_len=512) for item in items):
            raise LiveStateError("evidence_required")
        if not is_text(calendar_ref, max_len=_CALENDAR_REF_MAX_LEN):
            raise LiveStateError("calendar_disposition_invalid", "calendar_ref")
        if not is_trading_day(trading_day):
            raise LiveStateError("calendar_disposition_invalid", "trading_day")
        start = parse_aware_iso(continuous_start_utc)
        end = parse_aware_iso(session_end_utc)
        if start is None or end is None or start >= end:
            raise LiveStateError("calendar_disposition_invalid", "target_session")
        with self._lock():
            loaded = self._read()
            state = loaded.state
            order = state["orders"].get(waiting_id)
            if order is None:
                raise LiveStateError("waiting_invalid", "waiting_id")
            target = order["target_session"]
            if "calendar_ref" not in target:
                # No creation version was ever stored: the original target
                # cannot be proven, so the pause is never cleared by guessing.
                raise LiveStateError("calendar_disposition_invalid", "target_not_bound")
            if (
                target["trading_day"] != trading_day
                or parse_aware_iso(target["continuous_start_utc"]) != start
                or parse_aware_iso(target["session_end_utc"]) != end
            ):
                raise LiveStateError("calendar_disposition_invalid", "target_session_mismatch")
            facts = order["facts"]
            disposition = facts.get("calendar_disposition")
            if disposition is None:
                raise LiveStateError("calendar_disposition_invalid", "not_paused")
            audit_record = {
                "event": "waiting_pause_cleared",
                "strategy_uuid": self.strategy_uuid,
                "waiting_id": waiting_id,
                "local_seq": order["local_seq"],
                "bt_ref": order.get("bt_ref"),
                "symbol": order["symbol"],
                "exchange_name": order["exchange_name"],
                "previous_disposition": disposition,
                "observed_calendar_ref": calendar_ref,
                "target_trading_day": target["trading_day"],
                "operator": operator,
                "reason": reason,
                "evidence": items,
            }
            entry = append_audit(self.paths.strategy_dir, audit_record)
            facts.pop("calendar_disposition", None)
            facts.pop("calendar_disposition_at_utc", None)
            facts.pop("observed_calendar_ref", None)
            facts["calendar_pause_cleared"] = {
                "operator": operator,
                "reason": reason,
                "evidence": items,
                "observed_calendar_ref": calendar_ref,
                "previous_disposition": disposition,
                "cleared_at_utc": entry["ts_utc"],
            }
            order["updated_at_utc"] = utc_now_iso()
            try:
                self._store(state, source_version=loaded.version, source_bytes=loaded.raw)
            except BaseException:
                self._audit_best_effort(
                    {
                        "event": "waiting_pause_clear_failed",
                        "strategy_uuid": self.strategy_uuid,
                        "waiting_id": waiting_id,
                        "operator": operator,
                    }
                )
                raise
            return {
                "waiting_id": waiting_id,
                "cleared": True,
                "previous_disposition": disposition,
                "observed_calendar_ref": calendar_ref,
                "cleared_at_utc": entry["ts_utc"],
            }

    def get(self, waiting_id: str) -> Optional[dict]:
        state = self._load()
        order = state["orders"].get(waiting_id)
        if order is not None:
            return copy.deepcopy(order)
        for item in reversed(state["history"]):
            if item["waiting_id"] == waiting_id:
                return copy.deepcopy(item)
        return None

    def active(self) -> List[dict]:
        """WAITING and DISPATCHING orders, FIFO by ``local_seq`` (D62-35)."""
        orders = self._load()["orders"].values()
        return [copy.deepcopy(o) for o in sorted(orders, key=lambda o: o["local_seq"])]

    def waiting(self) -> List[dict]:
        """WAITING orders only, FIFO by ``local_seq``."""
        return [o for o in self.active() if o["status"] == "WAITING"]

    def history(self) -> List[dict]:
        return copy.deepcopy(self._load()["history"])
