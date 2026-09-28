"""Account-wide ActionRef snapshot contract for managed CTP cancellation.

This module defines a fail-closed consumer contract only. The repository does
not provide a trusted producer for native ActionRef floors or the merged G5 /
V21 history. Source digest fields are shape-checked only; they are not signed or
authenticated here. An absent producer cannot authorize a cancellation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Tuple


_MAX_NATIVE_ACTION_REF = 2_147_483_647
_MAX_SNAPSHOT_AGE_NS = 250_000_000
_MAX_ALLOCATIONS = 100_000
_ACCOUNT_KEY = re.compile(r"^account:[0-9a-f]{64}$", re.ASCII)
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$", re.ASCII)
_HEX_64 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_LEDGER_SOURCES = ("g5", "v21")
_KNOWN_STATES = frozenset({"READY", "CLAIMED", "COMPLETED", "UNKNOWN"})


class CtpManagedActionRefLedgerError(RuntimeError):
    """Redacted fail-closed result from ActionRef snapshot validation."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("managed CTP ActionRef ledger snapshot is unavailable")


def _reject(code: str) -> None:
    raise CtpManagedActionRefLedgerError(code)


def _digest(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        _reject("snapshot_payload_invalid")
    return hashlib.sha256(payload).hexdigest()


def ctp_managed_action_ref_mapping_sha256(
    allocations: Tuple["CtpManagedActionRefAllocationV1", ...],
) -> str:
    """Hash a canonical, sorted full-account mapping without one giant JSON blob."""

    if (
        type(allocations) is not tuple
        or len(allocations) > _MAX_ALLOCATIONS
        or any(type(row) is not CtpManagedActionRefAllocationV1 for row in allocations)
    ):
        _reject("snapshot_allocations_invalid")
    digest = hashlib.sha256(b"ctp.managed.actionref.mapping.v1\0")
    for row in sorted(
        allocations, key=lambda item: (item.native_action_ref, item.command_id, item.scope_key)
    ):
        encoded = json.dumps(
            row.to_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _require_id(value: Any, code: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        _reject(code)
    return value


@dataclass(frozen=True)
class CtpManagedActionRefAllocationV1:
    """One account-scoped durable native ActionRef mapping."""

    account_key: str
    native_action_ref: int
    command_id: str
    scope_key: str
    managed_action_id: str
    status: str

    def __post_init__(self) -> None:
        if type(self.account_key) is not str or _ACCOUNT_KEY.fullmatch(self.account_key) is None:
            _reject("allocation_account_invalid")
        if (
            type(self.native_action_ref) is not int
            or not 1 <= self.native_action_ref <= _MAX_NATIVE_ACTION_REF
        ):
            _reject("allocation_action_ref_invalid")
        _require_id(self.command_id, "allocation_command_invalid")
        _require_id(self.scope_key, "allocation_scope_invalid")
        _require_id(self.managed_action_id, "allocation_identity_invalid")
        if type(self.status) is not str or self.status not in _KNOWN_STATES:
            _reject("allocation_state_invalid")

    def to_payload(self) -> dict[str, Any]:
        return {
            "account_key": self.account_key,
            "native_action_ref": self.native_action_ref,
            "command_id": self.command_id,
            "scope_key": self.scope_key,
            "managed_action_id": self.managed_action_id,
            "status": self.status,
        }


@dataclass(frozen=True)
class CtpManagedActionRefLedgerSnapshotV1:
    """Short-lived account-wide cutover, native-floor, and allocation claim.

    ``ledger_sources`` must identify both the historical G5 allocation history
    and the V21 Store ledger. ``cutover_floor`` claims the native
    MaxOrderActionRef observed at the quiesced cutover. ``observed_native_high_water``
    claims the freshest native high-water observation available to the source.
    This DTO checks internal consistency but does not authenticate either
    claim, the source digests, or the account-wide cutover.
    """

    account_key: str
    cutover_id: str
    cutover_floor: int
    observed_native_high_water: int
    counter_high_water: int
    ledger_epoch: int
    ledger_sources: Tuple[str, ...]
    allocations: Tuple[CtpManagedActionRefAllocationV1, ...]
    unresolved_unknown_count: int
    observed_at_ns: int
    valid_until_ns: int
    native_floor_source_digest_sha256: str
    merged_ledger_source_digest_sha256: str
    mapping_sha256: str

    def __post_init__(self) -> None:
        if type(self.account_key) is not str or _ACCOUNT_KEY.fullmatch(self.account_key) is None:
            _reject("snapshot_account_invalid")
        _require_id(self.cutover_id, "snapshot_cutover_invalid")
        for value in (
            self.cutover_floor,
            self.observed_native_high_water,
            self.counter_high_water,
        ):
            if type(value) is not int or not 0 <= value <= _MAX_NATIVE_ACTION_REF:
                _reject("snapshot_high_water_invalid")
        if (
            self.observed_native_high_water < self.cutover_floor
            or self.counter_high_water < self.cutover_floor
        ):
            _reject("snapshot_floor_regressed")
        if type(self.ledger_epoch) is not int or self.ledger_epoch <= 0:
            _reject("snapshot_epoch_invalid")
        if type(self.ledger_sources) is not tuple or self.ledger_sources != _LEDGER_SOURCES:
            _reject("snapshot_sources_incomplete")
        if (
            type(self.allocations) is not tuple
            or len(self.allocations) > _MAX_ALLOCATIONS
            or any(type(row) is not CtpManagedActionRefAllocationV1 for row in self.allocations)
        ):
            _reject("snapshot_allocations_invalid")
        if type(self.unresolved_unknown_count) is not int or self.unresolved_unknown_count < 0:
            _reject("snapshot_unknown_count_invalid")
        for value in (self.observed_at_ns, self.valid_until_ns):
            if type(value) is not int or value <= 0:
                _reject("snapshot_time_invalid")
        if self.valid_until_ns <= self.observed_at_ns:
            _reject("snapshot_lifetime_invalid")
        for digest in (
            self.native_floor_source_digest_sha256,
            self.merged_ledger_source_digest_sha256,
            self.mapping_sha256,
        ):
            if type(digest) is not str or _HEX_64.fullmatch(digest) is None:
                _reject("snapshot_digest_invalid")
        if self.mapping_sha256 != ctp_managed_action_ref_mapping_sha256(self.allocations):
            _reject("snapshot_mapping_digest_mismatch")

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": "ctp.managed.actionref.account-ledger.v1",
            "account_key": self.account_key,
            "cutover_id": self.cutover_id,
            "cutover_floor": self.cutover_floor,
            "observed_native_high_water": self.observed_native_high_water,
            "counter_high_water": self.counter_high_water,
            "ledger_epoch": self.ledger_epoch,
            "ledger_sources": list(self.ledger_sources),
            "allocation_count": len(self.allocations),
            "unresolved_unknown_count": self.unresolved_unknown_count,
            "observed_at_ns": self.observed_at_ns,
            "valid_until_ns": self.valid_until_ns,
            "native_floor_source_digest_sha256": self.native_floor_source_digest_sha256,
            "merged_ledger_source_digest_sha256": self.merged_ledger_source_digest_sha256,
            "mapping_sha256": self.mapping_sha256,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())

    @property
    def fresh_until_ns(self) -> int:
        return min(self.valid_until_ns, self.observed_at_ns + _MAX_SNAPSHOT_AGE_NS)

    def require_current_cancel(
        self,
        *,
        now_ns: int,
        account_key: str,
        command_id: str,
        scope_key: str,
        managed_action_id: str,
        native_action_ref: int,
        expected_status: str,
    ) -> None:
        """Require a fresh, internally consistent current CANCEL allocation."""

        if (
            type(now_ns) is not int
            or now_ns <= 0
            or self.observed_at_ns > now_ns
            or now_ns - self.observed_at_ns > _MAX_SNAPSHOT_AGE_NS
            or self.valid_until_ns <= now_ns
        ):
            _reject("snapshot_stale")
        if type(expected_status) is not str or expected_status not in {"READY", "CLAIMED"}:
            _reject("current_action_status_invalid")
        if type(account_key) is not str or self.account_key != account_key:
            _reject("snapshot_account_mismatch")
        if self.unresolved_unknown_count != 0:
            _reject("account_unknown_actions_present")
        if self.counter_high_water < self.observed_native_high_water:
            _reject("counter_below_native_floor")

        refs: set[int] = set()
        commands: set[str] = set()
        action_ids: set[tuple[str, str]] = set()
        matched: list[CtpManagedActionRefAllocationV1] = []
        max_allocated = self.cutover_floor
        for row in self.allocations:
            if row.account_key != self.account_key:
                _reject("allocation_account_mismatch")
            if row.native_action_ref <= self.cutover_floor:
                _reject("allocation_below_cutover_floor")
            if (
                row.native_action_ref in refs
                or row.command_id in commands
                or (row.scope_key, row.managed_action_id) in action_ids
            ):
                _reject("account_action_mapping_conflict")
            refs.add(row.native_action_ref)
            commands.add(row.command_id)
            action_ids.add((row.scope_key, row.managed_action_id))
            max_allocated = max(max_allocated, row.native_action_ref)
            if row.status == "UNKNOWN":
                _reject("account_unknown_actions_present")
            if row.status == "CLAIMED" and row.command_id != command_id:
                _reject("account_claim_inflight")
            if row.command_id == command_id:
                matched.append(row)
        if self.counter_high_water != max_allocated:
            _reject("account_counter_mapping_mismatch")
        if len(matched) != 1:
            _reject("current_action_mapping_missing_or_duplicate")
        current = matched[0]
        if (
            current.scope_key != scope_key
            or current.managed_action_id != managed_action_id
            or current.native_action_ref != native_action_ref
            or current.status != expected_status
        ):
            _reject("current_action_mapping_mismatch")
        if (
            type(native_action_ref) is not int
            or native_action_ref <= self.observed_native_high_water
        ):
            _reject("current_action_ref_not_above_native_floor")


class CtpManagedActionRefLedgerSource(Protocol):
    """Expected deployment port for an account-wide ActionRef snapshot.

    The consumer does not authenticate an implementation of this protocol.
    Only a separately reviewed, authenticated producer can satisfy the trust
    assumptions; this repository currently provides none.
    """

    def read_action_ref_ledger(
        self, account_key: str
    ) -> Optional[CtpManagedActionRefLedgerSnapshotV1]:
        """Return fresh claimed floor/history data, or no snapshot."""
