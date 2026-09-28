"""Local-only durable checkpoint candidate for ActionRef ledger snapshots.

This wrapper detects accidental snapshot rollback across processes when the
same SQLite file is retained. The file is locally writable, source digests are
not authenticated, and this module is not registered or suitable as an
account-wide authority or native-floor producer.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .ctp_managed_actionref_floor import (
    CtpManagedActionRefAllocationV1,
    CtpManagedActionRefLedgerSnapshotV1,
)


class CtpLocalActionRefCheckpointError(RuntimeError):
    """Redacted fail-closed result from the local fake checkpoint candidate."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("local ActionRef snapshot checkpoint is unavailable")


def _reject(code: str) -> None:
    raise CtpLocalActionRefCheckpointError(code)


class CtpLocalActionRefCheckpointSource:
    """Persist account-keyed snapshot high-water state for local diagnostics."""

    def __init__(self, *, source: Any, database_path: str | Path) -> None:
        if not callable(getattr(source, "read_action_ref_ledger", None)):
            _reject("source_unavailable")
        path = Path(database_path)
        if not path.is_absolute() or str(path) == ":memory:":
            _reject("absolute_persistent_path_required")
        if not path.parent.is_dir():
            _reject("checkpoint_parent_unavailable")
        self._source = source
        self._database_path = path

    def read_action_ref_ledger(
        self, account_key: str
    ) -> Optional[CtpManagedActionRefLedgerSnapshotV1]:
        """Read and durably checkpoint one exact account snapshot or fail closed."""

        try:
            snapshot = self._source.read_action_ref_ledger(account_key)
        except Exception:
            _reject("source_read_failed")
        if (
            type(snapshot) is not CtpManagedActionRefLedgerSnapshotV1
            or snapshot.account_key != account_key
        ):
            _reject("snapshot_unavailable_or_account_mismatch")
        self._checkpoint(snapshot)
        return snapshot

    def _checkpoint(self, snapshot: CtpManagedActionRefLedgerSnapshotV1) -> None:
        document = _encode_snapshot(snapshot)
        try:
            connection = sqlite3.connect(
                str(self._database_path), timeout=5.0, isolation_level=None
            )
        except sqlite3.Error:
            _reject("checkpoint_open_failed")
        try:
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                _reject("checkpoint_schema_unsupported")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS actionref_snapshot_checkpoint ("
                "account_key TEXT PRIMARY KEY, ledger_epoch INTEGER NOT NULL, "
                "snapshot_digest TEXT NOT NULL, snapshot_json TEXT NOT NULL)"
            )
            if version == 0:
                connection.execute("PRAGMA user_version = 1")
            row = connection.execute(
                "SELECT ledger_epoch, snapshot_digest, snapshot_json "
                "FROM actionref_snapshot_checkpoint WHERE account_key = ?",
                (snapshot.account_key,),
            ).fetchone()
            if row is not None:
                prior = _decode_snapshot(row[2])
                if row[0] != prior.ledger_epoch or row[1] != prior.digest:
                    _reject("checkpoint_row_binding_mismatch")
                _require_monotonic(prior, snapshot)
            if row is None or row[1] != snapshot.digest:
                connection.execute(
                    "INSERT INTO actionref_snapshot_checkpoint "
                    "(account_key, ledger_epoch, snapshot_digest, snapshot_json) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(account_key) DO UPDATE SET "
                    "ledger_epoch=excluded.ledger_epoch, "
                    "snapshot_digest=excluded.snapshot_digest, "
                    "snapshot_json=excluded.snapshot_json",
                    (
                        snapshot.account_key,
                        snapshot.ledger_epoch,
                        snapshot.digest,
                        document,
                    ),
                )
            connection.execute("COMMIT")
        except CtpLocalActionRefCheckpointError:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            _reject("checkpoint_transaction_failed")
        finally:
            connection.close()


