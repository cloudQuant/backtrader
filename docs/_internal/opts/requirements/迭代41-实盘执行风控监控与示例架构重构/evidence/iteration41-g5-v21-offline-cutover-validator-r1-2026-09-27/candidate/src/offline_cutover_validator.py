"""Read-only consistency validator for exact, normalized ActionRef snapshots.

This is a local offline design candidate. It does not read or write databases,
allocate identifiers, authorize migration, or provide account authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

SCHEMA = "iteration41.actionref-cutover-consistency.v1"
LEGACY_SOURCE = "legacy_g5_action_reservations"
V21_SOURCE = "v21_action_allocations_joined_commands"
MAX_ACTION_REF = 2_147_483_647
_ALLOWED_STATES = frozenset({"READY", "CLAIMED", "COMPLETED"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_ROW_TEXT_FIELDS = (
    "account_key",
    "trading_day",
    "scope_key",
    "managed_action_id",
    "managed_intent_id",
    "runtime_order_id",
    "order_ref",
    "state",
)


class CutoverRejected(ValueError):
    """Stable fail-closed reason; never signifies migration authorization."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ActionRefEvidence:
    """Normalized join of one legacy reservation or V21 allocation + command."""

    account_key: str
    trading_day: str
    scope_key: str
    managed_action_id: str
    managed_intent_id: str
    runtime_order_id: str
    order_ref: str
    native_action_ref: int
    state: str

    def to_payload(self) -> dict[str, Any]:
        """Convenience serialization; the validator deliberately never calls it."""

        return _safe_row_payload(self)


@dataclass(frozen=True)
class SnapshotManifest:
    """Caller-provided metadata and rows for one immutable exported snapshot."""

    source: Literal[
        "legacy_g5_action_reservations",
        "v21_action_allocations_joined_commands",
    ]
    account_key: str
    snapshot_boundary_id: str
    snapshot_sha256: str
    row_count: int
    complete: bool
    high_water_action_ref: int
    rows: tuple[ActionRefEvidence, ...]
    read_error: str | None = None


@dataclass(frozen=True)
class CutoverBundle:
    schema: str
    account_key: str
    legacy: SnapshotManifest
    v21: SnapshotManifest


@dataclass(frozen=True)
class OfflineConsistencyReport:
    """Pure comparison result; explicitly carries no authority or write grant."""

    account_key: str
    snapshot_boundary_id: str
    matched_action_count: int
    legacy_high_water_action_ref: int
    v21_high_water_action_ref: int
    consistent: Literal[True] = True
    authority: Literal[False] = False
    write_enabled: Literal[False] = False


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _safe_row_payload(row: ActionRefEvidence) -> dict[str, Any]:
    """Copy exact dataclass fields to builtins without invoking row callbacks."""

    if type(row) is not ActionRefEvidence:
        _reject("row_type_invalid")
    payload: dict[str, Any] = {}
    for name in _ROW_TEXT_FIELDS:
        value = object.__getattribute__(row, name)
        if type(value) is not str:
            _reject("row_field_type_invalid")
        payload[name] = value
    action_ref = object.__getattribute__(row, "native_action_ref")
    if type(action_ref) is not int:
        _reject("row_field_type_invalid")
    payload["native_action_ref"] = action_ref
    return payload


