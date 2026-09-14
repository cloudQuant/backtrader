"""Fail-closed SimNow adapter for the Iteration 24 engineering smoke path.

This module is deliberately an adapter, not a CTP client.  It accepts an
already-created SDK object from a caller and never reads credentials or
``.env`` files.  The normal command-line example therefore remains offline.
External ACKs/fills are evidence supplied by the transport; this module never
creates synthetic fills.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Optional

import backtrader as bt
from backtrader.feeds import BarEvidence, ClockMapping
from backtrader.stores.btapistore import BtApiStore


class EngineeringSmokeBlocked(RuntimeError):
    """A missing safety prerequisite; no external action was attempted."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# This intentionally names the only allowed Set-2 profile rather than letting
# an injected client silently repurpose a first-set account.  The adapter never
# resolves the profile itself: the caller owns SDK construction and credentials.
SECOND_SET_ENGINEERING_PROFILE = "simnow_second_7x24"
ENGINEERING_OBSERVATION_MAX_SECONDS = 3600.0
ENGINEERING_OBSERVATION_G3_STATUS = "NOT_RUN_ENGINEERING_STRATEGY_OBSERVATION"
# The operator label is only an admission request.  The public SDK state must
# independently prove a concrete route in this second-set profile family.
SECOND_SET_SESSION_PROFILE_PREFIX = "set2_7x24"
_ADAPTER_SCOPED_WRITE_EVIDENCE_BOUNDARY = (
    "NOT_PROVEN: the adapter membrane and market_data_only Broker only observe "
    "adapter-routed attempts; they cannot attest raw external provider writes."
)


class _ObservationReadOnlyApi:
    """A deny-by-default write membrane around a caller-owned SDK object.

    The underlying object remains owned by the caller.  The membrane does not
    attempt to infer credentials or configure a trading session; it only
    permits one idempotent, narrowing configuration transition
    (``market_data_only=True``) when a managed SDK requires that transition at
    Store startup.  Every order, cancel, settlement and authorization-shaped
    entry point fails before it can reach the injected API.
    """

    _FORBIDDEN_METHODS = frozenset(
        {
            "submit_order",
            "make_order",
            "async_make_order",
            "place_order",
            "create_order",
            "send_order",
            "order_insert",
            "req_order_insert",
            "ReqOrderInsert",
            "cancel_order",
            "async_cancel_order",
            "order_action",
            "req_order_action",
            "ReqOrderAction",
            "settlement_confirm",
            "confirm_settlement",
            "confirm_ctp_settlement",
            "prepare_settlement",
            "prepare_ctp_settlement",
            "prepare_execution_authorization",
            "configure_ctp_execution_authorization",
            "configure_execution_authorization",
            "arm_execution",
            "arm_sdk_execution",
            "arm_execution_recovery",
            "complete_execution_recovery",
            "prepare_execution_recovery",
            "abort_execution_recovery",
            "enable_execution",
            "enable_trading",
            "disarm_execution",
            "arm_execution_from_preflight",
            "arm_execution_from_approval",
            "confirm_ctp_settlement_from_approval",
        }
    )
    _SAFE_READ_PREFIXES = (
        "get_",
        "query_",
        "list_",
        "fetch_",
        "poll_",
        "read_",
        "is_",
        "has_",
        "iter_",
        "supports_",
        "async_get_",
        "async_query_",
        "async_list_",
        "async_fetch_",
        "async_poll_",
    )
    _SAFE_READ_METHODS = frozenset({"get_ctp_session_state"})
    _SAFE_LIFECYCLE_METHODS = frozenset(
        {"connect", "disconnect", "close", "start", "stop", "subscribe", "unsubscribe"}
    )
    _FORBIDDEN_METHODS_NORMALIZED = frozenset(method.lower() for method in _FORBIDDEN_METHODS)

    def __init__(self, api: Any) -> None:
        if api is None:
            raise EngineeringSmokeBlocked(
                "SDK_NOT_INJECTED", "engineering observation requires an explicit API object"
            )
        self._api = api
        self._forbidden_write_attempts: Counter[str] = Counter()
        self._safe_market_data_only_configuration_calls = 0

    def _blocked(self, method_name: str) -> None:
        self._forbidden_write_attempts[method_name] += 1
        raise EngineeringSmokeBlocked(
            "FORBIDDEN_WRITE_ATTEMPT",
            f"engineering observation forbids API method {method_name}",
        )

    def configure_execution(self, execution_config: Any) -> Any:
        """Allow only a one-way, non-arming market-data-only configuration."""

        if not isinstance(execution_config, Mapping) or dict(execution_config) != {
            "market_data_only": True
        }:
            self._blocked("configure_execution")
        configure = getattr(self._api, "configure_execution", None)
        if not callable(configure):
            raise EngineeringSmokeBlocked(
                "SDK_MARKET_DATA_ONLY_UNAVAILABLE",
                "injected managed SDK cannot prove market_data_only configuration",
            )
        self._safe_market_data_only_configuration_calls += 1
        return configure({"market_data_only": True})

    def __getattr__(self, name: str) -> Any:
        if self._is_forbidden_method(name):
            return lambda *_args, **_kwargs: self._blocked(name)
        value = getattr(self._api, name)
        if callable(value) and not self._is_safe_callable(name):
            return lambda *_args, **_kwargs: self._blocked(name)
        return value

    @classmethod
    def _is_forbidden_method(cls, name: str) -> bool:
        return str(name).lower() in cls._FORBIDDEN_METHODS_NORMALIZED

    @classmethod
    def _is_safe_callable(cls, name: str) -> bool:
        normalized = str(name).lower()
        return (
            normalized in cls._SAFE_LIFECYCLE_METHODS
            or normalized in cls._SAFE_READ_METHODS
            or normalized.startswith(cls._SAFE_READ_PREFIXES)
        )

    def audit(self) -> dict[str, Any]:
        return {
            "forbidden_write_attempts": dict(sorted(self._forbidden_write_attempts.items())),
            "safe_market_data_only_configuration_calls": self._safe_market_data_only_configuration_calls,
        }


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise EngineeringSmokeBlocked("EVENT_TIME", f"{field} is not ISO time") from error
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise EngineeringSmokeBlocked("EVENT_TIME", f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class RealtimeCohortEvent:
    """The minimum identity needed to use a live event causally."""

    event_time: datetime
    recv_monotonic: float
    generation: int
    subscription_epoch: int
    symbol: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, event: Mapping[str, Any]) -> "RealtimeCohortEvent":
        event_time = _utc(event.get("event_time"), "event_time")
        recv = event.get("recv_monotonic", event.get("received_monotonic"))
        if recv is None and event.get("recv_monotonic_ns") is not None:
            recv = float(event["recv_monotonic_ns"]) / 1_000_000_000.0
        if isinstance(recv, bool) or not isinstance(recv, (int, float)) or recv < 0:
            raise EngineeringSmokeBlocked("EVENT_IDENTITY", "recv_monotonic is required")
        generation = event.get("generation", event.get("connection_generation"))
        epoch = event.get("subscription_epoch")
        if type(generation) is not int or generation <= 0:
            raise EngineeringSmokeBlocked("EVENT_IDENTITY", "generation is required")
        if type(epoch) is not int or epoch <= 0:
            raise EngineeringSmokeBlocked("EVENT_IDENTITY", "subscription_epoch is required")
        symbol = str(event.get("symbol") or "")
        if not symbol:
            raise EngineeringSmokeBlocked("EVENT_IDENTITY", "symbol is required")
        return cls(event_time, float(recv), generation, epoch, symbol, dict(event))


