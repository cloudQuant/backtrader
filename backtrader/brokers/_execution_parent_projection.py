"""Read-only projection of Execution parent/child facts into BT order facts.

Iteration 65 step 65.07.  The independent Execution service owns the parent
intent, its child plans, the execution-local progress journal and the
authoritative fill/account facts.  Backtrader owns the framework projection:
the real ``Order``/``Position`` objects of a running strategy and the
notifications the strategy receives.  This module is the boundary between the
two: it consumes a read-only Execution parent status through injected ports (or
plain mappings) and returns immutable facts.  It never calls a provider, opens
a socket, reads a credential, sends an order, cancels an order or installs an
object into a Strategy or Broker.  Application to routed orders lives in
``_execution_routing_apply`` and is opt-in through an injected facts port; this
module itself remains a pure projection.

Inputs (each port is a mapping keyed by ``request_id``, a callable taking the
``request_id``, or an object exposing the method of the same name):

``binding``   required.  The declared BT order intent: ``bt_ref``, ``side``
              (``buy``/``sell``), ``offset`` (explicit open/close family or
              ``None``), ``quantity`` and ``price`` (finite positive decimals;
              a first-phase Execution parent is limit-only, D65-07).  Optional:
              ``request_id`` (must match), ``parent_ref``, ``strategy_ref``,
              ``trading_day``.  :func:`order_binding` derives one from a real
              BT order.
``status``    the committed shape of
              ``bt_api_execution.parent_submit_service.status()``: parent
              ``state``, ``parent_ref``, ``request_sha256``, ``frozen``,
              ``last_error``, ``children`` (each with ``child_id``, ``state``,
              ``quantity``, ``reservation_id``, ``attempts``, ``last_error``)
              and ``unknown_children``.  Additive keys are tolerated; every
              required key is validated.
``fills``     optional.  A committed snapshot of authoritative fill facts, each
              ``fill_id`` (stable), ``child_id``, ``quantity``, ``price``,
              ``source`` = ``VENUE``, and optionally ``side``, ``offset``,
              ``trading_day``, ``exchange_trade_id``, ``parent_ref``.  A mapping
              that returns ``()`` declares "no committed fills"; a missing port
              or a ``None`` reply means the fill state is UNKNOWN.  Plans and
              execution scheduling are never converted into fills.
``cancel``    optional.  An authoritative cancel result: ``cancel_id`` and
              ``outcome`` in ``CANCELED``/``UNKNOWN``/``REJECTED``.
``completion`` optional.  An authoritative parent completion record:
              ``completion_id`` and ``completed_quantity``.

State mapping (parent facts):

===================  ==================================  =================
Execution state      BT order status                     notification
===================  ==================================  =================
``RECEIVED``         Submitted                           ``submitted``
``RISK_CLAIMED``     Submitted                           (once, see above)
``REGISTERING``      Submitted                           (once, see above)
``ACCEPTED``         Accepted                            ``accepted``
``REJECTED``         Rejected                            ``rejected``
``UNKNOWN``          Submitted or Accepted (never a      ``unknown``
                     terminal status)                    (finite reason)
absent / unreadable  Submitted or Accepted (never a      ``unknown``
                     terminal status)                    (finite reason)
unrecognized state   Submitted or Accepted (never a      ``unknown``
                     terminal status)                    (finite reason)
frozen               Submitted or Accepted (never a      ``unknown``
                     terminal status)                    (finite reason)
cancel ``CANCELED``  Canceled                            ``canceled``
cancel ``UNKNOWN``   Submitted or Accepted (never a      ``unknown``
                     terminal status)                    (finite reason)
cancel ``REJECTED``  unchanged                           none
completion           Completed                           ``completed``
===================  ==================================  =================

``Submitted``/``Accepted`` are the two active statuses: a fact never regresses
an order that already reached ``Accepted``, and a frozen or unknown parent is
never ``Rejected``/``Canceled``/``Completed``/``Expired``.  ``Canceled`` and
``Completed`` come only from their own authoritative fact, never from a state
name.  Child states map to nothing on the strategy order (per D65-03 and §3.6 a
child's own accepted/cancelled/rejected is not projected to BT): ``PLANNED``,
``RESERVING``, ``RESERVED`` and ``DISPATCHING`` are in flight and never a fill;
``SENT`` is on its way to the venue and never a fill; ``REJECTED`` cancels no
parent remainder; ``UNKNOWN`` freezes the parent and keeps the order active.

Missing facts are UNKNOWN, never "not sent": an absent reply, an unreadable
reply and an unrecognized state all keep the order non-terminal with a finite
code.  Only a committed ``PLANNED`` child state plus ``attempts == 0`` shows
that no remote attempt was claimed; that is still not a proof about the venue.

Dedupe and replay: every notification and every position delta carries a
deterministic key derived from the request identity and the fact content.  The
same facts twice (in one instance, or after :meth:`snapshot` and constructing a
new instance with ``restore=``) produce no second notification and no second
delta; a later fact advances exactly once; a regressed or foreign parent/child
identity is refused with a finite code and no state change.  A parent state
repeated identically is an idempotent identity transition for every committed
state -- including ``RECEIVED``/``RISK_CLAIMED``/``REGISTERING`` before
acceptance -- and never raises ``EXECUTION_STATE_REGRESSED``; only a genuine
backward or cross-line move is refused.

Evidence level: UNIT/FAKE.  Nothing here proves an Execution service, a
Gateway acceptance, a venue fill, an account permission or a Strategy
notification was delivered.  Internal transfer and virtual conversion ledgers
are not projected here; a fill fact whose ``source`` is not ``VENUE`` is
refused instead of being counted as a venue fill.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from ..order import Order, OrderBase
from ..position import Position

SCHEMA = "execution.parent_projection/v1"
STATE_SCHEMA = "execution.parent_projection_state/v1"

PARENT_STATES = (
    "RECEIVED",
    "RISK_CLAIMED",
    "REGISTERING",
    "ACCEPTED",
    "REJECTED",
    "UNKNOWN",
)
CHILD_STATES = (
    "PLANNED",
    "RESERVING",
    "RESERVED",
    "DISPATCHING",
    "SENT",
    "REJECTED",
    "UNKNOWN",
)
NOTIFICATION_KINDS = frozenset(
    {"submitted", "accepted", "rejected", "canceled", "completed", "unknown"}
)
CANCEL_OUTCOMES = ("CANCELED", "UNKNOWN", "REJECTED")
OFFSETS = ("open", "close", "close_today", "close_yesterday")
SIDES = ("buy", "sell")
FILL_SOURCES = ("VENUE",)

# Legal forward transitions of the committed Execution journal.  A poll can
# skip intermediate states, so every later state of the same line is allowed.
# A repeated identical state is an idempotent identity transition, not a
# regression: the journal can commit the same state again while the parent has
# not moved, and re-projecting the same snapshot must not raise a regression.
# UNKNOWN has no outgoing journal transition; an authoritative query that
# resolves it to ACCEPTED or REJECTED is accepted, any other move is a
# regression.  ACCEPTED and REJECTED are terminal here.
PARENT_TRANSITIONS = MappingProxyType(
    {
        "RECEIVED": frozenset(
            {"RECEIVED", "RISK_CLAIMED", "REGISTERING", "ACCEPTED", "REJECTED", "UNKNOWN"}
        ),
        "RISK_CLAIMED": frozenset(
            {"RISK_CLAIMED", "REGISTERING", "ACCEPTED", "REJECTED", "UNKNOWN"}
        ),
        "REGISTERING": frozenset({"REGISTERING", "ACCEPTED", "REJECTED", "UNKNOWN"}),
        "ACCEPTED": frozenset({"ACCEPTED"}),
        "REJECTED": frozenset({"REJECTED"}),
        "UNKNOWN": frozenset({"UNKNOWN", "ACCEPTED", "REJECTED"}),
    }
)
CHILD_TRANSITIONS = MappingProxyType(
    {
        "PLANNED": frozenset(
            {"PLANNED", "RESERVING", "RESERVED", "DISPATCHING", "SENT", "REJECTED", "UNKNOWN"}
        ),
        "RESERVING": frozenset(
            {"RESERVING", "RESERVED", "DISPATCHING", "SENT", "REJECTED", "UNKNOWN"}
        ),
        "RESERVED": frozenset({"RESERVED", "DISPATCHING", "SENT", "REJECTED", "UNKNOWN"}),
        "DISPATCHING": frozenset({"DISPATCHING", "SENT", "REJECTED", "UNKNOWN"}),
        "SENT": frozenset({"SENT"}),
        "REJECTED": frozenset({"REJECTED"}),
        "UNKNOWN": frozenset({"UNKNOWN", "SENT", "REJECTED"}),
    }
)

# Every finite code this module can raise, refuse with or publish as a reason.
CODES = frozenset(
    {
        "PORT_INVALID",
        "PORT_UNREADABLE",
        "RESTORE_INVALID",
        "INVALID_REQUEST_ID",
        "EXECUTION_BINDING_ABSENT",
        "EXECUTION_BINDING_INVALID",
        "EXECUTION_BINDING_CONFLICT",
        "EXECUTION_STATUS_ABSENT",
        "EXECUTION_STATUS_UNREADABLE",
        "EXECUTION_STATE_UNRECOGNIZED",
        "EXECUTION_CHILD_STATE_UNRECOGNIZED",
        "EXECUTION_CHILD_QUANTITY_INVALID",
        "EXECUTION_IDENTITY_FOREIGN",
        "EXECUTION_IDENTITY_CONFLICT",
        "EXECUTION_IDENTITY_REGRESSED",
        "EXECUTION_STATE_REGRESSED",
        "EXECUTION_REJECTED_WITH_CHILDREN",
        "EXECUTION_CHILD_IDENTITY_FOREIGN",
        "EXECUTION_CHILD_STATE_REGRESSED",
        "EXECUTION_CHILD_MISSING",
        "EXECUTION_PARENT_UNKNOWN",
        "EXECUTION_PARENT_FROZEN",
        "EXECUTION_CHILD_UNKNOWN",
        "EXECUTION_REMOTE_REJECTED",
        "FILL_PORT_UNAVAILABLE",
        "FILL_FACT_INVALID",
        "FILL_FACT_CONFLICT",
        "FILL_FACT_FOREIGN",
        "FILL_SOURCE_UNSUPPORTED",
        "FILL_SIDE_MISMATCH",
        "FILL_OFFSET_MISMATCH",
        "FILL_QUANTITY_EXCEEDS_ORDER",
        "FILL_QUANTITY_EXCEEDS_CHILD",
        "CANCEL_FACT_INVALID",
        "CANCEL_FACT_CONFLICT",
        "CANCEL_UNRESOLVED_CHILDREN",
        "CANCEL_OUTCOME_UNKNOWN",
        "CANCEL_REJECTED",
        "COMPLETION_FACT_INVALID",
        "COMPLETION_FACT_CONFLICT",
        "COMPLETION_FACT_UNPROVABLE",
        "COMPLETION_QUANTITY_MISMATCH",
        "EXECUTION_TERMINAL_CONFLICT",
        "POSITION_DELTA_INVALID",
    }
)
_CONFLICT_CODES = frozenset(
    {
        "EXECUTION_IDENTITY_CONFLICT",
        "EXECUTION_IDENTITY_REGRESSED",
        "EXECUTION_BINDING_CONFLICT",
        "FILL_FACT_CONFLICT",
        "FILL_FACT_FOREIGN",
        "CANCEL_FACT_CONFLICT",
        "COMPLETION_FACT_CONFLICT",
        "EXECUTION_TERMINAL_CONFLICT",
    }
)

_BT_STATUS = {
    "Submitted": Order.Submitted,
    "Accepted": Order.Accepted,
    "Completed": Order.Completed,
    "Canceled": Order.Canceled,
    "Rejected": Order.Rejected,
}
_BT_STATUS_NAMES = MappingProxyType({value: name for name, value in _BT_STATUS.items()})

_BINDING_REQUIRED = frozenset({"bt_ref", "side", "offset", "quantity", "price"})
_BINDING_OPTIONAL = frozenset({"request_id", "parent_ref", "strategy_ref", "trading_day"})
_STATUS_REQUIRED = frozenset(
    {
        "request_id",
        "parent_ref",
        "state",
        "request_sha256",
        "frozen",
        "last_error",
        "remote_attempts",
        "children",
        "unknown_children",
    }
)
_CHILD_REQUIRED = frozenset(
    {"child_id", "state", "quantity", "reservation_id", "attempts", "last_error"}
)
_FILL_REQUIRED = frozenset({"fill_id", "child_id", "quantity", "price", "source"})
_FILL_OPTIONAL = frozenset({"side", "offset", "trading_day", "exchange_trade_id", "parent_ref"})
_CANCEL_REQUIRED = frozenset({"cancel_id", "outcome"})
_CANCEL_OPTIONAL = frozenset({"reason_code"})
_COMPLETION_REQUIRED = frozenset({"completion_id", "completed_quantity"})
_COMPLETION_OPTIONAL = frozenset({"reason_code"})
_ENTRY_FIELDS = frozenset(
    {
        "binding",
        "parent_ref",
        "request_sha256",
        "parent_state",
        "status_frozen",
        "last_error",
        "children",
        "fills",
        "fill_total",
        "fill_children",
        "fills_known",
        "issued",
        "projected",
        "accepted",
        "terminal",
        "bt_status",
        "frozen",
        "unknown",
        "reason_code",
        "cancel_id",
        "cancel_outcome",
        "completion_id",
        "completed_quantity",
    }
)
_CHILD_ENTRY_FIELDS = frozenset({"state", "quantity", "reservation_id", "attempts", "last_error"})

_MAX_REQUESTS = 10_000
_MAX_CHILDREN = 10_000
_MAX_FILLS = 100_000
_MAX_TEXT_BYTES = 256
_MAX_REASON_BYTES = 64
_MAX_DECIMAL_TEXT = 64
_MAX_FRACTIONAL_DIGITS = 42
_MAX_ISSUED = 64
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_DECIMAL_TEXT = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_DAY_TEXT = re.compile(r"[0-9]{8}\Z")
_DIGEST_PREFIX = "epp:"


class ExecutionParentProjectionError(RuntimeError):
    """Finite projection failure; the message is the code and carries no values."""

    def __init__(self, code):
        if code not in CODES:
            raise ValueError("unknown projection code")
        self.code = code
        super().__init__(code)


class _Refusal(Exception):
    """The facts cannot be projected; the previous projection is kept."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _FactUnreadable(Exception):
    """One bounded fact cannot be read; it becomes an UNKNOWN fact, not a refusal."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


# ---------------------------------------------------------------------------
# value helpers
# ---------------------------------------------------------------------------
def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
    )


def _digest(*parts):
    return (
        _DIGEST_PREFIX
        + hashlib.sha256(_canonical(list(parts)).encode("utf-8", errors="strict")).hexdigest()
    )


def _text(value, max_bytes=_MAX_TEXT_BYTES):
    if type(value) is not str or not value or value != value.strip():
        return None
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return None
    if len(encoded) > max_bytes:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return None
    return value


def _optional_text(value, max_bytes=_MAX_TEXT_BYTES):
    return None if value is None else _text(value, max_bytes)


def _day(value):
    if type(value) is not str or _DAY_TEXT.fullmatch(value) is None:
        return None
    return value


def _decimal(value, *, positive=False):
    """Normalize one finite decimal to plain text; a float uses its repr."""
    if type(value) is bool:
        raise ValueError("boolean is not a decimal")
    if isinstance(value, Decimal):
        number = value
    elif type(value) is int:
        number = Decimal(value)
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError("non-finite float")
        number = Decimal(repr(value))
    elif type(value) is str:
        if _DECIMAL_TEXT.fullmatch(value) is None:
            raise ValueError("not a decimal literal")
        number = Decimal(value)
    else:
        raise ValueError("unsupported decimal type")
    if not number.is_finite():
        raise ValueError("non-finite decimal")
    if positive and number <= 0:
        raise ValueError("not positive")
    text = format(number.normalize(), "f")
    if text in ("-0", "-0.0"):
        text = "0"
    if len(text) > _MAX_DECIMAL_TEXT:
        raise ValueError("decimal too long")
    _whole, _dot, fraction = text.partition(".")
    if len(fraction) > _MAX_FRACTIONAL_DIGITS:
        raise ValueError("too many fractional digits")
    return text


def _difference_decimal(left, right):
    return _decimal(Decimal(left) - Decimal(right))


def _status_name(status):
    return _BT_STATUS_NAMES.get(status, Order.Status[status])


def _read_port(port, name):
    """Return a keyed reader for one injected port, or ``None`` if disabled."""
    if port is None:
        return None
    if isinstance(port, Mapping):
        return port.get
    if callable(port):
        return port
    method = getattr(port, name, None)
    if callable(method):
        return method
    raise ExecutionParentProjectionError("PORT_INVALID")


# ---------------------------------------------------------------------------
# public value objects
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OrderBinding:
    """The declared BT order intent; every field is caller-asserted, not a fact."""

    request_id: str
    bt_ref: int
    side: str
    offset: object
    quantity: str
    price: str
    parent_ref: object = None
    strategy_ref: object = None
    trading_day: object = None

    def payload(self):
        return {
            "request_id": self.request_id,
            "bt_ref": self.bt_ref,
            "side": self.side,
            "offset": self.offset,
            "quantity": self.quantity,
            "price": self.price,
            "parent_ref": self.parent_ref,
            "strategy_ref": self.strategy_ref,
            "trading_day": self.trading_day,
        }


@dataclass(frozen=True)
class ChildOrderFact:
    """One child plan/progress fact; it never changes the strategy order status."""

    child_id: str
    state: str
    reason_code: object
    quantity: str
    filled: str
    remaining: str
    reservation_id: object
    attempts: int
    unknown: bool
    bt_status: object = None
    affects_bt_status: bool = False

    def payload(self):
        return {
            "child_id": self.child_id,
            "state": self.state,
            "reason_code": self.reason_code,
            "quantity": self.quantity,
            "filled": self.filled,
            "remaining": self.remaining,
            "reservation_id": self.reservation_id,
            "attempts": self.attempts,
            "unknown": self.unknown,
            "bt_status": self.bt_status,
            "affects_bt_status": self.affects_bt_status,
        }


@dataclass(frozen=True)
class ParentOrderFact:
    """The parent projected onto one strategy order plus its child facts."""

    request_id: str
    parent_ref: object
    bt_ref: int
    side: str
    offset: object
    quantity: str
    price: str
    filled: str
    remaining: str
    bt_status: int
    bt_status_name: str
    state: object
    reason_code: object
    unknown: bool
    frozen: bool
    terminal: bool
    fills_known: bool
    children: tuple
    source: str = "EXECUTION_LOCAL_STATUS"

    def payload(self):
        return {
            "request_id": self.request_id,
            "parent_ref": self.parent_ref,
            "bt_ref": self.bt_ref,
            "side": self.side,
            "offset": self.offset,
            "quantity": self.quantity,
            "price": self.price,
            "filled": self.filled,
            "remaining": self.remaining,
            "bt_status": self.bt_status,
            "bt_status_name": self.bt_status_name,
            "state": self.state,
            "reason_code": self.reason_code,
            "unknown": self.unknown,
            "frozen": self.frozen,
            "terminal": self.terminal,
            "fills_known": self.fills_known,
            "children": [child.payload() for child in self.children],
            "source": self.source,
        }


@dataclass(frozen=True)
class PositionDelta:
    """One authorized venue fill as a signed position delta (never a plan)."""

    request_id: str
    child_id: str
    fill_id: str
    side: str
    offset: object
    quantity: str
    price: str
    trading_day: object
    exchange_trade_id: object
    delta_key: str

    def payload(self):
        return {
            "request_id": self.request_id,
            "child_id": self.child_id,
            "fill_id": self.fill_id,
            "side": self.side,
            "offset": self.offset,
            "quantity": self.quantity,
            "price": self.price,
            "trading_day": self.trading_day,
            "exchange_trade_id": self.exchange_trade_id,
            "delta_key": self.delta_key,
        }


@dataclass(frozen=True)
class ParentNotification:
    """One deterministic order notification for the wiring layer to deliver."""

    dedupe_key: str
    kind: str
    request_id: str
    bt_ref: int
    parent_ref: object
    state: object
    reason_code: object
    bt_status: int
    bt_status_name: str

    def payload(self):
        return {
            "dedupe_key": self.dedupe_key,
            "kind": self.kind,
            "request_id": self.request_id,
            "bt_ref": self.bt_ref,
            "parent_ref": self.parent_ref,
            "state": self.state,
            "reason_code": self.reason_code,
            "bt_status": self.bt_status,
            "bt_status_name": self.bt_status_name,
        }


@dataclass(frozen=True)
class ParentProjection:
    """The result of projecting one request at one point in time."""

    request_id: str
    parent_fact: object
    notifications: tuple
    position_deltas: tuple
    suppressed_notifications: int
    suppressed_fills: int
    refused: bool
    code: object
    fills_known: bool
    schema: str = SCHEMA

    def payload(self):
        return {
            "schema": self.schema,
            "request_id": self.request_id,
            "parent_fact": None if self.parent_fact is None else self.parent_fact.payload(),
            "notifications": [item.payload() for item in self.notifications],
            "position_deltas": [item.payload() for item in self.position_deltas],
            "suppressed_notifications": self.suppressed_notifications,
            "suppressed_fills": self.suppressed_fills,
            "refused": self.refused,
            "code": self.code,
            "fills_known": self.fills_known,
        }


@dataclass(frozen=True)
class ProjectionStatus:
    """A read-only, value-free view of the projection instance."""

    requests: int
    parents_projected: int
    children: int
    notifications_issued: int
    notifications_suppressed: int
    position_deltas_applied: int
    fills_suppressed: int
    refused: int
    conflicts: int
    unknown_facts: int
    restored: bool
    last_error_code: object
    schema: str = SCHEMA

    def payload(self):
        return MappingProxyType(
            {
                "schema": self.schema,
                "requests": self.requests,
                "parents_projected": self.parents_projected,
                "children": self.children,
                "notifications_issued": self.notifications_issued,
                "notifications_suppressed": self.notifications_suppressed,
                "position_deltas_applied": self.position_deltas_applied,
                "fills_suppressed": self.fills_suppressed,
                "refused": self.refused,
                "conflicts": self.conflicts,
                "unknown_facts": self.unknown_facts,
                "restored": self.restored,
                "last_error_code": self.last_error_code,
            }
        )


@dataclass(frozen=True)
class _ChildState:
    child_id: str
    state: str
    quantity: str
    reservation_id: object
    attempts: int
    last_error: object


@dataclass(frozen=True)
class _Status:
    parent_ref: object
    state: object
    request_sha256: object
    frozen: bool
    last_error: object
    children: tuple


@dataclass(frozen=True)
class _Fill:
    fill_id: str
    child_id: str
    quantity: str
    price: str
    side: object
    offset: object
    trading_day: object
    exchange_trade_id: object
    parent_ref: object
    digest: str


@dataclass(frozen=True)
class _Cancel:
    cancel_id: str
    outcome: str
    reason_code: object


@dataclass(frozen=True)
class _Completion:
    completion_id: str
    completed_quantity: str


@dataclass(frozen=True)
class _Composed:
    bt_status: int
    reason_code: object
    frozen: bool
    unknown: bool
    terminal: object
    state: object


# ---------------------------------------------------------------------------
# parsing (strict; no invented defaults)
# ---------------------------------------------------------------------------
def _request_id(value):
    text = _text(value)
    if text is None:
        raise ExecutionParentProjectionError("INVALID_REQUEST_ID")
    return text


def _parse_binding(request_id, raw):
    if raw is None:
        raise _Refusal("EXECUTION_BINDING_ABSENT")
    if not isinstance(raw, Mapping):
        raise _Refusal("EXECUTION_BINDING_INVALID")
    keys = frozenset(raw)
    if keys < _BINDING_REQUIRED or keys - (_BINDING_REQUIRED | _BINDING_OPTIONAL):
        raise _Refusal("EXECUTION_BINDING_INVALID")
    declared_request = raw.get("request_id")
    if declared_request is not None and declared_request != request_id:
        raise _Refusal("EXECUTION_IDENTITY_FOREIGN")
    try:
        bt_ref = raw["bt_ref"]
        if type(bt_ref) is not int or bt_ref < 1:
            raise ValueError
        side = raw["side"]
        if side not in SIDES:
            raise ValueError
        offset = raw["offset"]
        if offset is not None and offset not in OFFSETS:
            raise ValueError
        quantity = _decimal(raw["quantity"], positive=True)
        price = _decimal(raw["price"], positive=True)
        parent_ref = _optional_text(raw.get("parent_ref"))
        strategy_ref = _optional_text(raw.get("strategy_ref"))
        trading_day = raw.get("trading_day")
        if trading_day is not None and _day(trading_day) is None:
            raise ValueError
    except (TypeError, ValueError, ArithmeticError):
        raise _Refusal("EXECUTION_BINDING_INVALID") from None
    return OrderBinding(
        request_id=request_id,
        bt_ref=bt_ref,
        side=side,
        offset=offset,
        quantity=quantity,
        price=price,
        parent_ref=parent_ref,
        strategy_ref=strategy_ref,
        trading_day=trading_day,
    )


def _parse_child(raw):
    if not isinstance(raw, Mapping) or frozenset(raw) < _CHILD_REQUIRED:
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    child_id = _text(raw["child_id"])
    if child_id is None:
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    state = raw["state"]
    if state not in CHILD_STATES:
        raise _FactUnreadable("EXECUTION_CHILD_STATE_UNRECOGNIZED")
    try:
        quantity = _decimal(raw["quantity"], positive=True)
    except (TypeError, ValueError, ArithmeticError):
        raise _FactUnreadable("EXECUTION_CHILD_QUANTITY_INVALID") from None
    attempts = raw["attempts"]
    if type(attempts) is not int or attempts < 0:
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    reservation_id = _optional_text(raw["reservation_id"])
    if raw["reservation_id"] is not None and reservation_id is None:
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    last_error = _optional_text(raw["last_error"], _MAX_REASON_BYTES)
    if raw["last_error"] is not None and last_error is None:
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    return _ChildState(child_id, state, quantity, reservation_id, attempts, last_error)


def _parse_status(request_id, raw):
    """Return ``_Status`` or ``None`` for the committed missing-row shape."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or frozenset(raw) < _STATUS_REQUIRED:
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    if raw["request_id"] != request_id or _text(raw["request_id"]) is None:
        raise _Refusal("EXECUTION_IDENTITY_FOREIGN")
    if raw["state"] is None:
        return None
    if type(raw["state"]) is not str:
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    parent_ref = raw["parent_ref"]
    if parent_ref is not None and _text(parent_ref) is None:
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    request_sha256 = raw["request_sha256"]
    if request_sha256 is not None and (
        type(request_sha256) is not str or _HEX64.fullmatch(request_sha256) is None
    ):
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    if type(raw["frozen"]) is not bool:
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    last_error = _optional_text(raw["last_error"], _MAX_REASON_BYTES)
    if raw["last_error"] is not None and last_error is None:
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    attempts = raw["remote_attempts"]
    if type(attempts) is not int or attempts < 0:
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    children_raw = raw["children"]
    if not isinstance(children_raw, Sequence) or isinstance(children_raw, (str, bytes)):
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    if len(children_raw) > _MAX_CHILDREN:
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    children = []
    seen = set()
    for item in children_raw:
        child = _parse_child(item)
        if child.child_id in seen:
            raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
        seen.add(child.child_id)
        children.append(child)
    unknown_raw = raw["unknown_children"]
    if not isinstance(unknown_raw, Sequence) or isinstance(unknown_raw, (str, bytes)):
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    unknown_children = set()
    for item in unknown_raw:
        text = _text(item)
        if text is None:
            raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
        unknown_children.add(text)
    if unknown_children != {child.child_id for child in children if child.state == "UNKNOWN"}:
        raise _FactUnreadable("EXECUTION_STATUS_UNREADABLE")
    return _Status(
        parent_ref=parent_ref,
        state=raw["state"],
        request_sha256=request_sha256,
        frozen=raw["frozen"],
        last_error=last_error,
        children=tuple(children),
    )


