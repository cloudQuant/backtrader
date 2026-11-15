"""Apply the read-only Execution parent projection onto routed BT orders.

Iteration 65 step 65.07.  :mod:`backtrader.brokers._execution_parent_projection`
turns injected Execution parent facts into immutable BT-facing facts
(:class:`ParentOrderFact`, :class:`ParentNotification`,
:class:`PositionDelta`).  This module is the application side: it keeps one
read-only projection per routed parent, remembers which fact identities were
already delivered, and hands new deltas/notifications to explicitly injected
callbacks.  It never sends, cancels, reserves or reads a provider; the
framework side (a Broker) owns the real ``Order``/``Position`` mutation and the
existing notification path.

Contract:

* Only an explicitly registered parent is projected.  A Broker with no facts
  port configured therefore keeps its existing behaviour exactly.
* Each registration is a declared BT intent (``request_id`` + binding) plus the
  persisted Execution metadata a restart needs (``parent_ref``, the stable
  request key and the run id).  The binding is validated strictly and never
  inferred from the facts.
* The same facts twice - in one instance or after :meth:`snapshot` and a new
  instance with ``restore=`` - deliver no second notification and no second
  position delta.  A later fact advances once.  An identity is only remembered
  after its callback succeeded.
* A parent without an attached real order is still projected (so a restart can
  reconstruct the fact), but its deltas/notifications stay *pending* until an
  order is attached: nothing is marked applied and nothing is fabricated.
* A missing/unreadable facts port never changes an order status and never
  resends; the record keeps a finite code and the last projected fact (if one
  existed).

Evidence level: UNIT/FAKE.  Nothing here proves an Execution service, a
Gateway acceptance, a venue fill, an account position or a delivered Strategy
notification.
"""

from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from ._execution_parent_projection import (
    ExecutionParentProjection,
    ExecutionParentProjectionError,
    ParentNotification,
    PositionDelta,
    order_binding,
)
from ..order import Order

SCHEMA = "execution.parent_projection_apply/v1"

# Finite application codes this module publishes.  Projection refusals keep
# their own finite code from ``_execution_parent_projection.CODES``.
APPLY_CODES = frozenset(
    {
        "EXECUTION_FACTS_PORT_UNAVAILABLE",
        "EXECUTION_FACTS_PORT_INVALID",
        "EXECUTION_RECORD_INVALID",
        "EXECUTION_RECORD_CONFLICT",
        "EXECUTION_APPLY_INVALID",
    }
)

_OFFSETS = ("open", "close", "close_today", "close_yesterday")
_SIDES = ("buy", "sell")
_BINDING_REQUIRED = frozenset({"bt_ref", "side", "offset", "quantity", "price"})
_BINDING_OPTIONAL = frozenset({"request_id", "parent_ref", "strategy_ref", "trading_day"})
_DECIMAL_TEXT = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_DAY_TEXT = re.compile(r"[0-9]{8}\Z")
_MAX_RECORDS = 10_000
_MAX_TEXT_BYTES = 256
_NOTIFICATION_FIELDS = (
    "dedupe_key",
    "kind",
    "request_id",
    "bt_ref",
    "parent_ref",
    "state",
    "reason_code",
    "bt_status",
    "bt_status_name",
)
_DELTA_FIELDS = (
    "request_id",
    "child_id",
    "fill_id",
    "side",
    "offset",
    "quantity",
    "price",
    "trading_day",
    "exchange_trade_id",
    "delta_key",
)
_NOTIFICATION_KINDS = frozenset(
    {"submitted", "accepted", "rejected", "canceled", "completed", "unknown"}
)


class ExecutionRoutingApplyError(RuntimeError):
    """Finite application failure; the message is the code and carries no values."""

    def __init__(self, code):
        if code not in APPLY_CODES:
            raise ValueError("unknown application code")
        self.code = code
        super().__init__(code)


def _text(value):
    if type(value) is not str or not value or value != value.strip():
        return None
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return None
    if len(encoded) > _MAX_TEXT_BYTES:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return None
    return value


def _optional_text(value):
    return None if value is None else _text(value)