def snapshot_digest(
    *,
    source: str,
    account_key: str,
    snapshot_boundary_id: str,
    complete: bool,
    high_water_action_ref: int,
    rows: tuple[ActionRefEvidence, ...],
    read_error: str | None = None,
) -> str:
    """Return a payload integrity digest, not source authentication."""

    if type(source) is not str or type(account_key) is not str:
        _reject("snapshot_digest_input_invalid")
    if type(snapshot_boundary_id) is not str or type(rows) is not tuple:
        _reject("snapshot_digest_input_invalid")
    if type(complete) is not bool or type(high_water_action_ref) is not int:
        _reject("snapshot_digest_input_invalid")
    if not 0 <= high_water_action_ref <= MAX_ACTION_REF:
        _reject("snapshot_digest_input_invalid")
    if read_error is not None and type(read_error) is not str:
        _reject("snapshot_digest_input_invalid")
    row_payloads = [_safe_row_payload(row) for row in rows]
    row_payloads.sort(key=_canonical_bytes)
    payload = {
        "schema": "iteration41.actionref-source-snapshot.v1",
        "source": source,
        "account_key": account_key,
        "snapshot_boundary_id": snapshot_boundary_id,
        "complete": complete,
        "high_water_action_ref": high_water_action_ref,
        "read_error": read_error,
        "row_count": len(rows),
        "rows": row_payloads,
    }
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def make_snapshot(
    *,
    source: Literal[
        "legacy_g5_action_reservations",
        "v21_action_allocations_joined_commands",
    ],
    account_key: str,
    rows: tuple[ActionRefEvidence, ...],
    high_water_action_ref: int,
    snapshot_boundary_id: str = "synthetic-boundary-1",
    complete: bool = True,
    read_error: str | None = None,
) -> SnapshotManifest:
    """Test/design helper that packages typed rows with their digest."""

    return SnapshotManifest(
        source=source,
        account_key=account_key,
        snapshot_boundary_id=snapshot_boundary_id,
        snapshot_sha256=snapshot_digest(
            source=source,
            account_key=account_key,
            snapshot_boundary_id=snapshot_boundary_id,
            complete=complete,
            high_water_action_ref=high_water_action_ref,
            rows=rows,
            read_error=read_error,
        ),
        row_count=len(rows),
        complete=complete,
        high_water_action_ref=high_water_action_ref,
        rows=rows,
        read_error=read_error,
    )


def _reject(code: str) -> None:
    raise CutoverRejected(code)


def _validate_snapshot(
    snapshot: SnapshotManifest, *, expected_source: str, account_key: str
) -> tuple[tuple[dict[str, Any], ...], str, int]:
    if type(snapshot) is not SnapshotManifest:
        _reject("snapshot_type_invalid")

    source = object.__getattribute__(snapshot, "source")
    if type(source) is not str:
        _reject("snapshot_source_type_invalid")
    if source != expected_source:
        _reject("snapshot_source_mismatch")
    snapshot_account = object.__getattribute__(snapshot, "account_key")
    if type(snapshot_account) is not str or snapshot_account != account_key:
        _reject("snapshot_account_mismatch")
    boundary_id = object.__getattribute__(snapshot, "snapshot_boundary_id")
    if type(boundary_id) is not str or not boundary_id:
        _reject("snapshot_boundary_invalid")
    complete = object.__getattribute__(snapshot, "complete")
    if type(complete) is not bool or complete is not True:
        _reject("snapshot_incomplete")
    read_error = object.__getattribute__(snapshot, "read_error")
    if read_error is not None:
        _reject("snapshot_unreadable")
    rows = object.__getattribute__(snapshot, "rows")
    if type(rows) is not tuple:
        _reject("snapshot_rows_invalid")

    # Validate exact row/container types and all primitive field types before
    # hashing, equality, sorting, or using any caller-supplied row behavior.
    row_payloads = tuple(_safe_row_payload(row) for row in rows)
    row_count = object.__getattribute__(snapshot, "row_count")
    if type(row_count) is not int or row_count != len(row_payloads):
        _reject("snapshot_row_count_mismatch")
    high_water = object.__getattribute__(snapshot, "high_water_action_ref")
    if type(high_water) is not int or not 0 <= high_water <= MAX_ACTION_REF:
        _reject("snapshot_high_water_invalid")
    snapshot_sha256 = object.__getattribute__(snapshot, "snapshot_sha256")
    if type(snapshot_sha256) is not str or not _SHA256.fullmatch(snapshot_sha256):
        _reject("snapshot_digest_invalid")
    expected_digest = snapshot_digest(
        source=source,
        account_key=snapshot_account,
        snapshot_boundary_id=boundary_id,
        complete=complete,
        high_water_action_ref=high_water,
        rows=rows,
        read_error=read_error,
    )
    if snapshot_sha256 != expected_digest:
        _reject("snapshot_digest_mismatch")

    seen_refs: set[int] = set()
    seen_actions: set[tuple[str, str]] = set()
    max_row_ref = 0
    for row in row_payloads:
        text_fields = tuple(row[name] for name in _ROW_TEXT_FIELDS if name != "state")
        if any(not value for value in text_fields):
            _reject("row_identity_missing")
        if row["account_key"] != account_key:
            _reject("row_account_mismatch")
        trading_day = row["trading_day"]
        if (
            len(trading_day) != 8
            or not trading_day.isascii()
            or not trading_day.isdigit()
        ):
            _reject("row_trading_day_invalid")
        if not row["runtime_order_id"].startswith("bt-managed-v1:"):
            _reject("row_runtime_order_id_invalid")
        order_ref = row["order_ref"]
        if len(order_ref) != 12 or not order_ref.isascii() or not order_ref.isdigit():
            _reject("row_order_ref_invalid")
        action_ref = row["native_action_ref"]
        if not 1 <= action_ref <= MAX_ACTION_REF:
            _reject("row_action_ref_invalid")
        state = row["state"]
        if state == "UNKNOWN":
            _reject("unknown_action_present")
        if state not in _ALLOWED_STATES:
            _reject("row_state_missing_or_unrecognized")
        ref_key = action_ref
        action_key = (row["scope_key"], row["managed_action_id"])
        if ref_key in seen_refs or action_key in seen_actions:
            _reject("duplicate_or_conflicting_source_identity")
        seen_refs.add(ref_key)
        seen_actions.add(action_key)
        max_row_ref = max(max_row_ref, action_ref)
    if high_water > 0 and not row_payloads:
        _reject("snapshot_high_water_without_rows")
    if high_water < max_row_ref:
        _reject("snapshot_high_water_below_rows")
    return row_payloads, boundary_id, high_water