def _parse_fill(raw):
    if not isinstance(raw, Mapping):
        raise _Refusal("FILL_FACT_INVALID")
    keys = frozenset(raw)
    if keys < _FILL_REQUIRED or keys - (_FILL_REQUIRED | _FILL_OPTIONAL):
        raise _Refusal("FILL_FACT_INVALID")
    fill_id = _text(raw["fill_id"])
    child_id = _text(raw["child_id"])
    source = raw["source"]
    if fill_id is None or child_id is None:
        raise _Refusal("FILL_FACT_INVALID")
    if source not in FILL_SOURCES:
        raise _Refusal("FILL_SOURCE_UNSUPPORTED")
    try:
        quantity = _decimal(raw["quantity"], positive=True)
        price = _decimal(raw["price"], positive=True)
    except (TypeError, ValueError, ArithmeticError):
        raise _Refusal("FILL_FACT_INVALID") from None
    side = raw.get("side")
    if side is not None and side not in SIDES:
        raise _Refusal("FILL_FACT_INVALID")
    offset = raw.get("offset")
    if offset is not None and offset not in OFFSETS:
        raise _Refusal("FILL_FACT_INVALID")
    trading_day = raw.get("trading_day")
    if trading_day is not None and _day(trading_day) is None:
        raise _Refusal("FILL_FACT_INVALID")
    exchange_trade_id = raw.get("exchange_trade_id")
    if exchange_trade_id is not None and _text(exchange_trade_id) is None:
        raise _Refusal("FILL_FACT_INVALID")
    parent_ref = raw.get("parent_ref")
    if parent_ref is not None and _text(parent_ref) is None:
        raise _Refusal("FILL_FACT_INVALID")
    content = [
        fill_id,
        child_id,
        quantity,
        price,
        source,
        side,
        offset,
        trading_day,
        exchange_trade_id,
        parent_ref,
    ]
    return _Fill(
        fill_id=fill_id,
        child_id=child_id,
        quantity=quantity,
        price=price,
        side=side,
        offset=offset,
        trading_day=trading_day,
        exchange_trade_id=exchange_trade_id,
        parent_ref=parent_ref,
        digest=_digest(SCHEMA, "fill", content),
    )