def _positive_decimal(value):
    """Return normalized plain text of one positive decimal literal, else ``None``."""
    if type(value) is bool:
        return None
    if type(value) is str:
        if _DECIMAL_TEXT.fullmatch(value) is None:
            return None
        try:
            number = Decimal(value)
        except ArithmeticError:
            return None
    elif isinstance(value, Decimal):
        number = value
    elif type(value) is int:
        number = Decimal(value)
    elif type(value) is float:
        if not math.isfinite(value):
            return None
        number = Decimal(repr(value))
    else:
        return None
    if not number.is_finite() or number <= 0:
        return None
    text = format(number.normalize(), "f")
    if text in ("-0", "-0.0"):
        text = "0"
    return text


def _normalized_binding(request_id, raw):
    """Validate one persisted binding; return its canonical mapping or ``None``."""
    if not isinstance(raw, Mapping):
        return None
    keys = frozenset(raw)
    if keys < _BINDING_REQUIRED or keys - (_BINDING_REQUIRED | _BINDING_OPTIONAL):
        return None
    declared = raw.get("request_id")
    if declared is not None and declared != request_id:
        return None
    bt_ref = raw["bt_ref"]
    if type(bt_ref) is not int or bt_ref < 1:
        return None
    side = raw["side"]
    if side not in _SIDES:
        return None
    offset = raw["offset"]
    if offset is not None and offset not in _OFFSETS:
        return None
    quantity = _positive_decimal(raw["quantity"])
    price = _positive_decimal(raw["price"])
    if quantity is None or price is None:
        return None
    parent_ref = _optional_text(raw.get("parent_ref"))
    if raw.get("parent_ref") is not None and parent_ref is None:
        return None
    strategy_ref = _optional_text(raw.get("strategy_ref"))
    if raw.get("strategy_ref") is not None and strategy_ref is None:
        return None
    trading_day = raw.get("trading_day")
    if trading_day is not None and (
        type(trading_day) is not str or _DAY_TEXT.fullmatch(trading_day) is None
    ):
        return None
    binding = {
        "request_id": request_id,
        "bt_ref": bt_ref,
        "side": side,
        "offset": offset,
        "quantity": quantity,
        "price": price,
    }
    for name, value in (
        ("parent_ref", parent_ref),
        ("strategy_ref", strategy_ref),
        ("trading_day", trading_day),
    ):
        if value is not None:
            binding[name] = value
    return binding


def _port_reader(port, name):
    """Return a callable that reads ``name`` for one request, or ``None``."""
    if port is None:
        return None
    if isinstance(port, Mapping) or callable(port):
        return port
    method = getattr(port, name, None)
    return method if callable(method) else None


@dataclass
class RoutedParentRecord:
    """One registered routed parent and the fact identities already delivered."""

    request_id: str
    binding: dict
    parent_ref: object = None
    request_key: object = None
    run_id: object = None
    order: object = None
    applied_notifications: set = field(default_factory=set)
    applied_deltas: set = field(default_factory=set)
    pending_notifications: list = field(default_factory=list)
    pending_deltas: list = field(default_factory=list)
    last_code: object = None
    last_status: object = None
    last_state: object = None
    fact: object = None


@dataclass(frozen=True)
class ApplyResult:
    """One bounded poll round; value-free counters and finite codes only."""

    polled: int
    notifications: int
    deltas: int
    pending_notifications: int
    pending_deltas: int
    refused: int
    skipped: int
    codes: tuple

    def payload(self):
        return {
            "polled": self.polled,
            "notifications": self.notifications,
            "deltas": self.deltas,
            "pending_notifications": self.pending_notifications,
            "pending_deltas": self.pending_deltas,
            "refused": self.refused,
            "skipped": self.skipped,
            "codes": list(self.codes),
        }


@dataclass(frozen=True)
class ApplicationStatus:
    """A read-only, value-free view of the application instance."""

    records: int
    notifications: int
    deltas: int
    refused: int
    unknown_facts: int
    restored: bool
    port_code: object
    schema: str = SCHEMA

    def payload(self):
        return {
            "schema": self.schema,
            "records": self.records,
            "notifications": self.notifications,
            "deltas": self.deltas,
            "refused": self.refused,
            "unknown_facts": self.unknown_facts,
            "restored": self.restored,
            "port_code": self.port_code,
        }