def _encode_snapshot(snapshot: CtpManagedActionRefLedgerSnapshotV1) -> str:
    document = {
        "snapshot_payload": snapshot.to_payload(),
        "allocations": [row.to_payload() for row in snapshot.allocations],
        "digest": snapshot.digest,
    }
    try:
        return json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        _reject("snapshot_encoding_failed")


def _decode_snapshot(encoded: str) -> CtpManagedActionRefLedgerSnapshotV1:
    try:
        document = json.loads(encoded)
        if type(document) is not dict or set(document) != {
            "snapshot_payload",
            "allocations",
            "digest",
        }:
            _reject("checkpoint_snapshot_corrupt")
        payload = document["snapshot_payload"]
        if (
            type(payload) is not dict
            or payload.get("schema") != "ctp.managed.actionref.account-ledger.v1"
        ):
            _reject("checkpoint_snapshot_corrupt")
        raw_allocations = document["allocations"]
        if type(raw_allocations) is not list:
            _reject("checkpoint_snapshot_corrupt")
        allocations = tuple(CtpManagedActionRefAllocationV1(**row) for row in raw_allocations)
        if payload.get("allocation_count") != len(allocations):
            _reject("checkpoint_snapshot_corrupt")
        snapshot = CtpManagedActionRefLedgerSnapshotV1(
            account_key=payload["account_key"],
            cutover_id=payload["cutover_id"],
            cutover_floor=payload["cutover_floor"],
            observed_native_high_water=payload["observed_native_high_water"],
            counter_high_water=payload["counter_high_water"],
            ledger_epoch=payload["ledger_epoch"],
            ledger_sources=tuple(payload["ledger_sources"]),
            allocations=allocations,
            unresolved_unknown_count=payload["unresolved_unknown_count"],
            observed_at_ns=payload["observed_at_ns"],
            valid_until_ns=payload["valid_until_ns"],
            native_floor_source_digest_sha256=payload["native_floor_source_digest_sha256"],
            merged_ledger_source_digest_sha256=payload["merged_ledger_source_digest_sha256"],
            mapping_sha256=payload["mapping_sha256"],
        )
        if document["digest"] != snapshot.digest:
            _reject("checkpoint_snapshot_digest_mismatch")
        return snapshot
    except CtpLocalActionRefCheckpointError:
        raise
    except Exception:
        _reject("checkpoint_snapshot_corrupt")


def _require_monotonic(
    previous: CtpManagedActionRefLedgerSnapshotV1,
    current: CtpManagedActionRefLedgerSnapshotV1,
) -> None:
    if current.ledger_epoch < previous.ledger_epoch:
        _reject("snapshot_epoch_regressed")
    if current.ledger_epoch == previous.ledger_epoch:
        if current.digest != previous.digest:
            _reject("snapshot_same_epoch_changed")
        return
    if current.cutover_id != previous.cutover_id or current.cutover_floor != previous.cutover_floor:
        _reject("snapshot_cutover_changed_without_transition_proof")
    if (
        current.observed_native_high_water < previous.observed_native_high_water
        or current.counter_high_water < previous.counter_high_water
    ):
        _reject("snapshot_high_water_regressed")

    previous_by_ref = {row.native_action_ref: row for row in previous.allocations}
    current_by_ref = {row.native_action_ref: row for row in current.allocations}
    status_rank = {"READY": 0, "CLAIMED": 1, "COMPLETED": 2}
    for action_ref, old_row in previous_by_ref.items():
        new_row = current_by_ref.get(action_ref)
        if new_row is None or (
            new_row.account_key,
            new_row.command_id,
            new_row.scope_key,
            new_row.managed_action_id,
        ) != (
            old_row.account_key,
            old_row.command_id,
            old_row.scope_key,
            old_row.managed_action_id,
        ):
            _reject("snapshot_allocation_identity_changed")
        if status_rank.get(new_row.status, -1) < status_rank.get(old_row.status, -1):
            _reject("snapshot_allocation_status_regressed")
    if any(
        action_ref not in previous_by_ref and action_ref <= previous.counter_high_water
        for action_ref in current_by_ref
    ):
        _reject("snapshot_allocation_reused_below_counter")