def _parse_cancel(raw):
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise _Refusal("CANCEL_FACT_INVALID")
    keys = frozenset(raw)
    if keys < _CANCEL_REQUIRED or keys - (_CANCEL_REQUIRED | _CANCEL_OPTIONAL):
        raise _Refusal("CANCEL_FACT_INVALID")
    cancel_id = _text(raw["cancel_id"])
    outcome = raw["outcome"]
    if cancel_id is None or outcome not in CANCEL_OUTCOMES:
        raise _Refusal("CANCEL_FACT_INVALID")
    reason_code = raw.get("reason_code")
    if reason_code is not None and reason_code not in CODES:
        raise _Refusal("CANCEL_FACT_INVALID")
    return _Cancel(cancel_id, outcome, reason_code)


def _parse_completion(raw):
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise _Refusal("COMPLETION_FACT_INVALID")
    keys = frozenset(raw)
    if keys < _COMPLETION_REQUIRED or keys - (_COMPLETION_REQUIRED | _COMPLETION_OPTIONAL):
        raise _Refusal("COMPLETION_FACT_INVALID")
    completion_id = _text(raw["completion_id"])
    try:
        completed_quantity = _decimal(raw["completed_quantity"], positive=True)
    except (TypeError, ValueError, ArithmeticError):
        raise _Refusal("COMPLETION_FACT_INVALID") from None
    if completion_id is None:
        raise _Refusal("COMPLETION_FACT_INVALID")
    return _Completion(completion_id, completed_quantity)


