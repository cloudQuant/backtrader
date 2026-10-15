"""Durable logical-run manifests and replay receipts for service execution.

The Execution service owns the authoritative order/outbox journal.  This local
SQLite journal binds one Backtrader logical run to immutable submit/cancel
requests and durably records safe recovery snapshots, event receipts, local
projections and callback work before user callbacks run.  It is deliberately
not a distributed transaction and does not promise exactly-once user effects:
callbacks are at-least-once until acknowledged.

Execution durable scopes do not include Backtrader ``run_id``.  The local
manifest therefore selects which historical service rows belong to this
logical run.  Unmatched service events are retained as recovery evidence only;
they are never turned into this run's fills or callbacks.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import AbstractSet, Any, Callable, Iterator, Optional

_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_CLOSE_POSITION_EFFECTS = frozenset({"CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY"})


class ServiceExecutionRecoveryError(RuntimeError):
    """A logical-run recovery manifest or receipt is inconsistent."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ServiceExecutionRecoveryNamespace:
    """Stable Backtrader identity used to select one local recovery history."""

    account_ref: str
    strategy_ref: str
    logical_run_id: str

    def __post_init__(self) -> None:
        for name, value in (
            ("account_ref", self.account_ref),
            ("strategy_ref", self.strategy_ref),
            ("logical_run_id", self.logical_run_id),
        ):
            if not _identifier(value):
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_NAMESPACE")


@dataclass(frozen=True)
class ServiceExecutionRecoveryCallback:
    """One pending callback delivery backed by an already committed receipt."""

    receipt_id: str
    intent_id: str
    event_type: str
    sequence: int
    event: Mapping[str, Any]
    delivery_attempt: int


