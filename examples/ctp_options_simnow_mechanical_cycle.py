"""Injected, fail-closed mechanical open/close cycle for Iterations 23-25.

This module is an execution state machine, not a client or a strategy.  It
accepts a caller-owned Backtrader broker and feeds and reaches the native
boundary only through ``broker.buy``, ``broker.sell`` and ``broker.cancel``.
No Store private fields, credentials, API objects, account queries or network
operations are used here.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

import backtrader as bt


class MechanicalCycleBlocked(RuntimeError):
    """A required proof, identity or native callback is missing or unsafe."""


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MechanicalCycleBlocked(f"{name}_MISSING")
    return value.strip()


def _identity(value: Mapping[str, Any], name: str = "identity") -> tuple[str, str, int]:
    account = _text(value.get("account_fingerprint"), f"{name}.account_fingerprint")
    trading_day = _text(value.get("trading_day"), f"{name}.trading_day")
    generation = value.get("connection_generation", value.get("generation"))
    if type(generation) is not int or generation <= 0:
        raise MechanicalCycleBlocked(f"{name}.connection_generation_INVALID")
    return account, trading_day, generation


def _strict_snapshot(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MechanicalCycleBlocked(f"{name}_SCHEMA_INVALID")
    snapshot = dict(value)
    required = (
        "evidence_complete",
        "read_only_safe",
        "write_request_free",
        "account_fingerprint",
        "trading_day",
        "connection_generation",
        "flat",
        "active_order_count",
        "unknown_intent_count",
        "unmatched_trade_count",
    )
    missing = [key for key in required if key not in snapshot]
    if missing:
        raise MechanicalCycleBlocked(f"{name}_SCHEMA_INCOMPLETE:{','.join(missing)}")
    if any(
        snapshot[key] is not True
        for key in ("evidence_complete", "read_only_safe", "write_request_free", "flat")
    ):
        raise MechanicalCycleBlocked(f"{name}_NOT_SAFE_OR_FLAT")
    if any(
        snapshot[key] != 0
        for key in ("active_order_count", "unknown_intent_count", "unmatched_trade_count")
    ):
        raise MechanicalCycleBlocked(f"{name}_NONFLAT_OR_UNKNOWN")
    _identity(snapshot, name)
    return snapshot


def _semantic_hash(snapshot: Mapping[str, Any]) -> str:
    return _hash(
        {
            key: snapshot[key]
            for key in (
                "account_fingerprint",
                "trading_day",
                "connection_generation",
                "flat",
                "active_order_count",
                "unknown_intent_count",
                "unmatched_trade_count",
            )
        }
        | {
            "positions": snapshot.get("nonzero_positions", snapshot.get("positions", [])),
            "active_orders": snapshot.get("active_orders", []),
        }
    )


@dataclass(frozen=True)
class MechanicalLeg:
    symbol: str
    side: str
    price: float
    data: Any
    position_side: str = "long"

    def __post_init__(self) -> None:
        _text(self.symbol, "leg.symbol")
        if self.side not in {"buy", "sell"}:
            raise MechanicalCycleBlocked("leg.side_INVALID")
        if not math.isfinite(float(self.price)) or float(self.price) <= 0:
            raise MechanicalCycleBlocked("leg.price_INVALID")


class MechanicalCycle:
    """A single bounded cycle with one pending Backtrader order at a time."""

    def __init__(
        self,
        *,
        broker: Any,
        owner: Any,
        feeds: Mapping[str, Any],
        cycle_id: str,
        budget_capability: Any = None,
    ):
        if not callable(getattr(broker, "buy", None)) or not callable(
            getattr(broker, "sell", None)
        ):
            raise MechanicalCycleBlocked("BROKER_PUBLIC_ORDER_INTERFACE_REQUIRED")
        if not callable(getattr(broker, "cancel", None)):
            raise MechanicalCycleBlocked("BROKER_PUBLIC_CANCEL_INTERFACE_REQUIRED")
        self.broker = broker
        self.owner = owner
        self.feeds = dict(feeds)
        self.cycle_id = _text(cycle_id, "cycle_id")
        self.budget_capability = budget_capability
        self.state = "DISARMED"
        self.phase: str | None = None
        self.pending_order: Any = None
        self.pending_leg: MechanicalLeg | None = None
        self.pending_intent_id: str | None = None
        self.planned_legs: list[MechanicalLeg] = []
        self._entry_legs: tuple[MechanicalLeg, ...] = ()
        self.completed_legs: list[MechanicalLeg] = []
        self._journal: list[dict[str, Any]] = []
        self._identity: tuple[str, str, int] | None = None
        self._entry_proof_hash: str | None = None
        self._exit_planned = False
        self._bound_orders: dict[Any, dict[str, str]] = {}
        self._cancel_requested_refs: set[Any] = set()

    @property
    def journal(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._journal)

    def _record(self, status: str, *, intent_id: str | None = None, order: Any = None) -> None:
        row = {"cycle_id": self.cycle_id, "status": status}
        if intent_id:
            row["intent_id_hash"] = _hash(intent_id)
        if order is not None and getattr(order, "ref", None) is not None:
            row["bt_ref_hash"] = _hash(str(order.ref))
        self._journal.append(row)

    def arm(self, proof: Mapping[str, Any]) -> None:
        if self.state != "DISARMED":
            raise MechanicalCycleBlocked("CYCLE_ALREADY_ARMED_OR_STARTED")
        if not isinstance(proof, Mapping) or proof.get("settlement_verified") is not True:
            raise MechanicalCycleBlocked("SETTLEMENT_PROOF_REQUIRED")
        bundle = _strict_snapshot(proof.get("bundle_preflight"), "BUNDLE_PREFLIGHT")
        reconciliation_rounds = proof.get("reconciliation_rounds")
        if not isinstance(reconciliation_rounds, (list, tuple)) or len(reconciliation_rounds) != 2:
            raise MechanicalCycleBlocked("TWO_ROUND_RECONCILIATION_REQUIRED")
        first_reconciliation = _strict_snapshot(reconciliation_rounds[0], "RECONCILIATION")
        second_reconciliation = _strict_snapshot(reconciliation_rounds[1], "RECONCILIATION")
        if _identity(first_reconciliation, "reconciliation") != _identity(
            second_reconciliation, "reconciliation"
        ):
            raise MechanicalCycleBlocked("RECONCILIATION_IDENTITY_MISMATCH")
        expected_hashes = (
            _semantic_hash(first_reconciliation),
            _semantic_hash(second_reconciliation),
        )
        if expected_hashes[0] != expected_hashes[1]:
            raise MechanicalCycleBlocked("RECONCILIATION_SEMANTIC_HASH_REQUIRED")
        supplied_hashes = proof.get("reconciliation_semantic_hashes")
        if supplied_hashes is not None and tuple(supplied_hashes) != expected_hashes:
            raise MechanicalCycleBlocked("RECONCILIATION_SEMANTIC_HASH_MISMATCH")
        if _identity(bundle, "bundle") != _identity(first_reconciliation, "reconciliation"):
            raise MechanicalCycleBlocked("PROOF_IDENTITY_MISMATCH")
        authorization = proof.get("execution_authorization")
        if not isinstance(authorization, Mapping) or authorization.get("armed") is not True:
            raise MechanicalCycleBlocked("EXECUTION_ARMING_PROOF_REQUIRED")
        if (
            authorization.get("account_fingerprint") != bundle["account_fingerprint"]
            or authorization.get("connection_generation") != bundle["connection_generation"]
        ):
            raise MechanicalCycleBlocked("ARMING_IDENTITY_MISMATCH")
        self._identity = _identity(bundle, "bundle")
        self._entry_proof_hash = _hash(
            {"bundle": _semantic_hash(bundle), "reconciliation": expected_hashes}
        )
        self.state = "ARMED"
        self._record("ARMED")

    def plan_entry(self, legs: list[MechanicalLeg], *, intent_id: str) -> None:
        if self.state != "ARMED":
            raise MechanicalCycleBlocked("CYCLE_NOT_ARMED")
        if self.planned_legs or not 1 <= len(legs) <= 3:
            raise MechanicalCycleBlocked("ONE_ENTRY_PLAN_ONLY")
        if len({leg.symbol for leg in legs}) != len(legs):
            raise MechanicalCycleBlocked("DUPLICATE_LEG")
        if _text(intent_id, "intent_id") != intent_id:
            raise MechanicalCycleBlocked("intent_id_INVALID")
        self.planned_legs = list(legs)
        self._entry_legs = tuple(legs)
        self.phase = "OPEN"
        self.pending_intent_id = intent_id
        self._record("ENTRY_PLANNED", intent_id=intent_id)

    def _submit(self, leg: MechanicalLeg, *, intent_id: str, offset: str) -> Any:
        allowed_states = {"ARMED", "OPENING"} if offset == "open" else {"OPEN", "CLOSING"}
        if self.state not in allowed_states or self.pending_order is not None:
            raise MechanicalCycleBlocked("EXACTLY_ONE_PENDING_ORDER_REQUIRED")
        if offset not in {"open", "close"}:
            raise MechanicalCycleBlocked("OFFSET_INVALID")
        data = self.feeds.get(leg.symbol, leg.data)
        method = self.broker.buy if leg.side == "buy" else self.broker.sell
        self.pending_intent_id = intent_id
        self.pending_leg = leg
        self.state = "OPENING" if offset == "open" else "CLOSING"
        order_kwargs = {
            "owner": self.owner,
            "data": data,
            "size": 1,
            "price": float(leg.price),
            "exectype": bt.Order.Limit,
            "offset": offset,
            "position_side": leg.position_side,
            "execution_cycle_id": self.cycle_id,
            "intent_id": intent_id,
            "mechanical_proof_hash": self._entry_proof_hash,
        }
        if self.budget_capability is not None:
            # The SDK's managed write path requires the caller's opaque
            # budget reservation on every leg of the cycle.
            order_kwargs["budget_capability"] = self.budget_capability
        order = method(**order_kwargs)
        if order is None:
            self._halt("ORDER_SUBMISSION_RETURNED_NONE")
            raise MechanicalCycleBlocked("ORDER_SUBMISSION_RETURNED_NONE")
        self.pending_order = order
        self._bound_orders[getattr(order, "ref", id(order))] = {
            "cycle_id": self.cycle_id,
            "intent_id": intent_id,
        }
        self._record("ORDER_SUBMITTED", intent_id=intent_id, order=order)
        return order

    def submit_next_entry(self) -> Any:
        if self.phase != "OPEN" or not self.planned_legs:
            raise MechanicalCycleBlocked("ENTRY_PLAN_REQUIRED")
        index = len(self.completed_legs)
        if index >= len(self.planned_legs):
            raise MechanicalCycleBlocked("ENTRY_ALREADY_COMPLETE")
        return self._submit(
            self.planned_legs[index],
            intent_id=f"{self.pending_intent_id}:open:{index}",
            offset="open",
        )

    def _native_fields(self, order: Any) -> dict[str, Any]:
        info = getattr(order, "info", None)
        result = {}
        aliases = {
            "orderref": ("ctp_order_ref", "order_ref", "OrderRef", "orderref"),
            "frontid": ("front_id", "FrontID", "frontid"),
            "sessionid": ("session_id", "SessionID", "sessionid"),
            "ordersysid": ("external_order_id", "order_sys_id", "OrderSysID", "ordersysid"),
            "tradeid": ("trade_id", "TradeID", "tradeid"),
            "connection_generation": ("connection_generation", "generation"),
        }
        for canonical, names in aliases.items():
            value = None
            for key in names:
                value = getattr(order, key, None)
                if value not in (None, ""):
                    break
                if info is not None:
                    value = getattr(info, key, None)
                    if value in (None, "") and hasattr(info, "get"):
                        value = info.get(key)
                    if value not in (None, ""):
                        break
            if value not in (None, ""):
                result[canonical] = value
        return result

    def _order_info(self, order: Any, key: str) -> Any:
        value = getattr(order, key, None)
        info = getattr(order, "info", None)
        if value in (None, "") and info is not None:
            value = getattr(info, key, None)
            if value in (None, "") and hasattr(info, "get"):
                value = info.get(key)
        return value

    @staticmethod
    def _status_name(order: Any) -> str:
        getter = getattr(order, "getstatusname", None)
        if callable(getter):
            value = getter()
            if isinstance(value, str):
                return value.casefold()
        value = getattr(order, "status", "")
        return value.casefold() if isinstance(value, str) else ""

    def _halt(self, reason: str) -> None:
        self.state = "RECOVERY_REQUIRED"
        self._record(reason, intent_id=self.pending_intent_id, order=self.pending_order)

    def on_order_update(self, order: Any) -> None:
        if (
            self.pending_order is None
            or order is not self.pending_order
            and getattr(order, "ref", None) != getattr(self.pending_order, "ref", None)
        ):
            self._halt("FOREIGN_ORDER_UPDATE")
            raise MechanicalCycleBlocked("FOREIGN_ORDER_UPDATE")
        status = self._status_name(order)
        if status in {"partial", "partial_fill", "unknown", "pending_cancel"}:
            self._halt("PARTIAL_OR_UNKNOWN_FILL")
            raise MechanicalCycleBlocked("PARTIAL_OR_UNKNOWN_FILL")
        if status in {"canceled", "cancelled", "rejected", "expired"}:
            self._halt("ORDER_TERMINAL_WITHOUT_NATIVE_FILL")
            raise MechanicalCycleBlocked("ORDER_TERMINAL_WITHOUT_NATIVE_FILL")
        if status not in {"completed", "filled", "fill"}:
            self._halt("UNRECOGNIZED_ORDER_STATUS")
            raise MechanicalCycleBlocked("UNRECOGNIZED_ORDER_STATUS")
        fields = self._native_fields(order)
        required = (
            "orderref",
            "frontid",
            "sessionid",
            "ordersysid",
            "tradeid",
            "connection_generation",
        )
        binding = self._bound_orders.get(getattr(order, "ref", id(order)), {})
        fill_source = self._order_info(order, "execution_fill_source")
        if (
            any(key not in fields for key in required)
            or fill_source not in {"trade", "cumulative"}
            or binding.get("cycle_id") != self._order_info(order, "execution_cycle_id")
            or binding.get("intent_id") != self._order_info(order, "intent_id")
        ):
            self._halt("NATIVE_FILL_IDENTITY_INCOMPLETE")
            raise MechanicalCycleBlocked("NATIVE_FILL_IDENTITY_INCOMPLETE")
        if getattr(order, "ref", None) in self._cancel_requested_refs:
            self._halt("LATE_FILL_AFTER_CANCEL")
            raise MechanicalCycleBlocked("LATE_FILL_AFTER_CANCEL")
        if self._identity and int(fields["connection_generation"]) != self._identity[2]:
            self._halt("FILL_GENERATION_MISMATCH")
            raise MechanicalCycleBlocked("FILL_GENERATION_MISMATCH")
        leg = self.pending_leg
        self.pending_order = None
        self.pending_leg = None
        self.completed_legs.append(leg)
        self._record("NATIVE_FILL_CONFIRMED", intent_id=self.pending_intent_id, order=order)
        if self.phase == "OPEN" and len(self.completed_legs) < len(self.planned_legs):
            self.state = "ARMED"
        elif self.phase == "OPEN":
            self.state = "OPEN"
        elif self.phase == "CLOSE":
            self.state = (
                "CLOSE_FILLED" if len(self.completed_legs) == len(self.planned_legs) else "CLOSING"
            )

    def plan_exit(self, legs: list[MechanicalLeg], *, intent_id: str) -> None:
        if self.state != "OPEN" or len(self.completed_legs) != len(self._entry_legs):
            raise MechanicalCycleBlocked("EXIT_REQUIRES_NATIVE_OPEN_FILLS")
        if len(legs) != len(self._entry_legs):
            raise MechanicalCycleBlocked("EXIT_PLAN_MUST_COVER_ENTRY_LEGS")
        if any(
            supplied.symbol != entry.symbol
            or supplied.position_side != entry.position_side
            or supplied.side != ("sell" if entry.side == "buy" else "buy")
            for supplied, entry in zip(legs, self._entry_legs)
        ):
            raise MechanicalCycleBlocked("EXIT_PLAN_NOT_EQUIVALENT_TO_ENTRY")
        self.planned_legs = [
            MechanicalLeg(
                entry.symbol,
                "sell" if entry.side == "buy" else "buy",
                supplied.price,
                supplied.data,
                entry.position_side,
            )
            for supplied, entry in zip(legs, self._entry_legs)
        ]
        self.phase = "CLOSE"
        self._exit_planned = True
        self.completed_legs = []
        self.pending_intent_id = intent_id
        self._record("EXIT_PLANNED", intent_id=intent_id)

    def submit_next_exit(self) -> Any:
        if self.phase != "CLOSE" or not self._exit_planned:
            raise MechanicalCycleBlocked("EXIT_PLAN_REQUIRED")
        index = len(self.completed_legs)
        if index >= len(self.planned_legs):
            raise MechanicalCycleBlocked("EXIT_ALREADY_COMPLETE")
        return self._submit(
            self.planned_legs[index],
            intent_id=f"{self.pending_intent_id}:close:{index}",
            offset="close",
        )

    def cancel_pending(self) -> Any:
        if self.pending_order is None:
            raise MechanicalCycleBlocked("NO_PENDING_ORDER")
        order = self.broker.cancel(self.pending_order)
        self._record("CANCEL_REQUESTED", intent_id=self.pending_intent_id, order=self.pending_order)
        self._cancel_requested_refs.add(getattr(self.pending_order, "ref", id(self.pending_order)))
        return order

    def timeout(self) -> None:
        self._halt("TIMEOUT_RECOVERY_REQUIRED")
        raise MechanicalCycleBlocked("TIMEOUT_RECOVERY_REQUIRED")

    def reconnect(self, generation: int) -> None:
        if self._identity is None or generation != self._identity[2]:
            self._halt("RECONNECT_GENERATION_CHANGED")
            raise MechanicalCycleBlocked("RECONNECT_GENERATION_CHANGED")
        self._halt("RECONNECT_REQUIRES_REARM")
        raise MechanicalCycleBlocked("RECONNECT_REQUIRES_REARM")

    def finalize_flat(self, first: Mapping[str, Any], second: Mapping[str, Any]) -> None:
        if (
            self.phase != "CLOSE"
            or self.state != "CLOSE_FILLED"
            or self.pending_order is not None
            or len(self.completed_legs) != len(self.planned_legs)
        ):
            raise MechanicalCycleBlocked("CLOSE_FILLS_NOT_COMPLETE")
        left = _strict_snapshot(first, "FINAL_RECONCILIATION")
        right = _strict_snapshot(second, "FINAL_RECONCILIATION")
        if _identity(left) != _identity(right) or _semantic_hash(left) != _semantic_hash(right):
            raise MechanicalCycleBlocked("FINAL_RECONCILIATION_NOT_STABLE")
        if self._identity and _identity(left) != self._identity:
            raise MechanicalCycleBlocked("FINAL_RECONCILIATION_IDENTITY_MISMATCH")
        self.state = "CLOSED_FLAT"
        self._record("CLOSED_FLAT")