# ---------------------------------------------------------------------------
# entry helpers
# ---------------------------------------------------------------------------
def order_binding(
    order,
    request_id,
    *,
    offset=None,
    parent_ref=None,
    strategy_ref=None,
    trading_day=None,
):
    """Derive a declared binding from a real BT order; reads only.

    A first-phase Execution parent is limit-only (D65-07): an order without a
    finite positive price, or with a zero size, is refused with
    ``EXECUTION_BINDING_INVALID``.  This does not submit, accept or notify.
    """
    if not isinstance(order, OrderBase):
        raise ExecutionParentProjectionError("EXECUTION_BINDING_INVALID")
    text = _text(request_id)
    if text is None:
        raise ExecutionParentProjectionError("INVALID_REQUEST_ID")
    if offset is not None and offset not in OFFSETS:
        raise ExecutionParentProjectionError("EXECUTION_BINDING_INVALID")
    try:
        size = abs(order.size)
        if not size:
            raise ValueError
        quantity = _decimal(size, positive=True)
        price = _decimal(order.price, positive=True)
    except (TypeError, ValueError, ArithmeticError):
        raise ExecutionParentProjectionError("EXECUTION_BINDING_INVALID") from None
    binding = {
        "request_id": text,
        "bt_ref": order.ref,
        "side": "buy" if order.isbuy() else "sell",
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


def apply_position_delta(position, delta):
    """Apply one authorized fill delta to a real BT ``Position``.

    ``position.update`` returns ``(size, price, opened, closed)``.  The
    normalized decimal text is converted to ``float`` only for the framework
    object; the fact itself stays decimal text.
    """
    if not isinstance(position, Position) or not isinstance(delta, PositionDelta):
        raise ExecutionParentProjectionError("POSITION_DELTA_INVALID")
    return position.update(float(Decimal(delta.quantity)), float(Decimal(delta.price)))


# ---------------------------------------------------------------------------
# projection
# ---------------------------------------------------------------------------
def _empty_entry(binding):
    return {
        "binding": binding,
        "parent_ref": None,
        "request_sha256": None,
        "parent_state": None,
        "status_frozen": False,
        "last_error": None,
        "children": {},
        "fills": {},
        "fill_total": "0",
        "fill_children": {},
        "fills_known": False,
        "issued": set(),
        "projected": False,
        "accepted": False,
        "terminal": None,
        "bt_status": None,
        "frozen": False,
        "unknown": False,
        "reason_code": None,
        "cancel_id": None,
        "cancel_outcome": None,
        "completion_id": None,
        "completed_quantity": None,
    }


def _copy_entry(entry):
    copied = dict(entry)
    copied["children"] = {key: dict(value) for key, value in entry["children"].items()}
    copied["fills"] = dict(entry["fills"])
    copied["fill_children"] = dict(entry["fill_children"])
    copied["issued"] = set(entry["issued"])
    return copied


class _Missing:
    pass


class _Unreadable:
    pass


_MISSING = _Missing()
_UNREADABLE = _Unreadable()


class ExecutionParentProjection:
    """One read-only parent projection over injected fact ports.

    ``status_port`` and ``binding_port`` are required; ``fill_port``,
    ``cancel_port`` and ``completion_port`` are optional.  ``restore=`` accepts
    a :meth:`snapshot` value from a previous process so that a restart projects
    the same facts without a second notification or a second position delta.
    """

    def __init__(
        self,
        *,
        binding_port,
        status_port,
        fill_port=None,
        cancel_port=None,
        completion_port=None,
        restore=None,
    ):
        self._lock = threading.RLock()
        self._reads = {
            "binding": _read_port(binding_port, "binding"),
            "status": _read_port(status_port, "status"),
            "fills": _read_port(fill_port, "fills"),
            "cancel": _read_port(cancel_port, "cancel"),
            "completion": _read_port(completion_port, "completion"),
        }
        if self._reads["binding"] is None or self._reads["status"] is None:
            raise ExecutionParentProjectionError("PORT_INVALID")
        self._requests = {}
        self._child_owners = {}
        self._fill_owners = {}
        self._counters = {
            "parents_projected": 0,
            "notifications_issued": 0,
            "notifications_suppressed": 0,
            "position_deltas_applied": 0,
            "fills_suppressed": 0,
            "refused": 0,
            "conflicts": 0,
            "unknown_facts": 0,
        }
        self._last_error_code = None
        self._restored = False
        if restore is not None:
            self._load_restore(restore)

    # -- read-only views ---------------------------------------------------
    def projection_status(self):
        with self._lock:
            children = sum(len(entry["children"]) for entry in self._requests.values())
            return ProjectionStatus(
                requests=len(self._requests),
                parents_projected=self._counters["parents_projected"],
                children=children,
                notifications_issued=self._counters["notifications_issued"],
                notifications_suppressed=self._counters["notifications_suppressed"],
                position_deltas_applied=self._counters["position_deltas_applied"],
                fills_suppressed=self._counters["fills_suppressed"],
                refused=self._counters["refused"],
                conflicts=self._counters["conflicts"],
                unknown_facts=self._counters["unknown_facts"],
                restored=self._restored,
                last_error_code=self._last_error_code,
            )

    def snapshot(self):
        """Return a detached JSON-safe copy of the applied fact identities."""
        with self._lock:
            return {
                "schema": STATE_SCHEMA,
                "requests": {
                    request_id: self._entry_payload(entry)
                    for request_id, entry in sorted(self._requests.items())
                },
            }

    @staticmethod
    def _entry_payload(entry):
        return {
            "binding": entry["binding"].payload(),
            "parent_ref": entry["parent_ref"],
            "request_sha256": entry["request_sha256"],
            "parent_state": entry["parent_state"],
            "status_frozen": entry["status_frozen"],
            "last_error": entry["last_error"],
            "children": {
                child_id: {
                    "state": value["state"],
                    "quantity": value["quantity"],
                    "reservation_id": value["reservation_id"],
                    "attempts": value["attempts"],
                    "last_error": value["last_error"],
                }
                for child_id, value in sorted(entry["children"].items())
            },
            "fills": dict(sorted(entry["fills"].items())),
            "fill_total": entry["fill_total"],
            "fill_children": dict(sorted(entry["fill_children"].items())),
            "fills_known": entry["fills_known"],
            "issued": sorted(entry["issued"]),
            "projected": entry["projected"],
            "accepted": entry["accepted"],
            "terminal": entry["terminal"],
            "bt_status": entry["bt_status"],
            "frozen": entry["frozen"],
            "unknown": entry["unknown"],
            "reason_code": entry["reason_code"],
            "cancel_id": entry["cancel_id"],
            "cancel_outcome": entry["cancel_outcome"],
            "completion_id": entry["completion_id"],
            "completed_quantity": entry["completed_quantity"],
        }

    def _load_restore(self, restore):
        if not isinstance(restore, Mapping) or frozenset(restore) != {"schema", "requests"}:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        if restore["schema"] != STATE_SCHEMA:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        requests = restore["requests"]
        if not isinstance(requests, Mapping) or len(requests) > _MAX_REQUESTS:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        entries = {}
        child_owners = {}
        fill_owners = {}
        for raw_request, raw_entry in requests.items():
            request_id = _text(raw_request)
            if request_id is None or not isinstance(raw_entry, Mapping):
                raise ExecutionParentProjectionError("RESTORE_INVALID")
            if frozenset(raw_entry) != _ENTRY_FIELDS:
                raise ExecutionParentProjectionError("RESTORE_INVALID")
            entry = self._restore_entry(request_id, raw_entry)
            entries[request_id] = entry
            for child_id in entry["children"]:
                if child_id in child_owners:
                    raise ExecutionParentProjectionError("RESTORE_INVALID")
                child_owners[child_id] = request_id
            for fill_id, digest in entry["fills"].items():
                if fill_id in fill_owners:
                    raise ExecutionParentProjectionError("RESTORE_INVALID")
                fill_owners[fill_id] = (digest, request_id)
        self._requests = entries
        self._child_owners = child_owners
        self._fill_owners = fill_owners
        self._restored = True

    def _restore_entry(self, request_id, raw):
        try:
            binding = _parse_binding(request_id, raw["binding"])
        except _Refusal:
            raise ExecutionParentProjectionError("RESTORE_INVALID") from None
        entry = _empty_entry(binding)
        parent_ref = raw["parent_ref"]
        if parent_ref is not None and _text(parent_ref) is None:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        entry["parent_ref"] = parent_ref
        sha = raw["request_sha256"]
        if sha is not None and (type(sha) is not str or _HEX64.fullmatch(sha) is None):
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        entry["request_sha256"] = sha
        state = raw["parent_state"]
        if state is not None and state not in PARENT_STATES:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        entry["parent_state"] = state
        if type(raw["status_frozen"]) is not bool:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        entry["status_frozen"] = raw["status_frozen"]
        last_error = raw["last_error"]
        if last_error is not None and _text(last_error, _MAX_REASON_BYTES) is None:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        entry["last_error"] = last_error
        children = raw["children"]
        if not isinstance(children, Mapping) or len(children) > _MAX_CHILDREN:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        for child_id, value in children.items():
            if _text(child_id) is None or not isinstance(value, Mapping):
                raise ExecutionParentProjectionError("RESTORE_INVALID")
            if frozenset(value) != _CHILD_ENTRY_FIELDS:
                raise ExecutionParentProjectionError("RESTORE_INVALID")
            if value["state"] not in CHILD_STATES:
                raise ExecutionParentProjectionError("RESTORE_INVALID")
            try:
                quantity = _decimal(value["quantity"], positive=True)
            except (TypeError, ValueError, ArithmeticError):
                raise ExecutionParentProjectionError("RESTORE_INVALID") from None
            reservation_id = value["reservation_id"]
            if reservation_id is not None and _text(reservation_id) is None:
                raise ExecutionParentProjectionError("RESTORE_INVALID")
            attempts = value["attempts"]
            if type(attempts) is not int or attempts < 0:
                raise ExecutionParentProjectionError("RESTORE_INVALID")
            child_error = value["last_error"]
            if child_error is not None and _text(child_error, _MAX_REASON_BYTES) is None:
                raise ExecutionParentProjectionError("RESTORE_INVALID")
            entry["children"][child_id] = {
                "state": value["state"],
                "quantity": quantity,
                "reservation_id": reservation_id,
                "attempts": attempts,
                "last_error": child_error,
            }
        fills = raw["fills"]
        if not isinstance(fills, Mapping) or len(fills) > _MAX_FILLS:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        for fill_id, digest in fills.items():
            if (
                _text(fill_id) is None
                or type(digest) is not str
                or not digest.startswith(_DIGEST_PREFIX)
            ):
                raise ExecutionParentProjectionError("RESTORE_INVALID")
        entry["fills"] = dict(fills)
        try:
            entry["fill_total"] = _decimal(raw["fill_total"])
        except (TypeError, ValueError, ArithmeticError):
            raise ExecutionParentProjectionError("RESTORE_INVALID") from None
        fill_children = raw["fill_children"]
        if not isinstance(fill_children, Mapping):
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        for child_id, total in fill_children.items():
            if _text(child_id) is None:
                raise ExecutionParentProjectionError("RESTORE_INVALID")
            try:
                entry["fill_children"][child_id] = _decimal(total)
            except (TypeError, ValueError, ArithmeticError):
                raise ExecutionParentProjectionError("RESTORE_INVALID") from None
        if type(raw["fills_known"]) is not bool:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        entry["fills_known"] = raw["fills_known"]
        if entry["fills"] and not entry["fills_known"]:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        total = Decimal(entry["fill_total"])
        parts = sum((Decimal(value) for value in entry["fill_children"].values()), Decimal(0))
        if total != parts or total > Decimal(binding.quantity):
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        for child_id, value in entry["children"].items():
            if Decimal(entry["fill_children"].get(child_id, "0")) > Decimal(value["quantity"]):
                raise ExecutionParentProjectionError("RESTORE_INVALID")
        issued = raw["issued"]
        if not isinstance(issued, list) or len(issued) > _MAX_ISSUED:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        issued_keys = []
        for key in issued:
            if (
                type(key) is not str
                or not key.startswith(_DIGEST_PREFIX)
                or _HEX64.fullmatch(key[len(_DIGEST_PREFIX) :]) is None
            ):
                raise ExecutionParentProjectionError("RESTORE_INVALID")
            issued_keys.append(key)
        if len(set(issued_keys)) != len(issued_keys):
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        entry["issued"] = set(issued_keys)
        for name in ("projected", "accepted", "frozen", "unknown"):
            if type(raw[name]) is not bool:
                raise ExecutionParentProjectionError("RESTORE_INVALID")
            entry[name] = raw[name]
        terminal = raw["terminal"]
        if terminal not in (None, "REJECTED", "CANCELED", "COMPLETED"):
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        entry["terminal"] = terminal
        bt_status = raw["bt_status"]
        if bt_status is not None and bt_status not in _BT_STATUS_NAMES:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        entry["bt_status"] = bt_status
        reason_code = raw["reason_code"]
        if reason_code is not None and reason_code not in CODES:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        entry["reason_code"] = reason_code
        cancel_id = raw["cancel_id"]
        if cancel_id is not None and _text(cancel_id) is None:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        entry["cancel_id"] = cancel_id
        cancel_outcome = raw["cancel_outcome"]
        if cancel_outcome not in (None,) + CANCEL_OUTCOMES:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        entry["cancel_outcome"] = cancel_outcome
        completion_id = raw["completion_id"]
        if completion_id is not None and _text(completion_id) is None:
            raise ExecutionParentProjectionError("RESTORE_INVALID")
        entry["completion_id"] = completion_id
        completed = raw["completed_quantity"]
        if completed is not None:
            try:
                completed = _decimal(completed, positive=True)
            except (TypeError, ValueError, ArithmeticError):
                raise ExecutionParentProjectionError("RESTORE_INVALID") from None
        entry["completed_quantity"] = completed
        return entry

    # -- reading -----------------------------------------------------------
    def _read(self, name, request_id):
        reader = self._reads[name]
        if reader is None:
            return _MISSING
        try:
            return reader(request_id)
        except Exception:
            return _UNREADABLE

    # -- projection --------------------------------------------------------
    def project(self, request_id):
        """Project one request from the current injected facts."""
        text = _request_id(request_id)
        with self._lock:
            try:
                return self._project(text)
            except _Refusal as refusal:
                self._counters["refused"] += 1
                if refusal.code in _CONFLICT_CODES:
                    self._counters["conflicts"] += 1
                self._last_error_code = refusal.code
                prior = self._requests.get(text)
                fact = None
                if prior is not None and prior["bt_status"] is not None:
                    fact = self._fact_from_entry(prior)
                return ParentProjection(
                    request_id=text,
                    parent_fact=fact,
                    notifications=(),
                    position_deltas=(),
                    suppressed_notifications=0,
                    suppressed_fills=0,
                    refused=True,
                    code=refusal.code,
                    fills_known=prior["fills_known"] if prior is not None else False,
                )

    def _project(self, request_id):
        raw_binding = self._read("binding", request_id)
        if raw_binding is _UNREADABLE:
            raise _Refusal("PORT_UNREADABLE")
        if raw_binding is _MISSING:
            raise _Refusal("EXECUTION_BINDING_ABSENT")
        binding = _parse_binding(request_id, raw_binding)
        prior = self._requests.get(request_id)
        if prior is not None and prior["binding"] != binding:
            raise _Refusal("EXECUTION_BINDING_CONFLICT")
        entry = _copy_entry(prior) if prior is not None else _empty_entry(binding)

        status, status_code = self._read_status(request_id)
        if status is not None:
            self._check_identity(prior, status)
            self._check_children(request_id, prior, status)
        fills, fills_known, fill_code = self._read_fills(request_id)
        applied, deltas, suppressed_fills = self._apply_fills(
            request_id, binding, entry, status, fills, fills_known
        )
        cancel = self._read_cancel(request_id)
        completion = self._read_completion(request_id)

        effective_parent_ref = self._effective_parent_ref(entry, status)
        effective_sha = self._effective_sha(entry, status)
        entry["children"] = self._merge_children(entry, status)
        self._check_child_totals(entry)
        composed = self._compose(
            binding,
            entry,
            status,
            status_code,
            fills_known,
            fill_code,
            cancel,
            completion,
        )
        entry["parent_ref"] = effective_parent_ref
        entry["request_sha256"] = effective_sha
        # The cancel/completion identity must be visible to the dedupe keys, so
        # it is recorded before the notifications are derived.
        if cancel is not None:
            entry["cancel_id"] = cancel.cancel_id
            entry["cancel_outcome"] = cancel.outcome
        if completion is not None:
            entry["completion_id"] = completion.completion_id
            entry["completed_quantity"] = completion.completed_quantity
        notifications, suppressed = self._notifications(request_id, binding, entry, composed)

        entry["parent_state"] = composed.state
        entry["status_frozen"] = status.frozen if status is not None else entry["status_frozen"]
        entry["last_error"] = status.last_error if status is not None else entry["last_error"]
        entry["fills_known"] = fills_known
        entry["projected"] = True
        entry["bt_status"] = composed.bt_status
        entry["accepted"] = entry["accepted"] or composed.bt_status == Order.Accepted
        entry["terminal"] = composed.terminal
        entry["frozen"] = composed.frozen
        entry["unknown"] = composed.unknown
        entry["reason_code"] = composed.reason_code
        for item in notifications:
            entry["issued"].add(item.dedupe_key)

        self._requests[request_id] = entry
        for child_id in entry["children"]:
            self._child_owners[child_id] = request_id
        for fill in applied:
            self._fill_owners[fill.fill_id] = (fill.digest, request_id)
        self._counters["parents_projected"] += 1
        self._counters["notifications_issued"] += len(notifications)
        self._counters["notifications_suppressed"] += suppressed
        self._counters["position_deltas_applied"] += len(deltas)
        self._counters["fills_suppressed"] += suppressed_fills
        if composed.unknown:
            self._counters["unknown_facts"] += 1
        if composed.reason_code is not None:
            self._last_error_code = composed.reason_code
        fact = self._fact_from_entry(entry)
        return ParentProjection(
            request_id=request_id,
            parent_fact=fact,
            notifications=tuple(notifications),
            position_deltas=tuple(deltas),
            suppressed_notifications=suppressed,
            suppressed_fills=suppressed_fills,
            refused=False,
            code=composed.reason_code,
            fills_known=fills_known,
        )

    # -- identity and continuity ------------------------------------------
    @staticmethod
    def _check_identity(prior, status):
        if prior is None:
            return
        prior_ref = prior["parent_ref"]
        if prior_ref is not None and status.parent_ref not in (None, prior_ref):
            raise _Refusal("EXECUTION_IDENTITY_REGRESSED")
        prior_sha = prior["request_sha256"]
        if prior_sha is not None and status.request_sha256 not in (None, prior_sha):
            raise _Refusal("EXECUTION_IDENTITY_CONFLICT")
        prior_state = prior["parent_state"]
        if prior_state is not None and status.state not in PARENT_TRANSITIONS[prior_state]:
            raise _Refusal("EXECUTION_STATE_REGRESSED")

    def _check_children(self, request_id, prior, status):
        seen = set()
        for child in status.children:
            owner = self._child_owners.get(child.child_id)
            if owner is not None and owner != request_id:
                raise _Refusal("EXECUTION_CHILD_IDENTITY_FOREIGN")
            if child.child_id in seen:
                raise _Refusal("EXECUTION_CHILD_IDENTITY_FOREIGN")
            seen.add(child.child_id)
            prior_child = None if prior is None else prior["children"].get(child.child_id)
            if (
                prior_child is not None
                and child.state not in CHILD_TRANSITIONS[prior_child["state"]]
            ):
                raise _Refusal("EXECUTION_CHILD_STATE_REGRESSED")
        if prior is not None and set(prior["children"]) - seen:
            raise _Refusal("EXECUTION_CHILD_MISSING")

    @staticmethod
    def _effective_parent_ref(entry, status):
        if status is None or status.parent_ref is None:
            return entry["parent_ref"]
        return status.parent_ref

    @staticmethod
    def _effective_sha(entry, status):
        if status is None or status.request_sha256 is None:
            return entry["request_sha256"]
        return status.request_sha256

    # -- facts -------------------------------------------------------------
    def _read_status(self, request_id):
        raw = self._read("status", request_id)
        if raw is _UNREADABLE:
            return None, "EXECUTION_STATUS_UNREADABLE"
        if raw is _MISSING:
            return None, "EXECUTION_STATUS_ABSENT"
        try:
            status = _parse_status(request_id, raw)
        except _FactUnreadable as unreadable:
            return None, unreadable.code
        if status is None:
            return None, "EXECUTION_STATUS_ABSENT"
        return status, None

    def _read_fills(self, request_id):
        if self._reads["fills"] is None:
            return (), False, "FILL_PORT_UNAVAILABLE"
        raw = self._read("fills", request_id)
        if raw is _UNREADABLE or raw is _MISSING or raw is None:
            return (), False, "FILL_PORT_UNAVAILABLE"
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise _Refusal("FILL_FACT_INVALID")
        if len(raw) > _MAX_FILLS:
            raise _Refusal("FILL_FACT_INVALID")
        return tuple(_parse_fill(item) for item in raw), True, None

    def _read_cancel(self, request_id):
        if self._reads["cancel"] is None:
            return None
        raw = self._read("cancel", request_id)
        if raw is _UNREADABLE:
            raise _Refusal("PORT_UNREADABLE")
        if raw is _MISSING:
            return None
        return _parse_cancel(raw)

    def _read_completion(self, request_id):
        if self._reads["completion"] is None:
            return None
        raw = self._read("completion", request_id)
        if raw is _UNREADABLE:
            raise _Refusal("PORT_UNREADABLE")
        if raw is _MISSING:
            return None
        return _parse_completion(raw)

    def _apply_fills(self, request_id, binding, entry, status, fills, fills_known):
        """Validate every fill before anything is committed."""
        if not fills_known:
            return (), (), 0
        applied = []
        deltas = []
        suppressed = 0
        new_fills = dict(entry["fills"])
        new_total = Decimal(entry["fill_total"])
        child_totals = {key: Decimal(value) for key, value in entry["fill_children"].items()}
        child_quantity = {
            child.child_id: child.quantity for child in (status.children if status else ())
        }
        for child_id, value in entry["children"].items():
            child_quantity.setdefault(child_id, value["quantity"])
        expected_parent = binding.parent_ref or entry["parent_ref"]
        for fill in fills:
            if fill.fill_id in new_fills:
                if new_fills[fill.fill_id] != fill.digest:
                    raise _Refusal("FILL_FACT_CONFLICT")
                suppressed += 1
                continue
            owner = self._fill_owners.get(fill.fill_id)
            if owner is not None and owner[1] != request_id:
                raise _Refusal("FILL_FACT_FOREIGN")
            if fill.side is not None and fill.side != binding.side:
                raise _Refusal("FILL_SIDE_MISMATCH")
            if (
                fill.offset is not None
                and binding.offset is not None
                and fill.offset != binding.offset
            ):
                raise _Refusal("FILL_OFFSET_MISMATCH")
            if (
                fill.parent_ref is not None
                and expected_parent is not None
                and fill.parent_ref != expected_parent
            ):
                raise _Refusal("FILL_FACT_FOREIGN")
            if new_total + Decimal(fill.quantity) > Decimal(binding.quantity):
                raise _Refusal("FILL_QUANTITY_EXCEEDS_ORDER")
            if fill.child_id in child_quantity and (
                child_totals.get(fill.child_id, Decimal(0)) + Decimal(fill.quantity)
                > Decimal(child_quantity[fill.child_id])
            ):
                raise _Refusal("FILL_QUANTITY_EXCEEDS_CHILD")
            new_total += Decimal(fill.quantity)
            child_totals[fill.child_id] = child_totals.get(fill.child_id, Decimal(0)) + Decimal(
                fill.quantity
            )
            new_fills[fill.fill_id] = fill.digest
            applied.append(fill)
            deltas.append(
                PositionDelta(
                    request_id=request_id,
                    child_id=fill.child_id,
                    fill_id=fill.fill_id,
                    side=binding.side,
                    offset=fill.offset if fill.offset is not None else binding.offset,
                    quantity=fill.quantity if binding.side == "buy" else "-" + fill.quantity,
                    price=fill.price,
                    trading_day=fill.trading_day,
                    exchange_trade_id=fill.exchange_trade_id,
                    delta_key=_digest(SCHEMA, "delta", request_id, fill.fill_id, fill.digest),
                )
            )
        entry["fills"] = new_fills
        entry["fill_total"] = _decimal(new_total)
        entry["fill_children"] = {key: _decimal(value) for key, value in child_totals.items()}
        return applied, deltas, suppressed

    @staticmethod
    def _merge_children(entry, status):
        if status is None:
            return entry["children"]
        return {
            child.child_id: {
                "state": child.state,
                "quantity": child.quantity,
                "reservation_id": child.reservation_id,
                "attempts": child.attempts,
                "last_error": child.last_error,
            }
            for child in status.children
        }

    @staticmethod
    def _check_child_totals(entry):
        for child_id, total in entry["fill_children"].items():
            value = entry["children"].get(child_id)
            if value is not None and Decimal(total) > Decimal(value["quantity"]):
                raise _Refusal("FILL_QUANTITY_EXCEEDS_CHILD")

    # -- composition -------------------------------------------------------
    def _compose(
        self, binding, entry, status, status_code, fills_known, fill_code, cancel, completion
    ):
        # A missing status keeps the last provable execution state in the fact;
        # the fact itself becomes UNKNOWN, it does not invent a state.
        state = entry["parent_state"] if status is None else status.state
        children = entry["children"]
        unknown_children = tuple(
            sorted(child_id for child_id, value in children.items() if value["state"] == "UNKNOWN")
        )
        reason = None
        frozen = False
        unknown = False
        if status is not None and state is not None and state not in PARENT_STATES:
            reason = "EXECUTION_STATE_UNRECOGNIZED"
            frozen = True
            unknown = True
            state = None
        elif status is None:
            reason = status_code or "EXECUTION_STATUS_ABSENT"
            frozen = True
            unknown = True
        elif state == "UNKNOWN":
            reason = "EXECUTION_PARENT_UNKNOWN"
            frozen = True
            unknown = True
        elif unknown_children:
            reason = "EXECUTION_CHILD_UNKNOWN"
            frozen = True
            unknown = True
        elif status.frozen:
            reason = "EXECUTION_PARENT_FROZEN"
            frozen = True
            unknown = True
        elif state == "REJECTED":
            reason = self._reject_reason(status.last_error)
        if not fills_known and state != "REJECTED":
            # A rejected parent has no venue exposure; an unconfigured fill
            # source is irrelevant there.  Every other active parent without a
            # readable fill snapshot has an unknown strategy completion.
            unknown = True
            if reason is None:
                reason = fill_code or "FILL_PORT_UNAVAILABLE"

        terminal = entry["terminal"]
        if cancel is not None:
            if entry["cancel_id"] is not None and entry["cancel_id"] != cancel.cancel_id:
                raise _Refusal("CANCEL_FACT_CONFLICT")
            prior_outcome = entry["cancel_outcome"]
            if prior_outcome == cancel.outcome:
                cancel = None
            elif prior_outcome == "UNKNOWN" and cancel.outcome in ("CANCELED", "REJECTED"):
                pass
            elif prior_outcome is not None:
                raise _Refusal("CANCEL_FACT_CONFLICT")
        if completion is not None:
            if entry["completion_id"] is not None:
                if (
                    entry["completion_id"] != completion.completion_id
                    or entry["completed_quantity"] != completion.completed_quantity
                ):
                    raise _Refusal("COMPLETION_FACT_CONFLICT")
                completion = None

        bt_status = Order.Accepted if entry["accepted"] else Order.Submitted
        if terminal == "REJECTED":
            bt_status = Order.Rejected
        elif terminal == "CANCELED":
            bt_status = Order.Canceled
        elif terminal == "COMPLETED":
            bt_status = Order.Completed

        if completion is not None:
            if terminal is not None or state == "REJECTED":
                raise _Refusal("EXECUTION_TERMINAL_CONFLICT")
            if completion.completed_quantity != binding.quantity:
                raise _Refusal("COMPLETION_QUANTITY_MISMATCH")
            if status is None or unknown_children or not fills_known:
                raise _Refusal("COMPLETION_FACT_UNPROVABLE")
            terminal = "COMPLETED"
            bt_status = Order.Completed
            reason = None
            frozen = False
            unknown = False
        elif cancel is not None and cancel.outcome == "CANCELED":
            if terminal is not None or state == "REJECTED":
                raise _Refusal("EXECUTION_TERMINAL_CONFLICT")
            if status is None or unknown_children or not fills_known:
                reason = "CANCEL_UNRESOLVED_CHILDREN"
                unknown = True
            else:
                terminal = "CANCELED"
                bt_status = Order.Canceled
                reason = None
                frozen = False
                unknown = False
        elif state == "REJECTED":
            if children:
                raise _Refusal("EXECUTION_REJECTED_WITH_CHILDREN")
            if terminal is None:
                terminal = "REJECTED"
                frozen = False
                unknown = False
            bt_status = Order.Rejected
        # A cancel outcome annotates an active parent; it never pre-empts the
        # state mapping of a rejected parent.
        if terminal is None and cancel is not None and cancel.outcome == "UNKNOWN":
            reason = "CANCEL_OUTCOME_UNKNOWN"
            unknown = True
        elif terminal is None and cancel is not None and cancel.outcome == "REJECTED":
            reason = cancel.reason_code or "CANCEL_REJECTED"

        if terminal is not None:
            # A settled parent is not re-opened by a later missing, unreadable,
            # frozen or cancel read: the terminal fact stands.  A late cancel
            # fact never changes a rejected parent's reason.
            frozen = False
            unknown = False
            reason = "EXECUTION_REMOTE_REJECTED" if terminal == "REJECTED" else None
        if state == "ACCEPTED" and terminal is None:
            bt_status = Order.Accepted
        if entry["accepted"] and bt_status in (Order.Submitted, Order.Accepted):
            bt_status = Order.Accepted
        return _Composed(
            bt_status=bt_status,
            reason_code=reason,
            frozen=frozen,
            unknown=unknown,
            terminal=terminal,
            state=state,
        )

    @staticmethod
    def _reject_reason(last_error):
        mapped = {
            "remote_rejected": "EXECUTION_REMOTE_REJECTED",
            "parent_outcome_unknown": "EXECUTION_PARENT_UNKNOWN",
            "child_outcome_unknown": "EXECUTION_CHILD_UNKNOWN",
        }
        if last_error is None:
            return "EXECUTION_REMOTE_REJECTED"
        return mapped.get(last_error, "EXECUTION_REMOTE_REJECTED")

    # -- notifications -----------------------------------------------------
    @staticmethod
    def _notifications(request_id, binding, entry, composed):
        issued = entry["issued"]
        out = []
        suppressed = 0

        def add(kind, key, reason_code):
            nonlocal suppressed
            if key in issued:
                suppressed += 1
                return
            out.append(
                ParentNotification(
                    dedupe_key=key,
                    kind=kind,
                    request_id=request_id,
                    bt_ref=binding.bt_ref,
                    parent_ref=entry["parent_ref"],
                    state=composed.state,
                    reason_code=reason_code,
                    bt_status=composed.bt_status,
                    bt_status_name=_status_name(composed.bt_status),
                )
            )
            issued.add(key)

        add("submitted", _digest(SCHEMA, "notification", "submitted", request_id), None)
        if composed.state == "ACCEPTED":
            add("accepted", _digest(SCHEMA, "notification", "accepted", request_id), None)
        if composed.terminal == "REJECTED":
            add(
                "rejected",
                _digest(SCHEMA, "notification", "rejected", request_id, entry["request_sha256"]),
                composed.reason_code,
            )
        elif composed.terminal == "CANCELED":
            add(
                "canceled",
                _digest(SCHEMA, "notification", "canceled", request_id, entry["cancel_id"]),
                None,
            )
        elif composed.terminal == "COMPLETED":
            add(
                "completed",
                _digest(SCHEMA, "notification", "completed", request_id, entry["completion_id"]),
                None,
            )
        if composed.terminal is None and composed.unknown:
            add(
                "unknown",
                _digest(SCHEMA, "notification", "unknown", request_id, composed.reason_code),
                composed.reason_code,
            )
        return out, suppressed

    # -- facts from stored state ------------------------------------------
    def _fact_from_entry(self, entry):
        binding = entry["binding"]
        children = tuple(
            ChildOrderFact(
                child_id=child_id,
                state=value["state"],
                reason_code=self._child_reason(value),
                quantity=value["quantity"],
                filled=entry["fill_children"].get(child_id, "0"),
                remaining=_difference_decimal(
                    value["quantity"], entry["fill_children"].get(child_id, "0")
                ),
                reservation_id=value["reservation_id"],
                attempts=value["attempts"],
                unknown=value["state"] == "UNKNOWN",
            )
            for child_id, value in sorted(entry["children"].items())
        )
        status = entry["bt_status"] if entry["bt_status"] is not None else Order.Submitted
        return ParentOrderFact(
            request_id=binding.request_id,
            parent_ref=entry["parent_ref"],
            bt_ref=binding.bt_ref,
            side=binding.side,
            offset=binding.offset,
            quantity=binding.quantity,
            price=binding.price,
            filled=entry["fill_total"],
            remaining=_difference_decimal(binding.quantity, entry["fill_total"]),
            bt_status=status,
            bt_status_name=_status_name(status),
            state=entry["parent_state"],
            reason_code=entry["reason_code"],
            unknown=entry["unknown"],
            frozen=entry["frozen"],
            terminal=entry["terminal"] is not None,
            fills_known=entry["fills_known"],
            children=children,
        )

    @staticmethod
    def _child_reason(value):
        if value["state"] == "UNKNOWN":
            return "EXECUTION_CHILD_UNKNOWN"
        if value["state"] == "REJECTED":
            return ExecutionParentProjection._reject_reason(value["last_error"])
        return None


__all__ = (
    "CHILD_STATES",
    "CODES",
    "ChildOrderFact",
    "ExecutionParentProjection",
    "ExecutionParentProjectionError",
    "NOTIFICATION_KINDS",
    "OrderBinding",
    "PARENT_STATES",
    "ParentNotification",
    "ParentOrderFact",
    "ParentProjection",
    "PositionDelta",
    "ProjectionStatus",
    "SCHEMA",
    "STATE_SCHEMA",
    "apply_position_delta",
    "order_binding",
)
