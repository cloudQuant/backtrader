"""Pre-dispatch pending command markers (host side of the SDK commit port).

``state/pending.json`` holds ``{"version": 1, "strategy_uuid", "active":
{marker_id: marker}, "history": [marker, ...]}``.  A marker must be durable
*before* the SDK lets a provider send the native write (D62-14, 62.01 §3.2).

:meth:`PendingCommandStore.commit` implements
``bt_api_base.direct_write_protocol.PreDispatchCommitPort``: it accepts the
SDK ``PreDispatchRecord`` (anything with ``to_dict()``) or a plain mapping and
returns the new marker id only after the atomic write succeeded, else
``None``.  It never raises for I/O, lock or validation failures; ``None``
means "do not send".

Status model (rank order ``PREPARED < DISPATCHED < ACCEPTED < TERMINAL``):

* :meth:`mark` only moves forward in rank (``PREPARED`` may jump straight to
  ``ACCEPTED`` or ``TERMINAL`` because a venue return can arrive before the
  dispatching call returns, and a definitive "not sent" is terminal);
* any non-terminal marker may move to ``UNKNOWN``;
* ``UNKNOWN`` is sticky: only :meth:`resolve_manually` (audited, explicit
  operator conclusion) clears it, plus, for a ``settlement_confirm`` marker
  only, :meth:`resolve_settlement_readback` (audited, a verified read-only
  readback of the same route and trading day that found the settlement
  confirmed, or definitively unconfirmed, D62-29), and, for a ``place``
  marker only, :meth:`resolve_order_query` (audited, a complete order query
  of the same route and trading day matched by the marker's strong native
  identity: working -> ``ACCEPTED``, ended or absent -> ``TERMINAL``,
  D63-38 a).  There is no force-unlock.

A TERMINAL ``not_found_at_venue`` place marker carries a Rejected notice for
its strategy; :meth:`record_takeover` durably notes that it was taken over
(``facts.taken_over_at_utc``), so the host re-delivers it until then and never
twice.

``TERMINAL`` markers leave the active set and are kept in a bounded history
(last 500).  Duplicate detection of native identities therefore only covers
the active set plus that history.
"""

from __future__ import annotations

import copy
import hashlib
import os
import threading
from typing import Any, Iterable, List, Mapping, Optional, Union

from ._common import (
    StatePaths,
    ensure_no_secret_keys,
    get_logger,
    is_strict_int,
    is_text,
    is_uuid4,
    json_safe_copy,
    new_uuid4,
    scalar_mapping,
    strict_equal,
    utc_now_iso,
)
from .atomic import (
    LiveStateCorrupt,
    LiveStateError,
    LiveStateIdentityMismatch,
    LiveStateNotInitialized,
    atomic_write_json,
    read_json_bytes,
)
from .audit import append_audit

__all__ = (
    "ACTIVE_STATUSES",
    "BoundPreDispatchPort",
    "MANUAL_CONCLUSIONS",
    "OPERATIONS",
    "PENDING_VERSION",
    "PendingCommandStore",
    "STATUS_ACCEPTED",
    "STATUS_DISPATCHED",
    "STATUS_PREPARED",
    "STATUS_TERMINAL",
    "STATUS_UNKNOWN",
)

_log = get_logger(__name__)

PENDING_VERSION = 1
HISTORY_LIMIT = 500
_TRANSITIONS_LIMIT = 32

STATUS_PREPARED = "PREPARED"
STATUS_DISPATCHED = "DISPATCHED"
STATUS_ACCEPTED = "ACCEPTED"
STATUS_TERMINAL = "TERMINAL"
STATUS_UNKNOWN = "UNKNOWN"
STATUSES = frozenset(
    {STATUS_PREPARED, STATUS_DISPATCHED, STATUS_ACCEPTED, STATUS_TERMINAL, STATUS_UNKNOWN}
)
ACTIVE_STATUSES = frozenset({STATUS_PREPARED, STATUS_DISPATCHED, STATUS_ACCEPTED, STATUS_UNKNOWN})
_RANK = {STATUS_PREPARED: 0, STATUS_DISPATCHED: 1, STATUS_ACCEPTED: 2, STATUS_TERMINAL: 3}

OPERATIONS = frozenset({"place", "cancel", "settlement_confirm"})
MANUAL_CONCLUSIONS = frozenset(
    {"terminal_not_sent", "terminal_cancelled", "terminal_filled", "terminal_rejected"}
)
# Readback outcome -> evidence of :meth:`PendingCommandStore.resolve_settlement_readback`.
_READBACK_EVIDENCE = {
    "confirmed": "settlement_readback",
    "unconfirmed": "settlement_readback_unconfirmed",
}

# Facts that name an order and must not silently change once known.
_IMMUTABLE_FACT_KEYS = frozenset(
    {
        "client_order_id",
        "exchange_order_id",
        "order_sys_id",
        "exchange_id",
        "front_id",
        "session_id",
        "order_ref",
    }
)