def causal_fq2_events(
    events: Iterable[Mapping[str, Any]],
    *,
    cutoff: datetime,
    generation: int,
    subscription_epoch: int,
) -> tuple[RealtimeCohortEvent, ...]:
    """Return only complete, same-cohort events strictly before the cutoff."""

    cutoff = _utc(cutoff, "cutoff")
    accepted = []
    for raw in events:
        event = RealtimeCohortEvent.from_mapping(raw)
        if event.generation != generation or event.subscription_epoch != subscription_epoch:
            continue
        if event.event_time < cutoff:
            accepted.append(event)
    return tuple(sorted(accepted, key=lambda item: (item.event_time, item.recv_monotonic)))


class DurableExecutionJournal:
    """Append-only, identity-bearing execution evidence."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, kind: str, record: Mapping[str, Any]) -> None:
        if not kind or not isinstance(record, Mapping):
            raise ValueError("journal records require a kind and mapping")
        entry = {
            **dict(record),
            "kind": kind,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


@dataclass(frozen=True)
class FeeMarginInputs:
    fee_source: str
    margin_source: str
    fee_by_leg: Mapping[str, float]
    margin_by_leg: Mapping[str, float]
    identity: Mapping[str, str]

    def validate(self, symbols: Iterable[str]) -> None:
        expected = set(symbols)
        if not self.fee_source or not self.margin_source:
            raise EngineeringSmokeBlocked(
                "FEE_MARGIN_MISSING", "fee and margin sources are required"
            )
        if set(self.fee_by_leg) != expected or set(self.margin_by_leg) != expected:
            raise EngineeringSmokeBlocked("FEE_MARGIN_INCOMPLETE", "fee/margin must cover all legs")
        if any(float(value) < 0 for value in self.fee_by_leg.values()) or any(
            float(value) < 0 for value in self.margin_by_leg.values()
        ):
            raise EngineeringSmokeBlocked(
                "FEE_MARGIN_INVALID", "fee/margin values must be non-negative"
            )
        for key in ("account_fingerprint", "trading_day", "generation"):
            if not str(self.identity.get(key) or ""):
                raise EngineeringSmokeBlocked("FEE_MARGIN_IDENTITY", f"missing {key}")


class ThreeLegExecutionCoordinator:
    """Advance a basket only from confirmed external fills."""

    def __init__(self, symbols: tuple[str, str, str], journal: DurableExecutionJournal):
        if len(symbols) != 3 or len(set(symbols)) != 3:
            raise ValueError("exactly three distinct symbols are required")
        self.symbols = symbols
        self.journal = journal
        self.confirmed: MutableMapping[str, float] = dict.fromkeys(symbols, 0.0)
        self.status = "IDLE"
        self.recovery_required = False
        self._next_leg = 0
        self._active_basket_id: Optional[str] = None
        self._active_identity: Optional[tuple[str, str, str]] = None
        self._intent_symbol: Optional[str] = None
        self._intent_quantity: Optional[float] = None
        self._intent_client_order_id: Optional[str] = None
        self._ack_order_id: Optional[str] = None
        self._ack_client_order_id: Optional[str] = None
        self._evidence_failure = False
        self._seen_trade_keys: set[tuple[str, str, str, str, str]] = set()

    def record_intent(
        self,
        basket_id: str,
        symbol: str,
        quantity: float,
        identity: Mapping[str, Any],
        *,
        client_order_id: str,
    ) -> None:
        self._require_writable_evidence()
        if (
            self.status not in {"IDLE", "NEXT_LEG_CONFIRMED"}
            or symbol != self.symbols[self._next_leg]
        ):
            raise EngineeringSmokeBlocked("INTENT_ORDER", "intent is out of sequence")
        quantity_value = self._positive_finite_quantity(quantity, "INTENT_ORDER")
        if not basket_id or not client_order_id:
            raise EngineeringSmokeBlocked(
                "INTENT_ORDER", "basket, client order ID, and positive quantity are required"
            )
        identity_key = self._identity_key(identity)
        if self._active_basket_id is not None and basket_id != self._active_basket_id:
            raise EngineeringSmokeBlocked(
                "INTENT_BASKET", "intent basket does not match active basket"
            )
        if self._active_identity is not None and identity_key != self._active_identity:
            raise EngineeringSmokeBlocked(
                "INTENT_IDENTITY", "intent identity does not match active basket"
            )
        self._append_evidence(
            "intent",
            self._journal_payload(
                identity,
                basket_id=basket_id,
                symbol=symbol,
                quantity=quantity_value,
                client_order_id=client_order_id,
            ),
        )
        self._active_basket_id = basket_id
        self._active_identity = identity_key
        self._intent_symbol = symbol
        self._intent_quantity = quantity_value
        self._intent_client_order_id = str(client_order_id)
        self._ack_order_id = None
        self._ack_client_order_id = None
        self.status = "INTENT"

    def record_ack(
        self,
        basket_id: str,
        symbol: str,
        order_id: str,
        client_order_id: str,
        identity: Mapping[str, Any],
    ) -> None:
        self._require_writable_evidence()
        identity_key = self._identity_key(identity)
        if self.status != "INTENT" or self._intent_symbol != symbol:
            raise EngineeringSmokeBlocked("ACK_ORDER", "ACK requires the pending intent leg")
        if basket_id != self._active_basket_id:
            raise EngineeringSmokeBlocked("ACK_BASKET", "ACK basket does not match active basket")
        if identity_key != self._active_identity:
            raise EngineeringSmokeBlocked(
                "ACK_IDENTITY", "ACK identity does not match active basket"
            )
        if symbol != self.symbols[self._next_leg] or not order_id or not client_order_id:
            raise EngineeringSmokeBlocked(
                "ACK_IDENTITY", "ACK requires order and client identities"
            )
        if str(client_order_id) != self._intent_client_order_id:
            raise EngineeringSmokeBlocked(
                "ACK_IDENTITY", "ACK client order ID does not match the intent"
            )
        self._append_evidence(
            "ack",
            self._journal_payload(
                identity,
                basket_id=basket_id,
                symbol=symbol,
                order_id=order_id,
                client_order_id=client_order_id,
            ),
        )
        self._ack_order_id = str(order_id)
        self._ack_client_order_id = str(client_order_id)
        self.status = "ACKED"

    def record_fill(
        self, basket_id: str, symbol: str, quantity: float, identity: Mapping[str, Any]
    ) -> None:
        self._require_writable_evidence()
        identity_key, trade_key = self._fill_identity(identity, symbol)
        if self.status not in {"ACKED", "PARTIAL", "RECOVERY"} or self._intent_symbol != symbol:
            raise EngineeringSmokeBlocked(
                "FILL_ORDER", "fill requires the acknowledged pending leg"
            )
        if basket_id != self._active_basket_id:
            raise EngineeringSmokeBlocked("FILL_BASKET", "fill basket does not match active basket")
        if identity_key != self._active_identity:
            raise EngineeringSmokeBlocked(
                "FILL_IDENTITY", "fill identity does not match active basket"
            )
        if (
            str(identity["order_id"]) != self._ack_order_id
            or str(identity["client_order_id"]) != self._ack_client_order_id
        ):
            raise EngineeringSmokeBlocked(
                "FILL_IDENTITY", "fill identities do not match the acknowledged order"
            )
        if trade_key in self._seen_trade_keys:
            raise EngineeringSmokeBlocked("FILL_DUPLICATE", "fill trade ID was already recorded")
        quantity_value = self._positive_finite_quantity(quantity, "FILL_QUANTITY")
        if symbol not in self.confirmed or self._intent_quantity is None:
            raise EngineeringSmokeBlocked(
                "FILL_IDENTITY", "fill requires a known leg and pending quantity"
            )
        confirmed_quantity = self.confirmed[symbol] + quantity_value
        if not math.isfinite(confirmed_quantity) or confirmed_quantity > self._intent_quantity:
            raise EngineeringSmokeBlocked(
                "FILL_QUANTITY", "fill quantity exceeds the pending intent"
            )
        next_status = "NEXT_LEG_CONFIRMED"
        next_leg = self._next_leg
        recovery_required = self.recovery_required
        if confirmed_quantity < self._intent_quantity:
            next_status = "PARTIAL"
            recovery_required = True
        elif self.status in {"PARTIAL", "RECOVERY"} or recovery_required:
            # A partial or recovery state must be reconciled explicitly.  A
            # later fill may update the durable exposure evidence, but cannot
            # silently authorize the next leg.
            next_status = "RECOVERY"
            recovery_required = True
        else:
            next_leg = self.symbols.index(symbol) + 1
            if next_leg == len(self.symbols):
                next_status = "COMPLETE"
        self._append_evidence(
            "fill",
            self._journal_payload(
                identity,
                basket_id=basket_id,
                symbol=symbol,
                quantity=quantity_value,
                exchange_id=trade_key[2],
                trade_id=trade_key[4],
            ),
        )
        self._seen_trade_keys.add(trade_key)
        self.confirmed[symbol] = confirmed_quantity
        self.recovery_required = recovery_required
        self._next_leg = next_leg
        self.status = next_status

    def mark_compensation(self, basket_id: str, reason: str, identity: Mapping[str, Any]) -> None:
        self._require_writable_evidence()
        identity_key = self._terminal_identity(identity)
        if self.status not in {"ACKED", "PARTIAL"} or self._intent_symbol is None:
            raise EngineeringSmokeBlocked(
                "RECOVERY_ORDER",
                "recovery requires an acknowledged or partially filled pending leg",
            )
        if basket_id != self._active_basket_id:
            raise EngineeringSmokeBlocked(
                "RECOVERY_BASKET", "recovery basket does not match active basket"
            )
        if identity_key != self._active_identity:
            raise EngineeringSmokeBlocked(
                "RECOVERY_IDENTITY", "recovery identity does not match active basket"
            )
        if (
            str(identity["order_id"]) != self._ack_order_id
            or str(identity["client_order_id"]) != self._ack_client_order_id
        ):
            raise EngineeringSmokeBlocked(
                "RECOVERY_IDENTITY", "recovery identities do not match the acknowledged order"
            )
        self._append_evidence(
            "compensation_or_recovery",
            self._journal_payload(identity, basket_id=basket_id, reason=reason),
        )
        self.recovery_required = True
        self.status = "RECOVERY"

    @staticmethod
    def _identity_key(identity: Mapping[str, Any]) -> tuple[str, str, str]:
        for key in ("account_fingerprint", "trading_day", "generation"):
            if key not in identity or identity[key] in (None, ""):
                raise EngineeringSmokeBlocked("BASE_IDENTITY", f"missing base identity {key}")
        return tuple(
            str(identity[key]) for key in ("account_fingerprint", "trading_day", "generation")
        )

    @staticmethod
    def _positive_finite_quantity(quantity: float, code: str) -> float:
        try:
            quantity_value = float(quantity)
        except (TypeError, ValueError, OverflowError) as error:
            raise EngineeringSmokeBlocked(
                code, "quantity must be a finite positive number"
            ) from error
        if not math.isfinite(quantity_value) or quantity_value <= 0:
            raise EngineeringSmokeBlocked(code, "quantity must be a finite positive number")
        return quantity_value

    @staticmethod
    def _journal_payload(identity: Mapping[str, Any], **canonical_fields: Any) -> dict[str, Any]:
        """Keep journal identity metadata without allowing it to forge event facts."""

        return {**dict(identity), **canonical_fields}

    def _append_evidence(self, kind: str, record: Mapping[str, Any]) -> None:
        try:
            self.journal.append(kind, record)
        except Exception:
            self._evidence_failure = True
            self.recovery_required = True
            self.status = "EVIDENCE_FAILURE"
            raise

    def _require_writable_evidence(self) -> None:
        if self._evidence_failure:
            raise EngineeringSmokeBlocked(
                "EVIDENCE_FAILURE",
                "journal evidence previously failed; recovery is externally required",
            )

    @classmethod
    def _terminal_identity(cls, identity: Mapping[str, Any]) -> tuple[str, str, str]:
        identity_key = cls._identity_key(identity)
        for key in ("order_id", "client_order_id"):
            if key not in identity or identity[key] in (None, ""):
                raise EngineeringSmokeBlocked(
                    "TERMINAL_IDENTITY", f"missing terminal identity {key}"
                )
        return identity_key

    @classmethod
    def _fill_identity(
        cls, identity: Mapping[str, Any], symbol: str
    ) -> tuple[tuple[str, str, str], tuple[str, str, str, str, str]]:
        identity_key = cls._terminal_identity(identity)
        for key in ("exchange_id", "trade_id"):
            if key not in identity or identity[key] in (None, ""):
                raise EngineeringSmokeBlocked("FILL_IDENTITY", f"missing fill identity {key}")
        trade_key = (
            identity_key[0],
            identity_key[1],
            str(identity["exchange_id"]),
            str(symbol),
            str(identity["trade_id"]),
        )
        return identity_key, trade_key


_RECONCILIATION_SCHEMA = "backtrader.ctp.reconciliation.v1"
_BUNDLE_PREFLIGHT_SCHEMA = "backtrader.ctp.bundle-preflight.v2"
_RECONCILIATION_QUERY_NAMES = ("account", "positions", "orders", "trades")


def _reconciliation_request_id_scope(item: Mapping[str, Any]) -> frozenset[int]:
    """Return one complete account-query scope or stop before arming anything."""
    request_ids = item.get("request_ids")
    all_request_ids = item.get("all_request_ids")
    if not isinstance(request_ids, Mapping) or not isinstance(all_request_ids, Mapping):
        raise EngineeringSmokeBlocked(
            "RECONCILIATION_REQUEST_IDS_INCOMPLETE",
            "CTP reconciliation must include complete request-ID evidence",
        )
    values = []
    for name in _RECONCILIATION_QUERY_NAMES:
        request_id = request_ids.get(name)
        all_request_id = all_request_ids.get(name)
        if (
            type(request_id) is not int
            or request_id <= 0
            or type(all_request_id) is not int
            or all_request_id <= 0
            or all_request_id != request_id
        ):
            raise EngineeringSmokeBlocked(
                "RECONCILIATION_REQUEST_IDS_INVALID",
                "CTP reconciliation request-ID evidence is invalid",
            )
        values.append(request_id)
    if len(set(values)) != len(values):
        raise EngineeringSmokeBlocked(
            "RECONCILIATION_REQUEST_IDS_INVALID",
            "CTP reconciliation request IDs must be unique within one observation",
        )
    return frozenset(values)


def _stable_reconciliation_fingerprint(item: Mapping[str, Any]) -> str:
    """Fingerprint the complete account scope, excluding observation-local IDs."""
    fields = (
        "account_fingerprint",
        "trading_day",
        "connection_generation",
        "account",
        "positions",
        "orders",
        "trades",
        "active_order_count",
        "unknown_intent_count",
        "unmatched_trade_count",
        "flat",
    )
    return json.dumps(
        {field: item[field] for field in fields},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _require_flat_reconciliation(item: Mapping[str, Any]) -> frozenset[int]:
    required = (
        "schema_version",
        "account_fingerprint",
        "trading_day",
        "connection_generation",
        "account",
        "positions",
        "orders",
        "trades",
        "complete",
        "is_last_seen",
        "timed_out",
        "error_code",
        "evidence_complete",
        "read_only_safe",
        "write_request_free",
        "active_order_count",
        "unknown_intent_count",
        "unmatched_trade_count",
        "flat",
    )
    if any(key not in item for key in required):
        raise EngineeringSmokeBlocked(
            "RECONCILIATION_INCOMPLETE", "real CTP reconciliation fields are incomplete"
        )
    if item["schema_version"] != _RECONCILIATION_SCHEMA:
        raise EngineeringSmokeBlocked(
            "RECONCILIATION_SCHEMA", "unsupported CTP reconciliation schema"
        )
    if (
        not isinstance(item["account_fingerprint"], str)
        or not item["account_fingerprint"].strip()
        or not isinstance(item["trading_day"], str)
        or not item["trading_day"].strip()
        or type(item["connection_generation"]) is not int
        or item["connection_generation"] <= 0
    ):
        raise EngineeringSmokeBlocked(
            "RECONCILIATION_IDENTITY", "CTP reconciliation identity is invalid"
        )
    if (
        item["complete"] is not True
        or item["is_last_seen"] is not True
        or item["timed_out"] is not False
        or item["error_code"] not in (None, "", 0, "0")
        or any(
            not isinstance(item[key], (list, tuple))
            for key in ("account", "positions", "orders", "trades")
        )
    ):
        raise EngineeringSmokeBlocked(
            "RECONCILIATION_INCOMPLETE", "CTP reconciliation scope is incomplete"
        )
    if any(
        item[key] is not True
        for key in ("evidence_complete", "read_only_safe", "write_request_free", "flat")
    ):
        raise EngineeringSmokeBlocked(
            "RECONCILIATION_NOT_FLAT", "CTP reconciliation is not complete, read-only, or flat"
        )
    if any(
        item[key] != 0
        for key in ("active_order_count", "unknown_intent_count", "unmatched_trade_count")
    ):
        raise EngineeringSmokeBlocked(
            "RECONCILIATION_NOT_FLAT",
            "CTP reconciliation contains active or unknown execution state",
        )
    return _reconciliation_request_id_scope(item)


def require_two_account_reconciliations(
    rounds: Iterable[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Require two real v1, complete, same-identity, flat observations."""

    materialized = tuple(rounds)
    if len(materialized) != 2:
        raise EngineeringSmokeBlocked(
            "RECONCILIATION_ROUNDS", "exactly two reconciliation rounds are required"
        )
    request_id_scopes = tuple(_require_flat_reconciliation(item) for item in materialized)
    identity = tuple(
        materialized[0][key]
        for key in ("account_fingerprint", "trading_day", "connection_generation")
    )
    if any(
        tuple(item[key] for key in ("account_fingerprint", "trading_day", "connection_generation"))
        != identity
        for item in materialized[1:]
    ):
        raise EngineeringSmokeBlocked("RECONCILIATION_IDENTITY", "reconciliation identity changed")
    if _stable_reconciliation_fingerprint(materialized[0]) != _stable_reconciliation_fingerprint(
        materialized[1]
    ):
        raise EngineeringSmokeBlocked(
            "RECONCILIATION_SEMANTIC_MISMATCH",
            "two reconciliation observations must have stable account scope",
        )
    if request_id_scopes[0] & request_id_scopes[1]:
        raise EngineeringSmokeBlocked(
            "RECONCILIATION_REQUEST_ID_REPLAY",
            "two reconciliation observations must have disjoint request-ID scopes",
        )
    return materialized  # type: ignore[return-value]


