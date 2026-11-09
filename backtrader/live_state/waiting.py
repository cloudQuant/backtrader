"""Orders created during a confirmed market closure, waiting for the next session.

``state/waiting_orders.json`` holds ``{"version": 1, "strategy_uuid",
"orders": {waiting_id: order}, "history": [order, ...]}`` (D62-30/31).  The
original order parameters and the *intent* of the validity (``valid_intent``)
are stored unchanged; a DAY validity is computed by the dispatcher at actual
submit time, never pre-computed here.  ``offset`` is stored exactly as the
strategy gave it (``close_today`` is never rewritten).

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
from typing import Any, List, Mapping, Optional

from ._common import (
    StatePaths,
    ensure_no_secret_keys,
    get_logger,
    is_finite_number,
    is_strict_int,
    is_text,
    is_trading_day,
    is_uuid4,
    json_safe_copy,
    new_uuid4,
    parse_aware_iso,
    utc_now_iso,
)
from .atomic import (
    LiveStateCorrupt,
    LiveStateError,
    LiveStateIdentityMismatch,
    LiveStateNotInitialized,
    atomic_write_json,
    read_json,
)

__all__ = ("WAITING_STATUSES", "WAITING_VERSION", "WaitingOrderStore")

_log = get_logger(__name__)

WAITING_VERSION = 1
HISTORY_LIMIT = 500
_TRANSITIONS_LIMIT = 32

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


def _check_stored(order: Any, path: str, *, terminal: bool) -> None:
    if not isinstance(order, dict) or set(order) != _STORED:
        raise LiveStateCorrupt(path, "invalid_waiting_order")
    if not is_uuid4(order["waiting_id"]):
        raise LiveStateCorrupt(path, "invalid_waiting_id")
    status = order["status"]
    if status not in WAITING_STATUSES or (status in _TERMINAL) != terminal:
        raise LiveStateCorrupt(path, "invalid_waiting_status")


def validate_waiting_state(raw: Any, path: str, strategy_uuid: Optional[str]) -> dict:
    if not isinstance(raw, dict):
        raise LiveStateCorrupt(path, "not_a_mapping")
    if set(raw) != {"version", "strategy_uuid", "orders", "history"}:
        raise LiveStateCorrupt(path, "unexpected_keys")
    if type(raw["version"]) is not int or raw["version"] != WAITING_VERSION:
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
    keys = {"trading_day", "continuous_start_utc", "session_end_utc"}
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _bad("target_session")
    if not is_trading_day(value["trading_day"]):
        raise _bad("target_session.trading_day")
    start = parse_aware_iso(value["continuous_start_utc"])
    end = parse_aware_iso(value["session_end_utc"])
    if start is None or end is None or not start < end:
        raise _bad("target_session.window")
    return {key: value[key] for key in sorted(keys)}


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
    ) -> None:
        if not is_uuid4(strategy_uuid):
            raise LiveStateError("invalid_strategy_uuid")
        if not is_strict_int(history_limit, minimum=1):
            raise ValueError("history_limit must be a positive int")
        self.paths = StatePaths(strategy_dir)
        self.strategy_uuid = strategy_uuid
        self.lock_timeout = lock_timeout
        self.history_limit = history_limit

    @property
    def path(self) -> str:
        return self.paths.waiting

    def _lock(self):
        from .coordination import CoordinatedFileLock

        return CoordinatedFileLock(self.paths, self.paths.waiting_lock, timeout=self.lock_timeout)

    def _load(self) -> dict:
        try:
            raw = read_json(self.paths.waiting)
        except FileNotFoundError:
            raise LiveStateNotInitialized(self.paths.waiting) from None
        return validate_waiting_state(raw, self.paths.waiting, self.strategy_uuid)

    def _store(self, state: dict) -> None:
        overflow = len(state["history"]) - self.history_limit
        if overflow > 0:
            del state["history"][:overflow]
        atomic_write_json(self.paths.waiting, state)

    def add(self, order: Mapping[str, Any]) -> str:
        """Durably add a WAITING order; return its ``waiting_id``.

        Raises ``LiveStateError("waiting_invalid")`` for invalid input,
        ``("waiting_duplicate")`` for a reused ``waiting_id`` or a
        ``local_seq`` that already has a non-terminal waiting order, and any
        lock/corruption/I/O error (nothing is stored then).
        """
        stored = normalize_waiting_order(order)
        with self._lock():
            state = self._load()
            waiting_id = stored["waiting_id"]
            if waiting_id in state["orders"] or any(
                item["waiting_id"] == waiting_id for item in state["history"]
            ):
                raise LiveStateError("waiting_duplicate", "waiting_id")
            for item in state["orders"].values():
                if item["local_seq"] == stored["local_seq"]:
                    raise LiveStateError("waiting_duplicate", "local_seq")
            state["orders"][waiting_id] = stored
            self._store(state)
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
            state = self._load()
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
            self._store(state)
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
                state = self._load()
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
                self._store(state)
            return True
        except Exception as exc:
            _log.warning(
                "waiting notice takeover not recorded: %s",
                getattr(exc, "code", type(exc).__name__),
            )
            return False

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