_RECORD_KEYS = frozenset(
    {
        "operation",
        "host_scope",
        "exchange_name",
        "symbol",
        "identity",
        "target_identity",
        "request_summary",
        "trading_day",
        "session_generation",
        "created_at_utc",
        "local_seq",
        "bt_ref",
        "client_order_id",
        "native_identity",
    }
)
_SDK_IDENTITY_KEYS = frozenset({"exchange_name", "client_order_id", "fields", "session_generation"})

_MARKER_KEYS = frozenset(
    {
        "marker_id",
        "status",
        "operation",
        "host_scope",
        "local_seq",
        "bt_ref",
        "exchange_name",
        "symbol",
        "client_order_id",
        "native_identity",
        "target_identity",
        "request_summary",
        "trading_day",
        "session_generation",
        "created_at_utc",
        "committed_at_utc",
        "updated_at_utc",
        "facts",
        "transitions",
        "extra",
        "resolution",
    }
)


def initial_pending_state(strategy_uuid: str) -> dict:
    return {
        "version": PENDING_VERSION,
        "strategy_uuid": strategy_uuid,
        "active": {},
        "history": [],
    }


def _invalid(detail: str) -> LiveStateError:
    return LiveStateError("pending_record_invalid", detail)


def _check_marker(marker: Any, path: str, *, terminal: bool, gateway: bool = False) -> None:
    keys = _MARKER_KEYS | ({"gateway_ref"} if gateway else set())
    if not isinstance(marker, dict) or set(marker) != keys:
        raise LiveStateCorrupt(path, "invalid_marker")
    if not is_uuid4(marker["marker_id"]):
        raise LiveStateCorrupt(path, "invalid_marker_id")
    status = marker["status"]
    if terminal and status != STATUS_TERMINAL:
        raise LiveStateCorrupt(path, "history_not_terminal")
    if not terminal and status not in ACTIVE_STATUSES:
        raise LiveStateCorrupt(path, "active_status_invalid")
    if marker["operation"] not in OPERATIONS:
        raise LiveStateCorrupt(path, "invalid_operation")
    if not is_uuid4(marker["host_scope"]):
        raise LiveStateCorrupt(path, "invalid_host_scope")
    if any(value is not None and not is_strict_int(value, minimum=1)
           for value in (marker["local_seq"], marker["bt_ref"])):
        raise LiveStateCorrupt(path, "invalid_local_facts")
    if marker["operation"] in ("place", "cancel") and not is_text(marker["symbol"], max_len=128):
        raise LiveStateCorrupt(path, "invalid_symbol")
    if not gateway and not is_text(marker["exchange_name"], max_len=128):
        raise LiveStateCorrupt(path, "invalid_exchange")
    for key in ("native_identity", "request_summary", "facts", "extra"):
        if not isinstance(marker[key], dict):
            raise LiveStateCorrupt(path, f"invalid_field:{key}")
    if not isinstance(marker["transitions"], list):
        raise LiveStateCorrupt(path, "invalid_field:transitions")
    if (not gateway and marker["operation"] == "place"
            and marker["client_order_id"] is None and not marker["native_identity"]):
        raise LiveStateCorrupt(path, "invalid_identity")


def validate_pending_state(raw: Any, path: str, strategy_uuid: Optional[str]) -> dict:
    if not isinstance(raw, dict):
        raise LiveStateCorrupt(path, "not_a_mapping")
    version = raw.get("version")
    if type(version) is not int or version not in (1, 2, 3, 4, 5, 6):
        raise LiveStateCorrupt(path, "version_unsupported")
    keys = {"version", "strategy_uuid", "active", "history"}
    if version in (2, 3, 4, 5, 6):
        keys.add("gateway")
    if set(raw) != keys:
        raise LiveStateCorrupt(path, "unexpected_keys")
    if not is_uuid4(raw["strategy_uuid"]):
        raise LiveStateCorrupt(path, "invalid_field:strategy_uuid")
    if not isinstance(raw["active"], dict) or not isinstance(raw["history"], list):
        raise LiveStateCorrupt(path, "invalid_structure")
    seen_marker_ids = set()
    for marker_id, marker in raw["active"].items():
        _check_marker(marker, path, terminal=False, gateway=version in (2, 3, 4, 5, 6) and isinstance(marker, dict) and "gateway_ref" in marker)
        if marker["marker_id"] != marker_id or marker["host_scope"] != raw["strategy_uuid"]:
            raise LiveStateCorrupt(path, "marker_key_mismatch")
        seen_marker_ids.add(marker_id)
    for marker in raw["history"]:
        _check_marker(marker, path, terminal=True, gateway=version in (2, 3, 4, 5, 6) and isinstance(marker, dict) and "gateway_ref" in marker)
        if marker["marker_id"] in seen_marker_ids or marker["host_scope"] != raw["strategy_uuid"]:
            raise LiveStateCorrupt(path, "marker_key_mismatch")
        seen_marker_ids.add(marker["marker_id"])
    if strategy_uuid is not None and raw["strategy_uuid"] != strategy_uuid:
        raise LiveStateIdentityMismatch("strategy_uuid_mismatch", "pending.json")
    if version in (2, 3, 4, 5, 6):
        from .gateway_pending import validate_gateway_state
        validate_gateway_state(raw, path)
    return raw