class ExecutionRoutingApplication:
    """One read-only application over explicitly registered routed parents.

    ``facts`` is the injected read-only port.  For a plain object it exposes the
    projection readers ``status``, ``fills``, ``cancel`` and ``completion``
    (each taking the ``request_id``); ``status`` is required.  A mapping or a
    callable is also accepted and used for every reader, exactly like the
    projection's own ports.  ``on_fact``/``on_notification``/``on_delta`` are
    invoked on the calling (owner) thread only, and only for a record with an
    attached real order.  ``on_fact`` returns whether it delivered a status
    notification; ``on_notification`` also receives ``status_changed`` so an
    ``unknown`` fact does not repeat a status transition already notified in
    the same round.
    """

    def __init__(
        self,
        *,
        facts,
        on_fact=None,
        on_notification=None,
        on_delta=None,
        clock=None,
        interval=1.0,
        max_orders=32,
        restore=None,
    ):
        self._lock = threading.RLock()
        self._clock = clock if callable(clock) else time.monotonic
        self._interval = max(float(interval), 0.0) if interval is not None else 0.0
        self._max_orders = max(int(max_orders), 0) if max_orders is not None else 0
        self._on_fact = on_fact if callable(on_fact) else None
        self._on_notification = on_notification if callable(on_notification) else None
        self._on_delta = on_delta if callable(on_delta) else None
        self._records = {}
        self._cursor = 0
        self._last_poll = None
        self._counters = {
            "notifications": 0,
            "deltas": 0,
            "refused": 0,
            "unknown_facts": 0,
        }
        self._projection = None
        self._port_code = None
        self._restored = False
        projection_state = None
        if restore is not None:
            projection_state = self._load_restore(restore)
            self._restored = True
        self._build_projection(facts, projection_state)

    # -- construction ------------------------------------------------------
    def _build_projection(self, facts, restore):
        status = _port_reader(facts, "status")
        if status is None:
            self._projection = None
            self._port_code = (
                "EXECUTION_FACTS_PORT_UNAVAILABLE"
                if facts is None
                else "EXECUTION_FACTS_PORT_INVALID"
            )
            return
        try:
            self._projection = ExecutionParentProjection(
                binding_port=self._binding_for,
                status_port=status,
                fill_port=_port_reader(facts, "fills"),
                cancel_port=_port_reader(facts, "cancel"),
                completion_port=_port_reader(facts, "completion"),
                restore=restore,
            )
        except ExecutionParentProjectionError as error:
            self._projection = None
            self._port_code = error.code
        else:
            self._port_code = None

    def _binding_for(self, request_id):
        record = self._records.get(request_id)
        if record is None:
            # The projection turns this into a finite refusal; a binding is
            # never guessed from the facts.
            raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
        return dict(record.binding)

    # -- read-only views ---------------------------------------------------
    def status(self):
        with self._lock:
            return ApplicationStatus(
                records=len(self._records),
                notifications=self._counters["notifications"],
                deltas=self._counters["deltas"],
                refused=self._counters["refused"],
                unknown_facts=self._counters["unknown_facts"],
                restored=self._restored,
                port_code=self._port_code,
            )

    def projection_status(self):
        with self._lock:
            return None if self._projection is None else self._projection.projection_status()

    def record(self, request_id):
        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                return None
            return {
                "request_id": record.request_id,
                "binding": dict(record.binding),
                "parent_ref": record.parent_ref,
                "request_key": record.request_key,
                "run_id": record.run_id,
                "last_code": record.last_code,
                "last_status": record.last_status,
                "last_state": record.last_state,
                "has_order": record.order is not None,
                "pending_notifications": len(record.pending_notifications),
                "pending_deltas": len(record.pending_deltas),
                "applied_notifications": len(record.applied_notifications),
                "applied_deltas": len(record.applied_deltas),
            }

    # -- registration ------------------------------------------------------
    def register(
        self,
        *,
        request_id,
        order=None,
        binding=None,
        parent_ref=None,
        request_key=None,
        run_id=None,
        offset=None,
        strategy_ref=None,
        trading_day=None,
    ):
        """Register one routed parent; returns a finite code or ``None``.

        ``binding`` (persisted, canonical) is required when ``order`` is
        ``None``; otherwise it is derived from the real order, which is the
        declared BT intent and not a fact.  A repeated registration of the same
        request is idempotent; a different binding is refused.
        """
        text = _text(request_id)
        if text is None:
            return "EXECUTION_RECORD_INVALID"
        if binding is None:
            if order is None:
                return "EXECUTION_RECORD_INVALID"
            try:
                binding = order_binding(
                    order,
                    text,
                    offset=offset,
                    parent_ref=parent_ref,
                    strategy_ref=strategy_ref,
                    trading_day=trading_day,
                )
            except ExecutionParentProjectionError as error:
                return error.code
        normalized = _normalized_binding(text, binding)
        if normalized is None:
            return "EXECUTION_RECORD_INVALID"
        parent_ref_text = _optional_text(parent_ref)
        request_key_text = _optional_text(request_key)
        run_id_text = _optional_text(run_id)
        with self._lock:
            record = self._records.get(text)
            if record is not None:
                if record.binding != normalized:
                    return "EXECUTION_RECORD_CONFLICT"
                if order is not None:
                    record.order = order
                if parent_ref_text is not None:
                    record.parent_ref = parent_ref_text
                if request_key_text is not None:
                    record.request_key = request_key_text
                if run_id_text is not None:
                    record.run_id = run_id_text
                return None
            if len(self._records) >= _MAX_RECORDS:
                return "EXECUTION_RECORD_INVALID"
            self._records[text] = RoutedParentRecord(
                request_id=text,
                binding=normalized,
                parent_ref=parent_ref_text,
                request_key=request_key_text,
                run_id=run_id_text,
                order=order,
            )
        return None

    def attach(self, request_id, order):
        """Bind a real order to an already registered request; finite code or ``None``."""
        text = _text(request_id)
        if text is None or order is None:
            return "EXECUTION_RECORD_INVALID"
        with self._lock:
            record = self._records.get(text)
            if record is None:
                return "EXECUTION_RECORD_INVALID"
            record.order = order
        return None

    def unregister(self, request_id):
        with self._lock:
            self._records.pop(request_id, None)

    # -- polling -----------------------------------------------------------
    def due(self):
        """Whether the owner thread may start another bounded poll round now."""
        if self._interval <= 0:
            return True
        now = self._clock()
        if self._last_poll is None:
            return True
        return now - self._last_poll >= self._interval

    def poll(self):
        """Project the next bounded batch on the calling (owner) thread."""
        with self._lock:
            if not self.due():
                return ApplyResult(0, 0, 0, 0, 0, 0, 0, ())
            self._last_poll = self._clock()
            records = list(self._records.values())
            if not records:
                return ApplyResult(0, 0, 0, 0, 0, 0, 0, ())
            if self._max_orders <= 0:
                return ApplyResult(0, 0, 0, 0, 0, 0, len(records), ())
            start = self._cursor % len(records)
            self._cursor = (start + 1) % len(records)
            budget = self._max_orders
            batch = records[start : start + budget]
            if len(batch) < budget:
                batch += records[: budget - len(batch)]
            return self._poll_batch(tuple(batch))

    def _poll_batch(self, batch):
        polled = notifications = deltas = refused = 0
        codes = []
        for record in batch:
            polled += 1
            if self._projection is None:
                self._mark(record, self._port_code, None)
                refused += 1
                codes.append(self._port_code)
                self._drain(record, None)
                continue
            try:
                result = self._projection.project(record.request_id)
            except ExecutionParentProjectionError as error:
                self._mark(record, error.code, None)
                refused += 1
                codes.append(error.code)
                self._drain(record, record.fact)
                continue
            applied_notifications = len(record.applied_notifications)
            applied_deltas = len(record.applied_deltas)
            self._absorb(record, result)
            if result.parent_fact is not None:
                record.fact = result.parent_fact
            if result.position_deltas:
                self._counters["deltas"] += len(result.position_deltas)
            if result.notifications:
                self._counters["notifications"] += len(result.notifications)
            if result.refused:
                refused += 1
                self._counters["refused"] += 1
                codes.append(result.code)
                self._mark(record, result.code, record.fact)
                self._drain(record, record.fact)
                notifications += len(record.applied_notifications) - applied_notifications
                deltas += len(record.applied_deltas) - applied_deltas
                continue
            if result.code is not None:
                codes.append(result.code)
            if result.parent_fact is not None and result.parent_fact.unknown:
                self._counters["unknown_facts"] += 1
            self._mark(record, result.code, record.fact)
            self._drain(record, record.fact)
            notifications += len(record.applied_notifications) - applied_notifications
            deltas += len(record.applied_deltas) - applied_deltas
        pending_notifications = sum(len(item.pending_notifications) for item in batch)
        pending_deltas = sum(len(item.pending_deltas) for item in batch)
        return ApplyResult(
            polled,
            notifications,
            deltas,
            pending_notifications,
            pending_deltas,
            refused,
            0,
            tuple(sorted({code for code in codes if code is not None})),
        )

    def _absorb(self, record, result):
        new_notifications = 0
        for delta in result.position_deltas:
            if delta.delta_key in record.applied_deltas:
                continue
            if any(item.delta_key == delta.delta_key for item in record.pending_deltas):
                continue
            record.pending_deltas.append(delta)
        for notification in result.notifications:
            if notification.dedupe_key in record.applied_notifications:
                continue
            if any(
                item.dedupe_key == notification.dedupe_key for item in record.pending_notifications
            ):
                continue
            record.pending_notifications.append(notification)
            new_notifications += 1
        return new_notifications

    def _drain(self, record, fact):
        """Deliver pending facts/notifications/deltas once; remember each success.

        A record without an attached order, or without the corresponding
        callback, keeps its pending work: nothing is marked applied and nothing
        is fabricated.  ``on_fact`` returns whether it already delivered a
        status notification in this round; ``on_notification`` receives that
        flag so a status-less ``unknown`` fact does not duplicate it.
        """
        status_changed = False
        if record.order is not None and self._on_delta is not None:
            while record.pending_deltas:
                delta = record.pending_deltas[0]
                self._on_delta(record, delta)
                record.applied_deltas.add(delta.delta_key)
                record.pending_deltas.pop(0)
        if record.order is not None and self._on_fact is not None:
            status_changed = bool(self._on_fact(record, fact, record.last_code))
        if record.order is not None and self._on_notification is not None:
            while record.pending_notifications:
                notification = record.pending_notifications[0]
                self._on_notification(record, notification, status_changed=status_changed)
                record.applied_notifications.add(notification.dedupe_key)
                record.pending_notifications.pop(0)

    @staticmethod
    def _mark(record, code, fact):
        record.last_code = code
        if fact is not None:
            record.fact = fact
            record.last_status = fact.bt_status
            record.last_state = fact.state

    # -- restart -----------------------------------------------------------
    def snapshot(self):
        """Detached restart state: applied identities, pending work and projection state."""
        with self._lock:
            return {
                "schema": SCHEMA,
                "projection": (None if self._projection is None else self._projection.snapshot()),
                "records": {
                    request_id: {
                        "binding": dict(record.binding),
                        "parent_ref": record.parent_ref,
                        "request_key": record.request_key,
                        "run_id": record.run_id,
                        "applied_notifications": sorted(record.applied_notifications),
                        "applied_deltas": sorted(record.applied_deltas),
                        "pending_notifications": [
                            item.payload() for item in record.pending_notifications
                        ],
                        "pending_deltas": [item.payload() for item in record.pending_deltas],
                    }
                    for request_id, record in sorted(self._records.items())
                },
            }

    def _load_restore(self, restore):
        """Validate a restart state; return its projection state for the constructor."""
        if not isinstance(restore, Mapping) or frozenset(restore) != {
            "schema",
            "projection",
            "records",
        }:
            raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
        if restore["schema"] != SCHEMA:
            raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
        raw_records = restore["records"]
        if not isinstance(raw_records, Mapping) or len(raw_records) > _MAX_RECORDS:
            raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
        records = {}
        for raw_request, raw in raw_records.items():
            request_id = _text(raw_request)
            if request_id is None or not isinstance(raw, Mapping):
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if frozenset(raw) != {
                "binding",
                "parent_ref",
                "request_key",
                "run_id",
                "applied_notifications",
                "applied_deltas",
                "pending_notifications",
                "pending_deltas",
            }:
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            binding = _normalized_binding(request_id, raw["binding"])
            if binding is None:
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            parent_ref = _optional_text(raw["parent_ref"])
            request_key = _optional_text(raw["request_key"])
            run_id = _optional_text(raw["run_id"])
            if any(
                value is not None and text is None
                for value, text in (
                    (raw["parent_ref"], parent_ref),
                    (raw["request_key"], request_key),
                    (raw["run_id"], run_id),
                )
            ):
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            records[request_id] = RoutedParentRecord(
                request_id=request_id,
                binding=binding,
                parent_ref=parent_ref,
                request_key=request_key,
                run_id=run_id,
                applied_notifications=self._restore_keys(raw["applied_notifications"]),
                applied_deltas=self._restore_keys(raw["applied_deltas"]),
                pending_notifications=self._restore_pending_notifications(
                    raw["pending_notifications"]
                ),
                pending_deltas=self._restore_pending_deltas(raw["pending_deltas"]),
            )
        self._records = records
        projection = restore["projection"]
        if projection is not None and not isinstance(projection, Mapping):
            raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
        return projection

    @staticmethod
    def _restore_keys(values):
        if not isinstance(values, list) or any(type(item) is not str for item in values):
            raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
        if len(set(values)) != len(values):
            raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
        return set(values)

    @staticmethod
    def _restore_pending_notifications(values):
        if not isinstance(values, list):
            raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
        restored = []
        for raw in values:
            if not isinstance(raw, Mapping) or set(raw) != set(_NOTIFICATION_FIELDS):
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if any(raw[name] is None for name in ("dedupe_key", "kind", "request_id")):
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if not _is_digest(raw["dedupe_key"]):
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if raw["kind"] not in _NOTIFICATION_KINDS:
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if _text(raw["request_id"]) is None:
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if type(raw["bt_ref"]) is not int or raw["bt_ref"] < 1:
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if raw["parent_ref"] is not None and _text(raw["parent_ref"]) is None:
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if raw["state"] is not None and _text(raw["state"]) is None:
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if raw["reason_code"] is not None and type(raw["reason_code"]) is not str:
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if type(raw["bt_status"]) is not int or not (0 <= raw["bt_status"] <= Order.Rejected):
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if type(raw["bt_status_name"]) is not str:
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            restored.append(
                ParentNotification(**{name: raw[name] for name in _NOTIFICATION_FIELDS})
            )
        return restored

    @staticmethod
    def _restore_pending_deltas(values):
        if not isinstance(values, list):
            raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
        restored = []
        for raw in values:
            if not isinstance(raw, Mapping) or set(raw) != set(_DELTA_FIELDS):
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if any(_text(raw[name]) is None for name in ("request_id", "child_id", "fill_id")):
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if raw["side"] not in _SIDES:
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if raw["offset"] is not None and raw["offset"] not in _OFFSETS:
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if not _signed_decimal_text(raw["quantity"]) or not _positive_decimal(raw["price"]):
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if raw["trading_day"] is not None and (
                type(raw["trading_day"]) is not str
                or _DAY_TEXT.fullmatch(raw["trading_day"]) is None
            ):
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if raw["exchange_trade_id"] is not None and _text(raw["exchange_trade_id"]) is None:
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            if not _is_digest(raw["delta_key"]):
                raise ExecutionRoutingApplyError("EXECUTION_RECORD_INVALID")
            restored.append(PositionDelta(**{name: raw[name] for name in _DELTA_FIELDS}))
        return restored


def _is_digest(value):
    prefix = "epp:"
    return (
        type(value) is str
        and value.startswith(prefix)
        and re.fullmatch(r"[0-9a-f]{64}", value[len(prefix) :]) is not None
    )


def _signed_decimal_text(value):
    if type(value) is not str or _DECIMAL_TEXT.fullmatch(value) is None:
        return False
    try:
        return Decimal(value).is_finite()
    except ArithmeticError:
        return False


__all__ = (
    "APPLY_CODES",
    "ApplicationStatus",
    "ApplyResult",
    "ExecutionRoutingApplication",
    "ExecutionRoutingApplyError",
    "RoutedParentRecord",
    "SCHEMA",
)