def validate_startup_shutdown_reconciliations(
    *, startup: Iterable[Mapping[str, Any]], shutdown: Iterable[Mapping[str, Any]]
) -> dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]]:
    """Apply the same two-round account-wide gate at both lifecycle edges."""

    return {
        "startup": require_two_account_reconciliations(startup),
        "shutdown": require_two_account_reconciliations(shutdown),
    }


class CtpStoreLifecycle:
    """Use the existing public Store gates; never reach into a native client."""

    def __init__(self, store: BtApiStore):
        self.store = store

    def startup(
        self, legs: Any, *, primary_leg: Any = None, timeout: float = 15.0
    ) -> dict[str, Any]:
        bundle = self.store.get_ctp_bundle_preflight_snapshot(
            legs, primary_leg=primary_leg, timeout=timeout, read_only=True
        )
        required = ("schema_version", "evidence_complete", "read_only_safe", "flat")
        if (
            any(key not in bundle for key in required)
            or bundle["schema_version"] != _BUNDLE_PREFLIGHT_SCHEMA
        ):
            raise EngineeringSmokeBlocked(
                "BUNDLE_PREFLIGHT_SCHEMA", "unsupported or incomplete CTP bundle preflight"
            )
        if any(bundle[key] is not True for key in ("evidence_complete", "read_only_safe", "flat")):
            raise EngineeringSmokeBlocked(
                "BUNDLE_PREFLIGHT_NOT_FLAT",
                "CTP bundle preflight is not complete, read-only, or flat",
            )
        first = self.store.get_ctp_reconciliation_snapshot(timeout=timeout)
        second = self.store.get_ctp_reconciliation_snapshot(timeout=timeout)
        require_two_account_reconciliations((first, second))
        return {"bundle_preflight": bundle, "reconciliation": (first, second)}

    def shutdown(self, *, timeout: float = 5.0) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        rounds = (
            self.store.get_ctp_reconciliation_snapshot(timeout=timeout),
            self.store.get_ctp_reconciliation_snapshot(timeout=timeout),
        )
        require_two_account_reconciliations(rounds)
        return rounds

    def verify_settlement(self, *, timeout: float = 5.0) -> Mapping[str, Any]:
        result = self.store.verify_ctp_settlement(timeout=timeout)
        if not result.get("evidence_complete"):
            raise EngineeringSmokeBlocked(
                "SETTLEMENT_NOT_VERIFIED", "public Store settlement verification is incomplete"
            )
        return result

    def prepare_settlement(self, *, timeout: float = 5.0) -> Mapping[str, Any]:
        """Explicit operator action; never called by engineering_smoke."""
        result = self.store.prepare_ctp_settlement(timeout=timeout)
        if not result.get("evidence_complete"):
            raise EngineeringSmokeBlocked(
                "SETTLEMENT_NOT_PREPARED", "public Store settlement preparation is incomplete"
            )
        return result

    def configure_authorization(self, grant: Mapping[str, Any]) -> Mapping[str, Any]:
        """Bind only an externally-issued grant; never manufacture trust roots."""
        if not isinstance(grant, Mapping) or not grant:
            raise EngineeringSmokeBlocked(
                "TRUST_ROOT_UNAVAILABLE",
                "execution authorization requires an externally-issued grant",
            )
        try:
            return self.store.configure_ctp_execution_authorization(grant)
        except Exception as error:
            # The public Store owns the trust-root check.  Preserve its
            # fail-closed result without inspecting environment or secrets.
            message = str(error).lower()
            if "trust root" in message or "authorization" in message:
                raise EngineeringSmokeBlocked("TRUST_ROOT_UNAVAILABLE", str(error)) from error
            raise