# (realpath, strategy uuid) -> sha256 of the last pending.json bytes that passed
# validate_pending_state in this process (see PendingStore._load).
_VALIDATED_DIGESTS: dict = {}
_VALIDATED_LOCK = threading.Lock()


def is_pristine_pending(raw: Any, path: str) -> bool:
    try:
        state = validate_pending_state(raw, path, None)
    except LiveStateError:
        return False
    # A v2 binding itself is durable state, even before its first intent.
    return state["version"] == 1 and not state["active"] and not state["history"]


def _enum_text(value: Any) -> Any:
    inner = getattr(value, "value", None)
    if type(value) is not str and type(inner) is str and hasattr(type(value), "__members__"):
        return inner
    return value


def _optional_positive_int(value: Any, name: str) -> Optional[int]:
    if value is None:
        return None
    if not is_strict_int(value, minimum=1):
        raise _invalid(name)
    return value


def _normalize_sdk_identity(value: Any, name: str) -> dict:
    if not isinstance(value, Mapping) or not set(value) <= _SDK_IDENTITY_KEYS:
        raise _invalid(name)
    client = value.get("client_order_id")
    if client is not None and not is_text(client, max_len=256):
        raise _invalid(f"{name}.client_order_id")
    exchange = value.get("exchange_name")
    if exchange is not None and not is_text(exchange, max_len=128):
        raise _invalid(f"{name}.exchange_name")
    generation = value.get("session_generation")
    if generation is not None and not is_strict_int(generation, minimum=0):
        raise _invalid(f"{name}.session_generation")
    return {
        "exchange_name": exchange,
        "client_order_id": client,
        "fields": scalar_mapping(value.get("fields"), f"{name}.fields"),
        "session_generation": generation,
    }


def normalize_record(
    record: Any,
    strategy_uuid: str,
    *,
    local_seq: Optional[int] = None,
    bt_ref: Optional[int] = None,
) -> dict:
    """Validate a commit record and return the canonical marker (status PREPARED).

    Accepts the SDK ``PreDispatchRecord`` (via ``to_dict()``: nested
    ``identity``/``target_identity`` with ``fields``) or the flat mapping shape
    (``client_order_id`` + ``native_identity``).  Raises
    :class:`LiveStateError` on anything invalid or ambiguous.
    """
    to_dict = getattr(record, "to_dict", None)
    if callable(to_dict):
        raw = to_dict()
    else:
        raw = record
    if not isinstance(raw, Mapping):
        raise _invalid("record_type")
    raw = dict(raw)

    operation = _enum_text(raw.get("operation"))
    if operation not in OPERATIONS:
        raise _invalid("operation")
    if raw.get("host_scope") != strategy_uuid:
        raise LiveStateError("pending_scope_mismatch")
    exchange_name = raw.get("exchange_name")
    if not is_text(exchange_name, max_len=128):
        raise _invalid("exchange_name")
    symbol = raw.get("symbol")
    if symbol is not None and not is_text(symbol, max_len=128):
        raise _invalid("symbol")
    if operation in ("place", "cancel") and symbol is None:
        raise _invalid("symbol_required")

    session_generation = raw.get("session_generation")
    if session_generation is not None and not is_strict_int(session_generation, minimum=0):
        raise _invalid("session_generation")

    client_order_id = raw.get("client_order_id")
    if client_order_id is not None and not is_text(client_order_id, max_len=256):
        raise _invalid("client_order_id")
    native_identity = scalar_mapping(raw.get("native_identity"), "native_identity")
    sdk_identity = raw.get("identity")
    if sdk_identity is not None:
        ident = _normalize_sdk_identity(sdk_identity, "identity")
        if ident["exchange_name"] is not None and ident["exchange_name"] != exchange_name:
            raise _invalid("identity_exchange_mismatch")
        if client_order_id is not None and ident["client_order_id"] != client_order_id:
            raise _invalid("identity_client_order_id_conflict")
        if "native_identity" in raw and native_identity != ident["fields"]:
            raise _invalid("identity_fields_conflict")
        generation = ident["session_generation"]
        if generation is not None:
            if session_generation is not None and generation != session_generation:
                raise _invalid("identity_session_generation_conflict")
            session_generation = generation
        client_order_id = ident["client_order_id"]
        native_identity = ident["fields"]
    if "client_order_id" in native_identity:
        if client_order_id is not None and not strict_equal(
            native_identity["client_order_id"], client_order_id
        ):
            raise _invalid("native_identity_client_order_id_conflict")
        native_identity.pop("client_order_id")

    target = raw.get("target_identity")
    if target is not None:
        if not isinstance(target, Mapping) or not target:
            raise _invalid("target_identity")
        if "fields" in target:
            target = _normalize_sdk_identity(target, "target_identity")
            if not target["fields"] and target["client_order_id"] is None:
                raise _invalid("target_identity_empty")
        else:
            target = scalar_mapping(target, "target_identity")

    if operation == "place" and client_order_id is None and not native_identity:
        raise _invalid("identity_required")
    if operation == "cancel" and target is None:
        raise _invalid("target_identity_required")

    seq_value = _optional_positive_int(raw.get("local_seq"), "local_seq")
    ref_value = _optional_positive_int(raw.get("bt_ref"), "bt_ref")
    bound_seq = _optional_positive_int(local_seq, "local_seq")
    bound_ref = _optional_positive_int(bt_ref, "bt_ref")
    if bound_seq is not None:
        if seq_value is not None and seq_value != bound_seq:
            raise _invalid("local_seq_conflict")
        seq_value = bound_seq
    if bound_ref is not None:
        if ref_value is not None and ref_value != bound_ref:
            raise _invalid("bt_ref_conflict")
        ref_value = bound_ref

    summary = raw.get("request_summary")
    summary = {} if summary is None else json_safe_copy(summary, "request_summary")
    if not isinstance(summary, dict):
        raise _invalid("request_summary")
    trading_day = raw.get("trading_day")
    if trading_day is not None and not is_text(trading_day, max_len=32):
        raise _invalid("trading_day")
    created_at = raw.get("created_at_utc")
    if created_at is not None and not is_text(created_at, max_len=64):
        raise _invalid("created_at_utc")
    extra = {key: value for key, value in raw.items() if key not in _RECORD_KEYS}
    extra = json_safe_copy(extra, "extra")

    now = utc_now_iso()
    marker = {
        "marker_id": new_uuid4(),
        "status": STATUS_PREPARED,
        "operation": operation,
        "host_scope": strategy_uuid,
        "local_seq": seq_value,
        "bt_ref": ref_value,
        "exchange_name": exchange_name,
        "symbol": symbol,
        "client_order_id": client_order_id,
        "native_identity": native_identity,
        "target_identity": json_safe_copy(target, "target_identity"),
        "request_summary": summary,
        "trading_day": trading_day,
        "session_generation": session_generation,
        "created_at_utc": created_at,
        "committed_at_utc": now,
        "updated_at_utc": now,
        "facts": {},
        "transitions": [],
        "extra": extra,
        "resolution": None,
    }
    ensure_no_secret_keys(marker, "pending")
    return marker