def _identity(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["account_key"],
        row["trading_day"],
        row["scope_key"],
        row["managed_action_id"],
        row["managed_intent_id"],
        row["runtime_order_id"],
        row["order_ref"],
        row["native_action_ref"],
    )


def validate_cutover(bundle: CutoverBundle) -> OfflineConsistencyReport:
    """Compare exact source identities without mutating either source."""

    if type(bundle) is not CutoverBundle:
        _reject("bundle_type_invalid")
    schema = object.__getattribute__(bundle, "schema")
    if type(schema) is not str:
        _reject("bundle_schema_type_invalid")
    if schema != SCHEMA:
        _reject("bundle_schema_mismatch")
    account_key = object.__getattribute__(bundle, "account_key")
    if type(account_key) is not str or not account_key:
        _reject("bundle_account_invalid")
    legacy = object.__getattribute__(bundle, "legacy")
    v21 = object.__getattribute__(bundle, "v21")
    legacy_rows, legacy_boundary, legacy_high_water = _validate_snapshot(
        legacy, expected_source=LEGACY_SOURCE, account_key=account_key
    )
    v21_rows, v21_boundary, v21_high_water = _validate_snapshot(
        v21, expected_source=V21_SOURCE, account_key=account_key
    )
    if legacy_boundary != v21_boundary:
        _reject("snapshot_boundary_mismatch")
    if v21_high_water < legacy_high_water:
        _reject("v21_high_water_below_legacy_source")

    legacy_by_ref = {row["native_action_ref"]: row for row in legacy_rows}
    v21_by_ref = {row["native_action_ref"]: row for row in v21_rows}
    if legacy_by_ref.keys() != v21_by_ref.keys():
        _reject("mapping_missing_from_one_source")
    for action_ref, legacy_row in legacy_by_ref.items():
        v21_row = v21_by_ref[action_ref]
        if legacy_row["state"] != v21_row["state"]:
            _reject("mapping_state_conflict")
        if _identity(legacy_row) != _identity(v21_row):
            _reject("mapping_field_conflict")

    legacy_by_action = {
        (row["scope_key"], row["managed_action_id"]): row["native_action_ref"]
        for row in legacy_rows
    }
    v21_by_action = {
        (row["scope_key"], row["managed_action_id"]): row["native_action_ref"]
        for row in v21_rows
    }
    if legacy_by_action != v21_by_action:
        _reject("action_reference_conflict")

    return OfflineConsistencyReport(
        account_key=account_key,
        snapshot_boundary_id=legacy_boundary,
        matched_action_count=len(legacy_by_ref),
        legacy_high_water_action_ref=legacy_high_water,
        v21_high_water_action_ref=v21_high_water,
    )


__all__ = [
    "ActionRefEvidence",
    "CutoverBundle",
    "CutoverRejected",
    "OfflineConsistencyReport",
    "SnapshotManifest",
    "make_snapshot",
    "snapshot_digest",
    "validate_cutover",
]