def _engineering_duration_seconds(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EngineeringSmokeBlocked(
            "ENGINEERING_DURATION", "engineering observation duration must be a number"
        )
    seconds = float(value)
    if (
        not math.isfinite(seconds)
        or seconds <= 0.0
        or seconds > ENGINEERING_OBSERVATION_MAX_SECONDS
    ):
        raise EngineeringSmokeBlocked(
            "ENGINEERING_DURATION", "engineering observation duration must be in (0, 3600] seconds"
        )
    return seconds


class _ObservationSessionBindingProbe(bt.Analyzer):
    """Bind the already-connected Store to one public CTP session state."""

    params = (("on_session_bound", None),)

    def start(self) -> None:
        on_session_bound = self.p.on_session_bound
        if not callable(on_session_bound):
            raise RuntimeError("engineering observation session-binding callback is unavailable")
        on_session_bound()


def _positive_generation(value: Any) -> int | None:
    """Accept only one positive, native public integer generation."""

    return value if type(value) is int and value > 0 else None


def _require_second_set_session_binding(
    store: Any, *, clock_mapping: ClockMapping
) -> dict[str, Any]:
    """Fail closed unless public Store state binds this run to second Set-2."""

    if getattr(store, "is_connected", False) is not True:
        raise EngineeringSmokeBlocked(
            "CTP_SESSION_STATE_UNAVAILABLE",
            "Store has not connected before second-set session binding",
        )
    getter = getattr(store, "get_ctp_session_state", None)
    if not callable(getter):
        raise EngineeringSmokeBlocked(
            "CTP_SESSION_STATE_UNAVAILABLE",
            "public CTP session state is unavailable",
        )
    try:
        state = getter()
    except Exception as error:
        raise EngineeringSmokeBlocked(
            "CTP_SESSION_STATE_UNAVAILABLE",
            "public CTP session state could not be read",
        ) from error
    if not isinstance(state, Mapping) or state.get("connected") is not True:
        raise EngineeringSmokeBlocked(
            "CTP_SESSION_STATE_UNAVAILABLE",
            "public CTP session state does not prove a connection",
        )

    profile = state.get("environment_profile")
    if not isinstance(profile, str) or not profile.startswith(SECOND_SET_SESSION_PROFILE_PREFIX):
        raise EngineeringSmokeBlocked(
            "SECOND_SET_SESSION_PROFILE_REQUIRED",
            "public CTP session state is not a set2_7x24-family profile",
        )

    account_fingerprint = state.get("account_fingerprint")
    if not isinstance(account_fingerprint, str) or not account_fingerprint.strip():
        raise EngineeringSmokeBlocked(
            "SESSION_ACCOUNT_FINGERPRINT_REQUIRED",
            "public CTP session state has no account fingerprint",
        )
    if state.get("read_only_ready") is not True:
        raise EngineeringSmokeBlocked(
            "SESSION_READ_ONLY_NOT_READY",
            "public CTP session state is not read-only ready",
        )
    if state.get("execution_gate_armed") is not False:
        raise EngineeringSmokeBlocked(
            "SESSION_EXECUTION_GATE_NOT_UNARMED",
            "public CTP execution gate is not explicitly unarmed",
        )
    session_generation = _positive_generation(state.get("connection_generation"))
    if session_generation is None:
        raise EngineeringSmokeBlocked(
            "SESSION_GENERATION_REQUIRED",
            "public CTP session state has no positive connection generation",
        )
    if session_generation != clock_mapping.connection_generation:
        raise EngineeringSmokeBlocked(
            "SESSION_GENERATION_MISMATCH",
            "public CTP session generation differs from the trusted clock mapping",
        )

    # Preserve joinable proof fields only; never echo the account fingerprint
    # or caller-provided admission label in the observation report.
    return {
        "source": "BtApiStore.get_ctp_session_state",
        "session_environment_profile": profile,
        "profile_family_prefix": SECOND_SET_SESSION_PROFILE_PREFIX,
        "account_fingerprint_sha256": hashlib.sha256(account_fingerprint.encode()).hexdigest(),
        "read_only_ready": True,
        "execution_armed": False,
        "connection_generation": session_generation,
        "clock_mapping_id": clock_mapping.mapping_id,
        "clock_mapping_generation": clock_mapping.connection_generation,
    }


def _require_live_clock_mapping(
    *,
    clock_mapping: Any,
    feed_clock: Any,
    candidate: Mapping[str, Any],
    duration_seconds: float,
) -> ClockMapping:
    """Require one caller-owned, non-synthetic mapping for the whole run."""

    if not isinstance(clock_mapping, ClockMapping) or clock_mapping.synthetic:
        raise EngineeringSmokeBlocked(
            "LIVE_CLOCK_MAPPING_REQUIRED",
            "engineering observation requires a non-synthetic ClockMapping",
        )
    if clock_mapping.rules_hash != candidate["rules_hash"]:
        raise EngineeringSmokeBlocked(
            "LIVE_CLOCK_MAPPING_REQUIRED",
            "live ClockMapping rules hash does not match the configured candidate",
        )
    monotonic_ns = getattr(feed_clock, "monotonic_ns", None)
    if not callable(monotonic_ns):
        raise EngineeringSmokeBlocked(
            "LIVE_FEED_CLOCK_REQUIRED",
            "engineering observation requires an injected feed clock with monotonic_ns()",
        )
    try:
        now_ns = monotonic_ns()
    except Exception as error:
        raise EngineeringSmokeBlocked(
            "LIVE_FEED_CLOCK_REQUIRED", "injected feed clock could not provide monotonic_ns"
        ) from error
    if isinstance(now_ns, bool) or not isinstance(now_ns, int):
        raise EngineeringSmokeBlocked(
            "LIVE_FEED_CLOCK_REQUIRED", "feed clock monotonic_ns must return an integer"
        )
    required_until_ns = now_ns + int(math.ceil(duration_seconds * 1_000_000_000.0))
    if (
        now_ns < clock_mapping.mono_ns_at_anchor
        or required_until_ns > clock_mapping.valid_until_mono_ns
    ):
        raise EngineeringSmokeBlocked(
            "LIVE_CLOCK_MAPPING_EXPIRED",
            "live ClockMapping does not cover the requested observation duration",
        )
    return clock_mapping


def _guarded_live_evidence_provider(
    provider: Callable[[Any], Any],
    *,
    clock_mapping: ClockMapping,
    candidate: Mapping[str, Any],
) -> tuple[Callable[[Any], BarEvidence], list[BarEvidence]]:
    """Narrow a caller callback to one trusted, stable live evidence scope."""

    emitted: list[BarEvidence] = []

    def guarded(bar: Any) -> BarEvidence:
        try:
            evidence = provider(bar)
        except EngineeringSmokeBlocked:
            raise
        except Exception as error:
            raise EngineeringSmokeBlocked(
                "LIVE_EVIDENCE_PROVIDER_FAILED", "closed-bar evidence provider failed"
            ) from error
        if not isinstance(evidence, BarEvidence):
            raise EngineeringSmokeBlocked(
                "LIVE_EVIDENCE_REQUIRED", "closed-bar evidence provider must return BarEvidence"
            )
        if evidence.clock_mode != "live" or evidence.clock_mapping.synthetic:
            raise EngineeringSmokeBlocked(
                "LIVE_EVIDENCE_CLOCK_MODE",
                "engineering observation rejects replay/synthetic bar evidence",
            )
        if evidence.clock_mapping != clock_mapping:
            raise EngineeringSmokeBlocked(
                "LIVE_EVIDENCE_MAPPING_REQUIRED",
                "closed-bar evidence does not use the injected trusted ClockMapping",
            )
        if evidence.clock_domain != clock_mapping.clock_domain_id:
            raise EngineeringSmokeBlocked(
                "LIVE_EVIDENCE_CLOCK_DOMAIN",
                "closed-bar evidence clock domain does not match the trusted ClockMapping",
            )
        if (
            evidence.candidate_id != candidate["candidate_id"]
            or evidence.rules_hash != candidate["rules_hash"]
        ):
            raise EngineeringSmokeBlocked(
                "LIVE_EVIDENCE_CANDIDATE_SCOPE",
                "closed-bar evidence candidate/rules scope does not match the configured candidate",
            )
        emitted.append(evidence)
        return evidence

    return guarded, emitted


def _engineering_observation_shutdown_complete(summary: Any, store: Any = None) -> bool:
    """Accept a clean read-only stop without claiming remote account flatness."""

    if not isinstance(summary, Mapping):
        return False
    try:
        if store is not None and bool(getattr(store, "is_connected", False)):
            return False
    except BaseException:
        return False
    zero_counts = (
        "cancel_requested",
        "close_requested",
        "unknown_orders",
        "active_order_count",
        "local_position_count",
        "observed_remote_open_order_count",
    )
    return bool(
        summary.get("status") == "OBSERVATION_ONLY"
        and summary.get("market_data_only") is True
        and summary.get("store_shutdown_state") == "PASS"
        and summary.get("remote_flat_proven") is False
        and summary.get("remote_position_count") is None
        and summary.get("unknown_intent_count") is None
        and summary.get("unmatched_trade_count") is None
        and summary.get("startup_account_state_requires_nonflat") is False
        and all(type(summary.get(name)) is int and summary[name] == 0 for name in zero_counts)
    )


def _engineering_observation_shutdown_projection(summary: Any) -> dict[str, Any]:
    """Keep terminal lifecycle proof while omitting raw session diagnostics."""

    if not isinstance(summary, Mapping):
        return {"status": "UNPROVEN"}
    return {
        "status": summary.get("status", "UNPROVEN"),
        "market_data_only": summary.get("market_data_only"),
        "cancel_requested": summary.get("cancel_requested"),
        "close_requested": summary.get("close_requested"),
        "store_shutdown_state": summary.get("store_shutdown_state", "UNPROVEN"),
    }


def _engineering_observation_unstarted_store_shutdown_complete(store: Any) -> bool:
    """Accept only a proven never-started Store after construction aborts."""

    health_reader = getattr(store, "get_command_health", None)
    health = health_reader() if callable(health_reader) else None
    return bool(
        not bool(getattr(store, "is_connected", False))
        and isinstance(health, Mapping)
        and health.get("shutdown_state") == "NOT_STARTED"
        and int(health.get("queue_depth", 0) or 0) == 0
        and not health.get("inflight")
        and not health.get("worker_alive")
        and not health.get("close_thread_alive")
    )


def _engineering_observation_unstarted_graph_shutdown_complete(
    broker: Any,
    store: Any,
) -> bool:
    """Accept only a proven never-started graph after construction aborts."""

    if not _engineering_observation_unstarted_store_shutdown_complete(store):
        return False
    if broker is None:
        return True
    summary_reader = getattr(broker, "get_shutdown_summary", None)
    summary = summary_reader() if callable(summary_reader) else None
    return bool(isinstance(summary, Mapping) and summary.get("status") == "NOT_STARTED")


def _stop_engineering_observation_graph(*, broker: Any, feeds: list[Any], store: Any) -> bool:
    """Stop every constructed component and prove its zero-write terminal state."""

    clean = True
    if broker is not None:
        try:
            broker.stop()
        except BaseException:
            clean = False
    for feed in feeds:
        try:
            feed.stop()
        except BaseException:
            clean = False
    if store is not None:
        try:
            store.stop(timeout=2.0)
        except BaseException:
            clean = False
    if not clean:
        return False
    if store is None:
        return broker is None
    summary_reader = getattr(broker, "get_shutdown_summary", None)
    try:
        summary = summary_reader() if callable(summary_reader) else None
    except BaseException:
        return False
    return _engineering_observation_shutdown_complete(
        summary, store
    ) or _engineering_observation_unstarted_graph_shutdown_complete(broker, store)


def _engineering_observation_evidence_complete(
    strategy: Any,
    *,
    expected_symbols: tuple[str, ...],
    clock_mapping: ClockMapping,
) -> tuple[bool, str]:
    """Verify that Feed—not a mutable line or replay callback—formed all three legs."""

    decision_input = getattr(strategy, "_last_decision_input", None)
    if decision_input is None:
        return False, "FEED_SEALED_THREE_LEG_INPUT_MISSING"
    bars = getattr(decision_input, "bars", None)
    if not isinstance(bars, Mapping) or set(bars) != set(expected_symbols):
        return False, "FEED_SEALED_THREE_LEG_SCOPE_INCOMPLETE"
    for evidence in bars.values():
        if not isinstance(evidence, BarEvidence):
            return False, "FEED_SEALED_BAR_EVIDENCE_MISSING"
        if (
            evidence.clock_mode != "live"
            or evidence.clock_mapping != clock_mapping
            or evidence.clock_domain != clock_mapping.clock_domain_id
        ):
            return False, "FEED_SEALED_LIVE_CLOCK_MISMATCH"
    report = strategy.build_report()
    feed_evidence = report.get("feed_evidence") if isinstance(report, Mapping) else None
    if not isinstance(feed_evidence, Mapping) or feed_evidence.get("fault") is not None:
        return False, "FEED_SEALED_EVIDENCE_FAULT"
    return True, "PASS"


def _engineering_observation_elapsed_within_maximum(elapsed_seconds: float) -> bool:
    """Keep a successful observation inside its complete lifecycle ceiling."""

    return bool(
        math.isfinite(elapsed_seconds)
        and 0.0 <= elapsed_seconds <= ENGINEERING_OBSERVATION_MAX_SECONDS
    )


def run_engineering_observation(
    *,
    config: Mapping[str, Any],
    api: Any,
    environment_profile: str,
    run_seconds: Any,
    feed_clock: Any,
    clock_mapping: ClockMapping,
    closed_bar_evidence_provider: Callable[[Any], Any],
) -> dict[str, Any]:
    """Run one bounded Set-2 shadow observation through Store/Feed/Cerebro.

    This entry point is deliberately API-only.  It neither looks up an SDK nor
    reads any environment/credential file.  The caller has to inject an
    already-created API object, a calibrated live clock mapping and a provider
    that turns Feed-owned closed bars into immutable evidence.  It can never
    authorize execution, settle, submit, cancel or create synthetic fills.
    """

    if api is None:
        raise EngineeringSmokeBlocked(
            "SDK_NOT_INJECTED", "engineering observation requires an explicit API object"
        )
    if environment_profile != SECOND_SET_ENGINEERING_PROFILE:
        raise EngineeringSmokeBlocked(
            "ENGINEERING_PROFILE_REQUIRED",
            "engineering observation requires the simnow_second_7x24 profile",
        )
    if not isinstance(config, Mapping) or not isinstance(config.get("candidate"), Mapping):
        raise EngineeringSmokeBlocked(
            "ENGINEERING_CONFIG", "validated candidate configuration is required"
        )
    if not callable(closed_bar_evidence_provider):
        raise EngineeringSmokeBlocked(
            "LIVE_EVIDENCE_REQUIRED",
            "engineering observation requires a closed-bar evidence provider",
        )

    candidate = config["candidate"]
    duration_seconds = _engineering_duration_seconds(run_seconds)
    # This is deliberately earlier than Store/Broker/Feed construction.  The
    # maximum is an end-to-end engineering-observation ceiling, not a full
    # runtime grant which starts only after a potentially slow connection.
    started_at = time.monotonic()
    lifecycle_deadline = started_at + ENGINEERING_OBSERVATION_MAX_SECONDS
    trusted_mapping = _require_live_clock_mapping(
        clock_mapping=clock_mapping,
        feed_clock=feed_clock,
        candidate=candidate,
        duration_seconds=duration_seconds,
    )
    symbols = tuple(candidate["contracts"][field] for field in ("future", "call", "put"))
    if len(symbols) != 3 or len(set(symbols)) != 3:
        raise EngineeringSmokeBlocked(
            "ENGINEERING_CONFIG", "candidate must provide three distinct C/P/F symbols"
        )

    guarded_provider, emitted_evidence = _guarded_live_evidence_provider(
        closed_bar_evidence_provider,
        clock_mapping=trusted_mapping,
        candidate=candidate,
    )
    # The lifecycle ceiling begins before the native graph exists.  A blocking
    # Store/Broker/Feed constructor must consume this same budget and cannot
    # grant a fresh observation window once it returns.
    deadline_stop_requested = threading.Event()
    lifecycle_deadline_stop_requested = threading.Event()
    session_binding: list[dict[str, Any]] = []
    deadline_timers: list[threading.Timer] = []
    lifecycle_deadline_timers: list[threading.Timer] = []
    lifecycle_lock = threading.Lock()
    cerebro: Any = None
    guarded_api: Any = None
    store: Any = None
    broker: Any = None
    feeds: list[Any] = []

    def request_deadline_stop() -> None:
        deadline_stop_requested.set()
        active_cerebro = cerebro
        if active_cerebro is not None:
            active_cerebro.runstop()

    def request_lifecycle_deadline_stop() -> None:
        lifecycle_deadline_stop_requested.set()
        active_cerebro = cerebro
        if active_cerebro is not None:
            active_cerebro.runstop()

    def require_lifecycle_budget() -> None:
        if time.monotonic() >= lifecycle_deadline:
            request_lifecycle_deadline_stop()
        if lifecycle_deadline_stop_requested.is_set():
            raise EngineeringSmokeBlocked(
                "OBSERVATION_LIFECYCLE_DURATION_EXCEEDED",
                "engineering observation exhausted its end-to-end 3600-second lifecycle budget",
            )

    def cancel_observation_timers() -> bool:
        timer_shutdown_complete = True
        with lifecycle_lock:
            timers = tuple(deadline_timers) + tuple(lifecycle_deadline_timers)
        for timer in timers:
            timer.cancel()
            timer.join(timeout=1.0)
            if timer.is_alive():
                timer_shutdown_complete = False
        return timer_shutdown_complete

    remaining_lifecycle_seconds = lifecycle_deadline - time.monotonic()
    if remaining_lifecycle_seconds <= 0.0:
        request_lifecycle_deadline_stop()
        raise EngineeringSmokeBlocked(
            "OBSERVATION_LIFECYCLE_DURATION_EXCEEDED",
            "engineering observation setup exhausted its 3600-second lifecycle budget",
        )
    lifecycle_timer = threading.Timer(
        remaining_lifecycle_seconds,
        request_lifecycle_deadline_stop,
    )
    lifecycle_timer.name = "iter24-engineering-observation-lifecycle-deadline"
    lifecycle_timer.daemon = True
    lifecycle_deadline_timers.append(lifecycle_timer)
    lifecycle_timer.start()

    try:
        require_lifecycle_budget()
        guarded_api = _ObservationReadOnlyApi(api)
        # A managed SDK may require this narrowing transition at Store start.
        # The API membrane above admits only this exact non-arming configuration.
        store = BtApiStore(
            provider="btapi",
            api=guarded_api,
            config={"market_data_only": True, "execution_config": {"market_data_only": True}},
            autostart=False,
        )
        require_lifecycle_budget()
        broker = store.getbroker(
            market_data_only=True,
            flatten_on_stop=False,
            cash_check_enabled=True,
            sdk_preflight=False,
            force_refresh_queries=False,
        )
        require_lifecycle_budget()
        cerebro = bt.Cerebro(stdstats=False, quicknotify=True, runonce=False)
        require_lifecycle_budget()
        cerebro.setbroker(broker)
        require_lifecycle_budget()
        for symbol in symbols:
            feed = store.getdata(
                dataname=symbol,
                timeframe=bt.TimeFrame.Minutes,
                compression=1,
                backfill_start=False,
                dispatch_ticks=False,
                dispatch_orderbooks=False,
                dispatch_bars=True,
                qcheck=0.01,
                price_tick=float(
                    candidate["price_ticks"][
                        (
                            "future"
                            if symbol == symbols[0]
                            else "call" if symbol == symbols[1] else "put"
                        )
                    ]
                ),
                clock=feed_clock,
                closed_bar_evidence_provider=guarded_provider,
            )
            feeds.append(feed)
            cerebro.adddata(feed, name=symbol)
            require_lifecycle_budget()
        try:
            from .ctp_options_midfreq_strategy import CTPOptionsMidFrequencyStrategy
        except ImportError:  # Direct execution through this directory's modules.
            from ctp_options_midfreq_strategy import CTPOptionsMidFrequencyStrategy

        cerebro.addstrategy(
            CTPOptionsMidFrequencyStrategy,
            config=config,
            require_feed_bar_evidence=True,
            feed_evidence_clock_mode="live",
            feed_evidence_clock_domain=trusted_mapping.clock_domain_id,
        )
        require_lifecycle_budget()
    except BaseException as error:
        timer_shutdown_failed = not cancel_observation_timers()
        graph_shutdown_complete = store is None or _stop_engineering_observation_graph(
            broker=broker,
            feeds=feeds,
            store=store,
        )
        if timer_shutdown_failed or not graph_shutdown_complete:
            raise EngineeringSmokeBlocked(
                "OBSERVATION_SHUTDOWN_INCOMPLETE",
                "engineering observation construction shutdown is not proven complete",
            ) from error
        if isinstance(error, EngineeringSmokeBlocked):
            raise error
        raise EngineeringSmokeBlocked(
            "ENGINEERING_OBSERVATION_RUNTIME",
            "engineering observation construction aborted before runtime",
        ) from error

    def bind_session_then_start_deadline() -> None:
        """Run after Cerebro has connected the Store and started the strategy."""

        binding = _require_second_set_session_binding(
            store,
            clock_mapping=trusted_mapping,
        )
        with lifecycle_lock:
            if session_binding:
                return
            session_binding.append(binding)
            # A post-bind watchdog must never receive a fresh full hour after
            # slow Store/Broker/Feed startup.  It consumes only the remaining
            # end-to-end lifecycle budget.
            remaining_seconds = lifecycle_deadline - time.monotonic()
            if lifecycle_deadline_stop_requested.is_set() or remaining_seconds <= 0:
                request_lifecycle_deadline_stop()
                return
            timer = threading.Timer(min(duration_seconds, remaining_seconds), request_deadline_stop)
            timer.name = "iter24-engineering-observation-watchdog"
            timer.daemon = True
            deadline_timers.append(timer)
            timer.start()

    try:
        require_lifecycle_budget()
        cerebro.addanalyzer(
            _ObservationSessionBindingProbe,
            on_session_bound=bind_session_then_start_deadline,
        )
        require_lifecycle_budget()
    except BaseException as error:
        timer_shutdown_failed = not cancel_observation_timers()
        if timer_shutdown_failed or not _stop_engineering_observation_graph(
            broker=broker,
            feeds=feeds,
            store=store,
        ):
            raise EngineeringSmokeBlocked(
                "OBSERVATION_SHUTDOWN_INCOMPLETE",
                "engineering observation setup shutdown is not proven complete",
            ) from error
        if isinstance(error, EngineeringSmokeBlocked):
            raise error
        raise EngineeringSmokeBlocked(
            "ENGINEERING_OBSERVATION_RUNTIME",
            "engineering observation setup aborted before runtime",
        ) from error

    strategies = []
    run_error: Optional[BaseException] = None
    shutdown_error: Optional[EngineeringSmokeBlocked] = None
    try:
        require_lifecycle_budget()
        strategies = cerebro.run(preload=False, runonce=False)
    except BaseException as error:
        run_error = error
    finally:
        with lifecycle_lock:
            deadline_timer = deadline_timers[0] if deadline_timers else None
            lifecycle_timer = lifecycle_deadline_timers[0] if lifecycle_deadline_timers else None
        for timer in (deadline_timer, lifecycle_timer):
            if timer is None:
                continue
            timer.cancel()
            timer.join(timeout=1.0)
            if timer.is_alive():
                shutdown_error = EngineeringSmokeBlocked(
                    "OBSERVATION_SHUTDOWN_INCOMPLETE",
                    "engineering observation watchdog did not stop",
                )

        if run_error is not None:
            shutdown_reader = getattr(broker, "get_shutdown_summary", None)
            try:
                shutdown_before = shutdown_reader() if callable(shutdown_reader) else None
            except BaseException:
                shutdown_before = None
            # A disconnected Store is not sufficient evidence after an error:
            # accept the original runtime/binding failure only after a valid
            # public read-only shutdown summary.  Otherwise retry the whole
            # graph teardown and give missing proof failure precedence.
            if not _engineering_observation_shutdown_complete(shutdown_before, store):
                if not _stop_engineering_observation_graph(
                    broker=broker,
                    feeds=feeds,
                    store=store,
                ):
                    shutdown_error = EngineeringSmokeBlocked(
                        "OBSERVATION_SHUTDOWN_INCOMPLETE",
                        "engineering observation shutdown is not proven read-only and complete",
                    )
    elapsed_seconds = max(time.monotonic() - started_at, 0.0)
    if shutdown_error is not None:
        raise shutdown_error
    if run_error is not None:
        if isinstance(run_error, EngineeringSmokeBlocked):
            raise run_error
        raise EngineeringSmokeBlocked(
            "ENGINEERING_OBSERVATION_RUNTIME", "Cerebro observation aborted before completion"
        ) from run_error
    if len(session_binding) != 1:
        raise EngineeringSmokeBlocked(
            "CTP_SESSION_BINDING_MISSING",
            "engineering observation did not bind one public CTP session state",
        )

    shutdown_reader = getattr(broker, "get_shutdown_summary", None)
    shutdown = shutdown_reader() if callable(shutdown_reader) else {"status": "UNPROVEN"}
    strategy = strategies[0] if len(strategies) == 1 else None
    evidence_complete, evidence_status = (
        _engineering_observation_evidence_complete(
            strategy,
            expected_symbols=symbols,
            clock_mapping=trusted_mapping,
        )
        if strategy is not None
        else (False, "STRATEGY_RUNTIME_MISSING")
    )
    write_guard = guarded_api.audit()
    shutdown_complete = _engineering_observation_shutdown_complete(shutdown, store)
    duration_complete = deadline_stop_requested.is_set()
    elapsed_within_maximum = _engineering_observation_elapsed_within_maximum(elapsed_seconds)
    lifecycle_complete = elapsed_within_maximum and not lifecycle_deadline_stop_requested.is_set()
    write_complete = not write_guard["forbidden_write_attempts"]
    complete = (
        duration_complete
        and lifecycle_complete
        and evidence_complete
        and shutdown_complete
        and write_complete
    )
    failure_codes = []
    if not lifecycle_complete:
        failure_codes.append("OBSERVATION_LIFECYCLE_DURATION_EXCEEDED")
    if not duration_complete:
        failure_codes.append("OBSERVATION_DURATION_INCOMPLETE")
    if not evidence_complete:
        failure_codes.append(evidence_status)
    if not shutdown_complete:
        failure_codes.append("OBSERVATION_SHUTDOWN_INCOMPLETE")
    if not write_complete:
        failure_codes.append("FORBIDDEN_WRITE_ATTEMPT")

    strategy_report = strategy.build_report() if strategy is not None else None
    adapter_scoped_write_attempts = sum(write_guard["forbidden_write_attempts"].values())
    if isinstance(strategy_report, Mapping):
        # The strategy report is local to this injected graph.  Preserve its
        # decision evidence but remove its implied raw-provider write count.
        strategy_report = dict(strategy_report)
        strategy_report["adapter_scoped_write_attempts"] = adapter_scoped_write_attempts
        strategy_report["external_trade_writes"] = "NOT_PROVEN"
        strategy_report["external_trade_writes_basis"] = _ADAPTER_SCOPED_WRITE_EVIDENCE_BOUNDARY
    return {
        "status": (
            "PASS_ENGINEERING_STRATEGY_OBSERVATION"
            if complete
            else "INCOMPLETE_ENGINEERING_STRATEGY_OBSERVATION"
        ),
        "mode": "shadow",
        "purpose": "observation",
        "strategy_runtime_mode": config.get("mode"),
        "candidate_id": candidate["candidate_id"],
        "chain": {
            "store": "BtApiStore",
            "feeds": ["BtApiFeed"] * len(feeds),
            "broker": "BtApiBroker",
            "cerebro": "Cerebro",
            "strategy": "CTPOptionsMidFrequencyStrategy",
        },
        "duration": {
            "requested_seconds": duration_seconds,
            "elapsed_seconds": elapsed_seconds,
            "deadline_stop_requested": duration_complete,
            "lifecycle_deadline_stop_requested": lifecycle_deadline_stop_requested.is_set(),
            "elapsed_within_maximum": elapsed_within_maximum,
            "maximum_seconds": ENGINEERING_OBSERVATION_MAX_SECONDS,
        },
        "feed_evidence": {
            "provider_emitted_count": len(emitted_evidence),
            "accepted_complete_three_leg_input": evidence_complete,
            "status": evidence_status,
            "clock_mode": "live",
            "clock_domain": trusted_mapping.clock_domain_id,
            "clock_mapping_id": trusted_mapping.mapping_id,
            "clock_mapping_generation": trusted_mapping.connection_generation,
        },
        "session_binding": session_binding[0],
        "write_guard": write_guard,
        "adapter_scoped_write_attempts": adapter_scoped_write_attempts,
        "external_trade_writes": "NOT_PROVEN",
        "external_trade_writes_basis": _ADAPTER_SCOPED_WRITE_EVIDENCE_BOUNDARY,
        "shutdown": _engineering_observation_shutdown_projection(shutdown),
        "strategy": strategy_report,
        "failure_codes": failure_codes,
        "gates": {
            "G3_first_set_read_only": ENGINEERING_OBSERVATION_G3_STATUS,
            "G3_evaluation": "NOT_APPLICABLE_ENGINEERING_ONLY",
            "G4_simnow_mechanical": "NOT_RUN",
        },
    }


def build_engineering_smoke(
    *, config: Mapping[str, Any], api: Any = None, journal_path: Optional[Path] = None
) -> dict[str, Any]:
    """Build the sole native chain without starting a session or writing orders."""

    if api is None:
        raise EngineeringSmokeBlocked(
            "SDK_NOT_INJECTED", "engineering_smoke requires an explicit API object"
        )
    candidate = config["candidate"]
    symbols = tuple(candidate["contracts"][field] for field in ("future", "call", "put"))
    # Live SimNow is the managed bt_api_py session.  The CTP wrapper is still
    # owned by BtApiStore; no native Trader/MarketData client is constructed
    # here or passed around separately.
    store = BtApiStore(
        provider="btapi", api=api, config={"market_data_only": True}, autostart=False
    )
    feeds = tuple(
        store.getdata(
            dataname=symbol,
            backfill_start=False,
            dispatch_ticks=True,
            dispatch_bars=True,
            live_bars=[],
        )
        for symbol in symbols
    )
    broker = store.getbroker(market_data_only=True, flatten_on_stop=False, cash_check_enabled=True)
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    cerebro.setbroker(broker)
    for feed in feeds:
        cerebro.adddata(feed)
    return {
        "status": "ENGINEERING_SMOKE_BUILT",
        "external_network_requests": 0,
        # Construction neither opens a managed session nor observes a raw SDK
        # request counter, so it cannot certify any external provider-write
        # count even though this local graph has not submitted an order.
        "adapter_scoped_write_attempts": "NOT_OBSERVED",
        "external_trade_writes": "NOT_PROVEN",
        "external_trade_writes_basis": (
            "NOT_PROVEN: an unstarted construction graph cannot attest raw external provider writes."
        ),
        "chain": {
            "store": type(store).__name__,
            "feeds": [type(feed).__name__ for feed in feeds],
            "broker": type(broker).__name__,
            "cerebro": type(cerebro).__name__,
        },
        "symbols": symbols,
        "journal_path": str(journal_path) if journal_path else None,
        "orders_submitted": 0,
        "fills_created": 0,
        "market_data_only": True,
        "execution_permission": "NOT_PROVEN",
    }