def _identity_key(marker: Mapping[str, Any]):
    native = marker["native_identity"]
    items = tuple(sorted((key, type(value).__name__, value) for key, value in native.items()))
    return (marker["exchange_name"], marker["client_order_id"], items)


def _identity_view(marker: Mapping[str, Any]) -> dict:
    view = {}
    for key, value in marker["facts"].items():
        if value is None or type(value) in (str, int, bool, float):
            view[key] = value
    view.update(marker["native_identity"])
    if marker["client_order_id"] is not None:
        view["client_order_id"] = marker["client_order_id"]
    view["exchange_name"] = marker["exchange_name"]
    return view


def _transition_allowed(current: str, new: str) -> bool:
    if current == STATUS_UNKNOWN:
        return new == STATUS_UNKNOWN
    if new == STATUS_UNKNOWN or new == current:
        return current in ACTIVE_STATUSES
    return _RANK[new] > _RANK[current]


def _merge_facts(marker: dict, facts: Mapping[str, Any]) -> bool:
    known = marker["facts"]
    native = marker["native_identity"]
    for key, value in facts.items():
        if key in native and not strict_equal(native[key], value):
            return False
        if key == "client_order_id" and marker["client_order_id"] is not None:
            if not strict_equal(marker["client_order_id"], value):
                return False
        if key in _IMMUTABLE_FACT_KEYS and known.get(key) is not None:
            if not strict_equal(known[key], value):
                return False
    known.update(facts)
    return True


def _clean_facts(facts: Mapping[str, Any]) -> dict:
    cleaned = json_safe_copy(dict(facts), "facts")
    ensure_no_secret_keys(cleaned, "facts")
    return cleaned


def _normalize_evidence(evidence: Any) -> List[str]:
    if type(evidence) is str:
        items = [evidence]
    elif isinstance(evidence, (list, tuple)):
        items = list(evidence)
    else:
        raise LiveStateError("evidence_required")
    if not items or len(items) > 50:
        raise LiveStateError("evidence_required")
    for item in items:
        if not is_text(item, max_len=2000):
            raise LiveStateError("evidence_required")
    return items


