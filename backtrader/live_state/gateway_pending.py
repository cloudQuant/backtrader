"""Explicit, durable Gateway client host sharing the local pending journal.

The binding and observations are labels supplied by trusted callers, not
proof of venue state or authority. Ordinary version-one pending paths never
import this optional integration.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from bt_api_base.direct_write_protocol import DirectWriteError, NativeOrderIdentity
from bt_api_base.gateway_cancel_protocol import GatewayCancelRecord
from bt_api_base.gateway_direct_protocol import (
    GatewayCommandBinding,
    GatewayCommandRecord,
)
from bt_api_py.direct_write import project_direct_strong_identity_keys
from bt_api_py.gateway_direct_client import (
    GatewayCancelPlan,
    gateway_intent_from_mapping,
    gateway_intent_to_mapping,
    gateway_cancel_plan_from_mapping,
    gateway_cancel_plan_to_mapping,
    gateway_release_from_mapping,
    gateway_release_to_mapping,
    validate_gateway_record_progress,
    validate_gateway_cancel_record_progress,
)

from ._common import is_strict_int, is_uuid4, new_uuid4, strict_equal, utc_now_iso
from .atomic import LiveStateCorrupt
from .pending import PendingCommandStore, STATUS_PREPARED, _identity_key, _identity_view

_BINDING_FIELDS = ("journal_id", "account_scope", "strategy_scope", "principal")
_ENTRY_KEYS = {"intent", "record", "marker_id", "release", "local_seq", "bt_ref"}
_MAX_ENTRIES = 100_000


@dataclass(frozen=True)
class GatewayPendingContext:
    marker_id: str | None
    local_seq: int | None
    bt_ref: int | None


def _binding_mapping(binding: GatewayCommandBinding) -> dict:
    if type(binding) is not GatewayCommandBinding:
        raise ValueError("INVALID_BINDING")
    binding = GatewayCommandBinding(*(getattr(binding, name) for name in _BINDING_FIELDS))
    return {name: getattr(binding, name) for name in _BINDING_FIELDS}


def _binding_from_mapping(value: object) -> GatewayCommandBinding:
    if type(value) is not dict or set(value) != set(_BINDING_FIELDS):
        raise ValueError("INVALID_BINDING")
    return GatewayCommandBinding(*(value[name] for name in _BINDING_FIELDS))


def _record(value: object, binding: GatewayCommandBinding) -> GatewayCommandRecord:
    if type(value) is GatewayCommandRecord:
        value = value.to_mapping()
    return GatewayCommandRecord.from_mapping(value, expected_binding=binding)


def _positive_or_none(value: object) -> bool:
    return value is None or is_strict_int(value, minimum=1)


def _json_equal(left: object, right: object) -> bool:
    options = {"sort_keys": True, "separators": (",", ":"), "allow_nan": False}
    return json.dumps(left, **options) == json.dumps(right, **options)


def _check_native_marker_facts(marker: dict, identity: Any) -> None:
    known = dict(identity.fields)
    known["client_order_id"] = identity.client_order_id
    if any(key in marker["facts"] and marker["facts"][key] is not None
           and not strict_equal(marker["facts"][key], value) for key, value in known.items()):
        raise ValueError("GATEWAY_NATIVE_CONFLICT")


def _legacy_identity_candidates(marker: dict) -> tuple[set[str], set[str]]:
    """Project both possible SDK scopes; neither projection establishes scope."""
    native = dict(marker["native_identity"])
    facts = marker["facts"]
    for key, value in native.items():
        if key in facts and facts[key] is not None and not strict_equal(facts[key], value):
            raise ValueError("LEGACY_IDENTITY_FACT_CONFLICT")
    for key in ("client_order_id", "exchange_name", "session_generation"):
        if (key in facts and facts[key] is not None and marker[key] is not None
                and not strict_equal(facts[key], marker[key])):
            raise ValueError("LEGACY_IDENTITY_FACT_CONFLICT")
    view = _identity_view(marker)
    fields = {key: value for key, value in view.items()
              if key not in ("exchange_name", "client_order_id", "session_generation")}
    top_day, field_day = marker["trading_day"], fields.get("trading_day")
    if top_day is not None and field_day is not None and not strict_equal(top_day, field_day):
        raise ValueError("LEGACY_IDENTITY_DAY_CONFLICT")
    day = top_day if top_day is not None else field_day
    if day is not None:
        fields["trading_day"] = day
    if "client_order_id" in native:
        raise ValueError("LEGACY_IDENTITY_INVALID")
    generation = marker["session_generation"]
    if generation is None:
        generation = facts.get("session_generation")
    client_order_id = view.get("client_order_id")
    identity = NativeOrderIdentity(marker["exchange_name"], client_order_id,
                                   fields, generation)
    candidates: set[str] = set()
    for scoped in ((False, True) if day is not None else (False,)):
        try:
            keys = project_direct_strong_identity_keys(identity, day_scoped_ids=scoped)
        except DirectWriteError as exc:
            if exc.code == "direct_identity_strong_key_unavailable":
                continue
            raise ValueError("LEGACY_IDENTITY_INVALID") from None
        candidates.update(hashlib.sha256(key.encode("utf-8")).hexdigest() for key in keys)
    original_fields = dict(native)
    if day is not None:
        original_fields["trading_day"] = day
    original = NativeOrderIdentity(marker["exchange_name"], client_order_id,
                                   original_fields, generation)
    options = {"sort_keys": True, "separators": (",", ":"), "allow_nan": False}
    exact = {json.dumps(identity.to_dict(), **options), json.dumps(original.to_dict(), **options)}
    return exact, candidates


def _marker_for(state: dict, marker_id: str | None) -> dict | None:
    if marker_id is None:
        return None
    found = state["active"].get(marker_id)
    if found is not None:
        return found
    return next((m for m in state["history"] if m["marker_id"] == marker_id), None)


def _marker_index(state: dict) -> dict:
    return {m["marker_id"]: m for m in list(state["active"].values()) + state["history"]}


def _unresolved(state: dict, entry: dict, markers: dict | None = None) -> bool:
    marker = (_marker_for(state, entry["marker_id"]) if markers is None
              else markers.get(entry["marker_id"]))
    if marker is not None:
        return marker["status"] != "TERMINAL"
    record = entry["record"]
    return record is None or record["state"] not in {"NOT_SENT", "RELEASED", "EXPIRED"}


def has_unresolved_gateway_intents(state: dict) -> bool:
    markers = _marker_index(state)
    return any(_unresolved(state, entry, markers) for entry in state["gateway"]["intents"].values())


def has_unresolved_gateway_cancels(state: dict) -> bool:
    if state["version"] not in (3, 4, 5, 6):
        return False
    entries = state["gateway"]["intents"]
    markers = _marker_index(state)
    for attempt in state["gateway"]["cancel_attempts"].values():
        record = attempt["record"]
        if record is None or record["state"] in {"REQUESTED", "DISPATCHING", "UNKNOWN"}:
            return True
        if record["state"] == "SENT":
            marker = markers.get(entries[attempt["plan"]["request_key"]]["marker_id"])
            if marker is None or marker["status"] != "TERMINAL":
                return True
    return False


def _cancel_plan(value: object, binding: GatewayCommandBinding, entries: dict):
    plan = gateway_cancel_plan_from_mapping(value, expected_binding=binding)
    entry = entries.get(plan.request_key)
    if entry is None or entry["record"] is None:
        raise ValueError("GATEWAY_CANCEL_TARGET_MISSING")
    intent = gateway_intent_from_mapping(entry["intent"], expected_binding=binding)
    original = _record(entry["record"], binding)
    if (plan.route != intent.route or plan.reservation_id != original.reservation_id
            or plan.digest != original.digest or plan.digest != intent.digest
            or original.native_identity is None):
        raise ValueError("GATEWAY_CANCEL_TARGET_CONFLICT")
    return plan


def _cancel_record(value: object, binding: GatewayCommandBinding, plan: Any):
    if type(value) is GatewayCancelRecord:
        value = value.to_mapping()
    record = GatewayCancelRecord.from_mapping(value, expected_binding=binding)
    if (record.operation_id != plan.operation_id or record.request_key != plan.request_key
            or record.target_reservation_id != plan.reservation_id
            or record.target_digest != plan.digest):
        raise ValueError("GATEWAY_CANCEL_RECORD_CONFLICT")
    return record


def has_active_gateway_sequence(state: dict, local_seq: int) -> bool:
    markers = _marker_index(state)
    return any(entry["local_seq"] == local_seq and _unresolved(state, entry, markers)
               for entry in state["gateway"]["intents"].values())


def validate_gateway_state(state: dict, path: str) -> None:
    """Validate Gateway state and all cross-references before reading or mutation."""
    try:
        gateway = state["gateway"]
        gateway_keys = {"binding", "max_entries", "intents"}
        if state["version"] in (3, 4, 5, 6):
            gateway_keys |= {"max_cancel_entries", "cancel_attempts"}
        if state["version"] in (4, 5, 6):
            gateway_keys.add("execution")
        if state["version"] in (5, 6):
            gateway_keys |= {"order_snapshots", "max_order_snapshot_bytes"}
        if state["version"] == 6:
            gateway_keys.add("local_notifications")
        if type(gateway) is not dict or set(gateway) != gateway_keys:
            raise ValueError("gateway_shape")
        binding = _binding_from_mapping(gateway["binding"])
        capacity, entries = gateway["max_entries"], gateway["intents"]
        if not is_strict_int(capacity, minimum=1) or capacity > _MAX_ENTRIES:
            raise ValueError("capacity")
        if type(entries) is not dict or len(entries) > capacity:
            raise ValueError("intents")
        markers = list(state["active"].values()) + state["history"]
        marker_ids = [m["marker_id"] for m in markers]
        if len(set(marker_ids)) != len(marker_ids):
            raise ValueError("duplicate_marker")
        gateway_markers = {m["marker_id"]: m for m in markers if "gateway_ref" in m}
        markers_by_id = {m["marker_id"]: m for m in markers}
        seen_markers, strong_keys, native_keys, native_exchanges = set(), set(), set(), set()
        for key, entry in entries.items():
            if type(entry) is not dict or set(entry) != _ENTRY_KEYS:
                raise ValueError("entry")
            intent = gateway_intent_from_mapping(entry["intent"], expected_binding=binding)
            if type(key) is not str or key != intent.request_key:
                raise ValueError("intent_key")
            if not all(_positive_or_none(entry[name]) for name in ("local_seq", "bt_ref")):
                raise ValueError("facts")
            record = None if entry["record"] is None else _record(entry["record"], binding)
            if record is not None:
                validate_gateway_record_progress(None, record)
                if record.request_key != key or record.digest != intent.digest:
                    raise ValueError("record_identity")
                for digest in record.strong_identity_key_digests:
                    if digest in strong_keys:
                        raise ValueError("strong_identity_duplicate")
                    strong_keys.add(digest)
                if record.native_identity is not None:
                    native_exchanges.add(record.native_identity.exchange_name)
                    native = json.dumps(record.native_identity.to_dict(), sort_keys=True, separators=(",", ":"))
                    if native in native_keys:
                        raise ValueError("identity_duplicate")
                    native_keys.add(native)
            release = None if entry["release"] is None else gateway_release_from_mapping(entry["release"])
            if release is not None and (record is None or release.request_key != key
                    or release.reservation_id != record.reservation_id or release.digest != intent.digest):
                raise ValueError("release_identity")
            if (release is not None and record.release_operation_id is not None
                    and (release.operation_id != record.release_operation_id
                         or release.expected_version != record.release_expected_version)):
                raise ValueError("release_operation")
            marker_id = entry["marker_id"]
            if marker_id is not None:
                if not is_uuid4(marker_id) or marker_id in seen_markers or record is None:
                    raise ValueError("marker_id")
                marker = gateway_markers.get(marker_id)
                if marker is None or marker["gateway_ref"] != {"request_key": key}:
                    raise ValueError("marker_link")
                if marker["local_seq"] != entry["local_seq"] or marker["bt_ref"] != entry["bt_ref"]:
                    raise ValueError("marker_facts")
                if marker["host_scope"] != state["strategy_uuid"]:
                    raise ValueError("marker_scope")
                payload = json.loads(intent.canonical_payload)
                if (marker["operation"] != "place" or marker["symbol"] != payload["symbol"]
                        or marker["request_summary"] != payload):
                    raise ValueError("marker_payload")
                identity = record.native_identity
                if identity is None:
                    if (marker["native_identity"] != {} or marker["client_order_id"] is not None
                            or marker["exchange_name"] is not None or marker["session_generation"] is not None
                            or marker["trading_day"] is not None):
                        raise ValueError("marker_identity")
                elif (not _json_equal(marker["native_identity"], dict(identity.fields))
                      or not strict_equal(marker["client_order_id"], identity.client_order_id)
                      or not strict_equal(marker["exchange_name"], identity.exchange_name)
                      or not strict_equal(marker["session_generation"], identity.session_generation)
                      or not strict_equal(marker["trading_day"], identity.fields.get("trading_day"))):
                    raise ValueError("marker_identity")
                if identity is not None:
                    _check_native_marker_facts(marker, identity)
                seen_markers.add(marker_id)
        if seen_markers != set(gateway_markers):
            raise ValueError("orphan_marker")
        for marker in markers:
            if ("gateway_ref" in marker or marker["operation"] != "place"
                    or marker["exchange_name"] not in native_exchanges):
                continue
            exact, digests = _legacy_identity_candidates(marker)
            if exact & native_keys or digests & strong_keys:
                raise ValueError("legacy_native_identity_conflict")
        unresolved_sequences = set()
        active_sequences = {}
        for marker in state["active"].values():
            if marker["local_seq"] is not None:
                active_sequences.setdefault(marker["local_seq"], set()).add(marker["marker_id"])
        for entry in entries.values():
            seq = entry["local_seq"]
            if seq is not None and _unresolved(state, entry, markers_by_id):
                if seq in unresolved_sequences or active_sequences.get(seq, set()) - {entry["marker_id"]}:
                    raise ValueError("duplicate_local_seq")
                unresolved_sequences.add(seq)
        if state["version"] in (3, 4, 5, 6):
            max_cancels, attempts = gateway["max_cancel_entries"], gateway["cancel_attempts"]
            if (not is_strict_int(max_cancels, minimum=1) or max_cancels > _MAX_ENTRIES
                    or type(attempts) is not dict or len(attempts) > max_cancels):
                raise ValueError("cancel_capacity")
            for operation_id, attempt in attempts.items():
                if type(attempt) is not dict or set(attempt) != {"plan", "record"}:
                    raise ValueError("cancel_attempt")
                plan = _cancel_plan(attempt["plan"], binding, entries)
                if operation_id != plan.operation_id:
                    raise ValueError("cancel_operation")
                if attempt["record"] is not None:
                    record = _cancel_record(attempt["record"], binding, plan)
                    validate_gateway_cancel_record_progress(None, record)
        if state["version"] in (4, 5, 6):
            from .gateway_execution_state import validate_execution_state
            validate_execution_state(state, binding)
        if state["version"] in (5, 6):
            from .gateway_order_state import validate_order_state
            validate_order_state(state)
    except Exception as exc:
        if isinstance(exc, LiveStateCorrupt):
            raise
        raise LiveStateCorrupt(path, "gateway_invalid") from None


class GatewayPendingHost:
    """Seven-method SDK host port with process-safe single-file commits."""

    def __init__(self, strategy_dir: Any, strategy_uuid: str, binding: GatewayCommandBinding,
                 *, lock_timeout: float = 10.0) -> None:
        self._binding = GatewayCommandBinding(**_binding_mapping(binding))
        self._store = PendingCommandStore(strategy_dir, strategy_uuid, lock_timeout=lock_timeout)

    @classmethod
    def upgrade_for_gateway(cls, strategy_dir: Any, strategy_uuid: str,
                            binding: GatewayCommandBinding, *, max_entries: int = 10_000,
                            lock_timeout: float = 10.0) -> "GatewayPendingHost":
        if not is_strict_int(max_entries, minimum=1) or max_entries > _MAX_ENTRIES:
            raise ValueError("INVALID_GATEWAY_CAPACITY")
        host = cls(strategy_dir, strategy_uuid, binding, lock_timeout=lock_timeout)
        with host._store._lock():
            state = host._store._load()
            if state["version"] == 1:
                state["version"] = 2
                state["gateway"] = {"binding": _binding_mapping(binding),
                                    "max_entries": max_entries, "intents": {}}
                host._store._store(state, trim_history=False)
            else:
                host._check_state(state)
                if state["gateway"]["max_entries"] != max_entries:
                    raise ValueError("GATEWAY_CAPACITY_MISMATCH")
        return host

    @classmethod
    def upgrade_for_execution(cls, strategy_dir: Any, strategy_uuid: str,
                              binding: GatewayCommandBinding, *, consumer_ref: str,
                              max_events: int = 10_000, max_event_bytes: int = 32 * 1024 * 1024,
                              max_projection_bytes: int = 16 * 1024 * 1024,
                              lock_timeout: float = 10.0) -> "GatewayPendingHost":
        from .gateway_execution_state import upgrade_for_execution
        return upgrade_for_execution(cls, strategy_dir, strategy_uuid, binding,
            consumer_ref=consumer_ref, max_events=max_events, max_event_bytes=max_event_bytes,
            max_projection_bytes=max_projection_bytes, lock_timeout=lock_timeout)

    @classmethod
    def upgrade_for_order_state(cls, strategy_dir: Any, strategy_uuid: str,
                                binding: GatewayCommandBinding, *,
                                max_order_snapshot_bytes: int = 16 * 1024 * 1024,
                                lock_timeout: float = 10.0) -> "GatewayPendingHost":
        from .gateway_order_state import upgrade_for_order_state
        return upgrade_for_order_state(cls, strategy_dir, strategy_uuid, binding,
            max_order_snapshot_bytes=max_order_snapshot_bytes, lock_timeout=lock_timeout)

    def save_order_intent(self, intent: Any, *, local_seq: int, bt_ref: int, snapshot: dict) -> None:
        from .gateway_order_state import save_order_intent
        save_order_intent(self, intent, local_seq=local_seq, bt_ref=bt_ref, snapshot=snapshot)

    def upgrade_for_local_notifications(self):
        from .gateway_order_state import upgrade_for_local_notifications
        return upgrade_for_local_notifications(self)

    def save_submitted_order_intent(self, intent: Any, *, local_seq: int, bt_ref: int,
                                    snapshot: dict) -> None:
        from .gateway_order_state import save_order_intent
        save_order_intent(self, intent, local_seq=local_seq, bt_ref=bt_ref,
                          snapshot=snapshot, local_submitted=True)

    def local_order_notifications(self):
        from .gateway_order_state import local_notifications
        return local_notifications(self)

    def save_released_order_notification(self, request_key, *, bt_ref, snapshot):
        from .gateway_order_state import save_released_notification
        return save_released_notification(self, request_key, bt_ref=bt_ref, snapshot=snapshot)

    def save_rejected_order_notification(self, request_key, *, bt_ref, snapshot, code):
        from .gateway_order_state import save_rejected_notification
        return save_rejected_notification(self, request_key, bt_ref=bt_ref, snapshot=snapshot,
                                          code=code)

    def confirm_local_order_notifications(self, entries):
        from .gateway_order_state import confirm_local_notifications
        return confirm_local_notifications(self, entries)

    def load_order_snapshot(self, request_key: str):
        from .gateway_order_state import load_order_snapshot
        return load_order_snapshot(self, request_key)

    def iter_order_snapshots(self):
        from .gateway_order_state import iter_order_snapshots
        return iter_order_snapshots(self)

    def load_execution_checkpoint(self):
        from .gateway_execution_state import load_checkpoint
        return load_checkpoint(self)

    def ingest_execution_page(self, page, *, expected_revision: int, after_sequence: int):
        """Low-level port: after_sequence must come from this exact trusted read request."""
        from .gateway_execution_state import ingest_page
        return ingest_page(self, page, expected_revision=expected_revision, after_sequence=after_sequence)

    def ingest_execution_result(self, result, *, expected_revision: int):
        """Persist an SDK read result bound to its actual request, not a proof of authority."""
        from .gateway_execution_state import ingest_result
        return ingest_result(self, result, expected_revision=expected_revision)

    def read_execution_events(self, after_sequence=None, *, limit: int = 256):
        from .gateway_execution_state import read_events
        return read_events(self, after_sequence=after_sequence, limit=limit)

    def commit_execution_projection(self, through_sequence: int, projection, *,
                                    expected_revision: int, expected_applied_sequence: int):
        from .gateway_execution_state import commit_projection
        return commit_projection(self, through_sequence, projection, expected_revision=expected_revision,
                                 expected_applied_sequence=expected_applied_sequence)

    def commit_execution_notification_batch(self, through_sequence, projection, notifications, *,
                                            expected_revision, expected_applied_sequence):
        from .gateway_execution_state import commit_notification_batch
        return commit_notification_batch(self, through_sequence, projection, notifications,
                                         expected_revision=expected_revision,
                                         expected_applied_sequence=expected_applied_sequence)

    def load_execution_notification_batch(self):
        from .gateway_execution_state import load_notification_batch
        return load_notification_batch(self)

    def confirm_execution_notification_batch(self, batch_id, *, expected_revision,
                                             expected_applied_sequence, expected_projection_digest):
        from .gateway_execution_state import confirm_notification_batch
        return confirm_notification_batch(self, batch_id, expected_revision=expected_revision,
                                          expected_applied_sequence=expected_applied_sequence,
                                          expected_projection_digest=expected_projection_digest)

    def record_execution_ack(self, progress):
        from .gateway_execution_state import record_ack
        return record_ack(self, progress)

    def _check_state(self, state: dict) -> dict:
        if state["version"] not in (2, 3, 4, 5, 6) or _binding_from_mapping(state["gateway"]["binding"]) != self._binding:
            raise ValueError("GATEWAY_BINDING_MISMATCH")
        return state["gateway"]["intents"]

    @classmethod
    def upgrade_for_cancellation(cls, strategy_dir: Any, strategy_uuid: str,
                                 binding: GatewayCommandBinding, *, max_cancel_entries: int = 10_000,
                                 lock_timeout: float = 10.0) -> "GatewayPendingHost":
        """Explicitly extend a validated v2 file in place; never discard entries."""
        if not is_strict_int(max_cancel_entries, minimum=1) or max_cancel_entries > _MAX_ENTRIES:
            raise ValueError("INVALID_GATEWAY_CAPACITY")
        host = cls(strategy_dir, strategy_uuid, binding, lock_timeout=lock_timeout)
        with host._store._lock():
            state = host._store._load()
            host._check_state(state)
            if state["version"] == 2:
                state["version"] = 3
                state["gateway"]["max_cancel_entries"] = max_cancel_entries
                state["gateway"]["cancel_attempts"] = {}
                host._store._store(state, trim_history=False)
            elif state["gateway"]["max_cancel_entries"] != max_cancel_entries:
                raise ValueError("GATEWAY_CAPACITY_MISMATCH")
        return host

    def _cancel_attempts(self, state: dict) -> dict:
        self._check_state(state)
        if state["version"] not in (3, 4, 5, 6):
            raise ValueError("GATEWAY_CANCEL_UPGRADE_REQUIRED")
        return state["gateway"]["cancel_attempts"]

    def save_cancel_plan(self, plan: Any):
        mapping = gateway_cancel_plan_to_mapping(plan)
        with self._store._lock():
            state = self._store._load()
            attempts = self._cancel_attempts(state)
            canonical = _cancel_plan(mapping, self._binding, state["gateway"]["intents"])
            prior = attempts.get(canonical.operation_id)
            if prior is not None:
                return _cancel_plan(prior["plan"], self._binding, state["gateway"]["intents"])
            if len(attempts) >= state["gateway"]["max_cancel_entries"]:
                raise ValueError("GATEWAY_CANCEL_CAPACITY_EXCEEDED")
            attempts[canonical.operation_id] = {"plan": mapping, "record": None}
            self._store._store(state, trim_history=False)
            return canonical

    def load_cancel_plan(self, operation_id: str):
        with self._store._lock():
            state = self._store._load()
            attempt = self._cancel_attempts(state).get(operation_id)
            return None if attempt is None else _cancel_plan(
                attempt["plan"], self._binding, state["gateway"]["intents"]
            )

    def list_cancel_plans(self) -> tuple[GatewayCancelPlan, ...]:
        """Return a validated, operation-id-sorted snapshot without mutating state."""
        with self._store._lock():
            state = self._store._load()
            self._check_state(state)
            if state["version"] == 2:
                return ()
            attempts = self._cancel_attempts(state)
            entries = state["gateway"]["intents"]
            return tuple(
                _cancel_plan(attempts[operation_id]["plan"], self._binding, entries)
                for operation_id in sorted(attempts)
            )

    def save_cancel_record(self, operation_id: str, record: GatewayCancelRecord):
        if type(record) is not GatewayCancelRecord:
            raise ValueError("INVALID_CANCEL_RECORD")
        with self._store._lock():
            state = self._store._load()
            attempt = self._cancel_attempts(state).get(operation_id)
            if attempt is None:
                raise ValueError("GATEWAY_CANCEL_PLAN_REQUIRED")
            plan = _cancel_plan(attempt["plan"], self._binding, state["gateway"]["intents"])
            current = _cancel_record(record, self._binding, plan)
            previous = None if attempt["record"] is None else _cancel_record(
                attempt["record"], self._binding, plan
            )
            if previous is not None and current.version < previous.version:
                validate_gateway_cancel_record_progress(current, previous)
                return previous
            validate_gateway_cancel_record_progress(previous, current)
            mapping = current.to_mapping()
            if mapping != attempt["record"]:
                attempt["record"] = mapping
                self._store._store(state, trim_history=False)
            return current

    def load_cancel_record(self, operation_id: str):
        with self._store._lock():
            state = self._store._load()
            attempt = self._cancel_attempts(state).get(operation_id)
            if attempt is None or attempt["record"] is None:
                return None
            plan = _cancel_plan(attempt["plan"], self._binding, state["gateway"]["intents"])
            return _cancel_record(attempt["record"], self._binding, plan)

    def _entry(self, state: dict, request_key: str) -> dict:
        entry = self._check_state(state).get(request_key)
        if entry is None:
            raise ValueError("GATEWAY_INTENT_NOT_FOUND")
        return entry

    def _save_intent_in_state(self, state: dict, mapping: dict, canonical: Any,
                              local_seq: int | None, bt_ref: int | None) -> bool:
        entries = self._check_state(state)
        entry = entries.get(canonical.request_key)
        if entry is None:
            if len(entries) >= state["gateway"]["max_entries"]:
                raise ValueError("GATEWAY_CAPACITY_EXCEEDED")
            entry = {"intent": mapping, "record": None, "marker_id": None,
                     "release": None, "local_seq": local_seq, "bt_ref": bt_ref}
            entries[canonical.request_key] = entry
            changed = True
        else:
            old = entry["intent"]
            if {k: v for k, v in old.items() if k != "ttl_seconds"} != {
                k: v for k, v in mapping.items() if k != "ttl_seconds"
            }:
                raise ValueError("GATEWAY_INTENT_CONFLICT")
            changed = False
            for name, value in (("local_seq", local_seq), ("bt_ref", bt_ref)):
                if value is not None and entry[name] is not None and value != entry[name]:
                    raise ValueError("GATEWAY_FACT_CONFLICT")
                if value is not None and entry[name] is None:
                    entry[name] = value
                    marker = _marker_for(state, entry["marker_id"])
                    if marker is not None:
                        marker[name] = value
                    changed = True
        markers = _marker_index(state)
        if entry["local_seq"] is not None and _unresolved(state, entry, markers):
            seq = entry["local_seq"]
            if any(other is not entry and other["local_seq"] == seq and _unresolved(state, other, markers)
                   for other in entries.values()):
                raise ValueError("GATEWAY_LOCAL_SEQ_CONFLICT")
            if any(marker["local_seq"] == seq and marker["marker_id"] != entry["marker_id"]
                   for marker in state["active"].values()):
                raise ValueError("GATEWAY_LOCAL_SEQ_CONFLICT")
        return changed

    def save_intent(self, intent: Any, *, local_seq: int | None = None,
                    bt_ref: int | None = None) -> None:
        mapping = gateway_intent_to_mapping(intent)
        canonical = gateway_intent_from_mapping(mapping, expected_binding=self._binding)
        if not _positive_or_none(local_seq) or not _positive_or_none(bt_ref):
            raise ValueError("GATEWAY_FACT_INVALID")
        with self._store._lock():
            state = self._store._load()
            if self._save_intent_in_state(state, mapping, canonical, local_seq, bt_ref):
                self._store._store(state)

    def load_intent(self, request_key: str):
        with self._store._lock():
            entries = self._check_state(self._store._load())
            entry = entries.get(request_key)
            return None if entry is None else gateway_intent_from_mapping(entry["intent"], expected_binding=self._binding)

    def list_intents(self) -> tuple:
        with self._store._lock():
            entries = self._check_state(self._store._load())
            return tuple(gateway_intent_from_mapping(item["intent"], expected_binding=self._binding)
                         for item in entries.values())

    def load_context(self, request_key: str) -> GatewayPendingContext | None:
        with self._store._lock():
            entry = self._check_state(self._store._load()).get(request_key)
            if entry is None:
                return None
            return GatewayPendingContext(entry["marker_id"], entry["local_seq"], entry["bt_ref"])

    def load_record(self, request_key: str):
        with self._store._lock():
            entries = self._check_state(self._store._load())
            entry = entries.get(request_key)
            return None if entry is None or entry["record"] is None else _record(entry["record"], self._binding)

    def save_record(self, request_key: str, record: GatewayCommandRecord) -> None:
        current = _record(record, self._binding)
        with self._store._lock():
            state = self._store._load()
            entry = self._entry(state, request_key)
            intent = gateway_intent_from_mapping(entry["intent"], expected_binding=self._binding)
            previous = None if entry["record"] is None else _record(entry["record"], self._binding)
            if current.request_key != request_key or current.digest != intent.digest:
                raise ValueError("GATEWAY_RECORD_CONFLICT")
            validate_gateway_record_progress(previous, current)
            if (previous is not None and previous.native_identity is not None
                    and (current.native_identity is None
                         or not _json_equal(previous.native_identity.to_dict(),
                                            current.native_identity.to_dict()))):
                raise ValueError("GATEWAY_NATIVE_CONFLICT")
            if entry["release"] is not None and current.release_operation_id is not None:
                plan = gateway_release_from_mapping(entry["release"])
                if (plan.operation_id != current.release_operation_id
                        or plan.expected_version != current.release_expected_version):
                    raise ValueError("GATEWAY_RELEASE_CONFLICT")
            for other in self._check_state(state).values():
                if other is entry or other["record"] is None:
                    continue
                other_record = _record(other["record"], self._binding)
                if (set(current.strong_identity_key_digests) & set(other_record.strong_identity_key_digests)
                        or (current.native_identity is not None and other_record.native_identity is not None
                            and _json_equal(current.native_identity.to_dict(), other_record.native_identity.to_dict()))):
                    raise ValueError("GATEWAY_NATIVE_CONFLICT")
            marker = _marker_for(state, entry["marker_id"])
            if marker is not None and current.native_identity is not None:
                identity = current.native_identity
                new_fields = copy.deepcopy(dict(identity.fields))
                _check_native_marker_facts(marker, identity)
                for name, value in (("exchange_name", identity.exchange_name),
                                    ("client_order_id", identity.client_order_id),
                                    ("session_generation", identity.session_generation),
                                    ("native_identity", new_fields)):
                    if marker[name] not in (None, {}) and not _json_equal(marker[name], value):
                        raise ValueError("GATEWAY_NATIVE_CONFLICT")
                    marker[name] = value
                day = new_fields.get("trading_day")
                if day is not None:
                    if type(day) is not str or not day or (marker["trading_day"] is not None and marker["trading_day"] != day):
                        raise ValueError("GATEWAY_NATIVE_CONFLICT")
                    marker["trading_day"] = day
                for other in list(state["active"].values()) + state["history"]:
                    if other is not marker and other["operation"] == "place" and _identity_key(other) == _identity_key(marker):
                        raise ValueError("GATEWAY_NATIVE_CONFLICT")
            mapping = current.to_mapping()
            if entry["record"] != mapping:
                entry["record"] = mapping
                self._store._store(state)

    def commit_pre_dispatch(self, request_key: str, record: GatewayCommandRecord) -> str:
        current = _record(record, self._binding)
        with self._store._lock():
            state = self._store._load()
            entry = self._entry(state, request_key)
            if entry["record"] is None:
                raise ValueError("GATEWAY_RESERVATION_REQUIRED")
            previous = _record(entry["record"], self._binding)
            validate_gateway_record_progress(previous, current)
            if (current.request_key != request_key or current.state != "RESERVED"
                    or previous.state != "RESERVED" or current.version != previous.version):
                raise ValueError("GATEWAY_RESERVATION_REQUIRED")
            if entry["marker_id"] is not None:
                marker = state["active"].get(entry["marker_id"])
                if marker is None or marker["status"] != STATUS_PREPARED:
                    raise ValueError("GATEWAY_MARKER_NOT_PREPARED")
                return entry["marker_id"]
            intent = gateway_intent_from_mapping(entry["intent"], expected_binding=self._binding)
            payload = json.loads(intent.canonical_payload)
            now = utc_now_iso()
            marker_id = new_uuid4()
            marker = {"marker_id": marker_id, "status": STATUS_PREPARED, "operation": "place",
                      "host_scope": state["strategy_uuid"], "local_seq": entry["local_seq"],
                      "bt_ref": entry["bt_ref"], "exchange_name": None, "symbol": payload["symbol"],
                      "client_order_id": None, "native_identity": {}, "target_identity": None,
                      "request_summary": payload, "trading_day": None, "session_generation": None,
                      "created_at_utc": None, "committed_at_utc": now, "updated_at_utc": now,
                      "facts": {}, "transitions": [], "extra": {}, "resolution": None,
                      "gateway_ref": {"request_key": request_key}}
            state["active"][marker_id] = marker
            entry["marker_id"] = marker_id
            self._store._store(state)
            return marker_id

    def save_release(self, plan: Any) -> None:
        mapping = gateway_release_to_mapping(plan)
        plan = gateway_release_from_mapping(mapping)
        with self._store._lock():
            state = self._store._load()
            entry = self._entry(state, plan.request_key)
            intent = gateway_intent_from_mapping(entry["intent"], expected_binding=self._binding)
            record = None if entry["record"] is None else _record(entry["record"], self._binding)
            if record is None or plan.reservation_id != record.reservation_id or plan.digest != intent.digest:
                raise ValueError("GATEWAY_RELEASE_CONFLICT")
            if entry["release"] is not None:
                if entry["release"] != mapping:
                    raise ValueError("GATEWAY_RELEASE_CONFLICT")
                return
            if plan.expected_version != record.version:
                raise ValueError("GATEWAY_RELEASE_CONFLICT")
            entry["release"] = mapping
            self._store._store(state)

    def load_release(self, request_key: str):
        with self._store._lock():
            entry = self._check_state(self._store._load()).get(request_key)
            return None if entry is None or entry["release"] is None else gateway_release_from_mapping(entry["release"])