class ServiceExecutionRecoveryJournal:
    """SQLite durability boundary for one or more explicit logical runs.

    Submit manifests are committed before the service RPC.  Event pages are
    committed atomically with their cursor, projected event, stable receipt,
    and pending callback.  Replaying a committed page is idempotent.  A
    callback is acknowledged only after the caller returns successfully; a
    crash before acknowledgement leaves it pending for at-least-once delivery.
    """

    _SCHEMA_VERSION = 2
    _SUBMIT_FIELDS = frozenset(
        {
            "intent_id",
            "signal_id",
            "instrument",
            "side",
            "position_effect",
            "order_type",
            "quantity",
            "price",
            "time_in_force",
            "reduce_only",
            "metadata_version",
            "deadline_ns",
            "tags",
        }
    )
    _SNAPSHOT_ORDER_FIELDS = frozenset(
        {
            "scope_key",
            "intent_id",
            "intent_fingerprint",
            "submit_fingerprint",
            "signal_id",
            "instrument",
            "side",
            "position_effect",
            "order_type",
            "quantity",
            "price",
            "time_in_force",
            "reduce_only",
            "metadata_version",
            "deadline_ns",
            "state",
            "provider_order_id",
            "filled_quantity",
            "average_price",
            "cumulative_commission",
            "cumulative_commission_currency",
            "dispatch_attempts",
            "unknown_reason_code",
            "review_required",
            "latest_source_sequence",
            "latest_source_event_id",
            "latest_observation_sequence",
            "latest_observation_event_id",
        }
    )
    _EVENT_FIELDS = frozenset(
        {
            "scope_key",
            "intent_id",
            "intent_fingerprint",
            "submit_fingerprint",
            "event_id",
            "sequence",
            "journal_generation",
            "event_type",
            "state",
            "event_sha256",
            "details",
        }
    )
    _EVENT_TYPES = frozenset(
        {
            "intent_recorded",
            "intent_admitted",
            "pending_admission_reference_reauthorized",
            "intent_blocked",
            "intent_rejected",
            "dispatch_claimed",
            "dispatch_unknown",
            "dispatch_blocked",
            "provider_observation",
            "reconciled_observation",
            "provider_commission_evidence",
            "manual_review_required",
            "cancelled_by_cancel_intent",
        }
    )
    _CALLBACK_EVENT_TYPES = frozenset(
        {
            "intent_blocked",
            "intent_rejected",
            "dispatch_unknown",
            "dispatch_blocked",
            "provider_observation",
            "reconciled_observation",
            "provider_commission_evidence",
            "manual_review_required",
            "cancelled_by_cancel_intent",
        }
    )
    _EXECUTION_STATES = frozenset(
        {
            "PENDING_ADMISSION",
            "PENDING_DISPATCH",
            "DISPATCHING",
            "ACKED",
            "PARTIALLY_FILLED",
            "FILLED",
            "CANCELLED",
            "REJECTED",
            "BLOCKED",
            "UNKNOWN",
        }
    )
    _OBSERVATION_STATES = frozenset(
        {"ACKED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"}
    )
    _EVENT_FIXED_STATES = {
        "intent_recorded": "PENDING_ADMISSION",
        "intent_admitted": "PENDING_DISPATCH",
        "pending_admission_reference_reauthorized": "PENDING_DISPATCH",
        "intent_rejected": "REJECTED",
        "intent_blocked": "BLOCKED",
        "dispatch_claimed": "DISPATCHING",
        "dispatch_unknown": "UNKNOWN",
        "dispatch_blocked": "BLOCKED",
        "cancelled_by_cancel_intent": "CANCELLED",
    }

    def __init__(self, database_path: str | Path) -> None:
        path = Path(database_path).expanduser().resolve(strict=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(
                str(path), isolation_level=None, check_same_thread=False
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._lock = RLock()
            self._create_schema()
        except sqlite3.Error as error:
            raise ServiceExecutionRecoveryError("RECOVERY_JOURNAL_UNAVAILABLE") from error
        self.path = path

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def prepare_intent(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        *,
        intent_id: str,
        submit_payload: Mapping[str, Any],
        recovery_binding: Optional[Mapping[str, Any]] = None,
    ) -> str:
        """Persist exact scope-free immutable request facts before submit RPC."""

        if not _identifier(intent_id) or not isinstance(submit_payload, Mapping):
            raise ServiceExecutionRecoveryError("INVALID_INTENT_MANIFEST")
        payload = _json_mapping(submit_payload)
        if frozenset(payload) != self._SUBMIT_FIELDS or payload.get("intent_id") != intent_id:
            raise ServiceExecutionRecoveryError("INVALID_INTENT_MANIFEST")
        _validate_submit_payload(payload)
        payload_json = _canonical_json(payload)
        fingerprint = _sha256(payload_json.encode("utf-8"))
        binding_json = None
        if recovery_binding is not None:
            binding = _validate_recovery_binding(recovery_binding, payload)
            binding_json = _canonical_json(binding)
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            self._ensure_namespace(cursor, namespace, now_ns)
            if binding_json is not None:
                baseline = cursor.execute(
                    """SELECT 1 FROM service_recovery_baselines
                       WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?""",
                    _namespace_values(namespace),
                ).fetchone()
                if baseline is None:
                    raise ServiceExecutionRecoveryError("RECOVERY_BASELINE_REQUIRED")
            prior = cursor.execute(
                """SELECT logical_run_id, submit_fingerprint, payload_json
                   FROM service_recovery_intents
                   WHERE account_ref = ? AND strategy_ref = ? AND intent_id = ?""",
                (namespace.account_ref, namespace.strategy_ref, intent_id),
            ).fetchone()
            if prior is not None:
                if str(prior["logical_run_id"]) != namespace.logical_run_id:
                    raise ServiceExecutionRecoveryError("INTENT_ID_BOUND_TO_OTHER_RUN")
                if (
                    str(prior["submit_fingerprint"]) != fingerprint
                    or str(prior["payload_json"]) != payload_json
                ):
                    raise ServiceExecutionRecoveryError("INTENT_MANIFEST_CONFLICT")
                prior_binding = cursor.execute(
                    """SELECT binding_json FROM service_recovery_intent_bindings
                       WHERE account_ref = ? AND strategy_ref = ? AND intent_id = ?
                         AND logical_run_id = ?""",
                    (*_intent_namespace_values(namespace, intent_id), namespace.logical_run_id),
                ).fetchone()
                if binding_json is not None and (
                    prior_binding is None or str(prior_binding["binding_json"]) != binding_json
                ):
                    raise ServiceExecutionRecoveryError("INTENT_RECOVERY_BINDING_CONFLICT")
                return fingerprint
            cursor.execute(
                """INSERT INTO service_recovery_intents(
                       account_ref, strategy_ref, intent_id, logical_run_id,
                       submit_fingerprint, payload_json, created_at_ns, updated_at_ns
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    namespace.account_ref,
                    namespace.strategy_ref,
                    intent_id,
                    namespace.logical_run_id,
                    fingerprint,
                    payload_json,
                    now_ns,
                    now_ns,
                ),
            )
            if binding_json is not None:
                cursor.execute(
                    """INSERT INTO service_recovery_intent_bindings(
                           account_ref, strategy_ref, intent_id, logical_run_id, binding_json
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (*_intent_namespace_values(namespace, intent_id), namespace.logical_run_id, binding_json),
                )
        return fingerprint

    def prepare_cancel(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        *,
        cancel_id: str,
        target_intent_id: str,
        provider_order_id: str,
        metadata_version: str,
    ) -> str:
        """Persist a stable cancel identity and target before cancellation RPC."""

        values = (cancel_id, target_intent_id, provider_order_id, metadata_version)
        if not all(_identifier(value) for value in values):
            raise ServiceExecutionRecoveryError("INVALID_CANCEL_MANIFEST")
        payload = {
            "cancel_id": cancel_id,
            "target_intent_id": target_intent_id,
            "provider_order_id": provider_order_id,
            "metadata_version": metadata_version,
        }
        payload_json = _canonical_json(payload)
        fingerprint = _sha256(payload_json.encode("utf-8"))
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            self._ensure_namespace(cursor, namespace, now_ns)
            intent = cursor.execute(
                """SELECT logical_run_id FROM service_recovery_intents
                   WHERE account_ref = ? AND strategy_ref = ? AND intent_id = ?""",
                (namespace.account_ref, namespace.strategy_ref, target_intent_id),
            ).fetchone()
            if intent is None or str(intent["logical_run_id"]) != namespace.logical_run_id:
                raise ServiceExecutionRecoveryError("CANCEL_TARGET_NOT_IN_RUN_MANIFEST")
            prior = cursor.execute(
                """SELECT logical_run_id, cancel_fingerprint, payload_json
                   FROM service_recovery_cancels
                   WHERE account_ref = ? AND strategy_ref = ? AND cancel_id = ?""",
                (namespace.account_ref, namespace.strategy_ref, cancel_id),
            ).fetchone()
            if prior is not None:
                if str(prior["logical_run_id"]) != namespace.logical_run_id:
                    raise ServiceExecutionRecoveryError("CANCEL_ID_BOUND_TO_OTHER_RUN")
                if (
                    str(prior["cancel_fingerprint"]) != fingerprint
                    or str(prior["payload_json"]) != payload_json
                ):
                    raise ServiceExecutionRecoveryError("CANCEL_MANIFEST_CONFLICT")
                return fingerprint
            cursor.execute(
                """INSERT INTO service_recovery_cancels(
                       account_ref, strategy_ref, cancel_id, logical_run_id,
                       target_intent_id, provider_order_id, cancel_fingerprint,
                       payload_json, created_at_ns
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    namespace.account_ref,
                    namespace.strategy_ref,
                    cancel_id,
                    namespace.logical_run_id,
                    target_intent_id,
                    provider_order_id,
                    fingerprint,
                    payload_json,
                    now_ns,
                ),
            )
        return fingerprint

    def intent_manifest(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        intent_id: str,
    ) -> Optional[Mapping[str, Any]]:
        """Read one local immutable submit manifest without service I/O."""

        with self._lock:
            row = self._connection.execute(
                """SELECT logical_run_id, submit_fingerprint, payload_json,
                          server_scope_key, server_intent_fingerprint
                   FROM service_recovery_intents
                   WHERE account_ref = ? AND strategy_ref = ? AND intent_id = ?""",
                (namespace.account_ref, namespace.strategy_ref, intent_id),
            ).fetchone()
        if row is None or str(row["logical_run_id"]) != namespace.logical_run_id:
            return None
        with self._lock:
            binding_row = self._connection.execute(
                """SELECT binding_json FROM service_recovery_intent_bindings
                   WHERE account_ref = ? AND strategy_ref = ? AND intent_id = ?
                     AND logical_run_id = ?""",
                (*_intent_namespace_values(namespace, intent_id), namespace.logical_run_id),
            ).fetchone()
        return {
            "intent_id": intent_id,
            "logical_run_id": str(row["logical_run_id"]),
            "submit_fingerprint": str(row["submit_fingerprint"]),
            "submit_payload": json.loads(str(row["payload_json"])),
            "scope_key": row["server_scope_key"],
            "intent_fingerprint": row["server_intent_fingerprint"],
            "recovery_binding": (
                json.loads(str(binding_row["binding_json"])) if binding_row is not None else None
            ),
        }

    def cancel_manifest(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        cancel_id: str,
    ) -> Optional[Mapping[str, Any]]:
        """Read one local immutable cancellation manifest without service I/O."""

        with self._lock:
            row = self._connection.execute(
                """SELECT logical_run_id, target_intent_id, provider_order_id,
                          cancel_fingerprint, payload_json
                   FROM service_recovery_cancels
                   WHERE account_ref = ? AND strategy_ref = ? AND cancel_id = ?""",
                (namespace.account_ref, namespace.strategy_ref, cancel_id),
            ).fetchone()
        if row is None or str(row["logical_run_id"]) != namespace.logical_run_id:
            return None
        return {
            "cancel_id": cancel_id,
            "logical_run_id": str(row["logical_run_id"]),
            "target_intent_id": str(row["target_intent_id"]),
            "provider_order_id": str(row["provider_order_id"]),
            "cancel_fingerprint": str(row["cancel_fingerprint"]),
            "cancel_payload": json.loads(str(row["payload_json"])),
        }

    def install_snapshot(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        snapshot: Mapping[str, Any],
    ) -> bool:
        """Persist a complete RECOVERY_SNAPSHOT without queuing callbacks.

        Returns ``True`` when this call changed the durable snapshot and
        ``False`` when the exact same snapshot was already installed.
        """

        normalized = _json_mapping(snapshot)
        coverage, orders = self._validate_snapshot(namespace, normalized)
        snapshot_hash = _snapshot_hash(coverage, orders)
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            self._ensure_namespace(cursor, namespace, now_ns)
            return self._install_snapshot_cursor(
                cursor, namespace, coverage, orders, snapshot_hash, now_ns
            )

    def install_recovery_baseline(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        snapshot: Mapping[str, Any],
        owner_book: Mapping[str, Any],
    ) -> bool:
        """Atomically pin the first owner-book baseline and recovery snapshot.

        Existing baselines are immutable. A legacy run with manifests but no
        baseline cannot adopt a later restart snapshot as its opening state.
        """

        normalized = _json_mapping(snapshot)
        coverage, orders = self._validate_snapshot(namespace, normalized)
        baseline = self._validate_owner_book_baseline(namespace, coverage, owner_book)
        baseline["snapshot_orders"] = orders
        baseline_json = _canonical_json(baseline)
        baseline_hash = _sha256(baseline_json.encode("utf-8"))
        snapshot_hash = _snapshot_hash(coverage, orders)
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            self._ensure_namespace(cursor, namespace, now_ns)
            existing = cursor.execute(
                """SELECT baseline_hash, baseline_json FROM service_recovery_baselines
                   WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?""",
                _namespace_values(namespace),
            ).fetchone()
            if existing is None:
                manifests = cursor.execute(
                    """SELECT COUNT(*) AS total FROM service_recovery_intents
                       WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?""",
                    _namespace_values(namespace),
                ).fetchone()
                if manifests is not None and int(manifests["total"]) != 0:
                    raise ServiceExecutionRecoveryError(
                        "RECOVERY_BASELINE_MISSING_FOR_EXISTING_MANIFEST"
                    )
                prior_receipts = cursor.execute(
                    """SELECT COUNT(*) AS total FROM service_recovery_event_receipts
                       WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?""",
                    _namespace_values(namespace),
                ).fetchone()
                prior_pages = cursor.execute(
                    """SELECT COUNT(*) AS total FROM service_recovery_pages
                       WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?""",
                    _namespace_values(namespace),
                ).fetchone()
                if (
                    (prior_receipts is not None and int(prior_receipts["total"]) != 0)
                    or (prior_pages is not None and int(prior_pages["total"]) != 0)
                ):
                    raise ServiceExecutionRecoveryError(
                        "RECOVERY_BASELINE_MISSING_FOR_EXISTING_RECEIPTS"
                    )
                existing_run = cursor.execute(
                    """SELECT event_cursor FROM service_recovery_runs
                       WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?""",
                    _namespace_values(namespace),
                ).fetchone()
                if (
                    existing_run is not None
                    and existing_run["event_cursor"] is not None
                    and int(existing_run["event_cursor"]) != coverage["high_water_sequence"]
                ):
                    raise ServiceExecutionRecoveryError(
                        "RECOVERY_BASELINE_MISSING_FOR_EXISTING_CURSOR"
                    )
                self._install_snapshot_cursor(
                    cursor, namespace, coverage, orders, snapshot_hash, now_ns
                )
                cursor.execute(
                    """INSERT INTO service_recovery_baselines(
                           account_ref, strategy_ref, logical_run_id,
                           server_account_key, journal_generation, directory_revision,
                           baseline_cursor, baseline_hash, baseline_json, created_at_ns
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        *_namespace_values(namespace),
                        coverage["account_key"],
                        coverage["journal_generation"],
                        coverage["scope_directory_revision"],
                        coverage["high_water_sequence"],
                        baseline_hash,
                        baseline_json,
                        now_ns,
                    ),
                )
                return True

            if str(existing["baseline_hash"]) != _sha256(
                str(existing["baseline_json"]).encode("utf-8")
            ):
                raise ServiceExecutionRecoveryError("RECOVERY_BASELINE_CORRUPT")
            self._install_snapshot_cursor(
                cursor, namespace, coverage, orders, snapshot_hash, now_ns
            )
            return str(existing["baseline_hash"]) == baseline_hash

    def _install_snapshot_cursor(
        self,
        cursor: sqlite3.Cursor,
        namespace: ServiceExecutionRecoveryNamespace,
        coverage: Mapping[str, Any],
        orders: list[dict[str, Any]],
        snapshot_hash: str,
        now_ns: int,
    ) -> bool:
        current = cursor.execute(
            """SELECT journal_generation, directory_revision, snapshot_hash
               FROM service_recovery_runs
               WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?""",
            _namespace_values(namespace),
        ).fetchone()
        if current is None:
            raise ServiceExecutionRecoveryError("RECOVERY_NAMESPACE_MISSING")
        if current["journal_generation"] not in (None, coverage["journal_generation"]):
            raise ServiceExecutionRecoveryError("RECOVERY_JOURNAL_GENERATION_CHANGED")
        if current["directory_revision"] not in (
            None,
            coverage["scope_directory_revision"],
        ):
            raise ServiceExecutionRecoveryError("RECOVERY_DIRECTORY_CHANGED")
        if current["snapshot_hash"] is not None and str(current["snapshot_hash"]) == snapshot_hash:
            return False
        cursor.execute(
            """DELETE FROM service_recovery_snapshot_orders
               WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?""",
            _namespace_values(namespace),
        )
        for order in orders:
            manifest = cursor.execute(
                """SELECT logical_run_id, submit_fingerprint,
                          server_scope_key, server_intent_fingerprint
                   FROM service_recovery_intents
                   WHERE account_ref = ? AND strategy_ref = ? AND intent_id = ?""",
                (namespace.account_ref, namespace.strategy_ref, order["intent_id"]),
            ).fetchone()
            matched = False
            if manifest is not None and str(manifest["logical_run_id"]) == namespace.logical_run_id:
                if str(manifest["submit_fingerprint"]) != order["submit_fingerprint"]:
                    raise ServiceExecutionRecoveryError("SNAPSHOT_INTENT_PAYLOAD_MISMATCH")
                if manifest["server_scope_key"] not in (None, order["scope_key"]):
                    raise ServiceExecutionRecoveryError("SNAPSHOT_INTENT_SCOPE_CHANGED")
                if manifest["server_intent_fingerprint"] not in (
                    None,
                    order["intent_fingerprint"],
                ):
                    raise ServiceExecutionRecoveryError(
                        "SNAPSHOT_INTENT_FINGERPRINT_CHANGED"
                    )
                cursor.execute(
                    """UPDATE service_recovery_intents
                       SET server_scope_key = ?, server_intent_fingerprint = ?, updated_at_ns = ?
                       WHERE account_ref = ? AND strategy_ref = ? AND intent_id = ?
                         AND logical_run_id = ?""",
                    (
                        order["scope_key"], order["intent_fingerprint"], now_ns,
                        namespace.account_ref, namespace.strategy_ref, order["intent_id"],
                        namespace.logical_run_id,
                    ),
                )
                matched = True
            cursor.execute(
                """INSERT INTO service_recovery_snapshot_orders(
                       account_ref, strategy_ref, logical_run_id, scope_key,
                       intent_id, matched_manifest, order_json, snapshot_hash
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(account_ref, strategy_ref, logical_run_id, scope_key, intent_id)
                   DO UPDATE SET matched_manifest = excluded.matched_manifest,
                                 order_json = excluded.order_json,
                                 snapshot_hash = excluded.snapshot_hash""",
                (
                    namespace.account_ref, namespace.strategy_ref, namespace.logical_run_id,
                    order["scope_key"], order["intent_id"], int(matched),
                    _canonical_json(order), snapshot_hash,
                ),
            )
        cursor.execute(
            """UPDATE service_recovery_runs
               SET server_account_key = ?, journal_generation = ?, directory_revision = ?,
                   snapshot_high_water = ?, snapshot_hash = ?, updated_at_ns = ?
               WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?""",
            (
                coverage["account_key"], coverage["journal_generation"],
                coverage["scope_directory_revision"], coverage["high_water_sequence"],
                snapshot_hash, now_ns, *_namespace_values(namespace),
            ),
        )
        cursor.execute(
            """UPDATE service_recovery_runs
               SET event_cursor = COALESCE(event_cursor, ?),
                   scanned_through = COALESCE(scanned_through, ?)
               WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?""",
            (
                coverage["high_water_sequence"], coverage["high_water_sequence"],
                *_namespace_values(namespace),
            ),
        )
        return True

    def apply_events_page(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        page: Mapping[str, Any],
    ) -> bool:
        """Atomically persist a validated event page and its recovery effects.

        Reapplying an identical already-committed page returns ``False``.
        Every distinct page commits safe receipts, current-run projections,
        callback work and the sparse global cursor in one SQLite transaction.
        """

        normalized = _json_mapping(page)
        coverage, events = self._validate_event_page(namespace, normalized)
        page_json = _canonical_json({"coverage": coverage, "events": events})
        page_hash = _sha256(page_json.encode("utf-8"))
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            run = cursor.execute(
                """SELECT server_account_key, journal_generation, directory_revision,
                          event_cursor, scanned_through, event_high_water
                   FROM service_recovery_runs
                   WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?""",
                _namespace_values(namespace),
            ).fetchone()
            if run is None or run["journal_generation"] is None:
                raise ServiceExecutionRecoveryError("RECOVERY_SNAPSHOT_REQUIRED")
            if (
                str(run["journal_generation"]) != coverage["journal_generation"]
                or str(run["directory_revision"]) != coverage["scope_directory_revision"]
                or str(run["server_account_key"]) != coverage["account_key"]
            ):
                raise ServiceExecutionRecoveryError("RECOVERY_PAGE_CUT_CHANGED")
            durable_cursor = int(run["event_cursor"])
            after = coverage["after_sequence"]
            if after != durable_cursor:
                prior_page = cursor.execute(
                    """SELECT page_sha256, scanned_through
                       FROM service_recovery_pages
                       WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?
                         AND journal_generation = ? AND directory_revision = ?
                         AND after_sequence = ?""",
                    (
                        namespace.account_ref,
                        namespace.strategy_ref,
                        namespace.logical_run_id,
                        coverage["journal_generation"],
                        coverage["scope_directory_revision"],
                        after,
                    ),
                ).fetchone()
                if (
                    prior_page is not None
                    and str(prior_page["page_sha256"]) == page_hash
                    and durable_cursor >= int(prior_page["scanned_through"])
                ):
                    return False
                raise ServiceExecutionRecoveryError("RECOVERY_CURSOR_CONFLICT")
            if int(run["scanned_through"]) != durable_cursor:
                raise ServiceExecutionRecoveryError("RECOVERY_CURSOR_CORRUPT")

            # A quiet poll at an unchanged high-water is valid but carries no
            # new durable fact.  Avoid inserting a duplicate page key so the
            # same idle cursor can be polled again safely.
            if (
                not events
                and coverage["scanned_through"] == durable_cursor
                and coverage["high_water_sequence"] == durable_cursor
            ):
                return False

            for event in events:
                self._apply_one_event(cursor, namespace, event, now_ns)
            cursor.execute(
                """INSERT INTO service_recovery_pages(
                       account_ref, strategy_ref, logical_run_id, journal_generation,
                       directory_revision, after_sequence, scanned_through, page_sha256,
                       created_at_ns
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    namespace.account_ref,
                    namespace.strategy_ref,
                    namespace.logical_run_id,
                    coverage["journal_generation"],
                    coverage["scope_directory_revision"],
                    after,
                    coverage["scanned_through"],
                    page_hash,
                    now_ns,
                ),
            )
            cursor.execute(
                """UPDATE service_recovery_runs
                   SET event_cursor = ?, scanned_through = ?,
                       event_high_water = ?, updated_at_ns = ?
                   WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?
                     AND event_cursor = ?""",
                (
                    coverage["scanned_through"],
                    coverage["scanned_through"],
                    max(coverage["high_water_sequence"], int(run["event_high_water"] or 0)),
                    now_ns,
                    *_namespace_values(namespace),
                    after,
                ),
            )
            if cursor.rowcount != 1:
                raise ServiceExecutionRecoveryError("RECOVERY_CURSOR_CONFLICT")
        return True

    def cursor(self, namespace: ServiceExecutionRecoveryNamespace) -> Mapping[str, Any]:
        """Return the persisted recovery cut/cursor, without external I/O."""

        with self._lock:
            row = self._connection.execute(
                """SELECT server_account_key, journal_generation, directory_revision,
                          snapshot_high_water, event_high_water, event_cursor,
                          scanned_through
                   FROM service_recovery_runs
                   WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?""",
                _namespace_values(namespace),
            ).fetchone()
        if row is None:
            raise ServiceExecutionRecoveryError("RECOVERY_NAMESPACE_MISSING")
        return {
            "account_key": row["server_account_key"],
            "journal_generation": row["journal_generation"],
            "scope_directory_revision": row["directory_revision"],
            "snapshot_high_water_sequence": row["snapshot_high_water"],
            "event_high_water_sequence": row["event_high_water"],
            "event_cursor": row["event_cursor"],
            "scanned_through": row["scanned_through"],
        }

    def snapshot_orders(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        *,
        matched_only: bool = True,
    ) -> tuple[Mapping[str, Any], ...]:
        """Return safe snapshot rows; unmatched history is evidence only."""

        query = """SELECT order_json FROM service_recovery_snapshot_orders
                   WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?"""
        parameters: tuple[Any, ...] = _namespace_values(namespace)
        if matched_only:
            query += " AND matched_manifest = 1"
        query += " ORDER BY scope_key, intent_id"
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return tuple(json.loads(str(row["order_json"])) for row in rows)

    def recovery_baseline(
        self, namespace: ServiceExecutionRecoveryNamespace
    ) -> Optional[Mapping[str, Any]]:
        """Return the immutable owner-book baseline for this logical run."""

        with self._lock:
            row = self._connection.execute(
                """SELECT baseline_cursor, baseline_json, baseline_hash,
                          journal_generation, directory_revision, server_account_key
                   FROM service_recovery_baselines
                   WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?""",
                _namespace_values(namespace),
            ).fetchone()
        if row is None:
            return None
        raw = str(row["baseline_json"])
        if _sha256(raw.encode("utf-8")) != str(row["baseline_hash"]):
            raise ServiceExecutionRecoveryError("RECOVERY_BASELINE_CORRUPT")
        value = json.loads(raw)
        return {
            "baseline_cursor": int(row["baseline_cursor"]),
            "journal_generation": str(row["journal_generation"]),
            "scope_directory_revision": str(row["directory_revision"]),
            "account_key": str(row["server_account_key"]),
            **value,
        }

    def intent_recovery_state(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        intent_id: str,
    ) -> Optional[Mapping[str, Any]]:
        """Read one manifest-bound order fact without a service query."""

        if not _identifier(intent_id):
            raise ServiceExecutionRecoveryError("INVALID_INTENT_ID")
        manifest = self.intent_manifest(namespace, intent_id)
        if manifest is None:
            return None
        snapshot_order = None
        with self._lock:
            row = self._connection.execute(
                """SELECT order_json FROM service_recovery_snapshot_orders
                   WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?
                     AND intent_id = ? AND matched_manifest = 1
                   ORDER BY snapshot_hash DESC LIMIT 1""",
                (*_namespace_values(namespace), intent_id),
            ).fetchone()
            projection = self._connection.execute(
                """SELECT event_json, sequence, receipt_id
                   FROM service_recovery_intent_projections
                   WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?
                     AND intent_id = ?""",
                (*_namespace_values(namespace), intent_id),
            ).fetchone()
        if row is not None:
            snapshot_order = json.loads(str(row["order_json"]))
        event_projection = None
        if projection is not None:
            event_projection = {
                "event": json.loads(str(projection["event_json"])),
                "sequence": int(projection["sequence"]),
                "receipt_id": str(projection["receipt_id"]),
            }
        if snapshot_order is None and event_projection is None:
            return None
        return {
            "manifest": manifest,
            "snapshot_order": snapshot_order,
            "event_projection": event_projection,
        }

    def ordered_event_history_page(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        *,
        after_sequence: int,
        through_sequence: Optional[int] = None,
        limit: int = 128,
    ) -> Mapping[str, Any]:
        """Read one bounded, gap-checked page of durable owner receipts.

        This includes unmatched owner-scope facts for reconciliation. The
        caller must never bind or notify an unmatched event.
        """

        if type(after_sequence) is not int or after_sequence < 0:
            raise ServiceExecutionRecoveryError("INVALID_HISTORY_CURSOR")
        if type(limit) is not int or not 1 <= limit <= 256:
            raise ServiceExecutionRecoveryError("INVALID_HISTORY_LIMIT")
        baseline = self.recovery_baseline(namespace)
        if baseline is None:
            raise ServiceExecutionRecoveryError("RECOVERY_BASELINE_REQUIRED")
        with self._lock:
            run = self._connection.execute(
                """SELECT event_cursor, journal_generation, directory_revision
                   FROM service_recovery_runs
                   WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?""",
                _namespace_values(namespace),
            ).fetchone()
            if run is None or run["event_cursor"] is None:
                raise ServiceExecutionRecoveryError("RECOVERY_CURSOR_MISSING")
            high_water = int(run["event_cursor"])
            through = high_water if through_sequence is None else through_sequence
            if type(through) is not int or not after_sequence <= through <= high_water:
                raise ServiceExecutionRecoveryError("INVALID_HISTORY_CURSOR")
            if (
                str(run["journal_generation"]) != baseline["journal_generation"]
                or str(run["directory_revision"]) != baseline["scope_directory_revision"]
            ):
                raise ServiceExecutionRecoveryError("RECOVERY_HISTORY_CUT_CHANGED")
            self._assert_history_coverage(
                namespace,
                baseline_cursor=baseline["baseline_cursor"],
                through_sequence=through,
                journal_generation=baseline["journal_generation"],
                directory_revision=baseline["scope_directory_revision"],
            )
            rows = self._connection.execute(
                """SELECT r.receipt_id, r.sequence, r.event_id, r.matched_manifest,
                          r.event_json, c.acknowledged_at_ns, c.delivery_attempts
                   FROM service_recovery_event_receipts AS r
                   LEFT JOIN service_recovery_callbacks AS c
                     ON c.account_ref = r.account_ref
                    AND c.strategy_ref = r.strategy_ref
                    AND c.logical_run_id = r.logical_run_id
                    AND c.receipt_id = r.receipt_id
                   WHERE r.account_ref = ? AND r.strategy_ref = ? AND r.logical_run_id = ?
                     AND r.sequence > ? AND r.sequence <= ?
                   ORDER BY r.sequence, r.event_id LIMIT ?""",
                (*_namespace_values(namespace), after_sequence, through, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        selected = rows[:limit]
        events = []
        for row in selected:
            event = json.loads(str(row["event_json"]))
            binding = self._history_binding(namespace, event["intent_id"])
            events.append(
                {
                    "receipt_id": str(row["receipt_id"]),
                    "sequence": int(row["sequence"]),
                    "event_id": str(row["event_id"]),
                    "matched_manifest": bool(row["matched_manifest"]),
                    "callback_pending": (
                        row["acknowledged_at_ns"] is None
                        if row["delivery_attempts"] is not None
                        else False
                    ),
                    "callback_acknowledged": (
                        row["acknowledged_at_ns"] is not None
                        if row["delivery_attempts"] is not None
                        else False
                    ),
                    "event": event,
                    "binding": binding if bool(row["matched_manifest"]) else None,
                }
            )
        if has_more:
            scanned_through = events[-1]["sequence"] if events else after_sequence
        else:
            scanned_through = through
        return {
            "after_sequence": after_sequence,
            "through_sequence": through,
            "scanned_through": scanned_through,
            "has_more": has_more,
            "events": tuple(events),
        }

    def ordered_event_history(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        *,
        limit: int = 128,
        max_pages: int = 256,
    ) -> tuple[Mapping[str, Any], ...]:
        """Read the complete bounded receipt history or fail without truncation."""

        if type(max_pages) is not int or not 1 <= max_pages <= 1024:
            raise ServiceExecutionRecoveryError("INVALID_HISTORY_PAGE_BUDGET")
        baseline = self.recovery_baseline(namespace)
        if baseline is None:
            raise ServiceExecutionRecoveryError("RECOVERY_BASELINE_REQUIRED")
        cursor = baseline["baseline_cursor"]
        through = self.cursor(namespace)["event_cursor"]
        events: list[Mapping[str, Any]] = []
        for _ in range(max_pages):
            page = self.ordered_event_history_page(
                namespace,
                after_sequence=cursor,
                through_sequence=through,
                limit=limit,
            )
            events.extend(page["events"])
            cursor = page["scanned_through"]
            if page["has_more"] is False:
                if cursor != through:
                    raise ServiceExecutionRecoveryError("RECOVERY_HISTORY_GAP")
                return tuple(events)
        raise ServiceExecutionRecoveryError("RECOVERY_HISTORY_PAGE_BUDGET_EXHAUSTED")

    def strategy_trade_positions(
        self, namespace: ServiceExecutionRecoveryNamespace
    ) -> Mapping[tuple[str, int], Decimal]:
        """Project matched same-run trade quantities from ordered cumulative facts."""

        baseline = self.recovery_baseline(namespace)
        if baseline is None or baseline["trade_projection_available"] is not True:
            raise ServiceExecutionRecoveryError("RECOVERY_TRADE_BASELINE_INCOMPLETE")
        histories = self.ordered_event_history(namespace)
        cumulative: dict[str, Decimal] = {}
        positions: dict[tuple[str, int], Decimal] = {}
        manifests: dict[str, Mapping[str, Any]] = {}
        for receipt in histories:
            if receipt["matched_manifest"] is not True:
                continue
            event = receipt["event"]
            binding = receipt["binding"]
            if not isinstance(binding, Mapping):
                raise ServiceExecutionRecoveryError("RECOVERY_TRADE_BINDING_MISSING")
            manifest = self.intent_manifest(namespace, event["intent_id"])
            if manifest is None or manifest.get("recovery_binding") != binding:
                raise ServiceExecutionRecoveryError("RECOVERY_TRADE_BINDING_MISMATCH")
            manifests[event["intent_id"]] = manifest
            event_type = event["event_type"]
            if event_type not in {
                "provider_observation",
                "reconciled_observation",
                "provider_commission_evidence",
                "cancelled_by_cancel_intent",
            }:
                continue
            details = event["details"]
            quantity = _decimal_value(details["filled_quantity"], nonnegative=True)
            previous = cumulative.get(event["intent_id"], Decimal(0))
            if quantity < previous:
                raise ServiceExecutionRecoveryError("RECOVERY_FILL_CURSOR_REGRESSION")
            delta = quantity - previous
            cumulative[event["intent_id"]] = quantity
            if not delta:
                continue
            submit = manifest["submit_payload"]
            key = (binding["data_name"], binding["tradeid"])
            effect = submit["position_effect"]
            self._apply_trade_delta(
                positions,
                key,
                submit["side"],
                effect,
                delta,
            )
        return {key: value for key, value in positions.items() if value != 0}

    @staticmethod
    def _apply_trade_delta(positions, key, side, effect, delta):
        signed = delta if side == "BUY" else -delta
        prior = positions.get(key, Decimal(0))
        if effect == "OPEN":
            if prior and prior * signed < 0:
                raise ServiceExecutionRecoveryError("RECOVERY_TRADE_REVERSAL_NOT_SPLIT")
            positions[key] = prior + signed
            return
        if effect not in _CLOSE_POSITION_EFFECTS:
            raise ServiceExecutionRecoveryError("RECOVERY_TRADE_POSITION_EFFECT_INVALID")
        # Backtrader's recovered trade projection is aggregate by data/tradeid.
        # Preserve the original close variant in the immutable submit manifest;
        # this check does not prove provider-side today/yesterday bucket capacity.
        if prior == 0 or prior * signed >= 0 or delta > abs(prior):
            raise ServiceExecutionRecoveryError("RECOVERY_TRADE_CLOSE_CAPACITY_INVALID")
        positions[key] = prior + signed

    def _trade_projection_before(self, cursor, namespace, before_sequence):
        rows = cursor.execute(
            """SELECT r.intent_id, r.event_json, i.payload_json, b.binding_json
               FROM service_recovery_event_receipts AS r
               JOIN service_recovery_intents AS i
                 ON i.account_ref = r.account_ref AND i.strategy_ref = r.strategy_ref
                AND i.intent_id = r.intent_id AND i.logical_run_id = r.logical_run_id
               LEFT JOIN service_recovery_intent_bindings AS b
                 ON b.account_ref = r.account_ref AND b.strategy_ref = r.strategy_ref
                AND b.intent_id = r.intent_id AND b.logical_run_id = r.logical_run_id
               WHERE r.account_ref = ? AND r.strategy_ref = ? AND r.logical_run_id = ?
                 AND r.matched_manifest = 1 AND r.sequence < ?
                 AND r.event_type IN (
                     'provider_observation', 'reconciled_observation',
                     'provider_commission_evidence', 'cancelled_by_cancel_intent'
                 )
               ORDER BY r.sequence""",
            (*_namespace_values(namespace), before_sequence),
        ).fetchall()
        cumulative = {}
        positions = {}
        for row in rows:
            intent_id = str(row["intent_id"])
            event = json.loads(str(row["event_json"]))
            submit = json.loads(str(row["payload_json"]))
            binding_raw = row["binding_json"]
            if binding_raw is None:
                raise ServiceExecutionRecoveryError("RECOVERY_TRADE_BINDING_MISSING")
            binding = json.loads(str(binding_raw))
            filled = _decimal_value(event["details"]["filled_quantity"], nonnegative=True)
            previous = cumulative.get(intent_id, Decimal(0))
            if filled < previous:
                raise ServiceExecutionRecoveryError("RECOVERY_FILL_CURSOR_REGRESSION")
            delta = filled - previous
            cumulative[intent_id] = filled
            if delta:
                key = (binding["data_name"], binding["tradeid"])
                self._apply_trade_delta(
                    positions,
                    key,
                    submit["side"],
                    submit["position_effect"],
                    delta,
                )
        return positions, cumulative

    def _history_binding(
        self, namespace: ServiceExecutionRecoveryNamespace, intent_id: str
    ) -> Optional[Mapping[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                """SELECT binding_json FROM service_recovery_intent_bindings
                   WHERE account_ref = ? AND strategy_ref = ? AND intent_id = ?
                     AND logical_run_id = ?""",
                (*_intent_namespace_values(namespace, intent_id), namespace.logical_run_id),
            ).fetchone()
        return json.loads(str(row["binding_json"])) if row is not None else None

    def _assert_history_coverage(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        *,
        baseline_cursor: int,
        through_sequence: int,
        journal_generation: str,
        directory_revision: str,
    ) -> None:
        if through_sequence == baseline_cursor:
            return
        with self._lock:
            pages = self._connection.execute(
                """SELECT after_sequence, scanned_through FROM service_recovery_pages
                   WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?
                     AND journal_generation = ? AND directory_revision = ?
                     AND after_sequence >= ? AND scanned_through <= ?
                   ORDER BY after_sequence""",
                (
                    *_namespace_values(namespace), journal_generation, directory_revision,
                    baseline_cursor, through_sequence,
                ),
            ).fetchall()
        cursor = baseline_cursor
        for row in pages:
            if int(row["after_sequence"]) != cursor or int(row["scanned_through"]) <= cursor:
                raise ServiceExecutionRecoveryError("RECOVERY_HISTORY_GAP")
            cursor = int(row["scanned_through"])
            if cursor == through_sequence:
                break
        if cursor != through_sequence:
            raise ServiceExecutionRecoveryError("RECOVERY_HISTORY_GAP")

    def reconcile_owner_positions(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        owner_book: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Compare the original owner position with all persisted service fills."""

        baseline = self.recovery_baseline(namespace)
        if baseline is None:
            raise ServiceExecutionRecoveryError("RECOVERY_BASELINE_REQUIRED")
        current_orders = self.snapshot_orders(namespace, matched_only=False)
        expected = {
            key: Decimal(value) for key, value in baseline["positions"].items()
        }
        baseline_by_key = {
            (row["scope_key"], row["intent_id"]): row
            for row in baseline["snapshot_orders"]
        }
        current_by_key = {(row["scope_key"], row["intent_id"]): row for row in current_orders}
        if len(current_by_key) != len(current_orders):
            raise ServiceExecutionRecoveryError("RECOVERY_SNAPSHOT_ORDER_DUPLICATE")
        for key, old in baseline_by_key.items():
            if key not in current_by_key and Decimal(old["filled_quantity"]) != 0:
                raise ServiceExecutionRecoveryError("RECOVERY_OWNER_POSITION_HISTORY_MISSING")
        unresolved = []
        with self._lock:
            matched_rows = self._connection.execute(
                """SELECT scope_key, intent_id FROM service_recovery_snapshot_orders
                   WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?
                     AND matched_manifest = 1""",
                _namespace_values(namespace),
            ).fetchall()
        matched_keys = {
            (str(row["scope_key"]), str(row["intent_id"])) for row in matched_rows
        }
        matched_changes: dict[str, Decimal] = {}
        for key, row in current_by_key.items():
            old = baseline_by_key.get(key)
            old_quantity = Decimal(old["filled_quantity"]) if old is not None else Decimal(0)
            new_quantity = Decimal(row["filled_quantity"])
            if new_quantity < old_quantity:
                raise ServiceExecutionRecoveryError("RECOVERY_FILL_CURSOR_REGRESSION")
            delta = new_quantity - old_quantity
            if delta:
                signed = delta if row["side"] == "BUY" else -delta
                instrument = row["instrument"]
                expected[instrument] = expected.get(instrument, Decimal(0)) + signed
                if key in matched_keys:
                    matched_changes[instrument] = matched_changes.get(
                        instrument, Decimal(0)
                    ) + signed
            if row["state"] == "UNKNOWN" or row["review_required"] is True:
                unresolved.append(row["intent_id"])
            if old is not None and (
                old["instrument"] != row["instrument"] or old["side"] != row["side"]
            ):
                raise ServiceExecutionRecoveryError("RECOVERY_OWNER_ORDER_BINDING_CHANGED")
        actual_positions = {
            key: Decimal(value) for key, value in owner_book["positions"].items()
        }
        expected = {key: value for key, value in expected.items() if value != 0}
        actual_positions = {key: value for key, value in actual_positions.items() if value != 0}
        if expected != actual_positions:
            raise ServiceExecutionRecoveryError("RECOVERY_OWNER_POSITION_MISMATCH")
        actual_changes = {
            instrument: quantity - Decimal(baseline["positions"].get(instrument, "0"))
            for instrument, quantity in actual_positions.items()
        }
        for instrument, baseline_quantity in baseline["positions"].items():
            actual_changes.setdefault(instrument, -Decimal(baseline_quantity))
        actual_changes = {key: value for key, value in actual_changes.items() if value != 0}
        matched_changes = {key: value for key, value in matched_changes.items() if value != 0}
        trade_events_complete = self._trade_projection_events_complete(
            namespace, baseline
        )
        trade_projection_available = bool(
            baseline["trade_projection_available"]
            and owner_book["financial_available"] is True
            and owner_book["cost_basis_complete"] is True
            and trade_events_complete
            and not unresolved
            and matched_changes == actual_changes
        )
        trade_projection_unavailable_reason = None
        if not trade_projection_available:
            if baseline["trade_projection_available"] and not trade_events_complete:
                # Recovery v1 carries cumulative economics but no provider
                # execution time.  The journal's created_at_ns is only the
                # local append time and must not be used for OrderExecutionBit.dt.
                trade_projection_unavailable_reason = "provider_execution_time_unavailable"
            elif not baseline["trade_projection_available"]:
                trade_projection_unavailable_reason = "opening_trade_baseline_incomplete"
            elif unresolved:
                trade_projection_unavailable_reason = "unresolved_owner_intent"
            elif matched_changes != actual_changes:
                trade_projection_unavailable_reason = "owner_position_attribution_incomplete"
            else:
                trade_projection_unavailable_reason = "owner_financial_cut_incomplete"
        return {
            "positions_match": True,
            "current_positions": dict(owner_book["positions"]),
            "unresolved_intents": tuple(sorted(unresolved)),
            "trade_projection_available": trade_projection_available,
            "trade_projection_unavailable_reason": trade_projection_unavailable_reason,
            "baseline_cursor": baseline["baseline_cursor"],
            "current_cursor": owner_book["current_execution_cursor"],
        }

    def _trade_projection_events_complete(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        baseline: Mapping[str, Any],
    ) -> bool:
        """Return whether event facts can support exact Strategy Trade values.

        Backtrader's Trade ledger has no separate fee-only update operation.
        Missing fill price/fee currency or a fee/notional correction without a
        quantity increment therefore disables Trade projection rather than
        inventing a zero-cost fill.
        """

        history = self.ordered_event_history(namespace)
        previous: dict[str, tuple[Decimal, Optional[Decimal], Optional[str]]] = {}
        allowed_currencies = set(baseline["cash_by_currency"])
        currencies_by_trade: dict[tuple[str, int], str] = {}
        for receipt in history:
            if receipt["matched_manifest"] is not True:
                continue
            event = receipt["event"]
            if event["event_type"] not in {
                "provider_observation",
                "reconciled_observation",
                "provider_commission_evidence",
                "cancelled_by_cancel_intent",
            }:
                continue
            details = event["details"]
            filled = Decimal(details["filled_quantity"])
            cumulative_fee = (
                None
                if details["cumulative_commission"] is None
                else Decimal(details["cumulative_commission"])
            )
            currency = details.get("cumulative_commission_currency")
            prior_filled, prior_fee, prior_currency = previous.get(
                event["intent_id"], (Decimal(0), Decimal(0), None)
            )
            if filled < prior_filled:
                raise ServiceExecutionRecoveryError("RECOVERY_FILL_CURSOR_REGRESSION")
            quantity_delta = filled - prior_filled
            if quantity_delta:
                if (
                    details["average_price"] is None
                    or cumulative_fee is None
                    or not isinstance(currency, str)
                    or currency not in allowed_currencies
                ):
                    return False
                binding = receipt["binding"]
                if not isinstance(binding, Mapping):
                    return False
                trade_key = (binding["data_name"], binding["tradeid"])
                prior_trade_currency = currencies_by_trade.setdefault(trade_key, currency)
                if prior_trade_currency != currency:
                    return False
                if prior_currency not in (None, currency):
                    return False
                # The v1 event DTO intentionally omits provider execution
                # time.  created_at_ns is a local journal timestamp, not an
                # execution-time substitute, so historical Strategy Trade
                # reconstruction is unavailable for this fill.
                return False
            elif cumulative_fee != prior_fee:
                # A rebate/correction without new units cannot be represented
                # by OrderExecutionBit and Trade.update without a fabricated
                # zero-quantity execution.
                return False
            previous[event["intent_id"]] = (
                filled,
                cumulative_fee,
                currency if currency is not None else prior_currency,
            )
        return True

    def _validate_owner_book_baseline(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        coverage: Mapping[str, Any],
        raw: Mapping[str, Any],
    ) -> dict[str, Any]:
        required = {
            "account_key",
            "account_ref",
            "strategy_ref",
            "scope_directory_revision",
            "journal_generation",
            "baseline_execution_cursor",
            "current_execution_cursor",
            "positions",
            "cash_by_currency",
            "position_costs",
            "financial_available",
            "cost_basis_complete",
        }
        if not isinstance(raw, Mapping) or frozenset(raw) != required:
            raise ServiceExecutionRecoveryError("INVALID_OWNER_BOOK_BASELINE")
        if (
            raw["account_key"] != coverage["account_key"]
            or not _identifier(raw["account_key"])
            or raw["account_ref"] != namespace.account_ref
            or raw["strategy_ref"] != namespace.strategy_ref
            or raw["scope_directory_revision"] != coverage["scope_directory_revision"]
            or raw["journal_generation"] != coverage["journal_generation"]
            or type(raw["baseline_execution_cursor"]) is not int
            or type(raw["current_execution_cursor"]) is not int
            or raw["current_execution_cursor"] != coverage["high_water_sequence"]
            or raw["baseline_execution_cursor"] > raw["current_execution_cursor"]
            or type(raw["financial_available"]) is not bool
            or type(raw["cost_basis_complete"]) is not bool
            or not isinstance(raw["positions"], Mapping)
            or not isinstance(raw["cash_by_currency"], Mapping)
            or not isinstance(raw["position_costs"], Mapping)
        ):
            raise ServiceExecutionRecoveryError("OWNER_BOOK_RECOVERY_CUT_MISMATCH")
        positions: dict[str, str] = {}
        for instrument, quantity in raw["positions"].items():
            if not _identifier(instrument):
                raise ServiceExecutionRecoveryError("INVALID_OWNER_BOOK_BASELINE")
            positions[instrument] = _canonical_decimal_text(quantity)
        cash: dict[str, str] = {}
        for currency, amount in raw["cash_by_currency"].items():
            if not _identifier(currency):
                raise ServiceExecutionRecoveryError("INVALID_OWNER_BOOK_BASELINE")
            cash[currency] = _canonical_decimal_text(amount)
        costs: dict[str, dict[str, Any]] = {}
        for instrument, row in raw["position_costs"].items():
            if not _identifier(instrument) or not isinstance(row, Mapping) or frozenset(row) != {
                "quantity", "cost_basis", "cost_currency", "product_model",
                "metadata_version", "average_cost",
            }:
                raise ServiceExecutionRecoveryError("INVALID_OWNER_BOOK_BASELINE")
            costs[instrument] = {
                "quantity": _canonical_decimal_text(row["quantity"]),
                "cost_basis": (
                    None if row["cost_basis"] is None else _canonical_decimal_text(row["cost_basis"])
                ),
                "cost_currency": row["cost_currency"],
                "product_model": _identifier_or_none(row["product_model"]),
                "metadata_version": _identifier_or_none(row["metadata_version"]),
                "average_cost": (
                    None if row["average_cost"] is None else _canonical_decimal_text(row["average_cost"])
                ),
            }
        all_flat = all(Decimal(quantity) == 0 for quantity in positions.values())
        return {
            "account_key": raw["account_key"],
            "account_ref": namespace.account_ref,
            "strategy_ref": namespace.strategy_ref,
            "scope_directory_revision": coverage["scope_directory_revision"],
            "journal_generation": coverage["journal_generation"],
            "baseline_execution_cursor": raw["baseline_execution_cursor"],
            "current_execution_cursor": raw["current_execution_cursor"],
            "positions": positions,
            "cash_by_currency": cash,
            "position_costs": costs,
            "financial_available": raw["financial_available"],
            "cost_basis_complete": raw["cost_basis_complete"],
            "trade_projection_available": bool(
                raw["financial_available"] and raw["cost_basis_complete"] and all_flat
            ),
        }

    def claim_pending_callbacks(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        *,
        limit: int = 32,
    ) -> tuple[ServiceExecutionRecoveryCallback, ...]:
        """Return pending callbacks and count each delivery attempt.

        The queue stays pending until :meth:`acknowledge_callback` is called.
        A process crash or callback exception therefore permits a later
        at-least-once retry. This does not make arbitrary callback side effects
        exactly-once.
        """

        if type(limit) is not int or not 1 <= limit <= 128:
            raise ServiceExecutionRecoveryError("INVALID_CALLBACK_LIMIT")
        now_ns = time.time_ns()
        with self._transaction() as cursor:
            rows = cursor.execute(
                """SELECT c.receipt_id, c.delivery_attempts, r.intent_id,
                          r.event_type, r.sequence, r.event_json
                   FROM service_recovery_callbacks AS c
                   JOIN service_recovery_event_receipts AS r
                     ON r.account_ref = c.account_ref
                    AND r.strategy_ref = c.strategy_ref
                    AND r.logical_run_id = c.logical_run_id
                    AND r.receipt_id = c.receipt_id
                   WHERE c.account_ref = ? AND c.strategy_ref = ? AND c.logical_run_id = ?
                     AND c.acknowledged_at_ns IS NULL
                   ORDER BY r.sequence, r.event_id LIMIT ?""",
                (*_namespace_values(namespace), limit),
            ).fetchall()
            for row in rows:
                cursor.execute(
                    """UPDATE service_recovery_callbacks
                       SET delivery_attempts = delivery_attempts + 1,
                           last_attempt_at_ns = ?
                       WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?
                         AND receipt_id = ? AND acknowledged_at_ns IS NULL""",
                    (now_ns, *_namespace_values(namespace), str(row["receipt_id"])),
                )
        return tuple(
            ServiceExecutionRecoveryCallback(
                receipt_id=str(row["receipt_id"]),
                intent_id=str(row["intent_id"]),
                event_type=str(row["event_type"]),
                sequence=int(row["sequence"]),
                event=json.loads(str(row["event_json"])),
                delivery_attempt=int(row["delivery_attempts"]) + 1,
            )
            for row in rows
        )

    def claim_callback(
        self, namespace: ServiceExecutionRecoveryNamespace, receipt_id: str
    ) -> Optional[ServiceExecutionRecoveryCallback]:
        """Claim one pending order callback by its durable event receipt.

        The broker uses this narrower claim after it has rebound the stable
        intent to a live Strategy Order.  Claiming the whole callback queue
        would consume receipts for orders the caller has not reconstructed.
        """

        if not _digest(receipt_id):
            raise ServiceExecutionRecoveryError("INVALID_CALLBACK_RECEIPT")
        with self._transaction() as cursor:
            row = cursor.execute(
                """SELECT c.delivery_attempts, c.acknowledged_at_ns, r.intent_id,
                          r.event_type, r.sequence, r.event_json
                   FROM service_recovery_callbacks AS c
                   JOIN service_recovery_event_receipts AS r
                     ON r.account_ref = c.account_ref
                    AND r.strategy_ref = c.strategy_ref
                    AND r.logical_run_id = c.logical_run_id
                    AND r.receipt_id = c.receipt_id
                   WHERE c.account_ref = ? AND c.strategy_ref = ? AND c.logical_run_id = ?
                     AND c.receipt_id = ?""",
                (*_namespace_values(namespace), receipt_id),
            ).fetchone()
            if row is None or row["acknowledged_at_ns"] is not None:
                return None
            attempt = int(row["delivery_attempts"]) + 1
            cursor.execute(
                """UPDATE service_recovery_callbacks
                   SET delivery_attempts = ?, last_attempt_at_ns = ?
                   WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?
                     AND receipt_id = ? AND acknowledged_at_ns IS NULL""",
                (attempt, time.time_ns(), *_namespace_values(namespace), receipt_id),
            )
            if cursor.rowcount != 1:
                raise ServiceExecutionRecoveryError("CALLBACK_RECEIPT_CLAIM_CONFLICT")
        return ServiceExecutionRecoveryCallback(
            receipt_id=receipt_id,
            intent_id=str(row["intent_id"]),
            event_type=str(row["event_type"]),
            sequence=int(row["sequence"]),
            event=json.loads(str(row["event_json"])),
            delivery_attempt=attempt,
        )

    def acknowledge_callback(
        self, namespace: ServiceExecutionRecoveryNamespace, receipt_id: str
    ) -> None:
        """Acknowledge one callback only after its caller completed successfully."""

        if not _digest(receipt_id):
            raise ServiceExecutionRecoveryError("INVALID_CALLBACK_RECEIPT")
        with self._transaction() as cursor:
            result = cursor.execute(
                """UPDATE service_recovery_callbacks
                   SET acknowledged_at_ns = ?
                   WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?
                     AND receipt_id = ? AND acknowledged_at_ns IS NULL""",
                (time.time_ns(), *_namespace_values(namespace), receipt_id),
            )
            if result.rowcount != 1:
                row = cursor.execute(
                    """SELECT acknowledged_at_ns FROM service_recovery_callbacks
                       WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?
                         AND receipt_id = ?""",
                    (*_namespace_values(namespace), receipt_id),
                ).fetchone()
                if row is None or row["acknowledged_at_ns"] is None:
                    raise ServiceExecutionRecoveryError("CALLBACK_RECEIPT_MISSING")

    def deliver_pending_callbacks(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        callback: Callable[[ServiceExecutionRecoveryCallback], Any],
        *,
        limit: int = 32,
    ) -> int:
        """Deliver committed callback receipts and acknowledge successful calls.

        The callback runs after the event/projection/cursor transaction has
        committed. If it raises, the receipt remains pending and a later
        process may deliver it again. That is an at-least-once boundary for
        arbitrary user code, not an exactly-once guarantee.
        """

        if not callable(callback):
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_CALLBACK")
        delivered = 0
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ServiceExecutionRecoveryError("INVALID_CALLBACK_LIMIT")
        while delivered < limit:
            pending = self.claim_pending_callbacks(namespace, limit=1)
            if not pending:
                break
            item = pending[0]
            callback(item)
            self.acknowledge_callback(namespace, item.receipt_id)
            delivered += 1
        return delivered

    def event_projection(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        intent_id: str,
    ) -> Optional[Mapping[str, Any]]:
        """Read the last committed current-run event projection for an intent."""

        with self._lock:
            row = self._connection.execute(
                """SELECT event_json, sequence, receipt_id
                   FROM service_recovery_intent_projections
                   WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?
                     AND intent_id = ?""",
                (*_namespace_values(namespace), intent_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "event": json.loads(str(row["event_json"])),
            "sequence": int(row["sequence"]),
            "receipt_id": str(row["receipt_id"]),
        }

    def _validate_snapshot(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        snapshot: Mapping[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if (
            frozenset(snapshot) != {"view", "version", "coverage", "orders"}
            or snapshot.get("view") != "RECOVERY_SNAPSHOT"
            or type(snapshot.get("version")) is not int
            or snapshot["version"] != 1
        ):
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_SNAPSHOT")
        raw_coverage = snapshot.get("coverage")
        raw_orders = snapshot.get("orders")
        if not isinstance(raw_coverage, Mapping) or type(raw_orders) is not list:
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_SNAPSHOT")
        required = {
            "account_key",
            "owner_kind",
            "owner_ref",
            "scope_directory_revision",
            "journal_generation",
            "first_sequence",
            "last_sequence",
            "high_water_sequence",
            "complete",
            "source",
            "freshness",
            "scope_semantics",
        }
        if frozenset(raw_coverage) != required:
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_COVERAGE")
        coverage = _json_mapping(raw_coverage)
        if not _journal_generation(coverage["journal_generation"]):
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_COVERAGE")
        if (
            not _identifier(coverage["account_key"])
            or coverage["owner_kind"] != "STRATEGY"
            or coverage["owner_ref"] != namespace.strategy_ref
            or not _identifier(coverage["scope_directory_revision"])
            or coverage["complete"] is not True
            or coverage["source"] != "EXECUTION_SQLITE_JOURNAL"
            or coverage["freshness"] != "DURABLE_CUT_NOT_PROVIDER_LIVE"
            or coverage["scope_semantics"] != "DURABLE_STRATEGY_SCOPE_NO_RUN_ISOLATION"
        ):
            raise ServiceExecutionRecoveryError("RECOVERY_SNAPSHOT_NOT_COMPLETE_STRATEGY_SCOPE")
        first_sequence = _optional_sequence(coverage["first_sequence"])
        last_sequence = _optional_sequence(coverage["last_sequence"])
        high_water = _sequence(coverage["high_water_sequence"])
        if not _valid_global_bounds(first_sequence, last_sequence, high_water):
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_COVERAGE")

        orders: list[dict[str, Any]] = []
        identities: set[tuple[str, str]] = set()
        for raw in raw_orders:
            if not isinstance(raw, Mapping) or frozenset(raw) != self._SNAPSHOT_ORDER_FIELDS:
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_ORDER")
            order = _json_mapping(raw)
            if not _identifier(order["scope_key"]) or not _identifier(order["intent_id"]):
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_ORDER")
            if not _digest(order["intent_fingerprint"]) or not _digest(order["submit_fingerprint"]):
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_ORDER")
            if (
                not _identifier(order["signal_id"])
                or not _identifier(order["instrument"])
                or not _enum(order["side"], {"BUY", "SELL"})
                or not _enum(
                    order["position_effect"],
                    {"OPEN", "CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY"},
                )
                or not _enum(order["order_type"], {"MARKET", "LIMIT"})
                or not _enum(order["time_in_force"], {"GTC", "IOC", "FOK", "DAY"})
                or not _identifier(order["metadata_version"])
                or not _enum(order["state"], self._EXECUTION_STATES)
            ):
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_ORDER")
            if type(order["reduce_only"]) is not bool or type(order["review_required"]) is not bool:
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_ORDER")
            if type(order["dispatch_attempts"]) is not int or order["dispatch_attempts"] < 0:
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_ORDER")
            if order["deadline_ns"] is not None:
                _sequence(order["deadline_ns"])
            quantity = _decimal_value(order["quantity"], positive=True)
            filled = _decimal_value(order["filled_quantity"], nonnegative=True)
            if filled > quantity:
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_ORDER")
            _decimal_value(order["price"], positive=True, optional=True)
            _decimal_value(order["average_price"], positive=True, optional=True)
            cumulative_commission = _decimal_value(order["cumulative_commission"], optional=True)
            _optional_identifier(order["provider_order_id"])
            if order["unknown_reason_code"] is not None and not _reason_code(
                order["unknown_reason_code"]
            ):
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_ORDER")
            if order["cumulative_commission_currency"] is not None and (
                cumulative_commission is None
                or not _identifier(order["cumulative_commission_currency"])
            ):
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_ORDER")
            latest_source_sequence = _sequence(order["latest_source_sequence"])
            latest_observation = _optional_sequence(order["latest_observation_sequence"])
            if (
                latest_source_sequence == 0
                or not _hex32(order["latest_source_event_id"])
                or (latest_observation is None) != (order["latest_observation_event_id"] is None)
                or (
                    order["latest_observation_event_id"] is not None
                    and not _hex32(order["latest_observation_event_id"])
                )
                or latest_source_sequence > coverage["high_water_sequence"]
                or (latest_observation is not None and latest_observation > latest_source_sequence)
                or (
                    latest_observation is not None
                    and latest_observation > coverage["high_water_sequence"]
                )
            ):
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_ORDER")
            if order["order_type"] == "LIMIT" and order["price"] is None:
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_ORDER")
            key = (str(order["scope_key"]), str(order["intent_id"]))
            if key in identities:
                raise ServiceExecutionRecoveryError("DUPLICATE_RECOVERY_ORDER")
            identities.add(key)
            orders.append(order)
        return coverage, orders

    def _validate_event_page(
        self,
        namespace: ServiceExecutionRecoveryNamespace,
        page: Mapping[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if (
            frozenset(page) != {"view", "version", "coverage", "events"}
            or page.get("view") != "EVENTS_AFTER"
            or type(page.get("version")) is not int
            or page["version"] != 1
        ):
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT_PAGE")
        raw_coverage = page.get("coverage")
        raw_events = page.get("events")
        if not isinstance(raw_coverage, Mapping) or type(raw_events) is not list:
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT_PAGE")
        required = {
            "account_key",
            "owner_kind",
            "owner_ref",
            "scope_directory_revision",
            "journal_generation",
            "first_sequence",
            "last_sequence",
            "high_water_sequence",
            "source",
            "freshness",
            "after_sequence",
            "scanned_through",
            "has_more",
            "complete",
            "scope_semantics",
        }
        if frozenset(raw_coverage) != required:
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_PAGE_COVERAGE")
        coverage = _json_mapping(raw_coverage)
        for name in ("account_key", "scope_directory_revision"):
            if not _identifier(coverage[name]):
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_PAGE_COVERAGE")
        if not _journal_generation(coverage["journal_generation"]):
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_PAGE_COVERAGE")
        if (
            coverage["owner_kind"] != "STRATEGY"
            or coverage["owner_ref"] != namespace.strategy_ref
            or coverage["complete"] is not True
            or coverage["source"] != "EXECUTION_SQLITE_JOURNAL"
            or coverage["freshness"] != "DURABLE_CUT_NOT_PROVIDER_LIVE"
            or type(coverage["has_more"]) is not bool
            or coverage["scope_semantics"] != "DURABLE_STRATEGY_SCOPE_NO_RUN_ISOLATION"
        ):
            raise ServiceExecutionRecoveryError("RECOVERY_EVENT_PAGE_INCOMPLETE")
        first_sequence = _optional_sequence(coverage["first_sequence"])
        last_sequence = _optional_sequence(coverage["last_sequence"])
        for name in ("high_water_sequence", "after_sequence", "scanned_through"):
            _sequence(coverage[name])
        if coverage["high_water_sequence"] < coverage["after_sequence"] or not _valid_global_bounds(
            first_sequence, last_sequence, coverage["high_water_sequence"]
        ):
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_PAGE_COVERAGE")

        events: list[dict[str, Any]] = []
        previous_sequence = coverage["after_sequence"]
        for raw in raw_events:
            if not isinstance(raw, Mapping) or frozenset(raw) != self._EVENT_FIELDS:
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT")
            event = _json_mapping(raw)
            for name in ("scope_key", "intent_id"):
                if not _identifier(event[name]):
                    raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT")
            if not _hex32(event["event_id"]) or not _journal_generation(
                event["journal_generation"]
            ):
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT")
            for name in ("intent_fingerprint", "submit_fingerprint", "event_sha256"):
                if not _digest(event[name]):
                    raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT")
            if event["journal_generation"] != coverage["journal_generation"]:
                raise ServiceExecutionRecoveryError("RECOVERY_EVENT_GENERATION_MISMATCH")
            sequence = _sequence(event["sequence"])
            if sequence <= previous_sequence or sequence > coverage["high_water_sequence"]:
                raise ServiceExecutionRecoveryError("RECOVERY_EVENT_SEQUENCE_INVALID")
            if not _enum(event["event_type"], self._EVENT_TYPES) or not _enum(
                event["state"], self._EXECUTION_STATES
            ):
                raise ServiceExecutionRecoveryError("RECOVERY_EVENT_TYPE_UNSUPPORTED")
            expected_state = self._EVENT_FIXED_STATES.get(event["event_type"])
            if expected_state is not None and event["state"] != expected_state:
                raise ServiceExecutionRecoveryError("RECOVERY_EVENT_STATE_MISMATCH")
            if (
                event["event_type"]
                in {
                    "provider_observation",
                    "reconciled_observation",
                    "provider_commission_evidence",
                }
                and event["state"] not in self._OBSERVATION_STATES
            ):
                raise ServiceExecutionRecoveryError("RECOVERY_EVENT_STATE_MISMATCH")
            if not isinstance(event["details"], Mapping):
                raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT_DETAILS")
            event["details"] = _json_mapping(event["details"])
            _validate_event_details(event["event_type"], event["details"])
            previous_sequence = sequence
            events.append(event)
        last_sequence = events[-1]["sequence"] if events else coverage["after_sequence"]
        if coverage["has_more"]:
            if not events or coverage["scanned_through"] != last_sequence:
                raise ServiceExecutionRecoveryError("RECOVERY_PAGE_SCAN_BOUND_INVALID")
        elif coverage["scanned_through"] != coverage["high_water_sequence"]:
            raise ServiceExecutionRecoveryError("RECOVERY_PAGE_SCAN_BOUND_INVALID")
        if coverage["scanned_through"] < last_sequence:
            raise ServiceExecutionRecoveryError("RECOVERY_PAGE_SCAN_BOUND_INVALID")
        return coverage, events

    def _apply_one_event(
        self,
        cursor: sqlite3.Cursor,
        namespace: ServiceExecutionRecoveryNamespace,
        event: Mapping[str, Any],
        now_ns: int,
    ) -> None:
        receipt_id = _receipt_id(
            str(event["scope_key"]),
            str(event["journal_generation"]),
            str(int(event["sequence"])),
            str(event["event_id"]),
            str(event["event_sha256"]),
            str(event["intent_fingerprint"]),
        )
        event_json = _canonical_json(event)
        existing = cursor.execute(
            """SELECT event_id, event_sha256, intent_id, intent_fingerprint, event_json
               FROM service_recovery_event_receipts
               WHERE account_ref = ? AND strategy_ref = ? AND logical_run_id = ?
                 AND scope_key = ? AND journal_generation = ? AND sequence = ?""",
            (
                namespace.account_ref,
                namespace.strategy_ref,
                namespace.logical_run_id,
                event["scope_key"],
                event["journal_generation"],
                event["sequence"],
            ),
        ).fetchone()
        if existing is not None:
            if (
                str(existing["event_id"]) != event["event_id"]
                or str(existing["event_sha256"]) != event["event_sha256"]
                or str(existing["intent_id"]) != event["intent_id"]
                or str(existing["intent_fingerprint"]) != event["intent_fingerprint"]
                or str(existing["event_json"]) != event_json
            ):
                raise ServiceExecutionRecoveryError("RECOVERY_EVENT_RECEIPT_CONFLICT")
            return

        manifest = cursor.execute(
            """SELECT logical_run_id, submit_fingerprint, payload_json, server_scope_key,
                      server_intent_fingerprint
               FROM service_recovery_intents
               WHERE account_ref = ? AND strategy_ref = ? AND intent_id = ?""",
            (namespace.account_ref, namespace.strategy_ref, event["intent_id"]),
        ).fetchone()
        matched = False
        if manifest is not None and str(manifest["logical_run_id"]) == namespace.logical_run_id:
            if str(manifest["submit_fingerprint"]) != event["submit_fingerprint"]:
                raise ServiceExecutionRecoveryError("RECOVERY_EVENT_SUBMIT_FINGERPRINT_MISMATCH")
            if manifest["server_scope_key"] not in (None, event["scope_key"]):
                raise ServiceExecutionRecoveryError("RECOVERY_EVENT_SCOPE_MISMATCH")
            if manifest["server_intent_fingerprint"] not in (
                None,
                event["intent_fingerprint"],
            ):
                raise ServiceExecutionRecoveryError("RECOVERY_EVENT_INTENT_FINGERPRINT_MISMATCH")
            cursor.execute(
                """UPDATE service_recovery_intents
                   SET server_scope_key = ?, server_intent_fingerprint = ?, updated_at_ns = ?
                   WHERE account_ref = ? AND strategy_ref = ? AND intent_id = ?
                     AND logical_run_id = ?""",
                (
                    event["scope_key"],
                    event["intent_fingerprint"],
                    now_ns,
                    namespace.account_ref,
                    namespace.strategy_ref,
                    event["intent_id"],
                    namespace.logical_run_id,
                ),
            )
            matched = True
        if matched and event["event_type"] in {
            "provider_observation",
            "reconciled_observation",
            "provider_commission_evidence",
            "cancelled_by_cancel_intent",
        }:
            positions, cumulative = self._trade_projection_before(
                cursor, namespace, int(event["sequence"])
            )
            details = event["details"]
            filled = _decimal_value(details["filled_quantity"], nonnegative=True)
            previous = cumulative.get(str(event["intent_id"]), Decimal(0))
            if filled < previous:
                raise ServiceExecutionRecoveryError("RECOVERY_FILL_CURSOR_REGRESSION")
            delta = filled - previous
            if delta:
                binding_row = cursor.execute(
                    """SELECT binding_json FROM service_recovery_intent_bindings
                       WHERE account_ref = ? AND strategy_ref = ? AND intent_id = ?
                         AND logical_run_id = ?""",
                    (
                        *_intent_namespace_values(namespace, str(event["intent_id"])),
                        namespace.logical_run_id,
                    ),
                ).fetchone()
                if binding_row is None:
                    raise ServiceExecutionRecoveryError("RECOVERY_TRADE_BINDING_MISSING")
                binding = json.loads(str(binding_row["binding_json"]))
                submit = json.loads(str(manifest["payload_json"]))
                self._apply_trade_delta(
                    positions,
                    (binding["data_name"], binding["tradeid"]),
                    submit["side"],
                    submit["position_effect"],
                    delta,
                )
        cursor.execute(
            """INSERT INTO service_recovery_event_receipts(
                   account_ref, strategy_ref, logical_run_id, scope_key,
                   journal_generation, sequence, event_id, event_sha256,
                   intent_id, intent_fingerprint, event_type, state,
                   matched_manifest, event_json, receipt_id, created_at_ns
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                namespace.account_ref,
                namespace.strategy_ref,
                namespace.logical_run_id,
                event["scope_key"],
                event["journal_generation"],
                event["sequence"],
                event["event_id"],
                event["event_sha256"],
                event["intent_id"],
                event["intent_fingerprint"],
                event["event_type"],
                event["state"],
                int(matched),
                event_json,
                receipt_id,
                now_ns,
            ),
        )
        if not matched:
            return
        cursor.execute(
            """INSERT INTO service_recovery_intent_projections(
                   account_ref, strategy_ref, logical_run_id, intent_id,
                   sequence, receipt_id, event_json, updated_at_ns
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(account_ref, strategy_ref, logical_run_id, intent_id)
               DO UPDATE SET sequence = excluded.sequence, receipt_id = excluded.receipt_id,
                             event_json = excluded.event_json,
                             updated_at_ns = excluded.updated_at_ns
               WHERE excluded.sequence > service_recovery_intent_projections.sequence""",
            (
                namespace.account_ref,
                namespace.strategy_ref,
                namespace.logical_run_id,
                event["intent_id"],
                event["sequence"],
                receipt_id,
                event_json,
                now_ns,
            ),
        )
        if event["event_type"] in self._CALLBACK_EVENT_TYPES:
            cursor.execute(
                """INSERT INTO service_recovery_callbacks(
                       account_ref, strategy_ref, logical_run_id, receipt_id,
                       delivery_attempts, last_attempt_at_ns, acknowledged_at_ns
                   ) VALUES (?, ?, ?, ?, 0, NULL, NULL)""",
                (*_namespace_values(namespace), receipt_id),
            )

    def _ensure_namespace(
        self,
        cursor: sqlite3.Cursor,
        namespace: ServiceExecutionRecoveryNamespace,
        now_ns: int,
    ) -> None:
        cursor.execute(
            """INSERT OR IGNORE INTO service_recovery_runs(
                   account_ref, strategy_ref, logical_run_id,
                   server_account_key, journal_generation, directory_revision,
                   snapshot_high_water, event_high_water, event_cursor,
                   scanned_through, snapshot_hash, created_at_ns, updated_at_ns
               ) VALUES (?, ?, ?, NULL, NULL, NULL, NULL, 0, NULL, NULL, NULL, ?, ?)""",
            (*_namespace_values(namespace), now_ns, now_ns),
        )

    def _create_schema(self) -> None:
        with self._lock:
            cursor = self._connection.cursor()
            try:
                cursor.executescript(
                    """
                CREATE TABLE IF NOT EXISTS service_recovery_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS service_recovery_runs (
                    account_ref TEXT NOT NULL,
                    strategy_ref TEXT NOT NULL,
                    logical_run_id TEXT NOT NULL,
                    server_account_key TEXT,
                    journal_generation TEXT,
                    directory_revision TEXT,
                    snapshot_high_water INTEGER,
                    event_high_water INTEGER NOT NULL,
                    event_cursor INTEGER,
                    scanned_through INTEGER,
                    snapshot_hash TEXT,
                    created_at_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(account_ref, strategy_ref, logical_run_id)
                );
                CREATE TABLE IF NOT EXISTS service_recovery_intents (
                    account_ref TEXT NOT NULL,
                    strategy_ref TEXT NOT NULL,
                    intent_id TEXT NOT NULL,
                    logical_run_id TEXT NOT NULL,
                    submit_fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    server_scope_key TEXT,
                    server_intent_fingerprint TEXT,
                    created_at_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(account_ref, strategy_ref, intent_id)
                );
                CREATE TABLE IF NOT EXISTS service_recovery_intent_bindings (
                    account_ref TEXT NOT NULL,
                    strategy_ref TEXT NOT NULL,
                    intent_id TEXT NOT NULL,
                    logical_run_id TEXT NOT NULL,
                    binding_json TEXT NOT NULL,
                    PRIMARY KEY(account_ref, strategy_ref, intent_id)
                );
                CREATE TABLE IF NOT EXISTS service_recovery_baselines (
                    account_ref TEXT NOT NULL,
                    strategy_ref TEXT NOT NULL,
                    logical_run_id TEXT NOT NULL,
                    server_account_key TEXT NOT NULL,
                    journal_generation TEXT NOT NULL,
                    directory_revision TEXT NOT NULL,
                    baseline_cursor INTEGER NOT NULL,
                    baseline_hash TEXT NOT NULL,
                    baseline_json TEXT NOT NULL,
                    created_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(account_ref, strategy_ref, logical_run_id)
                );
                CREATE TABLE IF NOT EXISTS service_recovery_cancels (
                    account_ref TEXT NOT NULL,
                    strategy_ref TEXT NOT NULL,
                    cancel_id TEXT NOT NULL,
                    logical_run_id TEXT NOT NULL,
                    target_intent_id TEXT NOT NULL,
                    provider_order_id TEXT NOT NULL,
                    cancel_fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(account_ref, strategy_ref, cancel_id)
                );
                CREATE TABLE IF NOT EXISTS service_recovery_snapshot_orders (
                    account_ref TEXT NOT NULL,
                    strategy_ref TEXT NOT NULL,
                    logical_run_id TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    intent_id TEXT NOT NULL,
                    matched_manifest INTEGER NOT NULL,
                    order_json TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    PRIMARY KEY(account_ref, strategy_ref, logical_run_id, scope_key, intent_id)
                );
                CREATE TABLE IF NOT EXISTS service_recovery_pages (
                    account_ref TEXT NOT NULL,
                    strategy_ref TEXT NOT NULL,
                    logical_run_id TEXT NOT NULL,
                    journal_generation TEXT NOT NULL,
                    directory_revision TEXT NOT NULL,
                    after_sequence INTEGER NOT NULL,
                    scanned_through INTEGER NOT NULL,
                    page_sha256 TEXT NOT NULL,
                    created_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(account_ref, strategy_ref, logical_run_id,
                                journal_generation, directory_revision, after_sequence)
                );
                CREATE TABLE IF NOT EXISTS service_recovery_event_receipts (
                    account_ref TEXT NOT NULL,
                    strategy_ref TEXT NOT NULL,
                    logical_run_id TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    journal_generation TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    event_sha256 TEXT NOT NULL,
                    intent_id TEXT NOT NULL,
                    intent_fingerprint TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    state TEXT NOT NULL,
                    matched_manifest INTEGER NOT NULL,
                    event_json TEXT NOT NULL,
                    receipt_id TEXT NOT NULL,
                    created_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(account_ref, strategy_ref, logical_run_id,
                                scope_key, journal_generation, sequence),
                    UNIQUE(account_ref, strategy_ref, logical_run_id, receipt_id)
                );
                CREATE TABLE IF NOT EXISTS service_recovery_intent_projections (
                    account_ref TEXT NOT NULL,
                    strategy_ref TEXT NOT NULL,
                    logical_run_id TEXT NOT NULL,
                    intent_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    receipt_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(account_ref, strategy_ref, logical_run_id, intent_id)
                );
                CREATE TABLE IF NOT EXISTS service_recovery_callbacks (
                    account_ref TEXT NOT NULL,
                    strategy_ref TEXT NOT NULL,
                    logical_run_id TEXT NOT NULL,
                    receipt_id TEXT NOT NULL,
                    delivery_attempts INTEGER NOT NULL,
                    last_attempt_at_ns INTEGER,
                    acknowledged_at_ns INTEGER,
                    PRIMARY KEY(account_ref, strategy_ref, logical_run_id, receipt_id)
                );
                INSERT OR IGNORE INTO service_recovery_meta(key, value)
                    VALUES ('schema_version', '1');
                """
                )
                row = cursor.execute(
                    "SELECT value FROM service_recovery_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row is None or str(row["value"]) not in {"1", str(self._SCHEMA_VERSION)}:
                    raise ServiceExecutionRecoveryError("RECOVERY_SCHEMA_VERSION_UNSUPPORTED")
                if str(row["value"]) == "1":
                    cursor.execute(
                        "UPDATE service_recovery_meta SET value = ? WHERE key = 'schema_version'",
                        (str(self._SCHEMA_VERSION),),
                    )
            finally:
                cursor.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cursor = self._connection.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                yield cursor
                cursor.execute("COMMIT")
            except BaseException:
                try:
                    cursor.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                cursor.close()


def _validate_submit_payload(payload: Mapping[str, Any]) -> None:
    if (
        not _identifier(payload["intent_id"])
        or not _identifier(payload["signal_id"])
        or not _identifier(payload["instrument"])
        or not _enum(payload["side"], {"BUY", "SELL"})
        or not _enum(
            payload["position_effect"],
            {"OPEN", "CLOSE", "CLOSE_TODAY", "CLOSE_YESTERDAY"},
        )
        or not _enum(payload["order_type"], {"MARKET", "LIMIT"})
        or not _enum(payload["time_in_force"], {"GTC", "IOC", "FOK", "DAY"})
        or type(payload["reduce_only"]) is not bool
        or not _identifier(payload["metadata_version"])
        or (payload["deadline_ns"] is not None and _sequence(payload["deadline_ns"]) == 0)
        or type(payload["tags"]) is not dict
        or any(
            not _identifier(key) or not _identifier(value) for key, value in payload["tags"].items()
        )
    ):
        raise ServiceExecutionRecoveryError("INVALID_INTENT_MANIFEST")
    for name in ("quantity", "price"):
        value = payload[name]
        if name == "price" and value is None:
            continue
        if type(value) is not str:
            raise ServiceExecutionRecoveryError("INVALID_INTENT_MANIFEST")
        try:
            number = Decimal(value)
        except Exception as error:  # noqa: BLE001 - finite local contract error
            raise ServiceExecutionRecoveryError("INVALID_INTENT_MANIFEST") from error
        if (
            not number.is_finite()
            or (name == "quantity" and number <= 0)
            or (name == "price" and number <= 0)
        ):
            raise ServiceExecutionRecoveryError("INVALID_INTENT_MANIFEST")


def _json_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ServiceExecutionRecoveryError("INVALID_RECOVERY_JSON")
    result = {}
    for key, item in value.items():
        result[key] = _json_value(item)
    return result


def _json_value(value: Any) -> Any:
    if value is None or type(value) in (str, bool, int):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        raise ServiceExecutionRecoveryError("INVALID_RECOVERY_JSON")
    if isinstance(value, Mapping):
        return _json_mapping(value)
    if type(value) in (list, tuple):
        return [_json_value(item) for item in value]
    raise ServiceExecutionRecoveryError("INVALID_RECOVERY_JSON")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_value(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _namespace_values(namespace: ServiceExecutionRecoveryNamespace) -> tuple[str, str, str]:
    return namespace.account_ref, namespace.strategy_ref, namespace.logical_run_id


def _identifier(value: Any) -> bool:
    return bool(
        type(value) is str
        and 1 <= len(value) <= 192
        and value == value.strip()
        and all(character.isascii() and character.isprintable() for character in value)
    )


def _enum(value: Any, choices: AbstractSet[str]) -> bool:
    return type(value) is str and value in choices


def _digest(value: Any) -> bool:
    return bool(
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _journal_generation(value: Any) -> bool:
    return _hex32(value)


def _hex32(value: Any) -> bool:
    return bool(
        type(value) is str
        and len(value) == 32
        and all(character in "0123456789abcdef" for character in value)
    )


def _sequence(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ServiceExecutionRecoveryError("INVALID_RECOVERY_SEQUENCE")
    return value


def _optional_sequence(value: Any) -> Optional[int]:
    if value is None:
        return None
    return _sequence(value)


def _valid_global_bounds(
    first_sequence: Optional[int], last_sequence: Optional[int], high_water: int
) -> bool:
    """Validate the whole journal's contiguous bounds, not a selected page."""

    if high_water == 0:
        return first_sequence is None and last_sequence is None
    return first_sequence == 1 and last_sequence == high_water


def _decimal_value(
    value: Any,
    *,
    positive: bool = False,
    nonnegative: bool = False,
    optional: bool = False,
) -> Optional[Decimal]:
    if value is None and optional:
        return None
    if type(value) is not str:
        raise ServiceExecutionRecoveryError("INVALID_RECOVERY_DECIMAL")
    try:
        number = Decimal(value)
    except Exception as error:  # noqa: BLE001 - finite local contract error
        raise ServiceExecutionRecoveryError("INVALID_RECOVERY_DECIMAL") from error
    if (
        not number.is_finite()
        or format(number, "f") != value
        or (positive and number <= 0)
        or (nonnegative and number < 0)
    ):
        raise ServiceExecutionRecoveryError("INVALID_RECOVERY_DECIMAL")
    return number


def _optional_identifier(value: Any) -> None:
    if value is not None and not _identifier(value):
        raise ServiceExecutionRecoveryError("INVALID_RECOVERY_IDENTIFIER")


def _reason_code(value: Any) -> bool:
    return type(value) is str and _REASON_CODE.fullmatch(value) is not None


def _validate_event_details(event_type: str, details: Mapping[str, Any]) -> None:
    """Accept only the event-specific safe projection, never raw payload data."""

    empty_detail_events = {
        "intent_recorded",
        "intent_admitted",
        "pending_admission_reference_reauthorized",
    }
    reason_detail_events = {
        "intent_rejected",
        "intent_blocked",
        "dispatch_unknown",
        "dispatch_blocked",
        "manual_review_required",
    }
    if event_type in empty_detail_events:
        if details:
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT_DETAILS")
        return
    if event_type in reason_detail_events:
        if frozenset(details) != {"reason_code"}:
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT_DETAILS")
        if not _reason_code(details["reason_code"]):
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT_DETAILS")
        return
    if event_type == "dispatch_claimed":
        attempt = details.get("dispatch_attempt")
        if frozenset(details) != {"dispatch_attempt"} or type(attempt) is not int or attempt < 1:
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT_DETAILS")
        return

    if event_type in {"provider_observation", "reconciled_observation"}:
        required = {
            "provider_order_id",
            "filled_quantity",
            "average_price",
            "cumulative_commission",
            "reason_code",
            "source",
        }
        optional = {"cumulative_commission_currency"}
    elif event_type == "provider_commission_evidence":
        required = {
            "provider_order_id",
            "filled_quantity",
            "average_price",
            "cumulative_commission",
            "source",
        }
        optional = {"cumulative_commission_currency"}
    elif event_type == "cancelled_by_cancel_intent":
        required = {
            "cancel_id",
            "provider_order_id",
            "source",
            "filled_quantity",
            "average_price",
            "cumulative_commission",
        }
        optional = set()
    else:
        raise ServiceExecutionRecoveryError("RECOVERY_EVENT_TYPE_UNSUPPORTED")

    if not required.issubset(details) or not set(details).issubset(required | optional):
        raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT_DETAILS")
    if event_type == "cancelled_by_cancel_intent":
        if not _identifier(details["cancel_id"]) or not _identifier(details["provider_order_id"]):
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT_DETAILS")
    else:
        _optional_identifier(details["provider_order_id"])
    if not _enum(details["source"], {"provider", "reconcile"}):
        raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT_DETAILS")
    expected_source = {
        "provider_observation": "provider",
        "reconciled_observation": "reconcile",
    }.get(event_type)
    if expected_source is not None and details["source"] != expected_source:
        raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT_DETAILS")
    _decimal_value(details["filled_quantity"], nonnegative=True)
    _decimal_value(details["average_price"], positive=True, optional=True)
    cumulative_commission = _decimal_value(details["cumulative_commission"], optional=True)
    if "reason_code" in details:
        if details["reason_code"] is not None and not _reason_code(details["reason_code"]):
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT_DETAILS")
    if "cumulative_commission_currency" in details:
        if cumulative_commission is None or not _identifier(
            details["cumulative_commission_currency"]
        ):
            raise ServiceExecutionRecoveryError("INVALID_RECOVERY_EVENT_DETAILS")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _snapshot_hash(coverage: Mapping[str, Any], orders: list[dict[str, Any]]) -> str:
    payload = _canonical_json({"coverage": coverage, "orders": orders})
    return _sha256(payload.encode("utf-8"))


def _intent_namespace_values(
    namespace: ServiceExecutionRecoveryNamespace, intent_id: str
) -> tuple[str, str, str]:
    return namespace.account_ref, namespace.strategy_ref, intent_id


def _validate_recovery_binding(
    raw: Mapping[str, Any], submit_payload: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or frozenset(raw) != {"tradeid", "data_name"}:
        raise ServiceExecutionRecoveryError("INVALID_INTENT_RECOVERY_BINDING")
    if type(raw["tradeid"]) is not int or not _identifier(raw["data_name"]):
        raise ServiceExecutionRecoveryError("INVALID_INTENT_RECOVERY_BINDING")
    return {"tradeid": raw["tradeid"], "data_name": raw["data_name"]}


def _canonical_decimal_text(value: Any) -> str:
    if type(value) is Decimal:
        number = value
    elif type(value) is str:
        try:
            number = Decimal(value)
        except Exception as error:  # noqa: BLE001 - finite local contract error
            raise ServiceExecutionRecoveryError("INVALID_OWNER_BOOK_DECIMAL") from error
    else:
        raise ServiceExecutionRecoveryError("INVALID_OWNER_BOOK_DECIMAL")
    if not number.is_finite():
        raise ServiceExecutionRecoveryError("INVALID_OWNER_BOOK_DECIMAL")
    return format(number, "f")


def _identifier_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not _identifier(value):
        raise ServiceExecutionRecoveryError("INVALID_OWNER_BOOK_IDENTIFIER")
    return value


def _receipt_id(*parts: str) -> str:
    return _sha256("\0".join(parts).encode("utf-8"))


__all__ = [
    "ServiceExecutionRecoveryCallback",
    "ServiceExecutionRecoveryError",
    "ServiceExecutionRecoveryJournal",
    "ServiceExecutionRecoveryNamespace",
]