class PendingCommandStore:
    """Durable pre-dispatch markers of one strategy instance.

    Every operation re-reads ``state/pending.json`` under
    ``state/pending.lock``; nothing is cached, so several stores (threads or
    processes) on the same directory stay consistent.
    """

    def __init__(
        self,
        strategy_dir: Any,
        strategy_uuid: str,
        *,
        lock_timeout: float = 10.0,
        history_limit: int = HISTORY_LIMIT,
    ) -> None:
        if not is_uuid4(strategy_uuid):
            raise LiveStateError("invalid_strategy_uuid")
        if not is_strict_int(history_limit, minimum=1):
            raise ValueError("history_limit must be a positive int")
        self.paths = StatePaths(strategy_dir)
        self.strategy_uuid = strategy_uuid
        self.lock_timeout = lock_timeout
        self.history_limit = history_limit
        #: Marker id of the last successful :meth:`commit` through this object
        #: (not thread-safe; prefer the return value).
        self.last_marker_id: Optional[str] = None

    @property
    def path(self) -> str:
        return self.paths.pending

    def _lock(self):
        from .coordination import CoordinatedFileLock

        return CoordinatedFileLock(self.paths, self.paths.pending_lock, timeout=self.lock_timeout)

    def _load(self) -> dict:
        """Read and validate the pending state; return a fresh parsed object.

        Validation is a pure function of the file bytes, its path and the
        strategy uuid, but on a large Gateway state it costs ~0.1 s and the
        broker reads the state several times per bar (SimNow 63.09: a 0.5 MB
        state made one bar take seconds and every feed stale). The bytes are
        always re-read; only bytes identical to the last validated content of
        this path skip re-validation, so any change is fully validated.
        """
        try:
            content, raw = read_json_bytes(self.paths.pending)
        except FileNotFoundError:
            raise LiveStateNotInitialized(self.paths.pending) from None
        key = (os.path.realpath(self.paths.pending), self.strategy_uuid)
        digest = hashlib.sha256(content).digest()
        with _VALIDATED_LOCK:
            if _VALIDATED_DIGESTS.get(key) == digest:
                return raw
        state = validate_pending_state(raw, self.paths.pending, self.strategy_uuid)
        with _VALIDATED_LOCK:
            _VALIDATED_DIGESTS[key] = digest
        return state

    def _store(self, state: dict, *, trim_history: bool = True) -> None:
        if not trim_history:
            pass
        elif state["version"] == 1:
            overflow = len(state["history"]) - self.history_limit
            if overflow > 0:
                del state["history"][:overflow]
        else:
            old = [m for m in state["history"] if "gateway_ref" not in m]
            remove = {id(m) for m in old[:-self.history_limit]}
            state["history"][:] = [m for m in state["history"] if id(m) not in remove]
        if state["version"] in (2, 3, 4, 5, 6):
            # All writers, including the legacy mutation API, share the same
            # cross-reference contract before the atomic replacement.
            validate_pending_state(state, self.paths.pending, self.strategy_uuid)
        atomic_write_json(self.paths.pending, state)

    # -- commit port -------------------------------------------------------

    def commit(
        self, record: Any, *, local_seq: Optional[int] = None, bt_ref: Optional[int] = None
    ) -> Optional[str]:
        """Durably store ``record`` as a PREPARED marker; return its id or ``None``.

        ``None`` (never an exception) for invalid records, scope mismatch,
        duplicate native identity, duplicate in-flight ``local_seq``, lock
        timeout, corruption or I/O failure.  ``local_seq``/``bt_ref`` add the
        BT host facts the SDK record does not carry; they must agree with any
        value inside the record.
        """
        try:
            marker = normalize_record(
                record, self.strategy_uuid, local_seq=local_seq, bt_ref=bt_ref
            )
            with self._lock():
                state = self._load()
                self._reject_duplicates(state, marker)
                state["active"][marker["marker_id"]] = marker
                self._store(state)
        except Exception as exc:
            code = getattr(exc, "code", type(exc).__name__)
            _log.warning("pending marker commit refused: %s", code)
            return None
        self.last_marker_id = marker["marker_id"]
        return marker["marker_id"]

    def bind(
        self, *, local_seq: Optional[int] = None, bt_ref: Optional[int] = None
    ) -> "BoundPreDispatchPort":
        """Return a ``PreDispatchCommitPort`` that adds ``local_seq``/``bt_ref``."""
        return BoundPreDispatchPort(self, local_seq=local_seq, bt_ref=bt_ref)

    def _reject_duplicates(self, state: dict, marker: dict) -> None:
        if marker["operation"] != "place":
            return
        key = _identity_key(marker)
        for other in list(state["active"].values()) + state["history"]:
            if other["operation"] == "place" and _identity_key(other) == key:
                raise LiveStateError("pending_duplicate_identity")
        if marker["local_seq"] is not None:
            for other in state["active"].values():
                if other["operation"] == "place" and other["local_seq"] == marker["local_seq"]:
                    raise LiveStateError("pending_duplicate_local_seq")
            if state["version"] in (2, 3, 4, 5, 6):
                from .gateway_pending import has_active_gateway_sequence
                if has_active_gateway_sequence(state, marker["local_seq"]):
                    raise LiveStateError("pending_duplicate_local_seq")

    # -- status ------------------------------------------------------------

    def mark(self, marker_id: str, status: str, **facts: Any) -> bool:
        """Move an active marker to ``status`` and merge ``facts``.

        Returns ``False`` (never raises) for unknown markers, illegal
        transitions, conflicting immutable identity facts, invalid facts,
        lock timeout or I/O failure.  Re-marking the same non-terminal status
        only merges facts.
        """
        if status not in STATUSES:
            return False
        try:
            cleaned = _clean_facts(facts)
            with self._lock():
                state = self._load()
                marker = state["active"].get(marker_id)
                if marker is None:
                    return False
                current = marker["status"]
                if not _transition_allowed(current, status):
                    return False
                if not _merge_facts(marker, cleaned):
                    return False
                now = utc_now_iso()
                if current != status:
                    marker["transitions"].append({"from": current, "to": status, "at_utc": now})
                    del marker["transitions"][:-_TRANSITIONS_LIMIT]
                    marker["status"] = status
                marker["updated_at_utc"] = now
                if status == STATUS_TERMINAL:
                    del state["active"][marker_id]
                    state["history"].append(marker)
                self._store(state)
            return True
        except Exception as exc:
            _log.warning("pending marker mark failed: %s", getattr(exc, "code", type(exc).__name__))
            return False

    def attach(self, marker_id: str, **facts: Any) -> bool:
        """Merge ``facts`` (for example an exchange order id) without a status change.

        Identity facts (``exchange_order_id``, ``order_sys_id`` ...) and
        native identity fields cannot be changed once set; a conflicting value
        returns ``False``.  Never raises.
        """
        if not facts:
            return False
        try:
            cleaned = _clean_facts(facts)
            with self._lock():
                state = self._load()
                marker = state["active"].get(marker_id)
                if marker is None or not _merge_facts(marker, cleaned):
                    return False
                marker["updated_at_utc"] = utc_now_iso()
                self._store(state)
            return True
        except Exception as exc:
            _log.warning(
                "pending marker attach failed: %s", getattr(exc, "code", type(exc).__name__)
            )
            return False

    # -- queries -----------------------------------------------------------

    def get(self, marker_id: str) -> Optional[dict]:
        state = self._load()
        marker = state["active"].get(marker_id)
        if marker is not None:
            return copy.deepcopy(marker)
        for item in reversed(state["history"]):
            if item["marker_id"] == marker_id:
                return copy.deepcopy(item)
        return None

    def active(self) -> List[dict]:
        """Non-terminal markers (PREPARED, DISPATCHED, ACCEPTED, UNKNOWN), oldest first."""
        markers = self._load()["active"].values()
        return [copy.deepcopy(m) for m in sorted(markers, key=lambda m: m["committed_at_utc"])]

    def unknown(self) -> List[dict]:
        return [m for m in self.active() if m["status"] == STATUS_UNKNOWN]

    def history(self) -> List[dict]:
        return copy.deepcopy(self._load()["history"])

    def find_by_identity(
        self, native_identity: Mapping[str, Any], *, include_history: bool = False
    ) -> List[dict]:
        """Markers whose identity contains every ``native_identity`` item.

        The identity of a marker is its ``native_identity`` fields plus
        ``client_order_id``, ``exchange_name`` and scalar attached facts.
        Comparison is type-strict (``"1" != 1``).  An empty or non-scalar
        query raises ``LiveStateError("identity_query_invalid")``.
        """
        try:
            query = scalar_mapping(native_identity, "query")
        except LiveStateError:
            raise LiveStateError("identity_query_invalid") from None
        if not query:
            raise LiveStateError("identity_query_invalid")
        state = self._load()
        candidates: Iterable[dict] = list(state["active"].values())
        if include_history:
            candidates = list(candidates) + list(state["history"])
        out = []
        for marker in candidates:
            view = _identity_view(marker)
            if all(key in view and strict_equal(view[key], value) for key, value in query.items()):
                out.append(copy.deepcopy(marker))
        return out

    # -- manual resolution -------------------------------------------------

    def resolve_manually(
        self,
        marker_id: str,
        *,
        operator: str,
        conclusion: str,
        evidence: Union[str, List[str]],
    ) -> dict:
        """Clear one UNKNOWN marker with an explicit, audited operator conclusion.

        Only UNKNOWN markers can be resolved; ``conclusion`` must be one of
        :data:`MANUAL_CONCLUSIONS`; ``evidence`` is one or more non-empty
        references (not raw data).  The audit record is written first; if it
        cannot be written nothing changes.  Returns the resolved marker.
        """
        if not is_text(operator, max_len=200):
            raise LiveStateError("operator_required")
        if conclusion not in MANUAL_CONCLUSIONS:
            raise LiveStateError("invalid_conclusion")
        evidence_items = _normalize_evidence(evidence)
        with self._lock():
            state = self._load()
            marker = state["active"].get(marker_id)
            if marker is None:
                raise LiveStateError("marker_not_found")
            if marker["status"] != STATUS_UNKNOWN:
                raise LiveStateError("marker_not_unknown", marker["status"])
            audit_record = {
                "event": "pending_manual_resolution",
                "strategy_uuid": self.strategy_uuid,
                "marker_id": marker_id,
                "previous_status": STATUS_UNKNOWN,
                "operator": operator,
                "conclusion": conclusion,
                "evidence": evidence_items,
                "operation": marker["operation"],
                "exchange_name": marker["exchange_name"],
                "symbol": marker["symbol"],
                "local_seq": marker["local_seq"],
                "bt_ref": marker["bt_ref"],
                "client_order_id": marker["client_order_id"],
                "native_identity": marker["native_identity"],
            }
            entry = append_audit(self.paths.strategy_dir, audit_record)
            now = utc_now_iso()
            marker["status"] = STATUS_TERMINAL
            marker["transitions"].append(
                {"from": STATUS_UNKNOWN, "to": STATUS_TERMINAL, "at_utc": now}
            )
            del marker["transitions"][:-_TRANSITIONS_LIMIT]
            marker["updated_at_utc"] = now
            marker["resolution"] = {
                "kind": "manual",
                "operator": operator,
                "conclusion": conclusion,
                "evidence": evidence_items,
                "resolved_at_utc": entry["ts_utc"],
            }
            del state["active"][marker_id]
            state["history"].append(marker)
            try:
                self._store(state)
            except BaseException:
                try:
                    append_audit(
                        self.paths.strategy_dir,
                        {
                            "event": "pending_manual_resolution_failed",
                            "strategy_uuid": self.strategy_uuid,
                            "marker_id": marker_id,
                            "operator": operator,
                        },
                    )
                except Exception:
                    _log.warning("could not audit failed manual resolution")
                raise
            return copy.deepcopy(marker)

    def resolve_settlement_readback(
        self,
        marker_id: str,
        *,
        exchange_name: str,
        trading_day: str,
        session_generation: Optional[int] = None,
        outcome: str = "confirmed",
    ) -> bool:
        """Close one UNKNOWN ``settlement_confirm`` marker proven by a readback (D62-29).

        The host read the venue's settlement state read-only, on a verified
        session of the bound account, and found ``exchange_name``'s
        settlement of ``trading_day`` ``outcome``: ``"confirmed"`` (the
        confirmation took effect; evidence ``settlement_readback``) or a
        complete, definitive ``"unconfirmed"`` (it did not take effect;
        evidence ``settlement_readback_unconfirmed``, after which the host may
        confirm again under admission).  Only a marker with that operation,
        status, route and trading day qualifies; any other marker (orders,
        cancels, other days) still needs :meth:`resolve_manually`.  The audit
        record is written first.  Returns ``False`` (never raises) when
        nothing matches or anything cannot be written; the marker then stays
        UNKNOWN.
        """
        if not is_text(exchange_name, max_len=128) or not is_text(trading_day, max_len=32):
            return False
        if session_generation is not None and not is_strict_int(session_generation, minimum=0):
            return False
        evidence = _READBACK_EVIDENCE.get(outcome) if type(outcome) is str else None
        if evidence is None:
            return False
        try:
            with self._lock():
                state = self._load()
                marker = state["active"].get(marker_id)
                if (
                    marker is None
                    or marker["status"] != STATUS_UNKNOWN
                    or marker["operation"] != "settlement_confirm"
                    or marker["exchange_name"] != exchange_name
                    or marker["trading_day"] != trading_day
                ):
                    return False
                entry = append_audit(
                    self.paths.strategy_dir,
                    {
                        "event": "pending_settlement_readback_resolution",
                        "strategy_uuid": self.strategy_uuid,
                        "marker_id": marker_id,
                        "previous_status": STATUS_UNKNOWN,
                        "operation": marker["operation"],
                        "exchange_name": exchange_name,
                        "trading_day": trading_day,
                        "session_generation": session_generation,
                        "outcome": outcome,
                        "evidence": evidence,
                    },
                )
                now = utc_now_iso()
                marker["status"] = STATUS_TERMINAL
                marker["transitions"].append(
                    {"from": STATUS_UNKNOWN, "to": STATUS_TERMINAL, "at_utc": now}
                )
                del marker["transitions"][:-_TRANSITIONS_LIMIT]
                marker["updated_at_utc"] = now
                marker["facts"].update(final_status=outcome, resolution_evidence=evidence)
                marker["resolution"] = {
                    "kind": evidence,
                    "evidence": [evidence],
                    "trading_day": trading_day,
                    "session_generation": session_generation,
                    "resolved_at_utc": entry["ts_utc"],
                }
                del state["active"][marker_id]
                state["history"].append(marker)
                try:
                    self._store(state)
                except BaseException:
                    try:
                        append_audit(
                            self.paths.strategy_dir,
                            {
                                "event": "pending_settlement_readback_resolution_failed",
                                "strategy_uuid": self.strategy_uuid,
                                "marker_id": marker_id,
                            },
                        )
                    except Exception:
                        _log.warning("could not audit failed settlement readback resolution")
                    raise
            return True
        except Exception as exc:
            _log.warning(
                "settlement readback resolution failed: %s",
                getattr(exc, "code", type(exc).__name__),
            )
            return False

    def resolve_order_query(
        self,
        marker_id: str,
        *,
        exchange_name: str,
        trading_day: str,
        status: str,
        evidence: str,
        **facts: Any,
    ) -> bool:
        """Resolve one UNKNOWN ``place`` marker from a complete same-day order query.

        D63-38 a (user decision 2026-11-07): the host read the complete order
        list of the marker's own route and trading day and matched the
        marker's strong native identity; the host decides those
        preconditions.  ``status`` is ``ACCEPTED`` (the order is working; it
        stays active and later returns end it) or ``TERMINAL`` with a
        ``final_status`` fact (its end state, or ``not_found_at_venue``).
        Only an UNKNOWN place marker of ``exchange_name`` whose trading day
        (native identity, else the marker's) equals ``trading_day`` qualifies;
        anything else still needs :meth:`resolve_manually`.  The audit record
        is written first.  Returns ``False`` (never raises) when nothing
        matches, a fact conflicts with the marker's identity, or anything
        cannot be written; the marker then stays UNKNOWN.
        """
        if status not in (STATUS_ACCEPTED, STATUS_TERMINAL):
            return False
        if not is_text(exchange_name, max_len=128) or not is_text(trading_day, max_len=32):
            return False
        if not is_text(evidence, max_len=200):
            return False
        final_status = facts.get("final_status")
        if status == STATUS_TERMINAL and not is_text(final_status, max_len=128):
            return False
        try:
            cleaned = _clean_facts(
                {key: value for key, value in facts.items() if value is not None}
            )
            cleaned["resolution_evidence"] = evidence
            with self._lock():
                state = self._load()
                marker = state["active"].get(marker_id)
                if (
                    marker is None
                    or marker["status"] != STATUS_UNKNOWN
                    or marker["operation"] != "place"
                    or marker["exchange_name"] != exchange_name
                    or (marker["native_identity"].get("trading_day") or marker["trading_day"])
                    != trading_day
                ):
                    return False
                if not _merge_facts(marker, cleaned):
                    return False
                entry = append_audit(
                    self.paths.strategy_dir,
                    {
                        "event": "pending_order_query_resolution",
                        "strategy_uuid": self.strategy_uuid,
                        "marker_id": marker_id,
                        "previous_status": STATUS_UNKNOWN,
                        "status": status,
                        "final_status": final_status,
                        "evidence": evidence,
                        "exchange_name": exchange_name,
                        "trading_day": trading_day,
                        "symbol": marker["symbol"],
                        "local_seq": marker["local_seq"],
                        "bt_ref": marker["bt_ref"],
                    },
                )
                now = utc_now_iso()
                marker["status"] = status
                marker["transitions"].append({"from": STATUS_UNKNOWN, "to": status, "at_utc": now})
                del marker["transitions"][:-_TRANSITIONS_LIMIT]
                marker["updated_at_utc"] = now
                marker["resolution"] = {
                    "kind": "complete_order_query",
                    "evidence": [evidence],
                    "trading_day": trading_day,
                    "resolved_at_utc": entry["ts_utc"],
                }
                if status == STATUS_TERMINAL:
                    del state["active"][marker_id]
                    state["history"].append(marker)
                try:
                    self._store(state)
                except BaseException:
                    try:
                        append_audit(
                            self.paths.strategy_dir,
                            {
                                "event": "pending_order_query_resolution_failed",
                                "strategy_uuid": self.strategy_uuid,
                                "marker_id": marker_id,
                            },
                        )
                    except Exception:
                        _log.warning("could not audit failed order query resolution")
                    raise
            return True
        except Exception as exc:
            _log.warning(
                "order query resolution failed: %s", getattr(exc, "code", type(exc).__name__)
            )
            return False

    def record_takeover(self, marker_id: str) -> bool:
        """Durably note that the strategy took over the Rejected notice of a marker.

        Only a TERMINAL ``place`` marker resolved ``not_found_at_venue`` has
        such a notice (D63-38 a): the host re-delivers it on every restart
        until this fact (``facts.taken_over_at_utc``) exists.  The first
        time is kept (idempotent ``True``).  Returns ``False`` (never raises)
        for any other marker or when the fact cannot be written.
        """
        try:
            with self._lock():
                state = self._load()
                marker = next(
                    (item for item in reversed(state["history"]) if item["marker_id"] == marker_id),
                    None,
                )
                if (
                    marker is None
                    or marker["operation"] != "place"
                    or marker["facts"].get("final_status") != "not_found_at_venue"
                ):
                    return False
                if marker["facts"].get("taken_over_at_utc"):
                    return True
                marker["facts"]["taken_over_at_utc"] = utc_now_iso()
                self._store(state)
            return True
        except Exception as exc:
            _log.warning(
                "pending notice takeover not recorded: %s",
                getattr(exc, "code", type(exc).__name__),
            )
            return False


class BoundPreDispatchPort:
    """``PreDispatchCommitPort`` bound to one BT order's ``local_seq``/``bt_ref``.

    Pass it as ``pre_dispatch_commit`` to the SDK; ``commit(record)`` behaves
    like :meth:`PendingCommandStore.commit` with the bound host facts.
    """

    __slots__ = ("store", "local_seq", "bt_ref", "last_marker_id")

    def __init__(
        self,
        store: PendingCommandStore,
        *,
        local_seq: Optional[int] = None,
        bt_ref: Optional[int] = None,
    ) -> None:
        self.store = store
        self.local_seq = local_seq
        self.bt_ref = bt_ref
        self.last_marker_id: Optional[str] = None

    def commit(self, record: Any) -> Optional[str]:
        marker_id = self.store.commit(record, local_seq=self.local_seq, bt_ref=self.bt_ref)
        if marker_id is not None:
            self.last_marker_id = marker_id
        return marker_id
